"""Card channel port: push the glance-card payload to the client."""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class CardChannel(Protocol):
    async def publish_card(self, card: dict) -> None: ...
