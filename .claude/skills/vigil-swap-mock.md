---
name: vigil-swap-mock
description: Replace mock LiveKit services with real backend integration
---

# Swap Mock for Real LiveKit Integration

When replacing mocked services with real LiveKit room connection:

## Steps

1. **`src/hooks/useLiveKitRoom.ts`** — Replace mock `connectToRoom()` with real LiveKit:
   - Import `useRoom` from `@livekit/react-native`
   - Connect with real `url` and `token` (from env/config)
   - Expose same interface: `{ roomState, connect, disconnect }`

2. **`src/hooks/useAgentSession.ts`** — Replace mock flow:
   - Remove `getNextMockTranscript()` and dev-mode trigger
   - Subscribe to real LiveKit data channel for card payloads
   - Subscribe to agent audio track for TTS (replaces `expo-speech`)
   - STT + wake word detection happens server-side — app receives processed responses

3. **`App.tsx`** — Remove mock trigger button, add LiveKit `RoomProvider` wrapper

4. **Config** — Add LiveKit server URL and token endpoint to env/config

## What stays the same

- Types in `src/types/` — `GlanceCardData`, `TranscriptEntry`, `AppState` unchanged
- UI components — `GlanceCard`, `TranscriptView`, `StatusIndicator` unchanged
- Theme — all design tokens unchanged

## Testing

- `npm run typecheck && npm run lint`
- Dev build required: `npm run dev-build` (WebRTC needs native modules)
- Test on real iOS device for mic permissions + audio
