/**
 * Offline Harborline: answers from what Couchbase Lite already holds.
 *
 *  1. this person's earlier answers (`chat` doc `answers`, keyed by normalized question)
 *  2. the Help Center FAQ synced in `catalog::v1` - and, on a team member's
 *     phone only, the Team Handbook FAQ in `handbook::v1`
 *  3. the person's own documents: profile (orders, cart, onboarding, benefits),
 *     feed cards and the context cache the server assembled
 *
 * Mirrors backend/app/assistant.py's intent keywords so the same question
 * lands on the same cached context offline as online. The audience gate
 * holds offline by construction: a customer's phone has no handbook document.
 */
import type { Snapshot } from '../../db/localDb';
import type { Area, ChatMessage, Cta, Faq } from '../../types';

const KEYWORDS: Record<string, string[]> = {
  service_recovery: ['damaged', 'defective', 'never arrived', 'missing', 'disappointed', 'upset', 'terrible', 'unacceptable', 'wrong item', 'scratched', 'faulty', 'broke'],
  return: ['return', 'refund', 'exchange', 'send back', 'swap', 'money back'],
  order: ['order', 'track', 'tracking', 'where is my', "where's my", 'delivery', 'deliver', 'shipped', 'shipping', 'arrive', 'package', 'reschedule', 'assembly'],
  cart: ['cart', 'checkout', 'check out', 'basket', 'promo code', 'offer code', 'coupon'],
  onboarding: ['onboarding', 'paperwork', 'i-9', 'i9', 'w-4', 'w4', 'direct deposit', 'handbook', 'new hire', 'checklist', 'code of conduct', 'security training', 'forms'],
  it: ['password', 'vpn', 'laptop', 'locked out', 'ticket', 'software', 'install', 'access to', 'wifi', 'wi-fi', 'printer', 'outlook', 'mfa', 'help desk', 'sso', 'log in', 'login', 'sign in'],
  hr: ['benefits', 'medical', 'dental', 'vision', '401k', '401(k)', 'pto', 'time off', 'vacation', 'day off', 'days off', 'payday', 'paycheck', 'get paid', 'parental', 'insurance', 'hsa', 'enroll', 'employee discount'],
  product: ['recommend', 'looking for', 'suggest', 'desk', 'chair', 'monitor', 'headset', 'webcam', 'keyboard', 'tablet', 'compare', 'best', 'standing', 'warranty'],
  sales: ['consultation', 'consult', 'quote', 'office', 'workspace', 'seats', 'bulk', 'volume', 'for business', 'appointment', 'specialist', 'our team', 'per seat'],
  account: ['account', 'points', 'rewards', 'loyalty', 'tier', 'store credit', 'member'],
};
const AREA: Record<string, Area> = {
  general: 'support', account: 'support', service_recovery: 'support', order: 'commerce', return: 'commerce', cart: 'commerce',
  product: 'sales', sales: 'sales', it: 'workplace', hr: 'workplace', onboarding: 'workplace',
};
const EMPLOYEE_INTENTS = ['it', 'hr', 'onboarding'];

export function classify(q: string, audience = 'customer'): string {
  const m = q.toLowerCase();
  let best = 'general';
  let score = 0;
  for (const [intent, kws] of Object.entries(KEYWORDS)) {
    const s = kws.filter((k) => m.includes(k)).length * (intent === 'service_recovery' ? 2 : 1);
    if (s > score) {
      best = intent;
      score = s;
    }
  }
  if (audience === 'employee' && best === 'service_recovery') best = 'it';
  return best;
}

export const normalize = (q: string) => q.toLowerCase().replace(/[^a-z0-9 ]/g, '').trim().slice(0, 120);

const nice = (iso?: string | null) => {
  if (!iso) return '';
  const [y, mo, d] = iso.slice(0, 10).split('-').map(Number);
  return new Date(y, mo - 1, d).toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
};

function bestFaq(m: string, pool: Faq[]): Faq | undefined {
  return pool
    .map((f) => ({ f, s: f.keywords.filter((k) => m.includes(k)).reduce((n, k) => n + 1 + (k.split(' ').length - 1), 0) }))
    .filter((x) => x.s > 0)
    .sort((a, b) => b.s - a.s)[0]?.f;
}

