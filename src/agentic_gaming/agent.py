from __future__ import annotations

from typing import Protocol

from .contracts import AgentDecision, Urgency, WorldState
from .gamepacks import GamePack


class ModelGateway(Protocol):
    async def decide(self, state: WorldState, game_pack: GamePack) -> AgentDecision: ...


class DeterministicGateway:
    """Temporary gateway for Alpha; it makes the whole pipeline executable without an LLM."""

    async def decide(self, state: WorldState, game_pack: GamePack) -> AgentDecision:
        action_id = game_pack.manifest.default_action
        if action_id is None:
            action_id = next(iter(game_pack.actions), None)
        if action_id is None:
            raise RuntimeError(f"Game pack '{game_pack.id}' has no actions")

        action = game_pack.action(action_id)
        return AgentDecision(
            intent=action.intent,
            target=None,
            urgency=Urgency.NORMAL,
            confidence=0.5,
            reason_code="DETERMINISTIC_ALPHA_POLICY",
            motor_program=action.motor_program,
            based_on_state_version=state.version,
            expires_after_state_version=state.version + 1,
        )
