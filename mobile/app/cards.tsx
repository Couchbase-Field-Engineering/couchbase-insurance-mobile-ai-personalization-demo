import { Ionicons } from '@expo/vector-icons';
import { LinearGradient } from 'expo-linear-gradient';
import { useState } from 'react';
import { ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { useData } from '@/src/data/DataContext';
import { activeOnDemand, activePolicies, LINE_ICON, policySubject, vehicleName } from '@/src/insurance';
import { theme } from '@/src/theme';
import type { OnDemandCoverage, Policy } from '@/src/types';
import { Button, Card, CouchbaseMark, Empty, fmtDate, Pill, SectionTitle } from '@/src/ui/components';
import { ChoiceRow } from '@/src/ui/Choice';
import { form, OFFLINE_NOTE } from '@/src/ui/form';
import { RequestTracker } from '@/src/ui/RequestTracker';

const DELIVERY_LABEL: Record<string, string> = { app: 'In the app', email: 'Email', mail: 'Post' };

/**
 * Use case 1 - digital insurance cards and documents.
 *
 * Every card and document listed here is part of the profile document that
 * Sync Gateway replicated to this phone, so it opens with no signal: at the
 * roadside, at the pharmacy counter, at the vet. Asking for another document
 * (a letter for a lender, a printed card) is a request the assistant runs as
 * a governed `request_document` tool call.
 */
export default function Cards() {
  const { snap, request, sync } = useData();
  const p = snap.profile;
  const cat = snap.catalog;
  const [policyId, setPolicyId] = useState<string | undefined>();
  const [docType, setDocType] = useState<string | undefined>();
  const [delivery, setDelivery] = useState('app');
  const [recipient, setRecipient] = useState('');
  const [reqId, setReqId] = useState<string | null>(null);
  if (!p || !cat) return <Empty icon="card-outline" title="Loading your cards" body="They sync from Couchbase in a moment and then stay on this phone." />;

  const today = (snap.feed?.today ?? p.export_date).slice(0, 10);
  const pols = activePolicies(p);
  const cover = (p.on_demand?.coverages ?? []).filter((c) => c.end >= today);
  const activeIds = new Set(activeOnDemand(p, today).map((c) => c.coverage_id));
  const pol = pols.find((x) => x.policy_id === policyId) ?? pols[0];
  const types = pol ? cat.doc_types.filter((d) => d.lines.includes(pol.line)) : [];
  const type = types.find((d) => d.id === docType);
  const needsRecipient = docType === 'lender_letter';

  const send = async () => {
    if (!pol || !type) return;
    const req = await request('request_document', { policy_id: pol.policy_id, doc_type: type.id, delivery, recipient: recipient.trim() }, `${type.name} · ${pol.policy_id}`);
    setReqId(req._id);
  };

  return (
    <ScrollView contentContainerStyle={form.body} keyboardShouldPersistTaps="handled">
      <View style={{ flexDirection: 'row', gap: 8, alignItems: 'center', marginBottom: 12 }}>
        <Ionicons name={sync.status === 'paused' || sync.status === 'offline' ? 'cloud-offline' : 'phone-portrait'} size={15} color={theme.color.ok} />
        <Text style={[form.meta, { flex: 1 }]}>Stored on this phone in Couchbase Lite. These open with no signal.</Text>
      </View>

      {pols.filter((x) => x.id_card).map((x) => <IdCard key={x.policy_id} pol={x} phone={x.line === 'auto' ? cat.company.roadside_phone : cat.company.support_phone} />)}
      {cover.map((c) => <Certificate key={c.coverage_id} c={c} active={activeIds.has(c.coverage_id)} />)}
      {!pols.some((x) => x.id_card) && !cover.length ? (
        <Empty icon="card-outline" title="No cards yet" body="An ID card appears here when you have a policy, and a certificate as soon as you switch on on-demand cover." />
      ) : null}

      {pols.map((x) => (
        <View key={x.policy_id}>
          <SectionTitle title={`${x.product} · ${x.policy_id}`} />
          <Card style={{ padding: 4 }}>
            {x.documents.map((d, i) => (
              <View key={d.doc_id} style={[styles.doc, i > 0 && styles.docBorder]}>
                <Ionicons name="document-text" size={18} color={theme.color.red} />
                <View style={{ flex: 1 }}>
                  <Text style={styles.docTitle}>{d.title}</Text>
                  <Text style={form.meta}>{d.doc_id} · issued {fmtDate(d.issued)}{d.pages ? ` · ${d.pages} page${d.pages > 1 ? 's' : ''}` : ''}{d.recipient ? ` · for ${d.recipient}` : ''}</Text>
                </View>
                <Pill label={d.status === 'ready' ? 'On device' : 'Being prepared'} tone={d.status === 'ready' ? 'ok' : 'orange'} />
              </View>
            ))}
          </Card>
        </View>
      ))}

      {pols.length ? (
        reqId ? <RequestTracker id={reqId} onRetry={() => setReqId(null)} /> : (
          <>
            <SectionTitle title="Need another document?" />
            {pols.length > 1 ? (
              <ChoiceRow options={pols.map((x) => ({ value: x.policy_id, label: x.product.replace('Harborline ', '') }))} value={pol?.policy_id} onChange={(v) => { setPolicyId(v); setDocType(undefined); }} />
            ) : null}
            <ChoiceRow options={types.map((d) => ({ value: d.id, label: d.name }))} value={docType} onChange={setDocType} />
            {type ? <Text style={[form.meta, { marginTop: 6 }]}>{type.instant ? 'Ready instantly and saved to this phone.' : 'Prepared by hand: arrives in your documents within one business day.'}</Text> : null}
            <SectionTitle title="Send it" />
            <ChoiceRow options={cat.doc_delivery.map((d) => ({ value: d, label: DELIVERY_LABEL[d] ?? d }))} value={delivery} onChange={setDelivery} />
            {needsRecipient ? (
              <TextInput value={recipient} onChangeText={setRecipient} placeholder="Lender or landlord name" placeholderTextColor={theme.color.faint} style={[form.input, { marginTop: 10 }]} />
            ) : null}
            <View style={{ marginTop: 16 }}>
              <Button label={type ? `Request ${type.name.toLowerCase()}` : 'Choose a document'} icon="document-attach" disabled={!type || (needsRecipient && recipient.trim().length < 3)} onPress={() => void send()} />
            </View>
            <Text style={form.tiny}>{OFFLINE_NOTE}</Text>
          </>
        )
      ) : null}
    </ScrollView>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <View style={{ flex: 1 }}>
      <Text style={styles.k}>{label}</Text>
      <Text style={styles.v} selectable>{value}</Text>
    </View>
  );
}

const CARD_COLORS: Record<string, [string, string]> = { auto: ['#000000', '#333333'], health: ['#EC1218', '#7C0206'], pet: ['#6E6757', '#9B9382'] };

function IdCard({ pol, phone }: { pol: Policy; phone: string }) {
  const c = pol.id_card;
  if (!c) return null;
  const full: Intl.DateTimeFormatOptions = { month: 'short', day: 'numeric', year: 'numeric' };
  return (
    <LinearGradient colors={CARD_COLORS[pol.line] ?? CARD_COLORS.auto} start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }} style={styles.card}>
      <View style={styles.overlay} pointerEvents="none" />
      <View style={styles.cardHead}>
        <View style={{ flexDirection: 'row', gap: 8, alignItems: 'center' }}>
          <CouchbaseMark size={22} />
          <Text style={styles.brand}>{pol.product}</Text>
        </View>
        <Ionicons name={LINE_ICON[pol.line]} size={20} color={theme.color.onDark} />
      </View>
      <Text style={styles.eyebrow}>{pol.line === 'auto' ? 'INSURANCE IDENTIFICATION CARD' : 'MEMBER ID CARD'}</Text>
      <Text style={styles.insured}>{c.insured}</Text>
      <View style={styles.rows}>
        <Row label={pol.line === 'auto' ? 'POLICY NUMBER' : 'MEMBER ID'} value={c.number} />
        <Row label="VALID" value={`${fmtDate(c.valid_from, full)} - ${fmtDate(c.valid_to, full)}`} />
      </View>
      {pol.vehicles?.map((v) => (
        <View key={v.vehicle_id} style={styles.rows}>
          <Row label="VEHICLE" value={vehicleName(v)} />
          <Row label="VIN / PLATE" value={`…${v.vin_last6} · ${v.plate}`} />
        </View>
      ))}
      {pol.line === 'auto' ? (
        <View style={styles.rows}>
          <Row label="NAIC" value={c.naic ?? ''} />
          <Row label="ROADSIDE & CLAIMS" value={phone} />
        </View>
      ) : (
        <View style={styles.rows}>
          <Row label="PLAN" value={c.plan ?? pol.product} />
          <Row label={pol.line === 'health' ? 'GROUP / RX BIN' : 'COVERED'} value={pol.line === 'health' ? `${c.group ?? ''} · ${c.rx_bin ?? ''}` : policySubject(pol)} />
        </View>
      )}
    </LinearGradient>
  );
}

