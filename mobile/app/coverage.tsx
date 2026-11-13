import { Ionicons } from '@expo/vector-icons';
import { router, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { useData } from '@/src/data/DataContext';
import { activeOnDemand, onDemandQuote } from '@/src/insurance';
import { theme } from '@/src/theme';
import type { OnDemandProduct } from '@/src/types';
import { Button, Card, fmtDate, money, Pill, SectionTitle, type IconName } from '@/src/ui/components';
import { ChoiceRow } from '@/src/ui/Choice';
import { addDays, parse, short } from '@/src/ui/dates';
import { form } from '@/src/ui/form';
import { RequestTracker } from '@/src/ui/RequestTracker';

const ICON: Record<string, IconName> = { 'borrow-car': 'key', 'rental-car': 'car', travel: 'airplane', 'event-day': 'people' };
const daysBetween = (a: string, b: string) => Math.round((parse(b).getTime() - parse(a).getTime()) / 86400000);

/**
 * Use case 8 - short-term, on-demand coverage.
 *
 * Borrowed-car, rental-car, trip and one-day event cover, bought from the
 * phone and active as soon as the request is processed. Products and prices
 * are in the catalog document and the quote is worked out on the device, so
 * the screen is usable offline; the cover itself only starts once the request
 * reaches the Coverage Agent, and the screen says so. The certificate comes
 * back in the profile and appears under ID Cards, with roadside included
 * where the product has it.
 */
function CoverageScreen() {
  const params = useLocalSearchParams<{ product?: string }>();
  const { snap, request, offline } = useData();
  const p = snap.profile;
  const cat = snap.catalog;
  const plans = p?.on_demand?.plans ?? {};
  const products: OnDemandProduct[] = cat?.on_demand ?? snap.feed?.cards.find((c) => c.products?.length)?.products ?? [];
  const today = (snap.feed?.today ?? p?.export_date ?? new Date().toISOString()).slice(0, 10);
  const initial = products.find((x) => x.id === params.product)?.id ?? (plans.drive ? (plans.drive.kind === 'rental' ? 'rental-car' : 'borrow-car') : plans.trip ? 'travel' : products[0]?.id);

  // What we already know about this person's plans pre-fills each product.
  const defaults = (id: string | undefined) => {
    if (id === 'travel' && plans.trip) {
      return { start: plans.trip.depart < today ? today : plans.trip.depart, days: Math.max(1, daysBetween(plans.trip.depart, plans.trip.return) + 1), vehicle: '', destination: plans.trip.destination, cost: String(plans.trip.trip_cost_usd ?? '') };
    }
    if ((id === 'borrow-car' || id === 'rental-car') && plans.drive) {
      return { start: plans.drive.start < today ? today : plans.drive.start, days: plans.drive.days, vehicle: plans.drive.vehicle, destination: '', cost: '' };
    }
    return { start: today, days: 1, vehicle: '', destination: '', cost: '' };
  };
  const d0 = defaults(initial);
  const [productId, setProductId] = useState(initial);
  const [start, setStart] = useState(d0.start);
  const [days, setDays] = useState(d0.days);
  const [vehicle, setVehicle] = useState(d0.vehicle);
  const [destination, setDestination] = useState(d0.destination);
  const [cost, setCost] = useState(d0.cost);
  const [reqId, setReqId] = useState<string | null>(null);
  if (!p || !cat) return null;

  const prod = products.find((x) => x.id === productId);
  const pick = (id: string) => {
    const d = defaults(id);
    setProductId(id);
    setStart(d.start);
    setDays(d.days);
    setVehicle(d.vehicle);
    setDestination(d.destination);
    setCost(d.cost);
    setReqId(null);
  };
  const n = prod ? Math.max(1, Math.min(prod.max_days, days)) : 1;
  const tripCost = Number(cost) || 0;
  const price = prod ? onDemandQuote(prod, n, tripCost) : 0;
  const end = addDays(start, n - 1);
  const needsVehicle = !!prod?.needs.includes('vehicle');
  const needsDestination = !!prod?.needs.includes('destination');
  const ready = !!prod && (!needsVehicle || vehicle.trim().length >= 3) && (!needsDestination || destination.trim().length >= 3);
  const active = activeOnDemand(p, today);
  const upcoming = (p.on_demand?.coverages ?? []).filter((c) => c.start > today);
  const starts = Array.from(new Set([today, addDays(today, 1), addDays(today, 2), d0.start, start])).sort();

  const buy = async () => {
    if (!prod) return;
    const req = await request('activate_coverage', {
      product: prod.id, start_date: start, days: n, vehicle: needsVehicle ? vehicle.trim() : '', destination: needsDestination ? destination.trim() : '', trip_cost_usd: prod.pct_of_trip_cost ? tripCost : 0,
    }, `${prod.name} · ${n} day${n > 1 ? 's' : ''} · ${money(price)}`);
    setReqId(req._id);
  };

  return (
    <ScrollView contentContainerStyle={form.body} keyboardShouldPersistTaps="handled">
      {[...active, ...upcoming].map((c) => (
        <Pressable key={c.coverage_id} onPress={() => router.push('/cards')}>
          <Card style={styles.active}>
            <Ionicons name="shield-checkmark" size={22} color={theme.color.ok} />
            <View style={{ flex: 1 }}>
              <Text style={styles.title}>{c.name}</Text>
              <Text style={form.meta}>{fmtDate(c.start)} to {fmtDate(c.end)}{c.vehicle ? ` · ${c.vehicle}` : c.destination ? ` · ${c.destination}` : ''}</Text>
            </View>
            <Pill label={c.start > today ? 'Scheduled' : 'Active'} tone={c.start > today ? 'orange' : 'ok'} />
          </Card>
        </Pressable>
      ))}

      <Text style={form.h2}>Cover by the day</Text>
      <Text style={form.meta}>No annual policy needed. Pick what you're doing, confirm, and you're covered in minutes.</Text>

      <SectionTitle title="What do you need covered?" />
      {products.map((x) => (
        <Pressable key={x.id} onPress={() => pick(x.id)}>
          <Card style={[form.opt, productId === x.id && form.optSel]}>
            <Ionicons name={ICON[x.id] ?? 'flash'} size={22} color={theme.color.red} />
            <View style={{ flex: 1 }}>
              <Text style={styles.title}>{x.name}</Text>
              <Text style={form.meta}>{x.blurb}</Text>
            </View>
            <Text style={styles.price}>{money(x.price_per_day)}<Text style={form.meta}>/day</Text></Text>
          </Card>
        </Pressable>
      ))}

      {prod ? (
        reqId ? <RequestTracker id={reqId} onRetry={() => setReqId(null)} /> : (
          <>
            {needsVehicle ? (
              <>
                <SectionTitle title="Which car?" />
                <TextInput value={vehicle} onChangeText={setVehicle} style={form.input} placeholderTextColor={theme.color.faint} placeholder="Year, make and model, e.g. 2021 Toyota RAV4" />
              </>
            ) : null}
            {needsDestination ? (
              <>
                <SectionTitle title="Where are you going?" />
                <ChoiceRow options={Array.from(new Set([...(destination ? [destination] : []), ...cat.destinations])).map((x) => ({ value: x, label: x }))} value={destination} onChange={setDestination} />
                <TextInput value={destination} onChangeText={setDestination} style={[form.input, { marginTop: 8 }]} placeholderTextColor={theme.color.faint} placeholder="City, country" />
                <SectionTitle title="Trip cost to protect (optional)" />
                <TextInput value={cost} onChangeText={setCost} keyboardType="decimal-pad" style={form.input} placeholderTextColor={theme.color.faint} placeholder="Flights and bookings, e.g. 2400" />
              </>
            ) : null}
            <SectionTitle title="Starting" />
            <ChoiceRow options={starts.map((s) => ({ value: s, label: s === today ? 'Today' : s === addDays(today, 1) ? 'Tomorrow' : short(s) }))} value={start} onChange={setStart} />
            <SectionTitle title="For how long?" />
            <Card style={{ padding: 16, gap: 8 }}>
              <View style={form.stepper}>
                <Pressable onPress={() => setDays(Math.max(1, n - 1))} style={form.step}><Ionicons name="remove" size={22} color={theme.color.ink} /></Pressable>
                <Text style={[form.big, { minWidth: 120 }]}>{n}<Text style={styles.unit}> day{n > 1 ? 's' : ''}</Text></Text>
                <Pressable onPress={() => setDays(Math.min(prod.max_days, n + 1))} style={form.step}><Ionicons name="add" size={22} color={theme.color.ink} /></Pressable>
              </View>
              <Text style={[form.meta, { textAlign: 'center' }]}>{short(start)}{n > 1 ? ` to ${short(end)}` : ''} · up to {prod.max_days} days</Text>
            </Card>

            <SectionTitle title="What you get" />
            <Card style={{ padding: 16, gap: 6 }}>
              {prod.covers.map((c) => (
                <View key={c} style={{ flexDirection: 'row', gap: 8, alignItems: 'center' }}>
                  <Ionicons name="checkmark-circle" size={16} color={theme.color.ok} />
                  <Text style={{ flex: 1, color: theme.color.text }}>{c}</Text>
                </View>
              ))}
              <View style={[form.rowBetween, styles.total]}>
                <Text style={styles.title}>{money(prod.price_per_day)} × {n} day{n > 1 ? 's' : ''}{prod.pct_of_trip_cost && tripCost ? ` + ${prod.pct_of_trip_cost}% of ${money(tripCost)}` : ''}</Text>
                <Text style={styles.sum}>{money(price)}</Text>
              </View>
            </Card>

            <View style={{ marginTop: 16 }}>
              <Button label={ready ? `Activate · ${money(price)}` : needsVehicle ? 'Tell us which car' : 'Tell us where'} icon="flash" disabled={!ready} onPress={() => void buy()} />
            </View>
            <Text style={form.tiny}>
              {offline
                ? "You're offline: this is saved on your phone, but cover only starts once it syncs and is confirmed. You are not covered until then."
                : 'Charged to your card on file. Cover starts when the request is confirmed; the certificate is saved to this phone.'}
            </Text>
          </>
        )
      ) : null}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  active: { flexDirection: 'row', gap: 12, alignItems: 'center', padding: 14, marginBottom: 12, backgroundColor: theme.color.okSoft },
  title: { fontWeight: '700', color: theme.color.text, flexShrink: 1 },
  price: { fontWeight: '700', color: theme.color.ink, fontSize: theme.type.lg },
  unit: { fontSize: theme.type.lg, color: theme.color.muted },
  total: { borderTopWidth: 1, borderTopColor: theme.color.border, paddingTop: 10, marginTop: 6 },
  sum: { fontWeight: '700', color: theme.color.red, fontSize: theme.type.xl },
});

/** Form defaults come from the documents on the phone, so wait for the first read of Couchbase Lite. */
export default function Coverage() {
  const { snap } = useData();
  if (!snap.profile || !snap.catalog) return null;
  return <CoverageScreen />;
}
