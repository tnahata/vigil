# Vigil Mobile App

Thin client for the Vigil EMT voice copilot. **Voice in, voice out.** Screen is secondary to audio — the glance card exists for quick visual confirmation, not as the primary interface.

## Interaction Model

- **Always-on mic.** Wake word "Vigil" triggers a query — no tap-to-speak button.
- Reactive only — never speaks unprompted.
- App NEVER does retrieval, STT, or model calls. All intelligence is server-side (Python LiveKit agent).
- Dose display comes from backend card data — never format or transform dose numbers client-side.

## Architecture

Single screen. App connects to LiveKit Cloud via token from agent's endpoint. Agent auto-dispatches into the room.

```
App → GET /token?identity=medic → { serverUrl, roomName, participantToken }
App → room.connect(serverUrl, participantToken) → mic published → always-on
Agent (auto-dispatched) → LiveKit Inference STT → wake word detection → retrieval → TTS audio back + data channel card
App → plays agent audio (auto-subscribe) + renders card from data channel
```

App talks to LiveKit Cloud, never directly to the agent. The room is the meeting point.

## Connection Flow

1. App fetches `{ serverUrl, roomName, participantToken }` from token endpoint
2. `room.connect(serverUrl, participantToken)` — room name is baked into the JWT
3. `room.localParticipant.setMicrophoneEnabled(true)` — always-on mic
4. Agent audio auto-subscribes and plays
5. Data channel (topic `"card"`) delivers glance card JSON

## Environment

Single env var in `app/.env`:
```
EXPO_PUBLIC_TOKEN_ENDPOINT_URL=<agent's token endpoint base URL>
```
Bakes in at **build time** (Expo `EXPO_PUBLIC_*` pattern). Changing requires rebuild.

**Physical device:** localhost/LAN IP unreachable (WiFi isolation). Use ngrok: `ngrok http <agent-port>` → set ngrok URL as `EXPO_PUBLIC_TOKEN_ENDPOINT_URL`.

**Simulator:** localhost works.

## Tech Stack

- React Native + Expo dev build (not Expo Go — WebRTC needs native modules)
- TypeScript strict mode
- LiveKit RN SDK (`@livekit/react-native`, `livekit-client`) — real connection
- `expo-haptics` for tactile feedback on card appear
- iOS-first

## App holds zero LiveKit credentials

No API key, no API secret, no LiveKit URL in the app. Token endpoint provides everything. App only stores the token endpoint URL.

## TypeScript Configuration

- Strict mode enabled
- No implicit any
- Strict null checks
- ES modules

## Type Conventions

- Prefer interfaces for object shapes
- Use type aliases for unions/intersections
- Export types alongside implementations
- Avoid `any` - use `unknown` if type is truly unknown

## Patterns

- Use discriminated unions for state (AppState, AgentCard with Tier1Card | Tier2Card | NotFoundCard)
- Prefer readonly arrays and objects where applicable
- Use generics for reusable type-safe functions
- Leverage utility types (Partial, Required, Pick, Omit)

## Code Style

- Use explicit return types for exported functions
- Use const assertions for literal types
- Prefer nullish coalescing (??) over OR (||)
- Use optional chaining (?.) for safe property access
- Functional components + hooks only, no class components

## File Organization

- One export per file when possible
- Co-locate types with implementations
- Use barrel exports (index.ts) for public APIs

## Commands

- `npm run typecheck` - Check types without emitting
- `npm run lint` - Run ESLint with TypeScript rules
- `npm start` - Start Expo dev server
- `npm run ios` - Start on iOS simulator
- `npm run dev-build` - Prebuild + run native iOS build (needed for LiveKit WebRTC)

## Directory Structure

```
src/
  components/   - UI: GlanceCard (Tier1/Tier2/NotFound), TranscriptView, StatusIndicator
  hooks/        - useLiveKitRoom (real connection), useAgentSession (data channel driven)
  types/        - shared types (AppState, AgentCard, Tier1Card, Tier2Card, TranscriptEntry)
  theme/        - colors, spacing, typography (dark, high-contrast, medical)
```

## Build & Deploy to Phone

```bash
npx expo prebuild --clean
xcodebuild -workspace ios/Vigil.xcworkspace -scheme Vigil \
  -destination "id=<device-uuid>" -configuration Release \
  CODE_SIGN_STYLE=Automatic DEVELOPMENT_TEAM=<team-id> \
  CODE_SIGN_IDENTITY="Apple Development" -allowProvisioningUpdates build
xcrun devicectl device install app --device <device-uuid> <path-to-Vigil.app>
xcrun devicectl device process launch --device <device-uuid> com.tnahata.vigil
```
