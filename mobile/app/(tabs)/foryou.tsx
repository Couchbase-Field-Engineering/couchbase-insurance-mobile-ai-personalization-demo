import { Ionicons } from '@expo/vector-icons';
import { Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useData } from '@/src/data/DataContext';
import { theme } from '@/src/theme';
import type { FeedCard, Profile } from '@/src/types';
import { AreaTag, Card, daysBetween, Empty, Eyebrow, fmtDate, GradientArt, money, Pill, SectionTitle, STATUS_UI, SyncBadge, Wordmark } from '@/src/ui/components';
import { activeOnDemand, activePolicies, amountDue, policySubject } from '@/src/insurance';
import { KIND_ICON, KIND_LABEL, openAction } from '@/src/ui/nav';

const AUDIENCE_LABEL = { policyholder: 'Policyholder', member: 'Health & pet member', ondemand: 'On-demand customer' } as const;

/** The one number that matters most to this person today. */
function headline(p: Profile, today: string): { num: string; label: string; title: string; lines: string[] } {
  const pols = activePolicies(p);
  const live = (p.roadside?.dispatches ?? []).find((d) => ['dispatched', 'en_route', 'on_scene'].includes(d.status));
  if (live) return { num: String(live.eta_minutes), label: 'MINUTES AWAY', title: `${live.service_name} on the way`, lines: [live.provider, live.location.label] };
  const owing = pols.filter((x) => amountDue(x) > 0).sort((a, b) => ((a.billing.next_due ?? '') < (b.billing.next_due ?? '') ? -1 : 1))[0];
  if (owing?.billing.past_due) {
    return { num: money(amountDue(owing)), label: 'PAST DUE', title: `${owing.product} · ${policySubject(owing)}`, lines: [owing.policy_id, `Was due ${fmtDate(owing.billing.next_due)}`] };
  }
  const claim = (p.claims ?? []).find((c) => !['paid', 'closed', 'denied'].includes(c.status));
  if (claim) {
    return { num: String(Math.max(0, daysBetween(today, claim.filed_at))), label: 'DAYS SINCE YOU FILED', title: `Claim ${claim.claim_id}`,
      lines: [claim.status.replace(/_/g, ' '), claim.adjuster ? `Adjuster: ${claim.adjuster}` : ''].filter(Boolean) };
  }
  const cover = activeOnDemand(p, today)[0];
  if (cover) return { num: String(Math.max(0, daysBetween(cover.end, today)) + 1), label: 'DAYS OF COVER LEFT', title: cover.name, lines: [cover.vehicle ?? cover.destination ?? '', `Until ${fmtDate(cover.end)}`].filter(Boolean) };
  const plan = p.on_demand?.plans?.drive ?? null;
  if (p.audience === 'ondemand' && plan) {
    return { num: String(Math.max(0, daysBetween(plan.start, today))), label: plan.kind === 'rental' ? 'DAYS TO YOUR RENTAL' : 'DAYS TO BORROWING', title: plan.vehicle, lines: [`${plan.days} days from ${fmtDate(plan.start)}`, 'Not covered yet'] };
  }
  if (owing) return { num: String(Math.max(0, daysBetween(owing.billing.next_due ?? today, today))), label: 'DAYS TO NEXT PAYMENT', title: `${money(amountDue(owing))} · ${owing.product}`, lines: [owing.policy_id, fmtDate(owing.billing.next_due)] };
  const d = p.wellness?.deductible;
  if (d) return { num: `${Math.round((d.met_usd / d.individual_usd) * 100)}%`, label: 'OF DEDUCTIBLE MET', title: `${money(d.met_usd)} of ${money(d.individual_usd)}`, lines: [`Resets ${fmtDate(d.resets)}`] };
  return { num: String(pols.length), label: pols.length === 1 ? 'ACTIVE POLICY' : 'ACTIVE POLICIES', title: pols.map((x) => x.product.replace('Harborline ', '')).join(' + ') || 'On-demand cover', lines: [p.home_city] };
}

