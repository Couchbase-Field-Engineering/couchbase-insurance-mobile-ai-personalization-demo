import { Ionicons } from '@expo/vector-icons';
import { router } from 'expo-router';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useData } from '@/src/data/DataContext';
import { theme } from '@/src/theme';
import type { Profile } from '@/src/types';
import { Button, Card, Empty, fmtDate, money, Pill, SectionTitle, STATUS_UI, type Tone } from '@/src/ui/components';
import { ACTIVITY_ICON } from '@/src/ui/nav';

const ORDER_TONE: Record<string, Tone> = { processing: 'neutral', shipped: 'orange', out_for_delivery: 'red', delivered: 'ok', cancelled: 'neutral' };

/** Everything this person has going on, by audience - all read from Couchbase Lite. */
export default function Activity() {
  const { snap } = useData();
  const insets = useSafeAreaInsets();
  const p = snap.profile;
  if (!p) return <Empty icon="list-outline" title="Nothing yet" body="Your activity syncs from Couchbase in a moment." />;
  const items = [...(snap.activity?.items ?? [])].reverse();

  return (
    <ScrollView style={{ flex: 1, backgroundColor: theme.color.bg }} contentContainerStyle={[styles.body, { paddingTop: insets.top + 12 }]}>
      <Text style={styles.h1}>Activity</Text>
      <Text style={styles.sub}>
        {p.audience === 'customer' ? 'Orders, returns and credits' : p.audience === 'lead' ? `${p.company?.name} · your workspace project` : 'Onboarding, tickets, benefits and time off'}
      </Text>

      {p.audience === 'customer' ? <Customer p={p} /> : null}
      {p.audience === 'lead' ? <Lead p={p} /> : null}
      {p.audience === 'employee' ? <Employee p={p} /> : null}

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
                {[i.date ? fmtDate(i.date) : null, i.time, i.charge_usd ? money(i.charge_usd) : null, i.refund_usd ? `${money(i.refund_usd)} refund` : null,
                  i.label_code ? `code ${i.label_code}` : null].filter(Boolean).join(' · ')}
              </Text>
            </View>
            <Pill label={i.status === 'submitted' ? 'With manager' : 'Done'} tone={i.status === 'submitted' ? 'orange' : 'ok'} />
          </Card>
        ))
      )}

      <SectionTitle title="All requests" />
      {snap.requests.length === 0 ? (
        <Text style={styles.meta}>Requests you make appear here with their status, even offline.</Text>
      ) : (
        snap.requests.map((q) => {
          const ui = STATUS_UI[q.status] ?? STATUS_UI.pending;
          return (
            <Card key={q._id} style={styles.item}>
              <Ionicons name={ui.icon} size={18} color={theme.color.red} />
              <View style={{ flex: 1 }}>
                <Text style={styles.itemTitle}>{q.title}</Text>
                {q.summary ? <Text style={styles.meta}>{q.summary}</Text> : null}
                <Text style={styles.tiny}>
                  {q.governed ? `Governed by Agent Operations Manager · ${q.agent === 'insurance-returns-agent' ? 'Returns Agent' : 'Harborline Assistant'}` : q._local ? 'Queued in Couchbase Lite' : 'Processed'}
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

function Customer({ p }: { p: Profile }) {
  const orders = p.orders ?? [];
  return (
    <>
      <SectionTitle title="Orders" />
      {orders.length === 0 ? <Text style={styles.meta}>No orders yet.</Text> : null}
      {orders.map((o) => (
        <Pressable key={o.order_id} onPress={() => router.push({ pathname: '/order', params: { order_id: o.order_id } })}>
          <Card style={styles.item}>
            <Ionicons name="cube" size={18} color={theme.color.red} />
            <View style={{ flex: 1 }}>
              <Text style={styles.itemTitle}>{o.items.map((i) => i.name).join(', ')}</Text>
              <Text style={styles.meta}>
                {o.order_id} · {money(o.total_usd)} ·{' '}
                {o.status === 'delivered' ? `delivered ${fmtDate(o.delivered_at)}` : o.eta ? `arriving ${fmtDate(o.eta)}${o.delivery_window ? `, ${o.delivery_window}` : ''}` : ''}
              </Text>
            </View>
            <Pill label={o.status.replace(/_/g, ' ')} tone={ORDER_TONE[o.status] ?? 'neutral'} />
          </Card>
        </Pressable>
      ))}
      {p.cart?.items?.length ? (
        <>
          <SectionTitle title="Your cart" />
          <Card style={{ padding: 16, gap: 6 }}>
            {p.cart.items.map((i) => (
              <View key={i.sku} style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
                <Text style={styles.itemTitle}>{i.name}</Text>
                <Text style={styles.meta}>{money(i.price)}</Text>
              </View>
            ))}
            {p.cart.offer ? <Text style={styles.meta}>Code {p.cart.offer.code}: {p.cart.offer.pct_off}% off until {fmtDate(p.cart.offer.expires)}</Text> : null}
            <View style={{ marginTop: 8, alignItems: 'flex-start' }}>
              <Button small label="Check out" icon="cart" onPress={() => router.push({ pathname: '/confirm', params: { tool: 'checkout_cart', args: JSON.stringify({ apply_offer: true }), title: 'Check out your cart', price: money(p.cart!.subtotal_usd * (1 - (p.cart!.offer?.pct_off ?? 0) / 100)) } })} />
            </View>
          </Card>
        </>
      ) : null}
      {(p.returns ?? []).length ? (
        <>
          <SectionTitle title="Returns in progress" />
          {(p.returns ?? []).map((r) => (
            <Card key={r.return_id} style={styles.item}>
              <Ionicons name={r.resolution === 'exchange' ? 'swap-horizontal' : 'return-down-back'} size={18} color={theme.color.red} />
              <View style={{ flex: 1 }}>
                <Text style={styles.itemTitle}>{r.name}</Text>
                <Text style={styles.meta}>{r.return_id} · drop-off code {r.label_code}{r.exchange_name ? ` · for ${r.exchange_name}` : r.refund_usd ? ` · ${money(r.refund_usd)} refund` : ''}</Text>
              </View>
              <Pill label="Label issued" tone="orange" />
            </Card>
          ))}
        </>
      ) : null}
    </>
  );
}

function Lead({ p }: { p: Profile }) {
  const l = p.lead;
  const c = p.consultation;
  return (
    <>
      <SectionTitle title="Your quote" />
      <Card style={{ padding: 16, gap: 6 }}>
        <Text style={styles.big}>{p.company?.name}</Text>
        <Text style={styles.meta}>{p.company?.industry} · {p.company?.employees} people · {p.company?.city}</Text>
        <View style={{ flexDirection: 'row', gap: 6, flexWrap: 'wrap', marginTop: 6 }}>
          <Pill label={l?.seats ? `${l.seats} seats` : 'Seats: not shared yet'} tone={l?.seats ? 'ok' : 'neutral'} />
          <Pill label={l?.budget_band ?? 'Budget: not shared yet'} tone={l?.budget_band ? 'ok' : 'neutral'} />
          <Pill label={l?.timeline ?? 'Timeline: not shared yet'} tone={l?.timeline ? 'ok' : 'neutral'} />
        </View>
        <Text style={[styles.meta, { marginTop: 6 }]}>{l?.owner ? `Your specialist: ${l.owner}` : 'A specialist is assigned once you share your details.'}</Text>
        {!l?.budget_band ? (
          <View style={{ marginTop: 8, alignItems: 'flex-start' }}>
            <Button small label="Share details" icon="create" onPress={() => router.push({ pathname: '/consult', params: { step: 'details' } })} />
          </View>
        ) : null}
      </Card>
      <SectionTitle title="Consultation" />
      <Card style={{ padding: 16, gap: 6 }}>
        {c ? (
          <>
            <Text style={styles.big}>{fmtDate(c.date, { weekday: 'long', month: 'long', day: 'numeric' })} · {c.time}</Text>
            <Text style={styles.meta}>{c.topic} · {c.channel} · with {c.rep}</Text>
          </>
        ) : (
          <>
            <Text style={styles.meta}>Free, 45 minutes, by video, phone or in store.</Text>
            <View style={{ marginTop: 8, alignItems: 'flex-start' }}>
              <Button small label="Pick a time" icon="calendar" onPress={() => router.push('/consult')} />
            </View>
          </>
        )}
      </Card>
    </>
  );
}

function Employee({ p }: { p: Profile }) {
  const tasks = p.onboarding?.tasks ?? [];
  const done = tasks.filter((t) => t.status === 'complete').length;
  const b = p.hr?.benefits;
  return (
    <>
      <SectionTitle title="Onboarding" />
      <Pressable onPress={() => router.push('/onboarding')}>
        <Card style={{ padding: 16, gap: 8 }}>
          <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }}>
            <Text style={styles.big}>{done} of {tasks.length} complete</Text>
            <Pill label={p.onboarding?.status === 'complete' ? 'Complete' : 'In progress'} tone={p.onboarding?.status === 'complete' ? 'ok' : 'orange'} />
          </View>
          <View style={styles.bar}><View style={[styles.barFill, { width: `${tasks.length ? Math.round((done / tasks.length) * 100) : 0}%` }]} /></View>
          <Text style={styles.meta}>Started {fmtDate(p.employment?.start_date)} · reporting to {p.employment?.manager}</Text>
        </Card>
      </Pressable>
      <SectionTitle title="Help desk tickets" action={<Pressable onPress={() => router.push('/ticket')}><Text style={styles.link}>New ticket</Text></Pressable>} />
      {(p.it?.open_tickets ?? []).length === 0 ? <Text style={styles.meta}>No open tickets.</Text> : null}
      {(p.it?.open_tickets ?? []).map((t) => (
        <Card key={t.ticket_id} style={styles.item}>
          <Ionicons name="construct" size={18} color={theme.color.red} />
          <View style={{ flex: 1 }}>
            <Text style={styles.itemTitle}>{t.summary}</Text>
            <Text style={styles.meta}>{t.ticket_id} · {t.queue ?? t.category} team · opened {fmtDate(t.opened_at)}</Text>
          </View>
          <Pill label={t.status.replace(/_/g, ' ')} tone={t.priority === 'high' ? 'red' : 'orange'} />
        </Card>
      ))}
      <SectionTitle title="Benefits & time off" />
      <Card style={{ padding: 16, gap: 8 }}>
        <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }}>
          <Text style={styles.itemTitle}>{b?.enrolled ? 'Benefits: enrolled' : `Benefits: enroll by ${fmtDate(b?.enrollment_deadline)}`}</Text>
          {!b?.enrolled ? <Button small label="Enroll" onPress={() => router.push('/benefits')} /> : <Pill label="Active" tone="ok" />}
        </View>
        <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }}>
          <Text style={styles.itemTitle}>{p.hr?.pto.balance_days} days of paid time off</Text>
          <Button small kind="ghost" label="Request" onPress={() => router.push('/timeoff')} />
        </View>
        <Text style={styles.meta}>Next pay date {fmtDate(p.hr?.pay.next_pay_date)}</Text>
      </Card>
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
