import { useState, useCallback, useEffect, useRef } from 'react';
import * as Haptics from 'expo-haptics';
import { ConnectionState } from 'livekit-client';
import type { AppState, TranscriptEntry, AgentCard } from '../types';
import { useLiveKitRoom } from './useLiveKitRoom';

interface UseAgentSessionReturn {
  readonly appState: AppState;
  readonly transcript: readonly TranscriptEntry[];
  readonly currentCard: AgentCard | null;
  readonly connect: () => Promise<void>;
}

let entryId = 0;
function nextId(): string {
  entryId++;
  return `entry-${entryId}`;
}

function connectionToAppState(state: ConnectionState): AppState {
  switch (state) {
    case ConnectionState.Connected: return 'idle';
    case ConnectionState.Connecting: return 'connecting';
    case ConnectionState.Reconnecting: return 'connecting';
    default: return 'disconnected';
  }
}

export function useAgentSession(): UseAgentSessionReturn {
  const { connectionState, connect: connectRoom, lastCard, lastTranscript } = useLiveKitRoom();
  const [appState, setAppState] = useState<AppState>('disconnected');
  const [transcript, setTranscript] = useState<readonly TranscriptEntry[]>([]);
  const [currentCard, setCurrentCard] = useState<AgentCard | null>(null);
  const prevCardRef = useRef<AgentCard | null>(null);
  const prevTranscriptRef = useRef<{ role: 'user' | 'agent'; text: string } | null>(null);

  useEffect(() => {
    setAppState(connectionToAppState(connectionState));
  }, [connectionState]);

  useEffect(() => {
    if (lastCard && lastCard !== prevCardRef.current) {
      prevCardRef.current = lastCard;
      setCurrentCard(lastCard);
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
    }
  }, [lastCard]);

  useEffect(() => {
    if (lastTranscript && lastTranscript !== prevTranscriptRef.current) {
      prevTranscriptRef.current = lastTranscript;
      setTranscript((prev) => [
        ...prev,
        {
          id: nextId(),
          role: lastTranscript.role,
          text: lastTranscript.text,
          timestamp: Date.now(),
        },
      ]);
    }
  }, [lastTranscript]);

  const connect = useCallback(async (): Promise<void> => {
    await connectRoom();
  }, [connectRoom]);

  return { appState, transcript, currentCard, connect };
}
