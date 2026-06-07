import { useEffect } from 'react';
import { SafeAreaView, View, Text, StyleSheet } from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { useAgentSession } from './src/hooks/useAgentSession';
import { StatusIndicator } from './src/components/StatusIndicator';
import { GlanceCard } from './src/components/GlanceCard';
import { TranscriptView } from './src/components/TranscriptView';
import { colors, spacing } from './src/theme';

export default function App(): React.JSX.Element {
  const { appState, transcript, currentCard, connect } = useAgentSession();

  useEffect(() => {
    connect();
  }, [connect]);

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
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },
  cardSection: {
    flex: 3,
    justifyContent: 'center',
    alignItems: 'stretch',
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
});
