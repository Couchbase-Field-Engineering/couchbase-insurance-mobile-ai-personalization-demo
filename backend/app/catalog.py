"""Reference data for the insurance demo company.

**Harborline** is a fictional personal-lines insurer: auto, home and renters
policies, health and pet plans, and short-term cover you switch on from the
phone. One mobile app and one assistant serve three kinds of customer:

* policyholders        auto / home: ID cards, claims, roadside, billing, telematics
* members              health / pet plans: telehealth, deductibles, vet bills, wearables
* on-demand customers  no annual policy: borrowed-car, rental and trip cover by the day

Everything here is shared by the mock export generator
(datagen/generate_mock_export.py), the business logic (actions.py), the For
You ranking (personalization.py) and the Knowledge Base documents
(knowledge.py). Names, prices and policy terms are invented demo data.
"""
from __future__ import annotations

import datetime as dt
import hashlib

COMPANY = {
    "name": "Harborline",
    "legal_name": "Harborline Insurance Company",
    "tagline": "Cover that keeps up with you.",
    "support_phone": "1-800-555-0142",
    "claims_phone": "1-800-555-0177",
    "roadside_phone": "1-800-555-0199",
    "support_hours": "7am-10pm ET, every day",
    "naic": "00000",
    "wellness_brand": "Harborline Health & Pet",
    "telematics_program": "Harborline DriveWell",
    "website": "harborline.example",
}

AUDIENCES = {"policyholder": "Policyholder", "member": "Health & pet member", "ondemand": "On-demand customer"}

# The eight things the app is asked to do, and the intents (assistant.py) that
# belong to each. The app shows the area on every answer; each area's actions
# run as its own AOM agent (agents.py).
AREAS = {
    "documents": {"name": "ID Cards & Documents", "icon": "card", "audiences": ["policyholder", "member", "ondemand"]},
    "claims": {"name": "Claims", "icon": "camera", "audiences": ["policyholder", "member"]},
    "roadside": {"name": "Roadside & Emergency", "icon": "car-sport", "audiences": ["policyholder", "member", "ondemand"]},
    "billing": {"name": "Payments & Renewals", "icon": "wallet", "audiences": ["policyholder", "member"]},
    "telematics": {"name": "DriveWell Telematics", "icon": "speedometer", "audiences": ["policyholder"]},
    "support": {"name": "Customer Support", "icon": "help-buoy", "audiences": ["policyholder", "member", "ondemand"]},
    "wellness": {"name": "Health & Wellness", "icon": "fitness", "audiences": ["member"]},
    "coverage": {"name": "On-Demand Coverage", "icon": "flash", "audiences": ["policyholder", "member", "ondemand"]},
}

REGIONS = ["Northeast", "Southeast", "Midwest", "Southwest", "West"]
# Groups the workload draws its users from (workload.py).
GROUPS: dict[str, dict] = {
    "POL-NE": {"name": "Policyholders · Northeast", "audience": "policyholder", "region": "Northeast"},
    "POL-SE": {"name": "Policyholders · Southeast", "audience": "policyholder", "region": "Southeast"},
    "POL-MW": {"name": "Policyholders · Midwest", "audience": "policyholder", "region": "Midwest"},
    "POL-SW": {"name": "Policyholders · Southwest", "audience": "policyholder", "region": "Southwest"},
    "POL-W": {"name": "Policyholders · West", "audience": "policyholder", "region": "West"},
    "MEM-HEALTH": {"name": "Members · Health plans", "audience": "member", "line": "health"},
    "MEM-PET": {"name": "Members · Pet plans", "audience": "member", "line": "pet"},
    "OD-DRIVE": {"name": "On-demand · Borrowed & rental cars", "audience": "ondemand", "need": "drive"},
    "OD-TRAVEL": {"name": "On-demand · Travellers", "audience": "ondemand", "need": "travel"},
}
REGION_GROUP = {"Northeast": "POL-NE", "Southeast": "POL-SE", "Midwest": "POL-MW", "Southwest": "POL-SW", "West": "POL-W"}