export default function ForYou() {
  const { snap, sync, refresh } = useData();
  const insets = useSafeAreaInsets();
  const p = snap.profile;
  const today = (snap.feed?.today ?? p?.export_date ?? new Date().toISOString()).slice(0, 10);
  const cards = snap.feed?.cards ?? [];
  const recent = snap.requests.slice(0, 3);
  const hour = new Date().getHours();
  const greet = hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening';
  const h = p ? headline(p, today) : null;

  return (
    <ScrollView style={{ flex: 1, backgroundColor: theme.color.bg }} refreshControl={<RefreshControl refreshing={false} onRefresh={() => void refresh()} />}>
      <View style={[styles.hero, { paddingTop: insets.top + 14 }]}>
        <View style={styles.row}>
          <Wordmark height={16} />
          <SyncBadge sync={sync} dark />
        </View>
        {p && h ? (
          <>
            <Text style={styles.greet}>{greet}, {p.first_name}</Text>
            <View style={styles.countRow}>
              <View>
                <Text style={styles.countNum}>{h.num}</Text>
                <Text style={styles.countLbl}>{h.label}</Text>
              </View>
              <View style={{ flex: 1, gap: 4 }}>
                <Text style={styles.heroTitle} numberOfLines={2}>{h.title}</Text>
                {h.lines.map((l) => <Text key={l} style={styles.heroLine}>{l}</Text>)}
              </View>
            </View>
            <View style={[styles.row, { marginTop: 14, justifyContent: 'flex-start', gap: 8, flexWrap: 'wrap' }]}>
              <Pill label={AUDIENCE_LABEL[p.audience]} tone="dark" icon="shield-checkmark" />
              {p.telematics?.enrolled && p.telematics.score ? <Pill label={`DriveWell ${p.telematics.score}`} tone="dark" icon="speedometer" /> : null}
              <Pill label={p.home_city} tone="dark" icon="location-outline" />
            </View>
          </>
        ) : (
          <Text style={[styles.greet, { marginTop: 24 }]}>Loading from Couchbase Lite…</Text>
        )}
      </View>

      <View style={styles.body}>
        {recent.length ? (
          <>
            <SectionTitle title="Your requests" />
            <Card style={{ padding: 4 }}>
              {recent.map((q, i) => {
                const ui = STATUS_UI[q.status] ?? STATUS_UI.pending;
                return (
                  <View key={q._id} style={[styles.req, i > 0 && styles.reqBorder]}>
                    <Ionicons name={ui.icon} size={20} color={theme.color.red} />
                    <View style={{ flex: 1 }}>
                      <Text style={styles.reqTitle}>{q.title}</Text>
                      <Text style={styles.reqSub} numberOfLines={2}>
                        {q.summary ?? (q._local || q.status === 'pending' ? 'Saved on your phone - sends automatically when you have a connection.' : '')}
                      </Text>
                    </View>
                    <Pill label={q._local ? 'On device' : ui.label} tone={q._local ? 'warn' : ui.tone} />
                  </View>
                );
              })}
            </Card>
          </>
        ) : null}

        <SectionTitle title="Picked for you" action={snap.feed ? <Text style={styles.prov}>{snap.feed.segment}</Text> : null} />
        {cards.length === 0 ? (
          <Empty icon="sparkles-outline" title="Personalizing…" body="Your feed syncs from Couchbase in a moment." />
        ) : (
          cards.map((c) => <FeedCardView key={c.card_id} c={c} />)
        )}
        {snap.feed ? (
          <Text style={styles.footnote}>
            Ranked from last night's export ({snap.feed.export_date}, {snap.feed.model_version}) and re-ranked live after everything you do in Harborline.
            Stored on this phone in Couchbase Lite.
          </Text>
        ) : null}
      </View>
    </ScrollView>
  );
}

