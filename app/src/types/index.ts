export type AppState = 'disconnected' | 'connecting' | 'idle' | 'listening' | 'processing' | 'speaking';

export type TierValue = 'tier1_dose' | 'tier2_synthesis' | 'unknown';

export interface Tier1Card {
  readonly found: boolean;
  readonly tier: 'tier1_dose';
  readonly drug: string;
  readonly population: string;
  readonly indication: string;
  readonly dose: string;
  readonly citation: string;
}

export interface Tier2Card {
  readonly found: boolean;
  readonly tier: 'tier2_synthesis';
  readonly text: string;
  readonly citations: readonly string[];
  readonly population: string;
}

export interface NotFoundCard {
  readonly found: false;
  readonly tier: TierValue;
  readonly message?: string;
}

export type AgentCard = Tier1Card | Tier2Card | NotFoundCard;

export interface TranscriptEntry {
  readonly id: string;
  readonly role: 'user' | 'agent';
  readonly text: string;
  readonly timestamp: number;
  readonly card?: AgentCard;
}
