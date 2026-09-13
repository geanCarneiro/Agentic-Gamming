from __future__ import annotations

from time import monotonic_ns

from .contracts import AudioEvent, InformationOrigin, ObservedFact, VisionState, WorldState


class WorldStateStore:
    def __init__(self, run_id):
        self._state = WorldState(run_id=run_id, version=0, updated_at_ns=monotonic_ns())

    @property
    def state(self) -> WorldState:
        return self._state.model_copy(deep=True)

    def ingest_vision(self, vision: VisionState) -> WorldState:
        changed = []
        if vision.scene is not None:
            self._state.scene = vision.scene
            self._state.facts["scene"] = ObservedFact(
                key="scene",
                value=vision.scene,
                confidence=vision.confidence,
                observed_at_ns=vision.captured_at_ns,
                origin=InformationOrigin.OBSERVED_NOW,
            )
            changed.append("scene")

        for entity in vision.entities:
            key = f"entity.{entity.id}"
            self._state.facts[key] = ObservedFact(
                key=key,
                value=entity.model_dump(),
                confidence=entity.confidence,
                observed_at_ns=vision.captured_at_ns,
                origin=entity.origin,
            )
            changed.append(key)

        self._commit(vision.captured_at_ns, changed or vision.changed)
        return self.state

    def ingest_audio(self, event: AudioEvent) -> WorldState:
        self._state.event_queue.append(event)
        self._commit(event.started_at_ns, [f"audio.{event.event_type}"])
        return self.state

    def consume_audio(self, event_id: str) -> WorldState:
        self._state.event_queue = [
            event for event in self._state.event_queue if event.event_id != event_id
        ]
        self._commit(monotonic_ns(), [f"consume.{event_id}"])
        return self.state

    def _commit(self, timestamp_ns: int, deltas: list[str]) -> None:
        self._state.version += 1
        self._state.updated_at_ns = timestamp_ns
        self._state.recent_deltas = deltas
