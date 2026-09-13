from __future__ import annotations

import base64
import binascii
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic_ns, time_ns
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .agent import DeterministicGateway
from .contracts import (
    AgentDecision,
    AudioEvent,
    CreateRunRequest,
    EventEnvelope,
    MotorExecution,
    RunInfo,
    SourceMode,
    VisionState,
    WorldState,
)
from .event_bus import InMemoryEventBus, NatsEventBus
from .gamepacks import GamePack, GamePackRegistry
from .logging_setup import configure_logging, read_logs
from .motor import MotorExecutor
from .world_state import WorldStateStore

logger = logging.getLogger("agentic_gaming.core")


class RunSession:
    def __init__(
        self,
        run_id: UUID,
        game_pack: GamePack,
        source_mode: SourceMode,
        dry_run: bool,
        bus,
    ):
        self.info = RunInfo(
            run_id=run_id,
            game_pack_id=game_pack.id,
            source_mode=source_mode,
            dry_run=dry_run,
            status="RUNNING",
        )
        self.game_pack = game_pack
        self.state_store = WorldStateStore(run_id)
        self.agent = DeterministicGateway()
        self.executor = MotorExecutor(game_pack)
        self.bus = bus
        self.sequence = 0

    @property
    def state(self) -> WorldState:
        return self.state_store.state

    async def emit(self, event_type: str, payload: dict, timestamp_ns: int | None = None) -> None:
        self.sequence += 1
        event = EventEnvelope(
            run_id=self.info.run_id,
            source="core",
            sequence=self.sequence,
            source_timestamp_ns=timestamp_ns or monotonic_ns(),
            ingest_timestamp_ns=monotonic_ns(),
            world_state_version=self.state.version,
            event_type=event_type,
            payload=payload,
        )
        await self.bus.publish(event)


