/**
 * Web presentation only: renders the app inside a phone, so the browser demo
 * looks and behaves like the mobile app (393 x 852 points, the size of a
 * current iPhone). On iOS/Android, and in a browser narrower than a phone
 * frame needs (or one opened on an actual phone), it renders the app as is.
 *
 * Inside the frame the app sees real safe-area insets (status bar and home
 * indicator), so every screen lays out exactly as it does on a device. The
 * status bar shows "No service" while Profile → "Offline mode" is on.
 *
 * Add ?frame=0 to the URL for the full-width layout.
 */
import { Ionicons } from '@expo/vector-icons';
import { usePathname } from 'expo-router';
import { type ReactNode, useEffect, useState } from 'react';
import { Platform, Pressable, StyleSheet, Text, useWindowDimensions, View } from 'react-native';
import { SafeAreaFrameContext, SafeAreaInsetsContext } from 'react-native-safe-area-context';
import { api } from '../api';
import { useData } from '../data/DataContext';
import { theme } from '../theme';
import { CouchbaseLogo } from './components';

const PHONE_W = 393;
const PHONE_H = 852;
const BEZEL = 12;
const INSETS = { top: 54, bottom: 30, left: 0, right: 0 };
// Screens whose top edge is light, so the status bar text goes dark.
const LIGHT_TOP = ['/activity', '/profile'];
// Screens whose bottom edge is dark (no tab bar), so the home indicator goes light.
const DARK_BOTTOM = ['/login'];

/** Solid status-bar strip in the colour of the screen's top edge, so content
 * scrolling underneath never collides with the clock. */
function statusBackground(_pathname: string, lightTop: boolean): string {
  return lightTop ? 'rgba(247,247,247,0.97)' : theme.color.ink;
}

function frameWanted(): boolean {
  if (Platform.OS !== 'web' || typeof window === 'undefined') return false;
  try {
    return new URLSearchParams(window.location.search).get('frame') !== '0';
  } catch {
    return true;
  }
}

function Clock({ color }: { color: string }) {
  const fmt = () => {
    const d = new Date();
    return `${((d.getHours() + 11) % 12) + 1}:${String(d.getMinutes()).padStart(2, '0')}`;
  };
  const [t, setT] = useState(fmt);
  useEffect(() => {
    const id = setInterval(() => setT(fmt()), 15000);
    return () => clearInterval(id);
  }, []);
  return <Text style={[styles.clock, { color }]}>{t}</Text>;
}

function StatusBarOverlay({ dark, offline, background }: { dark: boolean; offline: boolean; background: string }) {
  const c = dark ? theme.color.text : '#FFFFFF';
  return (
    <View pointerEvents="none" style={[styles.statusBar, { backgroundColor: background }]}>
      <View style={styles.statusSide}><Clock color={c} /></View>
      <View style={styles.island} />
      <View style={[styles.statusSide, { justifyContent: 'flex-end', gap: 6 }]}>
        {offline ? (
          <Text style={[styles.noService, { color: c }]}>No service</Text>
        ) : (
          <>
            <Ionicons name="cellular" size={15} color={c} />
            <Ionicons name="wifi" size={16} color={c} />
          </>
        )}
        <Ionicons name="battery-full" size={22} color={c} />
      </View>
    </View>
  );
}

