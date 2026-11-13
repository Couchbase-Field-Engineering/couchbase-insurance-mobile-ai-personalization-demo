import { Ionicons } from '@expo/vector-icons';
import { router } from 'expo-router';
import { ActivityIndicator, StyleSheet, Text, View } from 'react-native';
import { useData } from '../data/DataContext';
import { theme } from '../theme';
import { Button, Card, Pill, STATUS_UI } from './components';

/** The Couchbase Labs Agent Operations Manager agent identity that runs each tool - mirrors backend/app/agents.py. */
export const AGENT_OF_TOOL: Record<string, string> = {
  file_claim: 'insurance-claims-agent', add_claim_evidence: 'insurance-claims-agent',
  request_roadside: 'insurance-roadside-agent', send_sos: 'insurance-roadside-agent',
  make_payment: 'insurance-billing-agent', set_autopay: 'insurance-billing-agent', renew_policy: 'insurance-billing-agent', request_fee_waiver: 'insurance-billing-agent',
  enroll_telematics: 'insurance-drive-agent', record_trip: 'insurance-drive-agent', redeem_drive_discount: 'insurance-drive-agent',
  book_telehealth: 'insurance-wellness-agent', submit_vet_bill: 'insurance-wellness-agent', link_wearable: 'insurance-wellness-agent',
  activate_coverage: 'insurance-coverage-agent',
};
export const AGENT_NAME: Record<string, string> = {
  'insurance-assistant': 'Harborline Assistant',
  'insurance-claims-agent': 'Claims Agent',
  'insurance-roadside-agent': 'Roadside Agent',
  'insurance-billing-agent': 'Billing Agent',
  'insurance-drive-agent': 'DriveWell Agent',
  'insurance-wellness-agent': 'Wellness Agent',
  'insurance-coverage-agent': 'Coverage Agent',
};
export const agentOf = (q: { agent?: string; tool: string }) => q.agent ?? AGENT_OF_TOOL[q.tool] ?? 'insurance-assistant';
const APPROVER: Record<string, string> = {
  request_fee_waiver: 'a billing supervisor',
  request_coverage_change: 'an underwriter',
};

/**
 * Live status of one offline-first request, read from the local database:
 * "On device" -> pushed -> processed by the backend through Couchbase Labs Agent Operations Manager -> synced back.
 */
export function RequestTracker({ id, onRetry, retryLabel = 'Try again' }: { id: string; onRetry?: () => void; retryLabel?: string }) {
  const { snap, sync } = useData();
  const q = snap.requests.find((r) => r._id === id);
  if (!q) return null;
  const ui = STATUS_UI[q.status] ?? STATUS_UI.pending;
  const waiting = q._local || q.status === 'pending' || q.status === 'processing';
  const agent = agentOf(q);
  const specialist = agent !== 'insurance-assistant';
  const agentLabel = `Run by the ${AGENT_NAME[agent] ?? agent} through Couchbase Labs Agent Operations Manager`;
  const steps = [
    { label: 'Saved in Couchbase Lite on your phone', done: true },
    { label: sync.status === 'paused' || sync.status === 'offline' ? 'Waiting for a connection…' : 'Synced to Couchbase Server', done: !q._local },
    { label: q.governed === false ? 'Processed (Couchbase Labs Agent Operations Manager not configured - ungoverned)' : agentLabel, done: !waiting },
    ...(specialist && q.governed !== false
      ? [{ label: q.remembered ? `Remembered in Couchbase Labs Agent Operations Manager Agent Memory${q.memories_recalled ? ` · recalled ${q.memories_recalled} earlier` : ''}` : 'Saving the outcome to Couchbase Labs Agent Operations Manager Agent Memory', done: !waiting && !!q.remembered }]
      : []),
    { label: q.status === 'awaiting_approval' ? `Waiting for ${APPROVER[q.tool] ?? 'an approver'} in Couchbase Labs Agent Operations Manager` : 'Result synced back to your phone', done: !waiting && q.status !== 'awaiting_approval' },
  ];
  return (
    <Card style={{ padding: 16, gap: 12, marginTop: 16 }}>
      <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }}>
        <Text style={styles.title}>{q.title}</Text>
        <Pill label={q._local ? 'On device' : ui.label} tone={q._local ? 'warn' : ui.tone} icon={ui.icon} />
      </View>
      {steps.map((s, i) => (
        <View key={i} style={{ flexDirection: 'row', gap: 10, alignItems: 'center' }}>
          {s.done ? (
            <Ionicons name="checkmark-circle" size={18} color={theme.color.ok} />
          ) : i === steps.findIndex((x) => !x.done) && sync.status !== 'paused' ? (
            <ActivityIndicator size="small" color={theme.color.red} />
          ) : (
            <Ionicons name="ellipse-outline" size={18} color={theme.color.faint} />
          )}
          <Text style={{ color: s.done ? theme.color.text : theme.color.muted, flex: 1 }}>{s.label}</Text>
        </View>
      ))}
      {q.summary ? <Text style={[styles.summary, q.status === 'failed' && { color: theme.color.danger }]}>{q.summary}</Text> : null}
      {q.governed ? <Text style={styles.tiny}>Governed by Couchbase Labs Agent Operations Manager{q.trace_id ? ` · trace ${q.trace_id}` : ''}</Text> : null}
      {q.status === 'failed' && onRetry ? <Button label={retryLabel} icon="refresh" onPress={onRetry} /> : null}
      <Button
        label={waiting ? 'Done - it will finish in the background' : 'Done'}
        kind={waiting || (q.status === 'failed' && onRetry) ? 'ghost' : 'ink'}
        onPress={() => (router.canGoBack() ? router.back() : router.replace('/(tabs)'))}
      />
    </Card>
  );
}

const styles = StyleSheet.create({
  title: { fontWeight: '700', color: theme.color.ink, fontSize: theme.type.lg, flex: 1, marginRight: 8, fontFamily: theme.font.display },
  summary: { color: theme.color.text, fontSize: theme.type.md, lineHeight: 21 },
  tiny: { color: theme.color.faint, fontSize: theme.type.xs },
});