# --------------------------------------------------------------------------
# Policies
# --------------------------------------------------------------------------
LINES = {
    "auto": {"name": "Auto", "product": "Harborline Auto", "icon": "car", "term_months": 6},
    "home": {"name": "Home", "product": "Harborline Home", "icon": "home", "term_months": 12},
    "renters": {"name": "Renters", "product": "Harborline Renters", "icon": "business", "term_months": 12},
    "health": {"name": "Health", "product": "Harborline Health", "icon": "medkit", "term_months": 12},
    "pet": {"name": "Pet", "product": "Harborline Pet", "icon": "paw", "term_months": 12},
}
COVERAGES = {
    "auto": [("Bodily injury liability", "$100,000 / $300,000"), ("Property damage liability", "$100,000"),
             ("Collision", "Actual cash value"), ("Comprehensive", "Actual cash value"),
             ("Uninsured motorist", "$100,000 / $300,000"), ("Rental reimbursement", "$40 a day, 30 days"),
             ("Roadside assistance", "4 service calls per term, towing to 25 miles")],
    "home": [("Dwelling", "$420,000"), ("Other structures", "$42,000"), ("Personal property", "$210,000"),
             ("Loss of use", "$84,000"), ("Personal liability", "$300,000"), ("Water backup", "$10,000")],
    "renters": [("Personal property", "$30,000"), ("Loss of use", "$9,000"), ("Personal liability", "$100,000")],
    "health": [("Primary care visit", "$25 copay"), ("Specialist visit", "$50 copay"), ("Telehealth visit", "$0-$10 copay"),
               ("Emergency room", "$250 copay after deductible"), ("Prescriptions", "$10 / $35 / $70")],
    "pet": [("Accidents & illness", "Reimbursed after the annual deductible"), ("Exam fees", "Included"),
            ("Prescription medication", "Included"), ("Routine care add-on", "$250 a year")],
}
VEHICLES = [("Honda", "Civic"), ("Toyota", "RAV4"), ("Subaru", "Outback"), ("Ford", "F-150"), ("Tesla", "Model 3"),
            ("Hyundai", "Tucson"), ("Mazda", "CX-5"), ("Chevrolet", "Bolt EUV"), ("Volkswagen", "Jetta"), ("Kia", "Telluride")]
PAY_PLANS = {"monthly": "Monthly", "pay_in_full": "Pay in full"}
PAY_IN_FULL_DISCOUNT_PCT = 6
AUTOPAY_DISCOUNT_USD = 5
PAYMENT_METHODS = ["card on file", "bank account"]
LATE_FEE_USD = 15
GRACE_DAYS = 10
FEE_WAIVER_MAX_USD = 50

DOC_TYPES = [
    {"id": "id_card", "name": "Insurance ID card", "lines": ["auto", "health", "pet"], "instant": True},
    {"id": "declarations", "name": "Declarations page", "lines": ["auto", "home", "renters"], "instant": True},
    {"id": "policy_booklet", "name": "Policy booklet", "lines": ["auto", "home", "renters", "health", "pet"], "instant": True},
    {"id": "proof_of_insurance", "name": "Proof of insurance letter", "lines": ["auto", "home", "renters"], "instant": True},
    {"id": "lender_letter", "name": "Evidence of insurance for a lender or landlord", "lines": ["auto", "home", "renters"], "instant": False},
    {"id": "claims_history", "name": "Claims history letter", "lines": ["auto", "home", "renters"], "instant": False},
    {"id": "benefits_summary", "name": "Summary of benefits", "lines": ["health", "pet"], "instant": True},
    {"id": "coverage_certificate", "name": "Certificate of coverage", "lines": ["ondemand"], "instant": True},
]
DOC_TYPE_BY_ID = {d["id"]: d for d in DOC_TYPES}
DOC_DELIVERY = ["app", "email", "mail"]

