from __future__ import annotations

import math
import os
import struct
from collections import deque
from dataclasses import dataclass
from time import monotonic_ns, time_ns
from uuid import uuid4

from pydantic import Field

from .contracts import AudioCandidate, AudioChunk, AudioMeasurement, LatencyTrace, StrictModel


class AudioAnalysisConfig(StrictModel):
    history_seconds: float = Field(default=5.0, gt=0)
    baseline_warmup_seconds: float = Field(default=3.0, gt=0)
    baseline_percentile: float = Field(default=0.2, ge=0, le=1)
    candidate_trigger_relative_loudness_db: float = Field(default=6.0, ge=0)
    silence_floor_dbfs: float = Field(default=-80.0, le=0)
    decision_budget_ms: float = Field(default=200.0, gt=0)
    latency_history_size: int = Field(default=200, gt=0)

    @classmethod
    def from_sources(cls, audio_config: dict | None = None) -> AudioAnalysisConfig:
        values: dict[str, object] = {}
        environment_names = {
            "history_seconds": "AUDIO_ANALYSIS_HISTORY_SECONDS",
            "baseline_warmup_seconds": "AUDIO_ANALYSIS_BASELINE_WARMUP_SECONDS",
            "baseline_percentile": "AUDIO_ANALYSIS_BASELINE_PERCENTILE",
            "candidate_trigger_relative_loudness_db": (
                "AUDIO_ANALYSIS_CANDIDATE_TRIGGER_RELATIVE_LOUDNESS_DB"
            ),
            "silence_floor_dbfs": "AUDIO_ANALYSIS_SILENCE_FLOOR_DBFS",
            "decision_budget_ms": "AUDIO_ANALYSIS_DECISION_BUDGET_MS",
            "latency_history_size": "AUDIO_ANALYSIS_LATENCY_HISTORY_SIZE",
        }
        for field_name, environment_name in environment_names.items():
            value = os.getenv(environment_name)
            if value is not None:
                values[field_name] = value

        pack_analysis = (audio_config or {}).get("analysis", {})
        if isinstance(pack_analysis, dict):
            values.update(pack_analysis)
        return cls.model_validate(values)


@dataclass(frozen=True)
class BufferedAudioChunk:
    chunk: AudioChunk
    pcm_bytes: bytes


class AudioRingBuffer:
    def __init__(self, max_duration_seconds: float):
        self.max_duration_ns = int(max_duration_seconds * 1_000_000_000)
        self._chunks: deque[BufferedAudioChunk] = deque()
        self._duration_ns = 0

    def append(self, chunk: AudioChunk, pcm_bytes: bytes) -> None:
        self._chunks.append(BufferedAudioChunk(chunk, pcm_bytes))
        self._duration_ns += chunk.duration_ns
        while len(self._chunks) > 1 and self._duration_ns > self.max_duration_ns:
            removed = self._chunks.popleft()
            self._duration_ns -= removed.chunk.duration_ns

    @property
    def duration_ns(self) -> int:
        return self._duration_ns

    @property
    def chunk_count(self) -> int:
        return len(self._chunks)

    def snapshot(self) -> tuple[BufferedAudioChunk, ...]:
        return tuple(self._chunks)


@dataclass(frozen=True)
class AudioAnalysisResult:
    measurement: AudioMeasurement
    candidate: AudioCandidate | None
    latency: LatencyTrace


