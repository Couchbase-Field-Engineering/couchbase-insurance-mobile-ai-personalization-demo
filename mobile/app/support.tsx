import { Ionicons } from '@expo/vector-icons';
import { router, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { useData } from '@/src/data/DataContext';
import { activePolicies, policySubject } from '@/src/insurance';
import { theme } from '@/src/theme';
import { Button, Card, Field, Pill, SectionTitle } from '@/src/ui/components';
import { ChoiceRow } from '@/src/ui/Choice';
import { form, OFFLINE_NOTE } from '@/src/ui/form';
import { RequestTracker } from '@/src/ui/RequestTracker';

type Tab = 'details' | 'change' | 'agent';
const TABS: { id: Tab; label: string }[] = [{ id: 'details', label: 'My details' }, { id: 'change', label: 'Change a policy' }, { id: 'agent', label: 'Licensed agent' }];
const CHANNEL: Record<string, string> = { chat: 'Chat', callback: 'Call me back', video: 'Video' };

/**
 * Use case 6 - in-app customer support.
 *
 * The 24/7 chatbot is the Chat tab. This screen is what it hands off to:
 * updating personal details, requesting a policy or document change, and
 * bringing in a licensed human agent with the conversation attached. The
 * Harborline Assistant runs these itself. A change to who or what is covered
 * (a driver, a vehicle, a deductible) is held in Couchbase Labs Agent Operations Manager for an underwriter.
 */
function SupportScreen() {
  const params = useLocalSearchParams<{ tab?: string; topic?: string }>();
  const { snap, request, queueAsk } = useData();
  const p = snap.profile;
  const cat = snap.catalog;
  const [tab, setTab] = useState<Tab>((['details', 'change', 'agent'] as const).find((t) => t === params.tab) ?? 'details');
  const [email, setEmail] = useState(p?.email ?? '');
  const [phone, setPhone] = useState(p?.phone ?? '');
  const [address, setAddress] = useState(p?.address ?? '');
  const [policyId, setPolicyId] = useState<string | undefined>();
  const [change, setChange] = useState<string | undefined>();
  const [details, setDetails] = useState('');
  const [topic, setTopic] = useState<string | undefined>(params.topic);
  const [channel, setChannel] = useState('chat');
  const [note, setNote] = useState('');
  const [reqId, setReqId] = useState<string | null>(null);
  if (!p || !cat) return null;

  const pols = activePolicies(p);
  const pol = pols.find((x) => x.policy_id === policyId) ?? pols[0];
  const changes = pol ? cat.policy_changes.filter((c) => c.lines.includes(pol.line)) : [];
  const ch = changes.find((c) => c.id === change);
  const changed: Record<string, string> = {};
  if (email.trim() && email.trim() !== (p.email ?? '')) changed.email = email.trim();
  if (phone.trim() && phone.trim() !== (p.phone ?? '')) changed.phone = phone.trim();
  if (address.trim() && address.trim() !== (p.address ?? '')) changed.address = address.trim();
  const waiting = (p.support?.requests ?? []).find((r) => r.kind === 'live_agent' && r.status === 'waiting');

  const send = async (tool: string, args: Record<string, unknown>, title: string) => {
    const req = await request(tool, args, title);
    setReqId(req._id);
  };

  return (
    <ScrollView contentContainerStyle={form.body} keyboardShouldPersistTaps="handled">
      <Pressable onPress={() => { queueAsk(null); router.navigate('/(tabs)'); }}>
        <Card style={styles.chat}>
          <Ionicons name="chatbubbles" size={22} color={theme.color.onDark} />
          <View style={{ flex: 1 }}>
            <Text style={styles.chatTitle}>Ask the Harborline Assistant</Text>
            <Text style={styles.chatMeta}>24/7 · knows your policies · answers offline from this phone</Text>
          </View>
          <Ionicons name="chevron-forward" size={18} color={theme.color.onDarkMuted} />
        </Card>
      </Pressable>

      <View style={form.seg}>
        {TABS.map((t) => (
          <Pressable key={t.id} onPress={() => { setTab(t.id); setReqId(null); }} style={[form.segBtn, tab === t.id && form.segOn]}>
            <Text style={[form.segText, { fontSize: theme.type.sm }, tab === t.id && { color: theme.color.onDark }]}>{t.label}</Text>
          </Pressable>
        ))}
      </View>

      {reqId ? <RequestTracker id={reqId} onRetry={() => setReqId(null)} /> : tab === 'details' ? (
        <>
          <SectionTitle title="Email" />
          <TextInput value={email} onChangeText={setEmail} autoCapitalize="none" keyboardType="email-address" style={form.input} placeholderTextColor={theme.color.faint} placeholder="you@example.com" />
          <SectionTitle title="Phone" />
          <TextInput value={phone} onChangeText={setPhone} keyboardType="phone-pad" style={form.input} placeholderTextColor={theme.color.faint} placeholder="+1 555 0100" />
          <SectionTitle title="Mailing address" />
          <TextInput value={address} onChangeText={setAddress} style={form.input} placeholderTextColor={theme.color.faint} placeholder="Street, city, state, ZIP" />
          {changed.address ? <Text style={[form.meta, { marginTop: 8 }]}>A new address can change an auto or home rate. We confirm the premium by email within a day.</Text> : null}
          <View style={{ marginTop: 16 }}>
            <Button label={Object.keys(changed).length ? `Update ${Object.keys(changed).join(', ')}` : 'Nothing changed yet'} icon="save" disabled={!Object.keys(changed).length}
              onPress={() => void send('update_contact_details', changed, `Update ${Object.keys(changed).join(', ')}`)} />
          </View>
          <Text style={form.tiny}>{OFFLINE_NOTE}</Text>
        </>
      ) : tab === 'change' ? (
        pols.length === 0 ? (
          <Text style={[form.meta, { marginTop: 12 }]}>You have no annual policy to change. On-demand cover is set up fresh each time, under On-Demand Coverage.</Text>
        ) : (
          <>
            <SectionTitle title="Which policy?" />
            <ChoiceRow options={pols.map((x) => ({ value: x.policy_id, label: x.product.replace('Harborline ', '') }))} value={pol?.policy_id} onChange={(v) => { setPolicyId(v); setChange(undefined); }} />
            {pol ? <Text style={[form.meta, { marginTop: 6 }]}>{pol.policy_id} · {policySubject(pol)}</Text> : null}
            <SectionTitle title="What should change?" />
            {changes.map((c) => (
              <Pressable key={c.id} onPress={() => setChange(c.id)}>
                <Card style={[form.opt, change === c.id && form.optSel]}>
                  <Ionicons name={c.approval ? 'shield-checkmark' : 'create'} size={20} color={theme.color.red} />
                  <Text style={[styles.title, { flex: 1 }]}>{c.name}</Text>
                  <Pill label={c.approval ? 'Underwriter review' : 'Same day'} tone={c.approval ? 'orange' : 'ok'} />
                </Card>
              </Pressable>
            ))}
            <SectionTitle title="The details" />
            <TextInput value={details} onChangeText={setDetails} multiline style={[form.input, { minHeight: 80, textAlignVertical: 'top' }]} placeholderTextColor={theme.color.faint}
              placeholder={change === 'add_driver' ? 'Name, date of birth and licence number' : change === 'add_vehicle' ? 'Year, make, model and VIN' : 'Tell us exactly what to change'} />
            <View style={{ marginTop: 16 }}>
              <Button label={ch ? `Request: ${ch.name.toLowerCase()}` : 'Choose a change'} icon="send" disabled={!ch || !pol || details.trim().length < 5}
                onPress={() => ch && pol && void send(ch.approval ? 'request_coverage_change' : 'request_policy_change', { policy_id: pol.policy_id, change: ch.id, details: details.trim() }, `${ch.name} · ${pol.policy_id}`)} />
            </View>
            <Text style={form.tiny}>{ch?.approval ? 'This changes who or what is covered, so an underwriter approves it in Couchbase Labs Agent Operations Manager before it applies.' : OFFLINE_NOTE}</Text>
          </>
        )
      ) : waiting ? (
        <Card style={{ padding: 16, gap: 6, marginTop: 12 }}>
          <Pill label="In the queue" tone="orange" icon="time-outline" />
          <Text style={form.h3}>{waiting.agent ?? 'A licensed agent'} will reach you shortly</Text>
          <Text style={form.meta}>{waiting.topic} · by {CHANNEL[waiting.channel ?? 'chat']?.toLowerCase()}{waiting.wait_minutes ? ` · about ${waiting.wait_minutes} minutes` : ''}</Text>
        </Card>
      ) : (
        <>
          <Text style={[form.meta, { marginTop: 4 }]}>A licensed agent joins with this conversation and your policies in front of them, so you won't repeat yourself.</Text>
          <SectionTitle title="What is it about?" />
          <ChoiceRow options={cat.agent_topics.map((t) => ({ value: t, label: t }))} value={topic} onChange={setTopic} />
          <SectionTitle title="How should they reach you?" />
          <ChoiceRow options={cat.agent_channels.map((c) => ({ value: c, label: CHANNEL[c] ?? c }))} value={channel} onChange={setChannel} />
          <SectionTitle title="Anything to add? (optional)" />
          <TextInput value={note} onChangeText={setNote} style={form.input} placeholderTextColor={theme.color.faint} placeholder="A sentence of context" />
          <View style={{ marginTop: 16 }}>
            <Button label={topic ? 'Connect me with an agent' : 'Choose a topic'} icon="headset" disabled={!topic} onPress={() => topic && void send('request_live_agent', { topic, channel, note: note.trim() }, `Licensed agent · ${topic}`)} />
          </View>
          <Card style={{ padding: 14, gap: 8, marginTop: 16 }}>
            <Field icon="call-outline" label="Customer care" value={`${cat.company.support_phone} · ${cat.company.support_hours}`} />
            <Field icon="camera-outline" label="Claims" value={cat.company.claims_phone} />
            <Field icon="car-sport-outline" label="Roadside, 24/7" value={cat.company.roadside_phone} />
          </Card>
          <Text style={form.tiny}>{OFFLINE_NOTE}</Text>
        </>
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  chat: { flexDirection: 'row', gap: 12, alignItems: 'center', padding: 14, backgroundColor: theme.color.ink },
  chatTitle: { color: theme.color.onDark, fontWeight: '700', fontSize: theme.type.md },
  chatMeta: { color: theme.color.onDarkMuted, fontSize: theme.type.xs },
  title: { fontWeight: '700', color: theme.color.text },
});

/** Form defaults come from the documents on the phone, so wait for the first read of Couchbase Lite. */
export default function Support() {
  const { snap } = useData();
  if (!snap.profile || !snap.catalog) return null;
  return <SupportScreen />;
}