# --------------------------------------------------------------------------
# Claims
# --------------------------------------------------------------------------
LOSS_TYPES = {
    "auto": [("collision", "Collision with a vehicle or object"), ("glass", "Windshield or glass"), ("weather", "Hail, flood or falling object"),
             ("theft", "Theft or break-in"), ("vandalism", "Vandalism")],
    "home": [("water", "Water damage"), ("wind_hail", "Wind or hail"), ("theft", "Theft"), ("fire", "Fire or smoke"), ("liability", "Someone was hurt on the property")],
    "renters": [("theft", "Theft"), ("water", "Water damage"), ("fire", "Fire or smoke")],
}
LOSS_LABEL = {k: v for line in LOSS_TYPES.values() for k, v in line}
CLAIM_STEPS = ["submitted", "under_review", "inspection_scheduled", "estimate_ready", "approved", "paid"]
CLAIM_STEP_LABEL = {"submitted": "Submitted", "under_review": "Under review", "inspection_scheduled": "Inspection scheduled",
                    "estimate_ready": "Estimate ready", "approved": "Approved", "paid": "Paid", "denied": "Denied", "closed": "Closed"}
CLAIM_NEXT = {
    "submitted": "An adjuster is assigned within one business day.",
    "under_review": "Your adjuster is reviewing the photos and the report.",
    "inspection_scheduled": "A field inspector visits on the scheduled day; no need to be home for exterior damage.",
    "estimate_ready": "Review the estimate and choose a repair shop or a direct payment.",
    "approved": "Payment is on its way to your bank account, usually within 2 business days.",
    "paid": "This claim is paid. You can still add a supplement if the shop finds more damage.",
}
EVIDENCE_KINDS = ["photo", "video", "police_report", "receipt", "estimate"]
ADJUSTERS = ["Priya Raman", "Marcus Reid", "Elena Vasquez", "Tom Okada", "Grace Whitfield"]
REPAIR_SHOPS = ["Keystone Collision Center", "Harbor Auto Body", "Northside Glass & Trim"]

# --------------------------------------------------------------------------
# Roadside and emergency
# --------------------------------------------------------------------------
ROADSIDE_SERVICES = [
    {"id": "tow", "name": "Tow truck", "eta_min": 35, "detail": "Towing to the nearest repair shop, up to 25 miles."},
    {"id": "flat", "name": "Flat tire change", "eta_min": 30, "detail": "We fit your spare; no spare means a tow."},
    {"id": "jump", "name": "Jump-start", "eta_min": 25, "detail": "Battery jump-start, or a tow if it won't hold a charge."},
    {"id": "lockout", "name": "Lockout", "eta_min": 30, "detail": "Locksmith service up to $100."},
    {"id": "fuel", "name": "Fuel delivery", "eta_min": 30, "detail": "Two gallons delivered; you pay for the fuel."},
]
ROADSIDE_BY_ID = {s["id"]: s for s in ROADSIDE_SERVICES}
ROADSIDE_CALLS_PER_TERM = 4
ROADSIDE_PAYG_USD = 79               # one call without a roadside plan
ROADSIDE_PROVIDERS = ["Anchor Towing", "Beacon Roadside", "Tri-County Tow & Recovery", "Rapid Response Auto"]
SOS_KINDS = [
    {"id": "accident", "name": "I've been in an accident", "detail": "Shares your location with our emergency desk, who call you and can send police, EMS and a tow."},
    {"id": "medical", "name": "Medical emergency", "detail": "Connects you to the 24/7 nurse and emergency coordination line. Call 911 first if life is at risk."},
    {"id": "travel", "name": "Emergency while travelling", "detail": "Travel assistance: medical referral, evacuation, lost passport and cash transfer."},
]
SOS_BY_ID = {s["id"]: s for s in SOS_KINDS}

