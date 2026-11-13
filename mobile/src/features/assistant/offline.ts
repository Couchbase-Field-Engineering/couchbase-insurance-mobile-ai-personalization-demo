/**
 * Offline Harborline: answers from what Couchbase Lite already holds.
 *
 *  1. this person's earlier answers (`chat` doc `answers`, keyed by normalized question)
 *  2. their own documents: profile (policies, claims, billing, DriveWell, wellness),
 *     feed cards and the context cache the server assembled
 *  3. the Help Center FAQ synced in `catalog::v1` - and, on a health or pet
 *     member's phone only, the Member Care Guide FAQ in `wellness::v1`
 *
 * Mirrors backend/app/assistant.py's intent keywords so the same question
 * lands on the same cached context offline as online. The members-only gate
 * holds offline by construction: a phone without a health or pet plan has
 * no Member Care Guide document.
 *
 * Offline matters most at the roadside: ID cards open, a tow or an SOS is
 * queued with the last known location, and a claim is written up with
 * photos, all before the phone finds a signal again.
 */
import type { Snapshot } from '../../db/localDb';
import { activeOnDemand, activePolicies, amountDue, driveDiscountPct, policySubject, roadsidePlan } from '../../insurance';
import type { Area, ChatMessage, Cta, Faq } from '../../types';

// Order matters: on a tie the earlier intent wins (as on the server).
const KEYWORDS: Record<string, string[]> = {
  emergency: ['sos', 'emergency', 'been in an accident', 'after an accident', 'car accident', 'just had an accident', 'had a crash', 'crashed', 'been hit', 'hit me',
    'rear-ended me', 'injured', 'hurt', 'ambulance', 'stranded'],
  roadside: ['tow', 'flat tire', 'flat tyre', 'jump start', 'jump-start', 'jumpstart', 'dead battery', 'battery died', 'battery is dead', 'locked out',
    'locked my keys', 'lockout', 'out of gas', 'out of fuel', 'ran out of', 'broke down', 'broken down', 'breakdown', "won't start", 'wont start', 'roadside', 'stuck on the'],
  wellness: ['telehealth', 'doctor', 'video visit', 'virtual visit', 'nurse', 'therapist', 'dermatolog', 'prescription', 'health deductible', 'out-of-pocket',
    'out of pocket', 'copay', 'vet', 'pet', 'dog', 'cat', 'wearable', 'apple watch', 'fitbit', 'garmin', 'oura', 'steps', 'fitness tracker', 'wellness', 'health plan', 'hsa', 'sick', 'symptom'],
  claim: ['claim', 'file a claim', 'accident', 'damage', 'adjuster', 'estimate', 'repair shop', 'body shop', 'windshield', 'hail', 'stolen', 'break-in', 'broken into',
    'burst pipe', 'leak', 'deductible', 'payout', 'dent', 'scratch', 'photos of', 'rear-ended'],
  telematics: ['drivewell', 'driving score', 'my score', 'telematics', 'safe driver', 'safe-driver', 'pay per mile', 'pay-per-mile', 'mileage', 'miles', 'hard brak',
    'speeding', 'last trip', 'recent trips', 'my trips', 'record a trip', 'usage-based', 'usage based', 'driving discount', 'my driving', 'beacon'],
  billing: ['pay', 'bill', 'premium', 'autopay', 'auto-pay', 'auto pay', 'due', 'late fee', 'past due', 'overdue', 'renew', 'expire', 'expiring', 'went up',
    'price increase', 'refund', 'charge', 'owe', 'balance', 'installment'],
  documents: ['id card', 'insurance card', 'proof of insurance', 'my card', 'document', 'declarations', 'dec page', 'policy booklet', 'certificate', 'lender', 'landlord',
    'mortgage company', 'evidence of insurance', 'copy of my policy', 'pdf', 'wallet', 'policy number', 'letter'],
  coverage: ['on-demand', 'on demand', 'short-term', 'short term', 'temporary', 'borrow', 'rental car', 'renting a car', 'rent a car', 'travel', 'trip protection',
    'my trip', 'trip to', 'vacation', 'holiday', 'flight', 'flying', 'for a day', 'for the weekend', 'this weekend', 'one day', 'few days', 'event', 'activate', 'quote',
    'what cover', 'my cover', 'cover me', 'cover for my'],
  account: ['my address', 'moved', 'moving', 'new address', 'my email', 'my phone', 'phone number', 'contact details', 'my details', 'update my', 'change my',
    'add a driver', 'remove a driver', 'add my', 'new car', 'add a vehicle', 'raise my', 'liability limit', 'coverage change', 'am i covered', 'my coverage', 'my policy',
    'my policies', 'name is wrong', 'misspelled'],
  handoff: ['agent', 'human', 'real person', 'representative', 'speak to', 'talk to', 'call me', 'someone call', 'live chat', 'a person', 'supervisor'],
};
const AREA: Record<string, Area> = {
  emergency: 'roadside', roadside: 'roadside', claim: 'claims', telematics: 'telematics', billing: 'billing', documents: 'documents',
  coverage: 'coverage', wellness: 'wellness', account: 'support', handoff: 'support', general: 'support',
};
const esc = (k: string) => k.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
// A keyword matches at the start of a word ("pet" doesn't match "competitor").
const KW_RE: Record<string, RegExp[]> = Object.fromEntries(
  Object.entries(KEYWORDS).map(([i, kws]) => [i, kws.map((k) => new RegExp(`(^|[^a-z0-9])${esc(k)}`))]),
);

