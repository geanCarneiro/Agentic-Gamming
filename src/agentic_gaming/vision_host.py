from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Protocol

from .contracts import VisionState
from .gamepacks import GamePack


@dataclass(frozen=True)
class VisionFrame:
    """Opaque frame envelope exposed to a Game Pack vision provider."""

    frame_id: str
    captured_at_ns: int
    width: int
    height: int
    frame_bytes: bytes


class GamePackVisionProvider(Protocol):
    def observe(self, frame: VisionFrame) -> VisionState:
        """Return the pack-specific observation for one captured frame."""


class GamePackVisionCompiler(Protocol):
    def compile(self, *, output_dir: Path) -> dict[str, Any]:
        """Compile pack-specific vision references and write review artifacts."""


class GamePackVisionHost:
    """Loads and invokes a Game Pack's vision provider.

    The Core owns this lifecycle boundary only. It does not inspect ROIs,
    assets, detector types or image-processing details.
    """

    def __init__(self) -> None:
        self._providers: dict[str, GamePackVisionProvider] = {}
        self._modules: dict[str, ModuleType] = {}

    def observe(
        self,
        *,
        frame_id: str,
        captured_at_ns: int,
        width: int,
        height: int,
        frame_bytes: bytes,
        game_pack: GamePack,
    ) -> VisionState:
        provider = self._provider(game_pack)
        return provider.observe(
            VisionFrame(
                frame_id=frame_id,
                captured_at_ns=captured_at_ns,
                width=width,
                height=height,
                frame_bytes=frame_bytes,
            )
        )

    def compile(self, *, game_pack: GamePack, output_dir: Path) -> dict[str, Any]:
        provider = self._provider(game_pack)
        compile_method = getattr(provider, "compile", None)
        if not callable(compile_method):
            raise NotImplementedError(
                f"Game pack '{game_pack.id}' does not provide a vision compiler"
            )
        return compile_method(output_dir=output_dir)

    def _provider(self, game_pack: GamePack) -> GamePackVisionProvider:
        cached = self._providers.get(game_pack.id)
        if cached is not None:
            return cached

        entrypoint = game_pack.manifest.vision.get("entrypoint")
        if not isinstance(entrypoint, str) or ":" not in entrypoint:
            raise ValueError(
                f"Game pack '{game_pack.id}' does not declare a vision entrypoint"
            )
        relative_module, attribute_name = entrypoint.split(":", 1)
        module_path = (game_pack.root / relative_module).resolve()
        if not module_path.is_file():
            raise FileNotFoundError(f"Game pack vision module does not exist: {module_path}")

        module_name = f"agentic_game_pack_{game_pack.id.replace('-', '_')}_vision"
        spec = importlib.util.spec_from_file_location(module_name, module_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Could not load Game Pack vision module: {module_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        factory: Any = getattr(module, attribute_name, None)
        if factory is None:
            raise AttributeError(
                f"Game Pack vision entrypoint '{attribute_name}' was not found in {module_path}"
            )
        provider = factory(
            game_pack_root=game_pack.root,
            manifest=game_pack.manifest.model_dump(),
        )
        if not hasattr(provider, "observe"):
            raise TypeError(f"Game Pack vision provider has no observe method: {module_path}")
        self._modules[game_pack.id] = module
        self._providers[game_pack.id] = provider
        return provider
