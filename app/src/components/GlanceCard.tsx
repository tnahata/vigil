import { View, Text, StyleSheet } from 'react-native';
import type { AgentCard } from '../types';
import { colors, spacing, typography } from '../theme';

interface GlanceCardProps {
  readonly data: AgentCard;
}

function Tier1Card({ data }: { readonly data: Extract<AgentCard, { tier: 'tier1_dose' }> }): React.JSX.Element {
  return (
    <View style={styles.card}>
      <Text style={typography.drugName} adjustsFontSizeToFit numberOfLines={1}>{data.drug.toUpperCase()}</Text>
      <Text style={typography.dose}>{data.dose}</Text>
      <Text style={typography.route}>{data.population.toUpperCase()}</Text>
      {data.indication ? (
        <Text style={[typography.protocolId, styles.indication]}>{data.indication}</Text>
      ) : null}
      <Text style={[typography.protocolId, styles.protocol]}>{data.citation}</Text>
    </View>
  );
}

function Tier2Card({ data }: { readonly data: Extract<AgentCard, { tier: 'tier2_synthesis' }> }): React.JSX.Element {
  return (
    <View style={styles.card}>
      <Text style={typography.transcriptAgent}>{data.text}</Text>
      <Text style={[typography.protocolId, styles.protocol]}>
        {data.citations.join(', ')}
      </Text>
    </View>
  );
}

function NotFoundCardView(): React.JSX.Element {
  return (
    <View style={[styles.card, styles.notFoundCard]}>
      <Text style={typography.contraindication}>Not in protocol</Text>
      <Text style={[typography.transcript, styles.protocol]}>Contact medical control</Text>
    </View>
  );
}

export function GlanceCard({ data }: GlanceCardProps): React.JSX.Element {
  if (!data.found) {
    return <NotFoundCardView />;
  }
  if (data.tier === 'tier1_dose') {
    return <Tier1Card data={data as Extract<AgentCard, { tier: 'tier1_dose' }>} />;
  }
  if (data.tier === 'tier2_synthesis') {
    return <Tier2Card data={data as Extract<AgentCard, { tier: 'tier2_synthesis' }>} />;
  }
  return <NotFoundCardView />;
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
    alignItems: 'center',
  },
  notFoundCard: {
    borderColor: colors.danger,
    alignItems: 'center',
  },
  indication: {
    marginTop: spacing.sm,
  },
  protocol: {
    marginTop: spacing.md,
  },
});
