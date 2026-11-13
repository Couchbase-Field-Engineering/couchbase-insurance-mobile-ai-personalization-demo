"""End-to-end checks of the demo backend in memory mode (no Couchbase, no AOM):
the eight use cases of an insurance app, across the three personas.

    cd backend && pytest -q
"""
import time
import uuid

# The `client` fixture (memory store, generated mock export, no AOM) lives in conftest.py.
MAYA, DANIEL, SOFIA = ("5510101", "Chen"), ("5520202", "Okafor"), ("5530303", "Alvarez")


def login(client, account, last):
    r = client.post("/api/auth/login", json={"account_id": account, "last_name": last})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}, r.json()["user_id"]


def pull(client, h):
    docs = client.get("/api/sync/pull", headers=h).json()["docs"]
    return {(d["collection"], d["id"]): d["doc"] for d in docs}


def ask(client, h, message):
    r = client.post("/api/chat", headers=h, json={"message": message})
    assert r.status_code == 200, r.text
    return r.json()


def push(client, h, uid, tool, args):
    rid = f"req::{uid}::{uuid.uuid4().hex[:12]}"
    r = client.post("/api/sync/push", headers=h, json={"docs": [{"collection": "requests", "id": rid, "doc": {
        "type": "request", "user_id": uid, "tool": tool, "args": args, "created_at": "2026-11-13T15:00:00Z"}}]})
    assert r.status_code == 200, r.text
    for _ in range(40):
        d = pull(client, h).get(("requests", rid))
        if d and d["status"] not in ("pending", "processing"):
            return d
        time.sleep(0.1)
    raise AssertionError("request never processed")


def profile(client, h, uid):
    return pull(client, h)[("profiles", f"profile::{uid}")]


def policy(p, policy_id):
    return next(x for x in p["policies"] if x["policy_id"] == policy_id)


def test_personas_and_login(client):
    ps = client.get("/api/demo/personas").json()["personas"]
    assert [p["user_id"] for p in ps] == ["P00000101", "M00000201", "O00000301"]
    assert [p["audience"] for p in ps] == ["policyholder", "member", "ondemand"]
    assert client.post("/api/auth/login", json={"account_id": "5510101", "last_name": "Nope"}).status_code == 401
    r = client.post("/api/auth/login", json={"account_id": "5520202", "last_name": "okafor"}).json()
    assert r["channels"] == ["user:M00000201", "catalog", "members"]


def test_feed_is_personalized_per_customer(client):
    h, uid = login(client, *MAYA)
    docs = pull(client, h)
    cards = docs[("feed", f"feed::{uid}")]["cards"]
    assert cards[0]["kind"] == "claim" and "$2,340" in cards[0]["title"]
    assert {"claim", "renewal", "payment", "drive", "idcard", "roadside"} <= {c["kind"] for c in cards}
    assert ("catalog", "catalog::v1") in docs
    h, uid = login(client, *DANIEL)
    cards = pull(client, h)[("feed", f"feed::{uid}")]["cards"]
    assert cards[0]["kind"] == "payment" and "past due" in cards[0]["title"]
    assert {"telehealth", "vetbill", "wearable", "deductible"} <= {c["kind"] for c in cards}
    assert next(c for c in cards if c["kind"] == "telehealth")["slots"]          # the Wellness screen works offline
    h, uid = login(client, *SOFIA)
    cards = pull(client, h)[("feed", f"feed::{uid}")]["cards"]
    assert [c["kind"] for c in cards] == ["coverage", "coverage"] and "$36" in cards[0]["subtitle"] and "Lisbon" in cards[1]["title"]


def test_member_guide_only_reaches_members(client):
    """Sync Gateway's `members` channel, mirrored by the preview sync."""
    for who in (MAYA, SOFIA):
        h, _ = login(client, *who)
        assert ("catalog", "wellness::v1") not in pull(client, h)
    h, _ = login(client, *DANIEL)
    wg = pull(client, h)[("catalog", "wellness::v1")]
    assert wg["channels"] == ["members"] and any("vet bill" in f["q"].lower() for f in wg["faq"])