function FeedCardView({ c }: { c: FeedCard }) {
  const { queueAsk } = useData();
  return (
    <Pressable onPress={() => openAction(c.cta, { title: c.title, price: c.badge, queueAsk })} style={({ pressed }) => [{ marginBottom: 14, opacity: pressed ? 0.92 : 1 }]}>
      <Card>
        <GradientArt palette={c.palette} icon={KIND_ICON[c.kind] ?? 'sparkles'} height={c.rank === 1 ? 118 : 92}>
          <View style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
            <Pill label={KIND_LABEL[c.kind] ?? c.kind} tone="dark" icon={KIND_ICON[c.kind]} />
            {c.rank <= 2 ? <Pill label={c.rank === 1 ? 'Do this first' : 'Next'} tone="dark" icon="sparkles" /> : null}
          </View>
          <Text style={styles.cardTitle} numberOfLines={2}>{c.title}</Text>
        </GradientArt>
        <View style={{ padding: 14, gap: 6 }}>
          <AreaTag area={c.area} />
          <Text style={styles.cardSub}>{c.subtitle}</Text>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
            <Ionicons name="sparkles" size={13} color={theme.color.orange} />
            <Text style={styles.reason}>{c.reason}</Text>
          </View>
          <View style={[styles.row, { marginTop: 6 }]}>
            <Text style={styles.badge}>{c.badge}</Text>
            <View style={styles.cta}>
              <Text style={styles.ctaText}>{c.cta.label}</Text>
              <Ionicons name={c.cta.ask ? 'chatbubble-ellipses' : 'arrow-forward'} size={15} color={theme.color.onDark} />
            </View>
          </View>
        </View>
      </Card>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  hero: { backgroundColor: theme.color.ink, paddingHorizontal: 20, paddingBottom: 26, borderBottomLeftRadius: 28, borderBottomRightRadius: 28 },
  row: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  greet: { color: theme.color.onDark, fontSize: theme.type.title, fontWeight: '600', fontFamily: theme.font.display, marginTop: 22, letterSpacing: -0.4 },
  countRow: { flexDirection: 'row', gap: 18, marginTop: 14, alignItems: 'center' },
  countNum: { color: theme.color.red, fontSize: 48, fontWeight: '600', fontFamily: theme.font.display, lineHeight: 60, letterSpacing: -1.5 },
  countLbl: { color: theme.color.onDarkMuted, fontSize: 10, fontWeight: '700', letterSpacing: 1.6 },
  heroTitle: { color: theme.color.onDark, fontSize: theme.type.lg, fontWeight: '600', fontFamily: theme.font.display },
  heroLine: { color: theme.color.onDarkMuted, fontSize: theme.type.sm },
  body: { padding: 16, maxWidth: 640, width: '100%', alignSelf: 'center' },
  req: { flexDirection: 'row', gap: 10, alignItems: 'center', padding: 12 },
  reqBorder: { borderTopWidth: 1, borderTopColor: theme.color.border },
  reqTitle: { fontWeight: '700', color: theme.color.text },
  reqSub: { color: theme.color.muted, fontSize: theme.type.sm },
  prov: { color: theme.color.red, fontSize: theme.type.xs, fontWeight: '700' },
  cardTitle: { color: theme.color.onDark, fontSize: theme.type.xl, fontWeight: '600', fontFamily: theme.font.display, letterSpacing: -0.3 },
  cardSub: { color: theme.color.text, fontSize: theme.type.md },
  reason: { color: theme.color.body, fontSize: theme.type.sm, fontWeight: '600', flex: 1 },
  badge: { color: theme.color.text, fontWeight: '700', flexShrink: 1, marginRight: 8 },
  cta: { flexDirection: 'row', gap: 6, alignItems: 'center', backgroundColor: theme.color.red, borderRadius: theme.radiusSm, paddingHorizontal: 14, paddingVertical: 9 },
  ctaText: { color: theme.color.onDark, fontWeight: '600', fontSize: theme.type.sm },
  footnote: { color: theme.color.faint, fontSize: theme.type.xs, textAlign: 'center', marginVertical: 18, lineHeight: 16 },
});
