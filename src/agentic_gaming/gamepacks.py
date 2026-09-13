from __future__ import annotations

import json
from pathlib import Path

from pydantic import Field

from .contracts import ActionSpec, MotorProgram, StrictModel


class GamePackManifest(StrictModel):
    id: str
    version: str
    display_name: str
    description: str
    default_action: str | None = None
    ontology: dict[str, list[str]] = Field(default_factory=dict)
    vision: dict = Field(default_factory=dict)
    audio: dict = Field(default_factory=dict)
    knowledge: list[str] = Field(default_factory=list)
    actions_file: str = "actions.json"


class GamePack:
    def __init__(
        self,
        root: Path,
        manifest: GamePackManifest,
        actions: list[ActionSpec],
        programs: list[MotorProgram],
    ):
        self.root = root
        self.manifest = manifest
        self.actions = {action.id: action for action in actions}
        self.programs = {program.id: program for program in programs}

    @property
    def id(self) -> str:
        return self.manifest.id

    def action(self, action_id: str) -> ActionSpec:
        try:
            return self.actions[action_id]
        except KeyError as exc:
            raise KeyError(f"Unknown action '{action_id}' in game pack '{self.id}'") from exc

    def program(self, program_id: str) -> MotorProgram:
        try:
            return self.programs[program_id]
        except KeyError as exc:
            raise KeyError(
                f"Unknown motor program '{program_id}' in game pack '{self.id}'"
            ) from exc

    def summary(self) -> dict:
        return {
            "id": self.manifest.id,
            "version": self.manifest.version,
            "display_name": self.manifest.display_name,
            "description": self.manifest.description,
            "ontology": self.manifest.ontology,
            "vision": self.manifest.vision,
            "audio": self.manifest.audio,
            "actions": [action.model_dump() for action in self.actions.values()],
            "programs": [program.model_dump() for program in self.programs.values()],
        }


class GamePackRegistry:
    def __init__(self, root: Path):
        self.root = root
        self._packs: dict[str, GamePack] = {}

    def load(self) -> None:
        self._packs.clear()
        if not self.root.exists():
            return
        for manifest_path in sorted(self.root.glob("*/manifest.json")):
            self._load_pack(manifest_path.parent, manifest_path)

    def _load_pack(self, pack_root: Path, manifest_path: Path) -> None:
        manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest = GamePackManifest.model_validate(manifest_data)
        actions_data = json.loads((pack_root / manifest.actions_file).read_text(encoding="utf-8"))
        actions = [ActionSpec.model_validate(item) for item in actions_data["actions"]]
        programs = [MotorProgram.model_validate(item) for item in actions_data["motor_programs"]]
        pack = GamePack(pack_root, manifest, actions, programs)
        if pack.id in self._packs:
            raise ValueError(f"Duplicated game pack id: {pack.id}")
        self._packs[pack.id] = pack

    def get(self, pack_id: str) -> GamePack:
        try:
            return self._packs[pack_id]
        except KeyError as exc:
            available = ", ".join(sorted(self._packs)) or "none"
            raise KeyError(f"Game pack '{pack_id}' not found. Available: {available}") from exc

    def summaries(self) -> list[dict]:
        return [self._packs[key].summary() for key in sorted(self._packs)]
