"""Knowledge Base documents published to AOM by the nightly loader.

Three kinds:

* **Help Center** - what any customer may be told: ID cards and documents,
  claims, roadside, billing and renewals, DriveWell, support and on-demand
  cover. Contains no personal data, so answers grounded only in it are safe
  to share across users through AOM's LLM cache. The general RAG application
  (`insurance-assistant`) is scoped to this document.
* **Member Care Guide** - telehealth, deductibles, vet bill reimbursement
  and wearable rewards. For health and pet plan members only: the wellness
  RAG application (`insurance-wellness`) is scoped to it, and its phone copy
  travels on the `members` channel.
* **User profile** - one per person, rendered from that night's export as
  plain prose. The assistant retrieves it with a `document_id`-scoped search,
  so an answer can only ever be grounded in the asker's *own* profile.

`FAQ` is the bundled copy of the CMS entries, served when no CMS endpoint is
configured (sources.py). Entries are also synced to the phone - general
entries inside `catalog::v1`, member entries inside `wellness::v1` - so the
app can answer the common questions offline from Couchbase Lite.
"""
from __future__ import annotations

from . import catalog as C
from .docs import days_until

_CO = C.COMPANY

FAQ = [
    # ---- Digital ID cards & documents ------------------------------------------------
    {"section": "ID cards & documents", "audience": "all", "intent": "documents",
     "q": "Where is my insurance ID card?",
     "a": "Your ID cards are under ID Cards & Documents and are stored on your phone, so they open with no signal. A digital card is "
          "accepted as proof of insurance by police and DMVs in every state we write in; you can also add it to your phone's wallet "
          "or have a printed card mailed.",
     "keywords": ["id card", "insurance card", "proof of insurance", "digital card", "wallet", "show my card", "card"]},
    {"section": "ID cards & documents", "audience": "all", "intent": "documents",
     "q": "How do I get a copy of my policy documents?",
     "a": "Open ID Cards & Documents and choose a policy: the declarations page, the policy booklet and a proof-of-insurance letter "
          "are ready instantly. Letters for a lender or landlord and a claims history letter are prepared by hand and arrive in your "
          "documents within one business day.",
     "keywords": ["policy document", "documents", "declarations", "dec page", "policy booklet", "copy of my policy", "paperwork", "pdf", "letter"]},
    {"section": "ID cards & documents", "audience": "all", "intent": "documents",
     "q": "My lender needs proof of insurance - what do I send?",
     "a": "Request an evidence of insurance letter from ID Cards & Documents and name the lender or landlord. It lists them as an "
          "interested party and is emailed to you within one business day, free of charge.",
     "keywords": ["lender", "landlord", "mortgage", "evidence of insurance", "lienholder", "leasing company", "bank needs"]},
    # ---- Claims -------------------------------------------------------------------------
    {"section": "Claims", "audience": "all", "intent": "claim",
     "q": "How do I file a claim?",
     "a": "Open Claims, pick the policy and what happened, describe it and take photos or a short video of the damage right there. "
          "You can file with no signal - the claim is saved on your phone and sent when you reconnect. An adjuster is assigned "
          "within one business day.",
     "keywords": ["file a claim", "make a claim", "start a claim", "report a claim", "claim", "accident report", "report damage"]},
    {"section": "Claims", "audience": "all", "intent": "claim",
     "q": "How long does a claim take?",
     "a": "Glass claims are usually approved the same day. Most auto claims get an estimate within 3 business days of your photos "
          "and are paid 2 business days after approval. Home claims that need an inspection take 7 to 10 days. Every step shows "
          "under Claims as it happens.",
     "keywords": ["how long", "claim take", "claim status", "track my claim", "when will i get paid", "claim timeline", "payout"]},
    {"section": "Claims", "audience": "all", "intent": "claim",
     "q": "What photos do you need for a claim?",
     "a": "Four corners of the vehicle or room, close-ups of each damaged area, the licence plate or address, and the other party's "
          "card and plate if someone else was involved. Add a police report or receipts later from the claim screen.",
     "keywords": ["photos", "pictures", "video", "evidence", "what do you need", "upload", "police report", "receipt"]},
    {"section": "Claims", "audience": "all", "intent": "claim",
     "q": "What is a deductible?",
     "a": "Your deductible is the part of a covered loss you pay; we pay the rest up to your limit. It applies per claim for auto "
          "and home. Glass repair has no deductible, and you never pay a deductible when the other driver is at fault and insured.",
     "keywords": ["deductible", "out of pocket", "how much do i pay", "excess"]},
    # ---- Roadside & emergency --------------------------------------------------------------
    {"section": "Roadside & emergency", "audience": "all", "intent": "roadside",
     "q": "How does roadside assistance work?",
     "a": "Open Roadside, choose tow, flat tire, jump-start, lockout or fuel, and share your location - help usually arrives in 25 to "
          f"40 minutes. Harborline Auto includes {C.ROADSIDE_CALLS_PER_TERM} calls per term with towing up to 25 miles; on-demand "
          f"borrowed-car and rental cover include it too. Without a plan, a call is ${C.ROADSIDE_PAYG_USD}.",
     "keywords": ["roadside", "tow", "towing", "flat tire", "jump start", "jump-start", "locked out", "lockout", "out of gas", "breakdown", "battery"]},
    {"section": "Roadside & emergency", "audience": "all", "intent": "emergency",
     "q": "What should I do after an accident?",
     "a": "Make sure everyone is safe and call 911 if anyone is hurt. Then use SOS in the app: it shares your location with our 24/7 "
          "emergency desk, who call you within 2 minutes and can send a tow. Photograph both vehicles and exchange details, but "
          "don't admit fault; you can start the claim from the same screen.",
     "keywords": ["accident", "crash", "collision", "sos", "emergency", "after an accident", "been hit", "what do i do"]},
    {"section": "Roadside & emergency", "audience": "all", "intent": "emergency",
     "q": "Is there emergency help when I travel?",
     "a": "Trip protection includes a 24/7 SOS line: medical referrals and evacuation, help with a lost passport and emergency cash. "
          "Press SOS and choose 'Emergency while travelling'; it works anywhere your phone has data or Wi-Fi.",
     "keywords": ["travel emergency", "abroad", "medical emergency", "evacuation", "lost passport", "overseas", "hospital"]},
    # ---- Payments & renewals ----------------------------------------------------------------
    {"section": "Payments & renewals", "audience": "all", "intent": "billing",
     "q": "How can I pay my premium?",
     "a": "Pay in the app with the card or bank account on file, one time or monthly. Paying the term in full saves "
          f"{C.PAY_IN_FULL_DISCOUNT_PCT}%. A payment posts the same day and you'll get a confirmation number.",
     "keywords": ["pay my premium", "pay my bill", "payment", "make a payment", "how can i pay", "payment methods", "bill"]},
    {"section": "Payments & renewals", "audience": "all", "intent": "billing",
     "q": "How does AutoPay work?",
     "a": f"AutoPay takes your monthly payment from the card or bank account on file on the day you choose and saves ${C.AUTOPAY_DISCOUNT_USD} "
           "a month. We remind you 3 days before each payment, and you can switch it off any time.",
     "keywords": ["autopay", "auto-pay", "auto pay", "automatic payment", "recurring"]},
    {"section": "Payments & renewals", "audience": "all", "intent": "billing",
     "q": "What happens if I miss a payment?",
     "a": f"There's a {C.GRACE_DAYS}-day grace period. After that a ${C.LATE_FEE_USD} late fee is added and we send a cancellation "
          "notice with a date at least 10 days out; paying before that date keeps your cover without a gap. If the fee was a one-off, "
          "ask the assistant - a billing supervisor can waive it once a year.",
     "keywords": ["miss a payment", "missed payment", "late fee", "late payment", "past due", "grace period", "cancel for non-payment", "overdue"]},
    {"section": "Payments & renewals", "audience": "all", "intent": "billing",
     "q": "How does renewal work?",
     "a": "About 30 days before your term ends we send a renewal offer with the new premium and what changed. Auto renews every 6 "
          "months, home and renters every 12. Accept it in the app in one tap, monthly or paid in full; if you do nothing, the "
          "policy renews on the same payment plan.",
     "keywords": ["renewal", "renew", "policy expires", "expiring", "new premium", "rate went up", "renewal offer"]},
    # ---- Telematics ----------------------------------------------------------------------------
    {"section": "DriveWell telematics", "audience": "all", "intent": "telematics",
     "q": "What is DriveWell?",
     "a": "DriveWell is our usage-based program. Safe Driver takes 5% off for joining and up to 25% at renewal based on a score "
          "for braking, speed, night driving, phone use and mileage. Pay-Per-Mile is a $29 monthly base plus 6 cents a mile, for cars "
          "driven under about 8,000 miles a year.",
     "keywords": ["drivewell", "telematics", "usage-based", "usage based", "safe driver", "pay per mile", "pay-per-mile", "driving discount"]},
    {"section": "DriveWell telematics", "audience": "all", "intent": "telematics",
     "q": "How is my driving score calculated?",
     "a": "Each trip scores 0 to 100: hard braking, speeding more than 10 mph over the limit, handling your phone while moving and "
          "driving between midnight and 4am take points off. Your score is the mileage-weighted average of your last 30 trips. 70 "
          "earns 5% off, 78 earns 10%, 85 earns 15%, 90 earns 20% and 95 earns 25%.",
     "keywords": ["driving score", "score calculated", "how is my score", "hard braking", "speeding", "trip score", "improve my score"]},
    {"section": "DriveWell telematics", "audience": "all", "intent": "telematics",
     "q": "What does DriveWell track?",
     "a": "Trip start and end, distance, time of day, braking and acceleration, speed against the limit and whether the phone was "
          "handled. Trips are recorded on your phone, even with no signal, and synced later. We never sell the data, and your score "
          "can lower your rate but never raise it.",
     "keywords": ["track", "tracking", "privacy", "location data", "what data", "sensor", "beacon", "mileage"]},
    # ---- Support ---------------------------------------------------------------------------------
    {"section": "Support", "audience": "all", "intent": "account",
     "q": "How do I update my address or contact details?",
     "a": "Tell the assistant or open Support: email, phone and mailing address change straight away. A new home address can change "
          "your auto or home rate, so we confirm the premium by email within a day; your cover continues meanwhile.",
     "keywords": ["update my address", "change my address", "moved", "moving", "contact details", "phone number", "email address", "update my details"]},
    {"section": "Support", "audience": "all", "intent": "account",
     "q": "How do I change my coverage?",
     "a": "Ask in chat or open Support. Simple updates - adding rental reimbursement, a new mortgage company, correcting a name - "
          "apply the same day. Adding or removing a driver or vehicle, and changing deductibles or liability limits, are reviewed "
          "by underwriting, usually within a few hours; you'll see the decision in the app.",
     "keywords": ["change my coverage", "add a driver", "remove a driver", "add a vehicle", "new car", "change deductible", "raise my limits", "change my policy"]},
    {"section": "Support", "audience": "all", "intent": "handoff",
     "q": "How do I reach a person?",
     "a": f"Say \"talk to an agent\" and a licensed agent joins by chat, callback or video, with your conversation and policies in "
          f"front of them. Agents are available {_CO['support_hours']}; the assistant, claims and roadside work around the clock. "
          f"You can also call {_CO['support_phone']}.",
     "keywords": ["human", "agent", "person", "representative", "speak to someone", "talk to", "call me", "live chat", "real person"]},
    {"section": "Support", "audience": "all", "intent": "general",
     "q": "Does the app work offline?",
     "a": "Yes. ID cards, documents, claims, bills and your driving trips are stored on your phone. Without a signal you can show a "
          "card, file a claim with photos, request roadside or record a trip; everything is sent as soon as you reconnect.",
     "keywords": ["offline", "no signal", "no service", "no internet", "without wifi", "airplane mode"]},
    {"section": "Support", "audience": "all", "intent": "general",
     "q": "What does Harborline insure?",
     "a": "Auto, home and renters policies; health and pet plans; and on-demand cover you switch on for a day or a trip - a borrowed "
          "car, a rental car, a journey or a one-day event. Bundling auto with home or renters takes 12% off both.",
     "keywords": ["what do you insure", "what do you cover", "products", "bundle", "what insurance", "offer"]},
    # ---- On-demand coverage ---------------------------------------------------------------------------
    {"section": "On-demand coverage", "audience": "all", "intent": "coverage",
     "q": "Can I get insurance for a car I'm borrowing?",
     "a": "Yes - borrowed-car cover is $12 a day, starts in minutes and needs only the car's make and model. It gives you liability "
          "and damage cover with a $500 deductible plus roadside assistance, and leaves the owner's own policy and no-claims record "
          "untouched.",
     "keywords": ["borrow", "borrowing", "borrowed car", "friend's car", "someone else's car", "temporary car insurance", "day insurance"]},
    {"section": "On-demand coverage", "audience": "all", "intent": "coverage",
     "q": "What does trip protection cover?",
     "a": "Trip cancellation up to the cost of the trip, $100,000 of emergency medical care, $250,000 of medical evacuation, "
          "baggage delay and the 24/7 SOS line. It costs $6 a day plus 4% of the trip cost you insure, from $19, and can be bought "
          "up to the day you leave.",
     "keywords": ["trip protection", "travel insurance", "travel cover", "trip cancellation", "vacation", "holiday", "flight", "trip"]},
    {"section": "On-demand coverage", "audience": "all", "intent": "coverage",
     "q": "How does on-demand coverage work?",
     "a": "Pick a product, the dates and the details, and pay by the day - cover is active as soon as you confirm, and the certificate "
          "is saved on your phone. Rental car damage cover is $9 a day and one-day event liability $25. You can buy it with or "
          "without an annual Harborline policy.",
     "keywords": ["on-demand", "on demand", "short-term", "short term", "temporary", "by the day", "rental car", "event", "one day"]},
    # ---- Health & wellness (Member Care Guide) ----------------------------------------------------------
    {"section": "Telehealth", "audience": "member", "intent": "wellness",
     "q": "How do telehealth visits work?",
     "a": "Book a video visit in Health & Wellness: primary care, urgent care, mental health or dermatology, 8:30am to 7pm, usually "
          "same or next day. Silver and Gold plans have no copay; Bronze is $10. The clinician can prescribe to your pharmacy. "
          "Pet plans include televet visits at no charge.",
     "keywords": ["telehealth", "video visit", "virtual visit", "see a doctor", "doctor", "televet", "online doctor", "appointment", "prescription"]},
    {"section": "Deductibles", "audience": "member", "intent": "wellness",
     "q": "How does my health deductible work?",
     "a": "You pay for covered care until you reach your deductible ($3,200 Bronze, $1,500 Silver, $500 Gold); after that you pay "
          "only copays and coinsurance until the out-of-pocket maximum, then nothing. Preventive care and telehealth don't wait "
          "for the deductible. It resets on January 1.",
     "keywords": ["deductible", "out-of-pocket", "out of pocket", "oop", "coinsurance", "how much have i met", "resets"]},
    {"section": "Pet plans", "audience": "member", "intent": "wellness",
     "q": "How do I get a vet bill reimbursed?",
     "a": "Pay the vet, then photograph the itemized invoice in Health & Wellness and submit it - even offline. We reimburse 70%, "
          "80% or 90% of covered costs after your annual deductible, depending on your plan. Bills up to $600 are approved "
          "automatically and paid within 2 days; larger ones are reviewed in about 2 business days.",
     "keywords": ["vet bill", "vet", "veterinary", "pet claim", "reimburse", "reimbursement", "invoice", "pet insurance", "dog", "cat"]},
    {"section": "Pet plans", "audience": "member", "intent": "wellness",
     "q": "What does pet insurance not cover?",
     "a": "Pre-existing conditions, and routine care - annual exams, vaccines and dental cleanings - unless you have the $250 routine "
          "care add-on. Accidents are covered from day 3 and illnesses from day 15 of a new plan.",
     "keywords": ["not cover", "exclusions", "pre-existing", "routine care", "vaccines", "dental cleaning", "waiting period"]},
    {"section": "Wearables", "audience": "member", "intent": "wellness",
     "q": "How do wearable rewards work?",
     "a": f"Link an Apple Watch, Fitbit, Garmin, Oura Ring or Pixel Watch. Each day you reach {C.WELLNESS_STEP_GOAL:,} steps earns "
          f"{C.WELLNESS_POINTS_PER_GOAL_DAY} points, linking earns {C.WELLNESS_LINK_BONUS}, and 1,000 points is $10 off your "
          "premium. We read steps and active minutes only - never heart rate, sleep or location.",
     "keywords": ["wearable", "apple watch", "fitbit", "garmin", "oura", "steps", "fitness tracker", "wellness points", "rewards", "sync my watch"]},
    {"section": "Health plans", "audience": "member", "intent": "wellness",
     "q": "What health plans are there?",
     "a": "Three: Harbor Bronze HSA ($3,200 deductible, $7,000 out-of-pocket maximum, health savings account), Harbor Silver PPO "
          "($1,500 deductible, $25 office visits, free telehealth) and Harbor Gold PPO ($500 deductible, $15 office visits). You can "
          "change plans at open enrollment in November or after a qualifying life event.",
     "keywords": ["health plan", "bronze", "silver", "gold", "ppo", "hsa", "open enrollment", "medical plan", "copay"]},
]
CUSTOMER_FAQ = [f for f in FAQ if f["audience"] == "all"]
MEMBER_FAQ = [f for f in FAQ if f["audience"] == "member"]