def create_app() -> FastAPI:
    app = FastAPI(title="Agentic Gaming Core", version="0.1.0")
    app.mount("/static", StaticFiles(directory="web"), name="static")

    @app.on_event("startup")
    async def startup() -> None:
        log_path = configure_logging()
        packs_dir = Path(os.getenv("GAME_PACKS_DIR", "game-packs"))
        registry = GamePackRegistry(packs_dir)
        registry.load()
        backend = os.getenv("EVENT_BUS_BACKEND", "memory")
        if backend == "nats":
            bus = NatsEventBus(os.getenv("NATS_URL", "nats://localhost:4222"))
            await bus.connect()
        else:
            bus = InMemoryEventBus()
        app.state.registry = registry
        app.state.bus = bus
        app.state.runs = {}
        app.state.log_path = log_path
        app.state.bridge = {
            "status": "DISCONNECTED",
            "connected_at": None,
            "disconnected_at": None,
            "client_id": None,
            "protocol_version": None,
            "profile_id": None,
            "window_title": None,
            "process_id": None,
            "capabilities": [],
            "dry_run": None,
            "safe_capture": None,
            "frames_received": 0,
            "last_frame_id": None,
            "last_frame_width": None,
            "last_frame_height": None,
            "last_frame_bytes": None,
            "last_frame_received_at": None,
            "last_frame_age_ms": None,
            "last_message_type": None,
            "last_error": None,
            "_last_frame_received_at_ns": None,
        }
        app.state.bridge_events = []
        logger.info("core_started", extra={"event_type": "core.started"})

    @app.on_event("shutdown")
    async def shutdown() -> None:
        bus = getattr(app.state, "bus", None)
        if isinstance(bus, NatsEventBus):
            await bus.close()

    def get_run(run_id: UUID) -> RunSession:
        try:
            return app.state.runs[run_id]
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Run not found") from exc

    def record_bridge_event(event_type: str, payload: dict) -> None:
        app.state.bridge_events.append({
            "timestamp": datetime.now(UTC).isoformat(),
            "event_type": event_type,
            "payload": payload,
        })
        del app.state.bridge_events[:-100]

    def update_bridge_status(**changes) -> None:
        app.state.bridge.update(changes)

    @app.get("/", include_in_schema=False)
    async def index():
        return FileResponse("web/index.html")

    @app.get("/health")
    async def health():
        return {
            "status": "UP",
            "event_bus": type(app.state.bus).__name__,
            "inference_device": os.getenv("INFERENCE_DEVICE", "auto"),
            "game_packs": len(app.state.registry.summaries()),
        }

    @app.get("/api/bridge/status")
    async def bridge_status():
        status = dict(app.state.bridge)
        received_at_ns = status.pop("_last_frame_received_at_ns", None)
        if received_at_ns is not None:
            status["last_frame_age_ms"] = round(max(0, time_ns() - received_at_ns) / 1_000_000, 1)
        return status

    @app.get("/api/bridge/events")
    async def bridge_events(limit: int = 50):
        bounded_limit = min(max(limit, 1), 100)
        return list(reversed(app.state.bridge_events[-bounded_limit:]))

    @app.get("/api/bridge/latest-frame", include_in_schema=False)
    async def latest_bridge_frame():
        frame_path = Path(os.getenv("BRIDGE_ARTIFACTS_DIR", "data/bridge")) / "latest.png"
        if not frame_path.exists():
            raise HTTPException(status_code=404, detail="No bridge frame has been received")
        return FileResponse(
            frame_path,
            media_type="image/png",
            filename="latest.png",
            content_disposition_type="inline",
        )

    @app.websocket("/ws/host-bridge")
    async def host_bridge(websocket: WebSocket):
        expected_token = os.getenv("HOST_BRIDGE_TOKEN", "dev-only-change-me")
        received_token = websocket.headers.get("x-bridge-token")
        if received_token != expected_token:
            await websocket.close(code=1008, reason="invalid bridge token")
            return

        await websocket.accept()
        bridge_dir = Path(os.getenv("BRIDGE_ARTIFACTS_DIR", "data/bridge"))
        bridge_dir.mkdir(parents=True, exist_ok=True)
        connected_at = datetime.now(UTC).isoformat()
        update_bridge_status(
            status="CONNECTED",
            connected_at=connected_at,
            disconnected_at=None,
            last_error=None,
            last_message_type="connected",
        )
        record_bridge_event("bridge.connected", {})
        logger.info("host_bridge_connected", extra={"event_type": "bridge.connected"})
        try:
            while True:
                message = await websocket.receive_json()
                message_type = message.get("type")
                if message_type == "hello":
                    update_bridge_status(
                        client_id=message.get("client_id"),
                        protocol_version=message.get("protocol_version"),
                        profile_id=message.get("profile_id"),
                        capabilities=message.get("capabilities") or [],
                        dry_run=message.get("dry_run"),
                        safe_capture=message.get("safe_capture"),
                        last_message_type="hello",
                        last_error=None,
                    )
                    record_bridge_event("bridge.hello", {
                        "client_id": message.get("client_id"),
                        "protocol_version": message.get("protocol_version"),
                        "profile_id": message.get("profile_id"),
                        "safe_capture": message.get("safe_capture"),
                    })
                    await websocket.send_json({
                        "type": "hello_ack",
                        "protocol_version": "1.0",
                        "server": "agentic-gaming-core",
                        "accepted": True,
                    })
                    logger.info("host_bridge_hello", extra={
                        "event_type": "bridge.hello",
                        "client_id": message.get("client_id"),
                    })
                elif message_type == "frame":
                    frame_id = str(message.get("frame_id", "unknown"))
                    encoded = message.get("data_base64")
                    if not isinstance(encoded, str):
                        update_bridge_status(
                            last_message_type="frame",
                            last_error="FRAME_DATA_MISSING",
                        )
                        record_bridge_event("bridge.error", {"code": "FRAME_DATA_MISSING"})
                        await websocket.send_json({
                            "type": "error",
                            "code": "FRAME_DATA_MISSING",
                            "message": "frame.data_base64 must be a string",
                        })
                        continue
                    try:
                        frame_bytes = base64.b64decode(encoded, validate=True)
                    except (ValueError, binascii.Error):
                        update_bridge_status(
                            last_message_type="frame",
                            last_error="FRAME_DATA_INVALID",
                        )
                        record_bridge_event("bridge.error", {"code": "FRAME_DATA_INVALID"})
                        await websocket.send_json({
                            "type": "error",
                            "code": "FRAME_DATA_INVALID",
                            "message": "frame.data_base64 is not valid base64",
                        })
                        continue
                    frame_path = bridge_dir / "latest.png"
                    frame_path.write_bytes(frame_bytes)
                    received_at_ns = time_ns()
                    captured_at_ns = message.get("captured_at_ns")
                    try:
                        frame_age_ms = round(
                            max(0, received_at_ns - int(captured_at_ns)) / 1_000_000,
                            1,
                        )
                    except (TypeError, ValueError):
                        frame_age_ms = None
                    source_process_id = message.get("source_process_id")
                    update_bridge_status(
                        status="CONNECTED",
                        frames_received=app.state.bridge["frames_received"] + 1,
                        last_frame_id=frame_id,
                        last_frame_width=message.get("width"),
                        last_frame_height=message.get("height"),
                        last_frame_bytes=len(frame_bytes),
                        last_frame_received_at=datetime.fromtimestamp(
                            received_at_ns / 1_000_000_000, UTC
                        ).isoformat(),
                        last_frame_age_ms=frame_age_ms,
                        last_message_type="frame",
                        last_error=None,
                        _last_frame_received_at_ns=received_at_ns,
                        window_title=(
                            message.get("source_window_title")
                            if message.get("source_window_title") is not None
                            else app.state.bridge["window_title"]
                        ),
                        process_id=(
                            source_process_id
                            if source_process_id is not None
                            else app.state.bridge["process_id"]
                        ),
                    )
                    record_bridge_event("bridge.frame.received", {
                        "frame_id": frame_id,
                        "bytes": len(frame_bytes),
                        "width": message.get("width"),
                        "height": message.get("height"),
                        "window_title": message.get("source_window_title"),
                    })
                    await websocket.send_json({
                        "type": "frame_ack",
                        "frame_id": frame_id,
                        "stored_path": str(frame_path),
                        "bytes": len(frame_bytes),
                    })
                    logger.info("host_bridge_frame", extra={
                        "event_type": "bridge.frame.received",
                        "frame_id": frame_id,
                        "bytes": len(frame_bytes),
                    })
                elif message_type == "heartbeat":
                    update_bridge_status(last_message_type="heartbeat")
                    await websocket.send_json({
                        "type": "heartbeat_ack",
                        "received_at_ns": monotonic_ns(),
                    })
                else:
                    code = "MESSAGE_TYPE_UNSUPPORTED"
                    update_bridge_status(last_message_type=message_type, last_error=code)
                    record_bridge_event("bridge.error", {
                        "code": code,
                        "message_type": message_type,
                    })
                    await websocket.send_json({
                        "type": "error",
                        "code": "MESSAGE_TYPE_UNSUPPORTED",
                        "message": f"Unsupported bridge message type: {message_type}",
                    })
        except WebSocketDisconnect:
            disconnected_at = datetime.now(UTC).isoformat()
            update_bridge_status(
                status="DISCONNECTED",
                disconnected_at=disconnected_at,
                last_message_type="disconnected",
            )
            record_bridge_event("bridge.disconnected", {})
            logger.info("host_bridge_disconnected", extra={"event_type": "bridge.disconnected"})

    @app.get("/api/game-packs")
    async def game_packs():
        return app.state.registry.summaries()

    @app.post("/api/runs", response_model=RunInfo)
    async def create_run(request: CreateRunRequest):
        try:
            pack = app.state.registry.get(request.game_pack_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        run_id = uuid4()
        session = RunSession(run_id, pack, request.source_mode, request.dry_run, app.state.bus)
        app.state.runs[run_id] = session
        await session.emit("run.started", session.info.model_dump())
        logger.info(
            "run_created",
            extra={"run_id": run_id, "event_type": "run.started", "state_version": 0},
        )
        return session.info

    @app.get("/api/runs", response_model=list[RunInfo])
    async def runs():
        return [session.info for session in app.state.runs.values()]

    @app.get("/api/runs/{run_id}/state", response_model=WorldState)
    async def state(run_id: UUID):
        return get_run(run_id).state

    @app.post("/api/runs/{run_id}/vision", response_model=WorldState)
    async def ingest_vision(run_id: UUID, vision: VisionState):
        session = get_run(run_id)
        state = session.state_store.ingest_vision(vision)
        await session.emit("perception.vision.state", vision.model_dump(), vision.captured_at_ns)
        logger.info(
            "vision_ingested",
            extra={
                "run_id": run_id,
                "event_type": "perception.vision.state",
                "state_version": state.version,
            },
        )
        return state

    @app.post("/api/runs/{run_id}/audio", response_model=WorldState)
    async def ingest_audio(run_id: UUID, event: AudioEvent):
        session = get_run(run_id)
        state = session.state_store.ingest_audio(event)
        await session.emit("perception.audio.event", event.model_dump(), event.started_at_ns)
        logger.info(
            "audio_ingested",
            extra={
                "run_id": run_id,
                "event_type": "perception.audio.event",
                "state_version": state.version,
            },
        )
        return state

    @app.post("/api/runs/{run_id}/decide", response_model=AgentDecision)
    async def decide(run_id: UUID):
        session = get_run(run_id)
        decision = await session.agent.decide(session.state, session.game_pack)
        await session.emit("agent.decision.created", decision.model_dump())
        logger.info(
            "decision_created",
            extra={
                "run_id": run_id,
                "event_type": "agent.decision.created",
                "state_version": decision.based_on_state_version,
                "motor_program": decision.motor_program,
            },
        )
        return decision

    @app.post("/api/runs/{run_id}/execute/{program_id}", response_model=MotorExecution)
    async def execute(run_id: UUID, program_id: str):
        session = get_run(run_id)
        execution = await session.executor.execute(program_id, dry_run=session.info.dry_run)
        await session.emit("motor.program.completed", execution.model_dump())
        logger.info(
            "motor_program_validated",
            extra={
                "run_id": run_id,
                "event_type": "motor.program.completed",
                "motor_program": program_id,
            },
        )
        return execution

    @app.get("/api/runs/{run_id}/logs")
    async def logs(run_id: UUID, limit: int = 100):
        get_run(run_id)
        return read_logs(app.state.log_path, str(run_id), min(max(limit, 1), 500))

    return app


app = create_app()


def run() -> None:
    import uvicorn

    uvicorn.run("agentic_gaming.main:app", host="0.0.0.0", port=8000, reload=False)
