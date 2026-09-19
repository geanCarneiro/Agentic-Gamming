import struct
from time import time_ns

from agentic_gaming.audio_analysis import (
    AudioAnalysisConfig,
    AudioAnalyzer,
    AudioRingBuffer,
    decode_pcm,
)
from agentic_gaming.contracts import AudioChunk


def make_chunk(
    sequence: int,
    payload: bytes,
    *,
    sample_format: str = "pcm_f32le",
    channels: int = 1,
    frame_count: int | None = None,
    started_at_ns: int | None = None,
) -> tuple[AudioChunk, bytes]:
    bytes_per_sample = 4 if sample_format == "pcm_f32le" else 2
    frame_count = frame_count or (len(payload) // bytes_per_sample // channels)
    chunk = AudioChunk(
        stream_id="test-stream",
        chunk_id=f"chunk-{sequence}",
        sequence=sequence,
        started_at_ns=started_at_ns or time_ns(),
        duration_ns=40_000_000,
        sample_rate=1_000,
        channels=channels,
        sample_format=sample_format,
        frame_count=frame_count,
        data_base64="ignored-by-analyzer",
    )
    return chunk, payload


def test_decode_pcm_supports_float_and_signed_16_bit_samples():
    float_payload = struct.pack("<2f", 0.5, -0.25)
    int_payload = struct.pack("<2h", 16384, -8192)

    assert decode_pcm(float_payload, "pcm_f32le") == [0.5, -0.25]
    assert decode_pcm(int_payload, "pcm_s16le") == [0.5, -0.25]


def test_analyzer_warms_baseline_and_creates_anonymous_candidate():
    analyzer = AudioAnalyzer(AudioAnalysisConfig(
        history_seconds=0.2,
        baseline_warmup_seconds=0.08,
        candidate_trigger_relative_loudness_db=6.0,
    ))
    silence = struct.pack("<4f", 0.0, 0.0, 0.0, 0.0)
    loud = struct.pack("<4f", 1.0, 1.0, 1.0, 1.0)

    first = analyzer.analyze(*make_chunk(1, silence))
    second = analyzer.analyze(*make_chunk(2, silence))
    third = analyzer.analyze(*make_chunk(3, loud))

    assert first.measurement.baseline_ready is False
    assert second.measurement.baseline_ready is True
    assert third.measurement.relative_loudness_db is not None
    assert third.measurement.relative_loudness_db >= 6.0
    assert third.candidate is not None
    assert third.candidate.candidate_id.startswith("audio-candidate-")
    assert third.candidate.evidence == ["above_baseline"]


def test_ring_buffer_keeps_only_configured_recent_duration():
    buffer = AudioRingBuffer(max_duration_seconds=0.08)
    payload = struct.pack("<f", 0.0)

    for sequence in range(1, 5):
        chunk, data = make_chunk(sequence, payload, frame_count=1)
        buffer.append(chunk, data)

    assert buffer.chunk_count == 2
    assert buffer.duration_ns == 80_000_000
    assert [item.chunk.sequence for item in buffer.snapshot()] == [3, 4]


def test_latency_snapshot_tracks_deadline_and_percentiles():
    analyzer = AudioAnalyzer(AudioAnalysisConfig(
        history_seconds=1.0,
        baseline_warmup_seconds=0.04,
        decision_budget_ms=200.0,
    ))
    payload = struct.pack("<4f", 0.1, 0.1, 0.1, 0.1)
    result = analyzer.analyze(*make_chunk(1, payload, started_at_ns=time_ns()))
    snapshot = analyzer.snapshot()

    assert result.latency.processing_ms >= 0
    assert result.latency.observation_to_decision_ms >= 0
    assert result.latency.deadline_met is True
    assert snapshot["latency_p50_ms"] is not None
    assert snapshot["latency_p95_ms"] is not None
    assert snapshot["latency_deadline_misses"] == 0


def test_pack_audio_overrides_pipeline_defaults(monkeypatch):
    monkeypatch.setenv("AUDIO_ANALYSIS_DECISION_BUDGET_MS", "250")

    config = AudioAnalysisConfig.from_sources({
        "analysis": {
            "decision_budget_ms": 125,
            "history_seconds": 8,
        }
    })

    assert config.decision_budget_ms == 125
    assert config.history_seconds == 8
