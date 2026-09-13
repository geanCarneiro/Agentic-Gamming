from __future__ import annotations

from .contracts import ActionStatus, MotorExecution
from .gamepacks import GamePack


class MotorExecutor:
    def __init__(self, game_pack: GamePack):
        self.game_pack = game_pack

    def validate(self, program_id: str) -> None:
        program = self.game_pack.program(program_id)
        if not program.steps:
            raise ValueError(f"Motor program '{program_id}' has no steps")
        for step in program.steps:
            if step.duration_ms < 0:
                raise ValueError(f"Motor program '{program_id}' contains a negative duration")

    async def execute(self, program_id: str, dry_run: bool = True) -> MotorExecution:
        self.validate(program_id)
        program = self.game_pack.program(program_id)
        status = ActionStatus.DRY_RUN if dry_run else ActionStatus.COMPLETED
        message = (
            "Validated only; no host input was sent"
            if dry_run
            else "Core execution completed"
        )
        return MotorExecution(
            motor_program=program.id,
            status=status,
            dry_run=dry_run,
            executed_steps=len(program.steps),
            message=message,
        )
