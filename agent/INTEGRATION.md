# Vigil — App ↔ Agent integration

Everything the React Native (or mobile-web) client needs to talk to the agent. The
client never connects to the agent directly: the app and the agent each dial **out**
to a LiveKit Cloud **room** and meet there.

```
App ──join(serverUrl, token)──▶ LiveKit Cloud room "vigil-demo" ◀──auto-dispatch── Agent
        (token from /token)                                          (python agent.py dev)
```

## 1. What you connect with

The app needs two things, both delivered by the token endpoint:

- **serverUrl** — `wss://<project>.livekit.cloud`
- **participantToken** — a short-lived JWT scoped to room `vigil-demo` (the room name is
  baked into the token; you do **not** pass a room name to `connect()`).

Fetch them:

```
GET <token-endpoint>/token?identity=medic
→ { "serverUrl": "...", "roomName": "vigil-demo",
    "participantName": "medic", "participantToken": "<JWT>" }
```

The `<token-endpoint>` is either our `token_server.py` (laptop LAN IP or ngrok URL) or a
LiveKit Sandbox token server. The response shape matches LiveKit's standard
`connection-details` example, so LiveKit's RN starter code works as-is.

## 2. Connect (React Native)

```js
// index.js — once, before anything else
import { registerGlobals } from '@livekit/react-native';
registerGlobals();
```

```js
import { Room, RoomEvent } from 'livekit-client';

const { serverUrl, participantToken } = await fetch(
  `${TOKEN_ENDPOINT}/token?identity=medic`
).then(r => r.json());

const room = new Room();
await room.connect(serverUrl, participantToken);   // room name is inside the token
await room.localParticipant.setMicrophoneEnabled(true);  // always-on mic
// The agent's audio track auto-subscribes and plays. Keep AEC (echo cancel) ON.
```

The agent (running `python agent.py dev`) is auto-dispatched into `vigil-demo` the moment
you connect — no coordination needed.

## 3. The glance card (data channel)

The agent publishes the card as JSON on data-channel **topic `"card"`** after each answer:

```js
room.on(RoomEvent.DataReceived, (payload, _participant, _kind, topic) => {
  if (topic !== 'card') return;
  const card = JSON.parse(new TextDecoder().decode(payload));
  // render per the shapes below
});
```

Payload shapes:

| Case | Payload |
|---|---|
| **Tier-1 dose** | `{ found:true, tier:"tier1_dose", drug, population, indication, dose, citation }` |
| **Tier-2 synthesis** | `{ found:true, tier:"tier2_synthesis", text, citations:[...], population }` |
| **Safe fallback** | `{ found:false, tier, message:"Not in protocol. Contact medical control." }` |

Rendering guidance:
- Render `dose` huge / high-contrast (sunlight + gloves). Show `citation` (protocol id).
- `found:false` → red "Contact medical control" warning, no dose.
- The agent also **speaks** the answer; the card is the visual mirror.

## 4. Talking to it

The agent is reactive and wake-word gated. Speak: **"Vigil, what's the adult epi dose for
anaphylaxis"** (Tier-1, verbatim dose) or **"Vigil, what should I consider before giving
epinephrine?"** (Tier-2, grounded synthesis). Nothing happens until it hears "Vigil".

## 5. Running the server side (us, not the app dev)

```bash
cd agent
.venv/bin/python token_server.py        # token endpoint on 0.0.0.0:8080
.venv/bin/python agent.py dev           # agent worker -> joins vigil-demo on demand
```

Reachability: the agent dials out (no inbound port). The **token endpoint** is the only
thing the app must reach — give the app dev `http://<laptop-LAN-IP>:8080/token` on the same
Wi-Fi, an `ngrok http 8080` URL for cellular, or a LiveKit Sandbox token server URL.
