"""Harborline actions - the business logic behind every MCP tool.

These functions are what actually changes state (documents, claims, roadside
dispatches, payments, renewals, telematics, telehealth, vet bills, on-demand
cover). They are only ever reached through `tool_gateway`, which routes them
through the Couchbase Agent Operations Manager when it is configured (RBAC,
approvals, tracing, audit) and calls them in-process otherwise. Every
mutation bumps the person's profile `rev`, which is what invalidates their
context cache and re-ranks their For You feed.

Each tool checks what the caller actually holds: a claim needs a policy of
that line, roadside needs an auto policy or active on-demand cover (or it is
charged per call), and the health and pet tools never run for someone without
one of those plans, whatever the agent was asked to do.
"""
from __future__ import annotations

import calendar
import datetime as dt
import uuid

from . import catalog as C
from .docs import INVENTORY_ID, activity_id, days_until, money, nice_date, now_iso, profile_id, today, user_channel
from .store import store


class ToolError(Exception):
    pass


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
async def load_profile(user_id: str) -> dict:
    p = await store.get("profiles", profile_id(user_id))
    if not p:
        raise ToolError(f"No profile for '{user_id}'")
    return p


def require_member(profile: dict):
    if profile.get("audience") != "member":
        raise ToolError(f"This is part of {C.COMPANY['wellness_brand']} plans and only available to their members")


async def save_profile(p: dict):
    p["rev"] = int(p.get("rev", 0)) + 1
    p["updated_at"] = now_iso()
    await store.upsert("profiles", profile_id(p["user_id"]), p)
    from .loader import mark_live  # late import: loader -> personalization -> actions
    await mark_live(p["user_id"])


async def record_activity(user_id: str, item: dict):
    doc = await store.get("activity", activity_id(user_id)) or {
        "type": "activity", "user_id": user_id, "items": [], "channels": [user_channel(user_id)]}
    doc["items"] = ([i for i in doc["items"] if i.get("item_id") != item["item_id"]] + [item])[-60:]
    doc["updated_at"] = now_iso()
    await store.upsert("activity", activity_id(user_id), doc)


async def after_change(user_id: str):
    # late imports: personalization/assistant import this module
    from . import assistant, personalization
    await personalization.refresh_feed(user_id)
    await assistant.invalidate_context(user_id)


async def get_inventory() -> tuple[dict, int]:
    doc, cas = await store.get_with_cas("inventory", INVENTORY_ID)
    if doc is None:
        await store.insert("inventory", INVENTORY_ID, {"type": "inventory", **C.initial_inventory(today()), "created_at": now_iso()})
        doc, cas = await store.get_with_cas("inventory", INVENTORY_ID)
    return doc, cas


async def take(kind: str, key: str, what: str):
    """Take one telehealth appointment (CAS: two phones can't both get the last one)."""
    for _ in range(10):
        doc, cas = await get_inventory()
        if doc[kind].get(key, 0) <= 0:
            raise ToolError(what)
        doc[kind][key] -= 1
        if await store.replace_cas("inventory", INVENTORY_ID, doc, cas):
            return doc[kind][key]
    raise ToolError("That's busy right now - please try again")


def _item(kind: str, title: str, **kw) -> dict:
    return {"item_id": f"{kind}-{uuid.uuid4().hex[:10]}", "kind": kind, "title": title, "status": "confirmed",
            "date": today().isoformat(), "created_at": now_iso(), **kw}


