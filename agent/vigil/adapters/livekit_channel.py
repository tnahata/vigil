"""CardChannel port backed by a LiveKit room data channel (topic="card")."""
from __future__ import annotations

import json


class LiveKitChannel:
    def __init__(self, room, topic: str = "card") -> None:
        self._room = room
        self._topic = topic

    async def publish_card(self, card: dict) -> None:
        payload = json.dumps(card).encode("utf-8")
        await self._room.local_participant.publish_data(payload, topic=self._topic)
