import { Ionicons } from '@expo/vector-icons';
import { useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { useData } from '@/src/data/DataContext';
import { activePolicies, amountDue, driveDiscountPct, LINE_ICON, PAY_IN_FULL_DISCOUNT_PCT, policySubject } from '@/src/insurance';
import { theme } from '@/src/theme';
import { Button, Card, Empty, fmtDate, money, Pill, SectionTitle } from '@/src/ui/components';
import { ChoiceRow } from '@/src/ui/Choice';
import { form, OFFLINE_NOTE } from '@/src/ui/form';
import { RequestTracker } from '@/src/ui/RequestTracker';

const METHODS = ['card on file', 'bank account'];

/**
 * Use case 4 - premium payments and renewals.
 *
 * What is due, AutoPay and the renewal offer are all in the profile document
 * on the phone. Each action is a request the Billing Agent runs through AOM:
 * a payment, an AutoPay change, accepting a renewal. A late-fee waiver is a
 * goodwill gesture, so AOM holds it for a billing supervisor's approval and
 * the phone shows "Awaiting approval" until the decision syncs back.
 *
 * Reminders: the For You feed raises a payment card inside the grace window
 * and a renewal card about 30 days before the term ends. Because the feed is
 * a replicated document, the reminder is on the phone before it is opened.
 */
export default function Pay() {
  const params = useLocalSearchParams<{ policy_id?: string; renew?: string }>();
  const { snap, request } = useData();
  const p = snap.profile;
  const [policyId, setPolicyId] = useState<string | undefined>(params.policy_id);
  const [method, setMethod] = useState(METHODS[0]);
  const [plan, setPlan] = useState<'monthly' | 'pay_in_full'>('monthly');
  const [day, setDay] = useState<number | undefined>();
  const [reason, setReason] = useState('');
  const [reqId, setReqId] = useState<string | null>(null);
  if (!p) return null;
  const pols = activePolicies(p);
  if (!pols.length) {
    return <Empty icon="wallet-outline" title="Nothing to pay" body="On-demand cover is charged to your card when you activate it. There is no bill or renewal to manage." />;
  }
  const pol = pols.find((x) => x.policy_id === policyId) ?? [...pols].sort((a, b) => amountDue(b) - amountDue(a))[0];
  const b = pol.billing;
  const due = amountDue(pol);
  const r = pol.renewal;
  const t = p.telematics;
  const earned = pol.line === 'auto' && t?.enrolled && t.program === 'safe-driver' && !t.redeemed && (t.trips?.length ?? 0) >= 5 ? driveDiscountPct(t.score) : 0;
  const fullPrice = r ? Math.round(r.offer_premium_usd * (1 - PAY_IN_FULL_DISCOUNT_PCT / 100) * 100) / 100 : 0;
  const payments = [...(p.payments ?? [])].filter((x) => x.policy_id === pol.policy_id).reverse().slice(0, 4);

  const go = async (tool: string, args: Record<string, unknown>, title: string) => {
    const req = await request(tool, { policy_id: pol.policy_id, ...args }, title);
    setReqId(req._id);
  };

  return (
    <ScrollView contentContainerStyle={form.body} keyboardShouldPersistTaps="handled">
      {pols.length > 1 ? (
        <ChoiceRow options={pols.map((x) => ({ value: x.policy_id, label: `${x.product.replace('Harborline ', '')}${amountDue(x) > 0 ? ` · ${money(amountDue(x))}` : ''}` }))} value={pol.policy_id}
          onChange={(v) => { setPolicyId(v); setReqId(null); }} />
      ) : null}

      <Card style={{ padding: 18, gap: 6, marginTop: 10 }}>
        <View style={form.rowBetween}>
          <View style={{ flexDirection: 'row', gap: 8, alignItems: 'center' }}>
            <Ionicons name={LINE_ICON[pol.line]} size={18} color={theme.color.red} />
            <Text style={styles.title}>{pol.product}</Text>
          </View>
          <Pill label={b.past_due ? 'Past due' : due > 0 ? 'Due soon' : 'Paid up'} tone={b.past_due ? 'danger' : due > 0 ? 'orange' : 'ok'} />
        </View>
        <Text style={form.meta}>{pol.policy_id} · {policySubject(pol)}</Text>
        <Text style={[form.big, { textAlign: 'left', marginTop: 6 }]}>{money(due > 0 ? due : b.installment_usd)}</Text>
        <Text style={form.meta}>
          {due > 0
            ? `${b.past_due ? 'Was due' : 'Due'} ${fmtDate(b.next_due)}${b.late_fee_usd ? ` · includes a ${money(b.late_fee_usd)} late fee` : ''}`
            : `Next payment ${fmtDate(b.next_due)}${b.autopay ? ` · AutoPay on the ${b.autopay_day}th` : ''}`}
        </Text>
        <Text style={form.meta}>{b.plan === 'monthly' ? 'Monthly' : 'Paid in full'} · {b.method.type} ending {b.method.last4}</Text>
      </Card>

      {reqId ? <RequestTracker id={reqId} onRetry={() => setReqId(null)} /> : (
        <>
          <SectionTitle title={due > 0 ? 'Pay now' : 'Pay ahead'} />
          <ChoiceRow options={METHODS.map((m) => ({ value: m, label: m === 'card on file' ? `Card ending ${b.method.type === 'card' ? b.method.last4 : 'on file'}` : 'Bank account' }))} value={method} onChange={setMethod} />
          <View style={{ marginTop: 10 }}>
            <Button label={`Pay ${money(due > 0 ? due : b.installment_usd)}`} icon="card" onPress={() => void go('make_payment', { amount_usd: 0, method }, `Payment · ${pol.policy_id}`)} />
          </View>

          {b.plan === 'monthly' ? (
            <>
              <SectionTitle title="AutoPay" action={<Pill label={b.autopay ? 'On' : 'Off'} tone={b.autopay ? 'ok' : 'neutral'} />} />
              <Card style={{ padding: 14, gap: 10 }}>
                <Text style={form.meta}>{b.autopay ? `We take ${money(b.installment_usd)} on the ${b.autopay_day}th of each month and remind you 3 days before.` : 'Never miss a payment, and save $5 a month. We remind you 3 days before each one.'}</Text>
                {!b.autopay ? <ChoiceRow options={[1, 5, 10, 15, 20, 25].map((d) => ({ value: String(d), label: `${d}th`.replace('1th', '1st') }))} value={day ? String(day) : undefined} onChange={(v) => setDay(Number(v))} /> : null}
                <Button kind={b.autopay ? 'ghost' : 'ink'} label={b.autopay ? 'Turn AutoPay off' : day ? `Turn on · the ${day}${day === 1 ? 'st' : 'th'} of each month` : 'Turn AutoPay on'} icon="repeat"
                  onPress={() => void go('set_autopay', { enabled: !b.autopay, day: b.autopay ? 0 : day ?? 0 }, `AutoPay ${b.autopay ? 'off' : 'on'} · ${pol.policy_id}`)} />
              </Card>
            </>
          ) : null}

          {r?.status === 'offered' ? (
            <>
              <SectionTitle title="Your renewal offer" action={<Text style={form.meta}>renews {fmtDate(pol.expires)}</Text>} />
              <Card style={{ padding: 16, gap: 8 }}>
                <View style={form.rowBetween}>
                  <Text style={form.h3}>{money(r.offer_premium_usd)}</Text>
                  {r.change_pct ? <Pill label={`${r.change_pct > 0 ? '+' : ''}${r.change_pct}% vs this term`} tone={r.change_pct > 0 ? 'orange' : 'ok'} /> : null}
                </View>
                {(r.discounts ?? []).map((d) => <Text key={d} style={form.meta}>✓ {d}</Text>)}
                {earned ? (
                  <View style={styles.earned}>
                    <Ionicons name="speedometer" size={16} color={theme.color.ok} />
                    <Text style={{ flex: 1, color: theme.color.ok, fontWeight: '700' }}>Your DriveWell score of {t?.score} has earned {earned}% off this offer.</Text>
                    <Button small label="Apply" onPress={() => void request('redeem_drive_discount', {}, `DriveWell discount · ${earned}% off renewal`).then((q) => setReqId(q._id))} />
                  </View>
                ) : null}
                <View style={form.seg}>
                  {(['monthly', 'pay_in_full'] as const).map((k) => (
                    <Pressable key={k} onPress={() => setPlan(k)} style={[form.segBtn, plan === k && form.segOn]}>
                      <Text style={[form.segText, plan === k && { color: theme.color.onDark }]}>{k === 'monthly' ? 'Monthly' : `In full · ${PAY_IN_FULL_DISCOUNT_PCT}% off`}</Text>
                    </Pressable>
                  ))}
                </View>
                <Button label={plan === 'monthly' ? `Renew · ${money(r.offer_premium_usd)} for the term` : `Renew and pay ${money(fullPrice)} now`} icon="refresh-circle"
                  disabled={b.past_due} onPress={() => void go('renew_policy', { pay_plan: plan }, `Renew · ${pol.policy_id}`)} />
                {b.past_due ? <Text style={form.meta}>Pay the past-due amount first, then renew.</Text> : null}
              </Card>
            </>
          ) : r?.status === 'renewed' ? (
            <>
              <SectionTitle title="Renewal" />
              <Card style={{ padding: 16, gap: 4 }}>
                <Pill label="Renewed" tone="ok" icon="checkmark-circle" />
                <Text style={form.meta}>Your cover continues from {fmtDate(pol.expires)} with no gap.</Text>
              </Card>
            </>
          ) : (
            <Text style={[form.meta, { marginTop: 18 }]}>This policy runs to {fmtDate(pol.expires)}. Your renewal offer arrives here about 30 days before, with a reminder in For You.</Text>
          )}

          {b.late_fee_usd > 0 ? (
            <>
              <SectionTitle title="Ask for the late fee to be waived" />
              <Card style={{ padding: 14, gap: 10 }}>
                <Text style={form.meta}>A waiver is a goodwill gesture (once a year, up to $50). The Billing Agent prepares it and a billing supervisor approves it in Couchbase AOM.</Text>
                <TextInput value={reason} onChangeText={setReason} placeholder="What happened? e.g. my card was replaced after fraud" placeholderTextColor={theme.color.faint} style={form.input} />
                <Button kind="ghost" label={`Request a ${money(b.late_fee_usd)} waiver`} icon="gift" disabled={reason.trim().length < 8} onPress={() => void go('request_fee_waiver', { reason: reason.trim() }, `Late-fee waiver · ${pol.policy_id}`)} />
              </Card>
            </>
          ) : null}

          {payments.length ? (
            <>
              <SectionTitle title="Recent payments" />
              <Card style={{ padding: 14, gap: 8 }}>
                {payments.map((x) => (
                  <View key={x.payment_id} style={form.rowBetween}>
                    <Text style={form.meta}>{fmtDate(x.at)} · {x.method}</Text>
                    <Text style={styles.title}>{money(x.amount_usd)}</Text>
                  </View>
                ))}
              </Card>
            </>
          ) : null}
          <Text style={form.tiny}>{OFFLINE_NOTE}</Text>
        </>
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  title: { fontWeight: '700', color: theme.color.text },
  earned: { flexDirection: 'row', gap: 8, alignItems: 'center', backgroundColor: theme.color.okSoft, borderRadius: theme.radiusSm, padding: 10 },
});
