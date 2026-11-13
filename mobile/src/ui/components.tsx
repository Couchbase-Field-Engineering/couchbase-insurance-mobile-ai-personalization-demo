import { Ionicons } from '@expo/vector-icons';
import { LinearGradient } from 'expo-linear-gradient';
import React from 'react';
import { ActivityIndicator, Image, Pressable, StyleSheet, Text, View, type StyleProp, type ViewStyle } from 'react-native';
import { theme } from '../theme';
import type { Area, RequestStatus, SyncState } from '../types';

export type IconName = React.ComponentProps<typeof Ionicons>['name'];

/**
 * The Couchbase logo as it appears in the couchbase.com header: the red mark
 * with the wordmark beside it (assets/brand/*.svg are the vector sources;
 * the PNGs here are rendered from them). `light` picks the white wordmark
 * for black surfaces.
 */
const LOGO_DARK_TEXT = require('../../assets/images/couchbase-logo.png');
const LOGO_WHITE_TEXT = require('../../assets/images/couchbase-logo-white.png');
const MARK = require('../../assets/images/brand-logo.png');
const LOGO_RATIO = 584 / 120;

export function CouchbaseLogo({ light = true, height = 22 }: { light?: boolean; height?: number }) {
  return (
    <Image source={light ? LOGO_WHITE_TEXT : LOGO_DARK_TEXT} style={{ height, width: height * LOGO_RATIO }} resizeMode="contain" accessibilityLabel="Couchbase" />
  );
}

export function CouchbaseMark({ size = 28 }: { size?: number }) {
  return <Image source={MARK} style={{ width: size, height: size }} resizeMode="contain" accessibilityLabel="Couchbase" />;
}

/** Product lockup: the Couchbase logo, a divider, and the product name. */
export function Wordmark({ light = true, height = 20 }: { light?: boolean; height?: number }) {
  const c = light ? theme.color.onDark : theme.color.ink;
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', gap: 10 }}>
      <CouchbaseLogo light={light} height={height} />
      <View style={{ width: 1, height: height * 0.9, backgroundColor: light ? 'rgba(255,255,255,0.35)' : theme.color.border }} />
      <Text style={{ color: c, fontSize: height * 0.82, fontWeight: '600', fontFamily: theme.font.display, letterSpacing: -0.2 }}>Harborline</Text>
    </View>
  );
}

/** couchbase.com eyebrow: small, bold, uppercase, wide tracking. */
export function Eyebrow({ children, color }: { children: React.ReactNode; color?: string }) {
  return <Text style={[styles.eyebrow, color ? { color } : null]}>{children}</Text>;
}

export function Card({ children, style }: { children: React.ReactNode; style?: StyleProp<ViewStyle> }) {
  return <View style={[styles.card, style]}>{children}</View>;
}

export function GradientArt({ palette, icon, height = 96, children }: { palette: string; icon: IconName; height?: number; children?: React.ReactNode }) {
  const colors = (theme.gradient as Record<string, readonly [string, string]>)[palette] ?? theme.gradient.ink;
  return (
    <LinearGradient colors={colors as unknown as [string, string]} start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }} style={{ height, borderTopLeftRadius: theme.radius, borderTopRightRadius: theme.radius, padding: 14, justifyContent: 'space-between' }}>
      <View style={styles.art} pointerEvents="none">
        <Ionicons name={icon} size={height * 0.95} color="rgba(255,255,255,0.12)" />
      </View>
      {children}
    </LinearGradient>
  );
}

export type Tone = 'neutral' | 'red' | 'orange' | 'ok' | 'warn' | 'danger' | 'ink' | 'dark';

export function Pill({ label, tone = 'neutral', icon }: { label: string; tone?: Tone; icon?: IconName }) {
  const map: Record<Tone, readonly [string, string]> = {
    neutral: [theme.color.bg, theme.color.muted],
    red: [theme.color.redSoft, theme.color.redActive],
    orange: [theme.color.peach, theme.color.warn],
    ok: [theme.color.okSoft, theme.color.ok],
    warn: [theme.color.peach, theme.color.warn],
    danger: [theme.color.dangerSoft, theme.color.danger],
    ink: [theme.color.ink, theme.color.onDark],
    dark: ['rgba(255,255,255,0.16)', theme.color.onDark],
  };
  const [bg, fg] = map[tone];
  return (
    <View style={[styles.pill, { backgroundColor: bg }]}>
      {icon ? <Ionicons name={icon} size={11} color={fg} /> : null}
      <Text style={{ color: fg, fontSize: theme.type.xs, fontWeight: '700' }}>{label}</Text>
    </View>
  );
}