function SidePanel() {
  const [reset, setReset] = useState<{ busy: boolean; line: string }>({ busy: false, line: '' });
  const resetDemo = async () => {
    if (!window.confirm("Reset the demo? Maya, Daniel and Sofia go back to today's export (requests, policies, claims, bills, trips, cover, chat, cached context), their Couchbase Labs Agent Operations Manager memories are deleted and the app's Couchbase Labs Agent Operations Manager caches are purged.")) return;
    setReset({ busy: true, line: 'Resetting…' });
    try {
      const r = await api<{ summary: { users: number; requests_removed: number; memories_deleted: number }; export_date: string }>(
        '/api/demo/reset', { method: 'POST', body: {}, timeoutMs: 120000 });
      setReset({ busy: false, line: `Reset done: ${r.summary.users} people back to export ${r.export_date}, ${r.summary.requests_removed} requests removed, ${r.summary.memories_deleted} Couchbase Labs Agent Operations Manager memories deleted. Reloading…` });
      setTimeout(() => window.location.assign('/login'), 1200);
    } catch (e) {
      setReset({ busy: false, line: `Reset failed: ${(e as Error).message}` });
    }
  };
  return (
    <View style={styles.panel}>
      <CouchbaseLogo light={false} height={30} />
      <Text style={styles.kicker}>INSURANCE · DEMO</Text>
      <Text style={styles.panelTitle}>One insurance app, seven governed agents</Text>
      <Text style={styles.panelBody}>
        ID cards, claims, roadside, payments, telematics, support, wellness and on-demand cover in one app. Every screen renders from the
        on-device database, and every answer and action is governed by the Couchbase Labs Agent Operations Manager.
      </Text>
      {[
        ['phone-portrait-outline', 'Couchbase Lite', 'Offline-first: ID cards open with no signal; claims, roadside calls, payments and trips queue on the phone and sync when it reconnects'],
        ['sparkles-outline', 'LLM and Context Caching', 'Shared answers are generated once; personal context from policy, member and on-demand systems is built once and reused'],
        ['shield-checkmark-outline', 'Governed agents', 'Seven agents, one per area of the app, each with its own tool scope and Agent Memory; two scoped knowledge apps keep member-only guidance out of other answers'],
      ].map(([icon, title, body]) => (
        <View key={title} style={styles.point}>
          <Ionicons name={icon as keyof typeof Ionicons.glyphMap} size={18} color={theme.color.red} />
          <View style={{ flex: 1 }}>
            <Text style={styles.pointTitle}>{title}</Text>
            <Text style={styles.pointBody}>{body}</Text>
          </View>
        </View>
      ))}
      <Pressable onPress={() => window.location.assign('/story')} style={styles.storyBtn}>
        <Ionicons name="book-outline" size={16} color={theme.color.onDark} />
        <Text style={styles.storyText}>The story: one insurance app, a fraction of the model calls</Text>
      </Pressable>
      <Pressable onPress={resetDemo} disabled={reset.busy} style={[styles.resetBtn, reset.busy && { opacity: 0.6 }]}>
        <Ionicons name="refresh-outline" size={16} color={theme.color.ink} />
        <Text style={styles.resetText}>{reset.busy ? 'Resetting…' : 'Reset demo'}</Text>
      </Pressable>
      {reset.line ? <Text style={styles.panelFoot}>{reset.line}</Text> : null}
    </View>
  );
}