export function answerOffline(q: string, snap: Snapshot): Omit<ChatMessage, 'id' | 'at' | 'role'> {
  const p = snap.profile;
  const audience = p?.audience ?? 'customer';
  const intent = classify(q, audience);
  const area = AREA[intent];
  const prior = snap.chat?.answers?.[normalize(q)];
  if (prior) {
    return { text: prior.reply, intent, area: prior.area ?? area, offline: true, context: { status: 'device', latency_ms: 0 } };
  }
  const m = q.toLowerCase();
  if (EMPLOYEE_INTENTS.includes(intent) && audience !== 'employee') {
    // No handbook on this phone - there is nothing to answer from, by design.
    return {
      text: "That one's for the Harborline team workspace - IT, benefits and onboarding answers are only available to signed-in team members.",
      intent, area, offline: true, restricted: true, context: { status: 'none', latency_ms: 0 },
    };
  }
  const workplace = EMPLOYEE_INTENTS.includes(intent);
  const pool = [...(workplace ? snap.handbook?.faq ?? [] : []), ...(snap.catalog?.faq ?? []), ...(workplace ? [] : snap.handbook?.faq ?? [])];
  const faq = bestFaq(m, pool);
  const ctx = snap.contexts[intent];
  const actions: Cta[] = [];
  let text: string | null = null;
  const personal = /\b(i|i'm|me|my|mine|we|our|us)\b/i.test(q) && !/^\s*(how (do|can) (i|we)|what (do|should) (i|we)|where (do|can) (i|we)|when (do|can) (i|we))\b/i.test(q);

  if (p && personal) {
    if (intent === 'order' && p.orders?.length) {
      const o = p.orders.find((x) => ['processing', 'shipped', 'out_for_delivery'].includes(x.status)) ?? p.orders[0];
      const open = o.status !== 'delivered' && o.status !== 'cancelled';
      text = open
        ? `From your phone: ${o.items.map((i) => i.name).join(' and ')} (order ${o.order_id}) is ${o.status.replace(/_/g, ' ')} with ${o.carrier}, arriving ${nice(o.eta)}${o.delivery_window ? `, ${o.delivery_window}` : ''}. Live tracking updates when you're back online.`
        : `Order ${o.order_id} was ${o.status}${o.delivered_at ? ` on ${nice(o.delivered_at)}` : ''}.`;
      actions.push({ label: `Open ${o.order_id}`, screen: 'order', args: { order_id: o.order_id } });
    } else if (intent === 'return' || intent === 'service_recovery') {
      const opts = snap.feed?.cards.find((c) => c.kind === 'return')?.options ?? [];
      if (opts.length) {
        text = `You're offline, but your return options are on this device: ${opts.slice(0, 3).map((o) => `${o.name} (${o.days_left} days left)`).join('; ')}. Start one now and I'll send it the moment you're back online.`;
        actions.push({ label: 'Start a return or exchange', screen: 'return' });
      }
    } else if (intent === 'cart' && p.cart?.items?.length) {
      const c = p.cart;
      text = `Your cart is saved on this device: ${c.items.map((i) => i.name).join(' and ')} ($${c.subtotal_usd})${c.offer ? ` - code ${c.offer.code} takes ${c.offer.pct_off}% off until ${nice(c.offer.expires)}` : ''}. Check out now and it's placed as soon as you reconnect.`;
      actions.push({ label: 'Check out', tool: 'checkout_cart', args: { apply_offer: true } });
    } else if (intent === 'sales' || (intent === 'product' && audience === 'lead')) {
      const card = snap.feed?.cards.find((c) => c.kind === 'consult');
      if (p.consultation) text = `You're booked with ${p.consultation.rep} on ${nice(p.consultation.date)} at ${p.consultation.time}.`;
      else if (card?.slots?.length) {
        text = 'You can pick a consultation time offline - open slots are saved on this device, and your booking is sent when you reconnect.';
        actions.push({ label: 'Pick a time', screen: 'consult' });
      }
    } else if (intent === 'account' && p.loyalty) {
      text = `You're a ${p.loyalty.tier} ${p.loyalty.program} member with ${p.loyalty.points.toLocaleString('en-US')} points.`;
    } else if (intent === 'onboarding' && p.onboarding) {
      const pend = p.onboarding.tasks.filter((t) => t.status !== 'complete').sort((a, b) => (a.due_date < b.due_date ? -1 : 1));
      text = pend.length
        ? `From your phone: ${pend.length} onboarding task${pend.length > 1 ? 's' : ''} left. Next is ${pend[0].title}, due ${nice(pend[0].due_date)}. You can sign offline - it syncs when you're connected.`
        : 'Your onboarding is complete.';
      if (pend.length) actions.push({ label: 'Open my checklist', screen: 'onboarding' });
    } else if (intent === 'hr' && p.hr) {
      if (/(time off|pto|vacation|day off|days off)/.test(m)) {
        text = `You have ${p.hr.pto.balance_days} days of paid time off. Pick your dates now; the request goes to ${p.employment?.manager} when you reconnect.`;
        actions.push({ label: 'Request time off', screen: 'timeoff' });
      } else if (/(paid|payday|paycheck)/.test(m)) {
        text = `Your next pay date is ${nice(p.hr.pay.next_pay_date)}.`;
      } else if (!p.hr.benefits.enrolled) {
        text = `You haven't enrolled in benefits yet - your window closes ${nice(p.hr.benefits.enrollment_deadline)}. The plans are saved on this device.`;
        actions.push({ label: 'Compare plans & enroll', screen: 'benefits' });
      }
    } else if (intent === 'it' && p.it) {
      const t = p.it.open_tickets;
      if (/(password|locked|sign in|log in|login)/.test(m)) {
        text = `Your password expires in ${p.it.password_expires_in_days} days. A reset needs a connection, but I can queue it now and it runs when you're back online.`;
        actions.push({ label: 'Reset my password', tool: 'reset_password', args: { system: 'sso' } });
      } else {
        text = t.length
          ? `Your open tickets: ${t.map((x) => `${x.ticket_id} - ${x.summary} (${x.status.replace(/_/g, ' ')})`).join('; ')}. You can open another offline; it's sent when you reconnect.`
          : "You're offline, but you can write up a ticket now - it's sent to the help desk when you reconnect.";
        actions.push({ label: 'Open a help desk ticket', screen: 'ticket', args: { summary: q.slice(0, 160) } });
      }
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
    sources: faq && text === faq.a ? [{ title: `${workplace ? 'Team Handbook' : 'Help Center'} (on device)`, snippet: faq.q, kind: 'couchbase-lite' }] : [],
  };
}
