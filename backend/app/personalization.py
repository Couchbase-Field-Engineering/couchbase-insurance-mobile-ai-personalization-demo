"""Ranks the "For You" feed for one person.

Inputs are the scores, segments and policies from the nightly export, plus
live state the export can't know about: what the person has done since (a
claim filed in the app, a payment made, cover switched on for the weekend)
and open telehealth appointments. The result is written to
`feed::<user_id>`, which Sync Gateway replicates to the person's phone - so
the feed renders from Couchbase Lite, even offline, and re-ranks itself on
the next sync after every action.

A card carries everything its screen needs (telehealth slots, on-demand
quotes), so those screens work offline too.
"""
from __future__ import annotations

import datetime as dt

from . import catalog as C
from .docs import days_until, feed_id, money, nice_date, now_iso, profile_id, today, user_channel
from .store import store

PALETTES = {  # gradient keys the app maps to brand gradients
    "payment": "red", "renewal": "ember", "claim": "ink", "idcard": "sand", "drive": "ink", "roadside": "red",
    "telehealth": "ember", "deductible": "sand", "vetbill": "red", "wearable": "ink", "coverage": "ember",
}
AREA_OF = {"payment": "billing", "renewal": "billing", "claim": "claims", "idcard": "documents", "drive": "telematics",
           "roadside": "roadside", "telehealth": "wellness", "deductible": "wellness", "vetbill": "wellness", "wearable": "wellness",
           "coverage": "coverage"}


def _card(kind: str, card_id: str, title: str, subtitle: str, reason: str, badge: str, score: float, cta: dict, **extra) -> dict:
    return {"card_id": card_id, "kind": kind, "palette": PALETTES.get(kind, "ink"), "area": AREA_OF[kind], "title": title,
            "subtitle": subtitle, "reason": reason, "badge": badge, "score": score, "cta": cta, **extra}


def _in(days: int | None) -> str:
    d = days or 0
    return "today" if d == 0 else "tomorrow" if d == 1 else f"in {d} days" if d > 0 else f"{-d} day{'s' if d != -1 else ''} ago"


def _what(pol: dict) -> str:
    if pol.get("vehicles"):
        return f"{pol['vehicles'][0]['make']} {pol['vehicles'][0]['model']}" + (f" +{len(pol['vehicles']) - 1}" if len(pol["vehicles"]) > 1 else "")
    if pol.get("pets"):
        return " & ".join(x["name"] for x in pol["pets"][:2])
    return C.LINES[pol["line"]]["name"]


async def _billing_cards(p: dict, pols: list[dict]) -> list[dict]:
    from .actions import amount_due
    cards = []
    t = p.get("telematics") or {}
    for pol in pols:
        b, r = pol["billing"], pol.get("renewal") or {}
        line = C.LINES[pol["line"]]["name"].lower()
        due = amount_due(pol)
        if b.get("past_due") and due > 0:
            cards.append(_card(
                "payment", f"pay-{pol['policy_id']}", f"Your {line} premium is past due", f"{pol['policy_id']} · {money(due)}" + (f" including a {money(b['late_fee_usd'])} late fee" if b.get("late_fee_usd") else ""),
                f"Due {_in(days_until(b['next_due']))} - pay now to keep {_what(pol)} covered", money(due), 1.3,
                {"label": "Pay now", "screen": "pay", "args": {"policy_id": pol["policy_id"]}}))
        elif due > 0 and (days_until(b.get("next_due")) or 99) <= C.GRACE_DAYS and not b.get("autopay"):
            d = days_until(b["next_due"])
            cards.append(_card(
                "payment", f"pay-{pol['policy_id']}", f"{money(due)} due {_in(d)}", f"{pol['product']} · {pol['policy_id']} · {nice_date(b['next_due'])}",
                f"Turn on AutoPay and save {money(C.AUTOPAY_DISCOUNT_USD)} a month", nice_date(b["next_due"]), 0.88 if (d or 0) <= 5 else 0.7,
                {"label": f"Pay {money(due)}", "tool": "make_payment", "args": {"policy_id": pol["policy_id"]}}))
        if r.get("status") == "offered":
            d = days_until(pol["expires"]) or 0
            earned = (C.drive_discount_pct(t.get("score")) if t.get("enrolled") and t.get("program") == "safe-driver" and not t.get("redeemed")
                      and len(t.get("trips", [])) >= 5 and pol["line"] == "auto" else 0)
            ch = r.get("change_pct") or 0
            cards.append(_card(
                "renewal", f"renew-{pol['policy_id']}", f"Your {line} policy renews {_in(d)}",
                f"{money(r['offer_premium_usd'])} for {C.LINES[pol['line']]['term_months']} months" + (f" ({'+' if ch > 0 else ''}{ch:g}%)" if ch else ""),
                f"Your DriveWell score of {t.get('score')} can take {earned}% off" if earned else "Renew in one tap, monthly or paid in full",
                nice_date(pol["expires"]), 0.92 if d <= 21 else 0.75, {"label": "Review renewal", "screen": "pay", "args": {"policy_id": pol["policy_id"], "renew": "1"}}))
    return cards