function Certificate({ c, active }: { c: OnDemandCoverage; active: boolean }) {
  return (
    <LinearGradient colors={['#FC9D0C', '#EC1218']} start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }} style={styles.card}>
      <View style={styles.cardHead}>
        <View style={{ flexDirection: 'row', gap: 8, alignItems: 'center' }}>
          <CouchbaseMark size={22} />
          <Text style={styles.brand}>Harborline On-Demand</Text>
        </View>
        <Pill label={active ? 'Active now' : 'Scheduled'} tone="dark" icon={active ? 'checkmark-circle' : 'time-outline'} />
      </View>
      <Text style={styles.eyebrow}>CERTIFICATE OF COVERAGE</Text>
      <Text style={styles.insured}>{c.name}</Text>
      <View style={styles.rows}>
        <Row label="CERTIFICATE" value={c.coverage_id} />
        <Row label="VALID" value={`${fmtDate(c.start)} - ${fmtDate(c.end)}`} />
      </View>
      {c.vehicle || c.destination ? <View style={styles.rows}><Row label={c.vehicle ? 'VEHICLE' : 'DESTINATION'} value={c.vehicle ?? c.destination ?? ''} /></View> : null}
      <Text style={styles.covers}>{c.covers.join(' · ')}</Text>
    </LinearGradient>
  );
}

