import { useState, useCallback, useRef, useEffect } from 'react';
import * as Speech from 'expo-speech';
import * as Haptics from 'expo-haptics';
import type { AppState, TranscriptEntry, GlanceCardData } from '../types';
import { connectToRoom, detectWakeWord, simulateAgentResponse, getNextMockTranscript } from '../services/mockRoom';

interface UseAgentSessionReturn {
  readonly appState: AppState;
  readonly transcript: readonly TranscriptEntry[];
  readonly currentCard: GlanceCardData | null;
  readonly triggerMockQuery: () => void;
}

let entryId = 0;
function nextId(): string {
  entryId++;
  return `entry-${entryId}`;
}

export function useAgentSession(): UseAgentSessionReturn {
  const [appState, setAppState] = useState<AppState>('disconnected');
  const [transcript, setTranscript] = useState<readonly TranscriptEntry[]>([]);
  const [currentCard, setCurrentCard] = useState<GlanceCardData | null>(null);
  const busyRef = useRef(false);

  useEffect(() => {
    connectToRoom().then(() => setAppState('idle'));
  }, []);

  const triggerMockQuery = useCallback((): void => {
    if (busyRef.current) return;
    busyRef.current = true;
    Speech.stop();

    const rawTranscript = getNextMockTranscript();
    const query = detectWakeWord(rawTranscript);
    if (!query) {
      busyRef.current = false;
      return;
    }

    setAppState('processing');
    setTranscript((prev) => [
      ...prev,
      { id: nextId(), role: 'user', text: rawTranscript, timestamp: Date.now() },
    ]);

    simulateAgentResponse(query).then((response) => {
      setCurrentCard(response.card ?? null);

      setTranscript((prev) => [
        ...prev,
        { id: nextId(), role: 'agent', text: response.agentText, timestamp: Date.now(), card: response.card },
      ]);

      setAppState('idle');
      busyRef.current = false;

      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);

      Speech.speak(response.spokenForm, {
        language: 'en-US',
        rate: 0.95,
      });
    }).catch(() => {
      setAppState('idle');
      busyRef.current = false;
    });
  }, []);

  return { appState, transcript, currentCard, triggerMockQuery };
}
