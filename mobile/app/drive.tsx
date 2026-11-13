import { Ionicons } from '@expo/vector-icons';
import { useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useData } from '@/src/data/DataContext';
import { activePolicies, driveDiscountPct, vehicleName } from '@/src/insurance';
import { theme } from '@/src/theme';
import { Button, Card, Empty, fmtDate, Pill, SectionTitle, type IconName } from '@/src/ui/components';
import { ChoiceRow } from '@/src/ui/Choice';
import { form, OFFLINE_NOTE } from '@/src/ui/form';
import { RequestTracker } from '@/src/ui/RequestTracker';

const DEVICES = ['phone', 'plug-in beacon', 'connected car'];
const FACTOR: Record<string, { label: string; icon: IconName }> = {
  braking: { label: 'Smooth braking', icon: 'hand-left' },
  speed: { label: 'Speed', icon: 'speedometer' },
  night: { label: 'Time of day', icon: 'moon' },
  phone: { label: 'Phone use', icon: 'phone-portrait' },
  mileage: { label: 'Mileage', icon: 'map' },
};
/** What the phone's motion sensors would summarize for one drive (the demo's stand-in for a recorded trip). */
const SAMPLE_TRIPS = [
  { id: 'commute', label: 'Smooth commute', miles: 12.4, minutes: 31, hard_brakes: 0, speeding_events: 0, night: false, phone_use: 0 },
  { id: 'errands', label: 'Stop-start errands', miles: 6.8, minutes: 24, hard_brakes: 2, speeding_events: 0, night: false, phone_use: 1 },
  { id: 'highway', label: 'Fast highway run', miles: 48.0, minutes: 44, hard_brakes: 1, speeding_events: 3, night: false, phone_use: 0 },
  { id: 'late', label: 'Late-night drive', miles: 18.2, minutes: 29, hard_brakes: 0, speeding_events: 1, night: true, phone_use: 0 },
];

/**
 * Use case 5 - telematics and usage-based insurance.
 *
 * A trip is recorded on the phone whether or not there is a signal: its
 * summary (miles, minutes, hard brakes, speeding, phone use) is written to
 * Couchbase Lite as a `record_trip` request and replicated later. The
 * DriveWell Agent scores it, updates the score and the factors in the
 * profile, and remembers how the driving is trending. A score of 70 or more
 * earns a renewal discount that one tap applies to the renewal offer.
 */
