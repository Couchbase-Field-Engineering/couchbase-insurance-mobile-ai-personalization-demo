/** Document shapes replicated from Couchbase (scope `ins`) into Couchbase Lite. */

export type Audience = 'policyholder' | 'member' | 'ondemand';
/** The eight things the app does. */
export type Area = 'documents' | 'claims' | 'roadside' | 'billing' | 'telematics' | 'support' | 'wellness' | 'coverage';
export type Line = 'auto' | 'home' | 'renters' | 'health' | 'pet';

export type PolicyDocument = { doc_id: string; type: string; title: string; issued: string; status: string; delivery?: string; pages?: number; recipient?: string };
export type Vehicle = { vehicle_id: string; year: number; make: string; model: string; vin_last6: string; plate: string };
export type Pet = { pet_id: string; name: string; species: string; breed: string; age: number };

export type Billing = {
  plan: 'monthly' | 'pay_in_full';
  installment_usd: number;
  next_due: string | null;
  balance_due_usd: number;
  late_fee_usd: number;
  past_due: boolean;
  autopay: boolean;
  autopay_day: number | null;
  method: { type: string; last4: string };
};

export type Renewal = { status: 'offered' | 'renewed' | string; offer_premium_usd: number; change_pct?: number; renews_on: string; discounts?: string[]; pay_plan?: string };

export type Policy = {
  policy_id: string;
  line: Line;
  product: string;
  status: string;
  effective: string;
  expires: string;
  premium_usd: number;
  deductible_usd: number | null;
  coverages: { name: string; limit: string }[];
  billing: Billing;
  documents: PolicyDocument[];
  renewal: Renewal | null;
  roadside?: boolean;
  vehicles?: Vehicle[];
  property?: { address: string; type: string };
  plan_id?: string;
  pets?: Pet[];
  routine_care?: boolean;
  usage?: { deductible_met_usd: number; paid_usd: number };
  id_card?: { number: string; insured: string; valid_from: string; valid_to: string; naic?: string; group?: string; plan?: string; rx_bin?: string };
};

export type Claim = {
  claim_id: string;
  policy_id: string;
  line: Line;
  loss_type: string;
  loss_date: string;
  filed_at: string;
  status: string;
  description: string;
  location?: string;
  adjuster?: string;
  deductible_usd?: number;
  estimate_usd?: number | null;
  payout_usd?: number | null;
  drivable?: boolean;
  evidence: { kind: string; count: number; at: string; note?: string }[];
  events: { at: string; text: string }[];
};

export type Dispatch = {
  dispatch_id: string; service: string; service_name: string; status: string; provider: string; eta_minutes: number;
  location: { label: string; lat?: number; lon?: number }; vehicle?: string; requested_at: string; cost_usd?: number;
};

export type Trip = { trip_id: string; date: string; miles: number; minutes: number; hard_brakes: number; speeding: number; night: boolean; phone_use: number; score: number };

export type Telematics = {
  enrolled: boolean;
  program?: 'safe-driver' | 'pay-per-mile';
  vehicle_id?: string;
  device?: string;
  enrolled_at?: string;
  score?: number | null;
  factors?: Record<string, number>;
  miles_month?: number;
  miles_term?: number;
  trips?: Trip[];
  redeemed?: boolean;
};

export type OnDemandCoverage = {
  coverage_id: string; product: string; name: string; start: string; end: string; days: number; price_usd: number; status: string;
  covers: string[]; vehicle?: string | null; destination?: string | null; roadside?: boolean;
  certificate?: { doc_id: string; type: string; title: string; issued: string; status: string };
};

export type TripPlan = { destination: string; depart: string; return: string; trip_cost_usd?: number };
export type DrivePlan = { kind: 'borrowed' | 'rental'; vehicle: string; start: string; days: number };
export type Plans = { trip?: TripPlan; drive?: DrivePlan };

