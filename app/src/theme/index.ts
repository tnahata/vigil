import { Platform, StyleSheet } from 'react-native';

export const colors = {
  background: '#0A0A0C',
  surface: '#1A1A1F',
  surfaceElevated: '#252530',
  textPrimary: '#FFFFFF',
  textSecondary: '#8E8E93',
  textDim: '#636366',
  accent: '#32D74B',
  danger: '#FF453A',
  warning: '#FFD60A',
  border: '#2C2C2E',
} as const;

export const spacing = {
  xs: 4,
  sm: 8,
  md: 16,
  lg: 24,
  xl: 32,
  xxl: 48,
} as const;

export const typography = StyleSheet.create({
  drugName: {
    fontSize: 38,
    fontWeight: '800' as const,
    color: colors.textPrimary,
    letterSpacing: 1,
    textAlign: 'center' as const,
    ...Platform.select({
      ios: { fontFamily: 'System' },
    }),
  },
  dose: {
    fontSize: 36,
    fontWeight: '600' as const,
    color: colors.textPrimary,
    textAlign: 'center' as const,
    ...Platform.select({
      ios: { fontFamily: 'System' },
    }),
  },
  route: {
    fontSize: 20,
    fontWeight: '500' as const,
    color: colors.textSecondary,
    textTransform: 'uppercase' as const,
    letterSpacing: 2,
    textAlign: 'center' as const,
    ...Platform.select({
      ios: { fontFamily: 'System' },
    }),
  },
  contraindication: {
    fontSize: 16,
    fontWeight: '600' as const,
    color: colors.danger,
    textAlign: 'center' as const,
    ...Platform.select({
      ios: { fontFamily: 'System' },
    }),
  },
  protocolId: {
    fontSize: 12,
    fontWeight: '400' as const,
    color: colors.textDim,
    textAlign: 'center' as const,
    ...Platform.select({
      ios: { fontFamily: 'System' },
    }),
  },
  status: {
    fontSize: 14,
    fontWeight: '500' as const,
    color: colors.textSecondary,
    ...Platform.select({
      ios: { fontFamily: 'System' },
    }),
  },
  transcript: {
    fontSize: 15,
    fontWeight: '400' as const,
    color: colors.textSecondary,
    lineHeight: 22,
    ...Platform.select({
      ios: { fontFamily: 'System' },
    }),
  },
  transcriptAgent: {
    fontSize: 15,
    fontWeight: '400' as const,
    color: colors.textPrimary,
    lineHeight: 22,
    ...Platform.select({
      ios: { fontFamily: 'System' },
    }),
  },
});
