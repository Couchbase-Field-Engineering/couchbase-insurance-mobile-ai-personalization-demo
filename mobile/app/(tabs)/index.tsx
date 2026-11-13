import { Ionicons } from '@expo/vector-icons';
import { useEffect, useRef, useState } from 'react';
import { ActivityIndicator, KeyboardAvoidingView, Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useData } from '@/src/data/DataContext';
import { theme } from '@/src/theme';
import type { Area, Audience, ChatMessage } from '@/src/types';
import { AREA_UI, AreaTag, Pill, SyncBadge, Wordmark, type Tone } from '@/src/ui/components';
import { openAction } from '@/src/ui/nav';

/** What each kind of customer can ask, by area - the eight jobs of an insurance app. */
const PROMPTS: Record<Audience, Partial<Record<Area, string[]>>> = {
  policyholder: {
    documents: ['Show my insurance card', 'I need proof of insurance for my lender', 'Where is my declarations page?'],
    claims: ["What's the status of my claim?", 'How do I file a claim?', 'Someone hit my car in a car park', 'What does my deductible mean?'],
    roadside: ['I have a flat tire', 'My battery died - can you send someone?', "I've been in an accident", 'How many roadside calls do I get?'],
    billing: ['When is my next payment due?', 'Why did my renewal go up?', 'Turn on AutoPay', 'Can I pay my premium in full?'],
    telematics: ["What's my driving score?", 'How much has DriveWell saved me?', 'How does pay-per-mile work?'],
    support: ['I moved - update my address', 'Add a driver to my policy', 'Can I talk to a licensed agent?'],
    coverage: ["I'm borrowing a friend's car this weekend", 'Do you cover rental cars?', 'I need cover for a trip'],
    wellness: ['Can I book a telehealth visit?'],
  },
  member: {
    wellness: ['Can I see a doctor today?', 'How much of my deductible have I met?', "How do I get Biscuit's vet bill paid back?", 'Link my Apple Watch',
      'How do telehealth visits work?'],
    documents: ['Show my insurance card', 'I need my summary of benefits'],
    billing: ['Is anything past due?', 'Can you waive my late fee?', 'Turn on AutoPay'],
    roadside: ['I have a medical emergency while travelling', 'Can I get roadside help without an auto policy?'],
    support: ['Change the email on my account', 'Can I talk to a licensed agent?'],
    coverage: ['I need cover for a trip', 'Do you cover rental cars?'],
    claims: ['How do I file a claim?'],
  },
  ondemand: {
    coverage: ["I'm borrowing a friend's car this weekend", 'Cover my trip to Lisbon', 'What does trip protection cover?', 'How fast does on-demand cover start?'],
    roadside: ['I have a flat tire', 'My rental car broke down', 'I have an emergency while travelling'],
    documents: ['Show my certificate of coverage', 'Is a digital ID card accepted as proof of insurance?'],
    support: ['Can I talk to a licensed agent?', 'What does Harborline insure?'],
    billing: ['How do I pay for on-demand cover?'],
    wellness: ['Can I book a telehealth visit?'],
  },
};
const AREA_ORDER: Area[] = ['documents', 'claims', 'roadside', 'billing', 'telematics', 'support', 'wellness', 'coverage'];
const HOME: Record<Audience, Area> = { policyholder: 'claims', member: 'wellness', ondemand: 'coverage' };
const INTRO: Record<Audience, string> = {
  policyholder: 'I know your policies, your open claim, what is due and your DriveWell score - and I can send roadside help to where you are.',
  member: 'I know your health and pet plans, your deductible, your telehealth visits and vet bills - plus everything about billing and documents.',
  ondemand: "I can switch on cover by the day for a borrowed car, a rental or a trip, and send roadside or SOS help while it's active.",
};
const PLACEHOLDER: Record<Audience, string> = {
  policyholder: 'Ask about claims, payments, roadside…',
  member: 'Ask about telehealth, vet bills, your deductible…',
  ondemand: 'Ask about cover for a car or a trip…',
};

