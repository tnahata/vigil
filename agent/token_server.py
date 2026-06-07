"""Tiny LiveKit token endpoint -- the only public HTTP surface in Vigil.

The app does NOT connect to the agent. The app and the agent each dial OUT to a
LiveKit Cloud room and meet there. To join, the app needs the LiveKit URL plus a
short-lived JWT signed with LIVEKIT_API_KEY/SECRET. The secret must never ship in
the app, so this server mints the token. It is the room authority: the room name
(`vigil-demo`) is baked into the signed token, and the agent -- registered for
automatic dispatch (no agent_name) -- auto-joins whatever room the client lands in.

This is NOT part of the deterministic dose path: it only reads LiveKit creds via
`vigil.config.load_config()` (config, not the pure `vigil.core`) and signs a JWT.

Run (from agent/, creds in agent/.env):

    .venv/bin/python token_server.py            # listens on 0.0.0.0:8080

Then the app fetches:

    GET http://<host>:8080/token?identity=medic
    -> { serverUrl, roomName, participantName, participantToken }
"""
from __future__ import annotations

import asyncio
import datetime
import logging
import os

# Load agent/.env at import time, anchored to this file's dir, so the LiveKit creds
# are present no matter the working directory (mirrors agent.py's import-time load).
try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except Exception:  # pragma: no cover - dotenv is optional
    pass

from aiohttp import web
from livekit import api

from vigil.config import load_config

log = logging.getLogger("vigil.token_server")

# Fixed demo room: every client and the agent share one room. Swap to a per-session
# name (e.g. f"vigil-{uuid4()}") here if multiple simultaneous medics are needed.
ROOM = os.getenv("VIGIL_ROOM", "vigil-demo")
TOKEN_TTL = datetime.timedelta(hours=6)

_CORS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Allow-Headers": "*",
}


@web.middleware
async def cors_middleware(request: web.Request, handler):
    # Browser/mobile-web fallback (Safari + LiveKit JS) sends a CORS preflight;
    # native RN fetch doesn't need this but the headers are harmless.
    if request.method == "OPTIONS":
        return web.Response(status=204, headers=_CORS)
    resp = await handler(request)
    resp.headers.update(_CORS)
    return resp


def _mint(identity: str, room: str = ROOM) -> str:
    cfg = load_config()
    if not (cfg.livekit_api_key and cfg.livekit_api_secret and cfg.livekit_url):
        raise web.HTTPInternalServerError(
            text="LIVEKIT_URL / LIVEKIT_API_KEY / LIVEKIT_API_SECRET missing in agent/.env"
        )
    grant = api.VideoGrants(
        room_join=True,
        room=room,
        can_publish=True,       # always-on mic
        can_subscribe=True,     # hear the agent
        can_publish_data=True,  # (client doesn't need it, but harmless)
    )
    return (
        api.AccessToken(cfg.livekit_api_key, cfg.livekit_api_secret)
        .with_identity(identity)
        .with_name(identity)
        .with_grants(grant)
        .with_ttl(TOKEN_TTL)
        .to_jwt()
    )


async def token(request: web.Request) -> web.Response:
    identity = request.query.get("identity", "medic")
    cfg = load_config()

    # Delete ALL existing vigil rooms so LiveKit dispatches a fresh agent.
    try:
        lk = api.LiveKitAPI(cfg.livekit_url, cfg.livekit_api_key, cfg.livekit_api_secret)
        try:
            rooms = await lk.room.list_rooms(api.ListRoomsRequest())
            for r in rooms.rooms:
                if r.name.startswith("vigil-"):
                    await lk.room.delete_room(api.DeleteRoomRequest(room=r.name))
        finally:
            await lk.aclose()
    except Exception:
        pass

    import uuid
    room_name = f"vigil-{uuid.uuid4().hex[:8]}"

    body = {
        "serverUrl": cfg.livekit_url,
        "roomName": room_name,
        "participantName": identity,
        "participantToken": _mint(identity, room_name),
    }
    log.info("issued token", extra={"vigil": {"room": room_name, "identity": identity}})
    return web.json_response(body)


async def health(_request: web.Request) -> web.Response:
    return web.json_response({"ok": True, "room": ROOM})


def build_app() -> web.Application:
    app = web.Application(middlewares=[cors_middleware])
    app.add_routes([web.get("/", health), web.get("/token", token)])
    return app


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    port = int(os.getenv("TOKEN_SERVER_PORT", "8080"))
    # 0.0.0.0 so a phone on the same Wi-Fi (or an ngrok tunnel) can reach it.
    web.run_app(build_app(), host="0.0.0.0", port=port)