def _claim_cards(p: dict) -> list[dict]:
    from .actions import claim_view
    cards = []
    for c in p.get("claims", []):
        v = claim_view(c)
        if not v["open"]:
            continue
        title = (f"Your estimate is ready: {money(c['estimate_usd'])}" if c["status"] == "estimate_ready" and c.get("estimate_usd") else
                 f"Claim {c['claim_id']}: {v['status_label'].lower()}")
        cards.append(_card(
            "claim", f"claim-{c['claim_id']}", title, f"{c['claim_id']} · {C.LOSS_LABEL.get(c['loss_type'], c['loss_type'])} · {c.get('adjuster')}",
            v["next_step"] or "Follow every step here", v["status_label"], 0.97 if c["status"] in ("estimate_ready", "submitted") else 0.8,
            {"label": "Track claim", "screen": "claim", "args": {"claim_id": c["claim_id"]}}))
    return cards


async def _wellness_cards(p: dict, pols: list[dict]) -> list[dict]:
    from .actions import telehealth_days
    cards = []
    w = p.get("wellness") or {}
    health = next((x for x in pols if x["line"] == "health"), None)
    pet = next((x for x in pols if x["line"] == "pet"), None)
    th = w.get("telehealth") or {}
    if th.get("upcoming"):
        u = th["upcoming"]
        cards.append(_card("telehealth", "telehealth-booked", f"Video visit {_in(days_until(u['date']))} at {u['time']}", f"{u['type_name']} with {u['provider']}",
                           "The join link appears 10 minutes before", "Booked", 1.0, {"label": "Visit details", "screen": "wellness", "args": {"tab": "telehealth"}}))
    elif health or pet:
        copay = C.HEALTH_PLAN_BY_ID[health["plan_id"]]["telehealth_copay"] if health else 0
        cards.append(_card(
            "telehealth", "telehealth", "See a doctor from your phone" if health else f"Talk to a vet about {_what(pet)}",
            "Primary care, urgent care, mental health and dermatology by video" if health else "Televet visits are included with your pet plan",
            f"{money(copay)} copay on your plan" if copay else "No copay on your plan", "Same day", 0.62,
            {"label": "Book a visit", "screen": "wellness", "args": {"tab": "telehealth"}},
            slots=await telehealth_days(), types=[t for t in C.TELEHEALTH_TYPES if (t["id"] == "vet" and pet) or (t["id"] != "vet" and health)]))
    d = w.get("deductible")
    if health and d:
        left = max(0, d["individual_usd"] - d["met_usd"])
        cards.append(_card("deductible", "deductible", f"{money(d['met_usd'])} of {money(d['individual_usd'])} deductible met",
                           f"{money(left)} to go · resets {nice_date(d.get('resets'))}" if left else "Deductible met - you now pay copays only",
                           f"Out-of-pocket so far: {money(d['oop_met_usd'])} of {money(d['oop_max_usd'])}", C.HEALTH_PLAN_BY_ID[health["plan_id"]]["name"], 0.4,
                           {"label": "See my plan", "screen": "wellness", "args": {"tab": "deductible"}}))
    if pet:
        plan = C.PET_PLAN_BY_ID[pet["plan_id"]]
        ded_left = max(0, plan["annual_deductible"] - (pet.get("usage") or {}).get("deductible_met_usd", 0))
        pending = [b for b in w.get("vet_bills", []) if b["status"] == "under_review"]
        cards.append(_card(
            "vetbill", "vetbill", f"{pending[0]['bill_id']} is being reviewed" if pending else f"Get {_what(pet)}'s vet bills paid back",
            f"{plan['name']}: {plan['reimbursement_pct']}% back" + (f" after {money(ded_left)} more of your deductible" if ded_left else ", deductible met"),
            "Snap the invoice - works offline, bills up to $600 pay in 2 days", f"{plan['reimbursement_pct']}%", 0.56,
            {"label": "Submit a vet bill", "screen": "wellness", "args": {"tab": "pet"}}))
    wr = w.get("wearable") or {}
    if health:
        if wr.get("linked"):
            cards.append(_card("wearable", "wearable", f"{wr.get('points', 0):,} wellness points", f"{wr.get('device')} · {wr.get('steps_7d_avg', 0):,} steps a day this week",
                               f"That's {money(wr.get('reward_usd', 0))} off your premium", money(wr.get("reward_usd", 0)), 0.3,
                               {"label": "My rewards", "screen": "wellness", "args": {"tab": "wearable"}}))
        else:
            cards.append(_card("wearable", "wearable", "Link your watch, earn premium credit", f"{C.WELLNESS_POINTS_PER_GOAL_DAY} points for every {C.WELLNESS_STEP_GOAL:,}-step day",
                               f"{C.WELLNESS_LINK_BONUS} points just for linking", f"+{C.WELLNESS_LINK_BONUS}", 0.5,
                               {"label": "Link a device", "screen": "wellness", "args": {"tab": "wearable"}}))
    return cards