const styles = StyleSheet.create({
  card: { borderRadius: theme.radius, padding: 18, marginBottom: 14, gap: 4, overflow: 'hidden', ...theme.shadow.card },
  cardHead: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 },
  brand: { color: theme.color.onDark, fontWeight: '600', fontFamily: theme.font.display, fontSize: theme.type.md },
  eyebrow: { color: 'rgba(255,255,255,0.7)', fontSize: 10, fontWeight: '700', letterSpacing: 1.6 },
  insured: { color: theme.color.onDark, fontSize: theme.type.xl, fontWeight: '600', fontFamily: theme.font.display, letterSpacing: -0.3, marginBottom: 6 },
  rows: { flexDirection: 'row', gap: 12, marginTop: 8 },
  k: { color: 'rgba(255,255,255,0.65)', fontSize: 9, fontWeight: '700', letterSpacing: 1.2 },
  v: { color: '#FFFFFF', fontSize: theme.type.sm, fontWeight: '700', marginTop: 1 },
  covers: { color: 'rgba(255,255,255,0.9)', fontSize: theme.type.xs, marginTop: 10, lineHeight: 16 },
  overlay: { position: 'absolute', right: -30, top: -30, width: 140, height: 140, borderRadius: 70, backgroundColor: 'rgba(255,255,255,0.06)' },
  doc: { flexDirection: 'row', gap: 10, alignItems: 'center', padding: 12 },
  docBorder: { borderTopWidth: 1, borderTopColor: theme.color.border },
  docTitle: { fontWeight: '700', color: theme.color.text },
});
