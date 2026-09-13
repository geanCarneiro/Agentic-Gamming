from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path


class JsonLineFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in ("run_id", "event_type", "state_version", "motor_program"):
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = str(value)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging() -> Path:
    path = Path(os.getenv("LOG_PATH", "data/logs/core.jsonl"))
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(JsonLineFormatter())
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    root.addHandler(handler)
    return path


def read_logs(path: Path, run_id: str | None = None, limit: int = 100) -> list[dict]:
    if not path.exists():
        return []
    entries: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        if run_id is None or entry.get("run_id") == run_id:
            entries.append(entry)
    return entries[-limit:]
