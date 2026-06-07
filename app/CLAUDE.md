# Vigil Mobile App

Thin client for the Vigil EMT voice copilot. **Voice in, voice out.** Screen is secondary to audio — the glance card exists for quick visual confirmation, not as the primary interface.

## Interaction Model

- **Always-on mic.** Wake word "Vigil" triggers a query — no tap-to-speak button.
- Reactive only — never speaks unprompted.
- App NEVER does retrieval or model calls. All intelligence is server-side (Python LiveKit agent + Moss retrieval).
- Dose display uses `spokenForm` from backend — never format or transform dose numbers client-side.

## Architecture

Single screen. LiveKit for real-time audio transport (currently mocked).

Production flow: always-on mic → LiveKit Cloud STT → Python agent detects wake word → Moss retrieval → Minimax TTS audio back + data channel glance card → app plays audio + renders card.

Mock flow: dev-mode button triggers canned query → mock response → `expo-speech` TTS + glance card.

## Tech Stack

- React Native + Expo dev build (not Expo Go — WebRTC needs native modules)
- TypeScript strict mode
- LiveKit RN SDK (`@livekit/react-native`, `livekit-client`) — installed, connection mocked
- `expo-speech` for TTS in mock mode
- `expo-haptics` for tactile feedback
- iOS-first

## Mock Status

All LiveKit room interactions mocked in `src/services/mock*.ts`. To connect to real backend: replace mock imports in `src/hooks/useLiveKitRoom.ts` with real LiveKit `useRoom()` hook.

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

- Use discriminated unions for state
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
  components/   - UI: GlanceCard, TranscriptView, StatusIndicator
  hooks/        - useLiveKitRoom (mocked), useAgentSession (state machine)
  services/     - mockRoom, mockResponses (swap for real LiveKit)
  types/        - shared types (AppState, GlanceCardData, TranscriptEntry)
  theme/        - colors, spacing, typography (dark, high-contrast, medical)
```
