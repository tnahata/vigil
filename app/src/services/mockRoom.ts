import type { GlanceCardData } from '../types';
import { MOCK_RESPONSES, FALLBACK_RESPONSE } from './mockResponses';

interface AgentResponse {
  readonly userTranscript: string;
  readonly agentText: string;
  readonly spokenForm: string;
  readonly card?: GlanceCardData;
}

const CONNECT_DELAY_MS = 200;
const RESPONSE_DELAY_MS = 400;

export function connectToRoom(): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, CONNECT_DELAY_MS);
  });
}

export function detectWakeWord(transcript: string): string | null {
  const lower = transcript.toLowerCase();
  const idx = lower.indexOf('vigil');
  if (idx === -1) return null;
  const query = transcript.slice(idx + 5).trim();
  return query.length > 0 ? query : null;
}

export function simulateAgentResponse(query: string): Promise<AgentResponse> {
  return new Promise((resolve) => {
    setTimeout(() => {
      const match = MOCK_RESPONSES.find((r) => r.trigger.test(query));
      if (match) {
        resolve({
          userTranscript: match.userTranscript,
          agentText: match.agentText,
          spokenForm: match.spokenForm,
          card: match.card,
        });
      } else {
        resolve({
          userTranscript: `Vigil, ${query}`,
          agentText: FALLBACK_RESPONSE.agentText,
          spokenForm: FALLBACK_RESPONSE.spokenForm,
        });
      }
    }, RESPONSE_DELAY_MS);
  });
}

const MOCK_TRANSCRIPTS: readonly string[] = [
  'Vigil, what is the peds epi dose for 20 kg?',
  'Vigil, adult aspirin contraindications?',
  'Vigil, what is the naloxone dose?',
  'Vigil, amiodarone dose for v-fib?',
  'Vigil, what about ketamine?',
  'Vigil, give me the fentanyl dose',
  'Vigil, can I give aspirin to a patient with active GI bleed?',
  'Vigil, epi dose for 500 kg patient?',
];

let mockIndex = 0;

export function getNextMockTranscript(): string {
  const transcript = MOCK_TRANSCRIPTS[mockIndex % MOCK_TRANSCRIPTS.length];
  mockIndex++;
  return transcript;
}
