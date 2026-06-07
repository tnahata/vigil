import { View, Text, StyleSheet } from 'react-native';
import type { AppState } from '../types';
import { colors, spacing, typography } from '../theme';

interface StatusIndicatorProps {
  readonly state: AppState;
}

const STATUS_CONFIG: Record<AppState, { readonly label: string; readonly color: string }> = {
  disconnected: { label: 'Disconnected', color: colors.textDim },
  connecting: { label: 'Connecting...', color: colors.warning },
  idle: { label: 'Listening', color: colors.accent },
  listening: { label: 'Hearing query...', color: colors.accent },
  processing: { label: 'Processing...', color: colors.warning },
  speaking: { label: 'Speaking...', color: colors.textPrimary },
};

export function StatusIndicator({ state }: StatusIndicatorProps): React.JSX.Element {
  const config = STATUS_CONFIG[state];

  return (
    <View style={styles.container}>
      <View style={[styles.dot, { backgroundColor: config.color }]} />
      <Text style={[typography.status, { color: config.color }]}>{config.label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  dot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    marginRight: spacing.sm,
  },
});
