from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

from .contracts import EventEnvelope


class ReplayRecorder:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, event: EventEnvelope) -> None:
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(event.model_dump_json() + "\n")


class ReplayReader:
    def __init__(self, path: Path):
        self.path = path

    def events(self) -> Iterator[EventEnvelope]:
        with self.path.open(encoding="utf-8") as stream:
            for line in stream:
                if line.strip():
                    yield EventEnvelope.model_validate(json.loads(line))
