import { useRef, useEffect } from 'react';
import { View, Text, ScrollView, StyleSheet } from 'react-native';
import type { TranscriptEntry } from '../types';
import { colors, spacing, typography } from '../theme';

interface TranscriptViewProps {
  readonly entries: readonly TranscriptEntry[];
}

export function TranscriptView({ entries }: TranscriptViewProps): React.JSX.Element {
  const scrollRef = useRef<ScrollView>(null);

  useEffect(() => {
    if (entries.length > 0) {
      scrollRef.current?.scrollToEnd({ animated: true });
    }
  }, [entries.length]);

  if (entries.length === 0) {
    return (
      <View style={styles.emptyContainer}>
        <Text style={styles.emptyText}>Say &quot;Vigil&quot; followed by your question</Text>
      </View>
    );
  }

  return (
    <ScrollView
      ref={scrollRef}
      style={styles.container}
      contentContainerStyle={styles.content}
    >
      {entries.map((entry) => (
        <View key={entry.id} style={styles.entry}>
          <Text style={styles.roleLabel}>
            {entry.role === 'user' ? 'You' : 'Vigil'}
          </Text>
          <Text style={entry.role === 'user' ? typography.transcript : typography.transcriptAgent}>
            {entry.text}
          </Text>
        </View>
      ))}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  content: {
    paddingHorizontal: spacing.md,
    paddingBottom: spacing.lg,
  },
  emptyContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    padding: spacing.xl,
  },
  emptyText: {
    ...typography.transcript,
    color: colors.textDim,
    textAlign: 'center',
  },
  entry: {
    marginTop: spacing.md,
  },
  roleLabel: {
    fontSize: 12,
    fontWeight: '600',
    color: colors.textDim,
    textTransform: 'uppercase',
    letterSpacing: 1,
    marginBottom: spacing.xs,
  },
});
