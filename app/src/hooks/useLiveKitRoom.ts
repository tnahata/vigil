import { useState, useCallback } from 'react';
import type { RoomState } from '../types';
import { connectToRoom } from '../services/mockRoom';

interface UseLiveKitRoomReturn {
  readonly roomState: RoomState;
  readonly connect: () => Promise<void>;
  readonly disconnect: () => void;
}

export function useLiveKitRoom(): UseLiveKitRoomReturn {
  const [roomState, setRoomState] = useState<RoomState>({
    connected: false,
    connecting: false,
  });

  const connect = useCallback(async (): Promise<void> => {
    setRoomState({ connected: false, connecting: true });
    await connectToRoom();
    setRoomState({ connected: true, connecting: false });
  }, []);

  const disconnect = useCallback((): void => {
    setRoomState({ connected: false, connecting: false });
  }, []);

  return { roomState, connect, disconnect };
}