export const AREA_UI: Record<Area | 'memory', { label: string; short: string; icon: IconName }> = {
  documents: { label: 'ID Cards & Documents', short: 'Cards', icon: 'card' },
  claims: { label: 'Claims', short: 'Claims', icon: 'camera' },
  roadside: { label: 'Roadside & Emergency', short: 'Roadside', icon: 'car-sport' },
  billing: { label: 'Payments & Renewals', short: 'Pay', icon: 'wallet' },
  telematics: { label: 'DriveWell Telematics', short: 'DriveWell', icon: 'speedometer' },
  support: { label: 'Customer Support', short: 'Support', icon: 'help-buoy' },
  wellness: { label: 'Health & Wellness', short: 'Wellness', icon: 'fitness' },
  coverage: { label: 'On-Demand Coverage', short: 'On-demand', icon: 'flash' },
  memory: { label: 'Memory', short: 'Memory', icon: 'bookmark' },
};

/** Which of the app's eight areas handled something. */
export function AreaTag({ area, dark }: { area?: string; dark?: boolean }) {
  const ui = AREA_UI[(area ?? 'support') as Area] ?? AREA_UI.support;
  const color = theme.area[area ?? 'support'] ?? theme.color.red;
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', gap: 5 }}>
      <View style={{ width: 7, height: 7, borderRadius: 4, backgroundColor: dark && (area === 'support' || area === 'documents') ? theme.color.onDark : color }} />
      <Ionicons name={ui.icon} size={11} color={dark ? theme.color.onDarkMuted : theme.color.muted} />
      <Text style={{ fontSize: theme.type.xs, fontWeight: '800', letterSpacing: 0.8, color: dark ? theme.color.onDarkMuted : theme.color.muted }}>
        {ui.label.toUpperCase()}
      </Text>
    </View>
  );
}

export function Button({ label, onPress, kind = 'primary', icon, disabled, busy, small }: {
  label: string; onPress: () => void; kind?: 'primary' | 'ink' | 'ghost' | 'light'; icon?: IconName; disabled?: boolean; busy?: boolean; small?: boolean;
}) {
  // couchbase.com's call to action: a red button, white text, 12px corners.
  const bg = { primary: theme.color.red, ink: theme.color.ink, ghost: 'transparent', light: theme.color.surface }[kind];
  const fg = { primary: theme.color.onDark, ink: theme.color.onDark, ghost: theme.color.ink, light: theme.color.ink }[kind];
  return (
    <Pressable
      onPress={onPress}
      disabled={disabled || busy}
      style={({ pressed }) => [
        styles.btn,
        small && styles.btnSmall,
        { backgroundColor: pressed && kind === 'primary' ? theme.color.redActive : bg, opacity: disabled ? 0.4 : pressed ? 0.9 : 1 },
        kind === 'ghost' && { borderWidth: 1.5, borderColor: theme.color.ink },
      ]}
    >
      {busy ? <ActivityIndicator color={fg} /> : icon ? <Ionicons name={icon} size={small ? 14 : 17} color={fg} /> : null}
      <Text style={{ color: fg, fontWeight: '600', fontFamily: theme.font.display, fontSize: small ? theme.type.sm : theme.type.md }}>{label}</Text>
    </Pressable>
  );
}

export function SectionTitle({ title, action }: { title: string; action?: React.ReactNode }) {
  return (
    <View style={styles.section}>
      <Eyebrow>{title}</Eyebrow>
      {action}
    </View>
  );
}

const SYNC_LABEL: Record<SyncState['status'], [string, 'ok' | 'warn' | 'danger' | 'neutral' | 'busy']> = {
  connecting: ['Connecting', 'busy'],
  connected: ['Synced', 'ok'],
  idle: ['Synced', 'ok'],
  busy: ['Syncing', 'busy'],
  offline: ['Offline', 'warn'],
  paused: ['Offline mode', 'warn'],
  error: ['Sync error', 'danger'],
  stopped: ['Local only', 'neutral'],
};