function llmLabel(m: ChatMessage): { label: string; tone: Tone } | null {
  if (m.offline) return { label: 'Answered on device · Couchbase Lite', tone: 'warn' };
  const s = m.llm?.status;
  if (!s || s === 'skipped') return null;
  if (s === 'hit_exact') return { label: 'LLM cache · exact hit', tone: 'ok' };
  if (s === 'hit_semantic') return { label: `LLM cache · semantic hit${m.llm?.similarity ? ` ${m.llm.similarity.toFixed(2)}` : ''}`, tone: 'ok' };
  if (s === 'miss') return { label: `LLM cache · miss${m.llm?.latency_ms ? ` · ${Math.round(m.llm.latency_ms)}ms` : ''}`, tone: 'neutral' };
  if (s === 'local') return { label: 'Composed from context (AOM not configured)', tone: 'neutral' };
  if (s === 'bypass') return { label: 'LLM cache · bypassed', tone: 'neutral' };
  return { label: `LLM · ${s}`, tone: 'warn' };
}

export default function Chat() {
  const { snap, sync, ask, thinking, liveChat, queuedAsk, queueAsk } = useData();
  const insets = useSafeAreaInsets();
  const [text, setText] = useState('');
  const scroll = useRef<ScrollView>(null);
  const audience: Audience = snap.profile?.audience ?? 'policyholder';
  const areas = AREA_ORDER.filter((a) => PROMPTS[audience][a]?.length);
  const home = HOME[audience];
  const [area, setArea] = useState<Area>(home);
  useEffect(() => setArea(home), [home]);
  const firstLive = liveChat[0]?.at;
  const history = (snap.chat?.messages ?? []).filter((m) => !firstLive || m.at < firstLive).slice(-10);
  const messages = [...history, ...liveChat];

  useEffect(() => {
    setTimeout(() => scroll.current?.scrollToEnd({ animated: true }), 50);
  }, [messages.length, thinking]);

  // A question handed over by a For You card ("Ask about it").
  useEffect(() => {
    if (queuedAsk && snap.profile) {
      const q = queuedAsk;
      queueAsk(null);
      void ask(q);
    }
  }, [queuedAsk, snap.profile, ask, queueAsk]);

  const send = (q: string) => {
    if (!q.trim()) return;
    setText('');
    void ask(q.trim());
  };

  return (
    <KeyboardAvoidingView style={{ flex: 1, backgroundColor: theme.color.bg }} behavior={Platform.OS === 'ios' ? 'padding' : undefined} keyboardVerticalOffset={60}>
      <View style={[styles.header, { paddingTop: insets.top + 12 }]}>
        <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }}>
          <Wordmark height={18} />
          <SyncBadge sync={sync} dark />
        </View>
        <Text style={styles.subtitle}>One assistant, seven agents: cards, claims, roadside, billing, DriveWell, wellness, cover · governed by Couchbase AOM</Text>
      </View>

      <ScrollView ref={scroll} style={{ flex: 1 }} contentContainerStyle={styles.list}>
        {messages.length === 0 ? (
          <View style={styles.intro}>
            <Text style={styles.introTitle}>Hi{snap.profile ? ` ${snap.profile.first_name}` : ''}, what can I help with?</Text>
            <Text style={styles.introBody}>
              {INTRO[audience]}
            </Text>
            <View style={{ gap: 6, marginTop: 4 }}>
              {areas.map((a) => (
                <View key={a} style={{ flexDirection: 'row', gap: 8, alignItems: 'center' }}>
                  <Ionicons name={AREA_UI[a].icon} size={14} color={theme.area[a]} />
                  <Text style={{ color: theme.color.body, fontSize: theme.type.sm, fontWeight: '600' }}>{AREA_UI[a].label}</Text>
                  {a === 'wellness' && audience !== 'member' ? <Text style={styles.tiny}>health & pet members only - try it</Text> : null}
                </View>
              ))}
            </View>
          </View>
        ) : null}
        {messages.map((m) => <Bubble key={m.id} m={m} />)}
        {thinking ? (
          <View style={[styles.bubble, styles.botBubble, { flexDirection: 'row', gap: 8, alignItems: 'center' }]}>
            <ActivityIndicator color={theme.color.red} />
            <Text style={{ color: theme.color.muted }}>Checking your context cache…</Text>
          </View>
        ) : null}
      </ScrollView>

      <ScrollView horizontal style={{ flexGrow: 0 }} showsHorizontalScrollIndicator={false} contentContainerStyle={styles.areas} keyboardShouldPersistTaps="handled">
        {areas.map((a) => (
          <Pressable key={a} onPress={() => setArea(a)} style={[styles.areaTab, area === a && styles.areaOn]}>
            <Ionicons name={AREA_UI[a].icon} size={13} color={area === a ? theme.color.onDark : theme.color.muted} />
            <Text style={[styles.areaText, area === a && { color: theme.color.onDark }]}>{AREA_UI[a].label}</Text>
          </Pressable>
        ))}
      </ScrollView>
      <ScrollView horizontal style={{ flexGrow: 0 }} showsHorizontalScrollIndicator={false} contentContainerStyle={styles.chips} keyboardShouldPersistTaps="handled">
        {(PROMPTS[audience][area] ?? []).map((p) => (
          <Pressable key={p} onPress={() => send(p)} style={styles.chip}>
            <Text style={styles.chipText}>{p}</Text>
          </Pressable>
        ))}
      </ScrollView>
      <View style={[styles.inputRow, { paddingBottom: 10 }]}>
        <TextInput
          value={text}
          onChangeText={setText}
          placeholder={PLACEHOLDER[audience]}
          placeholderTextColor={theme.color.faint}
          style={styles.input}
          onSubmitEditing={() => send(text)}
          returnKeyType="send"
        />
        <Pressable onPress={() => send(text)} style={[styles.send, !text.trim() && { opacity: 0.4 }]} disabled={!text.trim()}>
          <Ionicons name="arrow-up" size={20} color={theme.color.onDark} />
        </Pressable>
      </View>
    </KeyboardAvoidingView>
  );
}