# ---- 1. Digital ID cards & documents ---------------------------------------------
def test_id_cards_and_documents(client):
    h, uid = login(client, *MAYA)
    a = ask(client, h, "Show me my insurance card")
    assert a["intent"] == "documents" and a["area"] == "documents" and a["personal"] and a["context"]["status"] == "miss"
    assert "HL-AUTO-448120" in a["reply"] and "Subaru Outback" in a["reply"] and a["actions"][0]["screen"] == "cards"
    # the context was built with the person's current policy-administration record
    assert a["context"]["sor"]["system"] == "pas" and "Bundled auto + home" in a["context"]["sor"]["segments"]
    assert ask(client, h, "Where is my proof of insurance?")["context"]["status"] == "hit"
    g = ask(client, h, "How do I get a copy of my policy documents?")
    assert g["personal"] is False and "declarations page" in g["reply"]
    p = profile(client, h, uid)
    assert policy(p, "HL-AUTO-448120")["id_card"]["insured"] == "Maya Chen"
    assert {d["type"] for d in policy(p, "HL-AUTO-448120")["documents"]} >= {"id_card", "declarations", "policy_booklet"}
    r = push(client, h, uid, "request_document", {"policy_id": "HL-AUTO-448120", "doc_type": "proof_of_insurance", "delivery": "email"})
    assert r["status"] == "confirmed" and "maya.chen@example.com" in r["summary"] and r["agent"] == "insurance-assistant"
    lender = ask(client, h, "My lender needs proof of insurance")["actions"][0]
    assert lender["screen"] == "cards" and lender["args"]["request"] == "lender_letter"
    assert push(client, h, uid, "request_document", {"policy_id": "HL-HOME-207733", "doc_type": "lender_letter"})["status"] == "failed"   # who is it for?
    r = push(client, h, uid, "request_document", {"policy_id": "HL-HOME-207733", "doc_type": "lender_letter", "recipient": "First Harbor Bank"})
    assert r["status"] == "submitted" and "Nov 14" in r["summary"]
    assert push(client, h, uid, "request_document", {"policy_id": "HL-HOME-207733", "doc_type": "id_card"})["status"] == "failed"         # no card for a home
    docs = policy(profile(client, h, uid), "HL-HOME-207733")["documents"]
    assert docs[-1]["status"] == "requested" and "First Harbor Bank" in docs[-1]["title"]


# ---- 2. Claims filing & tracking -----------------------------------------------------
def test_claim_tracking_filing_and_evidence(client):
    h, uid = login(client, *MAYA)
    a = ask(client, h, "What's the status of my claim?")
    assert a["intent"] == "claim" and a["area"] == "claims" and a["personal"]
    assert "CLM-551207" in a["reply"] and "$1,840" in a["reply"] and "Priya Raman" in a["reply"]
    assert a["actions"][0] == {"label": "Track CLM-551207", "screen": "claim", "args": {"claim_id": "CLM-551207"}}
    assert "no signal" in ask(client, h, "How do I file a claim?")["reply"]
    assert ("context_cache", f"ctx::{uid}::claim") in pull(client, h)
    r = push(client, h, uid, "add_claim_evidence", {"claim_id": "CLM-551207", "kind": "photo", "count": 3})
    assert r["status"] == "confirmed" and r["agent"] == "insurance-claims-agent", r
    assert ("context_cache", f"ctx::{uid}::claim") not in pull(client, h)          # invalidated by the change
    r = push(client, h, uid, "file_claim", {"policy_id": "HL-AUTO-448120", "loss_type": "glass", "loss_date": "2026-11-12",
                                            "description": "A stone chipped the windshield on the expressway", "photos": 3, "videos": 1})
    assert r["status"] == "confirmed" and "no deductible" in r["summary"], r
    p = profile(client, h, uid)
    assert len(p["claims"]) == 2 and p["claims"][1]["status"] == "under_review" and p["claims"][1]["deductible_usd"] == 0
    assert sum(e["count"] for e in p["claims"][0]["evidence"]) == 9 and p["rev"] >= 2
    cards = pull(client, h)[("feed", f"feed::{uid}")]["cards"]
    assert sum(c["kind"] == "claim" for c in cards) == 2
    # business rules: a duplicate, a loss type from the wrong line, a date in the future
    dup = push(client, h, uid, "file_claim", {"policy_id": "HL-AUTO-448120", "loss_type": "glass", "loss_date": "2026-11-12", "description": "the same windshield again"})
    assert dup["status"] == "failed" and "already open" in dup["summary"]
    assert push(client, h, uid, "file_claim", {"policy_id": "HL-HOME-207733", "loss_type": "collision", "loss_date": "2026-11-12",
                                               "description": "this is not a home loss"})["status"] == "failed"
    assert push(client, h, uid, "file_claim", {"policy_id": "HL-HOME-207733", "loss_type": "water", "loss_date": "2026-12-01",
                                               "description": "a pipe burst under the sink"})["status"] == "failed"


