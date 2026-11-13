import { useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { ScrollView, Text } from 'react-native';
import { useData } from '@/src/data/DataContext';
import { theme } from '@/src/theme';
import { Button, Card, Pill } from '@/src/ui/components';
import { form, OFFLINE_NOTE } from '@/src/ui/form';
import { RequestTracker } from '@/src/ui/RequestTracker';

const TOOL: Record<string, { label: string; note: string }> = {
  request_document: { label: 'Request document', note: 'Instant documents are saved to your phone; letters prepared by hand arrive within one business day.' },
  update_contact_details: { label: 'Update details', note: 'A new address can change an auto or home rate; we confirm the premium by email within a day.' },
  request_policy_change: { label: 'Policy update', note: "A simple update that doesn't change coverage or price: applied the same day." },
  request_coverage_change: { label: 'Coverage change', note: 'This changes who or what is covered. Your request is held for an underwriter in Couchbase Labs Agent Operations Manager before it applies.' },
  request_live_agent: { label: 'Licensed agent', note: 'A licensed agent joins with this conversation and your policies in front of them.' },
  file_claim: { label: 'File a claim', note: 'The Claims Agent files it and remembers the outcome. An adjuster is assigned within one business day.' },
  add_claim_evidence: { label: 'Add to claim', note: 'Your adjuster is notified as soon as it syncs.' },
  request_roadside: { label: 'Roadside assistance', note: 'The Roadside Agent dispatches the nearest provider to your location.' },
  send_sos: { label: 'SOS', note: 'Shares your location with the 24/7 emergency desk, who call you within 2 minutes. Call 911 first if life is at risk.' },
  make_payment: { label: 'Make a payment', note: 'Charged to the card or bank account on file. Posts the same day.' },
  set_autopay: { label: 'AutoPay', note: 'Saves $5 a month. We remind you 3 days before each payment.' },
  renew_policy: { label: 'Renew policy', note: 'Your cover continues without a gap. Paying in full takes 6% off.' },
  request_fee_waiver: { label: 'Late-fee waiver', note: "Fee waivers are reviewed by a billing supervisor in Couchbase Labs Agent Operations Manager before they're applied. You'll see their decision here." },
  enroll_telematics: { label: 'Join DriveWell', note: 'Your phone records trips, even with no signal. Your score can lower your rate but never raise it.' },
  record_trip: { label: 'Record trip', note: 'Scored by the DriveWell Agent as soon as it syncs.' },
  redeem_drive_discount: { label: 'Apply discount', note: 'Applied to your auto renewal offer.' },
  book_telehealth: { label: 'Book telehealth', note: 'A video visit with a licensed clinician. The join link appears 10 minutes before.' },
  submit_vet_bill: { label: 'Submit vet bill', note: 'Bills up to $600 are approved automatically and paid within 2 days.' },
  link_wearable: { label: 'Link wearable', note: 'We read steps and active minutes only.' },
  activate_coverage: { label: 'Activate cover', note: 'Charged to your card on file. Active as soon as it is processed; the certificate is saved on your phone.' },
};

/** One-tap actions from For You and Chat land here before they're queued. */
export default function Confirm() {
  const { tool = '', args = '{}', title = '', price = '' } = useLocalSearchParams<{ tool: string; args: string; title: string; price: string }>();
  const { request } = useData();
  const [reqId, setReqId] = useState<string | null>(null);
  const parsed = JSON.parse(args) as Record<string, unknown>;
  const t = TOOL[tool];

  const submit = async () => {
    const req = await request(tool, parsed, title || t?.label || tool);
    setReqId(req._id);
  };

  return (
    <ScrollView contentContainerStyle={form.body}>
      {reqId ? <RequestTracker id={reqId} onRetry={() => setReqId(null)} /> : (
        <Card style={{ padding: 18, gap: 12 }}>
          <Pill label={t?.label ?? tool} tone="ink" />
          <Text style={form.h2}>{title}</Text>
          {price ? <Text style={[form.h3, { color: theme.color.red }]}>{price}</Text> : null}
          {typeof parsed.reason === 'string' ? <Text style={form.meta}>Reason: {parsed.reason}</Text> : null}
          {typeof parsed.details === 'string' ? <Text style={form.meta}>Details: {parsed.details}</Text> : null}
          <Text style={form.meta}>{t?.note ?? ''}</Text>
          <Button label="Confirm" icon="checkmark" onPress={() => void submit()} />
          <Text style={form.tiny}>{OFFLINE_NOTE}</Text>
        </Card>
      )}
    </ScrollView>
  );
}