function Bubble({ m }: { m: ChatMessage }) {
  const [open, setOpen] = useState(false);
  const { queueAsk } = useData();
  if (m.role === 'user') {
    return (
      <View style={[styles.bubble, styles.meBubble]}>
        <Text style={{ color: theme.color.onDark, fontSize: theme.type.md }}>{m.text}</Text>
      </View>
    );
  }
  const llm = llmLabel(m);
  const ctx = m.context;
  const kb = ctx?.knowledge === 'helpcenter' ? 'Help Center' : ctx?.knowledge ? 'Member Care Guide' : null;
  return (
    <View style={[styles.bubble, styles.botBubble, m.restricted && styles.restricted]}>
      <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
        <AreaTag area={m.area} />
        {m.restricted ? <Pill label="Members only" tone="ink" icon="lock-closed" /> : null}
      </View>
      <Text style={{ color: theme.color.text, fontSize: theme.type.md, lineHeight: 21 }}>{m.text}</Text>
      {m.actions?.length ? (
        <View style={{ gap: 8, marginTop: 10 }}>
          {m.actions.map((a, i) => (
            <Pressable key={a.label} onPress={() => openAction(a, { title: a.label, queueAsk })} style={[styles.action, i > 0 && styles.actionAlt]}>
              <Ionicons name={a.tool ? 'flash' : 'open-outline'} size={14} color={i > 0 ? theme.color.ink : theme.color.onDark} />
              <Text style={[styles.actionText, i > 0 && { color: theme.color.ink }]}>{a.label}</Text>
            </Pressable>
          ))}
        </View>
      ) : null}
      <View style={styles.meta}>
        {ctx?.status && !m.offline ? (
          <Pill
            label={`Context cache · ${ctx.status === 'hit' ? 'hit' : 'built'} ${Math.round(ctx.latency_ms)}ms`}
            tone={ctx.status === 'hit' ? 'ok' : 'orange'}
            icon={ctx.status === 'hit' ? 'flash' : 'layers-outline'}
          />
        ) : null}
        {ctx?.sor && ctx.status !== 'hit' && !m.offline ? (
          <Pill label={`${ctx.sor.label} · ${Math.round(ctx.sor.latency_ms)}ms`} tone="neutral" icon="cloud-download-outline" />
        ) : null}
        {llm ? <Pill label={llm.label} tone={llm.tone} icon={m.offline ? 'airplane' : 'hardware-chip-outline'} /> : null}
        {kb && !m.offline ? <Pill label={kb} tone="neutral" icon="book-outline" /> : null}
        {m.sources?.length ? (
          <Pressable onPress={() => setOpen(!open)}>
            <Pill label={`${m.sources.length} sources ${open ? '▲' : '▼'}`} tone="neutral" icon="library-outline" />
          </Pressable>
        ) : null}
      </View>
      {open
        ? m.sources?.map((s, i) => (
            <View key={i} style={styles.source}>
              <Text style={styles.sourceTitle}>{s.title} <Text style={{ color: theme.color.faint }}>({s.kind})</Text></Text>
              <Text style={styles.sourceText} numberOfLines={3}>{s.snippet}</Text>
            </View>
          ))
        : null}
    </View>
  );
}