# ---- 3. Roadside & emergency assistance -------------------------------------------------
def test_roadside_dispatch_and_sos(client):
    h, uid = login(client, *MAYA)
    a = ask(client, h, "My car won't start")
    assert a["intent"] == "roadside" and a["area"] == "roadside" and a["personal"] and "jump-start" in a["reply"]
    assert a["actions"][0]["screen"] == "roadside" and a["actions"][0]["args"] == {"service": "jump"}
    assert ask(client, h, "How does roadside assistance work?")["personal"] is False
    e = ask(client, h, "I've just been in an accident")
    assert e["intent"] == "emergency" and "911" in e["reply"] and e["actions"][0]["args"] == {"sos": "accident"}
    r = push(client, h, uid, "request_roadside", {"service": "jump", "lat": 40.6782, "lon": -73.9442})
    assert r["status"] == "confirmed" and r["charge_usd"] == 0 and r["agent"] == "insurance-roadside-agent", r
    assert "GPS 40.6782, -73.9442" in r["summary"]
    docs = pull(client, h)
    rs = docs[("profiles", f"profile::{uid}")]["roadside"]
    assert rs["dispatches"][0]["location"]["source"] == "gps" and rs["uses_this_term"] == 2
    assert docs[("feed", f"feed::{uid}")]["cards"][0]["kind"] == "roadside"       # the truck on the way goes to the top
    assert "already on the way" in push(client, h, uid, "request_roadside", {"service": "tow"})["summary"]
    s = push(client, h, uid, "send_sos", {"kind": "accident", "lat": 40.68, "lon": -73.94})
    assert s["status"] == "submitted" and "2 minutes" in s["summary"]
    # no auto policy and no on-demand cover: roadside is charged per call
    h, uid = login(client, *DANIEL)
    r = push(client, h, uid, "request_roadside", {"service": "flat", "location": "Barton Springs Rd"})
    assert r["status"] == "confirmed" and r["charge_usd"] == 79


