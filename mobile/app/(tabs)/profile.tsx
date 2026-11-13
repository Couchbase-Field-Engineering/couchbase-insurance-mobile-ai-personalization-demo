import { ScrollView, StyleSheet, Switch, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { API_URL } from '@/src/config';
import { useData } from '@/src/data/DataContext';
import { useAuth } from '@/src/session/AuthContext';
import { theme } from '@/src/theme';
import { Button, Card, Field, Pill, SectionTitle, SyncBadge } from '@/src/ui/components';

const AUDIENCE: Record<string, string> = { policyholder: 'Policyholder', member: 'Health & pet member', ondemand: 'On-demand customer' };
const SOURCE = 'Policy administration, claims and billing';
const SCORE_LABEL: Record<string, string> = {
  renewal_propensity: 'Renewal propensity', churn_risk: 'Churn risk', cross_sell_propensity: 'Cross-sell propensity', claim_risk: 'Claim risk',
};

export default function Profile() {
  const { snap, sync, offline, setOffline, dbLocation } = useData();
  const { signOut, session } = useAuth();
  const insets = useSafeAreaInsets();
  const p = snap.profile;
  const s = p?.ml_scores;
  const scores = Object.entries(SCORE_LABEL).filter(([k]) => typeof s?.[k] === 'number');
  const channels = session?.channels ?? [];

  return (
    <ScrollView style={{ flex: 1, backgroundColor: theme.color.bg }} contentContainerStyle={[styles.body, { paddingTop: insets.top + 12 }]}>
      <Text style={styles.h1}>Profile</Text>
      {p ? (
        <Card style={{ padding: 16, marginTop: 12, gap: 6 }}>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12 }}>
            <View style={styles.avatar}><Text style={{ fontWeight: '700', color: theme.color.onDark, fontSize: 18 }}>{p.first_name[0]}{p.last_name[0]}</Text></View>
            <View style={{ flex: 1 }}>
              <Text style={styles.name}>{p.first_name} {p.last_name}</Text>
              <Text style={styles.meta}>{p.email} · {p.home_city}</Text>
            </View>
          </View>
          <View style={{ flexDirection: 'row', gap: 6, flexWrap: 'wrap', marginTop: 8 }}>
            <Pill label={AUDIENCE[p.audience]} tone="ink" />
            {(p.policies ?? []).map((x) => <Pill key={x.policy_id} label={x.product.replace('Harborline ', '')} tone="neutral" />)}
            {p.telematics?.enrolled ? <Pill label={`DriveWell ${p.telematics.score ?? ''}`} tone="orange" icon="speedometer" /> : null}
            {p.history?.customer_since ? <Pill label={`Since ${p.history.customer_since.slice(0, 4)}`} tone="neutral" /> : null}
          </View>
        </Card>
      ) : null}

      {p ? (
        <>
          <SectionTitle title="How Harborline knows you" />
          <Card style={{ padding: 16, gap: 8 }}>
            <Field icon="analytics-outline" label="Source" value={`${SOURCE} · nightly export ${p.export_date}`} />
            <Field icon="git-branch-outline" label="Scores" value={String(s?.model_version)} />
            {p.segments?.length ? <Field icon="layers-outline" label="Segments" value={p.segments.map((a) => a.name).join(' · ')} /> : null}
            <Field icon="people-circle-outline" label="Segment" value={String(s?.segment)} />
            <Field icon="navigate-outline" label="Next best action" value={String(s?.next_best_action).replace(/_/g, ' ')} />
            {Array.isArray(s?.recommended_products) && s.recommended_products.length ? <Field icon="heart-outline" label="Might also need" value={s.recommended_products.join(', ')} /> : null}
            <Field icon="home-outline" label="Address" value={p.address ?? p.home_city} />
            {scores.map(([k, label]) => {
              const v = Number(s?.[k] ?? 0);
              return (
                <View key={k} style={{ gap: 3 }}>
                  <View style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
                    <Text style={styles.meta}>{label}</Text>
                    <Text style={[styles.meta, { fontWeight: '700' }]}>{Math.round(v * 100)}%</Text>
                  </View>
                  <View style={styles.bar}><View style={[styles.barFill, { width: `${Math.round(v * 100)}%` }]} /></View>
                </View>
              );
            })}
            <Text style={styles.tiny}>Profile revision {p.rev} - bumps with everything you do in Harborline, which invalidates your context cache.</Text>
          </Card>
        </>
      ) : null}

      <SectionTitle title="Offline & sync" />
      <Card style={{ padding: 16, gap: 10 }}>
        <SyncBadge sync={sync} />
        <Field icon="server-outline" label="Local database" value={sync.engine === 'couchbase-lite' ? 'Couchbase Lite' : 'Browser preview (in-memory)'} />
        <Field icon="folder-outline" label="Location" value={dbLocation ?? '—'} />
        <Field icon="swap-vertical-outline" label="Replicating with" value={sync.endpoint ?? '—'} />
        <Field icon="git-network-outline" label="Channels" value={channels.join(' · ') || '—'} />
        <Field icon="time-outline" label="Last sync" value={sync.lastSyncAt ? new Date(sync.lastSyncAt).toLocaleTimeString() : '—'} />
        <Field icon="cloud-upload-outline" label="Waiting to send" value={String(sync.pendingPush)} />
        <Text style={styles.tiny}>
          {snap.memberGuide
            ? 'The Member Care Guide document is on this phone because your Sync Gateway user has the members channel.'
            : 'No Member Care Guide on this phone: your Sync Gateway user has no members channel, so it is never replicated here.'}
        </Text>
        {sync.detail ? <Text style={[styles.tiny, { color: theme.color.danger }]}>{sync.detail}</Text> : null}
        <View style={styles.switchRow}>
          <View style={{ flex: 1 }}>
            <Text style={{ fontWeight: '700', color: theme.color.text }}>Offline mode</Text>
            <Text style={styles.meta}>Pause replication to demo offline: show an ID card, file a claim with photos, request a tow and ask Harborline from Couchbase Lite. Requests queue and send when you switch back.</Text>
          </View>
          <Switch value={offline} onValueChange={setOffline} trackColor={{ true: theme.color.red, false: theme.color.border }} thumbColor={theme.color.surface} />
        </View>
      </Card>

      <SectionTitle title="Agent Operations Manager" />
      <Card style={{ padding: 16, gap: 8 }}>
        <Text style={styles.meta}>
          Everything you confirm here becomes a request that a specialist agent runs through Couchbase AOM - Claims, Roadside, Billing, DriveWell,
          Wellness or Coverage - each limited to its own tools, with Agent Memory, a trace and an audit entry. Late-fee waivers wait for a billing
          supervisor and coverage changes for an underwriter. Answers use AOM's Knowledge Base, Context Cache and LLM Cache.
        </Text>
        <Field icon="link-outline" label="Backend" value={API_URL} />
        <Field icon="finger-print-outline" label="User ID" value={session?.user_id ?? '—'} />
      </Card>

      <View style={{ marginVertical: 24 }}>
        <Button label="Sign out" kind="ghost" icon="log-out-outline" onPress={() => void signOut()} />
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  body: { padding: 16, maxWidth: 640, width: '100%', alignSelf: 'center' },
  h1: { fontSize: theme.type.title, fontWeight: '600', fontFamily: theme.font.display, color: theme.color.ink, letterSpacing: -0.4 },
  avatar: { width: 52, height: 52, borderRadius: 26, backgroundColor: theme.color.red, alignItems: 'center', justifyContent: 'center' },
  name: { fontSize: theme.type.xl, fontWeight: '600', fontFamily: theme.font.display, color: theme.color.ink },
  meta: { color: theme.color.muted, fontSize: theme.type.sm },
  tiny: { color: theme.color.faint, fontSize: theme.type.xs },
  bar: { height: 6, borderRadius: 3, backgroundColor: theme.color.bg, overflow: 'hidden' },
  barFill: { height: 6, borderRadius: 3, backgroundColor: theme.color.red },
  switchRow: { flexDirection: 'row', gap: 12, alignItems: 'center', borderTopWidth: 1, borderTopColor: theme.color.border, paddingTop: 12, marginTop: 4 },
});