def _coverage_cards(p: dict) -> list[dict]:
    from .actions import active_on_demand, coverage_products
    cards = []
    od = p.get("on_demand") or {}
    plans = od.get("plans") or {}
    covs = od.get("coverages", [])
    products = coverage_products(p)
    quote = {x["id"]: x["quote"] for x in products}
    boost = 0.25 if p["audience"] == "ondemand" else 0
    for c in active_on_demand(p):
        cards.append(_card("coverage", f"cover-{c['coverage_id']}", f"{c['name']} is active", f"Until {nice_date(c['end'])}" + (f" · {c['vehicle']}" if c.get("vehicle") else f" · {c['destination']}" if c.get("destination") else ""),
                           "Your certificate is saved on this phone" + (" · roadside included" if c.get("roadside") else ""), "Active", 1.1,
                           {"label": "Show certificate", "screen": "cards"}))

    def covered(product: str, start: str, end: str) -> bool:
        return any(c["product"] == product and c["start"] <= end and start <= c["end"] for c in covs)

    trip, drive = plans.get("trip"), plans.get("drive")
    if drive:
        prod = "rental-car" if drive.get("kind") == "rental" else "borrow-car"
        end = (dt.date.fromisoformat(drive["start"]) + dt.timedelta(days=int(drive["days"]) - 1)).isoformat()
        if not covered(prod, drive["start"], end) and (days_until(end) or 0) >= 0:
            q = quote[prod]
            d = days_until(drive["start"]) or 0
            cards.append(_card(
                "coverage", f"offer-{prod}", f"{'Renting' if prod == 'rental-car' else 'Borrowing'} a {drive['vehicle'].split(' ', 1)[-1]} {'today' if d <= 0 else _in(d)}?",
                f"{C.ON_DEMAND_BY_ID[prod]['name']} · {q['days']} day{'s' if q['days'] != 1 else ''} · {money(q['price_usd'])}",
                "Starts in minutes; roadside included", money(q["price_usd"]), 0.8 + boost + (0.1 if d <= 2 else 0),
                {"label": "Get covered", "screen": "coverage", "args": {"product": prod}}, products=products, plans=plans))
    if trip and not covered("travel", trip["depart"], trip["return"]) and (days_until(trip["depart"]) or 0) >= 0:
        q = quote["travel"]
        cards.append(_card(
            "coverage", "offer-travel", f"Cover your trip to {trip['destination'].split(',')[0]}", f"Trip protection · {q['days']} days · {money(q['price_usd'])}",
            f"You leave {_in(days_until(trip['depart']))} - cancellation, medical and 24/7 SOS", money(q["price_usd"]), 0.78 + boost,
            {"label": "Protect this trip", "screen": "coverage", "args": {"product": "travel"}}, products=products, plans=plans))
    if not cards:
        cards.append(_card("coverage", "coverage", "Cover by the day, when you need it", "Borrowed car $12 · rental $9 · trips from $19 · events $25",
                           "No annual policy needed; active the moment you confirm", "From $9", 0.18 + boost,
                           {"label": "See on-demand cover", "screen": "coverage"}, products=products, plans=plans))
    return cards