# --------------------------------------------------------------------------
# Telematics (usage-based insurance)
# --------------------------------------------------------------------------
TELEMATICS_PROGRAMS = {
    "safe-driver": {"name": "DriveWell Safe Driver", "enroll_discount_pct": 5, "max_discount_pct": 25,
                    "blurb": "5% off for joining, then up to 25% at renewal based on your driving score."},
    "pay-per-mile": {"name": "DriveWell Pay-Per-Mile", "base_usd_month": 29, "cents_per_mile": 6,
                     "blurb": "A $29 monthly base plus 6 cents a mile - for cars driven under about 8,000 miles a year."},
}
TELEMATICS_DEVICES = ["phone", "plug-in beacon", "connected car"]
DRIVE_FACTORS = ["braking", "speed", "night", "phone", "mileage"]


def drive_discount_pct(score: int | float | None) -> int:
    """Renewal discount earned by a DriveWell score (0-100)."""
    s = int(score or 0)
    return 25 if s >= 95 else 20 if s >= 90 else 15 if s >= 85 else 10 if s >= 78 else 5 if s >= 70 else 0


def trip_score(miles: float, hard_brakes: int, speeding: int, night: bool, phone_use: int) -> int:
    per10 = 10 / max(float(miles), 1.0)
    s = 100 - hard_brakes * 6 * min(per10, 2) - speeding * 5 * min(per10, 2) - phone_use * 7 * min(per10, 2) - (4 if night else 0)
    return int(max(20, min(100, round(s))))


# --------------------------------------------------------------------------
# Support
# --------------------------------------------------------------------------
POLICY_CHANGES = [
    {"id": "add_driver", "name": "Add a driver", "lines": ["auto"], "approval": True},
    {"id": "remove_driver", "name": "Remove a driver", "lines": ["auto"], "approval": True},
    {"id": "add_vehicle", "name": "Add or replace a vehicle", "lines": ["auto"], "approval": True},
    {"id": "change_deductible", "name": "Change a deductible", "lines": ["auto", "home", "renters"], "approval": True},
    {"id": "raise_liability", "name": "Raise liability limits", "lines": ["auto", "home", "renters"], "approval": True},
    {"id": "add_rental", "name": "Add rental reimbursement", "lines": ["auto"], "approval": False},
    {"id": "update_mortgagee", "name": "Update the mortgage company or landlord", "lines": ["home", "renters"], "approval": False},
    {"id": "name_correction", "name": "Correct a name or date on documents", "lines": ["auto", "home", "renters", "health", "pet"], "approval": False},
]
POLICY_CHANGE_BY_ID = {c["id"]: c for c in POLICY_CHANGES}
AGENT_TOPICS = ["Claim question", "Billing question", "Coverage change", "Cancel or switch", "Something else"]
AGENT_CHANNELS = ["chat", "callback", "video"]
LICENSED_AGENTS = ["Jordan Avery", "Sam Whitlock", "Renee Castellano", "Imani Brooks", "Theo Lindqvist"]