# ---- 4. Premium payments & renewals -------------------------------------------------------
def test_payments_autopay_and_renewal(client):
    h, uid = login(client, *MAYA)
    a = ask(client, h, "When is my next payment due?")
    assert a["intent"] == "billing" and a["area"] == "billing" and "$158" in a["reply"] and "Nov 17" in a["reply"]
    assert a["actions"][0]["tool"] == "make_payment" and a["actions"][1]["tool"] == "set_autopay"
    rn = ask(client, h, "When does my policy renew?")
    assert "Dec 4" in rn["reply"] and "$1,012" in rn["reply"] and "15% off" in rn["reply"] and rn["context"]["status"] == "hit"
    assert [x.get("tool") or x.get("screen") for x in rn["actions"]] == ["redeem_drive_discount", "pay"]
    r = push(client, h, uid, "make_payment", {"policy_id": "HL-AUTO-448120"})
    assert r["status"] == "confirmed" and r["charge_usd"] == 158 and r["agent"] == "insurance-billing-agent", r
    assert push(client, h, uid, "make_payment", {"policy_id": "HL-AUTO-448120", "amount_usd": 900})["status"] == "failed"
    r = push(client, h, uid, "set_autopay", {"policy_id": "HL-AUTO-448120", "enabled": True})
    assert r["status"] == "confirmed" and "$153" in r["summary"], r
    assert push(client, h, uid, "set_autopay", {"policy_id": "HL-AUTO-448120", "enabled": True})["status"] == "failed"
    b = policy(profile(client, h, uid), "HL-AUTO-448120")["billing"]
    assert b["balance_due_usd"] == 0 and b["next_due"] == "2026-12-17" and b["autopay"] and b["autopay_day"] == 17
    # the home policy has no renewal offer yet
    assert "no renewal offer" in push(client, h, uid, "renew_policy", {"policy_id": "HL-HOME-207733"})["summary"]
    r = push(client, h, uid, "renew_policy", {"policy_id": "HL-AUTO-448120", "pay_plan": "pay_in_full"})
    assert r["status"] == "confirmed" and r["charge_usd"] == 951.28 and "Jun 4" in r["summary"], r      # $1,012 less 6%
    assert push(client, h, uid, "renew_policy", {"policy_id": "HL-AUTO-448120"})["status"] == "failed"
    kinds = [c["kind"] for c in pull(client, h)[("feed", f"feed::{uid}")]["cards"]]
    assert "renewal" not in kinds and "payment" not in kinds


def test_past_due_and_the_fee_waiver(client):
    h, uid = login(client, *DANIEL)
    a = ask(client, h, "How much do I owe?")
    assert "$66" in a["reply"] and "HL-PET-118052" in a["reply"] and "late fee" in a["reply"]
    assert [x["tool"] for x in a["actions"][:2]] == ["make_payment", "request_fee_waiver"]
    assert push(client, h, uid, "set_autopay", {"policy_id": "HL-PET-118052", "enabled": True})["status"] == "failed"    # pay what's past due first
    w = push(client, h, uid, "request_fee_waiver", a["actions"][1]["args"])
    assert w["status"] == "confirmed" and "$15" in w["summary"] and "$51 is still due" in w["summary"], w
    assert push(client, h, uid, "request_fee_waiver", {"policy_id": "HL-PET-118052", "reason": "again please"})["status"] == "failed"
    r = push(client, h, uid, "make_payment", {})                    # no policy named: the one that is due
    assert r["status"] == "confirmed" and r["charge_usd"] == 51 and "Dec 1" in r["summary"], r
    b = policy(profile(client, h, uid), "HL-PET-118052")["billing"]
    assert not b["past_due"] and b["late_fee_usd"] == 0 and b["balance_due_usd"] == 0


# ---- 5. Telematics & usage-based tracking ---------------------------------------------------
def test_telematics_trips_score_and_discount(client):
    client.post("/api/demo/reset", json={})                        # the renewal offer is back
    h, uid = login(client, *MAYA)
    a = ask(client, h, "What's my driving score?")
    assert a["intent"] == "telematics" and a["area"] == "telematics" and "88" in a["reply"] and "15% off" in a["reply"] and "braking" in a["reply"]
    assert a["actions"][0]["tool"] == "redeem_drive_discount"
    assert "25%" in ask(client, h, "What is DriveWell?")["reply"]
    t = push(client, h, uid, "record_trip", {"miles": 12.4, "minutes": 31, "hard_brakes": 1})
    assert t["status"] == "confirmed" and "score 95" in t["summary"] and t["agent"] == "insurance-drive-agent", t
    tel = profile(client, h, uid)["telematics"]
    assert len(tel["trips"]) == 13 and 86 <= tel["score"] <= 90
    r = push(client, h, uid, "redeem_drive_discount", {})
    assert r["status"] == "confirmed" and "$860.20" in r["summary"] and "$151.80" in r["summary"], r
    assert push(client, h, uid, "redeem_drive_discount", {})["status"] == "failed"
    rn = policy(profile(client, h, uid), "HL-AUTO-448120")["renewal"]
    assert rn["offer_premium_usd"] == 860.2 and rn["drive_discount_pct"] == 15
    assert push(client, h, uid, "record_trip", {"miles": 0, "minutes": 5})["status"] == "failed"
    # someone without an auto policy can't join, and trips need enrollment
    h, uid = login(client, *DANIEL)
    assert "Auto policy" in push(client, h, uid, "enroll_telematics", {})["summary"]
    assert push(client, h, uid, "record_trip", {"miles": 3, "minutes": 9})["status"] == "failed"