export function classify(q: string): string {
  const m = q.toLowerCase();
  let best = 'general';
  let score = 0;
  for (const [intent, rxs] of Object.entries(KW_RE)) {
    const s = rxs.filter((rx) => rx.test(m)).length;
    if (s > score) {
      best = intent;
      score = s;
    }
  }
  return best;
}

export const normalize = (q: string) => q.toLowerCase().replace(/[^a-z0-9 ]/g, '').trim().slice(0, 120);

const nice = (iso?: string | null) => {
  if (!iso) return '';
  const [y, mo, d] = iso.slice(0, 10).split('-').map(Number);
  return new Date(y, mo - 1, d).toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
};
const usd = (n: number) => `$${n.toLocaleString('en-US', { maximumFractionDigits: n % 1 ? 2 : 0 })}`;

function bestFaq(m: string, pool: Faq[]): Faq | undefined {
  return pool
    .map((f) => ({ f, s: f.keywords.filter((k) => m.includes(k)).reduce((n, k) => n + 1 + (k.split(' ').length - 1), 0) }))
    .filter((x) => x.s > 0)
    .sort((a, b) => b.s - a.s)[0]?.f;
}

const RESTRICTED =
  'Telehealth, deductible tracking, vet bills and wearable rewards are part of Harborline Health and Pet plans, so those answers are only available to members of those plans.';