export type VetBill = {
  bill_id: string; pet_id: string; pet_name: string; amount_usd: number; clinic: string; visit_date: string; reason: string; submitted_at: string;
  status: string; eligible_usd?: number; deductible_applied_usd?: number; reimbursement_usd?: number; routine?: boolean; pct?: number; pays_by?: string | null;
};

export type Wellness = {
  deductible?: { individual_usd: number; met_usd: number; oop_max_usd: number; oop_met_usd: number; resets: string };
  telehealth?: { visits_used: number; upcoming: { date: string; time: string; type_name: string; provider: string; reason?: string } | null };
  wearable?: { linked: boolean; device?: string; points?: number; steps_7d_avg?: number; reward_usd?: number; linked_at?: string };
  vet_bills?: VetBill[];
};

export type Profile = {
  type: 'profile';
  user_id: string;
  audience: Audience;
  group_code: string;
  account_id: string;
  export_date: string;
  rev: number;
  first_name: string;
  last_name: string;
  email: string | null;
  phone?: string | null;
  address?: string | null;
  home_city: string;
  region: string;
  preferences: { communication_channel: string; paperless: boolean; language: string };
  segments?: { id: string; name: string; status?: string }[];
  ml_scores: Record<string, number | string | string[] | null> & { model_version: string; segment: string; next_best_action: string };
  policies: Policy[];
  claims: Claim[];
  payments: { payment_id: string; policy_id: string; amount_usd: number; method: string; at: string; for?: string }[];
  roadside: { uses_this_term: number; dispatches: Dispatch[]; last_location?: { label: string; lat: number; lon: number } };
  emergencies?: { sos_id: string; kind: string; status: string; at: string; callback_minutes?: number }[];
  telematics: Telematics;
  on_demand: { coverages: OnDemandCoverage[]; plans: Plans };
  support?: { requests: { request_id: string; kind?: string; topic?: string; channel?: string; status: string; agent?: string; wait_minutes?: number; details?: string }[] };
  history?: { customer_since: string; claims_count: number };
  /** Health and pet members only. */
  wellness?: Wellness;
};

export type Cta = { label: string; screen?: string; tool?: string; ask?: string; args?: Record<string, unknown> };

export type SlotDay = { date: string; slots: { time: string; open: number }[] };

export type OnDemandProduct = {
  id: string; name: string; unit: string; price_per_day: number; pct_of_trip_cost?: number; min_usd: number; max_days: number;
  needs: string[]; roadside: boolean; blurb: string; covers: string[];
  quote?: { product: string; name: string; days: number; price_usd: number; covers: string[] };
};

export type FeedCard = {
  card_id: string;
  kind: 'payment' | 'renewal' | 'claim' | 'idcard' | 'drive' | 'roadside' | 'telehealth' | 'deductible' | 'vetbill' | 'wearable' | 'coverage';
  palette: string;
  area: Area;
  title: string;
  subtitle: string;
  reason: string;
  badge: string;
  score: number;
  rank: number;
  cta: Cta;
  slots?: SlotDay[];                       // telehealth card: open appointments, so booking works offline
  types?: { id: string; name: string }[];
  products?: OnDemandProduct[];            // coverage cards: every product with a quote for this person's plans
  plans?: Plans;
};

export type FeedDoc = {
  type: 'feed';
  audience: Audience;
  cards: FeedCard[];
  model_version: string;
  segment: string;
  export_date: string;
  today?: string;
  generated_at: string;
};

export type ActivityItem = {
  item_id: string;
  kind: string;
  title: string;
  status: string;
  date?: string;
  time?: string;
  charge_usd?: number | null;
  amount_usd?: number;
  refund_usd?: number | null;
  created_at: string;
};

export type RequestStatus = 'pending' | 'processing' | 'awaiting_approval' | 'confirmed' | 'accepted' | 'submitted' | 'failed';

export type ActionRequest = {
  _id: string;
  type: 'request';
  user_id: string;
  tool: string;
  args: Record<string, unknown>;
  title: string;
  status: RequestStatus;
  created_at: string;
  summary?: string;
  charge_usd?: number;
  governed?: boolean;
  trace_id?: string | null;
  /** Couchbase Labs Agent Operations Manager agent identity that ran it: the assistant, or the specialist that owns the use case. */
  agent?: string;
  memories_recalled?: number;
  remembered?: boolean;
  approval_id?: string | null;
  completed_at?: string | null;
  _local?: boolean; // created on this device, not yet acknowledged by the server
};

