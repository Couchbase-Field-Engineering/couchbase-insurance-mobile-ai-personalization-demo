import { Ionicons } from '@expo/vector-icons';
import { useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { useData } from '@/src/data/DataContext';
import { activePolicies } from '@/src/insurance';
import { theme } from '@/src/theme';
import type { SlotDay } from '@/src/types';
import { Button, Card, Empty, fmtDate, money, Pill, SectionTitle } from '@/src/ui/components';
import { ChoiceRow } from '@/src/ui/Choice';
import { addDays, short } from '@/src/ui/dates';
import { form, OFFLINE_NOTE } from '@/src/ui/form';
import { RequestTracker } from '@/src/ui/RequestTracker';

type Tab = 'telehealth' | 'deductible' | 'pet' | 'wearable';
const TAB_LABEL: Record<Tab, string> = { telehealth: 'Telehealth', deductible: 'Deductible', pet: 'Pet', wearable: 'Wearable' };
const ROUTINE = ['Annual exam', 'Dental cleaning'];

function Bar({ value, max, label }: { value: number; max: number; label: string }) {
  const pct = max ? Math.min(100, Math.round((value / max) * 100)) : 0;
  return (
    <View style={{ gap: 4 }}>
      <View style={form.rowBetween}>
        <Text style={styles.title}>{label}</Text>
        <Text style={form.meta}>{money(value)} of {money(max)}</Text>
      </View>
      <View style={styles.bar}><View style={[styles.barFill, { width: `${pct}%` }]} /></View>
    </View>
  );
}

/**
 * Use case 7 - health and wellness, for members of a health or pet plan.
 *
 * Telehealth booking, deductible tracking, vet bill upload and wearable
 * rewards. The plan reference data comes from the Member Care Guide document
 * (`wellness::v1`), which sits on the Sync Gateway `members` channel: a phone
 * without a health or pet plan never receives it, so this screen has nothing
 * to show there. Every action runs as the Wellness Agent, whose tools refuse
 * a non-member even if it is asked.
 */
function WellnessScreen() {
  const params = useLocalSearchParams<{ tab?: string }>();
  const { snap, request } = useData();
  const p = snap.profile;
  const guide = snap.memberGuide;
  const health = p ? activePolicies(p, 'health')[0] : undefined;
  const pet = p ? activePolicies(p, 'pet')[0] : undefined;
  const tabs: Tab[] = [...(health || pet ? (['telehealth'] as Tab[]) : []), ...(health ? (['deductible'] as Tab[]) : []), ...(pet ? (['pet'] as Tab[]) : []), ...(health ? (['wearable'] as Tab[]) : [])];
  const [tab, setTab] = useState<Tab>(tabs.find((t) => t === params.tab) ?? tabs[0] ?? 'telehealth');
  const [reqId, setReqId] = useState<string | null>(null);
  // telehealth
  const card = snap.feed?.cards.find((c) => c.kind === 'telehealth' && c.slots?.length);
  const days: SlotDay[] = card?.slots ?? ((snap.contexts.wellness?.facts?.data?.telehealth?.days ?? []) as SlotDay[]);
  const [visit, setVisit] = useState<string | undefined>();
  const [date, setDate] = useState<string | undefined>(days.find((d) => d.slots.some((s) => s.open > 0))?.date);
  const [time, setTime] = useState<string | undefined>();
  const [why, setWhy] = useState('');
  // vet bill
  const [petId, setPetId] = useState<string | undefined>();
  const [amount, setAmount] = useState('');
  const [clinic, setClinic] = useState('');
  const [reason, setReason] = useState<string | undefined>();
  const [visitDate, setVisitDate] = useState<string | undefined>();
  const [photos, setPhotos] = useState(0);
  // wearable
  const [device, setDevice] = useState<string | undefined>();

  if (!p) return null;
  if (p.audience !== 'member' || !guide || !tabs.length) {
    return (
      <Empty icon="lock-closed-outline" title="For health and pet plan members"
        body="Telehealth, deductible tracking, vet bills and wearable rewards come with a Harborline Health or Pet plan. The members' guide isn't replicated to this phone, by design. A licensed agent can tell you about adding a plan." />
    );
  }
  const today = (snap.feed?.today ?? p.export_date).slice(0, 10);
  const w = p.wellness ?? {};
  const send = async (tool: string, args: Record<string, unknown>, title: string) => {
    const req = await request(tool, args, title);
    setReqId(req._id);
  };

  const types = guide.telehealth_types.filter((t) => (t.id === 'vet' ? !!pet : !!health));
  const vt = types.find((t) => t.id === visit) ?? types[0];
  const hplan = guide.health_plans.find((x) => x.id === health?.plan_id);
  const pplan = guide.pet_plans.find((x) => x.id === pet?.plan_id);
  const up = w.telehealth?.upcoming;
  const slots = days.find((d) => d.date === date)?.slots ?? [];
  const pets = pet?.pets ?? [];
  const thePet = pets.find((x) => x.pet_id === petId) ?? pets[0];
  const amt = Number(amount) || 0;
  const dedLeft = pplan ? Math.max(0, pplan.annual_deductible - (pet?.usage?.deductible_met_usd ?? 0)) : 0;
  const routine = !!reason && ROUTINE.includes(reason) && !pet?.routine_care;
  const back = pplan && !routine ? Math.max(0, Math.round((amt - Math.min(amt, dedLeft)) * pplan.reimbursement_pct) / 100) : 0;
  const wr = w.wearable;

  return (
    <ScrollView contentContainerStyle={form.body} keyboardShouldPersistTaps="handled">
      {tabs.length > 1 ? (
        <View style={form.seg}>
          {tabs.map((t) => (
            <Pressable key={t} onPress={() => { setTab(t); setReqId(null); }} style={[form.segBtn, tab === t && form.segOn]}>
              <Text style={[form.segText, { fontSize: theme.type.sm }, tab === t && { color: theme.color.onDark }]}>{TAB_LABEL[t]}</Text>
            </Pressable>
          ))}
        </View>
      ) : null}

      {reqId ? <RequestTracker id={reqId} onRetry={() => setReqId(null)} /> : tab === 'telehealth' ? (
        up ? (
          <Card style={{ padding: 18, gap: 6 }}>
            <Pill label="Booked" tone="ok" icon="checkmark-circle" />
            <Text style={form.h2}>{fmtDate(up.date, { weekday: 'long', month: 'long', day: 'numeric' })} · {up.time}</Text>
            <Text style={form.meta}>{up.type_name} video visit with {up.provider}</Text>
            {up.reason ? <Text style={form.meta}>For: {up.reason}</Text> : null}
            <Text style={form.meta}>The join link appears here 10 minutes before. {w.telehealth?.visits_used ?? 0} visit{w.telehealth?.visits_used === 1 ? '' : 's'} used this year.</Text>
          </Card>
        ) : days.length === 0 ? (
          <Empty icon="videocam-outline" title="No appointments on this phone yet" body="Ask Harborline about a telehealth visit while you're online and the open times sync here." />
        ) : (
          <>
            <Text style={form.meta}>
              A video visit with a licensed clinician, usually the same or next day.{' '}
              {hplan ? (hplan.telehealth_copay ? `${money(hplan.telehealth_copay)} copay on ${hplan.name}.` : `No copay on ${hplan.name}.`) : 'Televet visits are included with your pet plan.'}
            </Text>
            <SectionTitle title="What kind of visit?" />
            <ChoiceRow options={types.map((t) => ({ value: t.id, label: t.name }))} value={vt?.id} onChange={setVisit} />
            <SectionTitle title="Day" />
            <ChoiceRow options={days.map((d) => ({ value: d.date, label: short(d.date), disabled: !d.slots.some((s) => s.open > 0) }))} value={date} onChange={(d) => { setDate(d); setTime(undefined); }} />
            <SectionTitle title="Time" />
            <ChoiceRow options={slots.map((s) => ({ value: s.time, label: s.open > 0 ? s.time : `${s.time} · full`, disabled: s.open <= 0 }))} value={time} onChange={setTime} />
            <SectionTitle title="What's it about? (optional)" />
            <TextInput value={why} onChangeText={setWhy} style={form.input} placeholderTextColor={theme.color.faint} placeholder="e.g. a sore throat for three days" />
            <View style={{ marginTop: 16 }}>
              <Button label={date && time ? `Book ${short(date)} at ${time}` : 'Choose a time'} icon="videocam" disabled={!date || !time || !vt}
                onPress={() => date && time && vt && void send('book_telehealth', { date, time, visit_type: vt.id, reason: why.trim() }, `Telehealth · ${vt.name} · ${short(date)} ${time}`)} />
            </View>
            <Text style={form.tiny}>Not for emergencies: call 911. {OFFLINE_NOTE}</Text>
          </>
        )
      ) : tab === 'deductible' && w.deductible ? (
        <>
          <Card style={{ padding: 18, gap: 14 }}>
            <View style={form.rowBetween}>
              <Text style={form.h3}>{hplan?.name ?? 'Your plan'}</Text>
              <Pill label={`Resets ${fmtDate(w.deductible.resets, { month: 'short', day: 'numeric' })}`} tone="neutral" />
            </View>
            <Bar label="Deductible" value={w.deductible.met_usd} max={w.deductible.individual_usd} />
            <Bar label="Out-of-pocket maximum" value={w.deductible.oop_met_usd} max={w.deductible.oop_max_usd} />
            <Text style={form.meta}>
              {w.deductible.met_usd >= w.deductible.individual_usd
                ? 'Your deductible is met: you now pay copays only.'
                : `${money(w.deductible.individual_usd - w.deductible.met_usd)} to go. Telehealth and preventive care don't wait for the deductible.`}
            </Text>
          </Card>
          <SectionTitle title="What you pay" />
          <Card style={{ padding: 16, gap: 8 }}>
            {(health?.coverages ?? []).map((c) => (
              <View key={c.name} style={form.rowBetween}><Text style={form.meta}>{c.name}</Text><Text style={styles.title}>{c.limit}</Text></View>
            ))}
          </Card>
          {hplan ? <Text style={[form.meta, { marginTop: 10 }]}>{hplan.blurb}</Text> : null}
        </>
      ) : tab === 'pet' && pet && pplan ? (
        <>
          <Card style={{ padding: 16, gap: 6 }}>
            <View style={form.rowBetween}>
              <Text style={form.h3}>{pplan.name}</Text>
              <Pill label={`${pplan.reimbursement_pct}% back`} tone="ok" />
            </View>
            <Text style={form.meta}>{pets.map((x) => `${x.name} (${x.breed}, ${x.age})`).join(' · ')}</Text>
            <Bar label="Annual deductible" value={pet.usage?.deductible_met_usd ?? 0} max={pplan.annual_deductible} />
            <Text style={form.meta}>Up to {money(pplan.annual_limit)} a year · {pet.routine_care ? 'routine care included' : 'routine care not included'}</Text>
          </Card>
          <SectionTitle title="Submit a vet bill" />
          {pets.length > 1 ? <ChoiceRow options={pets.map((x) => ({ value: x.pet_id, label: x.name }))} value={thePet?.pet_id} onChange={setPetId} /> : null}
          <Pressable onPress={() => setPhotos(photos + 1)}>
            <Card style={styles.snap}>
              <Ionicons name={photos ? 'document-text' : 'camera'} size={24} color={theme.color.ink} />
              <View style={{ flex: 1 }}>
                <Text style={styles.title}>{photos ? `${photos} photo${photos > 1 ? 's' : ''} of the invoice` : 'Photograph the itemized invoice'}</Text>
                <Text style={form.meta}>{photos ? 'Tap to add another page' : 'Kept on this phone until it syncs'}</Text>
              </View>
              {photos ? <Ionicons name="checkmark-circle" size={22} color={theme.color.ok} /> : null}
            </Card>
          </Pressable>
          <TextInput value={amount} onChangeText={setAmount} keyboardType="decimal-pad" style={form.input} placeholderTextColor={theme.color.faint} placeholder="Bill total, e.g. 240" />
          <TextInput value={clinic} onChangeText={setClinic} style={[form.input, { marginTop: 10 }]} placeholderTextColor={theme.color.faint} placeholder="Clinic name" />
          <SectionTitle title="Reason for the visit" />
          <ChoiceRow options={guide.vet_visit_reasons.map((r) => ({ value: r, label: r }))} value={reason} onChange={setReason} />
          <SectionTitle title="Visit date" />
          <ChoiceRow options={[0, -1, -2, -3, -7, -14].map((n) => ({ value: addDays(today, n), label: n === 0 ? 'Today' : n === -1 ? 'Yesterday' : short(addDays(today, n)) }))} value={visitDate} onChange={setVisitDate} />
          {amt > 0 && reason ? (
            <Card style={[styles.estimate, routine && { backgroundColor: theme.color.peach }]}>
              <Text style={[styles.title, { color: routine ? theme.color.warn : theme.color.ok }]}>
                {routine ? 'Routine care is only covered with the routine care add-on.' : `Estimated ${money(back)} back`}
              </Text>
              {!routine ? <Text style={form.meta}>{pplan.reimbursement_pct}% of {money(amt)}{dedLeft ? ` after ${money(Math.min(amt, dedLeft))} of your deductible` : ''}. {amt <= 600 ? 'Approved automatically, paid in 2 days.' : 'Over $600: reviewed in about 2 business days.'}</Text> : null}
            </Card>
          ) : null}
          <View style={{ marginTop: 16 }}>
            <Button label="Submit bill" icon="paw" disabled={!thePet || amt < 5 || clinic.trim().length < 3 || !reason || !visitDate || photos < 1}
              onPress={() => thePet && reason && visitDate && void send('submit_vet_bill', { pet_id: thePet.pet_id, amount_usd: amt, clinic: clinic.trim(), visit_date: visitDate, reason, photos }, `Vet bill · ${thePet.name} · ${money(amt)}`)} />
          </View>
          <Text style={form.tiny}>{OFFLINE_NOTE}</Text>
          {(w.vet_bills ?? []).length ? <SectionTitle title="Earlier bills" /> : null}
          {[...(w.vet_bills ?? [])].reverse().map((b) => (
            <Card key={b.bill_id} style={styles.bill}>
              <Ionicons name="paw" size={18} color={theme.color.red} />
              <View style={{ flex: 1 }}>
                <Text style={styles.title}>{b.pet_name} · {b.reason} · {money(b.amount_usd)}</Text>
                <Text style={form.meta}>{b.bill_id} · {b.clinic} · {fmtDate(b.visit_date)}{b.reimbursement_usd ? ` · ${money(b.reimbursement_usd)} back` : b.deductible_applied_usd ? ' · applied to your deductible' : ''}</Text>
              </View>
              <Pill label={b.status.replace(/_/g, ' ')} tone={b.status === 'approved' ? 'ok' : b.status === 'denied' ? 'danger' : 'orange'} />
            </Card>
          ))}
        </>
      ) : tab === 'wearable' ? (
        <>
          {wr?.linked ? (
            <Card style={{ padding: 18, gap: 6, backgroundColor: theme.color.ink }}>
              <Pill label={`${wr.device} linked`} tone="dark" icon="watch" />
              <Text style={styles.points}>{(wr.points ?? 0).toLocaleString('en-US')}<Text style={styles.pointsUnit}> points</Text></Text>
              <Text style={styles.onDark}>{money(wr.reward_usd ?? 0)} off your premium · {(wr.steps_7d_avg ?? 0).toLocaleString('en-US')} steps a day this week</Text>
            </Card>
          ) : (
            <Card style={{ padding: 16, gap: 6 }}>
              <Text style={form.h3}>Walk your premium down</Text>
              <Text style={form.meta}>
                {guide.points_per_goal_day} points for every {guide.step_goal.toLocaleString('en-US')}-step day. {(1000).toLocaleString('en-US')} points is {money(1000 / guide.points_per_dollar)} off your premium, and linking earns 500 to start.
              </Text>
            </Card>
          )}
          <SectionTitle title={wr?.linked ? 'Switch device' : 'Link a device'} />
          <ChoiceRow options={guide.wearables.map((d) => ({ value: d, label: d, disabled: wr?.linked && wr.device === d }))} value={device} onChange={setDevice} />
          <View style={{ marginTop: 16 }}>
            <Button label={device ? `Link my ${device}` : 'Choose a device'} icon="watch" disabled={!device} onPress={() => device && void send('link_wearable', { device }, `${device} linked`)} />
          </View>
          <Text style={form.tiny}>We read steps and active minutes only. Never heart rate, sleep or location.</Text>
        </>
      ) : null}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  title: { fontWeight: '700', color: theme.color.text, flexShrink: 1 },
  bar: { height: 10, borderRadius: 5, backgroundColor: theme.color.bg, overflow: 'hidden' },
  barFill: { height: 10, borderRadius: 5, backgroundColor: theme.color.red },
  snap: { flexDirection: 'row', gap: 12, alignItems: 'center', padding: 16, marginVertical: 10, backgroundColor: theme.color.peach, borderWidth: 1.5, borderColor: theme.color.ink, borderStyle: 'dashed' },
  estimate: { padding: 14, gap: 4, marginTop: 14, backgroundColor: theme.color.okSoft },
  bill: { flexDirection: 'row', gap: 10, alignItems: 'center', padding: 14, marginBottom: 10 },
  points: { color: theme.color.red, fontSize: 48, fontWeight: '600', fontFamily: theme.font.display, letterSpacing: -1 },
  pointsUnit: { fontSize: theme.type.lg, color: theme.color.onDarkMuted },
  onDark: { color: theme.color.onDarkMuted, fontSize: theme.type.sm },
});

/** Form defaults come from the documents on the phone, so wait for the first read of Couchbase Lite. */
export default function Wellness() {
  const { snap } = useData();
  if (!snap.profile || !snap.catalog) return null;
  return <WellnessScreen />;
}
