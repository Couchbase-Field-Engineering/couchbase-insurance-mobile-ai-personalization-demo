import { Ionicons } from '@expo/vector-icons';
import { router } from 'expo-router';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useData } from '@/src/data/DataContext';
import { activeOnDemand, amountDue, LINE_ICON, policySubject } from '@/src/insurance';
import { theme } from '@/src/theme';
import type { Profile } from '@/src/types';
import { Card, Empty, fmtDate, money, Pill, SectionTitle, STATUS_UI, type Tone } from '@/src/ui/components';
import { ACTIVITY_ICON } from '@/src/ui/nav';
import { AGENT_NAME, agentOf } from '@/src/ui/RequestTracker';

const CLAIM_TONE: Record<string, Tone> = { submitted: 'neutral', under_review: 'orange', inspection_scheduled: 'orange', estimate_ready: 'red', approved: 'ok', paid: 'ok', denied: 'danger' };
const SUB: Record<string, string> = {
  policyholder: 'Policies, claims, payments and driving',
  member: 'Plans, visits, vet bills and payments',
  ondemand: 'Cover by the day, roadside and certificates',
};

/** Everything this person has going on - all read from Couchbase Lite. */
export default function Activity() {
  const { snap } = useData();
  const insets = useSafeAreaInsets();
  const p = snap.profile;
  if (!p) return <Empty icon="list-outline" title="Nothing yet" body="Your activity syncs from Couchbase in a moment." />;
  const items = [...(snap.activity?.items ?? [])].reverse();
  const today = (snap.feed?.today ?? p.export_date).slice(0, 10);

  return (
    <ScrollView style={{ flex: 1, backgroundColor: theme.color.bg }} contentContainerStyle={[styles.body, { paddingTop: insets.top + 12 }]}>
      <Text style={styles.h1}>Activity</Text>
      <Text style={styles.sub}>{SUB[p.audience]}</Text>

      <Policies p={p} />
      <Claims p={p} />
      <Cover p={p} today={today} />
      {p.audience === 'member' ? <Member p={p} /> : null}

      <SectionTitle title="Done in Harborline" />
      {items.length === 0 ? (
        <Text style={styles.meta}>Nothing yet - ask in Chat or pick something from For You.</Text>
      ) : (
        items.map((i) => (
          <Card key={i.item_id} style={styles.item}>
            <Ionicons name={ACTIVITY_ICON[i.kind] ?? 'checkmark'} size={18} color={theme.color.red} />
            <View style={{ flex: 1 }}>
              <Text style={styles.itemTitle}>{i.title}</Text>
              <Text style={styles.meta}>
                {[i.date ? fmtDate(i.date) : null, i.time, i.charge_usd ? money(i.charge_usd) : null, i.refund_usd ? `${money(i.refund_usd)} back` : null]
                  .filter(Boolean).join(' · ')}
              </Text>
            </View>
            <Pill label={i.status === 'submitted' ? 'In progress' : 'Done'} tone={i.status === 'submitted' ? 'orange' : 'ok'} />
          </Card>
        ))
      )}

      <SectionTitle title="All requests" />
      {snap.requests.length === 0 ? (
        <Text style={styles.meta}>Requests you make appear here with their status, even offline.</Text>
      ) : (
        snap.requests.map((q) => {
          const ui = STATUS_UI[q.status] ?? STATUS_UI.pending;
          const agent = agentOf(q);
          return (
            <Card key={q._id} style={styles.item}>
              <Ionicons name={ui.icon} size={18} color={theme.color.red} />
              <View style={{ flex: 1 }}>
                <Text style={styles.itemTitle}>{q.title}</Text>
                {q.summary ? <Text style={styles.meta}>{q.summary}</Text> : null}
                <Text style={styles.tiny}>
                  {q.governed ? `Governed by Couchbase Labs Agent Operations Manager · ${AGENT_NAME[agent] ?? agent}` : q._local ? `Queued in Couchbase Lite for the ${AGENT_NAME[agent] ?? agent}` : `Processed · ${AGENT_NAME[agent] ?? agent}`}
                  {q.remembered ? ' · remembered' : ''}
                  {q.trace_id ? ` · trace ${q.trace_id.slice(0, 8)}` : ''}
                </Text>
              </View>
              <Pill label={q._local ? 'On device' : ui.label} tone={q._local ? 'warn' : ui.tone} />
            </Card>
          );
        })
      )}
      <View style={{ height: 30 }} />
    </ScrollView>
  );
}

