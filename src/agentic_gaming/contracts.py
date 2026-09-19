from __future__ import annotations

from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class SourceMode(StrEnum):
    SIMULATOR = "simulator"
    REPLAY = "replay"
    IMAGE = "image"
    AUDIO = "audio"
    LIVE = "live"


class InformationOrigin(StrEnum):
    OBSERVED_NOW = "observed_now"
    OBSERVED_MEMORY = "observed_memory"
    TECHNICAL_KNOWLEDGE = "technical_knowledge"
    INFERENCE = "inference"
    GROUND_TRUTH = "ground_truth"


class Urgency(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class ActionStatus(StrEnum):
    PLANNED = "planned"
    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    DRY_RUN = "dry_run"


class MotorStepType(StrEnum):
    KEY_DOWN = "key_down"
    KEY_UP = "key_up"
    MOUSE_MOVE = "mouse_move"
    MOUSE_BUTTON_DOWN = "mouse_button_down"
    MOUSE_BUTTON_UP = "mouse_button_up"
    WAIT = "wait"


class VisionEntity(StrictModel):
    id: str
    kind: str
    state: str | None = None
    confidence: float = Field(ge=0, le=1)
    bbox: tuple[float, float, float, float] | None = None
    properties: dict[str, Any] = Field(default_factory=dict)
    origin: InformationOrigin = InformationOrigin.OBSERVED_NOW


class VisionState(StrictModel):
    frame_id: str = Field(default_factory=lambda: str(uuid4()))
    captured_at_ns: int = Field(ge=0)
    scene: str | None = None
    confidence: float = Field(ge=0, le=1)
    entities: list[VisionEntity] = Field(default_factory=list)
    changed: list[str] = Field(default_factory=list)
    raw_frame_ref: str | None = None
    annotated_frame_ref: str | None = None


class AudioChunk(StrictModel):
    type: str = "audio_chunk"
    stream_id: str
    chunk_id: str
    sequence: int = Field(ge=1)
    started_at_ns: int = Field(ge=0)
    duration_ns: int = Field(gt=0)
    sample_rate: int = Field(gt=0)
    channels: int = Field(gt=0, le=32)
    sample_format: str
    frame_count: int = Field(gt=0)
    data_base64: str
    device_id: str | None = None
    device_name: str | None = None
    source_process_id: int | None = Field(default=None, gt=0)
    source_process_name: str | None = None
    capture_packets_dropped: int = Field(default=0, ge=0)


class AudioEvent(StrictModel):
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    started_at_ns: int = Field(ge=0)
    ended_at_ns: int | None = Field(default=None, ge=0)
    event_type: str
    confidence: float = Field(ge=0, le=1)
    direction: str | None = None
    distance_hypothesis: str | None = None
    relative_loudness_db: float | None = None
    loudness_percentile: float | None = Field(default=None, ge=0, le=1)
    evidence: list[str] = Field(default_factory=list)
    origin: InformationOrigin = InformationOrigin.OBSERVED_NOW


class ObservedFact(StrictModel):
    key: str
    value: Any
    confidence: float = Field(ge=0, le=1)
    observed_at_ns: int = Field(ge=0)
    origin: InformationOrigin


class ActiveAction(StrictModel):
    execution_id: str
    motor_program: str
    status: ActionStatus
    current_step: int = Field(ge=0)
    started_at_ns: int = Field(ge=0)


class WorldState(StrictModel):
    run_id: UUID
    version: int = Field(ge=0)
    updated_at_ns: int = Field(ge=0)
    scene: str | None = None
    facts: dict[str, ObservedFact] = Field(default_factory=dict)
    event_queue: list[AudioEvent] = Field(default_factory=list)
    active_action: ActiveAction | None = None
    recent_deltas: list[str] = Field(default_factory=list)


class MotorStep(StrictModel):
    type: MotorStepType
    value: str | int | float | tuple[float, float] | None = None
    duration_ms: int = Field(default=0, ge=0)


class MotorProgram(StrictModel):
    id: str
    version: str
    description: str
    steps: list[MotorStep] = Field(min_length=1)
    preconditions: dict[str, Any] = Field(default_factory=dict)
    cancellable_after_step: int | None = Field(default=None, ge=0)
    timeout_ms: int = Field(gt=0)
    failure_action: str | None = None


class ActionSpec(StrictModel):
    id: str
    intent: str
    description: str
    motor_program: str
    risk: str = "normal"


class AgentDecision(StrictModel):
    decision_id: str = Field(default_factory=lambda: str(uuid4()))
    intent: str
    target: str | None = None
    urgency: Urgency = Urgency.NORMAL
    confidence: float = Field(ge=0, le=1)
    reason_code: str
    motor_program: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    based_on_state_version: int = Field(ge=0)
    expires_after_state_version: int | None = Field(default=None, ge=0)


class MotorExecution(StrictModel):
    execution_id: str = Field(default_factory=lambda: str(uuid4()))
    motor_program: str
    status: ActionStatus
    dry_run: bool
    executed_steps: int = Field(ge=0)
    message: str


class EventEnvelope(StrictModel):
    schema_version: str = "1.0"
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    run_id: UUID
    source: str
    sequence: int = Field(ge=0)
    source_timestamp_ns: int = Field(ge=0)
    ingest_timestamp_ns: int = Field(ge=0)
    world_state_version: int | None = Field(default=None, ge=0)
    correlation_id: str | None = None
    event_type: str
    payload: dict[str, Any] = Field(default_factory=dict)


class CreateRunRequest(StrictModel):
    game_pack_id: str = "fnaf1"
    source_mode: SourceMode = SourceMode.SIMULATOR
    dry_run: bool = True


class RunInfo(StrictModel):
    run_id: UUID
    game_pack_id: str
    source_mode: SourceMode
    dry_run: bool
    status: str