# --------------------------------------------------------------------------
# Health & wellness (members only)
# --------------------------------------------------------------------------
HEALTH_PLANS = [
    {"id": "HLT-BRONZE", "name": "Harbor Bronze HSA", "deductible": 3200, "oop_max": 7000, "telehealth_copay": 10, "blurb": "High-deductible plan with a health savings account."},
    {"id": "HLT-SILVER", "name": "Harbor Silver PPO", "deductible": 1500, "oop_max": 5500, "telehealth_copay": 0, "blurb": "Broad network, $25 office visits, free telehealth."},
    {"id": "HLT-GOLD", "name": "Harbor Gold PPO", "deductible": 500, "oop_max": 3500, "telehealth_copay": 0, "blurb": "Lowest deductible and $15 office visits."},
]
HEALTH_PLAN_BY_ID = {p["id"]: p for p in HEALTH_PLANS}
PET_PLANS = [
    {"id": "PET-ESSENTIAL", "name": "Pet Essential", "reimbursement_pct": 70, "annual_deductible": 500, "annual_limit": 5000, "blurb": "Accidents and illness, 70% back."},
    {"id": "PET-COMPLETE", "name": "Pet Complete", "reimbursement_pct": 80, "annual_deductible": 250, "annual_limit": 10000, "blurb": "Accidents, illness, exam fees and prescriptions, 80% back."},
    {"id": "PET-PREMIER", "name": "Pet Premier", "reimbursement_pct": 90, "annual_deductible": 100, "annual_limit": 20000, "blurb": "90% back with a $100 deductible and dental illness cover."},
]
PET_PLAN_BY_ID = {p["id"]: p for p in PET_PLANS}
PETS = [("dog", "Labrador Retriever"), ("dog", "French Bulldog"), ("dog", "Mixed breed"), ("cat", "Domestic Shorthair"), ("cat", "Maine Coon"), ("dog", "Golden Retriever")]
PET_NAMES = ["Biscuit", "Luna", "Mochi", "Otis", "Pepper", "Juno", "Rosie", "Theo"]
VET_VISIT_REASONS = ["Ear infection", "Upset stomach", "Limping / sprain", "Skin allergy", "Dental cleaning", "Ingested foreign object", "Annual exam"]
VET_ROUTINE = {"Annual exam", "Dental cleaning"}       # routine care: only with the add-on
VET_CLINICS = ["Greenpoint Veterinary", "Parkside Animal Hospital", "Midtown Vet Care", "Lakeshore Pet Clinic"]
TELEHEALTH_TYPES = [
    {"id": "primary", "name": "Primary care"}, {"id": "urgent", "name": "Urgent care"},
    {"id": "mental", "name": "Mental health"}, {"id": "derm", "name": "Dermatology"}, {"id": "vet", "name": "Televet (pets)"},
]
TELEHEALTH_TYPE_BY_ID = {t["id"]: t for t in TELEHEALTH_TYPES}
TELEHEALTH_TIMES = ["08:30", "10:00", "12:30", "15:00", "17:30", "19:00"]
TELEHEALTH_PROVIDERS = ["Dr. Anika Rao", "Dr. Luis Mendoza", "Dr. Hannah Weiss", "Dr. Kwame Boateng"]
WEARABLES = ["Apple Watch", "Fitbit", "Garmin", "Oura Ring", "Google Pixel Watch"]
WELLNESS_STEP_GOAL = 7000
WELLNESS_POINTS_PER_GOAL_DAY = 100
WELLNESS_POINTS_PER_DOLLAR = 100          # 1,000 points = $10 premium credit
WELLNESS_LINK_BONUS = 500

# --------------------------------------------------------------------------
# On-demand coverage
# --------------------------------------------------------------------------
ON_DEMAND = [
    {"id": "borrow-car", "name": "Borrowed-car cover", "unit": "day", "price_per_day": 12, "min_usd": 12, "max_days": 30,
     "needs": ["vehicle"], "roadside": True,
     "blurb": "Liability and damage cover while you drive a friend's or relative's car. Starts in minutes; their own policy stays untouched.",
     "covers": ["Liability $100,000 / $300,000", "Damage to the borrowed car, $500 deductible", "Roadside assistance"]},
    {"id": "rental-car", "name": "Rental car damage cover", "unit": "day", "price_per_day": 9, "min_usd": 9, "max_days": 30,
     "needs": [], "roadside": True,
     "blurb": "Covers damage and theft of a rental car so you can decline the counter's waiver.",
     "covers": ["Damage and theft of the rental, $0 deductible", "Loss-of-use and towing charges", "Roadside assistance"]},
    {"id": "travel", "name": "Trip protection", "unit": "trip", "price_per_day": 6, "pct_of_trip_cost": 4, "min_usd": 19, "max_days": 60,
     "needs": ["destination"], "roadside": False,
     "blurb": "Trip cancellation, emergency medical and 24/7 SOS assistance for one trip.",
     "covers": ["Trip cancellation up to the trip cost", "Emergency medical $100,000", "Medical evacuation $250,000", "Baggage delay $300", "24/7 SOS line"]},
    {"id": "event-day", "name": "One-day event liability", "unit": "day", "price_per_day": 25, "min_usd": 25, "max_days": 3,
     "needs": [], "roadside": False,
     "blurb": "Liability cover for a party, a market stall or a moving day.",
     "covers": ["Liability $1,000,000", "Damage to a rented venue $100,000"]},
]
ON_DEMAND_BY_ID = {p["id"]: p for p in ON_DEMAND}
DESTINATIONS = ["Lisbon, Portugal", "Tokyo, Japan", "Mexico City, Mexico", "Vancouver, Canada", "Reykjavik, Iceland", "Rome, Italy"]