function Policies({ p }: { p: Profile }) {
  const pols = p.policies ?? [];
  if (!pols.length) return null;
  return (
    <>
      <SectionTitle title="Policies" action={<Pressable onPress={() => router.push('/cards')}><Text style={styles.link}>ID cards</Text></Pressable>} />
      {pols.map((pol) => {
        const due = amountDue(pol);
        const offered = pol.renewal?.status === 'offered';
        return (
          <Pressable key={pol.policy_id} onPress={() => router.push({ pathname: '/pay', params: { policy_id: pol.policy_id } })}>
            <Card style={styles.item}>
              <Ionicons name={LINE_ICON[pol.line] ?? 'shield'} size={18} color={theme.color.red} />
              <View style={{ flex: 1 }}>
                <Text style={styles.itemTitle}>{pol.product}</Text>
                <Text style={styles.meta}>{pol.policy_id} · {policySubject(pol)}</Text>
                <Text style={styles.meta}>
                  {due > 0 ? `${money(due)} ${pol.billing.past_due ? 'past due' : `due ${fmtDate(pol.billing.next_due)}`}` : pol.billing.autopay ? `AutoPay on the ${pol.billing.autopay_day}th` : `Next payment ${fmtDate(pol.billing.next_due)}`}
                  {offered ? ` · renews ${fmtDate(pol.expires)}` : pol.renewal?.status === 'renewed' ? ' · renewed' : ''}
                </Text>
              </View>
              <Pill label={pol.billing.past_due ? 'Past due' : offered ? 'Renewal offer' : 'Active'} tone={pol.billing.past_due ? 'danger' : offered ? 'orange' : 'ok'} />
            </Card>
          </Pressable>
        );
      })}
    </>
  );
}

function Claims({ p }: { p: Profile }) {
  const claims = p.claims ?? [];
  const canFile = (p.policies ?? []).some((x) => ['auto', 'home', 'renters'].includes(x.line));
  if (!claims.length && !canFile) return null;
  return (
    <>
      <SectionTitle title="Claims" action={canFile ? <Pressable onPress={() => router.push('/claim')}><Text style={styles.link}>File a claim</Text></Pressable> : null} />
      {claims.length === 0 ? <Text style={styles.meta}>No claims. If something happens, you can file one here in a couple of minutes - even offline.</Text> : null}
      {claims.map((c) => (
        <Pressable key={c.claim_id} onPress={() => router.push({ pathname: '/claim', params: { claim_id: c.claim_id } })}>
          <Card style={styles.item}>
            <Ionicons name="camera" size={18} color={theme.color.red} />
            <View style={{ flex: 1 }}>
              <Text style={styles.itemTitle}>{c.claim_id} · {c.loss_type.replace(/_/g, ' ')}</Text>
              <Text style={styles.meta}>
                Filed {fmtDate(c.filed_at)}{c.adjuster ? ` · ${c.adjuster}` : ''}{c.estimate_usd ? ` · estimate ${money(c.estimate_usd)}` : ''}
              </Text>
            </View>
            <Pill label={c.status.replace(/_/g, ' ')} tone={CLAIM_TONE[c.status] ?? 'neutral'} />
          </Card>
        </Pressable>
      ))}
    </>
  );
}