export default function Drive() {
  const { snap, request } = useData();
  const p = snap.profile;
  const cat = snap.catalog;
  const [program, setProgram] = useState<'safe-driver' | 'pay-per-mile'>('safe-driver');
  const [vehicleId, setVehicleId] = useState<string | undefined>();
  const [device, setDevice] = useState(DEVICES[0]);
  const [trip, setTrip] = useState(SAMPLE_TRIPS[0].id);
  const [reqId, setReqId] = useState<string | null>(null);
  if (!p || !cat) return null;
  const auto = activePolicies(p, 'auto');
  const vehicles = auto.flatMap((x) => x.vehicles ?? []);
  if (!vehicles.length) {
    return <Empty icon="speedometer-outline" title="DriveWell comes with Harborline Auto" body="It scores how you drive from your phone and takes up to 25% off an auto policy. Ask in Chat about adding one." />;
  }
  const t = p.telematics;
  const send = async (tool: string, args: Record<string, unknown>, title: string) => {
    const req = await request(tool, args, title);
    setReqId(req._id);
  };

  if (!t?.enrolled) {
    const progs = cat.telematics_programs;
    return (
      <ScrollView contentContainerStyle={form.body}>
        <Text style={form.h2}>Drive well, pay less</Text>
        <Text style={form.meta}>Your phone records each trip, even with no signal. Your score can lower your rate but never raise it.</Text>
        {reqId ? <RequestTracker id={reqId} onRetry={() => setReqId(null)} /> : (
          <>
            <SectionTitle title="Choose a program" />
            {(Object.keys(progs) as ('safe-driver' | 'pay-per-mile')[]).map((k) => (
              <Pressable key={k} onPress={() => setProgram(k)}>
                <Card style={[form.opt, program === k && form.optSel]}>
                  <Ionicons name={k === 'safe-driver' ? 'ribbon' : 'map'} size={22} color={theme.color.red} />
                  <View style={{ flex: 1 }}>
                    <Text style={styles.title}>{progs[k].name}</Text>
                    <Text style={form.meta}>{progs[k].blurb}</Text>
                  </View>
                </Card>
              </Pressable>
            ))}
            <SectionTitle title="Which car?" />
            <ChoiceRow options={vehicles.map((v) => ({ value: v.vehicle_id, label: vehicleName(v) }))} value={vehicleId ?? vehicles[0].vehicle_id} onChange={setVehicleId} />
            <SectionTitle title="Track with" />
            <ChoiceRow options={DEVICES.map((d) => ({ value: d, label: d === 'phone' ? 'This phone' : d[0].toUpperCase() + d.slice(1) }))} value={device} onChange={setDevice} />
            <View style={{ marginTop: 16 }}>
              <Button label={`Join ${progs[program]?.name ?? 'DriveWell'}`} icon="speedometer"
                onPress={() => void send('enroll_telematics', { vehicle_id: vehicleId ?? vehicles[0].vehicle_id, program, device }, `Join ${progs[program]?.name ?? 'DriveWell'}`)} />
            </View>
            <Text style={form.tiny}>{OFFLINE_NOTE}</Text>
          </>
        )}
      </ScrollView>
    );
  }

  const trips = [...(t.trips ?? [])].reverse();
  const pct = driveDiscountPct(t.score);
  const safe = t.program === 'safe-driver';
  const v = vehicles.find((x) => x.vehicle_id === t.vehicle_id) ?? vehicles[0];
  const offered = auto.some((x) => x.renewal?.status === 'offered');
  const canRedeem = safe && !t.redeemed && trips.length >= 5 && pct > 0;
  const sample = SAMPLE_TRIPS.find((x) => x.id === trip) ?? SAMPLE_TRIPS[0];
  const ppm = cat.telematics_programs['pay-per-mile'];
  const next = [70, 78, 85, 90, 95].find((s) => s > (t.score ?? 0));

  return (
    <ScrollView contentContainerStyle={form.body}>
      <Card style={styles.hero}>
        <View style={form.rowBetween}>
          <Pill label={cat.telematics_programs[t.program ?? 'safe-driver']?.name ?? 'DriveWell'} tone="dark" icon="speedometer" />
          <Text style={styles.heroMeta}>{vehicleName(v)} · {t.device}</Text>
        </View>
        <View style={{ flexDirection: 'row', alignItems: 'flex-end', gap: 14, marginTop: 8 }}>
          <Text style={styles.score}>{t.score ?? '–'}</Text>
          <View style={{ flex: 1, paddingBottom: 12 }}>
            <Text style={styles.heroTitle}>{safe ? (pct ? `${pct}% off at renewal` : 'No discount yet') : `${t.miles_month ?? 0} miles this month`}</Text>
            <Text style={styles.heroMeta}>
              {safe
                ? next ? `Reach ${next} for ${driveDiscountPct(next)}% off` : 'Top tier reached'
                : ppm ? `$${ppm.base_usd_month} base + ${ppm.cents_per_mile}¢ a mile ≈ $${Math.round((ppm.base_usd_month ?? 0) + ((t.miles_month ?? 0) * (ppm.cents_per_mile ?? 0)) / 100)} so far` : ''}
            </Text>
          </View>
        </View>
        <Text style={styles.heroMeta}>{trips.length} trips · {t.miles_term ?? 0} miles this term · since {fmtDate(t.enrolled_at)}</Text>
      </Card>

      {reqId ? <RequestTracker id={reqId} onRetry={() => setReqId(null)} /> : null}

      {canRedeem && !reqId ? (
        <Card style={styles.redeem}>
          <Ionicons name="pricetag" size={20} color={theme.color.ok} />
          <Text style={{ flex: 1, color: theme.color.ok, fontWeight: '700' }}>{offered ? `Take ${pct}% off your renewal offer.` : `You've earned ${pct}% off. It applies when your renewal offer arrives.`}</Text>
          {offered ? <Button small label="Apply" onPress={() => void send('redeem_drive_discount', {}, `DriveWell discount · ${pct}% off renewal`)} /> : null}
        </Card>
      ) : null}
      {t.redeemed ? <Card style={styles.redeem}><Ionicons name="checkmark-circle" size={20} color={theme.color.ok} /><Text style={{ flex: 1, color: theme.color.ok, fontWeight: '700' }}>Your DriveWell discount is applied to your renewal.</Text></Card> : null}

      <SectionTitle title="What makes up your score" />
      <Card style={{ padding: 16, gap: 12 }}>
        {Object.entries(t.factors ?? {}).map(([k, val]) => (
          <View key={k} style={{ gap: 4 }}>
            <View style={form.rowBetween}>
              <View style={{ flexDirection: 'row', gap: 8, alignItems: 'center' }}>
                <Ionicons name={FACTOR[k]?.icon ?? 'analytics'} size={15} color={theme.color.red} />
                <Text style={styles.title}>{FACTOR[k]?.label ?? k}</Text>
              </View>
              <Text style={styles.title}>{val}</Text>
            </View>
            <View style={styles.bar}><View style={[styles.barFill, { width: `${Math.max(0, Math.min(100, val))}%` }, val < 85 && { backgroundColor: theme.color.orange }]} /></View>
          </View>
        ))}
      </Card>

      {!reqId ? (
        <>
          <SectionTitle title="Record a trip" />
          <Card style={{ padding: 14, gap: 10 }}>
            <Text style={form.meta}>On a real drive the phone's sensors write this summary when you park. Pick one to send it now:</Text>
            <ChoiceRow options={SAMPLE_TRIPS.map((x) => ({ value: x.id, label: x.label }))} value={trip} onChange={setTrip} />
            <Text style={form.meta}>
              {sample.miles} mi · {sample.minutes} min · {sample.hard_brakes} hard brake{sample.hard_brakes === 1 ? '' : 's'} · {sample.speeding_events} speeding · {sample.phone_use} phone use{sample.night ? ' · at night' : ''}
            </Text>
            <Button kind="ink" label="Save trip" icon="navigate" onPress={() => {
              const { id: _id, label, ...args } = sample;
              void send('record_trip', args, `Trip · ${label} · ${sample.miles} mi`);
            }} />
          </Card>
        </>
      ) : null}

      <SectionTitle title="Recent trips" />
      {trips.length === 0 ? <Text style={form.meta}>No trips yet. Five trips give you a score that counts.</Text> : null}
      {trips.slice(0, 8).map((x) => (
        <Card key={x.trip_id} style={styles.trip}>
          <View style={[styles.badge, x.score < 85 && { backgroundColor: theme.color.peach }]}><Text style={styles.badgeText}>{x.score}</Text></View>
          <View style={{ flex: 1 }}>
            <Text style={styles.title}>{fmtDate(x.date)} · {x.miles} mi · {x.minutes} min</Text>
            <Text style={form.meta}>
              {[x.hard_brakes ? `${x.hard_brakes} hard brake${x.hard_brakes > 1 ? 's' : ''}` : null, x.speeding ? `${x.speeding} speeding` : null, x.phone_use ? 'phone use' : null, x.night ? 'night' : null]
                .filter(Boolean).join(' · ') || 'A clean drive'}
            </Text>
          </View>
        </Card>
      ))}
      <Text style={form.tiny}>{OFFLINE_NOTE}</Text>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  hero: { padding: 18, backgroundColor: theme.color.ink, gap: 2 },
  score: { color: theme.color.red, fontSize: 72, fontWeight: '600', fontFamily: theme.font.display, letterSpacing: -2, lineHeight: 78 },
  heroTitle: { color: theme.color.onDark, fontSize: theme.type.lg, fontWeight: '600', fontFamily: theme.font.display },
  heroMeta: { color: theme.color.onDarkMuted, fontSize: theme.type.sm },
  title: { fontWeight: '700', color: theme.color.text },
  redeem: { flexDirection: 'row', gap: 10, alignItems: 'center', padding: 14, marginTop: 12, backgroundColor: theme.color.okSoft },
  bar: { height: 8, borderRadius: 4, backgroundColor: theme.color.bg, overflow: 'hidden' },
  barFill: { height: 8, borderRadius: 4, backgroundColor: theme.color.ok },
  trip: { flexDirection: 'row', gap: 12, alignItems: 'center', padding: 12, marginBottom: 8 },
  badge: { width: 42, height: 42, borderRadius: 21, backgroundColor: theme.color.okSoft, alignItems: 'center', justifyContent: 'center' },
  badgeText: { fontWeight: '700', color: theme.color.ink },
});