def faq_public(entries: list[dict]) -> list[dict]:
    return [{"q": f["q"], "a": f["a"], "keywords": f["keywords"], "section": f.get("section"), "intent": f.get("intent")} for f in entries]


def _faq_md(entries: list[dict]) -> list[str]:
    lines, section = [], None
    for f in entries:
        if f.get("section") != section:
            section = f.get("section")
            lines += ["", f"## {section}", ""]
        lines += [f"### {f['q']}", f["a"], ""]
    return lines


def help_center_markdown(export_date: str, entries: list[dict] | None = None) -> str:
    entries = [e for e in (entries or FAQ) if e.get("audience", "all") == "all"]
    lines = [f"# {_CO['name']} Help Center", f"Published {export_date}. Public information for {_CO['name']} customers.", ""]
    lines += _faq_md(entries)
    lines += ["", "## Policy documents you can request", ""]
    for d in C.DOC_TYPES:
        lines.append(f"- {d['name']} ({d['id']}): for {', '.join(d['lines'])}; " + ("ready instantly." if d["instant"] else "prepared within one business day."))
    lines += ["", "## Roadside services", ""]
    for s in C.ROADSIDE_SERVICES:
        lines.append(f"- {s['name']} ({s['id']}): typically {s['eta_min']} minutes. {s['detail']}")
    lines += ["", "## Policy changes", ""]
    for c in C.POLICY_CHANGES:
        lines.append(f"- {c['name']} ({c['id']}): " + ("reviewed by underwriting before it applies." if c["approval"] else "applied the same day."))
    lines += ["", "## On-demand cover", ""]
    for p in C.ON_DEMAND:
        lines.append(f"- {p['name']} ({p['id']}): ${p['price_per_day']} a day"
                     + (f" plus {p['pct_of_trip_cost']}% of the insured trip cost" if p.get("pct_of_trip_cost") else "")
                     + f", minimum ${p['min_usd']}, up to {p['max_days']} days. {p['blurb']} Covers: {'; '.join(p['covers'])}.")
    lines += ["", "## Contact", "",
              f"- Customer care {_CO['support_phone']} ({_CO['support_hours']}); claims {_CO['claims_phone']} and roadside {_CO['roadside_phone']}, 24/7."]
    return "\n".join(lines)


