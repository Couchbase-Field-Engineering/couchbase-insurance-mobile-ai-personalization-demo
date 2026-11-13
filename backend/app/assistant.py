"""The Harborline Assistant - the agent behind the app's Chat tab. One
assistant for everything an insurance customer asks: ID cards and documents,
claims, roadside and emergencies, payments and renewals, telematics, account
changes, health and pet benefits, and on-demand cover.

One turn:

1. **Classify** the question into an intent and its *area* (documents,
   claims, roadside, billing, telematics, support, wellness, coverage), and
   decide whether it is *personal* (needs this person's data) or a *shared*
   question anyone could ask ("how does roadside assistance work?").
2. **Audience gate.** Health and wellness intents are for members of a
   health or pet plan. Anyone else who asks one gets a polite refusal and
   nothing is retrieved - the Member Care Guide is never in their context.
3. **Shared questions -> an AOM RAG Application.** One call to
   `/v1/agent/rag/<app>/query`: the general app (scoped to today's Help
   Center) or, for a member's wellness question, the wellness app (scoped
   to today's Member Care Guide). AOM runs retrieval behind its Context
   Cache and generation behind its LLM Cache, and counts the query on its
   RAG Applications page.
4. **Personal questions -> Context Caching.** Look the context up in AOM's
   Context Cache (`/v1/context/get`, namespace `rag:<app>:user-context`),
   then in the Couchbase `ctx::<user>::<intent>` document. On a miss,
   assemble it: the person's current record from their system of record
   (policy administration, member platform or on-demand platform - segments
   and scores), AOM Knowledge Base retrieval scoped to this person's profile
   document and to the right knowledge document, plus live facts from the
   governed MCP tools (policies, claims, billing, roadside status, driving
   summary, wellness summary, on-demand quotes). It is stored in AOM
   (`/v1/context/set`, with the real build time) and in Couchbase, keyed by
   the export date and the profile revision, so the next nightly export or
   anything the person does invalidates it. The Couchbase copy carries the
   person's channel, so Sync Gateway puts it on the phone too - which is
   what lets the app answer offline.
5. **Memory** - recall what this person told the assistant before, and what
   the specialist agents remembered (AOM agent memory), live every turn.
6. **LLM Caching** - complete through AOM `/v1/llm/complete` in the
   `rag:<app>:personal` namespace.
7. Suggest one-tap actions; the app turns a tap into an offline-first
   `requests` document that the matching specialist agent runs.
"""
from __future__ import annotations

import logging
import re
import time
import uuid

from . import catalog as C
from . import config, knowledge, metrics, rag_app, sources, tool_gateway
from .aom_client import AOMError, aom, current_trace
from .docs import STATE, chat_id, ctx_id, days_until, money, nice_date, now_iso, profile_id, user_channel
from .rag_app import MEMBER_INTENTS
from .store import store

log = logging.getLogger("insurance.assistant")

INTENTS = ["emergency", "roadside", "claim", "telematics", "billing", "documents", "coverage", "wellness", "account", "handoff", "general"]
AREA = {"emergency": "roadside", "roadside": "roadside", "claim": "claims", "telematics": "telematics", "billing": "billing",
        "documents": "documents", "coverage": "coverage", "wellness": "wellness", "account": "support", "handoff": "support",
        "general": "support"}
# Which intents can be *personal* for each audience. Anything else is answered
# as a shared question from the knowledge document.
_COMMON = {"emergency", "roadside", "claim", "telematics", "billing", "documents", "coverage", "account", "handoff", "general"}
APPLICABLE = {
    "policyholder": _COMMON,
    "member": _COMMON | {"wellness"},
    "ondemand": _COMMON,
}
# Context-cache keys: personal context per intent, plus a shared context per
# intent for generic questions (no personal data in it).
CONTEXT_KEYS = INTENTS + [f"playbook_{i}" for i in INTENTS]

# Order matters: on a tie the earlier intent wins. A keyword matches at the
# start of a word ("pet" doesn't match "competitor", "cat" doesn't match "vacation").
KEYWORDS = {
    "emergency": ["sos", "emergency", "been in an accident", "after an accident", "car accident", "just had an accident", "had a crash", "crashed", "been hit", "hit me",
                  "rear-ended me", "injured", "hurt", "ambulance", "stranded"],
    "roadside": ["tow", "flat tire", "flat tyre", "jump start", "jump-start", "jumpstart", "dead battery", "battery died", "battery is dead",
                 "locked out", "locked my keys", "lockout", "out of gas", "out of fuel", "ran out of", "broke down", "broken down",
                 "breakdown", "won't start", "wont start", "roadside", "stuck on the"],
    "wellness": ["telehealth", "doctor", "video visit", "virtual visit", "nurse", "therapist", "dermatolog", "prescription", "health deductible",
                 "out-of-pocket", "out of pocket", "copay", "vet", "pet", "dog", "cat", "wearable", "apple watch", "fitbit", "garmin", "oura",
                 "steps", "fitness tracker", "wellness", "health plan", "hsa", "sick", "symptom"],
    "claim": ["claim", "file a claim", "accident", "damage", "adjuster", "estimate", "repair shop", "body shop", "windshield", "hail", "stolen", "break-in",
              "broken into", "burst pipe", "leak", "deductible", "payout", "dent", "scratch", "photos of", "rear-ended"],
    "telematics": ["drivewell", "driving score", "my score", "telematics", "safe driver", "safe-driver", "pay per mile", "pay-per-mile",
                   "mileage", "miles", "hard brak", "speeding", "last trip", "recent trips", "my trips", "record a trip", "usage-based",
                   "usage based", "driving discount", "my driving", "beacon"],
    "billing": ["pay", "bill", "premium", "autopay", "auto-pay", "auto pay", "due", "late fee", "past due", "overdue", "renew", "expire",
                "expiring", "went up", "price increase", "refund", "charge", "owe", "balance", "installment"],
    "documents": ["id card", "insurance card", "proof of insurance", "my card", "document", "declarations", "dec page", "policy booklet",
                  "certificate", "lender", "landlord", "mortgage company", "evidence of insurance", "copy of my policy", "pdf", "wallet",
                  "policy number", "letter"],
    "coverage": ["on-demand", "on demand", "short-term", "short term", "temporary", "borrow", "rental car", "renting a car", "rent a car",
                 "travel", "trip protection", "my trip", "trip to", "vacation", "holiday", "flight", "flying", "for a day", "for the weekend",
                 "this weekend", "one day", "few days", "event", "activate", "quote", "what cover", "my cover", "cover me", "cover for my"],
    "account": ["my address", "moved", "moving", "new address", "my email", "my phone", "phone number", "contact details", "my details",
                "update my", "change my", "change my deductible", "raise my deductible", "lower my deductible", "add a driver", "remove a driver",
                "add my", "new car", "add a vehicle", "raise my", "liability limit", "coverage change", "am i covered", "my coverage",
                "my policy", "my policies", "name is wrong", "misspelled"],
    "handoff": ["agent", "human", "real person", "representative", "speak to", "talk to", "call me", "someone call", "live chat", "a person",
                "supervisor"],
}
_KW_RE = {i: [re.compile(r"(?<![a-z0-9])" + re.escape(k)) for k in kws] for i, kws in KEYWORDS.items()}
PERSONAL_RE = re.compile(r"\b(i|i'm|im|i've|me|my|mine|we|we're|our|us)\b", re.I)
# "How do I file a claim?" has a pronoun but asks how something works:
# everyone gets the same answer, so it stays on the shared (cacheable) path.
PROCEDURAL_RE = re.compile(r"^\s*(how (do|can|would|should) (i|we)\b|how (much|many|long|often)\b.*\bdo (i|we) get\b|what (do|should) (i|we) (need|do)\b"
                           r"|what \w+ do (i|we) need\b|where (do|can) (i|we)\b|when (do|can|should) (i|we)\b|why did (i|we)\b|do (i|we) need\b)", re.I)
QUESTION_RE = re.compile(r"\s*(how|what|is|are|can|do|does|who|when|where|which|why)\b", re.I)
# Always about this person, however it is phrased.
PERSONAL_INTENTS: set[str] = set()
# A bare request ("need a tow", "send help, there's been a crash", "talk to an agent") is personal; a question
# about how it works is not.
ACTION_INTENTS = {"emergency", "roadside", "handoff"}