# ---- 6. In-app customer support ---------------------------------------------------------------
def test_support_details_changes_and_live_agent(client):
    h, uid = login(client, *MAYA)
    for q, expect in (("How do I update my address or contact details?", "mailing address"), ("How do I reach a person?", "licensed agent"),
                      ("Does the app work offline?", "stored on your phone"), ("What is a deductible?", "per claim")):
        a = ask(client, h, q)
        assert a["personal"] is False and expect in a["reply"], (q, a["reply"])
    a = ask(client, h, "I moved, can you update my address?")
    assert a["intent"] == "account" and a["area"] == "support" and "418 Prospect Pl" in a["reply"] and a["actions"][0]["screen"] == "support"
    r = push(client, h, uid, "update_contact_details", {"address": "77 Harbor Rd, Brooklyn, NY 11201", "phone": "+1 555 0100 2000"})
    assert r["status"] == "confirmed" and "rate" in r["summary"]
    assert push(client, h, uid, "update_contact_details", {"email": "not-an-email"})["status"] == "failed"
    assert profile(client, h, uid)["address"].startswith("77 Harbor Rd")
    # coverage changes go through the approval-tier tool; simple updates don't
    assert "underwriting" in push(client, h, uid, "request_policy_change", {"policy_id": "HL-AUTO-448120", "change": "add_driver", "details": "Add my daughter Lily"})["summary"]
    c = push(client, h, uid, "request_coverage_change", {"policy_id": "HL-AUTO-448120", "change": "add_driver", "details": "Add my daughter Lily, 17"})
    assert c["status"] == "confirmed" and "Add a driver" in c["summary"]
    assert push(client, h, uid, "request_policy_change", {"policy_id": "HL-HOME-207733", "change": "update_mortgagee", "details": "Loan moved to First Harbor Bank"})["status"] == "confirmed"
    t = ask(client, h, "I want to talk to an agent about my claim")
    assert t["intent"] == "handoff" and t["actions"][0]["tool"] == "request_live_agent" and t["actions"][0]["args"]["topic"] == "Claim question"
    r = push(client, h, uid, "request_live_agent", t["actions"][1]["args"])
    assert r["status"] == "submitted" and "calls" in r["summary"] and "licensed agent" in r["summary"]
    assert push(client, h, uid, "request_live_agent", {"topic": "Billing question"})["status"] == "failed"      # already in the queue