def member_guide_markdown(export_date: str, entries: list[dict] | None = None) -> str:
    entries = [e for e in (entries or FAQ) if e.get("audience") == "member"]
    lines = [f"# {_CO['name']} Member Care Guide", f"Published {export_date}. For members of {_CO['wellness_brand']} plans only.", ""]
    lines += _faq_md(entries)
    lines += ["", "## Health plans", ""]
    for p in C.HEALTH_PLANS:
        lines.append(f"- {p['name']} ({p['id']}): ${p['deductible']:,} deductible, ${p['oop_max']:,} out-of-pocket maximum, "
                     f"${p['telehealth_copay']} telehealth copay. {p['blurb']}")
    lines += ["", "## Pet plans", ""]
    for p in C.PET_PLANS:
        lines.append(f"- {p['name']} ({p['id']}): {p['reimbursement_pct']}% reimbursement, ${p['annual_deductible']} annual deductible, "
                     f"${p['annual_limit']:,} annual limit. {p['blurb']}")
    lines += ["", "## Telehealth visit types", ""]
    for t in C.TELEHEALTH_TYPES:
        lines.append(f"- {t['name']} ({t['id']}); visits at {', '.join(C.TELEHEALTH_TIMES)}.")
    lines += ["", "## Wearable rewards", "",
              f"- Supported devices: {', '.join(C.WEARABLES)}. {C.WELLNESS_POINTS_PER_GOAL_DAY} points for each {C.WELLNESS_STEP_GOAL:,}-step day; "
              f"{C.WELLNESS_POINTS_PER_DOLLAR} points is $1 of premium credit."]
    return "\n".join(lines)


