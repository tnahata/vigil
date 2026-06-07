import { View, Text, StyleSheet } from 'react-native';
import type { GlanceCardData } from '../types';
import { colors, spacing, typography } from '../theme';

interface GlanceCardProps {
  readonly data: GlanceCardData;
}

export function GlanceCard({ data }: GlanceCardProps): React.JSX.Element {
  return (
    <View style={styles.card}>
      <Text style={typography.drugName}>{data.drugName}</Text>
      <Text style={typography.dose}>{data.dose}</Text>
      <Text style={typography.route}>{data.route}</Text>

      {data.contraindications && data.contraindications.length > 0 && (
        <View style={styles.contraindications}>
          {data.contraindications.map((c) => (
            <Text key={c} style={typography.contraindication}>
              {'⚠'} {c}
            </Text>
          ))}
        </View>
      )}

      <Text style={[typography.protocolId, styles.protocol]}>{data.protocolId}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.surface,
    borderRadius: 16,
    padding: spacing.lg,
    marginHorizontal: spacing.md,
    marginVertical: spacing.sm,
    borderWidth: 1,
    borderColor: colors.border,
  },
  contraindications: {
    marginTop: spacing.md,
    paddingTop: spacing.md,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.border,
  },
  protocol: {
    marginTop: spacing.md,
  },
});