function Cover({ p, today }: { p: Profile; today: string }) {
  const covs = [...(p.on_demand?.coverages ?? [])].sort((a, b) => (a.start < b.start ? 1 : -1));
  const active = new Set(activeOnDemand(p, today).map((c) => c.coverage_id));
  if (!covs.length && p.audience !== 'ondemand') return null;
  return (
    <>
      <SectionTitle title="On-demand cover" action={<Pressable onPress={() => router.push('/coverage')}><Text style={styles.link}>Get cover</Text></Pressable>} />
      {covs.length === 0 ? <Text style={styles.meta}>Nothing bought yet. Cover starts minutes after you confirm.</Text> : null}
      {covs.map((c) => (
        <Pressable key={c.coverage_id} onPress={() => router.push('/cards')}>
          <Card style={styles.item}>
            <Ionicons name="flash" size={18} color={theme.color.red} />
            <View style={{ flex: 1 }}>
              <Text style={styles.itemTitle}>{c.name}</Text>
              <Text style={styles.meta}>{c.coverage_id} · {fmtDate(c.start)} to {fmtDate(c.end)} · {money(c.price_usd)}{c.vehicle ? ` · ${c.vehicle}` : c.destination ? ` · ${c.destination}` : ''}</Text>
            </View>
            <Pill label={active.has(c.coverage_id) ? 'Active' : c.start > today ? 'Scheduled' : 'Ended'} tone={active.has(c.coverage_id) ? 'ok' : c.start > today ? 'orange' : 'neutral'} />
          </Card>
        </Pressable>
      ))}
    </>
  );
}

function Member({ p }: { p: Profile }) {
  const w = p.wellness ?? {};
  const d = w.deductible;
  const up = w.telehealth?.upcoming;
  return (
    <>
      <SectionTitle title="Health & wellness" action={<Pressable onPress={() => router.push('/wellness')}><Text style={styles.link}>Open</Text></Pressable>} />
      {d ? (
        <Card style={{ padding: 16, gap: 8, marginBottom: 10 }}>
          <Text style={styles.big}>{money(d.met_usd)} of {money(d.individual_usd)} deductible met</Text>
          <View style={styles.bar}><View style={[styles.barFill, { width: `${Math.min(100, Math.round((d.met_usd / d.individual_usd) * 100))}%` }]} /></View>
          <Text style={styles.meta}>Out-of-pocket {money(d.oop_met_usd)} of {money(d.oop_max_usd)} · resets {fmtDate(d.resets)}</Text>
        </Card>
      ) : null}
      {up ? (
        <Card style={styles.item}>
          <Ionicons name="videocam" size={18} color={theme.color.red} />
          <View style={{ flex: 1 }}>
            <Text style={styles.itemTitle}>{up.type_name} with {up.provider}</Text>
            <Text style={styles.meta}>{fmtDate(up.date)} at {up.time}</Text>
          </View>
          <Pill label="Booked" tone="ok" />
        </Card>
      ) : null}
      {(w.vet_bills ?? []).map((b) => (
        <Card key={b.bill_id} style={styles.item}>
          <Ionicons name="paw" size={18} color={theme.color.red} />
          <View style={{ flex: 1 }}>
            <Text style={styles.itemTitle}>{b.pet_name} · {b.reason}</Text>
            <Text style={styles.meta}>{b.bill_id} · {b.clinic} · {money(b.amount_usd)}{b.reimbursement_usd ? ` · ${money(b.reimbursement_usd)} back` : b.deductible_applied_usd ? ' · applied to your deductible' : ''}</Text>
          </View>
          <Pill label={b.status.replace(/_/g, ' ')} tone={b.status === 'approved' ? 'ok' : 'orange'} />
        </Card>
      ))}
    </>
  );
}

const styles = StyleSheet.create({
  body: { padding: 16, maxWidth: 640, width: '100%', alignSelf: 'center' },
  h1: { fontSize: theme.type.title, fontWeight: '600', fontFamily: theme.font.display, color: theme.color.ink, letterSpacing: -0.4 },
  sub: { color: theme.color.muted, marginTop: 2 },
  big: { fontSize: theme.type.lg, fontWeight: '600', fontFamily: theme.font.display, color: theme.color.ink },
  meta: { color: theme.color.muted, fontSize: theme.type.sm },
  tiny: { color: theme.color.faint, fontSize: theme.type.xs, marginTop: 2 },
  link: { color: theme.color.red, fontWeight: '700', fontSize: theme.type.sm },
  item: { flexDirection: 'row', gap: 10, alignItems: 'center', padding: 14, marginBottom: 10 },
  itemTitle: { fontWeight: '700', color: theme.color.text, flexShrink: 1 },
  bar: { height: 8, borderRadius: 4, backgroundColor: theme.color.bg, overflow: 'hidden' },
  barFill: { height: 8, borderRadius: 4, backgroundColor: theme.color.red },
});