export type ChatMessage = {
  id: string;
  role: 'user' | 'assistant';
  text: string;
  at: string;
  intent?: string;
  area?: Area;
  actions?: Cta[];
  restricted?: boolean;
  context?: {
    status: string | null; latency_ms: number; kb_mode?: string; build_ms?: number; rag_app?: string; knowledge?: string; source?: string;
    // the system-of-record round trip (policy administration, claims, billing) made while building this context
    sor?: { system: string; label: string; mode: string; latency_ms: number; segments: string[] } | null;
  };
  llm?: { status: string; namespace?: string | null; similarity?: number | null; latency_ms?: number | null; stub?: boolean; composed_locally?: boolean };
  sources?: { title: string; snippet: string; kind: string }[];
  offline?: boolean;
  pending?: boolean;
};

export type ChatDoc = { type: 'chat'; messages: ChatMessage[]; answers: Record<string, { reply: string; intent: string; area?: Area; at: string }> };

export type ContextDoc = {
  type: 'context_cache';
  intent: string;
  area: Area;
  personal: boolean;
  export_date: string;
  built_at: string;
  build_ms: number;
  kb_mode: string;
  kb_profile: { title: string; content: string }[];
  kb_playbook: { title: string; content: string; answer?: string }[];
  facts: { tool?: string; data?: any };
};

export type Faq = { q: string; a: string; keywords: string[]; section?: string; intent?: string };

/** `catalog::v1` - on the `catalog` channel, so every signed-in phone has it. */
export type Catalog = {
  type: 'catalog';
  export_date: string;
  company: { name: string; support_phone: string; claims_phone: string; roadside_phone: string; support_hours: string; wellness_brand: string; telematics_program: string };
  lines: Record<string, { name: string; product: string; icon: string; term_months: number }>;
  doc_types: { id: string; name: string; lines: string[]; instant: boolean }[];
  doc_delivery: string[];
  loss_types: Record<string, { id: string; name: string }[]>;
  claim_steps: string[];
  claim_step_label: Record<string, string>;
  evidence_kinds: string[];
  roadside_services: { id: string; name: string; eta_min: number; detail: string }[];
  roadside_payg_usd: number;
  sos_kinds: { id: string; name: string; detail: string }[];
  pay_plans: Record<string, string>;
  late_fee_usd: number;
  telematics_programs: Record<string, { name: string; blurb: string; enroll_discount_pct?: number; max_discount_pct?: number; base_usd_month?: number; cents_per_mile?: number }>;
  policy_changes: { id: string; name: string; lines: string[]; approval: boolean }[];
  agent_topics: string[];
  agent_channels: string[];
  on_demand: OnDemandProduct[];
  destinations: string[];
  faq: Faq[];
};

/** `wellness::v1` - on the `members` channel: only a health or pet member's phone ever receives it. */
export type MemberGuide = {
  type: 'member_guide';
  export_date: string;
  health_plans: { id: string; name: string; deductible: number; oop_max: number; telehealth_copay: number; blurb: string }[];
  pet_plans: { id: string; name: string; reimbursement_pct: number; annual_deductible: number; annual_limit: number; blurb: string }[];
  telehealth_types: { id: string; name: string }[];
  telehealth_times: string[];
  vet_visit_reasons: string[];
  wearables: string[];
  step_goal: number;
  points_per_goal_day: number;
  points_per_dollar: number;
  faq: Faq[];
};

export type SyncState = {
  engine: 'couchbase-lite' | 'preview';
  status: 'connecting' | 'connected' | 'idle' | 'busy' | 'offline' | 'paused' | 'error' | 'stopped';
  lastSyncAt: number | null;
  pendingPush: number;
  detail?: string;
  endpoint?: string;
};
