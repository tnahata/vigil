import { SafeAreaView, View, Text, Pressable, StyleSheet } from 'react-native';
import { StatusBar } from 'expo-status-bar';
import * as Haptics from 'expo-haptics';
import { useAgentSession } from './src/hooks/useAgentSession';
import { StatusIndicator } from './src/components/StatusIndicator';
import { GlanceCard } from './src/components/GlanceCard';
import { TranscriptView } from './src/components/TranscriptView';
import { colors, spacing } from './src/theme';

export default function App(): React.JSX.Element {
  const { appState, transcript, currentCard, triggerMockQuery } = useAgentSession();

  const handleMockTrigger = (): void => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    triggerMockQuery();
  };

  const canTrigger = appState === 'idle' || appState === 'disconnected' || appState === 'speaking';

  const buttonLabel = (): string => {
    switch (appState) {
      case 'processing': return 'Processing...';
      default: return 'Simulate Query';
    }
  };

  return (
    <SafeAreaView style={styles.container}>
      <StatusBar style="light" />

      <StatusIndicator state={appState} />

      <View style={styles.cardSection}>
        {currentCard ? (
          <GlanceCard data={currentCard} />
        ) : (
          <View style={styles.placeholder}>
            <Text style={styles.placeholderTitle}>VIGIL</Text>
            <Text style={styles.placeholderSubtitle}>Voice Copilot for EMTs</Text>
          </View>
        )}
      </View>

      <View style={styles.transcriptSection}>
        <TranscriptView entries={transcript} />
      </View>

      <View style={styles.mockTrigger}>
        <Pressable
          onPress={handleMockTrigger}
          disabled={!canTrigger}
          style={({ pressed }) => [
            styles.mockButton,
            pressed && styles.mockButtonPressed,
            !canTrigger && styles.mockButtonDisabled,
          ]}
        >
          <Text style={[styles.mockButtonText, !canTrigger && styles.mockButtonTextDisabled]}>
            {buttonLabel()}
          </Text>
        </Pressable>
        <Text style={styles.mockHint}>Dev mode — simulates wake word + query</Text>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },
  cardSection: {
    justifyContent: 'center',
    minHeight: 200,
  },
  placeholder: {
    alignItems: 'center',
    padding: spacing.xl,
  },
  placeholderTitle: {
    fontSize: 36,
    fontWeight: '800',
    color: colors.textDim,
    letterSpacing: 8,
  },
  placeholderSubtitle: {
    fontSize: 14,
    color: colors.textDim,
    marginTop: spacing.sm,
    letterSpacing: 2,
  },
  transcriptSection: {
    flex: 1,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.border,
  },
  mockTrigger: {
    padding: spacing.md,
    alignItems: 'center',
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.border,
  },
  mockButton: {
    backgroundColor: colors.surfaceElevated,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm + 4,
    borderRadius: 20,
    borderWidth: 1,
    borderColor: colors.border,
  },
  mockButtonPressed: {
    opacity: 0.7,
  },
  mockButtonDisabled: {
    opacity: 0.4,
  },
  mockButtonText: {
    color: colors.textSecondary,
    fontSize: 14,
    fontWeight: '500',
  },
  mockButtonTextDisabled: {
    color: colors.textDim,
  },
  mockHint: {
    color: colors.textDim,
    fontSize: 11,
    marginTop: spacing.xs,
  },
});