const styles = StyleSheet.create({
  header: { backgroundColor: theme.color.ink, paddingHorizontal: 16, paddingBottom: 14 },
  subtitle: { color: theme.color.onDarkMuted, fontSize: theme.type.xs, marginTop: 8 },
  list: { padding: 14, gap: 10, maxWidth: 680, width: '100%', alignSelf: 'center' },
  intro: { backgroundColor: theme.color.peach, borderRadius: theme.radius, padding: 18, gap: 8 },
  introTitle: { fontWeight: '600', fontFamily: theme.font.display, fontSize: theme.type.xl, color: theme.color.ink, letterSpacing: -0.3 },
  introBody: { color: theme.color.body, lineHeight: 20 },
  tiny: { color: theme.color.faint, fontSize: theme.type.xs },
  bubble: { padding: 13, borderRadius: 18, maxWidth: '90%' },
  meBubble: { backgroundColor: theme.color.ink, alignSelf: 'flex-end', borderBottomRightRadius: 6 },
  botBubble: { backgroundColor: theme.color.surface, alignSelf: 'flex-start', borderBottomLeftRadius: 6, ...theme.shadow.card },
  restricted: { borderWidth: 1.5, borderColor: theme.color.ink },
  action: { flexDirection: 'row', gap: 6, alignItems: 'center', backgroundColor: theme.color.red, borderRadius: theme.radiusSm, paddingVertical: 10, paddingHorizontal: 14, alignSelf: 'flex-start' },
  actionAlt: { backgroundColor: theme.color.surface, borderWidth: 1.5, borderColor: theme.color.ink },
  actionText: { color: theme.color.onDark, fontWeight: '600', fontSize: theme.type.sm, flexShrink: 1 },
  meta: { flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginTop: 10 },
  source: { marginTop: 8, borderLeftWidth: 3, borderLeftColor: theme.color.red, paddingLeft: 8 },
  sourceTitle: { fontWeight: '700', fontSize: theme.type.xs, color: theme.color.text },
  sourceText: { fontSize: theme.type.xs, color: theme.color.muted },
  areas: { flexDirection: 'row', gap: 6, paddingHorizontal: 12, paddingTop: 8 },
  areaTab: { flexDirection: 'row', gap: 5, alignItems: 'center', paddingHorizontal: 9, paddingVertical: 6, borderRadius: 8, backgroundColor: theme.color.surface, borderWidth: 1, borderColor: theme.color.border },
  areaOn: { backgroundColor: theme.color.ink, borderColor: theme.color.ink },
  areaText: { fontSize: 11, fontWeight: '700', color: theme.color.muted },
  chips: { gap: 8, paddingHorizontal: 12, paddingVertical: 8 },
  chip: { backgroundColor: theme.color.surface, borderRadius: 10, paddingHorizontal: 12, paddingVertical: 8, borderWidth: 1, borderColor: theme.color.border, maxWidth: 300 },
  chipText: { color: theme.color.ink, fontWeight: '600', fontSize: theme.type.sm },
  inputRow: { flexDirection: 'row', gap: 8, paddingHorizontal: 12, alignItems: 'center' },
  input: { flex: 1, backgroundColor: theme.color.surface, borderRadius: theme.radiusSm, paddingHorizontal: 16, paddingVertical: 12, fontSize: theme.type.md, borderWidth: 1, borderColor: theme.color.border, color: theme.color.text },
  send: { width: 44, height: 44, borderRadius: theme.radiusSm, backgroundColor: theme.color.red, alignItems: 'center', justifyContent: 'center' },
});
