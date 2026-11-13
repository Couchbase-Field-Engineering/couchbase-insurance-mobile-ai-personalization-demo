import { Ionicons } from '@expo/vector-icons';
import { router, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Switch, Text, TextInput, View } from 'react-native';
import { useData } from '@/src/data/DataContext';
import { activePolicies, policySubject } from '@/src/insurance';
import { theme } from '@/src/theme';
import type { Catalog, Claim } from '@/src/types';
import { Button, Card, Empty, fmtDate, money, Pill, SectionTitle } from '@/src/ui/components';
import { ChoiceRow } from '@/src/ui/Choice';
import { addDays, short } from '@/src/ui/dates';
import { form, OFFLINE_NOTE } from '@/src/ui/form';
import { RequestTracker } from '@/src/ui/RequestTracker';

const EVIDENCE_LABEL: Record<string, string> = { photo: 'Photo', video: 'Video', police_report: 'Police report', receipt: 'Receipt', estimate: 'Repair estimate' };
const NEXT: Record<string, string> = {
  submitted: 'An adjuster is assigned within one business day.',
  under_review: 'Your adjuster is reviewing the photos and the report.',
  inspection_scheduled: 'A field inspector visits on the scheduled day.',
  estimate_ready: 'Review the estimate and choose a repair shop or a direct payment.',
  approved: 'Payment is on its way to your bank account, usually within 2 business days.',
  paid: 'This claim is paid. You can still add a supplement if the shop finds more damage.',
};

/**
 * Use case 2 - claims filing and tracking.
 *
 * Filing: photos and video are captured at the scene, where there is often
 * no signal. The claim is saved as a `requests` document in Couchbase Lite
 * and pushed when the phone reconnects; the worker hands it to the Claims
 * Agent, which recalls this customer's claim history from Couchbase Labs Agent Operations Manager Agent Memory
 * and files it as a governed tool call.
 *
 * Tracking: the claim lives in the profile document, so every status change
 * the insurer makes replicates to the phone without the app polling for it.
 */
export default function ClaimScreen() {
  const params = useLocalSearchParams<{ claim_id?: string }>();
  const { snap } = useData();
  const p = snap.profile;
  const cat = snap.catalog;
  const [open, setOpen] = useState<string | undefined>(params.claim_id);
  const [filing, setFiling] = useState(false);
  if (!p || !cat) return null;
  const claims = [...(p.claims ?? [])].reverse();
  const claim = claims.find((c) => c.claim_id === open);
  const canFile = activePolicies(p, 'auto', 'home', 'renters').length > 0;

  if (claim && !filing) return <Tracker claim={claim} cat={cat} onBack={claims.length > 1 || canFile ? () => setOpen(undefined) : undefined} />;
  if (filing || (!claims.length && canFile)) return <FileClaim onCancel={claims.length ? () => setFiling(false) : undefined} />;

  return (
    <ScrollView contentContainerStyle={form.body}>
      {claims.length === 0 ? (
        <Empty icon="camera-outline" title="Claims are filed on auto, home and renters policies"
          body={p.audience === 'member' ? 'For a vet bill, open Health & Wellness. For anything else, a licensed agent can help.' : 'On-demand cover claims are handled by a licensed agent - ask in Chat.'} />
      ) : null}
      {claims.map((c) => (
        <Pressable key={c.claim_id} onPress={() => setOpen(c.claim_id)}>
          <Card style={styles.row}>
            <Ionicons name="camera" size={18} color={theme.color.red} />
            <View style={{ flex: 1 }}>
              <Text style={styles.title}>{c.claim_id} · {c.loss_type.replace(/_/g, ' ')}</Text>
              <Text style={form.meta}>Filed {fmtDate(c.filed_at)} · {c.policy_id}</Text>
            </View>
            <Pill label={cat.claim_step_label[c.status] ?? c.status} tone={c.status === 'paid' ? 'ok' : 'orange'} />
          </Card>
        </Pressable>
      ))}
      {canFile ? <View style={{ marginTop: 8 }}><Button label="File a new claim" icon="add" onPress={() => setFiling(true)} /></View> : null}
    </ScrollView>
  );
}

