import { StyleSheet } from 'react-native';
import { theme } from '../theme';

/** Shared styles for the modal action screens. */
export const form = StyleSheet.create({
  body: { padding: 16, maxWidth: 640, width: '100%', alignSelf: 'center', paddingBottom: 40 },
  h2: { fontSize: theme.type.xl, fontWeight: '600', fontFamily: theme.font.display, color: theme.color.ink, letterSpacing: -0.3 },
  h3: { fontSize: theme.type.lg, fontWeight: '600', fontFamily: theme.font.display, color: theme.color.ink },
  meta: { color: theme.color.muted, fontSize: theme.type.sm, lineHeight: 19 },
  tiny: { color: theme.color.faint, fontSize: theme.type.xs, textAlign: 'center', marginTop: 10 },
  opt: { flexDirection: 'row', alignItems: 'center', gap: 10, padding: 14, marginBottom: 10, borderWidth: 2, borderColor: 'transparent' },
  optSel: { borderColor: theme.color.ink },
  input: { borderWidth: 1, borderColor: theme.color.border, borderRadius: theme.radiusSm, padding: 13, fontSize: theme.type.md, color: theme.color.text, backgroundColor: theme.color.surface },
  seg: { flexDirection: 'row', backgroundColor: theme.color.surface, borderRadius: theme.radiusSm, padding: 4, marginVertical: 12, borderWidth: 1, borderColor: theme.color.border },
  segBtn: { flex: 1, paddingVertical: 10, borderRadius: 9, alignItems: 'center' },
  segOn: { backgroundColor: theme.color.ink },
  segText: { fontWeight: '700', color: theme.color.muted },
  stepper: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 22 },
  step: { width: 44, height: 44, borderRadius: theme.radiusSm, backgroundColor: theme.color.peach, alignItems: 'center', justifyContent: 'center' },
  big: { fontSize: 38, fontWeight: '600', fontFamily: theme.font.display, color: theme.color.ink, textAlign: 'center', letterSpacing: -1 },
  rowBetween: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
});
export const OFFLINE_NOTE = 'Works offline: your request is saved in Couchbase Lite and sent when you reconnect.';
