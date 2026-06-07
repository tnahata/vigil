import type { MockResponse } from '../types';

export const MOCK_RESPONSES: readonly MockResponse[] = [
  {
    trigger: /peds?\s+(epi|epinephrine)\s+dose/i,
    userTranscript: 'Vigil, what is the peds epi dose for 20 kg?',
    agentText: 'Pediatric epinephrine: 0.01 milligrams per kilogram, intramuscular. For 20 kilograms, that is 0.2 milligrams IM. Protocol 4210.',
    spokenForm: 'Pediatric epinephrine: zero point zero one milligrams per kilogram, intramuscular. For twenty kilograms, that is zero point two milligrams I M. Protocol forty-two ten.',
    card: {
      drugName: 'EPINEPHRINE',
      dose: '0.01 mg/kg → 0.2 mg',
      route: 'IM',
      protocolId: 'Protocol 4210',
      tier: 1,
      spokenForm: 'zero point two milligrams intramuscular',
    },
  },
  {
    trigger: /aspirin\s+(contraindication|contra)/i,
    userTranscript: 'Vigil, adult aspirin contraindications?',
    agentText: 'Aspirin contraindications: active GI bleeding, known aspirin allergy, children under 16 with viral illness. Protocol 3100.',
    spokenForm: 'Aspirin contraindications: active G I bleeding, known aspirin allergy, children under sixteen with viral illness. Protocol thirty-one hundred.',
    card: {
      drugName: 'ASPIRIN',
      dose: '324 mg',
      route: 'PO',
      contraindications: [
        'Active GI bleeding',
        'Known aspirin allergy',
        'Children <16 with viral illness',
      ],
      protocolId: 'Protocol 3100',
      tier: 1,
      spokenForm: 'three hundred twenty-four milligrams by mouth',
    },
  },
  {
    trigger: /naloxone|narcan/i,
    userTranscript: 'Vigil, what is the naloxone dose?',
    agentText: 'Adult naloxone: 2 milligrams intranasal. May repeat every 2 to 3 minutes. Protocol 5010.',
    spokenForm: 'Adult naloxone: two milligrams intranasal. May repeat every two to three minutes. Protocol fifty ten.',
    card: {
      drugName: 'NALOXONE',
      dose: '2 mg IN',
      route: 'IN',
      protocolId: 'Protocol 5010',
      tier: 1,
      spokenForm: 'two milligrams intranasal',
    },
  },
  {
    trigger: /amiodarone/i,
    userTranscript: 'Vigil, amiodarone dose for v-fib?',
    agentText: 'Amiodarone for ventricular fibrillation: 300 milligrams IV push, first dose. Second dose 150 milligrams. Protocol 4110.',
    spokenForm: 'Amiodarone for ventricular fibrillation: three hundred milligrams I V push, first dose. Second dose one hundred fifty milligrams. Protocol forty-one ten.',
    card: {
      drugName: 'AMIODARONE',
      dose: '300 mg (1st) / 150 mg (2nd)',
      route: 'IV Push',
      protocolId: 'Protocol 4110',
      tier: 1,
      spokenForm: 'three hundred milligrams I V push first dose',
    },
  },
  {
    trigger: /ketamine/i,
    userTranscript: 'Vigil, what about ketamine?',
    agentText: 'Ketamine is not in the current protocol set. Contact medical control for guidance.',
    spokenForm: 'Ketamine is not in the current protocol set. Contact medical control for guidance.',
  },
  {
    trigger: /fentanyl/i,
    userTranscript: 'Vigil, give me the fentanyl dose',
    agentText: 'Fentanyl is not in the current protocol set. Contact medical control for guidance.',
    spokenForm: 'Fentanyl is not in the current protocol set. Contact medical control for guidance.',
  },
  {
    trigger: /200\s*kg|300\s*kg|500\s*kg/i,
    userTranscript: 'Vigil, epi dose for 500 kg patient?',
    agentText: 'Weight 500 kg is outside the supported range. Contact medical control for guidance.',
    spokenForm: 'Weight five hundred kilograms is outside the supported range. Contact medical control for guidance.',
  },
  {
    trigger: /aspirin.*bleed|bleed.*aspirin/i,
    userTranscript: 'Vigil, can I give aspirin to a patient with active GI bleed?',
    agentText: 'Aspirin is contraindicated with active GI bleeding. Do NOT administer. Contact medical control. Protocol 3100.',
    spokenForm: 'Aspirin is contraindicated with active G I bleeding. Do NOT administer. Contact medical control. Protocol thirty-one hundred.',
    card: {
      drugName: 'ASPIRIN',
      dose: 'DO NOT ADMINISTER',
      route: '—',
      contraindications: [
        'ACTIVE GI BLEED — CONTRAINDICATED',
      ],
      protocolId: 'Protocol 3100',
      tier: 1,
      spokenForm: 'Do not administer. Contraindicated.',
    },
  },
];

export const FALLBACK_RESPONSE: Omit<MockResponse, 'trigger'> = {
  userTranscript: '',
  agentText: 'That query is not in the current protocol set. Contact medical control for guidance.',
  spokenForm: 'That query is not in the current protocol set. Contact medical control for guidance.',
};