export function SyncBadge({ sync, dark }: { sync: SyncState; dark?: boolean }) {
  const [label, tone] = SYNC_LABEL[sync.status];
  const text = sync.pendingPush ? `${label} · ${sync.pendingPush} to send` : label;
  const dot = { ok: '#21EA2A', warn: theme.color.orange, danger: theme.color.red, neutral: theme.color.faint, busy: theme.color.orangeSoft }[tone];
  return (
    <View style={[styles.sync, dark ? { backgroundColor: theme.color.onDarkFaint } : { backgroundColor: theme.color.bg }]}>
      <View style={[styles.dot, { backgroundColor: dot }]} />
      <Text style={{ color: dark ? theme.color.onDark : theme.color.text, fontSize: theme.type.xs, fontWeight: '700' }}>
        {sync.engine === 'couchbase-lite' ? 'Couchbase Lite · ' : 'Preview · '}
        {text}
      </Text>
    </View>
  );
}

export const STATUS_UI: Record<RequestStatus, { label: string; tone: Tone; icon: IconName }> = {
  pending: { label: 'Waiting to sync', tone: 'warn', icon: 'cloud-upload-outline' },
  processing: { label: 'Processing', tone: 'neutral', icon: 'sync' },
  awaiting_approval: { label: 'Awaiting approval', tone: 'warn', icon: 'shield-checkmark-outline' },
  confirmed: { label: 'Done', tone: 'ok', icon: 'checkmark-circle' },
  accepted: { label: 'Accepted', tone: 'ok', icon: 'checkmark-circle' },
  submitted: { label: 'Submitted', tone: 'neutral', icon: 'time-outline' },
  failed: { label: 'Not completed', tone: 'danger', icon: 'alert-circle' },
};

export function Empty({ icon, title, body }: { icon: IconName; title: string; body: string }) {
  return (
    <View style={{ alignItems: 'center', padding: theme.space.xl, gap: 6 }}>
      <Ionicons name={icon} size={34} color={theme.color.faint} />
      <Text style={{ fontWeight: '700', color: theme.color.text, fontSize: theme.type.md }}>{title}</Text>
      <Text style={{ color: theme.color.muted, textAlign: 'center' }}>{body}</Text>
    </View>
  );
}

export function Field({ icon, label, value }: { icon: IconName; label: string; value: string }) {
  return (
    <View style={{ flexDirection: 'row', gap: 10, alignItems: 'flex-start' }}>
      <Ionicons name={icon} size={16} color={theme.color.red} style={{ marginTop: 1 }} />
      <Text style={{ color: theme.color.muted, fontSize: theme.type.sm, width: 118 }}>{label}</Text>
      <Text style={{ flex: 1, color: theme.color.text, fontWeight: '600', fontSize: theme.type.sm }} selectable>{value}</Text>
    </View>
  );
}

export const money = (n: number | undefined | null) =>
  n == null ? '' : `$${Number(n).toLocaleString('en-US', { maximumFractionDigits: n % 1 ? 2 : 0, minimumFractionDigits: n % 1 ? 2 : 0 })}`;

export function fmtDate(iso: string | null | undefined, opts: Intl.DateTimeFormatOptions = { weekday: 'short', month: 'short', day: 'numeric' }) {
  if (!iso) return '';
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number);
  return new Date(y, m - 1, d).toLocaleDateString('en-US', opts);
}

export function daysBetween(iso: string, today: string) {
  const [a, b] = [new Date(iso.slice(0, 10)), new Date(today.slice(0, 10))];
  return Math.round((a.getTime() - b.getTime()) / 86400000);
}

export const styles = StyleSheet.create({
  card: { backgroundColor: theme.color.surface, borderRadius: theme.radius, ...theme.shadow.card },
  art: { position: 'absolute', right: -6, bottom: -14 },
  pill: { flexDirection: 'row', alignItems: 'center', gap: 4, paddingHorizontal: 8, paddingVertical: 3, borderRadius: 999, alignSelf: 'flex-start' },
  btn: { flexDirection: 'row', gap: 8, alignItems: 'center', justifyContent: 'center', paddingVertical: 14, paddingHorizontal: 18, borderRadius: theme.radiusSm },
  btnSmall: { paddingVertical: 8, paddingHorizontal: 14, borderRadius: 10 },
  section: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginTop: theme.space.xl, marginBottom: theme.space.sm },
  eyebrow: { color: theme.color.ink, fontSize: theme.type.xs, fontWeight: '700', letterSpacing: 1.6, textTransform: 'uppercase' },
  sync: { flexDirection: 'row', alignItems: 'center', gap: 6, paddingHorizontal: 10, paddingVertical: 5, borderRadius: 999, alignSelf: 'flex-start' },
  dot: { width: 7, height: 7, borderRadius: 4 },
});