export function DeviceFrame({ children }: { children: ReactNode }) {
  const { width, height } = useWindowDimensions();
  const pathname = usePathname();
  const { offline } = useData();
  const [wanted] = useState(frameWanted);
  // A real phone (or a very narrow window) gets the app edge to edge.
  if (!wanted || width < PHONE_W + 2 * BEZEL + 40) return <>{children}</>;

  const outerH = PHONE_H + 2 * BEZEL;
  const scale = Math.min(1, (height - 40) / outerH);
  const showPanel = width >= 980;
  const darkStatus = LIGHT_TOP.some((p) => pathname === p || pathname.startsWith(`${p}/`));
  const lightIndicator = DARK_BOTTOM.includes(pathname);

  return (
    <View style={styles.stage}>
      <View style={[styles.row, { gap: showPanel ? 72 : 0 }]}>
        {showPanel ? <SidePanel /> : null}
        <View style={{ width: (PHONE_W + 2 * BEZEL) * scale, height: outerH * scale }}>
          <View style={[styles.phone, { transform: [{ scale }], transformOrigin: 'top left' } as object]}>
            <View style={styles.screen}>
              <SafeAreaFrameContext.Provider value={{ x: 0, y: 0, width: PHONE_W, height: PHONE_H }}>
                <SafeAreaInsetsContext.Provider value={INSETS}>{children}</SafeAreaInsetsContext.Provider>
              </SafeAreaFrameContext.Provider>
              <StatusBarOverlay dark={darkStatus} offline={offline} background={statusBackground(pathname, darkStatus)} />
              <View
                pointerEvents="none"
                style={[styles.homeIndicator, { backgroundColor: lightIndicator ? '#FFFFFF' : theme.color.text }]}
              />
            </View>
          </View>
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  stage: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: theme.color.bg,
    backgroundImage: 'radial-gradient(1200px 700px at 30% 20%, #FFFFFF 0%, #FFF0DA 60%, #FBCE90 100%)',
  } as object,
  row: { flexDirection: 'row', alignItems: 'center' },
  phone: {
    width: PHONE_W + 2 * BEZEL,
    height: PHONE_H + 2 * BEZEL,
    padding: BEZEL,
    borderRadius: 64,
    backgroundColor: '#0B0B0B',
    boxShadow: '0 40px 80px rgba(0,0,0,0.35), 0 0 0 2px #2A2A2A inset',
  } as object,
  screen: { flex: 1, borderRadius: 52, overflow: 'hidden', backgroundColor: theme.color.bg },
  statusBar: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    height: INSETS.top,
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 28,
    zIndex: 10,
  },
  statusSide: { flex: 1, flexDirection: 'row', alignItems: 'center' },
  clock: { fontSize: 16, fontWeight: '700', letterSpacing: 0.2, paddingLeft: 8 },
  noService: { fontSize: 13, fontWeight: '600' },
  island: { width: 122, height: 36, borderRadius: 20, backgroundColor: '#000' },
  homeIndicator: {
    position: 'absolute',
    bottom: 8,
    alignSelf: 'center',
    width: 134,
    height: 5,
    borderRadius: 3,
    opacity: 0.85,
    zIndex: 10,
  },
  panel: { width: 340, gap: 14 },
  kicker: { color: theme.color.ink, fontSize: 12, fontWeight: '700', letterSpacing: 1.6, marginTop: 6 },
  panelTitle: { color: theme.color.ink, fontSize: 38, fontWeight: '600', fontFamily: theme.font.display, lineHeight: 42, letterSpacing: -1 },
  panelBody: { color: theme.color.body, fontSize: 15, lineHeight: 22, marginBottom: 6 },
  point: { flexDirection: 'row', gap: 12, alignItems: 'flex-start', backgroundColor: '#FFFFFF', padding: 14, borderRadius: 18, boxShadow: '0 0 24px rgba(0,0,0,0.08)' } as object,
  pointTitle: { color: theme.color.ink, fontWeight: '700', fontSize: 15 },
  pointBody: { color: theme.color.muted, fontSize: 13, lineHeight: 18, marginTop: 2 },
  storyBtn: { flexDirection: 'row', gap: 8, alignItems: 'center', alignSelf: 'flex-start', backgroundColor: theme.color.red, borderRadius: 12, paddingHorizontal: 16, paddingVertical: 11, marginTop: 4 },
  storyText: { color: theme.color.onDark, fontWeight: '600', fontSize: 14 },
  resetBtn: { flexDirection: 'row', gap: 8, alignItems: 'center', alignSelf: 'flex-start', backgroundColor: theme.color.surface, borderWidth: 1.5, borderColor: theme.color.ink, borderRadius: 12, paddingHorizontal: 16, paddingVertical: 10 },
  resetText: { color: theme.color.ink, fontWeight: '600', fontSize: 14 },
  panelFoot: { color: theme.color.muted, fontSize: 12, lineHeight: 18, marginTop: 6 },
});
