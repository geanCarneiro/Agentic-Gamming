from time import monotonic_ns
from uuid import uuid4

import pytest

from agentic_gaming.agent import DeterministicGateway
from agentic_gaming.contracts import AudioEvent, VisionEntity, VisionState
from agentic_gaming.gamepacks import GamePackRegistry
from agentic_gaming.motor import MotorExecutor
from agentic_gaming.world_state import WorldStateStore


@pytest.fixture
def fnaf1():
    registry = GamePackRegistry(__import__("pathlib").Path("game-packs"))
    registry.load()
    return registry.get("fnaf1")


@pytest.mark.asyncio
async def test_alpha_pipeline_keeps_external_game_pack_and_produces_decision(fnaf1):
    store = WorldStateStore(uuid4())
    state = store.ingest_vision(
        VisionState(
            captured_at_ns=monotonic_ns(),
            scene="office",
            confidence=0.9,
            entities=[VisionEntity(id="left_door", kind="door", state="closed", confidence=0.8)],
        )
    )
    store.ingest_audio(
        AudioEvent(started_at_ns=monotonic_ns(), event_type="footstep", confidence=0.7)
    )

    decision = await DeterministicGateway().decide(store.state, fnaf1)

    assert state.version == 1
    assert store.state.version == 2
    assert decision.motor_program == "OPEN_CAMERA_PANEL"
    assert decision.based_on_state_version == 2


@pytest.mark.asyncio
async def test_motor_executor_is_dry_run_by_default(fnaf1):
    execution = await MotorExecutor(fnaf1).execute("OPEN_CAMERA_PANEL", dry_run=True)

    assert execution.dry_run is True
    assert execution.status.value == "dry_run"
    assert execution.executed_steps == 3


def test_game_pack_rejects_unknown_program(fnaf1):
    with pytest.raises(KeyError):
        fnaf1.program("DOES_NOT_EXIST")