def _policy_line(x: dict) -> str:
    what = ""
    if x.get("vehicles"):
        what = " covering " + ", ".join(f"{v['year']} {v['make']} {v['model']}" for v in x["vehicles"])
    elif x.get("property"):
        what = f" covering {x['property'].get('address')}"
    elif x.get("pets"):
        what = " covering " + ", ".join(f"{pt['name']} the {pt['breed']}" for pt in x["pets"])
    b = x.get("billing") or {}
    return (f"{x['product']} policy {x['policy_id']}{what}: active {x['effective']} to {x['expires']}, premium ${x['premium_usd']:,.2f} per term"
            + (f", deductible ${x['deductible_usd']:,}" if x.get("deductible_usd") else "")
            + (f", {b.get('plan', 'monthly').replace('_', ' ')} billing, AutoPay {'on' if b.get('autopay') else 'off'}" if b else ""))


def user_profile_markdown(p: dict) -> str:
    s = p.get("ml_scores", {})
    head = [f"# User profile {p['user_id']}: {p['first_name']} {p['last_name']} ({C.AUDIENCES[p['audience']]})",
            f"Source: Harborline nightly export {p.get('export_date')}, scores by {s.get('model_version')}"
            + (f"; segments: {', '.join(a['name'] for a in p['segments'])}" if p.get("segments") else "") + ".", ""]
    prefs = p.get("preferences", {})
    pols = [x for x in p.get("policies", []) if x.get("status") == "active"]
    body = [
        "## Account",
        f"{p['first_name']} lives in {p.get('home_city')} ({p.get('address') or 'no address on file'}) and has been a customer since "
        f"{(p.get('history') or {}).get('customer_since', 'recently')}. Email {p.get('email')}, phone {p.get('phone') or 'not on file'}. "
        f"Prefers {prefs.get('communication_channel')} messages; paperless {'on' if prefs.get('paperless') else 'off'}.",
        "", "## Policies",
        ("; ".join(_policy_line(x) for x in pols) + "." if pols else "No annual policy - an on-demand customer."),
        "", "## Billing",
        ("; ".join(f"{x['policy_id']}: ${x['billing']['installment_usd']:,.2f} due {x['billing'].get('next_due')}"
                   + (f", ${x['billing'].get('balance_due_usd', 0):,.2f} past due plus a ${x['billing'].get('late_fee_usd', 0):,.0f} late fee" if x["billing"].get("past_due") else "")
                   + (f", renewal offer ${x['renewal']['offer_premium_usd']:,.2f} from {x['expires']}" if (x.get("renewal") or {}).get("status") == "offered" else "")
                   for x in pols) + "." if pols else "Nothing billed."),
        "", "## Claims",
        ("; ".join(f"claim {c['claim_id']} on {c['policy_id']} ({C.LOSS_LABEL.get(c['loss_type'], c['loss_type']).lower()}, {c['loss_date']}): "
                   f"{C.CLAIM_STEP_LABEL.get(c['status'], c['status']).lower()}, adjuster {c.get('adjuster')}"
                   + (f", estimate ${c['estimate_usd']:,}" if c.get("estimate_usd") else "") for c in p.get("claims", [])) + "."
         if p.get("claims") else "No claims on file."),
    ]
    rs = p.get("roadside") or {}
    body += ["", "## Roadside",
             f"Roadside calls used this term: {rs.get('uses_this_term', 0)}. Last known location: {(rs.get('last_location') or {}).get('label', 'unknown')}."]
    t = p.get("telematics") or {}
    body += ["", "## Driving",
             (f"Enrolled in {C.TELEMATICS_PROGRAMS[t['program']]['name']} via {t.get('device')}: score {t.get('score')}, "
              f"{t.get('miles_month', 0):g} miles this month, {len(t.get('trips', []))} recent trips." if t.get("enrolled")
              else "Not enrolled in DriveWell telematics." if any(x["line"] == "auto" for x in pols) else "No auto policy.")]
    if p["audience"] == "member":
        w = p.get("wellness") or {}
        d, th, wr = w.get("deductible") or {}, w.get("telehealth") or {}, w.get("wearable") or {}
        body += ["", "## Wellness",
                 (f"Health deductible: ${d.get('met_usd', 0):,.0f} of ${d.get('individual_usd', 0):,.0f} met; out-of-pocket ${d.get('oop_met_usd', 0):,.0f} "
                  f"of ${d.get('oop_max_usd', 0):,.0f}. " if d else "")
                 + f"Telehealth visits this year: {th.get('visits_used', 0)}"
                 + (f"; next visit {th['upcoming']['date']} {th['upcoming']['time']} with {th['upcoming']['provider']}" if th.get("upcoming") else "") + ". "
                 + (f"Wearable: {wr.get('device')} linked, {wr.get('points', 0):,} points. " if wr.get("linked") else "No wearable linked. ")
                 + (f"Vet bills submitted: {len(w.get('vet_bills', []))}." if any(x["line"] == "pet" for x in pols) else "")]
    od = p.get("on_demand") or {}
    plans = od.get("plans") or {}
    body += ["", "## On-demand cover",
             ("; ".join(f"{c['name']} {c['coverage_id']} from {c['start']} to {c['end']} (${c['price_usd']:,.2f})" for c in od.get("coverages", [])) + ". "
              if od.get("coverages") else "No on-demand cover bought yet. ")
             + (f"Planning a trip to {plans['trip']['destination']} from {plans['trip']['depart']} to {plans['trip']['return']}. " if plans.get("trip") else "")
             + (f"Planning to drive a {plans['drive']['vehicle']} ({plans['drive']['kind']}) for {plans['drive']['days']} days from {plans['drive']['start']}." if plans.get("drive") else "")]
    body += ["", "## Personalization signals",
             f"Segment: {s.get('segment')}. Next best action: {s.get('next_best_action')}. Renewal propensity {s.get('renewal_propensity')}, "
             f"churn risk {s.get('churn_risk')}, cross-sell propensity {s.get('cross_sell_propensity')}. Days to next renewal: "
             f"{min((days_until(x['expires']) or 999 for x in pols), default='n/a')}."]
    return "\n".join(head + body)