def _ref(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


def _first(p: dict) -> str:
    return p["first_name"]


def _date(value: str, what: str = "Date") -> dt.date:
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        raise ToolError(f"{what} must be YYYY-MM-DD") from None


def add_months(d: dt.date, n: int) -> dt.date:
    m = d.month - 1 + n
    y, m = d.year + m // 12, m % 12 + 1
    return dt.date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def active_policies(p: dict, *lines: str) -> list[dict]:
    return [x for x in p.get("policies", []) if x.get("status") == "active" and (not lines or x["line"] in lines)]


def _policy(p: dict, policy_id: str, *lines: str) -> dict:
    pol = next((x for x in p.get("policies", []) if x["policy_id"] == policy_id), None)
    if not pol and not policy_id:
        cands = active_policies(p, *lines)
        if len(cands) == 1:
            pol = cands[0]
    if not pol:
        raise ToolError(f"I can't find policy {policy_id} on this account" if policy_id else "Which policy? Give the policy number")
    if lines and pol["line"] not in lines:
        raise ToolError(f"{pol['policy_id']} is {C.a_or_an(pol['line'])} policy; this needs {' or '.join(lines)}")
    return pol


def _vehicles(p: dict) -> list[dict]:
    return [dict(v, policy_id=pol["policy_id"]) for pol in active_policies(p, "auto") for v in pol.get("vehicles", [])]


def vehicle_name(v: dict | None) -> str:
    return f"{v['year']} {v['make']} {v['model']}" if v else "your vehicle"


def active_on_demand(p: dict, roadside: bool = False) -> list[dict]:
    out = []
    for c in (p.get("on_demand") or {}).get("coverages", []):
        if c["start"] <= today().isoformat() <= c["end"] and (not roadside or C.ON_DEMAND_BY_ID.get(c["product"], {}).get("roadside")):
            out.append(c)
    return out


def roadside_plan(p: dict) -> dict:
    """How this person's next roadside call is covered."""
    rs = p.get("roadside") or {}
    auto = [x for x in active_policies(p, "auto") if x.get("roadside")]
    if auto:
        left = max(0, C.ROADSIDE_CALLS_PER_TERM - int(rs.get("uses_this_term", 0)))
        if left:
            return {"plan": "included", "calls_left": left, "cost_usd": 0, "source": auto[0]["policy_id"]}
    od = active_on_demand(p, roadside=True)
    if od:
        return {"plan": "on-demand", "calls_left": None, "cost_usd": 0, "source": od[0]["coverage_id"]}
    return {"plan": "pay-per-use", "calls_left": 0, "cost_usd": C.ROADSIDE_PAYG_USD, "source": None}


def amount_due(pol: dict) -> float:
    b = pol["billing"]
    return round(float(b.get("balance_due_usd") or 0) + float(b.get("late_fee_usd") or 0), 2)


def claim_view(c: dict) -> dict:
    step = C.CLAIM_STEPS.index(c["status"]) if c["status"] in C.CLAIM_STEPS else -1
    return {**c, "step": step, "status_label": C.CLAIM_STEP_LABEL.get(c["status"], c["status"]),
            "next_step": C.CLAIM_NEXT.get(c["status"], ""), "open": c["status"] not in ("paid", "closed", "denied"),
            "photos": sum(e.get("count", 1) for e in c.get("evidence", []) if e["kind"] in ("photo", "video"))}


def pet_claim_math(pol: dict, amount: float, reason: str) -> dict:
    """What a vet bill pays back: after the remaining annual deductible, at the
    plan's reimbursement rate, up to what's left of the annual limit."""
    plan = C.PET_PLAN_BY_ID[pol["plan_id"]]
    used = pol.setdefault("usage", {"deductible_met_usd": 0, "paid_usd": 0})
    if reason in C.VET_ROUTINE and not pol.get("routine_care"):
        return {"eligible_usd": 0, "deductible_applied_usd": 0, "reimbursement_usd": 0, "routine": True, "pct": plan["reimbursement_pct"]}
    ded_left = max(0, plan["annual_deductible"] - used["deductible_met_usd"])
    ded = min(ded_left, amount)
    pay = round((amount - ded) * plan["reimbursement_pct"] / 100, 2)
    pay = max(0, min(pay, plan["annual_limit"] - used["paid_usd"]))
    return {"eligible_usd": amount, "deductible_applied_usd": round(ded, 2), "reimbursement_usd": round(pay, 2), "routine": False,
            "pct": plan["reimbursement_pct"]}


# --------------------------------------------------------------------------
# read tools
# --------------------------------------------------------------------------
async def get_customer_context(user_id: str) -> dict:
    p = await load_profile(user_id)
    pols = active_policies(p)
    return {"user_id": user_id, "audience": p["audience"], "name": f"{p['first_name']} {p['last_name']}",
            "home_city": p.get("home_city"), "email": p.get("email"), "phone": p.get("phone"), "address": p.get("address"),
            "customer_since": (p.get("history") or {}).get("customer_since"),
            "policies": [{"policy_id": x["policy_id"], "line": x["line"], "product": x["product"], "expires": x["expires"]} for x in pols],
            "open_claims": sum(1 for c in p.get("claims", []) if claim_view(c)["open"]),
            "total_due_usd": round(sum(amount_due(x) for x in pols), 2),
            "on_demand_active": len(active_on_demand(p)),
            "segment": p["ml_scores"].get("segment"), "next_best_action": p["ml_scores"].get("next_best_action"),
            "preferences": p.get("preferences"),
            "support": {"open_requests": [r for r in (p.get("support") or {}).get("requests", []) if r.get("status") != "done"]}}


async def get_policies(user_id: str) -> dict:
    p = await load_profile(user_id)
    pols = []
    for x in p.get("policies", []):
        pols.append({k: x.get(k) for k in ("policy_id", "line", "product", "status", "effective", "expires", "premium_usd",
                                           "deductible_usd", "coverages", "vehicles", "property", "pets", "plan_id", "id_card", "documents", "roadside")}
                    | {"days_to_expiry": days_until(x["expires"]),
                       "available_documents": [d["id"] for d in C.DOC_TYPES if x["line"] in d["lines"]]})
    act = active_on_demand(p)
    return {"user_id": user_id, "policies": pols,
            "on_demand": [dict(c, active=c in act) for c in (p.get("on_demand") or {}).get("coverages", [])],
            "pending_documents": [d for x in p.get("policies", []) for d in x.get("documents", []) if d.get("status") == "requested"]}


async def get_claims(user_id: str, claim_id: str = "") -> dict:
    p = await load_profile(user_id)
    claims = [claim_view(c) for c in p.get("claims", []) if not claim_id or c["claim_id"] == claim_id]
    if claim_id and not claims:
        raise ToolError(f"I can't find claim {claim_id} on this account")
    claims.sort(key=lambda c: c["filed_at"], reverse=True)
    fileable = [{"policy_id": x["policy_id"], "line": x["line"], "product": x["product"], "deductible_usd": x.get("deductible_usd"),
                 "what": ", ".join(vehicle_name(v) for v in x.get("vehicles", [])) or (x.get("property") or {}).get("address"),
                 "loss_types": [{"id": i, "name": n} for i, n in C.LOSS_TYPES.get(x["line"], [])]}
                for x in active_policies(p, "auto", "home", "renters")]
    return {"user_id": user_id, "claims": claims, "open": [c["claim_id"] for c in claims if c["open"]], "fileable_policies": fileable}


async def get_roadside_status(user_id: str) -> dict:
    p = await load_profile(user_id)
    rs = p.get("roadside") or {}
    active = next((d for d in rs.get("dispatches", []) if d["status"] in ("dispatched", "en_route", "on_scene")), None)
    return {"user_id": user_id, **roadside_plan(p), "vehicles": _vehicles(p), "active_dispatch": active,
            "recent": rs.get("dispatches", [])[-3:], "last_location": rs.get("last_location"),
            "services": C.ROADSIDE_SERVICES, "emergencies": (p.get("emergencies") or [])[-2:],
            "phone": C.COMPANY["roadside_phone"]}


async def get_billing(user_id: str) -> dict:
    p = await load_profile(user_id)
    rows = []
    for x in active_policies(p):
        b, r = x["billing"], x.get("renewal") or {}
        rows.append({"policy_id": x["policy_id"], "line": x["line"], "product": x["product"], "plan": b["plan"],
                     "installment_usd": b["installment_usd"], "next_due": b.get("next_due"), "days_to_due": days_until(b.get("next_due")),
                     "balance_due_usd": b.get("balance_due_usd", 0), "late_fee_usd": b.get("late_fee_usd", 0), "amount_due_usd": amount_due(x),
                     "past_due": bool(b.get("past_due")), "autopay": bool(b.get("autopay")), "autopay_day": b.get("autopay_day"),
                     "method": b.get("method"), "expires": x["expires"], "days_to_expiry": days_until(x["expires"]),
                     "renewal": r if r.get("status") in ("offered", "renewed") else None})
    rows.sort(key=lambda r: (not r["past_due"], r["next_due"] or "9999"))
    return {"user_id": user_id, "policies": rows, "total_due_usd": round(sum(r["amount_due_usd"] for r in rows), 2),
            "past_due": [r["policy_id"] for r in rows if r["past_due"]],
            "renewals": [r["policy_id"] for r in rows if r["renewal"] and r["renewal"]["status"] == "offered"],
            "payments": (p.get("payments") or [])[-5:], "autopay_discount_usd": C.AUTOPAY_DISCOUNT_USD,
            "pay_in_full_discount_pct": C.PAY_IN_FULL_DISCOUNT_PCT}


async def get_driving_summary(user_id: str) -> dict:
    p = await load_profile(user_id)
    t = p.get("telematics") or {"enrolled": False}
    vehicles = _vehicles(p)
    out = {"user_id": user_id, "enrolled": bool(t.get("enrolled")), "vehicles": vehicles, "programs": C.TELEMATICS_PROGRAMS,
           "eligible": bool(vehicles)}
    if t.get("enrolled"):
        trips = t.get("trips", [])
        out.update({"program": t["program"], "program_name": C.TELEMATICS_PROGRAMS[t["program"]]["name"], "device": t.get("device"),
                    "vehicle_id": t.get("vehicle_id"), "score": t.get("score"), "factors": t.get("factors"),
                    "discount_earned_pct": C.drive_discount_pct(t.get("score")) if t["program"] == "safe-driver" else 0,
                    "discount_applied": bool(t.get("redeemed")), "miles_month": t.get("miles_month", 0), "miles_term": t.get("miles_term", 0),
                    "trips_count": len(trips), "recent_trips": trips[-5:],
                    "weakest_factor": min(t["factors"], key=t["factors"].get) if t.get("factors") else None})
        if t["program"] == "pay-per-mile":
            prog = C.TELEMATICS_PROGRAMS["pay-per-mile"]
            out["month_cost_usd"] = round(prog["base_usd_month"] + t.get("miles_month", 0) * prog["cents_per_mile"] / 100, 2)
    return out


async def telehealth_days() -> list[dict]:
    inv, _ = await get_inventory()
    days: dict[str, list] = {}
    for sid, left in sorted(inv["slots"].items()):
        date, time = sid.split("T")
        if (days_until(date) or 0) >= 1:
            days.setdefault(date, []).append({"time": time, "open": left})
    return [{"date": d, "slots": s} for d, s in list(days.items())[:5]]


async def get_wellness_summary(user_id: str) -> dict:
    p = await load_profile(user_id)
    require_member(p)
    w = p.get("wellness") or {}
    health = next(iter(active_policies(p, "health")), None)
    pet = next(iter(active_policies(p, "pet")), None)
    out = {"user_id": user_id, "has_health": bool(health), "has_pet": bool(pet), "deductible": w.get("deductible"),
           "telehealth": {**(w.get("telehealth") or {}), "days": await telehealth_days(), "types": C.TELEHEALTH_TYPES},
           "wearable": w.get("wearable"), "vet_bills": (w.get("vet_bills") or [])[-5:]}
    if health:
        plan = C.HEALTH_PLAN_BY_ID[health["plan_id"]]
        out["health_plan"] = {**plan, "policy_id": health["policy_id"]}
    if pet:
        plan = C.PET_PLAN_BY_ID[pet["plan_id"]]
        used = pet.get("usage") or {}
        out["pet_plan"] = {**plan, "policy_id": pet["policy_id"], "pets": pet.get("pets", []), "routine_care": bool(pet.get("routine_care")),
                           "deductible_left_usd": max(0, plan["annual_deductible"] - used.get("deductible_met_usd", 0)),
                           "limit_left_usd": plan["annual_limit"] - used.get("paid_usd", 0)}
    return out


def coverage_products(p: dict) -> list[dict]:
    """Every on-demand product with a quote sized to what this person is planning."""
    plans = (p.get("on_demand") or {}).get("plans") or {}
    products = []
    for prod in C.ON_DEMAND:
        days, cost = 1, 0
        if prod["id"] == "travel" and plans.get("trip"):
            t = plans["trip"]
            days = max(1, (dt.date.fromisoformat(t["return"]) - dt.date.fromisoformat(t["depart"])).days + 1)
            cost = t.get("trip_cost_usd", 0)
        elif prod["id"] in ("borrow-car", "rental-car") and plans.get("drive"):
            days = int(plans["drive"].get("days", 1))
        products.append({**prod, "quote": C.on_demand_quote(prod["id"], days, cost)})
    return products


async def get_coverage_options(user_id: str) -> dict:
    p = await load_profile(user_id)
    od = p.get("on_demand") or {}
    covs = od.get("coverages", [])
    return {"user_id": user_id, "products": coverage_products(p), "plans": od.get("plans") or {},
            "active": active_on_demand(p), "upcoming": [c for c in covs if c["start"] > today().isoformat()],
            "past": [c for c in covs if c["end"] < today().isoformat()][-3:],
            "has_annual_auto": bool(active_policies(p, "auto"))}


# --------------------------------------------------------------------------
# documents and support
# --------------------------------------------------------------------------
async def request_document(user_id: str, policy_id: str, doc_type: str, delivery: str = "app", recipient: str = "") -> dict:
    p = await load_profile(user_id)
    pol = _policy(p, policy_id)
    d = C.DOC_TYPE_BY_ID.get(doc_type)
    if not d or pol["line"] not in d["lines"]:
        raise ToolError(f"Documents for {C.a_or_an(pol['line'])} policy: {', '.join(x['id'] for x in C.DOC_TYPES if pol['line'] in x['lines'])}")
    if delivery not in C.DOC_DELIVERY:
        raise ToolError(f"Delivery: {', '.join(C.DOC_DELIVERY)}")
    if doc_type == "lender_letter" and len(recipient.strip()) < 3:
        raise ToolError("Who is the letter for? Give the lender's or landlord's name")
    ready = d["instant"] and delivery != "mail"
    doc = {"doc_id": _ref("DOC"), "type": doc_type, "title": d["name"] + (f" for {recipient.strip()[:60]}" if recipient.strip() else ""),
           "issued": today().isoformat(), "status": "ready" if ready else "requested", "delivery": delivery,
           "ready_by": None if ready else (today() + dt.timedelta(days=5 if delivery == "mail" else 1)).isoformat()}
    pol.setdefault("documents", []).append(doc)
    await save_profile(p)
    item = _item("document", f"{d['name']} · {pol['policy_id']}", policy_id=pol["policy_id"], doc_id=doc["doc_id"],
                 status="confirmed" if ready else "submitted")
    await record_activity(user_id, item)
    await after_change(user_id)
    where = {"app": "It's in ID Cards & Documents now, and saved on your phone for offline use.",
             "email": f"It's in the app now and a PDF is on its way to {p.get('email')}.",
             "mail": f"A printed copy goes to {p.get('address') or 'your address on file'} and arrives in about 5 days."}[delivery]
    return {"ok": True, "status": "confirmed" if ready else "submitted", "item": item,
            "summary": (f"Your {d['name'].lower()} for {pol['policy_id']} is ready. {where}" if ready else
                        f"Requested: {doc['title']} for {pol['policy_id']}. " + (where if delivery == "mail" else
                        f"We prepare these by hand - it will be in your documents by {nice_date(doc['ready_by'])}."))}


async def update_contact_details(user_id: str, email: str = "", phone: str = "", address: str = "") -> dict:
    p = await load_profile(user_id)
    changed = []
    if email.strip():
        if "@" not in email or "." not in email.split("@")[-1]:
            raise ToolError("That email address doesn't look right")
        p["email"] = email.strip()[:120]
        changed.append("email")
    if phone.strip():
        if sum(ch.isdigit() for ch in phone) < 7:
            raise ToolError("That phone number doesn't look right")
        p["phone"] = phone.strip()[:30]
        changed.append("phone")
    if address.strip():
        if len(address.strip()) < 8:
            raise ToolError("Give the full street address, city and ZIP")
        p["address"] = address.strip()[:200]
        changed.append("address")
    if not changed:
        raise ToolError("Tell me what to update: email, phone or address")
    await save_profile(p)
    item = _item("details", "Contact details updated · " + ", ".join(changed), fields=changed)
    await record_activity(user_id, item)
    await after_change(user_id)
    rated = "address" in changed and bool(active_policies(p, "auto", "home", "renters"))
    return {"ok": True, "status": "confirmed", "item": item,
            "summary": f"Updated your {' and '.join(changed)}, {_first(p)}." + (" A new address can change your rate, so we'll confirm your premium "
                       "by email within a day; your cover continues unchanged meanwhile." if rated else " Your documents will show the change from tonight.")}


async def _policy_change(user_id: str, policy_id: str, change: str, details: str, underwriting: bool) -> dict:
    if not details or len(details.strip()) < 5:
        raise ToolError("Describe the change in a sentence, for the record")
    p = await load_profile(user_id)
    pol = _policy(p, policy_id)
    ch = C.POLICY_CHANGE_BY_ID.get(change)
    if not ch or pol["line"] not in ch["lines"]:
        raise ToolError(f"Changes for {C.a_or_an(pol['line'])} policy: {', '.join(c['id'] for c in C.POLICY_CHANGES if pol['line'] in c['lines'])}")
    if ch["approval"] != underwriting:
        raise ToolError(f"{ch['name']} " + ("changes your coverage or price, so it goes through a coverage change request reviewed by underwriting"
                                           if ch["approval"] else "is a simple update - send it as a policy change request"))
    rec = {"request_id": _ref("CHG"), "kind": "policy_change", "policy_id": pol["policy_id"], "change": change, "name": ch["name"],
           "details": details.strip()[:300], "status": "done", "underwriting": underwriting, "at": today().isoformat(),
           "effective": (today() + dt.timedelta(days=1)).isoformat()}
    p.setdefault("support", {}).setdefault("requests", []).append(rec)
    pol.setdefault("endorsements", []).append({"change": change, "details": rec["details"], "effective": rec["effective"]})
    await save_profile(p)
    item = _item("change", f"{ch['name']} · {pol['policy_id']}", policy_id=pol["policy_id"], change=change, underwriting=underwriting)
    await record_activity(user_id, item)
    await after_change(user_id)
    return {"ok": True, "status": "confirmed", "item": item,
            "summary": f"{ch['name']} is applied to {pol['policy_id']}, effective {nice_date(rec['effective'])}. "
                       + ("Updated declarations and ID cards are in your documents; any change in premium shows on your next bill. " if underwriting
                          else "Your documents are updated. ") + f"Recorded: {rec['details'][:120]}"}


async def request_policy_change(user_id: str, policy_id: str, change: str, details: str) -> dict:
    """Simple updates that don't change coverage or price: applied straight away."""
    return await _policy_change(user_id, policy_id, change, details, underwriting=False)


async def request_coverage_change(user_id: str, policy_id: str, change: str, details: str) -> dict:
    """Changes to who or what is covered, limits and deductibles. Held for an
    underwriter's decision in AOM's approval tier before it can run."""
    return await _policy_change(user_id, policy_id, change, details, underwriting=True)


async def request_live_agent(user_id: str, topic: str, channel: str = "chat", note: str = "") -> dict:
    p = await load_profile(user_id)
    if channel not in C.AGENT_CHANNELS:
        raise ToolError(f"Choose one of: {', '.join(C.AGENT_CHANNELS)}")
    if not topic or len(topic.strip()) < 3:
        raise ToolError("What should the agent help with?")
    sup = p.setdefault("support", {})
    if any(r.get("kind") == "live_agent" and r.get("status") == "waiting" for r in sup.get("requests", [])):
        raise ToolError("You're already in the queue for a licensed agent - they'll reach you shortly")
    agent = C.LICENSED_AGENTS[C._h(user_id, topic) % len(C.LICENSED_AGENTS)]
    wait = 2 + C._h(user_id, p.get("rev", 0)) % 6
    rec = {"request_id": _ref("AGT"), "kind": "live_agent", "topic": topic.strip()[:80], "channel": channel, "note": note.strip()[:300],
           "agent": agent, "wait_minutes": wait, "status": "waiting", "at": now_iso()}
    sup.setdefault("requests", []).append(rec)
    await save_profile(p)
    item = _item("agent", f"Licensed agent · {rec['topic']}", status="submitted", channel=channel, agent=agent)
    await record_activity(user_id, item)
    await after_change(user_id)
    how = {"chat": "joins this chat", "callback": f"calls {p.get('phone') or 'the number on your account'}", "video": "sends a video link"}[channel]
    return {"ok": True, "status": "submitted", "item": item,
            "summary": f"{agent}, a licensed agent, {how} in about {wait} minutes. They can see this conversation and your policies, "
                       "so you won't have to repeat yourself."}


# --------------------------------------------------------------------------
# claims
# --------------------------------------------------------------------------
async def file_claim(user_id: str, policy_id: str, loss_type: str, loss_date: str, description: str, location: str = "",
                     photos: int = 0, videos: int = 0, police_report: bool = False, drivable: bool = True) -> dict:
    p = await load_profile(user_id)
    pol = _policy(p, policy_id, "auto", "home", "renters")
    if pol.get("status") != "active":
        raise ToolError(f"{pol['policy_id']} isn't active")
    kinds = dict(C.LOSS_TYPES[pol["line"]])
    if loss_type not in kinds:
        raise ToolError(f"What happened? One of: {', '.join(kinds)}")
    when = _date(loss_date, "The date it happened")
    if when > today():
        raise ToolError("The date it happened can't be in the future")
    if when.isoformat() < pol["effective"]:
        raise ToolError(f"{pol['policy_id']} started on {nice_date(pol['effective'])}, after this happened")
    if not description or len(description.strip()) < 10:
        raise ToolError("Describe what happened in a sentence or two")
    if any(c["policy_id"] == pol["policy_id"] and c["loss_type"] == loss_type and c["loss_date"] == when.isoformat()
           and claim_view(c)["open"] for c in p.get("claims", [])):
        raise ToolError("A claim for this is already open - add your photos to it instead")
    cid = f"CLM-{500000 + C._h(user_id, loss_type, when, p.get('rev', 0)) % 400000}"
    adjuster = C.ADJUSTERS[C._h(cid) % len(C.ADJUSTERS)]
    evidence = []
    if int(photos) > 0:
        evidence.append({"kind": "photo", "count": int(photos), "at": now_iso()})
    if int(videos) > 0:
        evidence.append({"kind": "video", "count": int(videos), "at": now_iso()})
    if police_report:
        evidence.append({"kind": "police_report", "count": 1, "at": now_iso()})
    fast = pol["line"] == "auto" and loss_type == "glass" and int(photos) >= 2
    status = "under_review" if evidence else "submitted"
    claim = {"claim_id": cid, "policy_id": pol["policy_id"], "line": pol["line"], "loss_type": loss_type, "loss_date": when.isoformat(),
             "filed_at": today().isoformat(), "status": status, "description": description.strip()[:500], "location": location.strip()[:160],
             "adjuster": adjuster, "deductible_usd": 0 if fast else pol.get("deductible_usd", 500), "estimate_usd": None, "payout_usd": None,
             "drivable": bool(drivable), "fast_track": fast, "evidence": evidence,
             "events": [{"at": today().isoformat(), "text": "Claim filed in the Harborline app"},
                        {"at": today().isoformat(), "text": f"Assigned to {adjuster}"}]}
    if evidence:
        claim["events"].append({"at": today().isoformat(), "text": "Photos received - review started"})
    p.setdefault("claims", []).append(claim)
    p.setdefault("history", {})["claims_count"] = int((p.get("history") or {}).get("claims_count", 0)) + 1
    await save_profile(p)
    item = _item("claim", f"Claim {cid} · {kinds[loss_type]}", claim_id=cid, policy_id=pol["policy_id"], loss_type=loss_type, photos=int(photos))
    await record_activity(user_id, item)
    await after_change(user_id)
    return {"ok": True, "status": "confirmed", "item": item, "claim_id": cid,
            "summary": f"Claim {cid} is filed on {pol['policy_id']} ({kinds[loss_type].lower()}, {nice_date(when.isoformat())}). {adjuster} is your adjuster"
                       + (" and has your photos already" if int(photos) else "; add photos of the damage to speed things up")
                       + (". Glass claims have no deductible and are usually approved the same day." if fast else
                          f". Your deductible is {money(claim['deductible_usd'])}; you can follow every step under Claims.")
                       + ("" if drivable or pol["line"] != "auto" else " Since the car isn't drivable, request a tow from Roadside and we'll take it to a partner shop.")}


async def add_claim_evidence(user_id: str, claim_id: str, kind: str = "photo", count: int = 1, note: str = "") -> dict:
    p = await load_profile(user_id)
    c = next((c for c in p.get("claims", []) if c["claim_id"] == claim_id), None)
    if not c:
        raise ToolError(f"I can't find claim {claim_id} on this account")
    if not claim_view(c)["open"]:
        raise ToolError(f"Claim {claim_id} is {C.CLAIM_STEP_LABEL.get(c['status'], c['status']).lower()} - call your adjuster to add a supplement")
    if kind not in C.EVIDENCE_KINDS:
        raise ToolError(f"You can add: {', '.join(C.EVIDENCE_KINDS)}")
    n = max(1, min(int(count), 30))
    c.setdefault("evidence", []).append({"kind": kind, "count": n, "note": note.strip()[:200], "at": now_iso()})
    label = kind.replace("_", " ")
    c["events"].append({"at": today().isoformat(), "text": f"{n} {label}{'s' if n > 1 else ''} added from the app"})
    if c["status"] == "submitted":
        c["status"] = "under_review"
        c["events"].append({"at": today().isoformat(), "text": "Review started"})
    await save_profile(p)
    item = _item("evidence", f"{n} {label}{'s' if n > 1 else ''} added · {claim_id}", claim_id=claim_id, evidence_kind=kind, count=n)
    await record_activity(user_id, item)
    await after_change(user_id)
    return {"ok": True, "status": "confirmed", "item": item, "claim_id": claim_id,
            "summary": f"Added {n} {label}{'s' if n > 1 else ''} to claim {claim_id}. {c['adjuster']} is notified; the claim is "
                       f"{C.CLAIM_STEP_LABEL[c['status']].lower()}."}


# --------------------------------------------------------------------------
# roadside and emergency
# --------------------------------------------------------------------------
def _place(p: dict, location: str, lat: float, lon: float) -> dict:
    last = (p.get("roadside") or {}).get("last_location") or {}
    has_gps = bool(lat or lon)
    return {"label": location.strip()[:160] or (f"GPS {float(lat):.4f}, {float(lon):.4f}" if has_gps else last.get("label") or p.get("home_city")),
            "lat": round(float(lat), 5) if has_gps else last.get("lat"), "lon": round(float(lon), 5) if has_gps else last.get("lon"),
            "source": "gps" if has_gps else "typed" if location.strip() else "last known"}


async def request_roadside(user_id: str, service: str, vehicle_id: str = "", location: str = "", lat: float = 0.0, lon: float = 0.0,
                           note: str = "") -> dict:
    p = await load_profile(user_id)
    svc = C.ROADSIDE_BY_ID.get(service)
    if not svc:
        raise ToolError(f"Roadside services: {', '.join(s['id'] for s in C.ROADSIDE_SERVICES)}")
    rs = p.setdefault("roadside", {"uses_this_term": 0, "dispatches": []})
    if any(d["status"] in ("dispatched", "en_route", "on_scene") for d in rs.get("dispatches", [])):
        raise ToolError("Help is already on the way - open Roadside to follow the truck")
    plan = roadside_plan(p)
    vehicles = _vehicles(p)
    v = next((x for x in vehicles if x["vehicle_id"] == vehicle_id), vehicles[0] if vehicles and not vehicle_id else None)
    if vehicle_id and not v:
        raise ToolError(f"{vehicle_id} isn't a vehicle on your policy")
    place = _place(p, location, lat, lon)
    if not place["label"]:
        raise ToolError("Where are you? Share your location or type the nearest address")
    did = f"RSA-{700000 + C._h(user_id, service, p.get('rev', 0)) % 200000}"
    eta = svc["eta_min"] + C._h(did) % 12 - 4
    d = {"dispatch_id": did, "service": service, "service_name": svc["name"], "status": "dispatched", "eta_minutes": eta,
         "provider": C.ROADSIDE_PROVIDERS[C._h(did, "p") % len(C.ROADSIDE_PROVIDERS)], "vehicle_id": (v or {}).get("vehicle_id"),
         "vehicle": vehicle_name(v) if v else (note.strip()[:60] or "your vehicle"), "location": place, "note": note.strip()[:200],
         "requested_at": now_iso(), "covered_by": plan["plan"], "cost_usd": plan["cost_usd"]}
    rs.setdefault("dispatches", []).append(d)
    rs["last_location"] = {k: place[k] for k in ("label", "lat", "lon")}
    if plan["plan"] == "included":
        rs["uses_this_term"] = int(rs.get("uses_this_term", 0)) + 1
    await save_profile(p)
    item = _item("roadside", f"{svc['name']} · {did}", dispatch_id=did, service=service, charge_usd=plan["cost_usd"], time=f"{eta} min")
    await record_activity(user_id, item)
    await after_change(user_id)
    left = (plan["calls_left"] or 1) - 1
    cover = {"included": f"covered by your policy ({left} call{'s' if left != 1 else ''} left this term)",
             "on-demand": "covered by your on-demand cover",
             "pay-per-use": f"{money(plan['cost_usd'])} charged to your card on file, as you have no roadside plan"}[plan["plan"]]
    return {"ok": True, "status": "confirmed", "charge_usd": plan["cost_usd"], "item": item, "dispatch_id": did,
            "summary": f"{d['provider']} is on the way to {place['label']} for a {svc['name'].lower()} - about {eta} minutes. "
                       f"It's {cover}. The driver will text you; stay somewhere safe, away from traffic."}


async def send_sos(user_id: str, kind: str, location: str = "", lat: float = 0.0, lon: float = 0.0, note: str = "") -> dict:
    p = await load_profile(user_id)
    k = C.SOS_BY_ID.get(kind)
    if not k:
        raise ToolError(f"Emergency type: {', '.join(s['id'] for s in C.SOS_KINDS)}")
    place = _place(p, location, lat, lon)
    rec = {"sos_id": _ref("SOS"), "kind": kind, "location": place, "note": note.strip()[:300], "at": now_iso(), "status": "open",
           "callback_minutes": 2}
    p.setdefault("emergencies", []).append(rec)
    if place.get("lat"):
        p.setdefault("roadside", {"uses_this_term": 0, "dispatches": []})["last_location"] = {x: place[x] for x in ("label", "lat", "lon")}
    await save_profile(p)
    item = _item("sos", f"SOS · {k['name']}", sos_id=rec["sos_id"], sos_kind=kind, status="submitted")
    await record_activity(user_id, item)
    await after_change(user_id)
    extra = {"accident": " If the car can't be driven, I can send a tow and start your claim from here.",
             "medical": " If anyone's life is at risk, call 911 now.",
             "travel": " Keep your passport and booking details to hand."}[kind]
    return {"ok": True, "status": "submitted", "item": item, "sos_id": rec["sos_id"],
            "summary": f"Your location ({place['label'] or 'not shared'}) is with our 24/7 emergency desk and someone will call "
                       f"{p.get('phone') or 'you'} within 2 minutes.{extra}"}


# --------------------------------------------------------------------------
# payments and renewals
# --------------------------------------------------------------------------
async def make_payment(user_id: str, policy_id: str = "", amount_usd: float = 0, method: str = "card on file") -> dict:
    p = await load_profile(user_id)
    if not policy_id:
        owing = sorted([x for x in active_policies(p) if amount_due(x) > 0], key=lambda x: x["billing"].get("next_due") or "")
        if not owing:
            raise ToolError("Nothing is due right now. Tell me the policy if you'd like to pay ahead")
        pol = owing[0]
    else:
        pol = _policy(p, policy_id)
    if method not in C.PAYMENT_METHODS:
        raise ToolError(f"Pay with: {', '.join(C.PAYMENT_METHODS)}")
    b = pol["billing"]
    due = amount_due(pol)
    amount = round(float(amount_usd), 2) if float(amount_usd or 0) > 0 else (due or float(b["installment_usd"]))
    ceiling = max(due, float(b["installment_usd"]))
    if amount < 1 or amount > ceiling + 0.005:
        raise ToolError(f"You can pay between $1 and {money(ceiling)} on {pol['policy_id']}")
    was_due = due > 0
    fee = min(float(b.get("late_fee_usd") or 0), amount)
    b["late_fee_usd"] = round(float(b.get("late_fee_usd") or 0) - fee, 2)
    b["balance_due_usd"] = round(max(0.0, float(b.get("balance_due_usd") or 0) - (amount - fee)), 2)
    if b["balance_due_usd"] <= 0 and b["late_fee_usd"] <= 0:
        b["past_due"] = False
        # the bill that was due (or the next one, paid ahead) is settled: move to the following month
        if b["plan"] == "monthly" and b.get("next_due") and (was_due or amount >= float(b["installment_usd"]) - 0.005):
            b["next_due"] = add_months(dt.date.fromisoformat(b["next_due"]), 1).isoformat()
    pay = {"payment_id": _ref("PAY"), "policy_id": pol["policy_id"], "amount_usd": amount, "at": today().isoformat(), "method": method,
           "status": "posted"}
    p.setdefault("payments", []).append(pay)
    await save_profile(p)
    item = _item("payment", f"Payment · {pol['policy_id']}", policy_id=pol["policy_id"], charge_usd=amount, payment_id=pay["payment_id"])
    await record_activity(user_id, item)
    await after_change(user_id)
    left = amount_due(pol)
    return {"ok": True, "status": "confirmed", "charge_usd": amount, "item": item,
            "summary": f"{money(amount)} paid on {pol['policy_id']} from your {method} (confirmation {pay['payment_id']}). "
                       + (f"{money(left)} is still due." if left > 0 else
                          f"You're paid up; the next payment of {money(b['installment_usd'])} is due {nice_date(b['next_due'])}." if b["plan"] == "monthly" and b.get("next_due")
                          else "You're paid up for this term.")
                       + ("" if b.get("autopay") or b["plan"] != "monthly" else f" Turn on AutoPay to save {money(C.AUTOPAY_DISCOUNT_USD)} a month.")}


def _th(n: int) -> str:
    return "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


async def set_autopay(user_id: str, policy_id: str = "", enabled: bool = True, day: int = 0) -> dict:
    p = await load_profile(user_id)
    if policy_id:
        pol = _policy(p, policy_id)
    else:
        pol = next((x for x in active_policies(p) if x["billing"]["plan"] == "monthly" and bool(x["billing"].get("autopay")) != bool(enabled)), None)
        if not pol:
            raise ToolError(f"AutoPay is already {'on' if enabled else 'off'} for every monthly policy")
    b = pol["billing"]
    if b["plan"] != "monthly":
        raise ToolError(f"{pol['policy_id']} is paid in full for the term, so there are no monthly payments to automate")
    if bool(b.get("autopay")) == bool(enabled):
        raise ToolError(f"AutoPay is already {'on' if enabled else 'off'} for {pol['policy_id']}")
    if enabled and b.get("past_due") and amount_due(pol) > 0:
        raise ToolError(f"Pay the {money(amount_due(pol))} that's past due first, then AutoPay can take over")
    if int(day or 0) and not 1 <= int(day) <= 28:
        raise ToolError("Pick a day of the month from 1 to 28")
    b["autopay"] = bool(enabled)
    if enabled:
        b["autopay_day"] = int(day) or (min(28, dt.date.fromisoformat(b["next_due"]).day) if b.get("next_due") else 1)
        b["installment_usd"] = round(float(b["installment_usd"]) - C.AUTOPAY_DISCOUNT_USD, 2)
    else:
        b["autopay_day"] = None
        b["installment_usd"] = round(float(b["installment_usd"]) + C.AUTOPAY_DISCOUNT_USD, 2)
    await save_profile(p)
    item = _item("autopay", f"AutoPay {'on' if enabled else 'off'} · {pol['policy_id']}", policy_id=pol["policy_id"], enabled=bool(enabled))
    await record_activity(user_id, item)
    await after_change(user_id)
    m = b.get("method") or {}
    return {"ok": True, "status": "confirmed", "item": item,
            "summary": (f"AutoPay is on for {pol['policy_id']}: {money(b['installment_usd'])} on the {b['autopay_day']}{_th(b['autopay_day'])} of each month "
                        f"from your {m.get('type', 'card')} ending {m.get('last4', '')}. That includes the "
                        f"{money(C.AUTOPAY_DISCOUNT_USD)} AutoPay discount; we'll remind you 3 days before each payment." if enabled else
                        f"AutoPay is off for {pol['policy_id']}. Your payment goes back to {money(b['installment_usd'])} and is due {nice_date(b.get('next_due'))}.")}


async def renew_policy(user_id: str, policy_id: str = "", pay_plan: str = "monthly") -> dict:
    p = await load_profile(user_id)
    if not policy_id:
        offered = [x for x in active_policies(p) if (x.get("renewal") or {}).get("status") == "offered"]
        if not offered:
            raise ToolError("None of your policies has a renewal offer yet - offers arrive about 30 days before the term ends")
        pol = sorted(offered, key=lambda x: x["expires"])[0]
    else:
        pol = _policy(p, policy_id)
    r = pol.get("renewal") or {}
    if r.get("status") == "renewed":
        raise ToolError(f"{pol['policy_id']} is already renewed through {nice_date(r.get('new_expires'))}")
    if r.get("status") != "offered":
        raise ToolError(f"{pol['policy_id']} has no renewal offer yet - it arrives about 30 days before {nice_date(pol['expires'])}")
    if pay_plan not in C.PAY_PLANS:
        raise ToolError(f"Payment plan: {', '.join(C.PAY_PLANS)}")
    if pol["billing"].get("past_due") and amount_due(pol) > 0:
        raise ToolError(f"{money(amount_due(pol))} is past due on {pol['policy_id']} - pay that first and then renew")
    months = C.LINES[pol["line"]]["term_months"]
    premium = float(r["offer_premium_usd"])
    charge = 0.0
    if pay_plan == "pay_in_full":
        premium = round(premium * (1 - C.PAY_IN_FULL_DISCOUNT_PCT / 100), 2)
        charge = premium
    start = dt.date.fromisoformat(pol["expires"])
    r.update(status="renewed", pay_plan=pay_plan, final_premium_usd=premium, renewed_at=today().isoformat(),
             new_effective=start.isoformat(), new_expires=add_months(start, months).isoformat(),
             installment_usd=None if pay_plan == "pay_in_full" else round(premium / months, 2))
    pol["renewal"] = r
    p["ml_scores"]["next_best_action"] = "none"
    if charge:
        p.setdefault("payments", []).append({"payment_id": _ref("PAY"), "policy_id": pol["policy_id"], "amount_usd": charge,
                                             "at": today().isoformat(), "method": "card on file", "status": "posted", "for": "renewal"})
    await save_profile(p)
    item = _item("renewal", f"Renewed · {pol['policy_id']}", policy_id=pol["policy_id"], charge_usd=charge or None, date=r["new_effective"])
    await record_activity(user_id, item)
    await after_change(user_id)
    return {"ok": True, "status": "confirmed", "charge_usd": charge, "item": item,
            "summary": f"{pol['policy_id']} is renewed from {nice_date(r['new_effective'])} to {nice_date(r['new_expires'])} at {money(premium)} for the term"
                       + (f" - {money(charge)} paid in full today, saving {C.PAY_IN_FULL_DISCOUNT_PCT}%." if charge else
                          f", {money(r['installment_usd'])} a month.")
                       + (f" Your {r['drive_discount_pct']}% DriveWell discount is included." if r.get("drive_discount_pct") else "")
                       + " New ID cards are in your documents on the renewal date."}


async def request_fee_waiver(user_id: str, policy_id: str, reason: str) -> dict:
    """Waive a late fee as a goodwill gesture. Held for a billing supervisor's
    decision in AOM's approval tier before it can run."""
    if not reason or len(reason.strip()) < 5:
        raise ToolError("A fee waiver needs a reason for the audit trail")
    p = await load_profile(user_id)
    pol = _policy(p, policy_id)
    b = pol["billing"]
    fee = float(b.get("late_fee_usd") or 0)
    if fee <= 0:
        raise ToolError(f"There's no late fee on {pol['policy_id']} to waive")
    if fee > C.FEE_WAIVER_MAX_USD:
        raise ToolError(f"Fees over {money(C.FEE_WAIVER_MAX_USD)} need a call with billing: {C.COMPANY['support_phone']}")
    if any(w["policy_id"] == pol["policy_id"] and (days_until(w["at"]) or 0) > -365 for w in p.get("fee_waivers", [])):
        raise ToolError("A late fee was already waived on this policy in the last 12 months")
    b["late_fee_usd"] = 0
    p.setdefault("fee_waivers", []).append({"waiver_id": _ref("WVR"), "policy_id": pol["policy_id"], "amount_usd": fee,
                                            "reason": reason.strip()[:300], "at": today().isoformat()})
    await save_profile(p)
    item = _item("waiver", f"Late fee waived · {money(fee)}", policy_id=pol["policy_id"], amount_usd=fee, reason=reason.strip()[:300])
    await record_activity(user_id, item)
    await after_change(user_id)
    return {"ok": True, "status": "confirmed", "charge_usd": 0, "item": item,
            "summary": f"The {money(fee)} late fee on {pol['policy_id']} is waived. " + (f"{money(amount_due(pol))} is still due to stay covered. " if amount_due(pol) > 0 else "")
                       + f"Reason recorded: {reason.strip()[:120]}"}


# --------------------------------------------------------------------------
# telematics
# --------------------------------------------------------------------------
async def enroll_telematics(user_id: str, vehicle_id: str = "", program: str = "safe-driver", device: str = "phone") -> dict:
    p = await load_profile(user_id)
    vehicles = _vehicles(p)
    if not vehicles:
        raise ToolError(f"{C.COMPANY['telematics_program']} needs a Harborline Auto policy")
    if program not in C.TELEMATICS_PROGRAMS:
        raise ToolError(f"Programs: {', '.join(C.TELEMATICS_PROGRAMS)}")
    if device not in C.TELEMATICS_DEVICES:
        raise ToolError(f"Track with: {', '.join(C.TELEMATICS_DEVICES)}")
    t = p.get("telematics") or {}
    if t.get("enrolled") and t.get("program") == program:
        raise ToolError(f"You're already in {C.TELEMATICS_PROGRAMS[program]['name']}")
    v = next((x for x in vehicles if x["vehicle_id"] == vehicle_id), vehicles[0] if not vehicle_id else None)
    if not v:
        raise ToolError(f"{vehicle_id} isn't a vehicle on your policy")
    prog = C.TELEMATICS_PROGRAMS[program]
    p["telematics"] = {"enrolled": True, "program": program, "vehicle_id": v["vehicle_id"], "device": device, "enrolled_at": today().isoformat(),
                       "score": t.get("score"), "factors": t.get("factors") or {f: 100 for f in C.DRIVE_FACTORS},
                       "miles_month": t.get("miles_month", 0), "miles_term": t.get("miles_term", 0), "trips": t.get("trips", []), "redeemed": False}
    p["ml_scores"]["next_best_action"] = "drive_safely"
    await save_profile(p)
    item = _item("telematics", f"{prog['name']} · {vehicle_name(v)}", program=program, vehicle_id=v["vehicle_id"])
    await record_activity(user_id, item)
    await after_change(user_id)
    return {"ok": True, "status": "confirmed", "item": item,
            "summary": f"You're in {prog['name']} with your {vehicle_name(v)}, tracked by {device}. "
                       + (f"{prog['enroll_discount_pct']}% comes off your next bill for joining; after your first trips your score sets a renewal discount of up to "
                          f"{prog['max_discount_pct']}%." if program == "safe-driver" else
                          f"From your next bill you pay {money(prog['base_usd_month'])} a month plus {prog['cents_per_mile']} cents a mile.")
                       + " Trips are recorded on your phone, even with no signal, and sync when you're connected."}


async def record_trip(user_id: str, miles: float, minutes: int, hard_brakes: int = 0, speeding_events: int = 0, night: bool = False,
                      phone_use: int = 0, trip_date: str = "") -> dict:
    """A trip summary from the phone's sensors or the plug-in beacon."""
    p = await load_profile(user_id)
    t = p.get("telematics") or {}
    if not t.get("enrolled"):
        raise ToolError(f"Join {C.COMPANY['telematics_program']} first - trips are only recorded once you're enrolled")
    miles = round(float(miles), 1)
    if not 0.1 <= miles <= 1500 or not 1 <= int(minutes) <= 1440:
        raise ToolError("That doesn't look like a trip: check the miles and minutes")
    when = _date(trip_date, "Trip date") if trip_date else today()
    if when > today():
        raise ToolError("A trip can't be in the future")
    score = C.trip_score(miles, int(hard_brakes), int(speeding_events), bool(night), int(phone_use))
    trip = {"trip_id": f"TRP-{uuid.uuid4().hex[:8].upper()}", "date": when.isoformat(), "miles": miles, "minutes": int(minutes),
            "hard_brakes": int(hard_brakes), "speeding": int(speeding_events), "night": bool(night), "phone_use": int(phone_use), "score": score}
    trips = (t.get("trips", []) + [trip])[-30:]
    before = t.get("score")
    total = sum(x["miles"] for x in trips) or 1
    t.update(trips=trips, score=int(round(sum(x["score"] * x["miles"] for x in trips) / total)),
             miles_month=round(float(t.get("miles_month", 0)) + miles, 1), miles_term=round(float(t.get("miles_term", 0)) + miles, 1))
    per100 = 100 / total
    t["factors"] = {"braking": int(max(40, 100 - sum(x["hard_brakes"] for x in trips) * per100 * 4)),
                    "speed": int(max(40, 100 - sum(x["speeding"] for x in trips) * per100 * 4)),
                    "night": int(max(40, 100 - 60 * sum(x["miles"] for x in trips if x["night"]) / total)),
                    "phone": int(max(40, 100 - sum(x["phone_use"] for x in trips) * per100 * 5)),
                    "mileage": int(max(40, 100 - max(0, t["miles_month"] - 700) / 15))}
    p["telematics"] = t
    await save_profile(p)
    item = _item("trip", f"Trip · {miles:g} mi · score {score}", trip_id=trip["trip_id"], miles=miles, score=score, date=when.isoformat())
    await record_activity(user_id, item)
    await after_change(user_id)
    tips = []
    if hard_brakes:
        tips.append(f"{hard_brakes} hard brake{'s' if hard_brakes != 1 else ''}")
    if speeding_events:
        tips.append(f"{speeding_events} speeding event{'s' if speeding_events != 1 else ''}")
    if phone_use:
        tips.append("phone use while moving")
    if night:
        tips.append("late-night driving")
    disc = C.drive_discount_pct(t["score"]) if t["program"] == "safe-driver" else None
    return {"ok": True, "status": "confirmed", "item": item, "trip_score": score, "score": t["score"],
            "summary": f"Trip recorded: {miles:g} miles in {int(minutes)} minutes, score {score}. " + (f"It lost points for {', '.join(tips)}. " if tips else "A clean drive. ")
                       + f"Your DriveWell score is {t['score']}" + (f" (was {before})" if before and before != t["score"] else "")
                       + (f", worth {disc}% off at renewal." if disc is not None else
                          f"; this month is {t['miles_month']:g} miles so far.")}


async def redeem_drive_discount(user_id: str) -> dict:
    p = await load_profile(user_id)
    t = p.get("telematics") or {}
    if not t.get("enrolled") or t.get("program") != "safe-driver":
        raise ToolError("The renewal discount is part of DriveWell Safe Driver - join it to start earning")
    if t.get("redeemed"):
        raise ToolError("Your DriveWell discount is already applied to your renewal")
    if len(t.get("trips", [])) < 5:
        raise ToolError(f"You need at least 5 recorded trips for a score that counts - you have {len(t.get('trips', []))}")
    pct = C.drive_discount_pct(t.get("score"))
    if pct <= 0:
        raise ToolError(f"A score of {t.get('score')} doesn't earn a discount yet - 70 or above does. Your weakest area is "
                        f"{min(t['factors'], key=t['factors'].get)}")
    pol = next((x for x in active_policies(p, "auto") if any(v["vehicle_id"] == t.get("vehicle_id") for v in x.get("vehicles", []))), None)
    r = (pol or {}).get("renewal") or {}
    if not pol or r.get("status") != "offered":
        raise ToolError("The discount is applied to a renewal offer, and yours hasn't arrived yet - it comes about 30 days before the term ends")
    before = float(r["offer_premium_usd"])
    base = float(r.get("base_premium_usd") or before)
    r.update(base_premium_usd=base, offer_premium_usd=round(base * (1 - pct / 100), 2), drive_discount_pct=pct)
    r.setdefault("discounts", []).append(f"DriveWell score {t['score']}: {pct}% off")
    t["redeemed"] = True
    await save_profile(p)
    saved = round(base - r["offer_premium_usd"], 2)
    item = _item("discount", f"DriveWell discount · {pct}% off renewal", policy_id=pol["policy_id"], amount_usd=saved)
    await record_activity(user_id, item)
    await after_change(user_id)
    return {"ok": True, "status": "confirmed", "item": item,
            "summary": f"Your score of {t['score']} earned {pct}% off: the renewal offer on {pol['policy_id']} drops from {money(before)} to "
                       f"{money(r['offer_premium_usd'])}, saving {money(saved)} for the term. Renew whenever you're ready."}


# --------------------------------------------------------------------------
# health and wellness (members)
# --------------------------------------------------------------------------
async def book_telehealth(user_id: str, date: str, time: str, visit_type: str = "primary", reason: str = "") -> dict:
    p = await load_profile(user_id)
    require_member(p)
    vt = C.TELEHEALTH_TYPE_BY_ID.get(visit_type)
    if not vt:
        raise ToolError(f"Visit types: {', '.join(t['id'] for t in C.TELEHEALTH_TYPES)}")
    need = "pet" if visit_type == "vet" else "health"
    pol = next(iter(active_policies(p, need)), None)
    if not pol:
        raise ToolError(f"{vt['name']} visits are included with a Harborline {need.title()} plan, which isn't on this account")
    if time not in C.TELEHEALTH_TIMES:
        raise ToolError(f"Times available: {', '.join(C.TELEHEALTH_TIMES)}")
    w = p.setdefault("wellness", {})
    th = w.setdefault("telehealth", {"visits_used": 0})
    if th.get("upcoming"):
        u = th["upcoming"]
        raise ToolError(f"You already have a visit booked for {nice_date(u['date'])} at {u['time']}")
    inv, _ = await get_inventory()
    sid = C.slot_id(date, time)
    if sid not in inv["slots"] or (days_until(date) or 0) < 1:
        raise ToolError("Pick a day in the next week")
    if inv["slots"][sid] <= 0:
        alts = [t for t in C.TELEHEALTH_TIMES if inv["slots"].get(C.slot_id(date, t), 0) > 0][:3]
        raise ToolError(f"{time} on {date} is fully booked." + (f" Open that day: {', '.join(alts)}" if alts else " Try another day."))
    await take("slots", sid, f"{time} on {date} was just taken - pick another time")
    copay = 0 if need == "pet" else C.HEALTH_PLAN_BY_ID[pol["plan_id"]]["telehealth_copay"]
    provider = C.TELEHEALTH_PROVIDERS[C._h(user_id, sid) % len(C.TELEHEALTH_PROVIDERS)]
    th["upcoming"] = {"visit_id": _ref("TLH"), "date": date, "time": time, "type": visit_type, "type_name": vt["name"],
                      "provider": provider, "reason": reason.strip()[:200], "copay_usd": copay, "booked_at": now_iso()}
    p["ml_scores"]["next_best_action"] = "attend_telehealth"
    await save_profile(p)
    item = _item("telehealth", f"Telehealth · {vt['name']}", date=date, time=time, provider=provider, charge_usd=copay or None)
    await record_activity(user_id, item)
    await after_change(user_id)
    return {"ok": True, "status": "confirmed", "charge_usd": copay, "item": item,
            "summary": f"Booked: {vt['name'].lower()} video visit with {provider} on {nice_date(date)} at {time}. "
                       + (f"Your copay is {money(copay)}." if copay else "There's no copay on your plan.")
                       + " The join link appears here 10 minutes before."}


async def submit_vet_bill(user_id: str, pet_id: str, amount_usd: float, clinic: str, visit_date: str, reason: str, photos: int = 1) -> dict:
    p = await load_profile(user_id)
    require_member(p)
    pol = next(iter(active_policies(p, "pet")), None)
    if not pol:
        raise ToolError("Vet bills are reimbursed by a Harborline Pet plan, which isn't on this account")
    pets = pol.get("pets", [])
    pet = next((x for x in pets if x["pet_id"] == pet_id), pets[0] if len(pets) == 1 and not pet_id else None)
    if not pet:
        raise ToolError(f"Which pet? On your plan: {', '.join(x['name'] + ' (' + x['pet_id'] + ')' for x in pets)}")
    amount = round(float(amount_usd), 2)
    if not 5 <= amount <= 25000:
        raise ToolError("The bill total must be between $5 and $25,000")
    when = _date(visit_date, "Visit date")
    if when > today() or (today() - when).days > 180:
        raise ToolError("Vet bills can be submitted for visits in the last 180 days")
    if int(photos) < 1:
        raise ToolError("Take a photo of the itemized invoice so we can read it")
    if not clinic or len(clinic.strip()) < 3 or not reason or len(reason.strip()) < 3:
        raise ToolError("Give the clinic's name and the reason for the visit")
    w = p.setdefault("wellness", {})
    if any(b["pet_id"] == pet["pet_id"] and b["visit_date"] == when.isoformat() and b["amount_usd"] == amount for b in w.get("vet_bills", [])):
        raise ToolError("This bill has already been submitted")
    m = pet_claim_math(pol, amount, reason.strip())
    auto_ok = amount <= 600 and not m["routine"]
    status = "denied" if m["routine"] else "approved" if auto_ok else "under_review"
    bill = {"bill_id": f"VET-{600000 + C._h(user_id, pet['pet_id'], when, amount) % 300000}", "pet_id": pet["pet_id"], "pet_name": pet["name"],
            "amount_usd": amount, "clinic": clinic.strip()[:80], "visit_date": when.isoformat(), "reason": reason.strip()[:120],
            "photos": int(photos), "submitted_at": today().isoformat(), "status": status, **m,
            "pays_by": (today() + dt.timedelta(days=2)).isoformat() if auto_ok else None}
    if auto_ok:
        pol["usage"]["deductible_met_usd"] = round(pol["usage"]["deductible_met_usd"] + m["deductible_applied_usd"], 2)
        pol["usage"]["paid_usd"] = round(pol["usage"]["paid_usd"] + m["reimbursement_usd"], 2)
    w.setdefault("vet_bills", []).append(bill)
    await save_profile(p)
    item = _item("vetbill", f"Vet bill · {pet['name']} · {money(amount)}", bill_id=bill["bill_id"], refund_usd=m["reimbursement_usd"] if auto_ok else None,
                 status="submitted" if status == "under_review" else "confirmed")
    await record_activity(user_id, item)
    await after_change(user_id)
    if m["routine"]:
        summary = (f"{bill['bill_id']}: {reason.strip()} is routine care, which {pol['product']} only covers with the routine care add-on, "
                   f"so this {money(amount)} bill isn't reimbursed. I can connect you with an agent to add it.")
    elif auto_ok:
        summary = (f"{bill['bill_id']} is approved: {money(m['reimbursement_usd'])} back for {pet['name']}'s visit to {bill['clinic']} "
                   f"({m['pct']}% of {money(amount)}" + (f" after {money(m['deductible_applied_usd'])} of your deductible" if m["deductible_applied_usd"] else "")
                   + f"). It reaches your bank account by {nice_date(bill['pays_by'])}.")
    else:
        summary = (f"{bill['bill_id']} is submitted for {pet['name']}. Bills over $600 are checked by a claims specialist, usually within 2 business days; "
                   f"the estimate is {money(m['reimbursement_usd'])} back.")
    return {"ok": True, "status": "submitted" if status == "under_review" else "confirmed", "item": item, "bill_id": bill["bill_id"], "summary": summary}


async def link_wearable(user_id: str, device: str) -> dict:
    p = await load_profile(user_id)
    require_member(p)
    if not active_policies(p, "health"):
        raise ToolError("Wearable rewards are part of Harborline Health plans")
    if device not in C.WEARABLES:
        raise ToolError(f"Supported devices: {', '.join(C.WEARABLES)}")
    w = p.setdefault("wellness", {})
    cur = w.get("wearable") or {}
    if cur.get("linked") and cur.get("device") == device:
        raise ToolError(f"Your {device} is already linked")
    first = not cur.get("linked")
    points = int(cur.get("points", 0)) + (C.WELLNESS_LINK_BONUS if first else 0)
    w["wearable"] = {"linked": True, "device": device, "linked_at": today().isoformat(), "steps_7d_avg": cur.get("steps_7d_avg", 0),
                     "goal_days_week": cur.get("goal_days_week", 0), "points": points,
                     "reward_usd": round(points / C.WELLNESS_POINTS_PER_DOLLAR, 2)}
    await save_profile(p)
    item = _item("wearable", f"{device} linked", device=device)
    await record_activity(user_id, item)
    await after_change(user_id)
    return {"ok": True, "status": "confirmed", "item": item,
            "summary": f"Your {device} is linked. " + (f"{C.WELLNESS_LINK_BONUS} welcome points are on your account. " if first else "")
                       + f"Every day you reach {C.WELLNESS_STEP_GOAL:,} steps earns {C.WELLNESS_POINTS_PER_GOAL_DAY} points; "
                         f"1,000 points is {money(1000 / C.WELLNESS_POINTS_PER_DOLLAR)} off your premium. We only read steps and active minutes."}


# --------------------------------------------------------------------------
# on-demand coverage
# --------------------------------------------------------------------------
async def activate_coverage(user_id: str, product: str, start_date: str = "", days: int = 1, vehicle: str = "", destination: str = "",
                            trip_cost_usd: float = 0) -> dict:
    p = await load_profile(user_id)
    prod = C.ON_DEMAND_BY_ID.get(product)
    if not prod:
        raise ToolError(f"On-demand products: {', '.join(x['id'] for x in C.ON_DEMAND)}")
    start = _date(start_date, "Start date") if start_date else today()
    if start < today() or (start - today()).days > 180:
        raise ToolError("Cover can start today or any day in the next 6 months")
    days = int(days)
    if not 1 <= days <= prod["max_days"]:
        raise ToolError(f"{prod['name']} runs from 1 to {prod['max_days']} days")
    if "vehicle" in prod["needs"] and len(vehicle.strip()) < 3:
        raise ToolError("Which car? Give the year, make and model (and the plate if you have it)")
    if "destination" in prod["needs"] and len(destination.strip()) < 3:
        raise ToolError("Where are you travelling to?")
    end = start + dt.timedelta(days=days - 1)
    od = p.setdefault("on_demand", {"coverages": []})
    if any(c["product"] == product and c["start"] <= end.isoformat() and start.isoformat() <= c["end"] for c in od.get("coverages", [])):
        raise ToolError(f"You already have {prod['name'].lower()} over those dates")
    q = C.on_demand_quote(product, days, trip_cost_usd)
    cid = f"ODC-{800000 + C._h(user_id, product, start, p.get('rev', 0)) % 100000}"
    cov = {"coverage_id": cid, "product": product, "name": prod["name"], "start": start.isoformat(), "end": end.isoformat(), "days": days,
           "price_usd": q["price_usd"], "status": "active" if start == today() else "scheduled", "covers": prod["covers"],
           "vehicle": vehicle.strip()[:80] or None, "destination": destination.strip()[:80] or None,
           "trip_cost_usd": float(trip_cost_usd) or None, "purchased_at": now_iso(), "roadside": prod["roadside"],
           "certificate": {"doc_id": _ref("DOC"), "type": "coverage_certificate", "title": f"Certificate of coverage · {prod['name']}",
                           "issued": today().isoformat(), "status": "ready"}}
    od.setdefault("coverages", []).append(cov)
    p["ml_scores"]["next_best_action"] = "none"
    p.setdefault("payments", []).append({"payment_id": _ref("PAY"), "policy_id": cid, "amount_usd": q["price_usd"], "at": today().isoformat(),
                                         "method": "card on file", "status": "posted", "for": "on-demand"})
    await save_profile(p)
    item = _item("coverage", f"{prod['name']} · {days} day{'s' if days != 1 else ''}", coverage_id=cid, charge_usd=q["price_usd"], date=start.isoformat())
    await record_activity(user_id, item)
    await after_change(user_id)
    what = f" for the {cov['vehicle']}" if cov["vehicle"] else f" for {cov['destination']}" if cov["destination"] else ""
    return {"ok": True, "status": "confirmed", "charge_usd": q["price_usd"], "item": item, "coverage_id": cid,
            "summary": f"{prod['name']}{what} is {'active now' if start == today() else 'scheduled'}: {nice_date(start.isoformat())}"
                       + (f" to {nice_date(end.isoformat())}" if days > 1 else "") + f", {money(q['price_usd'])} charged to your card on file. "
                       f"Your certificate ({cid}) is in ID Cards & Documents and works offline."
                       + (" Roadside assistance is included while it's active." if prod["roadside"] else "")}


TOOLS = {
    "get_customer_context": get_customer_context,
    "get_policies": get_policies,
    "get_claims": get_claims,
    "get_roadside_status": get_roadside_status,
    "get_billing": get_billing,
    "get_driving_summary": get_driving_summary,
    "get_wellness_summary": get_wellness_summary,
    "get_coverage_options": get_coverage_options,
    "request_document": request_document,
    "update_contact_details": update_contact_details,
    "request_policy_change": request_policy_change,
    "request_coverage_change": request_coverage_change,
    "request_live_agent": request_live_agent,
    "file_claim": file_claim,
    "add_claim_evidence": add_claim_evidence,
    "request_roadside": request_roadside,
    "send_sos": send_sos,
    "make_payment": make_payment,
    "set_autopay": set_autopay,
    "renew_policy": renew_policy,
    "request_fee_waiver": request_fee_waiver,
    "enroll_telematics": enroll_telematics,
    "record_trip": record_trip,
    "redeem_drive_discount": redeem_drive_discount,
    "book_telehealth": book_telehealth,
    "submit_vet_bill": submit_vet_bill,
    "link_wearable": link_wearable,
    "activate_coverage": activate_coverage,
}
READ_ONLY_TOOLS = {"get_customer_context", "get_policies", "get_claims", "get_roadside_status", "get_billing", "get_driving_summary",
                   "get_wellness_summary", "get_coverage_options"}
# Held for a person in AOM's approval tier before they run.
APPROVAL_TOOLS = ["request_coverage_change", "request_fee_waiver"]