# ---- 7. Health & wellness ------------------------------------------------------------------------
def test_wellness_telehealth_vet_bills_and_wearables(client):
    h, uid = login(client, *DANIEL)
    g = ask(client, h, "How do telehealth visits work?")
    assert g["intent"] == "wellness" and g["area"] == "wellness" and g["personal"] is False and "no copay" in g["reply"]
    d = ask(client, h, "How much of my deductible have I met?")
    assert d["personal"] and "$640" in d["reply"] and "$860 to go" in d["reply"] and d["context"]["sor"]["system"] == "members"
    v = ask(client, h, "Will you pay back my dog's vet bill?")
    assert v["intent"] == "wellness" and "80%" in v["reply"] and "$160" in v["reply"] and v["actions"][0]["args"] == {"tab": "pet"}
    book = next(x for x in ask(client, h, "I have a rash, can I book a video visit?")["actions"] if x.get("tool") == "book_telehealth")
    assert book["args"]["visit_type"] == "derm"
    r = push(client, h, uid, "book_telehealth", book["args"])
    assert r["status"] == "confirmed" and "no copay" in r["summary"] and r["agent"] == "insurance-wellness-agent", r
    assert "already have a visit" in push(client, h, uid, "book_telehealth", book["args"])["summary"]
    r = push(client, h, uid, "submit_vet_bill", {"pet_id": "PET-118052-1", "amount_usd": 340, "clinic": "Greenpoint Veterinary",
                                                 "visit_date": "2026-11-10", "reason": "Limping / sprain", "photos": 2})
    assert r["status"] == "confirmed" and "$144 back" in r["summary"] and "$160 of your deductible" in r["summary"], r
    big = push(client, h, uid, "submit_vet_bill", {"pet_id": "PET-118052-1", "amount_usd": 1800, "clinic": "Parkside Animal Hospital",
                                                   "visit_date": "2026-11-11", "reason": "Ingested foreign object", "photos": 3})
    assert big["status"] == "submitted" and "$1,440" in big["summary"]                       # deductible now met: 80% of the bill
    routine = push(client, h, uid, "submit_vet_bill", {"pet_id": "PET-118052-2", "amount_usd": 210, "clinic": "Greenpoint Veterinary",
                                                       "visit_date": "2026-11-09", "reason": "Dental cleaning", "photos": 1})
    assert "routine care" in routine["summary"] and "isn't reimbursed" in routine["summary"]
    assert push(client, h, uid, "submit_vet_bill", {"pet_id": "PET-118052-1", "amount_usd": 90, "clinic": "Greenpoint Veterinary",
                                                    "visit_date": "2026-11-10", "reason": "Skin allergy", "photos": 0})["status"] == "failed"   # no invoice photo
    w = push(client, h, uid, "link_wearable", {"device": "Garmin"})
    assert w["status"] == "confirmed" and "500 welcome points" in w["summary"]
    p = profile(client, h, uid)
    assert p["wellness"]["telehealth"]["upcoming"]["type"] == "derm" and p["wellness"]["wearable"]["points"] == 500
    assert policy(p, "HL-PET-118052")["usage"] == {"deductible_met_usd": 250.0, "paid_usd": 144.0}
    assert [b["status"] for b in p["wellness"]["vet_bills"]] == ["approved", "approved", "under_review", "denied"]
    assert "telehealth-booked" in [c["card_id"] for c in pull(client, h)[("feed", f"feed::{uid}")]["cards"]]


