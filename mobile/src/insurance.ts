/**
 * Small pieces of the insurer's rules the screens need without a connection.
 * They mirror backend/app/actions.py and catalog.py; the server recomputes
 * every figure when the request is processed.
 */
import type { OnDemandCoverage, OnDemandProduct, Policy, Profile } from './types';

export const todayOf = (p: Profile | null | undefined, feedToday?: string) => (feedToday ?? p?.export_date ?? new Date().toISOString()).slice(0, 10);

export const activePolicies = (p: Profile, ...lines: string[]) =>
  (p.policies ?? []).filter((x) => x.status === 'active' && (!lines.length || lines.includes(x.line)));

export const amountDue = (pol: Policy) => Math.round(((pol.billing.balance_due_usd || 0) + (pol.billing.late_fee_usd || 0)) * 100) / 100;

export const vehicleName = (v: { year: number; make: string; model: string }) => `${v.year} ${v.make} ${v.model}`;

/** What a policy covers, in a few words: the car, the address, the pets, the plan. */
export function policySubject(pol: Policy): string {
  if (pol.vehicles?.length) return pol.vehicles.map(vehicleName).join(' · ');
  if (pol.property) return pol.property.address;
  if (pol.pets?.length) return pol.pets.map((x) => x.name).join(' & ');
  return pol.id_card?.plan ?? pol.product;
}

export const activeOnDemand = (p: Profile, today: string, roadsideOnly = false): OnDemandCoverage[] =>
  (p.on_demand?.coverages ?? []).filter((c) => c.start <= today && today <= c.end && (!roadsideOnly || c.roadside));

export const ROADSIDE_CALLS_PER_TERM = 4;

/** How this person's next roadside call is covered. */
export function roadsidePlan(p: Profile, today: string, paygUsd: number): { plan: 'included' | 'on-demand' | 'pay-per-use'; callsLeft: number; costUsd: number } {
  if (activePolicies(p, 'auto').some((x) => x.roadside)) {
    const left = Math.max(0, ROADSIDE_CALLS_PER_TERM - (p.roadside?.uses_this_term ?? 0));
    if (left) return { plan: 'included', callsLeft: left, costUsd: 0 };
  }
  if (activeOnDemand(p, today, true).length) return { plan: 'on-demand', callsLeft: 0, costUsd: 0 };
  return { plan: 'pay-per-use', callsLeft: 0, costUsd: paygUsd };
}

export function onDemandQuote(prod: OnDemandProduct, days: number, tripCostUsd = 0): number {
  let price = prod.price_per_day * Math.max(1, days);
  if (prod.pct_of_trip_cost && tripCostUsd) price += (tripCostUsd * prod.pct_of_trip_cost) / 100;
  return Math.round(Math.max(prod.min_usd, price) * 100) / 100;
}

/** Renewal discount earned by a DriveWell score (0-100). */
export function driveDiscountPct(score: number | null | undefined): number {
  const s = Math.floor(score ?? 0);
  return s >= 95 ? 25 : s >= 90 ? 20 : s >= 85 ? 15 : s >= 78 ? 10 : s >= 70 ? 5 : 0;
}

export const PAY_IN_FULL_DISCOUNT_PCT = 6;
export const LINE_ICON = { auto: 'car', home: 'home', renters: 'business', health: 'medkit', pet: 'paw' } as const;
