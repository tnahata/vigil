---
name: vigil-add-mock-response
description: Add new mock EMT Q&A pair to Vigil mock responses
---

# Add Mock Response

Add new EMT Q&A pairs to `app/src/services/mockResponses.ts`.

## Steps

1. Add entry to `MOCK_RESPONSES` array with shape:

```typescript
{
  trigger: /keyword_regex/i,           // regex to match query after "Vigil"
  userTranscript: 'Vigil, ...',        // full user utterance
  agentText: '...',                    // text version of response
  spokenForm: '...',                   // TTS-safe version (spell out numbers, abbreviations)
  card: {                              // optional — omit for refusal/fallback responses
    drugName: 'DRUG NAME',             // ALL CAPS
    dose: '0.X mg/kg',                 // exact from protocol
    route: 'IM',                       // route abbreviation
    contraindications: ['...'],        // optional array
    protocolId: 'Protocol XXXX',       // protocol reference
    tier: 1,                           // 1 = deterministic dose, 2 = LLM synthesis
    spokenForm: '...',                 // TTS-safe dose pronunciation
  },
}
```

2. For adversarial/refusal cases (drug not in protocol), omit `card` field entirely.

3. `spokenForm` must spell out numbers and abbreviations:
   - "0.01" → "zero point zero one"
   - "mg" → "milligrams"
   - "IV" → "I V"
   - "IM" → "I M"

4. Also add to `getNextMockTranscript()` cycle in `mockRoom.ts` if desired for dev-mode rotation.

5. Verify: `npm run typecheck && npm run lint`