async def compute_feed(profile: dict) -> list[dict]:
    if not profile.get("consent", {}).get("personalization_opt_in", True):
        return []
    from .actions import active_on_demand, active_policies, roadside_plan
    p = profile
    pols = active_policies(p)
    cards = await _billing_cards(p, pols) + _claim_cards(p) + _coverage_cards(p)
    if p["audience"] == "member":
        cards += await _wellness_cards(p, pols)
    rs = p.get("roadside") or {}
    live = next((d for d in rs.get("dispatches", []) if d["status"] in ("dispatched", "en_route", "on_scene")), None)
    if live:
        cards.append(_card("roadside", f"dispatch-{live['dispatch_id']}", f"{live['service_name']} on the way · about {live['eta_minutes']} min",
                           f"{live['provider']} → {live['location']['label']}", "Stay somewhere safe, away from traffic", "En route", 1.5,
                           {"label": "Follow the truck", "screen": "roadside"}))
    auto = [x for x in pols if x["line"] == "auto"]
    cardable = [x for x in pols if x.get("id_card")]
    od_active = active_on_demand(p)
    if cardable or od_active:
        names = [f"{C.LINES[x['line']]['name']} · {_what(x)}" for x in cardable] + [c["name"] for c in od_active]
        cards.append(_card("idcard", "idcards", "Your ID cards, ready offline", " · ".join(names[:3]), "Stored on this phone - no signal needed at the roadside or the pharmacy",
                           f"{len(names)} card{'s' if len(names) != 1 else ''}", 0.5, {"label": "Show my cards", "screen": "cards"}))
    if auto:
        t = p.get("telematics") or {}
        if t.get("enrolled"):
            pct = C.drive_discount_pct(t.get("score")) if t["program"] == "safe-driver" else 0
            weak = min(t["factors"], key=t["factors"].get) if t.get("factors") else None
            cards.append(_card("drive", "drive", f"DriveWell score {t.get('score') or '–'}",
                               f"{pct}% off at renewal" if t["program"] == "safe-driver" else f"{t.get('miles_month', 0):g} miles this month",
                               f"Biggest gain: {weak}" if weak and t["factors"][weak] < 95 else "Trips record even with no signal", f"{len(t.get('trips', []))} trips",
                               0.58, {"label": "My driving", "screen": "drive"}))
        else:
            cards.append(_card("drive", "drive", "Save up to 25% for driving well", "5% off just for joining DriveWell", "Your phone records trips - no device to install", "Up to 25%",
                               0.2 + float(p["ml_scores"].get("cross_sell_propensity") or 0.3) * 0.6, {"label": "Join DriveWell", "screen": "drive"}))
    if (auto or any(c.get("roadside") for c in od_active)) and not live:
        plan = roadside_plan(p)
        cards.append(_card("roadside", "roadside", "Roadside help in one tap", "Tow, flat tire, jump-start, lockout or fuel - sent to your GPS location",
                           f"{plan['calls_left']} call{'s' if plan['calls_left'] != 1 else ''} left this term" if plan["plan"] == "included" else
                           "Included with your on-demand cover" if plan["plan"] == "on-demand" else f"{money(plan['cost_usd'])} per call", "24/7", 0.32,
                           {"label": "Get help", "screen": "roadside"}))
    cards.sort(key=lambda c: c["score"], reverse=True)
    for i, c in enumerate(cards):
        c["rank"] = i + 1
        c["score"] = round(c["score"], 3)
    return cards


async def refresh_feed(user_id: str) -> dict | None:
    profile = await store.get("profiles", profile_id(user_id))
    if not profile:
        return None
    doc = {
        "type": "feed", "user_id": user_id, "audience": profile["audience"], "cards": await compute_feed(profile),
        "model_version": profile["ml_scores"].get("model_version"), "segment": profile["ml_scores"].get("segment"),
        "export_date": profile.get("export_date"), "profile_rev": profile.get("rev", 0), "today": today().isoformat(),
        "generated_at": now_iso(), "channels": [user_channel(user_id)],
    }
    await store.upsert("feed", feed_id(user_id), doc)
    return doc