# Canonical retrieval query per intent: the cached context is per intent, so
# it is retrieved with a stable query rather than the wording of whichever
# question happened to miss the cache first.
INTENT_QUERY = {
    "emergency": "accident emergency SOS what to do roadside tow",
    "roadside": "roadside assistance tow flat tire jump-start calls per term",
    "claim": "claim status adjuster estimate deductible photos",
    "telematics": "DriveWell telematics driving score discount pay-per-mile",
    "billing": "premium payment due date AutoPay late fee renewal offer",
    "documents": "insurance ID card proof of insurance policy documents declarations",
    "coverage": "on-demand short-term cover borrowed car rental car trip protection",
    "wellness": "telehealth deductible vet bill reimbursement wearable rewards",
    "account": "update address contact details change coverage policy",
    "handoff": "talk to a licensed agent customer care",
    "general": "what Harborline insures offline app support",
}
FACT_TOOL = {"emergency": "get_roadside_status", "roadside": "get_roadside_status", "claim": "get_claims", "telematics": "get_driving_summary",
             "billing": "get_billing", "documents": "get_policies", "coverage": "get_coverage_options", "wellness": "get_wellness_summary",
             "account": "get_customer_context", "handoff": "get_customer_context"}

PERSONA = ("You are the Harborline Assistant in the Harborline insurance app. Be warm, concise (under 120 words) and specific. "
           "Use only the facts in CONTEXT. Never invent premiums, coverage limits, deductibles, dates, claim outcomes or "
           "reference numbers, and never give medical or legal advice. Never say an action is done - the person confirms "
           "actions with the buttons shown under your reply.")
RESTRICTED = ("Telehealth, deductible tracking, vet bills and wearable rewards are part of Harborline Health and Pet plans, so "
              "those answers are only available to members of those plans. I can help with your ID cards, claims, roadside, "
              "payments or on-demand cover - or bring in a licensed agent to talk about adding a plan.")


def _scores(m: str) -> dict[str, int]:
    return {i: sum(1 for rx in rxs if rx.search(m)) for i, rxs in _KW_RE.items()}


def classify(message: str, audience: str = "policyholder") -> tuple[str, bool]:
    m = message.lower()
    scores = _scores(m)
    scores["emergency"] *= 2
    intent = max(scores, key=scores.get)
    if scores[intent] == 0:
        intent = "general"
    # A member asking about "my deductible" means the health plan's, not a claim's.
    if audience == "member" and intent == "claim" and scores["claim"] == 1 and "deductible" in m:
        intent = "wellness"
    pron = bool(PERSONAL_RE.search(message))
    question = bool(QUESTION_RE.match(m))
    personal = ((pron and not PROCEDURAL_RE.match(m)) or intent in PERSONAL_INTENTS
                or (intent in ACTION_INTENTS and not question))
    if intent == "general" and not personal:
        return "general", False
    # A policy question phrased generically ("what is a deductible?") stays on
    # the shared path even though its intent can be personal.
    if not pron and question and intent not in PERSONAL_INTENTS:
        return intent, False
    return intent, personal


