---
name: vigil-add-component
description: Add a new UI component to the Vigil mobile app following project conventions
---

# Add Component to Vigil App

When adding a new component to `app/src/components/`:

1. Create file with PascalCase name matching component
2. Use explicit interface for props with `readonly` fields
3. Use explicit return type `React.JSX.Element`
4. Import theme tokens from `../theme` — never hardcode colors, spacing, or font sizes
5. Use `StyleSheet.create()` for styles, defined at module scope
6. Dark background, high contrast — this is a medical tool used in ambulances
7. Dose-related text must be large (44-60pt) and high contrast
8. Contraindications always in red (`colors.danger`)

Example skeleton:

```typescript
import { View, Text, StyleSheet } from 'react-native';
import { colors, spacing, typography } from '../theme';

interface MyComponentProps {
  readonly someValue: string;
}

export function MyComponent({ someValue }: MyComponentProps): React.JSX.Element {
  return (
    <View style={styles.container}>
      <Text style={typography.transcript}>{someValue}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    padding: spacing.md,
  },
});
```

After creating, verify with `npm run typecheck && npm run lint` from `/app/`.