class AudioAnalyzer:
    def __init__(self, config: AudioAnalysisConfig | None = None):
        self.config = config or AudioAnalysisConfig()
        self.buffer = AudioRingBuffer(self.config.history_seconds)
        self._loudness_history: deque[tuple[int, float]] = deque()
        self._loudness_history_duration_ns = 0
        self._active_candidate: AudioCandidate | None = None
        self._latencies: deque[LatencyTrace] = deque(maxlen=self.config.latency_history_size)
        self._deadline_misses = 0

    def analyze(
        self,
        chunk: AudioChunk,
        pcm_bytes: bytes,
        received_at_ns: int | None = None,
    ) -> AudioAnalysisResult:
        received_at_ns = received_at_ns or time_ns()
        trace_id = f"audio-trace-{uuid4().hex}"
        stages: dict[str, float] = {}
        processing_started = monotonic_ns()

        decode_started = monotonic_ns()
        values = decode_pcm(pcm_bytes, chunk.sample_format)
        expected_samples = chunk.frame_count * chunk.channels
        if len(values) != expected_samples:
            raise ValueError(
                f"PCM sample count does not match chunk: expected {expected_samples}, "
                f"received {len(values)}"
            )
        stages["pcm_decode"] = elapsed_ms(decode_started)

        measurement_started = monotonic_ns()
        measurement = self._measure(chunk, values)
        stages["acoustic_measurement"] = elapsed_ms(measurement_started)

        buffer_started = monotonic_ns()
        self.buffer.append(chunk, pcm_bytes)
        baseline_dbfs, relative_db, percentile, baseline_ready = self._update_history(
            chunk.duration_ns,
            measurement.dbfs,
        )
        measurement = measurement.model_copy(update={
            "baseline_dbfs": baseline_dbfs,
            "relative_loudness_db": relative_db,
            "loudness_percentile": percentile,
            "baseline_ready": baseline_ready,
        })
        stages["history_and_buffer"] = elapsed_ms(buffer_started)

        candidate_started = monotonic_ns()
        candidate = self._update_candidate(chunk, relative_db, baseline_ready)
        stages["candidate_generation"] = elapsed_ms(candidate_started)

        processing_ms = elapsed_ms(processing_started)
        observation_to_decision_ms = max(
            0.0,
            (time_ns() - chunk.started_at_ns) / 1_000_000,
        )
        latency = LatencyTrace(
            trace_id=trace_id,
            stream_id=chunk.stream_id,
            chunk_id=chunk.chunk_id,
            sequence=chunk.sequence,
            observed_at_ns=chunk.started_at_ns,
            received_at_ns=received_at_ns,
            stages_ms=stages,
            capture_to_core_ms=max(0.0, (received_at_ns - chunk.started_at_ns) / 1_000_000),
            processing_ms=processing_ms,
            observation_to_decision_ms=observation_to_decision_ms,
            decision_budget_ms=self.config.decision_budget_ms,
            deadline_met=observation_to_decision_ms <= self.config.decision_budget_ms,
        )
        self._latencies.append(latency)
        if not latency.deadline_met:
            self._deadline_misses += 1

        return AudioAnalysisResult(measurement, candidate, latency)

    def snapshot(self) -> dict[str, object]:
        latest = self._latencies[-1] if self._latencies else None
        durations = [item.observation_to_decision_ms for item in self._latencies]
        return {
            "status": "READY" if self._is_baseline_ready() else "WARMING",
            "config": self.config.model_dump(),
            "baseline_ready": self._is_baseline_ready(),
            "buffer_chunks": self.buffer.chunk_count,
            "buffer_duration_ms": round(self.buffer.duration_ns / 1_000_000, 2),
            "last_latency_ms": latest.observation_to_decision_ms if latest else None,
            "latency_p50_ms": percentile(durations, 0.50),
            "latency_p95_ms": percentile(durations, 0.95),
            "latency_p99_ms": percentile(durations, 0.99),
            "latency_max_ms": max(durations) if durations else None,
            "latency_deadline_ms": self.config.decision_budget_ms,
            "latency_deadline_misses": self._deadline_misses,
            "last_trace_id": latest.trace_id if latest else None,
        }

    def _measure(self, chunk: AudioChunk, values: list[float]) -> AudioMeasurement:
        channel_squares = [0.0] * chunk.channels
        channel_peaks = [0.0] * chunk.channels
        total_square = 0.0
        peak = 0.0
        for index, value in enumerate(values):
            if not math.isfinite(value):
                raise ValueError("PCM samples must be finite")
            absolute = abs(value)
            channel = index % chunk.channels
            channel_squares[channel] += value * value
            channel_peaks[channel] = max(channel_peaks[channel], absolute)
            total_square += value * value
            peak = max(peak, absolute)

        channel_rms = [math.sqrt(square / chunk.frame_count) for square in channel_squares]
        rms = math.sqrt(total_square / len(values))
        dbfs = max(
            self.config.silence_floor_dbfs,
            20 * math.log10(max(rms, 10 ** (self.config.silence_floor_dbfs / 20))),
        )
        return AudioMeasurement(
            stream_id=chunk.stream_id,
            chunk_id=chunk.chunk_id,
            sequence=chunk.sequence,
            started_at_ns=chunk.started_at_ns,
            ended_at_ns=chunk.started_at_ns + chunk.duration_ns,
            sample_rate=chunk.sample_rate,
            channels=chunk.channels,
            sample_format=chunk.sample_format,
            sample_count=len(values),
            rms=rms,
            peak=peak,
            channel_rms=channel_rms,
            channel_peak=channel_peaks,
            dbfs=dbfs,
            baseline_ready=False,
        )

    def _update_history(
        self,
        duration_ns: int,
        dbfs: float,
    ) -> tuple[float | None, float | None, float | None, bool]:
        self._loudness_history.append((duration_ns, dbfs))
        self._loudness_history_duration_ns += duration_ns
        while (
            len(self._loudness_history) > 1
            and self._loudness_history_duration_ns
            > int(self.config.history_seconds * 1_000_000_000)
        ):
            removed_duration, _ = self._loudness_history.popleft()
            self._loudness_history_duration_ns -= removed_duration

        values = [item[1] for item in self._loudness_history]
        baseline = quantile(values, self.config.baseline_percentile)
        ready = self._is_baseline_ready()
        relative = dbfs - baseline if ready else None
        rank = sum(value <= dbfs for value in values) / len(values)
        return baseline, relative, rank, ready

    def _is_baseline_ready(self) -> bool:
        return self._loudness_history_duration_ns >= int(
            self.config.baseline_warmup_seconds * 1_000_000_000
        )

    def _update_candidate(
        self,
        chunk: AudioChunk,
        relative_db: float | None,
        baseline_ready: bool,
    ) -> AudioCandidate | None:
        is_candidate = (
            baseline_ready
            and relative_db is not None
            and relative_db >= self.config.candidate_trigger_relative_loudness_db
        )
        if not is_candidate:
            self._active_candidate = None
            return None

        if self._active_candidate is None:
            candidate_id = f"audio-candidate-{uuid4().hex}"
            self._active_candidate = AudioCandidate(
                candidate_id=candidate_id,
                stream_id=chunk.stream_id,
                started_at_ns=chunk.started_at_ns,
                ended_at_ns=chunk.started_at_ns + chunk.duration_ns,
                first_sequence=chunk.sequence,
                last_sequence=chunk.sequence,
                salience=min(1.0, relative_db / max(
                    self.config.candidate_trigger_relative_loudness_db * 2,
                    1.0,
                )),
                evidence=["above_baseline"],
            )
        else:
            self._active_candidate = self._active_candidate.model_copy(update={
                "ended_at_ns": chunk.started_at_ns + chunk.duration_ns,
                "last_sequence": chunk.sequence,
                "salience": min(
                    1.0,
                    max(
                        self._active_candidate.salience,
                        relative_db / max(
                            self.config.candidate_trigger_relative_loudness_db * 2,
                            1.0,
                        ),
                    ),
                ),
            })
        return self._active_candidate


def decode_pcm(pcm_bytes: bytes, sample_format: str) -> list[float]:
    if sample_format == "pcm_f32le":
        if len(pcm_bytes) % 4:
            raise ValueError("pcm_f32le byte length must be divisible by 4")
        return list(struct.unpack(f"<{len(pcm_bytes) // 4}f", pcm_bytes))
    if sample_format == "pcm_s16le":
        if len(pcm_bytes) % 2:
            raise ValueError("pcm_s16le byte length must be divisible by 2")
        return [sample / 32768.0 for (sample,) in struct.iter_unpack("<h", pcm_bytes)]
    raise ValueError(f"Unsupported audio sample format: {sample_format}")


def elapsed_ms(started_at_ns: int) -> float:
    return round((monotonic_ns() - started_at_ns) / 1_000_000, 4)


def quantile(values: list[float], probability: float) -> float:
    if not values:
        raise ValueError("quantile requires at least one value")
    ordered = sorted(values)
    index = min(len(ordered) - 1, round((len(ordered) - 1) * probability))
    return ordered[index]


def percentile(values: list[float], probability: float) -> float | None:
    if not values:
        return None
    return round(quantile(values, probability), 4)
