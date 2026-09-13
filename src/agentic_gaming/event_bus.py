from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Protocol

from .contracts import EventEnvelope

EventHandler = Callable[[EventEnvelope], Awaitable[None]]


class EventBus(Protocol):
    async def publish(self, event: EventEnvelope) -> None: ...

    async def subscribe(self, event_type: str, handler: EventHandler) -> None: ...


class InMemoryEventBus:
    """Deterministic bus used by tests and by the zero-dependency local mode."""

    def __init__(self):
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)
        self.events: list[EventEnvelope] = []

    async def publish(self, event: EventEnvelope) -> None:
        self.events.append(event)
        await asyncio.gather(*(handler(event) for handler in self._handlers[event.event_type]))

    async def subscribe(self, event_type: str, handler: EventHandler) -> None:
        self._handlers[event_type].append(handler)


class NatsEventBus:
    """JetStream-backed adapter; the core remains independent of NATS."""

    def __init__(self, url: str):
        self.url = url
        self._nc = None

    async def connect(self) -> None:
        import nats

        self._nc = await nats.connect(self.url)

    async def publish(self, event: EventEnvelope) -> None:
        if self._nc is None:
            raise RuntimeError("NATS bus is not connected")
        await self._nc.publish(event.event_type, event.model_dump_json().encode())

    async def subscribe(self, event_type: str, handler: EventHandler) -> None:
        if self._nc is None:
            raise RuntimeError("NATS bus is not connected")

        async def callback(message):
            event = EventEnvelope.model_validate_json(message.data)
            await handler(event)

        await self._nc.subscribe(event_type, cb=callback)

    async def close(self) -> None:
        if self._nc is not None:
            await self._nc.drain()