export function answerOffline(q: string, snap: Snapshot): Omit<ChatMessage, 'id' | 'at' | 'role'> {
  const p = snap.profile;
  const audience = p?.audience ?? 'policyholder';
  const intent = classify(q);
  const area = AREA[intent];
  const prior = snap.chat?.answers?.[normalize(q)];
  if (prior) {
    return { text: prior.reply, intent, area: prior.area ?? area, offline: true, context: { status: 'device', latency_ms: 0 } };
  }
  const m = q.toLowerCase();
  if (intent === 'wellness' && audience !== 'member') {
    // No Member Care Guide on this phone - there is nothing to answer from, by design.
    return { text: RESTRICTED, intent, area, offline: true, restricted: true, context: { status: 'none', latency_ms: 0 } };
  }
  const members = intent === 'wellness';
  const pool = [...(members ? snap.memberGuide?.faq ?? [] : []), ...(snap.catalog?.faq ?? [])];
  const faq = bestFaq(m, pool);
  const ctx = snap.contexts[intent] ?? snap.contexts[`playbook_${intent}`];
  const actions: Cta[] = [];
  let text: string | null = null;
  const procedural = /^\s*(how (do|can|would|should) (i|we)|what (do|should) (i|we) (need|do)|where (do|can) (i|we)|when (do|can|should) (i|we)|do (i|we) need)\b/i.test(q);
  const personal = (/\b(i|i'm|im|i've|me|my|mine|we|our|us)\b/i.test(q) && !procedural) || ['emergency', 'roadside', 'handoff'].includes(intent);

  if (p && personal) {
    const today = (snap.feed?.today ?? p.export_date).slice(0, 10);
    const pols = activePolicies(p);
    if (intent === 'emergency') {
      text = "You're offline, so call 911 first if anyone is hurt. I can queue an SOS with your last known location and it reaches our emergency desk the moment you have a signal - or call "
        + `${snap.catalog?.company.roadside_phone ?? 'the number on your ID card'}. Your ID card is on this phone.`;
      actions.push({ label: 'Open SOS & roadside', screen: 'roadside', args: { sos: '1' } }, { label: 'Show my ID cards', screen: 'cards' });
    } else if (intent === 'roadside') {
      const plan = roadsidePlan(p, today, snap.catalog?.roadside_payg_usd ?? 79);
      const where = p.roadside?.last_location?.label;
      const live = (p.roadside?.dispatches ?? []).find((d) => ['dispatched', 'en_route', 'on_scene'].includes(d.status));
      text = live ? `From your phone: ${live.provider} is on the way to ${live.location.label} for a ${live.service_name.toLowerCase()}, about ${live.eta_minutes} minutes from when it was dispatched. The live ETA updates when you're back online.` : `You're offline, but I can queue roadside help now and it's dispatched as soon as you reconnect${where ? ` - your last known location is ${where}` : ''}. `
        + (plan.plan === 'included' ? `It's included with your auto policy (${plan.callsLeft} call${plan.callsLeft === 1 ? '' : 's'} left this term).`
          : plan.plan === 'on-demand' ? "It's included with your on-demand cover." : `Without a roadside plan it's ${usd(plan.costUsd)} per call.`);
      actions.push({ label: live ? 'Follow the truck' : 'Request roadside help', screen: 'roadside' });
    } else if (intent === 'claim') {
      const open = (p.claims ?? []).find((c) => !['paid', 'closed', 'denied'].includes(c.status));
      if (open) {
        text = `From your phone: claim ${open.claim_id} is ${open.status.replace(/_/g, ' ')}${open.adjuster ? ` with ${open.adjuster}` : ''}`
          + `${open.estimate_usd ? `; the estimate is ${usd(open.estimate_usd)} and your deductible is ${usd(open.deductible_usd ?? 0)}` : ''}. The latest status syncs when you're back online.`;
        actions.push({ label: `Open ${open.claim_id}`, screen: 'claim', args: { claim_id: open.claim_id } });
      } else if (pols.some((x) => ['auto', 'home', 'renters'].includes(x.line))) {
        text = "You can file a claim offline: take the photos, describe what happened and I'll send it to the Claims Agent the moment you reconnect.";
        actions.push({ label: 'File a claim', screen: 'claim' });
      }
    } else if (intent === 'billing' && pols.length) {
      const byDue = [...pols].sort((a, b) => ((a.billing.next_due ?? '') < (b.billing.next_due ?? '') ? -1 : 1));
      const owing = byDue.filter((x) => amountDue(x) > 0);
      const offer = pols.find((x) => x.renewal?.status === 'offered');
      if (/(renew|expire|went up|price increase)/.test(m) && offer?.renewal) {
        const ch = offer.renewal.change_pct;
        text = `From your phone: ${offer.policy_id} renews ${nice(offer.expires)} at ${usd(offer.renewal.offer_premium_usd)}${ch ? ` (${ch > 0 ? '+' : ''}${ch}%)` : ''}. You can accept it offline; it's processed when you reconnect.`;
        actions.push({ label: 'Review renewal', screen: 'pay', args: { policy_id: offer.policy_id, renew: '1' } });
      } else if (owing.length) {
        const o = owing[0];
        text = `From your phone: ${usd(amountDue(o))} is ${o.billing.past_due ? `past due on ${o.policy_id} (including a ${usd(o.billing.late_fee_usd)} late fee)` : `due ${nice(o.billing.next_due)} on ${o.policy_id}`}. Pay now and it posts as soon as you're online.`;
        actions.push({ label: `Pay ${usd(amountDue(o))}`, screen: 'pay', args: { policy_id: o.policy_id } });
      } else {
        const next = byDue[0];
        text = `Nothing is due right now. Your next payment is ${usd(next.billing.installment_usd)} on ${nice(next.billing.next_due)} for ${next.policy_id}${next.billing.autopay ? ', on AutoPay' : ''}.`;
        actions.push({ label: 'Payments & renewals', screen: 'pay' });
      }
    } else if (intent === 'documents') {
      const cards = pols.filter((x) => x.id_card);
      const od = activeOnDemand(p, today);
      const n = cards.length + od.length;
      if (n) {
        text = `Your ${[...cards.map((x) => `${x.line} ID card (${policySubject(x)})`), ...od.map((c) => `${c.name} certificate`)].join(' and ')} ${n > 1 ? 'are' : 'is'} stored on this phone and open${n > 1 ? '' : 's'} without a signal.`;
        actions.push({ label: 'Show my ID cards', screen: 'cards' });
      }
    } else if (intent === 'telematics') {
      const t = p.telematics;
      if (t?.enrolled) {
        const pct = driveDiscountPct(t.score);
        text = `From your phone: your DriveWell score is ${t.score ?? 'not ready yet'} over ${t.trips?.length ?? 0} trips and ${t.miles_month ?? 0} miles this month`
          + `${t.program === 'safe-driver' ? `, worth ${pct}% off at renewal` : ''}. Trips keep recording offline and are scored when they sync.`;
        actions.push({ label: 'My driving', screen: 'drive' });
      } else if (pols.some((x) => x.line === 'auto')) {
        text = "You're not in DriveWell yet. Joining takes 5% off straight away and up to 25% at renewal - you can enroll offline and it starts when you reconnect.";
        actions.push({ label: 'Join DriveWell', screen: 'drive' });
      }
    } else if (intent === 'coverage') {
      const od = activeOnDemand(p, today);
      const plans = p.on_demand?.plans ?? {};
      if (od.length) text = `${od.map((c) => `${c.name} is active until ${nice(c.end)}`).join('; ')}. The certificate is on this phone.`;
      else if (plans.drive || plans.trip) {
        text = `You can set up cover offline${plans.drive ? ` for the ${plans.drive.vehicle}` : ''}${plans.drive && plans.trip ? ' and' : ''}${plans.trip ? ` for your trip to ${plans.trip.destination}` : ''}. `
          + "Prices are saved on this phone; cover starts once the request syncs, so it isn't active until you're back online.";
      } else {
        text = "On-demand prices are saved on this phone: borrowed car $12 a day, rental $9 a day, trips from $19. Cover starts once your request syncs, so it isn't active while you're offline.";
      }
      actions.push({ label: od.length ? 'Show certificate' : 'See on-demand cover', screen: od.length ? 'cards' : 'coverage' });
    } else if (intent === 'wellness' && p.wellness) {
      const w = p.wellness;
      if (/(deductible|out.of.pocket|oop)/.test(m) && w.deductible) {
        const d = w.deductible;
        text = `From your phone: you've met ${usd(d.met_usd)} of your ${usd(d.individual_usd)} deductible and ${usd(d.oop_met_usd)} of your ${usd(d.oop_max_usd)} out-of-pocket maximum. It resets ${nice(d.resets)}.`;
        actions.push({ label: 'See my plan', screen: 'wellness', args: { tab: 'deductible' } });
      } else if (/(vet|pet|dog|cat)/.test(m)) {
        text = "You can submit a vet bill offline: photograph the invoice, enter the total and it's sent to the Wellness Agent when you reconnect.";
        actions.push({ label: 'Submit a vet bill', screen: 'wellness', args: { tab: 'pet' } });
      } else if (w.telehealth?.upcoming) {
        const u = w.telehealth.upcoming;
        text = `Your ${u.type_name.toLowerCase()} video visit with ${u.provider} is ${nice(u.date)} at ${u.time}. Joining it needs a connection.`;
      } else if (/(doctor|telehealth|visit|sick|nurse|therapist)/.test(m)) {
        text = 'Open appointments are saved on this phone. Pick one now and the booking is confirmed when you reconnect. If this is urgent, call 911.';
        actions.push({ label: 'Book a visit', screen: 'wellness', args: { tab: 'telehealth' } });
      }
    } else if (intent === 'account') {
      text = `From your phone: we have ${p.address ?? p.home_city}, ${p.email ?? 'no email'} and ${p.phone ?? 'no phone number'} on your account. You can write up a change offline and it's applied when you reconnect.`;
      actions.push({ label: 'Update my details', screen: 'support' });
    } else if (intent === 'handoff') {
      text = `A licensed agent needs a connection. I can queue the request now and they'll reach you when you're back online, or call ${snap.catalog?.company.support_phone ?? 'customer care'} (${snap.catalog?.company.support_hours ?? 'every day'}).`;
      actions.push({ label: 'Request a licensed agent', screen: 'support', args: { tab: 'agent' } });
    }
  }
  if (!text && faq) text = faq.a;
  if (!text && ctx?.kb_playbook?.[0]) text = ctx.kb_playbook[0].answer ?? ctx.kb_playbook[0].content;
  if (!text) {
    text = "You're offline right now, so I can only answer from what's saved on your phone. Ask me again when you're connected - or open For You, which works offline.";
  }
  return {
    text,
    intent,
    area,
    actions,
    offline: true,
    context: { status: ctx || faq ? 'device' : 'none', latency_ms: 0 },
    sources: faq && text === faq.a ? [{ title: `${members ? 'Member Care Guide' : 'Help Center'} (on device)`, snippet: faq.q, kind: 'couchbase-lite' }] : [],
  };
}
