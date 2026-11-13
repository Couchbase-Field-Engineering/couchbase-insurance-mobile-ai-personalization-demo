import { Ionicons } from '@expo/vector-icons';
import { Redirect } from 'expo-router';
import { useEffect, useState } from 'react';
import { KeyboardAvoidingView, Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { api, type Persona } from '@/src/api';
import { API_URL } from '@/src/config';
import { useAuth } from '@/src/session/AuthContext';
import { theme } from '@/src/theme';
import { AREA_UI, Button, Eyebrow, Wordmark, type IconName } from '@/src/ui/components';

const FALLBACK: Persona[] = [
  { user_id: 'P00000101', name: 'Maya Chen', last_name: 'Chen', account_id: '5510101', audience: 'policyholder', audience_label: 'Policyholder', headline: 'Auto + Home · Brooklyn, NY', blurb: 'ID cards, an open claim, a bill due, a renewal and a DriveWell score.' },
  { user_id: 'M00000201', name: 'Daniel Okafor', last_name: 'Okafor', account_id: '5520202', audience: 'member', audience_label: 'Health & pet member', headline: 'Health + Pet · Austin, TX', blurb: 'Telehealth, a deductible in progress, vet bills and a wearable to link.' },
  { user_id: 'O00000301', name: 'Sofia Alvarez', last_name: 'Alvarez', account_id: '5530303', audience: 'ondemand', audience_label: 'On-demand customer', headline: 'On-demand cover · Charlotte, NC', blurb: 'Borrowing a car this weekend and flying to Lisbon: cover by the day.' },
];
const AUDIENCE_ICON: Record<string, IconName> = { policyholder: 'car', member: 'fitness', ondemand: 'flash' };
const AUDIENCE_AREAS: Record<string, (keyof typeof AREA_UI)[]> = {
  policyholder: ['documents', 'claims', 'roadside', 'billing', 'telematics'], member: ['wellness', 'billing', 'documents'], ondemand: ['coverage', 'roadside', 'support'],
};

export default function Login() {
  const { session, signIn, notice } = useAuth();
  const insets = useSafeAreaInsets();
  const [account, setAccount] = useState('');
  const [last, setLast] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [personas, setPersonas] = useState<Persona[]>(FALLBACK);

  useEffect(() => {
    api<{ personas: Persona[] }>('/api/demo/personas', { timeoutMs: 5000 })
      .then((r) => r.personas.length && setPersonas(r.personas))
      .catch(() => {});
  }, []);

  if (session) return <Redirect href="/(tabs)" />;

  const go = async (a = account, l = last) => {
    setBusy(true);
    setErr(null);
    try {
      await signIn(a, l);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <KeyboardAvoidingView style={{ flex: 1, backgroundColor: theme.color.ink }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <ScrollView contentContainerStyle={[styles.wrap, { paddingTop: insets.top + 28, paddingBottom: insets.bottom + 24 }]} keyboardShouldPersistTaps="handled">
        <Wordmark height={22} />
        <View style={{ marginTop: 26, gap: 10 }}>
          <Eyebrow color={theme.color.onDark}>Insurance that knows you, even with no signal.</Eyebrow>
          <Text style={styles.hero}>Your cover,{'\n'}in your pocket.</Text>
          <Text style={styles.sub}>
            ID cards, claims, roadside help, payments, DriveWell, wellness and cover by the day - personalized from your own policies, run by governed AI agents, and still working when you're offline.
          </Text>
        </View>

        <View style={styles.form}>
          {notice ? (
            <View style={styles.notice}>
              <Ionicons name="time-outline" size={16} color={theme.color.ink} />
              <Text style={styles.noticeText}>{notice}</Text>
            </View>
          ) : null}
          <Text style={styles.label}>ACCOUNT NUMBER</Text>
          <TextInput value={account} onChangeText={setAccount} placeholder="e.g. 5510101" placeholderTextColor={theme.color.faint} style={styles.input} keyboardType="number-pad" />
          <Text style={styles.label}>LAST NAME</Text>
          <TextInput value={last} onChangeText={setLast} placeholder="e.g. Chen" placeholderTextColor={theme.color.faint} style={styles.input} autoCapitalize="words" />
          {err ? <Text style={styles.err}>{err}</Text> : null}
          <Button label="Sign in" onPress={() => void go()} busy={busy} disabled={!account || !last} icon="arrow-forward" />
        </View>

        <View style={{ marginTop: 28, marginBottom: 2 }}>
          <Eyebrow color={theme.color.onDarkMuted}>Demo sign-ins · one per kind of customer</Eyebrow>
        </View>
        {personas.map((p) => (
          <Pressable key={p.user_id} onPress={() => void go(p.account_id, p.last_name)} style={({ pressed }) => [styles.persona, pressed && { opacity: 0.8 }]}>
            <View style={styles.avatar}>
              <Ionicons name={AUDIENCE_ICON[p.audience] ?? 'person'} size={20} color={theme.color.onDark} />
            </View>
            <View style={{ flex: 1, gap: 3 }}>
              <View style={{ flexDirection: 'row', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                <Text style={styles.pname}>{p.name}</Text>
                <Text style={styles.paud}>{p.audience_label.toUpperCase()}</Text>
              </View>
              <Text style={styles.pmeta}>{p.headline} · #{p.account_id}</Text>
              <Text style={styles.pblurb}>{(AUDIENCE_AREAS[p.audience] ?? []).map((a) => AREA_UI[a].short).join(' · ')}</Text>
            </View>
            <Ionicons name="chevron-forward" size={18} color={theme.color.onDarkMuted} />
          </Pressable>
        ))}
        <Text style={styles.foot}>Demo company: Harborline (fictional) · Backend: {API_URL}</Text>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  wrap: { paddingHorizontal: 22, gap: 10, maxWidth: 520, width: '100%', alignSelf: 'center' },
  hero: { color: theme.color.onDark, fontSize: theme.type.hero, fontWeight: '600', fontFamily: theme.font.display, lineHeight: 38, letterSpacing: -0.5 },
  sub: { color: theme.color.onDarkMuted, fontSize: theme.type.md, lineHeight: 22 },
  form: { backgroundColor: theme.color.surface, borderRadius: theme.radius, padding: 18, gap: 8, marginTop: 20 },
  label: { color: theme.color.muted, fontSize: theme.type.xs, fontWeight: '700', letterSpacing: 1.6 },
  input: { borderWidth: 1, borderColor: theme.color.border, borderRadius: theme.radiusSm, padding: 13, fontSize: theme.type.lg, color: theme.color.text, marginBottom: 6 },
  err: { color: theme.color.danger, fontWeight: '600' },
  notice: { flexDirection: 'row', gap: 8, alignItems: 'center', backgroundColor: theme.color.peach, borderRadius: theme.radiusSm, padding: 10, marginBottom: 6 },
  noticeText: { flex: 1, color: theme.color.ink, fontWeight: '600', fontSize: theme.type.sm },
  persona: { flexDirection: 'row', gap: 12, alignItems: 'center', backgroundColor: theme.color.inkSoft, borderRadius: theme.radius, padding: 14, borderWidth: 1, borderColor: 'rgba(255,255,255,0.14)' },
  avatar: { width: 42, height: 42, borderRadius: 21, backgroundColor: theme.color.red, alignItems: 'center', justifyContent: 'center' },
  pname: { color: theme.color.onDark, fontWeight: '700', fontSize: theme.type.md },
  paud: { color: theme.color.orange, fontWeight: '700', fontSize: 10, letterSpacing: 1.2 },
  pmeta: { color: theme.color.onDarkMuted, fontSize: theme.type.sm },
  pblurb: { color: 'rgba(255,255,255,0.9)', fontSize: theme.type.sm },
  foot: { color: 'rgba(255,255,255,0.4)', fontSize: theme.type.xs, marginTop: 16, textAlign: 'center' },
});
