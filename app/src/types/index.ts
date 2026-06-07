export type AppState = 'disconnected' | 'connecting' | 'idle' | 'listening' | 'processing' | 'speaking';

export interface GlanceCardData {
  readonly drugName: string;
  readonly dose: string;
  readonly route: string;
  readonly contraindications?: readonly string[];
  readonly protocolId: string;
  readonly tier: 1 | 2;
  readonly spokenForm: string;
}

export interface TranscriptEntry {
  readonly id: string;
  readonly role: 'user' | 'agent';
  readonly text: string;
  readonly timestamp: number;
  readonly card?: GlanceCardData;
}

export interface MockResponse {
  readonly trigger: RegExp;
  readonly userTranscript: string;
  readonly agentText: string;
  readonly spokenForm: string;
  readonly card?: GlanceCardData;
}

export interface RoomState {
  readonly connected: boolean;
  readonly connecting: boolean;
}
