import { useState, useCallback, useRef, useEffect } from 'react';
import { Room, RoomEvent, ConnectionState } from 'livekit-client';
import Constants from 'expo-constants';
import type { AgentCard } from '../types';

const TOKEN_ENDPOINT_URL: string = Constants.expoConfig?.extra?.tokenEndpointUrl ?? '';

interface ConnectionDetails {
  readonly serverUrl: string;
  readonly roomName: string;
  readonly participantToken: string;
}

interface UseLiveKitRoomReturn {
  readonly connectionState: ConnectionState;
  readonly connect: () => Promise<void>;
  readonly disconnect: () => void;
  readonly lastCard: AgentCard | null;
  readonly lastTranscript: { role: 'user' | 'agent'; text: string } | null;
}

async function fetchConnectionDetails(): Promise<ConnectionDetails> {
  const url = `${TOKEN_ENDPOINT_URL}/token?identity=medic`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Token fetch failed: ${res.status}`);
  const data = await res.json() as ConnectionDetails;
  if (!data.participantToken || !data.serverUrl) {
    throw new Error('Missing serverUrl or participantToken in response');
  }
  return data;
}

export function useLiveKitRoom(): UseLiveKitRoomReturn {
  const [connectionState, setConnectionState] = useState<ConnectionState>(ConnectionState.Disconnected);
  const [lastCard, setLastCard] = useState<AgentCard | null>(null);
  const [lastTranscript, setLastTranscript] = useState<{ role: 'user' | 'agent'; text: string } | null>(null);
  const roomRef = useRef<Room | null>(null);

  useEffect(() => {
    return () => {
      roomRef.current?.disconnect();
    };
  }, []);

  const connect = useCallback(async (): Promise<void> => {
    if (!TOKEN_ENDPOINT_URL) {
      throw new Error('EXPO_PUBLIC_TOKEN_ENDPOINT_URL must be set');
    }

    const room = new Room();
    roomRef.current = room;

    room.on(RoomEvent.ConnectionStateChanged, (state: ConnectionState) => {
      setConnectionState(state);
    });

    room.on(RoomEvent.DataReceived, (payload: Uint8Array, _participant, _kind, topic) => {
      const text = new TextDecoder().decode(payload);
      try {
        const parsed: unknown = JSON.parse(text);
        if (topic === 'card') {
          setLastCard(parsed as AgentCard);
        } else if (topic === 'transcript') {
          setLastTranscript(parsed as { role: 'user' | 'agent'; text: string });
        }
      } catch {
        // ignore non-JSON data
      }
    });

    setConnectionState(ConnectionState.Connecting);
    const { serverUrl, participantToken } = await fetchConnectionDetails();
    await room.connect(serverUrl, participantToken);
    await room.localParticipant.setMicrophoneEnabled(true);
  }, []);

  const disconnect = useCallback((): void => {
    roomRef.current?.disconnect();
    roomRef.current = null;
    setConnectionState(ConnectionState.Disconnected);
  }, []);

  return { connectionState, connect, disconnect, lastCard, lastTranscript };
}