function Tracker({ claim: c, cat, onBack }: { claim: Claim; cat: Catalog; onBack?: () => void }) {
  const { request, queueAsk } = useData();
  const [kind, setKind] = useState('photo');
  const [count, setCount] = useState(1);
  const [reqId, setReqId] = useState<string | null>(null);
  const step = cat.claim_steps.indexOf(c.status);
  const closed = ['paid', 'closed', 'denied'].includes(c.status);
  const photos = c.evidence.filter((e) => e.kind === 'photo' || e.kind === 'video').reduce((n, e) => n + (e.count ?? 1), 0);

  const add = async () => {
    const req = await request('add_claim_evidence', { claim_id: c.claim_id, kind, count }, `${count} ${EVIDENCE_LABEL[kind].toLowerCase()}${count > 1 ? 's' : ''} · ${c.claim_id}`);
    setReqId(req._id);
  };

  return (
    <ScrollView contentContainerStyle={form.body}>
      {onBack ? <Pressable onPress={onBack} style={{ marginBottom: 10 }}><Text style={styles.link}>‹ All claims</Text></Pressable> : null}
      <Card style={{ padding: 18, gap: 6 }}>
        <View style={form.rowBetween}>
          <Pill label={cat.claim_step_label[c.status] ?? c.status} tone={closed ? 'ok' : 'red'} />
          <Text style={form.meta}>{c.policy_id}</Text>
        </View>
        <Text style={form.h2}>{c.claim_id}</Text>
        <Text style={form.meta}>{c.description}</Text>
        <Text style={form.meta}>{fmtDate(c.loss_date)}{c.location ? ` · ${c.location}` : ''}</Text>
        {c.adjuster ? <Text style={[form.meta, { color: theme.color.text, fontWeight: '700' }]}>Adjuster: {c.adjuster}</Text> : null}
      </Card>

      <SectionTitle title="Where it stands" />
      <Card style={{ padding: 16, gap: 2 }}>
        {cat.claim_steps.map((s, i) => {
          const done = step >= 0 && i <= step;
          const here = i === step;
          return (
            <View key={s} style={{ flexDirection: 'row', gap: 12 }}>
              <View style={{ alignItems: 'center', width: 20 }}>
                <Ionicons name={done ? 'checkmark-circle' : 'ellipse-outline'} size={20} color={done ? (here ? theme.color.red : theme.color.ok) : theme.color.faint} />
                {i < cat.claim_steps.length - 1 ? <View style={[styles.line, done && i < step && { backgroundColor: theme.color.ok }]} /> : null}
              </View>
              <View style={{ flex: 1, paddingBottom: 12 }}>
                <Text style={[styles.step, !done && { color: theme.color.faint }, here && { color: theme.color.ink }]}>{cat.claim_step_label[s] ?? s}</Text>
                {here && NEXT[s] ? <Text style={form.meta}>{NEXT[s]}</Text> : null}
              </View>
            </View>
          );
        })}
      </Card>

      {c.estimate_usd ? (
        <>
          <SectionTitle title="The numbers" />
          <Card style={{ padding: 16, gap: 8 }}>
            <View style={form.rowBetween}><Text style={form.meta}>Repair estimate</Text><Text style={styles.num}>{money(c.estimate_usd)}</Text></View>
            <View style={form.rowBetween}><Text style={form.meta}>Your deductible</Text><Text style={styles.num}>- {money(c.deductible_usd ?? 0)}</Text></View>
            <View style={[form.rowBetween, styles.total]}>
              <Text style={styles.title}>{c.payout_usd ? 'Paid to you' : 'We pay'}</Text>
              <Text style={[styles.num, { color: theme.color.red, fontSize: theme.type.lg }]}>{money(c.payout_usd ?? Math.max(0, c.estimate_usd - (c.deductible_usd ?? 0)))}</Text>
            </View>
          </Card>
        </>
      ) : null}

      <SectionTitle title="Timeline" />
      <Card style={{ padding: 16, gap: 10 }}>
        {[...c.events].reverse().map((e, i) => (
          <View key={i} style={{ flexDirection: 'row', gap: 10 }}>
            <Text style={[form.meta, { width: 86 }]}>{fmtDate(e.at)}</Text>
            <Text style={{ flex: 1, color: theme.color.text }}>{e.text}</Text>
          </View>
        ))}
        <Text style={form.meta}>{photos} photo{photos === 1 ? '' : 's'} and video{photos === 1 ? '' : 's'} received{c.evidence.some((e) => e.kind === 'police_report') ? ' · police report on file' : ''}</Text>
      </Card>

      {!closed ? (
        reqId ? <RequestTracker id={reqId} onRetry={() => setReqId(null)} /> : (
          <>
            <SectionTitle title="Add photos or documents" />
            <ChoiceRow options={cat.evidence_kinds.map((k) => ({ value: k, label: EVIDENCE_LABEL[k] ?? k }))} value={kind} onChange={(k) => { setKind(k); setCount(1); }} />
            {kind === 'photo' || kind === 'video' ? <Capture kind={kind} count={count} onChange={setCount} /> : null}
            <View style={{ marginTop: 14, gap: 10 }}>
              <Button label={`Send to ${c.adjuster?.split(' ')[0] ?? 'my adjuster'}`} icon="cloud-upload" disabled={count < 1} onPress={() => void add()} />
              <Button kind="ghost" label="Ask about this claim" icon="chatbubble-ellipses" onPress={() => { queueAsk(`What's the status of my claim ${c.claim_id}?`); router.navigate('/(tabs)'); }} />
            </View>
            <Text style={form.tiny}>{OFFLINE_NOTE}</Text>
          </>
        )
      ) : null}
    </ScrollView>
  );
}