def on_demand_quote(product_id: str, days: int, trip_cost_usd: float = 0) -> dict:
    p = ON_DEMAND_BY_ID[product_id]
    days = max(1, int(days))
    price = p["price_per_day"] * days
    if p.get("pct_of_trip_cost") and trip_cost_usd:
        price += float(trip_cost_usd) * p["pct_of_trip_cost"] / 100
    price = round(max(p["min_usd"], price), 2)
    return {"product": product_id, "name": p["name"], "days": days, "price_usd": price, "covers": p["covers"]}


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _h(*parts) -> int:
    return int(hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:8], 16)


def a_or_an(noun: str) -> str:
    return ("an " if noun[:1].lower() in "aeiou" else "a ") + noun


def next_days(start: dt.date, n: int) -> list[dt.date]:
    return [start + dt.timedelta(days=i) for i in range(1, n + 1)]


def slot_id(date: str, time: str) -> str:
    return f"{date}T{time}"


def initial_inventory(today: dt.date) -> dict:
    """Open telehealth appointments per slot. One CAS-protected document
    (`inv::v1`): two members can't take the same last appointment.
    Deterministic, so a reset restores it."""
    slots = {}
    for d in next_days(today, 7):
        for t in TELEHEALTH_TIMES:
            slots[slot_id(d.isoformat(), t)] = _h("slot", d.isoformat(), t) % 4   # 0 = fully booked
    return {"slots": slots}


def public_catalog() -> dict:
    """What every signed-in user's phone gets (`catalog::v1`, channel `catalog`)."""
    return {
        "company": COMPANY,
        "areas": AREAS,
        "lines": LINES,
        "doc_types": DOC_TYPES,
        "doc_delivery": DOC_DELIVERY,
        "loss_types": {k: [{"id": i, "name": n} for i, n in v] for k, v in LOSS_TYPES.items()},
        "claim_steps": CLAIM_STEPS,
        "claim_step_label": CLAIM_STEP_LABEL,
        "evidence_kinds": EVIDENCE_KINDS,
        "roadside_services": ROADSIDE_SERVICES,
        "roadside_payg_usd": ROADSIDE_PAYG_USD,
        "sos_kinds": SOS_KINDS,
        "pay_plans": PAY_PLANS,
        "late_fee_usd": LATE_FEE_USD,
        "telematics_programs": TELEMATICS_PROGRAMS,
        "policy_changes": POLICY_CHANGES,
        "agent_topics": AGENT_TOPICS,
        "agent_channels": AGENT_CHANNELS,
        "on_demand": ON_DEMAND,
        "destinations": DESTINATIONS,
    }


def member_catalog() -> dict:
    """Members-only reference data (`wellness::v1`, channel `members`): Sync
    Gateway never sends this document to a phone without a health or pet plan."""
    return {
        "health_plans": HEALTH_PLANS,
        "pet_plans": PET_PLANS,
        "telehealth_types": TELEHEALTH_TYPES,
        "telehealth_times": TELEHEALTH_TIMES,
        "vet_visit_reasons": VET_VISIT_REASONS,
        "wearables": WEARABLES,
        "step_goal": WELLNESS_STEP_GOAL,
        "points_per_goal_day": WELLNESS_POINTS_PER_GOAL_DAY,
        "points_per_dollar": WELLNESS_POINTS_PER_DOLLAR,
    }