# ---- 8. Short-term / on-demand coverage ---------------------------------------------------------------
def test_on_demand_cover_quotes_activation_and_roadside(client):
    h, uid = login(client, *SOFIA)
    a = ask(client, h, "I'm borrowing my sister's car this weekend, can you cover me?")
    assert a["intent"] == "coverage" and a["area"] == "coverage" and a["personal"] and "$36" in a["reply"] and "2021 Toyota RAV4" in a["reply"]
    assert a["context"]["sor"]["system"] == "ondemand"
    act = a["actions"][0]
    assert act["tool"] == "activate_coverage" and act["args"] == {"product": "borrow-car", "days": 3, "start_date": "2026-11-14", "vehicle": "2021 Toyota RAV4"}
    t = ask(client, h, "I need cover for my trip")
    assert "Lisbon" in t["reply"] and "$144" in t["reply"] and t["context"]["status"] == "hit"       # $6 x 8 days + 4% of $2,400
    assert "$12 a day" in ask(client, h, "Is there insurance for a borrowed car?")["reply"]
    assert "Nothing is active" in ask(client, h, "What cover do I have active right now?")["reply"]
    # before any cover, a tow would be charged; she has no card to show either
    assert "$79" in ask(client, h, "I need a tow")["reply"]
    r = push(client, h, uid, "activate_coverage", {"product": "borrow-car", "days": 3, "vehicle": "2021 Toyota RAV4"})        # starting today
    assert r["status"] == "confirmed" and r["charge_usd"] == 36 and "active now" in r["summary"] and r["agent"] == "insurance-coverage-agent", r
    r2 = push(client, h, uid, "activate_coverage", t["actions"][0]["args"])
    assert r2["status"] == "confirmed" and r2["charge_usd"] == 144 and "scheduled" in r2["summary"], r2
    assert push(client, h, uid, "activate_coverage", {"product": "borrow-car", "days": 2, "vehicle": "2021 Toyota RAV4"})["status"] == "failed"   # overlaps
    assert push(client, h, uid, "activate_coverage", {"product": "travel", "days": 5})["status"] == "failed"                                  # where to?
    docs = pull(client, h)
    covs = docs[("profiles", f"profile::{uid}")]["on_demand"]["coverages"]
    assert [c["status"] for c in covs] == ["expired", "active", "scheduled"] and covs[1]["certificate"]["status"] == "ready"
    kinds = [c["kind"] for c in docs[("feed", f"feed::{uid}")]["cards"]]
    assert kinds[0] == "coverage" and "idcard" in kinds and "roadside" in kinds
    assert "certificate" in ask(client, h, "Show me my insurance card")["reply"]
    # roadside is included while borrowed-car cover is active
    rs = push(client, h, uid, "request_roadside", {"service": "flat", "location": "I-77 near exit 9"})
    assert rs["status"] == "confirmed" and rs["charge_usd"] == 0 and "on-demand cover" in rs["summary"]
    assert push(client, h, uid, "send_sos", {"kind": "travel", "location": "Lisbon airport"})["status"] == "submitted"
    # a policyholder can buy on-demand cover too
    h, uid = login(client, *MAYA)
    assert push(client, h, uid, "activate_coverage", {"product": "rental-car", "days": 2})["charge_usd"] == 18


# ---- one app, three kinds of customer: the guard rails -------------------------------------------------
def test_wellness_questions_are_refused_without_a_health_or_pet_plan(client):
    for who in (MAYA, SOFIA):
        h, _ = login(client, *who)
        for q in ("Can I see a doctor by video?", "How do I get a vet bill reimbursed?", "How do wearable rewards work?"):
            a = ask(client, h, q)
            assert a["restricted"] and a["area"] == "wellness" and "members" in a["reply"], q
            assert not a["sources"] and not a["actions"] and a["llm"]["status"] == "skipped"


def test_tools_check_what_the_customer_holds(client):
    h, uid = login(client, *MAYA)
    r = push(client, h, uid, "book_telehealth", {"date": "2026-11-16", "time": "10:00"})
    assert r["status"] == "failed" and "members" in r["summary"]
    assert push(client, h, uid, "submit_vet_bill", {"pet_id": "", "amount_usd": 80, "clinic": "Any Vet", "visit_date": "2026-11-10", "reason": "Skin allergy"})["status"] == "failed"
    assert push(client, h, uid, "get_policies", {})["status"] == "failed"          # read tools can't be requested from a phone
    h, uid = login(client, *SOFIA)
    assert push(client, h, uid, "file_claim", {"policy_id": "", "loss_type": "collision", "loss_date": "2026-11-12", "description": "scraped a bollard"})["status"] == "failed"
    assert "Nothing is due" in push(client, h, uid, "make_payment", {})["summary"]


def test_push_rejects_other_users(client):
    h, uid = login(client, *DANIEL)
    r = client.post("/api/sync/push", headers=h, json={"docs": [{"collection": "requests", "id": "req::P00000101::x",
                                                                 "doc": {"user_id": "P00000101", "tool": "make_payment"}}]})
    assert r.status_code == 403


def test_personas_are_pinned_to_the_export_date(client):
    import datetime as dt
    client.post("/api/demo/reset", json={})
    day = dt.date(2026, 11, 13)
    h, uid = login(client, *MAYA)
    p = profile(client, h, uid)
    assert (dt.date.fromisoformat(policy(p, "HL-AUTO-448120")["expires"]) - day).days == 21
    assert (dt.date.fromisoformat(policy(p, "HL-AUTO-448120")["billing"]["next_due"]) - day).days == 4