/** Stand-in for the camera: each tap is one capture kept with the claim draft on the device. */
function Capture({ kind, count, onChange }: { kind: string; count: number; onChange: (n: number) => void }) {
  return (
    <View style={styles.capture}>
      {Array.from({ length: count }).map((_, i) => (
        <Pressable key={i} onPress={() => onChange(Math.max(0, count - 1))} style={styles.thumb}>
          <Ionicons name={kind === 'video' ? 'videocam' : 'image'} size={22} color={theme.color.onDark} />
          <Text style={styles.thumbText}>{i + 1}</Text>
        </Pressable>
      ))}
      {count < 12 ? (
        <Pressable onPress={() => onChange(count + 1)} style={[styles.thumb, styles.thumbAdd]}>
          <Ionicons name={kind === 'video' ? 'videocam-outline' : 'camera-outline'} size={22} color={theme.color.ink} />
          <Text style={[styles.thumbText, { color: theme.color.ink }]}>Add</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

function FileClaim({ onCancel }: { onCancel?: () => void }) {
  const { snap, request } = useData();
  const p = snap.profile!;
  const cat = snap.catalog!;
  const today = (snap.feed?.today ?? p.export_date).slice(0, 10);
  const pols = activePolicies(p, 'auto', 'home', 'renters');
  const [policyId, setPolicyId] = useState(pols[0]?.policy_id);
  const pol = pols.find((x) => x.policy_id === policyId) ?? pols[0];
  const [loss, setLoss] = useState<string | undefined>();
  const [date, setDate] = useState(today);
  const [desc, setDesc] = useState('');
  const [where, setWhere] = useState(pol?.line === 'auto' ? p.roadside?.last_location?.label ?? '' : pol?.property?.address ?? p.address ?? '');
  const [photos, setPhotos] = useState(0);
  const [videos, setVideos] = useState(0);
  const [police, setPolice] = useState(false);
  const [drivable, setDrivable] = useState(true);
  const [reqId, setReqId] = useState<string | null>(null);
  const types = cat.loss_types[pol?.line ?? 'auto'] ?? [];
  const ready = !!pol && !!loss && desc.trim().length >= 10;

  const submit = async () => {
    if (!pol || !loss) return;
    const req = await request('file_claim', {
      policy_id: pol.policy_id, loss_type: loss, loss_date: date, description: desc.trim(), location: where.trim(), photos, videos,
      police_report: police, drivable: pol.line === 'auto' ? drivable : true,
    }, `Claim · ${types.find((t) => t.id === loss)?.name ?? loss}`);
    setReqId(req._id);
  };

  if (reqId) return <ScrollView contentContainerStyle={form.body}><RequestTracker id={reqId} onRetry={() => setReqId(null)} /></ScrollView>;

  return (
    <ScrollView contentContainerStyle={form.body} keyboardShouldPersistTaps="handled">
      {onCancel ? <Pressable onPress={onCancel} style={{ marginBottom: 10 }}><Text style={styles.link}>‹ All claims</Text></Pressable> : null}
      <Text style={form.h2}>Tell us what happened</Text>
      <Text style={form.meta}>Two minutes, and it works with no signal. If anyone is hurt, call 911 first.</Text>

      <SectionTitle title="Which policy?" />
      <ChoiceRow options={pols.map((x) => ({ value: x.policy_id, label: `${x.product.replace('Harborline ', '')} · ${policySubject(x).split(' · ')[0]}` }))} value={pol?.policy_id}
        onChange={(v) => { setPolicyId(v); setLoss(undefined); }} />
      <SectionTitle title="What happened?" />
      <ChoiceRow options={types.map((t) => ({ value: t.id, label: t.name }))} value={loss} onChange={setLoss} />
      <SectionTitle title="When?" />
      <ChoiceRow options={[0, -1, -2, -3, -7].map((n) => ({ value: addDays(today, n), label: n === 0 ? 'Today' : n === -1 ? 'Yesterday' : short(addDays(today, n)) }))} value={date} onChange={setDate} />
      <SectionTitle title="Describe it" />
      <TextInput value={desc} onChangeText={setDesc} multiline placeholder="e.g. Rear-ended at a red light; rear bumper and tailgate damaged." placeholderTextColor={theme.color.faint}
        style={[form.input, { minHeight: 90, textAlignVertical: 'top' }]} />
      <SectionTitle title="Where?" />
      <TextInput value={where} onChangeText={setWhere} placeholder="Street and city" placeholderTextColor={theme.color.faint} style={form.input} />

      <SectionTitle title="Photos of the damage" action={<Text style={form.meta}>{photos} taken</Text>} />
      <Capture kind="photo" count={photos} onChange={setPhotos} />
      <SectionTitle title="Video walk-around" action={<Text style={form.meta}>{videos} recorded</Text>} />
      <Capture kind="video" count={videos} onChange={setVideos} />

      <Card style={{ padding: 14, gap: 12, marginTop: 16 }}>
        <View style={form.rowBetween}>
          <Text style={styles.title}>A police report was filed</Text>
          <Switch value={police} onValueChange={setPolice} trackColor={{ true: theme.color.red, false: theme.color.border }} thumbColor={theme.color.surface} />
        </View>
        {pol?.line === 'auto' ? (
          <View style={form.rowBetween}>
            <Text style={styles.title}>The car can still be driven</Text>
            <Switch value={drivable} onValueChange={setDrivable} trackColor={{ true: theme.color.red, false: theme.color.border }} thumbColor={theme.color.surface} />
          </View>
        ) : null}
      </Card>

      {pol?.deductible_usd ? <Text style={[form.meta, { marginTop: 10 }]}>Your deductible on {pol.policy_id} is {money(pol.deductible_usd)}.</Text> : null}
      <View style={{ marginTop: 16 }}>
        <Button label="Submit claim" icon="send" disabled={!ready} onPress={() => void submit()} />
      </View>
      <Text style={form.tiny}>{ready ? OFFLINE_NOTE : 'Choose what happened and describe it in a sentence.'}</Text>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', gap: 10, alignItems: 'center', padding: 14, marginBottom: 10 },
  title: { fontWeight: '700', color: theme.color.text, flexShrink: 1 },
  link: { color: theme.color.red, fontWeight: '700' },
  line: { width: 2, flex: 1, minHeight: 14, backgroundColor: theme.color.border },
  step: { fontWeight: '700', color: theme.color.body },
  num: { fontWeight: '700', color: theme.color.text },
  total: { borderTopWidth: 1, borderTopColor: theme.color.border, paddingTop: 8 },
  capture: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginTop: 4 },
  thumb: { width: 62, height: 62, borderRadius: 12, backgroundColor: theme.color.inkSoft, alignItems: 'center', justifyContent: 'center' },
  thumbAdd: { backgroundColor: theme.color.peach, borderWidth: 1.5, borderColor: theme.color.ink, borderStyle: 'dashed' },
  thumbText: { color: theme.color.onDark, fontSize: 10, fontWeight: '700', marginTop: 2 },
});
