import { Ionicons } from '@expo/vector-icons';
import { useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { useData } from '@/src/data/DataContext';
import { activePolicies, roadsidePlan, vehicleName } from '@/src/insurance';
import { theme } from '@/src/theme';
import { Button, Card, money, Pill, SectionTitle, type IconName } from '@/src/ui/components';
import { ChoiceRow } from '@/src/ui/Choice';
import { form } from '@/src/ui/form';
import { RequestTracker } from '@/src/ui/RequestTracker';

const SERVICE_ICON: Record<string, IconName> = { tow: 'car-sport', flat: 'disc', jump: 'battery-charging', lockout: 'key', fuel: 'water' };
const SOS_ICON: Record<string, IconName> = { accident: 'warning', medical: 'medkit', travel: 'airplane' };

type Fix = { lat: number; lon: number } | null;

/** The device's position, where the platform offers it (browser preview and dev builds with a geolocation provider). */
function locate(): Promise<Fix> {
  return new Promise((resolve) => {
    const geo = (globalThis as { navigator?: { geolocation?: { getCurrentPosition: (ok: (pos: { coords: { latitude: number; longitude: number } }) => void, err: () => void, o?: object) => void } } }).navigator?.geolocation;
    if (!geo) return resolve(null);
    const timer = setTimeout(() => resolve(null), 6000);
    try {
      geo.getCurrentPosition(
        (pos) => { clearTimeout(timer); resolve({ lat: pos.coords.latitude, lon: pos.coords.longitude }); },
        () => { clearTimeout(timer); resolve(null); },
        { timeout: 5000, maximumAge: 60000 },
      );
    } catch {
      clearTimeout(timer);
      resolve(null);
    }
  });
}

/**
 * Use case 3 - roadside and emergency assistance.
 *
 * The request carries the phone's GPS position (or the last location the
 * profile knows, or a typed address) and is saved in Couchbase Lite first:
 * a breakdown is exactly when coverage is patchy. Once it syncs, the
 * Roadside Agent dispatches the nearest provider as a governed tool call and
 * remembers which vehicle it was, so the assistant can say "that's the second
 * flat on the Outback this year". The truck's ETA comes back in the profile.
 */
export default function Roadside() {
  const params = useLocalSearchParams<{ sos?: string }>();
  const { snap, request, offline } = useData();
  const p = snap.profile;
  const cat = snap.catalog;
  const [mode, setMode] = useState<'help' | 'sos'>(params.sos ? 'sos' : 'help');
  const [service, setService] = useState<string | undefined>();
  const [sos, setSos] = useState<string | undefined>();
  const [vehicleId, setVehicleId] = useState<string | undefined>();
  const [typed, setTyped] = useState('');
  const [fix, setFix] = useState<Fix>(null);
  const [locating, setLocating] = useState(false);
  const [note, setNote] = useState('');
  const [reqId, setReqId] = useState<string | null>(null);
  if (!p || !cat) return null;

  const today = (snap.feed?.today ?? p.export_date).slice(0, 10);
  const plan = roadsidePlan(p, today, cat.roadside_payg_usd);
  const vehicles = activePolicies(p, 'auto').flatMap((x) => x.vehicles ?? []);
  const last = p.roadside?.last_location;
  const live = (p.roadside?.dispatches ?? []).find((d) => ['dispatched', 'en_route', 'on_scene'].includes(d.status));
  const svc = cat.roadside_services.find((s) => s.id === service);
  const where = typed.trim() || (fix ? `GPS ${fix.lat.toFixed(4)}, ${fix.lon.toFixed(4)}` : last?.label ?? '');
  const position = { location: typed.trim(), lat: fix?.lat ?? 0, lon: fix?.lon ?? 0 };

  const useGps = async () => {
    setLocating(true);
    setFix(await locate());
    setLocating(false);
  };
  const dispatch = async () => {
    if (!svc) return;
    const req = await request('request_roadside', { service: svc.id, vehicle_id: vehicleId ?? vehicles[0]?.vehicle_id ?? '', ...position, note: note.trim() }, `${svc.name} · ${where || 'my location'}`);
    setReqId(req._id);
  };
  const raise = async () => {
    const k = cat.sos_kinds.find((x) => x.id === sos);
    if (!k) return;
    const req = await request('send_sos', { kind: k.id, ...position, note: note.trim() }, `SOS · ${k.name}`);
    setReqId(req._id);
  };

  return (
    <ScrollView contentContainerStyle={form.body} keyboardShouldPersistTaps="handled">
      {live ? (
        <Card style={styles.live}>
          <View style={form.rowBetween}>
            <Pill label="On the way" tone="dark" icon="navigate" />
            <Text style={styles.liveId}>{live.dispatch_id}</Text>
          </View>
          <Text style={styles.eta}>{live.eta_minutes}<Text style={styles.etaUnit}> min</Text></Text>
          <Text style={styles.liveTitle}>{live.service_name} · {live.provider}</Text>
          <Text style={styles.liveMeta}>{live.vehicle ? `${live.vehicle} · ` : ''}{live.location.label}</Text>
          <Text style={styles.liveMeta}>The driver will text you. Stay somewhere safe, away from traffic.</Text>
        </Card>
      ) : null}

      <View style={form.seg}>
        {(['help', 'sos'] as const).map((m) => (
          <Pressable key={m} onPress={() => { setMode(m); setReqId(null); }} style={[form.segBtn, mode === m && (m === 'sos' ? { backgroundColor: theme.color.red } : form.segOn)]}>
            <Text style={[form.segText, mode === m && { color: theme.color.onDark }]}>{m === 'help' ? 'Roadside help' : 'SOS'}</Text>
          </Pressable>
        ))}
      </View>

      {reqId ? <RequestTracker id={reqId} onRetry={() => setReqId(null)} /> : (
        <>
          {mode === 'help' ? (
            <>
              <View style={{ flexDirection: 'row', gap: 6, flexWrap: 'wrap' }}>
                <Pill
                  label={plan.plan === 'included' ? `Included · ${plan.callsLeft} call${plan.callsLeft === 1 ? '' : 's'} left this term` : plan.plan === 'on-demand' ? 'Included with your on-demand cover' : `${money(plan.costUsd)} per call · no roadside plan`}
                  tone={plan.plan === 'pay-per-use' ? 'orange' : 'ok'} icon="shield-checkmark" />
              </View>
              <SectionTitle title="What do you need?" />
              {cat.roadside_services.map((s) => (
                <Pressable key={s.id} onPress={() => setService(s.id)} disabled={!!live}>
                  <Card style={[form.opt, service === s.id && form.optSel, !!live && { opacity: 0.5 }]}>
                    <Ionicons name={SERVICE_ICON[s.id] ?? 'construct'} size={22} color={theme.color.red} />
                    <View style={{ flex: 1 }}>
                      <Text style={styles.optTitle}>{s.name}</Text>
                      <Text style={form.meta}>{s.detail}</Text>
                    </View>
                    <Text style={form.meta}>~{s.eta_min} min</Text>
                  </Card>
                </Pressable>
              ))}
              {vehicles.length > 1 ? (
                <>
                  <SectionTitle title="Which vehicle?" />
                  <ChoiceRow options={vehicles.map((v) => ({ value: v.vehicle_id, label: vehicleName(v) }))} value={vehicleId ?? vehicles[0].vehicle_id} onChange={setVehicleId} />
                </>
              ) : null}
            </>
          ) : (
            <>
              <Card style={{ padding: 14, backgroundColor: theme.color.dangerSoft, flexDirection: 'row', gap: 10, alignItems: 'center' }}>
                <Ionicons name="call" size={20} color={theme.color.danger} />
                <Text style={{ flex: 1, color: theme.color.danger, fontWeight: '700' }}>If anyone's life is at risk, call 911 first.</Text>
              </Card>
              <SectionTitle title="What's happening?" />
              {cat.sos_kinds.map((k) => (
                <Pressable key={k.id} onPress={() => setSos(k.id)}>
                  <Card style={[form.opt, sos === k.id && form.optSel]}>
                    <Ionicons name={SOS_ICON[k.id] ?? 'alert-circle'} size={22} color={theme.color.red} />
                    <View style={{ flex: 1 }}>
                      <Text style={styles.optTitle}>{k.name}</Text>
                      <Text style={form.meta}>{k.detail}</Text>
                    </View>
                  </Card>
                </Pressable>
              ))}
            </>
          )}

          <SectionTitle title="Where are you?" />
          <Card style={{ padding: 14, gap: 10 }}>
            <View style={{ flexDirection: 'row', gap: 10, alignItems: 'center' }}>
              <Ionicons name={fix ? 'locate' : 'location-outline'} size={20} color={fix ? theme.color.ok : theme.color.red} />
              <View style={{ flex: 1 }}>
                <Text style={styles.optTitle}>{where || 'No location yet'}</Text>
                <Text style={form.meta}>{typed.trim() ? 'Typed by you' : fix ? "From this phone's GPS" : last ? 'Last location we know for you' : 'Share your position or type the nearest address'}</Text>
              </View>
              <Button small kind="ghost" label={fix ? 'Update' : 'Use GPS'} icon="navigate" busy={locating} onPress={() => void useGps()} />
            </View>
            <TextInput value={typed} onChangeText={setTyped} placeholder="Or type the nearest address or mile marker" placeholderTextColor={theme.color.faint} style={form.input} />
            <TextInput value={note} onChangeText={setNote} placeholder={mode === 'help' ? 'Anything the driver should know? (optional)' : 'Anything we should know? (optional)'} placeholderTextColor={theme.color.faint} style={form.input} />
          </Card>

          <View style={{ marginTop: 16 }}>
            {mode === 'help' ? (
              <Button label={live ? 'Help is already on the way' : svc ? `Send ${svc.name.toLowerCase()}${plan.costUsd ? ` · ${money(plan.costUsd)}` : ''}` : 'Choose a service'} icon="navigate"
                disabled={!svc || !where || !!live} onPress={() => void dispatch()} />
            ) : (
              <Button label={sos ? 'Send SOS and share my location' : 'Choose what is happening'} icon="alert-circle" disabled={!sos} onPress={() => void raise()} />
            )}
          </View>
          <Text style={form.tiny}>
            {offline
              ? `You're offline: this is saved on your phone and sent the moment you have a signal. To reach us now, call ${cat.company.roadside_phone}.`
              : `Saved on your phone first, then sent - so it still goes if your signal drops. Or call ${cat.company.roadside_phone}.`}
          </Text>
        </>
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  live: { padding: 18, gap: 4, backgroundColor: theme.color.ink, marginBottom: 6 },
  liveId: { color: theme.color.onDarkMuted, fontSize: theme.type.xs, fontWeight: '700' },
  eta: { color: theme.color.red, fontSize: 52, fontWeight: '600', fontFamily: theme.font.display, letterSpacing: -1.5 },
  etaUnit: { fontSize: theme.type.lg, color: theme.color.onDarkMuted },
  liveTitle: { color: theme.color.onDark, fontWeight: '700', fontSize: theme.type.lg },
  liveMeta: { color: theme.color.onDarkMuted, fontSize: theme.type.sm },
  optTitle: { fontWeight: '700', color: theme.color.text },
});