def _norm(q: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", q.lower()).strip()


async def kb_doc_id(key: str) -> str | None:
    doc = await store.get("lookups", f"kbdoc::{key}")
    return doc.get("document_id") if doc else None


# --------------------------------------------------------------------------
# Context cache
# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
# Context cache
# --------------------------------------------------------------------------
async def invalidate_context(user_id: str):
    for key in CONTEXT_KEYS:
        await store.remove("context_cache", ctx_id(user_id, key))


async def _kb(query: str, document_id: str | None, top_k=3) -> tuple[list[dict], str]:
    if not (aom.enabled and document_id):
        return [], "unavailable"
    try:
        res = await aom.knowledge_search(query, top_k=top_k, document_id=document_id)
        return [{"title": r.get("document_title"), "content": r.get("content"), "score": round(r.get("score") or 0, 3),
                 "document_id": r.get("document_id"), "source": "aom-kb"} for r in res.get("results", [])], "aom"
    except AOMError as exc:
        log.warning("KB search failed: %s", exc)
        return [], "error"


_PROFILE_SECTIONS = {
    "emergency": ["Account", "Policies", "Roadside"], "roadside": ["Policies", "Roadside", "On-demand"], "claim": ["Claims", "Policies"],
    "telematics": ["Driving", "Policies"], "billing": ["Billing", "Policies"], "documents": ["Policies", "On-demand"],
    "coverage": ["On-demand", "Policies", "Personalization"], "wellness": ["Wellness", "Policies"], "account": ["Account", "Policies"],
    "handoff": ["Account", "Policies", "Claims"], "general": ["Account", "Policies"],
}


def _local_profile_chunks(profile: dict, intent: str) -> list[dict]:
    md = knowledge.user_profile_markdown(profile)
    want = _PROFILE_SECTIONS[intent]
    out = []
    for s in md.split("\n## "):
        if any(s.startswith(w) for w in want):
            out.append({"title": f"User profile {profile['user_id']}", "content": s[:1200], "score": None,
                        "document_id": None, "source": "local-export"})
    return out


def _faq_score(q: str, f: dict) -> int:
    return sum(1 + k.count(" ") for k in f["keywords"] if re.search(r"(?<![a-z0-9])" + re.escape(k), q))


def _local_playbook_chunks(query: str, audience: str, wellness: bool | None = None) -> list[dict]:
    """Keyword match over the bundled entries. Member Care Guide entries are
    only ever considered for a health or pet plan member."""
    q = query.lower()
    pool = knowledge.FAQ if audience == "member" else knowledge.CUSTOMER_FAQ
    if wellness is True:
        pool = knowledge.MEMBER_FAQ if audience == "member" else []
    elif wellness is False:
        pool = knowledge.CUSTOMER_FAQ
    scored = [(s, f) for f in pool if (s := _faq_score(q, f))]
    scored.sort(key=lambda x: -x[0])
    return [{"title": "Member Care Guide" if f["audience"] == "member" else "Help Center", "content": f"{f['q']} {f['a']}",
             "answer": f["a"], "score": None, "document_id": None, "source": "local-playbook"} for _, f in scored[:3]]


async def _facts(user_id: str, intent: str) -> dict:
    tool = FACT_TOOL.get(intent)
    if not tool:
        return {}
    res = await tool_gateway.invoke(tool, {"user_id": user_id})
    data = res.get("data", res)
    return {"tool": tool, "governed": res.get("governed", False), "trace_id": res.get("trace_id"), "data": data}


def _aom_context_key(user_id: str, cache_key: str, profile: dict, personal: bool) -> str:
    """Key in AOM's Context Cache. The export date and (for personal context)
    the profile revision are part of the key, so a new nightly export or any
    action makes the old entry unreachable at once. Shared context holds no
    personal data, so every user of that app shares one entry per intent."""
    if personal:
        return f"{user_id}:{cache_key}:{profile.get('export_date')}:r{profile.get('rev', 0)}"
    return f"{cache_key}:{profile.get('export_date')}"


def _local_valid(doc: dict | None, profile: dict, personal: bool) -> bool:
    return bool(doc and doc.get("export_date") == profile.get("export_date")
                and (not personal or doc.get("profile_rev") == profile.get("rev", 0)))


async def get_context(user_id: str, intent: str, profile: dict, personal: bool = True) -> dict:
    """Context Caching, with AOM's Context Cache in front of the assembly.

    1. AOM `/v1/context/get` in the app's `rag:<app>:user-context` namespace,
       so hit rate and latency avoided show on AOM's Context Cache and RAG
       Applications pages.
    2. On a miss (or with AOM unreachable), the Couchbase `context_cache`
       document, if it was built from today's export and the current profile.
    3. Otherwise assemble: the person's current system-of-record view
       (segments, scores), KB retrieval scoped to this person's profile
       document and the knowledge document, plus live facts from the governed
       MCP tools. The result goes to AOM (`/v1/context/set` with the real
       build time as `source_latency_ms`) and to Couchbase, where the
       person's channel puts it on the phone for offline answers.
    """
    audience = profile["audience"]
    app_key = rag_app.app_for(intent, audience)
    app = rag_app.APPS[app_key]
    namespace = config.context_namespace(app["app_id"])
    cache_key = intent if personal else f"playbook_{intent}"
    key = ctx_id(user_id, cache_key)
    aom_key = _aom_context_key(user_id, cache_key, profile, personal)
    t0 = time.perf_counter()
    aom_status = "off"
    if aom.enabled:
        try:
            res = await aom.context_get(aom_key, namespace)
            aom_status = (res.get("cache") or {}).get("status") or ("hit" if res.get("hit") else "miss")
            value = res.get("value")
            if res.get("hit") and isinstance(value, dict):
                # A shared entry may have been stored by another person's
                # turn: re-home it to this user before it syncs to their phone.
                doc = dict(value, user_id=user_id, channels=[user_channel(user_id)])
                local = await store.get("context_cache", key)
                if not _local_valid(local, profile, personal):
                    # Keep the phone's copy current for offline answers.
                    await store.upsert("context_cache", key, doc, ttl=config.CONTEXT_CACHE_TTL_SECONDS)
                doc["_cache"] = {"status": "hit", "source": "aom", "namespace": namespace,
                                 "latency_ms": round((time.perf_counter() - t0) * 1000, 1)}
                return doc
        except AOMError as exc:
            aom_status = "error"
            log.info("AOM context get failed: %s", exc)

    cached = await store.get("context_cache", key)
    if _local_valid(cached, profile, personal):
        cached["_cache"] = {"status": "hit", "source": "couchbase", "aom": aom_status,
                            "latency_ms": round((time.perf_counter() - t0) * 1000, 1)}
        if aom_status == "miss":
            await _aom_context_set(aom_key, cached, cached.get("build_ms"), namespace)
        return cached

    query = INTENT_QUERY[intent]
    user_doc = await kb_doc_id(user_id) if personal else None
    playbook_doc = await kb_doc_id(app["kb_key"])
    kb_profile, kb_mode = ([], "skipped")
    if personal and intent != "general":
        kb_profile, kb_mode = await _kb(query, user_doc)
        if not kb_profile:
            kb_profile = _local_profile_chunks(profile, intent)
    kb_playbook, pb_mode = await _kb(query, playbook_doc)
    if not kb_playbook:
        kb_playbook = _local_playbook_chunks(query + " " + intent, audience, wellness=app_key == "wellness")
    if kb_mode == "skipped":
        kb_mode = pb_mode
    facts = await _facts(user_id, intent) if personal and intent != "general" else {}
    # The person's *current* record from their system of record: segments and
    # scores as of now, not as of last night's export.
    sor = await sources.profile_view(user_id, profile) if personal else None
    build_ms = round((time.perf_counter() - t0) * 1000, 1)
    doc = {
        "type": "context_cache", "user_id": user_id, "audience": audience, "intent": intent, "area": AREA[intent],
        "personal": personal, "query": query, "rag_app": app["app_id"], "knowledge": app["kb_key"],
        "export_date": profile.get("export_date"), "profile_rev": profile.get("rev", 0),
        "built_at": now_iso(), "build_ms": build_ms, "kb_mode": kb_mode,
        "kb_profile": kb_profile, "kb_playbook": kb_playbook, "facts": facts, "sor": sor,
        "user_document_id": user_doc, "playbook_document_id": playbook_doc,
        "aom_key": aom_key, "channels": [user_channel(user_id)],
    }
    await store.upsert("context_cache", key, doc, ttl=config.CONTEXT_CACHE_TTL_SECONDS)
    await _aom_context_set(aom_key, doc, build_ms, namespace)
    doc = dict(doc)
    doc["_cache"] = {"status": "miss", "source": "built", "aom": aom_status, "latency_ms": build_ms}
    return doc


async def _aom_context_set(aom_key: str, doc: dict, build_ms, namespace: str) -> None:
    if not aom.enabled:
        return
    value = {k: v for k, v in doc.items() if not k.startswith("_")}
    if not value.get("personal"):
        if value.get("kb_profile") or value.get("facts") or value.get("sor"):
            return  # never share personal data across users
        for k in ("user_id", "channels", "user_document_id", "audience"):
            value.pop(k, None)
    try:
        await aom.context_set(aom_key, value, namespace, ttl_seconds=config.CONTEXT_CACHE_TTL_SECONDS,
                              source_latency_ms=int(build_ms or 0))
    except AOMError as exc:
        # 409 = context caching switched off in AOM's policy, 413 = over its size limit.
        log.info("AOM context set skipped: %s", exc)


# --------------------------------------------------------------------------
# Answer composition
# --------------------------------------------------------------------------
def _user_summary(p: dict) -> str:
    pols = [x for x in p.get("policies", []) if x.get("status") == "active"]
    held = ", ".join(f"{x['product']} {x['policy_id']}" for x in pols) or "no annual policy"
    return (f"{p['first_name']} {p['last_name']} ({C.AUDIENCES[p['audience']]}), {p.get('home_city')}. Holds: {held}. "
            f"Customer since {(p.get('history') or {}).get('customer_since', 'recently')}.")


def _facts_text(facts: dict) -> str:
    d = facts.get("data") or {}
    t = facts.get("tool")
    if t == "get_policies":
        rows = [f"{x['product']} {x['policy_id']} ({', '.join(str(v['year']) + ' ' + v['make'] + ' ' + v['model'] for v in x.get('vehicles') or []) or (x.get('property') or {}).get('address') or ', '.join(pt['name'] for pt in x.get('pets') or []) or x['line']}), "
                f"valid {x['effective']} to {x['expires']}; documents: {', '.join(doc['title'] for doc in (x.get('documents') or [])[:5])}"
                for x in d.get("policies", [])]
        od = [f"{c['name']} {c['coverage_id']} {c['start']} to {c['end']}" + (" (active)" if c.get("active") else "") for c in d.get("on_demand", [])]
        return "Policies and ID cards: " + ("; ".join(rows) or "none") + (". On-demand certificates: " + "; ".join(od) if od else "")
    if t == "get_claims":
        rows = [f"{c['claim_id']} on {c['policy_id']} ({c['loss_type']}, {c['loss_date']}): {c['status_label']}, adjuster {c.get('adjuster')}"
                + (f", estimate ${c['estimate_usd']:,} less ${c['deductible_usd']:,} deductible" if c.get("estimate_usd") else "")
                + f", {c['photos']} photos; next: {c['next_step']}" for c in d.get("claims", [])[:4]]
        return "Claims: " + ("; ".join(rows) or "none on file") + ". Can file on: " + (", ".join(f"{x['policy_id']} ({x['line']})" for x in d.get("fileable_policies", [])) or "no policy")
    if t == "get_roadside_status":
        a = d.get("active_dispatch")
        return (f"Roadside: {d.get('plan')}" + (f", {d.get('calls_left')} calls left this term" if d.get("plan") == "included" else f", ${d.get('cost_usd')} per call" if d.get("plan") == "pay-per-use" else "")
                + f"; vehicles: {', '.join(str(v['year']) + ' ' + v['make'] + ' ' + v['model'] for v in d.get('vehicles', [])) or 'none on a policy'}"
                + f"; last known location {(d.get('last_location') or {}).get('label')}"
                + (f"; {a['service_name']} {a['dispatch_id']} on the way with {a['provider']}, about {a['eta_minutes']} minutes" if a else "; nothing dispatched"))
    if t == "get_billing":
        rows = [f"{r['policy_id']} ({r['line']}): ${r['installment_usd']:,.2f} {r['plan'].replace('_', ' ')}, next due {r['next_due']}, amount due ${r['amount_due_usd']:,.2f}"
                + (f" PAST DUE incl. ${r['late_fee_usd']:,.0f} late fee" if r["past_due"] else "") + f", AutoPay {'on' if r['autopay'] else 'off'}"
                + (f"; renewal offer ${r['renewal']['offer_premium_usd']:,.2f} from {r['expires']} ({r['renewal'].get('change_pct', 0):+g}%)" if r.get("renewal") and r["renewal"]["status"] == "offered" else "")
                for r in d.get("policies", [])]
        return f"Billing (total due ${d.get('total_due_usd', 0):,.2f}): " + ("; ".join(rows) or "no policies billed")
    if t == "get_driving_summary":
        if not d.get("enrolled"):
            return "DriveWell: not enrolled" + ("; eligible with " + ", ".join(v["make"] + " " + v["model"] for v in d.get("vehicles", [])) if d.get("eligible") else "; needs an auto policy")
        return (f"DriveWell: {d.get('program_name')}, score {d.get('score')}, factors {d.get('factors')}, {d.get('trips_count')} trips, "
                f"{d.get('miles_month')} miles this month, renewal discount earned {d.get('discount_earned_pct')}%"
                + (" (already applied)" if d.get("discount_applied") else ""))
    if t == "get_wellness_summary":
        ded, th, wr, pp = d.get("deductible") or {}, d.get("telehealth") or {}, d.get("wearable") or {}, d.get("pet_plan") or {}
        opens = [f"{day['date']} {s['time']}" for day in th.get("days", []) for s in day["slots"] if s["open"] > 0][:4]
        return ((f"Health: {(d.get('health_plan') or {}).get('name')}, deductible ${ded.get('met_usd', 0):,.0f} of ${ded.get('individual_usd', 0):,.0f} met, "
                 f"out-of-pocket ${ded.get('oop_met_usd', 0):,.0f} of ${ded.get('oop_max_usd', 0):,.0f}. " if d.get("has_health") else "")
                + (f"Telehealth: {th.get('visits_used', 0)} visits used; " + (f"booked {th['upcoming']['date']} {th['upcoming']['time']} with {th['upcoming']['provider']}" if th.get("upcoming") else "open: " + ", ".join(opens)) + ". ")
                + (f"Pet: {pp.get('name')} for {', '.join(x['name'] for x in pp.get('pets', []))}, {pp.get('reimbursement_pct')}% back, ${pp.get('deductible_left_usd', 0):,.0f} of deductible left. " if d.get("has_pet") else "")
                + (f"Wearable: {wr.get('device')} linked, {wr.get('points', 0)} points." if wr.get("linked") else "Wearable: not linked."))
    if t == "get_coverage_options":
        txt = "On-demand cover: " + "; ".join(f"{x['name']} ${x['quote']['price_usd']:,.2f} for {x['quote']['days']} day(s)" for x in d.get("products", []))
        if d.get("active"):
            txt += ". Active now: " + "; ".join(f"{c['name']} until {c['end']}" for c in d["active"])
        if d.get("plans"):
            txt += f". Plans: {d['plans']}"
        return txt
    if t == "get_customer_context" and d:
        return f"Account: {d}"[:700]
    return ""


def _when(iso: str | None) -> str:
    d = days_until(iso)
    if d is None:
        return "soon"
    return "today" if d == 0 else "tomorrow" if d == 1 else f"on {nice_date(iso)}"


def build_prompt(message: str, personal: bool, ctx: dict, profile: dict, memories: list[str]) -> str:
    parts = [PERSONA, "", "CONTEXT:"]
    if personal:
        parts.append("Person: " + _user_summary(profile))
        for c in ctx.get("kb_profile", [])[:3]:
            parts.append("Profile note: " + (c.get("content") or "")[:900])
        ft = _facts_text(ctx.get("facts") or {})
        if ft:
            parts.append(ft)
        if ctx.get("sor"):
            parts.append(f"{ctx['sor'].get('source_label', 'System of record')} segments: " + sources.segments_text(ctx["sor"]) + ".")
        for m in memories[:3]:
            parts.append("Earlier this person said: " + m[:300])
    for c in ctx.get("kb_playbook", [])[:3]:
        parts.append("Knowledge: " + (c.get("content") or "")[:900])
    parts += ["", f"QUESTION: {message.strip()}", "", "ANSWER:"]
    return "\n".join(parts)


def _mentioned_policy(m: str, pols: list[dict]) -> dict | None:
    """The policy a message is about: its number, its line ("my pet policy",
    "the car") or something it covers ("the Outback", "Biscuit")."""
    for x in pols:
        if x["policy_id"].lower() in m:
            return x
    words = {"auto": ["auto", "car", "vehicle", "driving"], "home": ["home", "house"], "renters": ["renters", "apartment"],
             "health": ["health", "medical"], "pet": ["pet", "dog", "cat", "vet"]}
    for x in pols:
        names = [str(v.get("model", "")).lower() for v in x.get("vehicles") or []] + [str(pt.get("name", "")).lower() for pt in x.get("pets") or []]
        if any(re.search(r"(?<![a-z])" + re.escape(w), m) for w in words.get(x["line"], []) + [n for n in names if n]):
            return x
    return None


def _service(m: str) -> dict | None:
    for sid, keys in (("flat", ["flat", "tire", "tyre", "puncture"]), ("jump", ["jump", "battery", "won't start", "wont start"]),
                      ("lockout", ["locked", "lockout", "keys"]), ("fuel", ["gas", "fuel"]), ("tow", ["tow", "broke", "broken", "breakdown", "accident"])):
        if any(k in m for k in keys):
            return C.ROADSIDE_BY_ID[sid]
    return None


def _drive_discount_ready(profile: dict) -> int:
    t = profile.get("telematics") or {}
    if not (t.get("enrolled") and t.get("program") == "safe-driver" and not t.get("redeemed") and len(t.get("trips", [])) >= 5):
        return 0
    return C.drive_discount_pct(t.get("score"))


def _open_slots(d: dict) -> list[tuple[str, str]]:
    return [(day["date"], s["time"]) for day in (d.get("telehealth") or {}).get("days", []) for s in day["slots"] if s["open"] > 0]


def _cover_pick(m: str, d: dict) -> dict | None:
    """The on-demand product a message is about, else the one their plans point to."""
    prods = {x["id"]: x for x in d.get("products", [])}
    plans = d.get("plans") or {}
    if any(k in m for k in ("borrow", "friend", "sister", "brother", "parents")):
        return prods.get("borrow-car")
    if any(k in m for k in ("rental", "rent a car", "renting")):
        return prods.get("rental-car")
    if any(k in m for k in ("trip", "travel", "flight", "flying", "vacation", "holiday", "abroad")):
        return prods.get("travel")
    if any(k in m for k in ("event", "party", "wedding", "market")):
        return prods.get("event-day")
    if plans.get("drive") and (days_until(plans["drive"]["start"]) or 0) <= 3:
        return prods.get("rental-car" if plans["drive"].get("kind") == "rental" else "borrow-car")
    if plans.get("trip"):
        return prods.get("travel")
    if plans.get("drive"):
        return prods.get("rental-car" if plans["drive"].get("kind") == "rental" else "borrow-car")
    return None


def _cover_args(prod: dict, d: dict) -> dict:
    plans = d.get("plans") or {}
    args: dict = {"product": prod["id"], "days": prod["quote"]["days"]}
    if prod["id"] == "travel" and plans.get("trip"):
        t = plans["trip"]
        args.update(start_date=t["depart"], destination=t["destination"], trip_cost_usd=t.get("trip_cost_usd", 0))
    elif prod["id"] in ("borrow-car", "rental-car") and plans.get("drive"):
        args.update(start_date=plans["drive"]["start"], vehicle=plans["drive"]["vehicle"])
    return args


def compose_fallback(intent: str, personal: bool, message: str, ctx: dict, profile: dict) -> str:
    """Deterministic answer from the same context - used when AOM has no LLM
    provider key (it returns a labelled stub) or AOM is not configured."""
    d = (ctx.get("facts") or {}).get("data") or {}
    first = profile["first_name"]
    audience = profile["audience"]
    m = message.lower()
    pols = [x for x in profile.get("policies", []) if x.get("status") == "active"]
    if not personal or intent == "general":
        # Answer the question actually asked from the bundled entries when it
        # matches; otherwise the best retrieved chunk.
        wellness = True if ctx.get("knowledge") == "memberguide" else None
        pb = _local_playbook_chunks(message, audience, wellness) or ctx.get("kb_playbook")
        if pb:
            return pb[0].get("answer") or pb[0]["content"]
        return "I can help with ID cards and documents, claims, roadside, payments and renewals, DriveWell, on-demand cover - or bring in a licensed agent."
    if intent == "documents":
        ps = d.get("policies", [])
        od = [c for c in d.get("on_demand", []) if c.get("active")]
        if any(k in m for k in ("lender", "landlord", "mortgage", "evidence of insurance", "bank")):
            return (f"I can request an evidence of insurance letter naming your lender or landlord, {first}. It's prepared by hand and is in "
                    "your documents within one business day, free of charge.")
        cards = [x for x in ps if x.get("id_card")]
        pick = _mentioned_policy(m, cards) or (cards[0] if cards else None)
        if pick:
            what = " and ".join(f"{v['year']} {v['make']} {v['model']}" for v in pick.get("vehicles") or []) or pick["product"]
            return (f"Your {pick['line']} ID card for {what} (policy {pick['policy_id']}, valid to {nice_date(pick['expires'])}) is on your phone, "
                    f"{first} - it opens without a signal and is accepted as proof of insurance. "
                    + (f"You also have {len(ps) - 1} other polic{'ies' if len(ps) - 1 != 1 else 'y'} with documents ready. " if len(ps) > 1 else "")
                    + "I can also email or mail a copy.")
        if od:
            return f"Your certificate for {od[0]['name']} ({od[0]['coverage_id']}, valid to {nice_date(od[0]['end'])}) is saved on your phone, {first}."
        if ps:
            return f"Your documents for {', '.join(x['policy_id'] for x in ps)} are in ID Cards & Documents, {first}, and stored on your phone."
        return f"You don't have a policy or active cover yet, {first}, so there's no card to show. On-demand cover gives you a certificate the moment you activate it."
    if intent == "claim":
        claims = d.get("claims", [])
        fileable = d.get("fileable_policies", [])
        filing = any(k in m for k in ("file", "new claim", "start a claim", "make a claim", "report"))
        c = next((x for x in claims if x["claim_id"].lower() in m), None) or (None if filing else next((x for x in claims if x["open"]), claims[0] if claims else None))
        if c:
            txt = (f"Claim {c['claim_id']} ({C.LOSS_LABEL.get(c['loss_type'], c['loss_type']).lower()}, {nice_date(c['loss_date'])}) is at "
                   f"\"{c['status_label'].lower()}\", {first}. ")
            if c.get("estimate_usd"):
                txt += (f"The estimate is {money(c['estimate_usd'])}; after your {money(c['deductible_usd'])} deductible, "
                        f"{money(max(0, c['estimate_usd'] - c['deductible_usd']))} would be paid. ")
            return txt + f"{c['adjuster']} is your adjuster and has {c['photos']} photo{'s' if c['photos'] != 1 else ''}. {c['next_step']}"
        if not fileable:
            return f"Claims are filed on an auto, home or renters policy, {first}, and there isn't one on your account. For on-demand cover, call {C.COMPANY['claims_phone']}."
        return (f"You have no open claims, {first}. I can start one on {' or '.join(x['policy_id'] for x in fileable[:2])}: tell me what happened, "
                "take a few photos or a short video, and it's filed - even with no signal. An adjuster is assigned within one business day.")
    if intent == "emergency":
        return (f"I'm sorry, {first}. First make sure everyone is safe, and call 911 if anyone is hurt. I can alert our 24/7 emergency desk "
                f"with your location right now - they'll call {profile.get('phone') or 'you'} within 2 minutes"
                + (", and I can send a tow and start your claim from here." if d.get("vehicles") else "."))
    if intent == "roadside":
        a = d.get("active_dispatch")
        if a:
            return (f"{a['provider']} is already on the way for your {a['service_name'].lower()} ({a['dispatch_id']}), about {a['eta_minutes']} minutes "
                    f"from when you asked, heading to {a['location']['label']}.")
        svc = _service(m)
        cover = (f"it's covered by your policy - {d.get('calls_left')} call{'s' if d.get('calls_left') != 1 else ''} left this term" if d.get("plan") == "included"
                 else "it's included with your on-demand cover" if d.get("plan") == "on-demand"
                 else f"you don't have a roadside plan, so a call is {money(d.get('cost_usd') or C.ROADSIDE_PAYG_USD)}")
        where = (d.get("last_location") or {}).get("label")
        return (f"I can send {C.a_or_an(svc['name'].lower()) if svc else 'help'} to you now, {first}; {cover}. "
                + (f"{svc['detail']} " if svc else "Tow, flat tire, jump-start, lockout or fuel. ")
                + (f"I'll use your phone's GPS - your last known spot was {where}." if where else "Share your location and it usually takes 25 to 40 minutes."))
    if intent == "billing":
        rows = d.get("policies", [])
        if not rows:
            return f"There's nothing billed on your account, {first} - on-demand cover is paid when you activate it."
        r = next((x for x in rows if x["policy_id"].lower() in m), None) or _row_for(m, rows, pols)
        ready = _drive_discount_ready(profile)
        if any(k in m for k in ("renew", "expire", "expiring", "went up", "increase")):
            rr = r if r and r.get("renewal") else next((x for x in rows if x.get("renewal") and x["renewal"]["status"] == "offered"), None)
            if not rr:
                nxt = min(rows, key=lambda x: x["expires"])
                return f"No renewal offer yet, {first}. Your next renewal is {nxt['policy_id']} on {nice_date(nxt['expires'])}; the offer arrives about 30 days before."
            rn = rr["renewal"]
            if rn["status"] == "renewed":
                return f"{rr['policy_id']} is already renewed through {nice_date(rn.get('new_expires'))}, {first}."
            ch = rn.get("change_pct") or 0
            return (f"Your {rr['line']} policy {rr['policy_id']} renews on {nice_date(rr['expires'])} ({rr['days_to_expiry']} days) at {money(rn['offer_premium_usd'])} "
                    f"for the term" + (f", {abs(ch):g}% {'more' if ch > 0 else 'less'} than now" if ch else "") + f", {first}. "
                    + (f"Your DriveWell score has earned {ready}% off that - apply it before you renew. " if ready and rr["line"] == "auto" else "")
                    + f"Paying in full takes another {d.get('pay_in_full_discount_pct')}% off.")
        if "autopay" in m or "auto-pay" in m or "auto pay" in m:
            on = [x["policy_id"] for x in rows if x["autopay"]]
            off = [x["policy_id"] for x in rows if not x["autopay"] and x["plan"] == "monthly"]
            return ((f"AutoPay is on for {', '.join(on)}" if on else "AutoPay isn't on for any policy") + (f" and off for {', '.join(off)}" if off else "")
                    + f", {first}. Turning it on saves {money(d.get('autopay_discount_usd'))} a month per policy.")
        late = next((x for x in rows if x["past_due"]), None)
        if late and (r is None or r["policy_id"] == late["policy_id"]):
            return (f"{money(late['amount_due_usd'])} is past due on your {late['line']} policy {late['policy_id']}, {first}: the "
                    f"{money(late['balance_due_usd'])} payment from {nice_date(late['next_due'])} plus a {money(late['late_fee_usd'])} late fee. "
                    "Pay it now to stay covered; if it was a one-off, I can ask a billing supervisor to waive the fee.")
        r = r or min(rows, key=lambda x: x["next_due"] or "9999")
        if r["plan"] != "monthly":
            return f"{r['policy_id']} is paid in full through {nice_date(r['expires'])}, {first} - nothing is due."
        return (f"Your next {r['line']} payment is {money(r['amount_due_usd'] or r['installment_usd'])}, due {_when(r['next_due'])} on {r['policy_id']}, {first}. "
                + (f"AutoPay will take it from your {(r.get('method') or {}).get('type', 'card')} ending {(r.get('method') or {}).get('last4', '')}." if r["autopay"]
                   else f"AutoPay is off; turning it on saves {money(d.get('autopay_discount_usd'))} a month.")
                + (f" In total {money(d['total_due_usd'])} is due across your policies." if len(rows) > 1 and d.get("total_due_usd", 0) > (r["amount_due_usd"] or 0) else ""))
    if intent == "telematics":
        if not d.get("enrolled"):
            if not d.get("eligible"):
                return f"DriveWell goes with a Harborline Auto policy, {first}, and there isn't one on your account."
            v = d["vehicles"][0]
            return (f"You're not in DriveWell yet, {first}. Safe Driver takes 5% off for joining and up to 25% at renewal for your "
                    f"{v['make']} {v['model']}; your phone records the trips, even with no signal. Pay-Per-Mile suits cars driven under 8,000 miles a year.")
        if d.get("program") == "pay-per-mile":
            return (f"You've driven {d.get('miles_month', 0):g} miles this month on Pay-Per-Mile, {first}, so this month's bill is about "
                    f"{money(d.get('month_cost_usd'))}. Your driving score is {d.get('score')}.")
        weak = d.get("weakest_factor")
        return (f"Your DriveWell score is {d.get('score')} over {d.get('trips_count')} trips, {first} - that earns {d.get('discount_earned_pct')}% off at renewal"
                + (" and it's already applied. " if d.get("discount_applied") else ". ")
                + (f"Your weakest area is {weak} ({d['factors'][weak]}); improving it is the quickest way to the next tier. " if weak and d["factors"][weak] < 95 else "")
                + f"You've driven {d.get('miles_month', 0):g} miles this month.")
    if intent == "wellness":
        ded, th, wr, pp = d.get("deductible") or {}, d.get("telehealth") or {}, d.get("wearable") or {}, d.get("pet_plan") or {}
        if any(k in m for k in ("vet", "pet", "dog", "cat", "invoice", "reimburs")) and d.get("has_pet"):
            names = " and ".join(x["name"] for x in pp.get("pets", []))
            return (f"{pp['name']} pays back {pp['reimbursement_pct']}% of covered vet costs for {names}, {first}"
                    + (f", after {money(pp['deductible_left_usd'])} more of your {money(pp['annual_deductible'])} deductible. " if pp.get("deductible_left_usd") else "; your deductible is met. ")
                    + "Photograph the itemized invoice and submit it - bills up to $600 are approved automatically and paid in 2 days."
                    + ("" if pp.get("routine_care") else " Routine care (annual exams, dental cleanings) isn't covered without the add-on."))
        if any(k in m for k in ("wearable", "watch", "fitbit", "garmin", "oura", "steps", "points", "reward")):
            if wr.get("linked"):
                return (f"Your {wr['device']} is linked, {first}: {wr.get('points', 0):,} points, worth {money(wr.get('reward_usd', 0))} off your premium. "
                        f"You're averaging {wr.get('steps_7d_avg', 0):,} steps a day this week.")
            return (f"You haven't linked a wearable yet, {first}. Link one for {C.WELLNESS_LINK_BONUS} points, then earn {C.WELLNESS_POINTS_PER_GOAL_DAY} for every "
                    f"{C.WELLNESS_STEP_GOAL:,}-step day; 1,000 points is $10 off your premium.")
        if any(k in m for k in ("deductible", "out-of-pocket", "out of pocket", "met")) and ded:
            left = max(0, ded["individual_usd"] - ded["met_usd"])
            return (f"You've met {money(ded['met_usd'])} of your {money(ded['individual_usd'])} deductible, {first}, so {money(left)} to go; "
                    f"out-of-pocket is {money(ded['oop_met_usd'])} of {money(ded['oop_max_usd'])}. It resets {nice_date(ded.get('resets'))}. "
                    "Telehealth and preventive care don't wait for the deductible.")
        if th.get("upcoming"):
            u = th["upcoming"]
            return f"You're booked for a {u['type_name'].lower()} video visit with {u['provider']} on {nice_date(u['date'])} at {u['time']}, {first}."
        opens = _open_slots(d)
        copay = (d.get("health_plan") or {}).get("telehealth_copay", 0)
        return ("You can see a clinician by video" + (f" with a {money(copay)} copay" if copay else " with no copay on your plan") + f", {first}"
                + (f" - the next opening is {_when(opens[0][0])} at {opens[0][1]}. " if opens else ". ")
                + "I can't give medical advice, but I can book the visit now.")
    if intent == "coverage":
        act = d.get("active", [])
        if any(k in m for k in ("active", "do i have", "already have")):
            up = d.get("upcoming", [])
            if not act and not up:
                return f"Nothing is active right now, {first}. On-demand cover starts the moment you confirm - tell me what you're doing and I'll price it."
            return ((("Active now: " + "; ".join(f"{c['name']} until {nice_date(c['end'])}" for c in act) + ". ") if act else "Nothing is active right now. ")
                    + (("Scheduled: " + "; ".join(f"{c['name']} from {nice_date(c['start'])}" for c in up) + ". ") if up else "")
                    + f"The certificates are saved on your phone, {first}.")
        prod = _cover_pick(m, d)
        if act and not prod:
            return "Active now, " + first + ": " + "; ".join(f"{c['name']} until {nice_date(c['end'])}" for c in act) + ". The certificates are on your phone."
        if not prod:
            return ("On-demand cover starts the moment you confirm, " + first + ": "
                    + "; ".join(f"{x['name'].lower()} from {money(x['min_usd'])}" for x in d.get("products", [])) + ". Tell me what you're doing and I'll price it.")
        q, plans = prod["quote"], d.get("plans") or {}
        detail = ""
        if prod["id"] == "travel" and plans.get("trip"):
            detail = f" for your trip to {plans['trip']['destination']} ({nice_date(plans['trip']['depart'])} to {nice_date(plans['trip']['return'])})"
        elif prod["id"] in ("borrow-car", "rental-car") and plans.get("drive"):
            detail = f" for the {plans['drive']['vehicle']} from {nice_date(plans['drive']['start'])}"
        return (f"{prod['name']}{detail} is {money(q['price_usd'])} for {q['days']} day{'s' if q['days'] != 1 else ''}, {first}. "
                f"{prod['blurb']} It's active as soon as you confirm, and the certificate is saved on your phone.")
    if intent == "account":
        if any(k in m for k in ("address", "moved", "moving", "email", "phone", "contact", "details")):
            return (f"I have {profile.get('address') or 'no address'}, {profile.get('email')} and {profile.get('phone') or 'no phone number'} on file, {first}. "
                    "Tell me what changed and I'll update it - a new address can change an auto or home rate, which we confirm within a day.")
        if any(k in m for k in ("driver", "vehicle", "new car", "deductible", "liability", "limit", "coverage change", "rental reimbursement", "mortgage")):
            return (f"I can send that change in for you, {first}. Adding or removing a driver or vehicle and changing deductibles or limits are "
                    "reviewed by underwriting - you'll see their decision here; simple updates like a new mortgage company apply the same day.")
        if not pols:
            return f"You don't have an annual policy, {first} - you buy cover by the day when you need it."
        return (f"You have {len(pols)} active polic{'ies' if len(pols) != 1 else 'y'}, {first}: "
                + "; ".join(f"{x['product']} {x['policy_id']} (to {nice_date(x['expires'])}" + (f", {money(x['deductible_usd'])} deductible" if x.get("deductible_usd") else "") + ")" for x in pols)
                + ". Ask me about any coverage, or I can request a change.")
    if intent == "handoff":
        return (f"Of course, {first}. A licensed agent can join by chat, callback or video ({C.COMPANY['support_hours']}); they'll see this conversation "
                "and your policies, so you won't have to repeat yourself.")
    return "Here's what I found."


def _row_for(m: str, rows: list[dict], pols: list[dict]) -> dict | None:
    pick = _mentioned_policy(m, pols)
    return next((r for r in rows if pick and r["policy_id"] == pick["policy_id"]), None)


def suggest_actions(intent: str, ctx: dict, profile: dict, message: str) -> list[dict]:
    d = (ctx.get("facts") or {}).get("data") or {}
    m = message.lower()
    said = message.strip()[:200]
    pols = [x for x in profile.get("policies", []) if x.get("status") == "active"]
    acts: list[dict] = []
    if intent == "documents":
        ps = d.get("policies", [])
        if ps or d.get("on_demand"):
            acts.append({"label": "Show my ID cards", "screen": "cards"})
        pick = _mentioned_policy(m, ps) or (ps[0] if ps else None)
        if pick and any(k in m for k in ("lender", "landlord", "mortgage", "evidence of insurance", "bank")):
            acts.insert(0, {"label": "Request a lender letter", "screen": "cards", "args": {"policy_id": pick["policy_id"], "request": "lender_letter"}})
        elif pick and "mail" in m and pick.get("id_card"):
            acts.append({"label": "Mail me a printed card", "tool": "request_document", "args": {"policy_id": pick["policy_id"], "doc_type": "id_card", "delivery": "mail"}})
        elif pick and any(k in m for k in ("proof", "letter")) and "proof_of_insurance" in pick.get("available_documents", []):
            acts.append({"label": "Email proof of insurance", "tool": "request_document",
                         "args": {"policy_id": pick["policy_id"], "doc_type": "proof_of_insurance", "delivery": "email"}})
    elif intent == "claim":
        claims = d.get("claims", [])
        filing = any(k in m for k in ("file", "new claim", "start a claim", "make a claim", "report"))
        c = next((x for x in claims if x["claim_id"].lower() in m), None) or (None if filing else next((x for x in claims if x["open"]), None))
        if c:
            acts.append({"label": f"Track {c['claim_id']}", "screen": "claim", "args": {"claim_id": c["claim_id"]}})
            if c["open"]:
                acts.append({"label": "Add photos or documents", "screen": "claim", "args": {"claim_id": c["claim_id"], "add": "1"}})
        elif d.get("fileable_policies"):
            acts.append({"label": "File a claim with photos", "screen": "claim"})
    elif intent == "emergency":
        acts.append({"label": "Send SOS with my location", "screen": "roadside", "args": {"sos": "travel" if any(k in m for k in ("abroad", "travel", "trip")) else "medical" if any(k in m for k in ("medical", "hospital", "sick")) else "accident"}})
        if d.get("vehicles") or d.get("plan") != "pay-per-use":
            acts.append({"label": "Request a tow", "screen": "roadside", "args": {"service": "tow"}})
        if any(x["line"] == "auto" for x in pols):
            acts.append({"label": "Start a claim", "screen": "claim"})
    elif intent == "roadside":
        if not d.get("active_dispatch"):
            svc = _service(m)
            acts.append({"label": f"Send {C.a_or_an(svc['name'].lower())} to my location" if svc else "Request roadside help", "screen": "roadside",
                         "args": {"service": svc["id"]} if svc else {}})
        else:
            acts.append({"label": "Follow the truck", "screen": "roadside"})
    elif intent == "billing":
        rows = d.get("policies", [])
        ready = _drive_discount_ready(profile)
        offered = [r for r in rows if r.get("renewal") and r["renewal"]["status"] == "offered"]
        if any(k in m for k in ("renew", "expire", "expiring", "went up", "increase")) and offered:
            r = offered[0]
            if ready and r["line"] == "auto":
                acts.append({"label": f"Apply my {ready}% DriveWell discount", "tool": "redeem_drive_discount", "args": {}})
            acts.append({"label": "Review my renewal", "screen": "pay", "args": {"policy_id": r["policy_id"], "renew": "1"}})
        else:
            r = next((x for x in rows if x["policy_id"].lower() in m), None) or _row_for(m, rows, pols)
            late = next((x for x in rows if x["past_due"]), None)
            r = r or late or next((x for x in sorted(rows, key=lambda x: x["next_due"] or "9999") if x["amount_due_usd"] > 0), None)
            if r and r["amount_due_usd"] > 0:
                acts.append({"label": f"Pay {money(r['amount_due_usd'])} now", "tool": "make_payment", "args": {"policy_id": r["policy_id"]}})
                if r["late_fee_usd"]:
                    acts.append({"label": f"Ask to waive the {money(r['late_fee_usd'])} late fee", "tool": "request_fee_waiver",
                                 "args": {"policy_id": r["policy_id"], "reason": f"Requested in chat: {said}"}})
            auto_off = next((x for x in rows if not x["autopay"] and x["plan"] == "monthly" and not x["past_due"]), None)
            if auto_off and len(acts) < 2:
                acts.append({"label": f"Turn on AutoPay · save {money(d.get('autopay_discount_usd'))}/mo", "tool": "set_autopay",
                             "args": {"policy_id": auto_off["policy_id"], "enabled": True}})
            if rows:
                acts.append({"label": "See all bills", "screen": "pay"})
    elif intent == "telematics":
        if d.get("enrolled"):
            ready = _drive_discount_ready(profile)
            if ready and any((x.get("renewal") or {}).get("status") == "offered" for x in pols if x["line"] == "auto"):
                acts.append({"label": f"Apply my {ready}% discount to renewal", "tool": "redeem_drive_discount", "args": {}})
            acts.append({"label": "See my trips", "screen": "drive"})
        elif d.get("eligible"):
            acts.append({"label": "Join DriveWell Safe Driver", "tool": "enroll_telematics", "args": {"program": "safe-driver", "device": "phone"}})
            acts.append({"label": "Compare programs", "screen": "drive"})
    elif intent == "wellness":
        if any(k in m for k in ("vet", "pet", "dog", "cat", "invoice", "reimburs")) and d.get("has_pet"):
            acts.append({"label": "Submit a vet bill", "screen": "wellness", "args": {"tab": "pet"}})
        elif any(k in m for k in ("wearable", "watch", "fitbit", "garmin", "oura", "steps", "points", "reward")):
            acts.append({"label": "My rewards" if (d.get("wearable") or {}).get("linked") else "Link a device", "screen": "wellness", "args": {"tab": "wearable"}})
        elif any(k in m for k in ("deductible", "out-of-pocket", "out of pocket", "met")):
            acts.append({"label": "See my plan", "screen": "wellness", "args": {"tab": "deductible"}})
        elif not (d.get("telehealth") or {}).get("upcoming"):
            opens = _open_slots(d)
            vt = "vet" if not d.get("has_health") else "mental" if any(k in m for k in ("therap", "anxi", "stress", "mental")) else "derm" if any(k in m for k in ("skin", "rash", "derm")) else "primary"
            if opens:
                acts.append({"label": f"Book {nice_date(opens[0][0])} at {opens[0][1]}", "tool": "book_telehealth",
                             "args": {"date": opens[0][0], "time": opens[0][1], "visit_type": vt, "reason": said}})
            acts.append({"label": "See all visit times", "screen": "wellness", "args": {"tab": "telehealth"}})
    elif intent == "coverage":
        prod = None if any(k in m for k in ("active", "do i have", "already have")) else _cover_pick(m, d)
        if d.get("active") and not prod:
            acts.append({"label": "Show my certificates", "screen": "cards"})
        if prod:
            args = _cover_args(prod, d)
            need = [n for n in prod["needs"] if not args.get(n)]
            if not need:
                acts.append({"label": f"Activate · {money(prod['quote']['price_usd'])}", "tool": "activate_coverage", "args": args})
            acts.append({"label": "Change dates or details", "screen": "coverage", "args": {"product": prod["id"]}})
        else:
            acts.append({"label": "See on-demand cover", "screen": "coverage"})
    elif intent == "account":
        if any(k in m for k in ("address", "moved", "moving", "email", "phone", "contact", "details")):
            acts.append({"label": "Update my details", "screen": "support", "args": {"tab": "details"}})
        elif pols:
            acts.append({"label": "Request a policy change", "screen": "support", "args": {"tab": "change"}})
            acts.append({"label": "Show my policies", "screen": "cards"})
    elif intent == "handoff":
        topic = ("Claim question" if "claim" in m else "Billing question" if any(k in m for k in ("bill", "pay", "fee", "premium")) else
                 "Coverage change" if any(k in m for k in ("coverage", "policy", "add", "change")) else "Cancel or switch" if "cancel" in m else "Something else")
        acts.append({"label": "Chat with a licensed agent", "tool": "request_live_agent", "args": {"topic": topic, "channel": "chat", "note": said}})
        acts.append({"label": "Request a callback", "tool": "request_live_agent", "args": {"topic": topic, "channel": "callback", "note": said}})
    return acts


# Only durable things a person says about themselves become memories ("I
# park on the street", "Biscuit is allergic to chicken"). Plain questions
# don't, which also keeps repeat questions' prompts stable for the LLM cache.
STATEMENT_RE = re.compile(r"\b(i|we)('m|'re| am| are| love| like| prefer| hate| don't| do not| want| need| always| never| work| have| drive| park| travel)\b"
                          r"|\bmy (wife|husband|partner|kids?|son|daughter|car|dog|cat|commute|garage|doctor|vet)\b|\ballerg", re.I)


async def _remember(user_id: str, message: str, reply: str, intent: str, session_id: str):
    if not aom.enabled or not STATEMENT_RE.search(message) or message.strip().endswith("?"):
        return
    try:
        await aom.memory_add(user_id, f"User said ({intent}): {message.strip()[:500]}", session_id=session_id,
                             metadata={"intent": intent, "app": "insurance-mobile"})
    except AOMError as exc:
        log.info("memory add skipped: %s", exc)


async def _recall(user_id: str, message: str) -> list[str]:
    if not aom.enabled:
        return []
    try:
        res = await aom.memory_search(user_id, message, top_k=3)
        return [e.get("content", "") for e in res.get("entries", []) if e.get("content")]
    except AOMError:
        return []


async def _ask_rag_app(message: str, intent: str, profile: dict) -> dict | None:
    """Shared questions go to one of the app's AOM RAG Applications: one call
    that runs AOM's Context Cache (retrieval), the KB search scoped to today's
    Help Center or Member Care Guide, and the LLM Cache, and is counted on the RAG
    Applications page."""
    key = rag_app.app_for(intent, profile["audience"])
    app = rag_app.APPS[key]
    if not rag_app.usable(key):
        return None
    l0 = time.perf_counter()
    try:
        res = await aom.rag_query(app["app_id"], message)
    except AOMError as exc:
        rag_app.query_failed(key, exc)
        log.info("RAG app query failed, answering on the assistant's own path: %s", exc)
        return None
    ms = round((time.perf_counter() - l0) * 1000, 1)
    retrieval = res.get("retrieval") or {}
    llm_res = res.get("llm") or {}
    cache = llm_res.get("cache") or {}
    srcs = res.get("sources") or []
    chunks = [{"title": c.get("document_title"), "content": c.get("preview"), "source": "aom-rag"} for c in srcs]
    reply = (res.get("answer") or "").strip()
    llm = {"status": cache.get("status", "skipped" if not res.get("llm") else "miss"), "similarity": cache.get("similarity"),
           "namespace": f"rag:{app['app_id']}", "provider": llm_res.get("provider"), "model": llm_res.get("model"),
           "latency_ms": ms, "stub": bool(llm_res.get("stub")), "tokens_saved": llm_res.get("tokens_saved") or 0,
           "cost_saved_usd": llm_res.get("cost_saved_usd") or 0, "rag_app": app["app_id"]}
    if not res.get("llm") or llm["stub"] or not reply:
        # No LLM provider key in AOM (stub) or nothing retrieved: answer from
        # the same knowledge deterministically.
        reply = compose_fallback(intent, False, message, {"kb_playbook": chunks, "knowledge": app["kb_key"]}, profile)
        llm["composed_locally"] = True
    return {
        "reply": reply, "llm": llm,
        "sources": [{"title": c["title"], "snippet": (c.get("content") or "")[:160], "kind": "aom-rag"} for c in chunks[:3]],
        "context": {"status": retrieval.get("cache", "miss"), "latency_ms": retrieval.get("latency_ms", 0),
                    "source": "aom-rag", "rag_app": app["app_id"], "knowledge": app["kb_key"], "chunks": retrieval.get("chunks"),
                    "export_date": profile.get("export_date"), "kb_mode": "aom"},
        "trace_id": (res.get("trace") or {}).get("trace_id"),
    }


async def ask(user_id: str, message: str, session_id: str | None = None) -> dict:
    session_id = session_id or f"app-{user_id}"
    trace_id = uuid.uuid4().hex
    token = current_trace.set({"trace_id": trace_id, "session_id": session_id})
    t0 = time.perf_counter()
    try:
        profile = await store.get("profiles", profile_id(user_id))
        if not profile:
            raise ValueError("unknown user")
        audience = profile["audience"]
        intent, personal = classify(message, audience)
        base = {"intent": intent, "area": AREA[intent], "audience": audience, "export_date": STATE.get("export_date")}
        if intent in MEMBER_INTENTS and audience != "member":
            # Nothing is retrieved or generated: the Member Care Guide never
            # enters the context of someone without a health or pet plan.
            result = {**base, "reply": RESTRICTED, "personal": False, "restricted": True, "actions": [], "sources": [],
                      "context": {"status": None, "latency_ms": 0, "source": "audience-gate"}, "memory_recalled": 0,
                      "llm": {"status": "skipped", "namespace": None}, "trace_id": None, "governed": aom.enabled,
                      "total_ms": round((time.perf_counter() - t0) * 1000, 1)}
            metrics.assistant(result)
            await _append_chat(user_id, message, result)
            return result
        if personal and intent not in APPLICABLE[audience]:
            personal = False
        if not personal:
            via_rag = await _ask_rag_app(message, intent, profile)
            if via_rag:
                result = {**base, "reply": via_rag["reply"], "personal": False, "actions": [],
                          "sources": via_rag["sources"], "context": via_rag["context"], "memory_recalled": 0,
                          "llm": via_rag["llm"], "trace_id": via_rag["trace_id"] or trace_id, "governed": True,
                          "total_ms": round((time.perf_counter() - t0) * 1000, 1)}
                metrics.assistant(result)
                await _append_chat(user_id, message, result)
                return result
        ctx = await get_context(user_id, intent, profile, personal)
        memories = await _recall(user_id, message) if personal else []
        prompt = build_prompt(message, personal, ctx, profile, memories)
        app_id = rag_app.APPS[rag_app.app_for(intent, audience)]["app_id"]
        namespace = config.llm_namespace(app_id, personal)
        llm = {"status": "local", "namespace": namespace, "provider": None, "model": None, "similarity": None,
               "latency_ms": None, "stub": False, "tokens_saved": 0}
        reply = None
        if aom.enabled:
            try:
                l0 = time.perf_counter()
                res = await aom.complete(prompt, namespace=namespace)
                cache = res.get("cache") or {}
                llm.update({"status": cache.get("status", "miss"), "similarity": cache.get("similarity"),
                            "provider": res.get("provider"), "model": res.get("model"),
                            "latency_ms": round((time.perf_counter() - l0) * 1000, 1), "stub": bool(res.get("stub")),
                            "tokens_saved": res.get("tokens_saved", 0), "cost_saved_usd": res.get("cost_saved_usd", 0)})
                if not res.get("stub") and (res.get("response") or "").strip():
                    reply = res["response"].strip()
            except AOMError as exc:
                llm["status"] = "error"
                llm["error"] = str(exc)[:200]
        if not reply:
            reply = compose_fallback(intent, personal, message, ctx, profile)
            llm["composed_locally"] = True
        actions = suggest_actions(intent, ctx, profile, message) if personal else []
        sources_out = ([{"title": c["title"], "snippet": (c.get("content") or "")[:160], "kind": c.get("source")}
                        for c in (ctx.get("kb_profile", []) if personal else [])[:2]]
                       + [{"title": c["title"], "snippet": (c.get("content") or "")[:160], "kind": c.get("source")}
                          for c in ctx.get("kb_playbook", [])[:2]])
        sor = ctx.get("sor")
        result = {
            **base, "reply": reply, "personal": personal, "actions": actions, "sources": sources_out,
            "context": {"status": ctx["_cache"]["status"], "latency_ms": ctx["_cache"]["latency_ms"],
                        "source": ctx["_cache"].get("source"), "rag_app": app_id, "knowledge": ctx.get("knowledge"),
                        "built_at": ctx.get("built_at"), "build_ms": ctx.get("build_ms"), "kb_mode": ctx.get("kb_mode"),
                        "export_date": ctx.get("export_date"),
                        "sor": ({"system": sor.get("source"), "label": sor.get("source_label"), "mode": sor.get("mode"),
                                 "latency_ms": sor.get("latency_ms"), "segments": [s["name"] for s in sor.get("segments", [])]}
                                if sor else None)},
            "memory_recalled": len(memories), "llm": llm, "trace_id": trace_id if aom.enabled else None,
            "governed": aom.enabled, "total_ms": round((time.perf_counter() - t0) * 1000, 1),
        }
        metrics.assistant(result)
        await _append_chat(user_id, message, result)
        await _remember(user_id, message, reply, intent, session_id)
        return result
    finally:
        current_trace.reset(token)


async def _append_chat(user_id: str, message: str, result: dict):
    doc = await store.get("chat", chat_id(user_id)) or {
        "type": "chat", "user_id": user_id, "messages": [], "answers": {}, "channels": [user_channel(user_id)]}
    now = now_iso()
    doc["messages"] = (doc["messages"] + [
        {"id": uuid.uuid4().hex[:12], "role": "user", "text": message, "at": now},
        {"id": uuid.uuid4().hex[:12], "role": "assistant", "text": result["reply"], "at": now,
         "intent": result["intent"], "area": result["area"], "actions": result["actions"], "context": result["context"],
         "llm": result["llm"], "sources": result["sources"], "restricted": result.get("restricted", False)},
    ])[-40:]
    # Answer cache the phone can reuse offline for the same (normalized) question.
    if not result.get("restricted"):
        doc["answers"][_norm(message)[:120]] = {"reply": result["reply"], "intent": result["intent"], "area": result["area"], "at": now}
    if len(doc["answers"]) > 60:
        doc["answers"] = dict(list(doc["answers"].items())[-60:])
    doc["updated_at"] = now
    await store.upsert("chat", chat_id(user_id), doc)
