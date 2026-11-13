#!/usr/bin/env python3
"""Generate the mock nightly export the insurance demo is loaded from.

Harborline (the demo insurer, see backend/app/catalog.py) keeps the people its
mobile app serves in three systems of record:

* the **policy administration system** - policyholders, their auto, home and
  renters policies, billing, claims, roadside usage and telematics scores
* the **member platform** - health and pet plan members: deductibles,
  telehealth, vet bills and wearable rewards
* the **on-demand platform** - people with no annual policy who buy cover by
  the day or the trip

Every night a scheduled export lands one JSON Lines dataset with a row per
person (`audience` says which kind) in a time-stamped folder. This script
writes that layout:

    data/insurance-export/exportTime=20261113/
        part-00000-<uuid>-c000.json      # JSON Lines, one person per line
        part-00001-<uuid>-c000.json
        _SUCCESS
        _manifest.json                   # row/byte counts per audience, schema + model versions

Fully deterministic for a given --seed and --export-date, and standard
library only (runs anywhere Python 3.9+ does). Default target is 24 MiB.

    python datagen/generate_mock_export.py                 # today
    python datagen/generate_mock_export.py --export-date 2026-11-13 --target-mb 24
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import random
import sys
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "backend"))
from app import catalog as C  # noqa: E402

SCHEMA_VERSION = "insurance_person_v1"
MODEL_VERSION = "harborline-propensity-v2"
PERSONAS = ["P00000101", "M00000201", "O00000301"]
AUDIENCES = ["policyholder", "member", "ondemand"]

FIRST = ["Ava", "Noah", "Mia", "Liam", "Zoe", "Ethan", "Nora", "Lucas", "Ivy", "Owen", "Leah", "Caleb", "Ruby", "Isaac",
         "Elena", "Mateo", "Amara", "Kofi", "Yuki", "Arjun", "Fatima", "Diego", "Hana", "Tariq", "Ingrid", "Rafael",
         "Chloe", "Jamal", "Mei", "Andre", "Sana", "Victor", "Lena", "Omar", "Tessa", "Reza", "Nia", "Paulo", "Greta", "Dev"]
LAST = ["Nguyen", "Patel", "Garcia", "Johnson", "Kim", "Hernandez", "Brown", "Singh", "Martinez", "Cohen", "Okonkwo",
        "Larsen", "Tanaka", "Ali", "Rossi", "Murphy", "Santos", "Haddad", "Novak", "Park", "Mensah", "Dubois", "Ivanov",
        "Castillo", "Reyes", "Walker", "Fischer", "Banerjee", "Costa", "Holt", "Yamamoto", "Abbasi", "Lindgren", "Okoye"]
CITIES = {
    "Northeast": [("Brooklyn, NY", 40.6782, -73.9442), ("Boston, MA", 42.3601, -71.0589), ("Philadelphia, PA", 39.9526, -75.1652),
                  ("Jersey City, NJ", 40.7178, -74.0431), ("Providence, RI", 41.8240, -71.4128)],
    "Southeast": [("Atlanta, GA", 33.7490, -84.3880), ("Miami, FL", 25.7617, -80.1918), ("Charlotte, NC", 35.2271, -80.8431),
                  ("Nashville, TN", 36.1627, -86.7816), ("Tampa, FL", 27.9506, -82.4572)],
    "Midwest": [("Chicago, IL", 41.8781, -87.6298), ("Minneapolis, MN", 44.9778, -93.2650), ("Columbus, OH", 39.9612, -82.9988),
                ("Madison, WI", 43.0731, -89.4012), ("Detroit, MI", 42.3314, -83.0458)],
    "Southwest": [("Austin, TX", 30.2672, -97.7431), ("Phoenix, AZ", 33.4484, -112.0740), ("Dallas, TX", 32.7767, -96.7970),
                  ("Denver, CO", 39.7392, -104.9903), ("Albuquerque, NM", 35.0844, -106.6504)],
    "West": [("Seattle, WA", 47.6062, -122.3321), ("San Francisco, CA", 37.7749, -122.4194), ("Portland, OR", 45.5152, -122.6784),
             ("San Diego, CA", 32.7157, -117.1611), ("Oakland, CA", 37.8044, -122.2712)],
}
STREETS = ["Maple St", "Cedar Ave", "Harbor Rd", "Juniper Ln", "Willow Way", "Atlantic Ave", "Lakeview Dr", "Orchard St", "Prospect Pl"]
SEGMENTS = {
    "seg-renewal-30": "Renewing within 30 days",
    "seg-bundled": "Bundled auto + home",
    "seg-open-claim": "Open claim",
    "seg-past-due": "Payment past due",
    "seg-telematics": "DriveWell drivers",
    "seg-telematics-prospect": "Eligible for DriveWell",
    "seg-at-risk": "At risk of switching",
    "seg-health-members": "Health plan members",
    "seg-pet-parents": "Pet parents",
    "seg-wearable-linked": "Wearable linked",
    "seg-travel-intent": "Upcoming trip",
    "seg-occasional-drivers": "Occasional drivers",
}
LINE_CODE = {"auto": "AUTO", "home": "HOME", "renters": "RENT", "health": "HLTH", "pet": "PET"}
TERM_DAYS = {"auto": 182, "home": 365, "renters": 365, "health": 365, "pet": 365}


def clamp(x: float, lo=0.01, hi=0.99) -> float:
    return round(max(lo, min(hi, x)), 2)


def seg(*ids) -> list[dict]:
    return [{"id": i, "name": SEGMENTS[i], "status": "realized"} for i in ids if i]


class Gen:
    def __init__(self, export_date: dt.date, seed: int):
        self.r = random.Random(seed)
        self.today = export_date
        self.n = {a: 1000 for a in AUDIENCES}
        self.account = 6_000_000
        self.policy_no = 300_000
        self.claim_no = 500_000

    # ---- ids -------------------------------------------------------------
    def uid(self, audience: str) -> str:
        self.n[audience] += 1
        return f"{audience[0].upper()}{self.n[audience]:08d}"

    def next_account(self) -> str:
        self.account += self.r.randint(1, 9)
        return str(self.account)

    def next_policy(self, line: str) -> str:
        self.policy_no += self.r.randint(1, 40)
        return f"HL-{LINE_CODE[line]}-{self.policy_no}"

    def day(self, offset: int) -> str:
        return (self.today + dt.timedelta(days=offset)).isoformat()

    def person(self):
        return self.r.choice(FIRST), self.r.choice(LAST)

    def base(self, audience, first, last, region, group, city=None):
        r = self.r
        city, lat, lon = city or r.choice(CITIES[region])
        return {
            "user_id": self.uid(audience), "audience": audience, "group_code": group, "account_id": self.next_account(),
            "export_date": self.today.isoformat(), "schema_version": SCHEMA_VERSION,
            "first_name": first, "last_name": last, "email": f"{first}.{last}".lower().replace(" ", "") + "@example.com",
            "phone": f"+1 555 01{r.randint(10, 99)} {r.randint(1000, 9999)}",
            "home_city": city, "region": region, "address": f"{r.randint(12, 980)} {r.choice(STREETS)}, {city}",
            "consent": {"personalization_opt_in": True, "marketing_opt_in": r.random() < 0.7, "telematics_data": True},
            "preferences": {"communication_channel": r.choice(["app", "email", "sms"]), "paperless": r.random() < 0.8, "language": "en"},
            "policies": [], "claims": [], "payments": [], "fee_waivers": [], "emergencies": [],
            "roadside": {"uses_this_term": 0, "dispatches": [],
                         "last_location": {"label": city, "lat": round(lat + r.uniform(-0.03, 0.03), 4), "lon": round(lon + r.uniform(-0.03, 0.03), 4)}},
            "telematics": {"enrolled": False}, "on_demand": {"coverages": [], "plans": {}}, "support": {"requests": []},
            "history": {"customer_since": self.day(-r.randint(30, 3200)), "claims_count": 0},
        }

    # ---- policies ------------------------------------------------------------
    def billing(self, premium: float, months: int, expires: str, state: str | None = None) -> dict:
        r = self.r
        state = state or r.choices(["current", "due_soon", "past_due", "paid_in_full"], weights=[55, 22, 6, 17])[0]
        method = {"type": r.choice(["card", "card", "bank account"]), "last4": f"{r.randint(1000, 9999)}"}
        if state == "paid_in_full":
            return {"plan": "pay_in_full", "installment_usd": round(premium, 2), "next_due": expires, "balance_due_usd": 0, "late_fee_usd": 0,
                    "past_due": False, "autopay": False, "autopay_day": None, "method": method}
        inst = round(premium / months, 2)
        autopay = state == "current" and r.random() < 0.6
        if state == "past_due":
            return {"plan": "monthly", "installment_usd": inst, "next_due": self.day(-r.randint(11, 24)), "balance_due_usd": inst,
                    "late_fee_usd": C.LATE_FEE_USD, "past_due": True, "autopay": False, "autopay_day": None, "method": method}
        off = r.randint(1, 9) if state == "due_soon" else r.randint(11, 27)
        due = self.today + dt.timedelta(days=off)
        return {"plan": "monthly", "installment_usd": round(inst - (C.AUTOPAY_DISCOUNT_USD if autopay else 0), 2), "next_due": due.isoformat(),
                "balance_due_usd": inst if state == "due_soon" else 0, "late_fee_usd": 0, "past_due": False, "autopay": autopay,
                "autopay_day": min(28, due.day) if autopay else None, "method": method}

    def docs(self, line: str, issued: str) -> list[dict]:
        out = []
        for d in C.DOC_TYPES:
            if line in d["lines"] and d["id"] in ("id_card", "declarations", "policy_booklet", "benefits_summary"):
                out.append({"doc_id": f"DOC-{self.r.randint(10**7, 10**8 - 1)}", "type": d["id"], "title": d["name"], "issued": issued,
                            "status": "ready", "delivery": "app", "pages": {"id_card": 1, "declarations": 3, "benefits_summary": 4}.get(d["id"], 28)})
        return out

    def policy(self, line: str, holder: str, elapsed: int | None = None, premium: float | None = None, bill_state: str | None = None,
               **extra) -> dict:
        r = self.r
        term = TERM_DAYS[line]
        elapsed = r.randint(5, term - 2) if elapsed is None else elapsed
        effective, expires = self.day(-elapsed), self.day(term - elapsed)
        months = C.LINES[line]["term_months"]
        premium = premium or {"auto": r.randint(620, 1480), "home": r.randint(1100, 2600), "renters": r.randint(160, 320),
                              "health": r.randint(3600, 6900), "pet": r.randint(380, 980)}[line]
        pid = self.next_policy(line)
        pol = {"policy_id": pid, "line": line, "product": C.LINES[line]["product"], "status": "active", "effective": effective, "expires": expires,
               "premium_usd": float(premium), "deductible_usd": {"auto": r.choice([250, 500, 1000]), "home": r.choice([1000, 2500]), "renters": 500}.get(line),
               "coverages": [{"name": n, "limit": lim} for n, lim in C.COVERAGES[line]],
               "billing": self.billing(premium, months, expires, bill_state), "documents": self.docs(line, effective), "renewal": None}
        if line == "auto":
            n = r.choice([1, 1, 2])
            pol["roadside"] = True
            pol["vehicles"] = []
            for i in range(n):
                make, model = r.choice(C.VEHICLES)
                pol["vehicles"].append({"vehicle_id": f"VEH-{pid[-6:]}-{i + 1}", "year": r.randint(2014, 2026), "make": make, "model": model,
                                        "vin_last6": f"{r.randint(100000, 999999)}", "plate": f"{r.choice('ABCDEFGHJKLMNPRSTUVWXYZ')}{r.choice('ABCDEFGHJKLMNPRSTUVWXYZ')}{r.choice('ABCDEFGHJKLMNPRSTUVWXYZ')}-{r.randint(1000, 9999)}"})
            pol["id_card"] = {"number": pid, "naic": C.COMPANY["naic"], "insured": holder, "valid_from": effective, "valid_to": expires}
        elif line in ("home", "renters"):
            pol["property"] = {"address": extra.pop("address", ""), "type": "Single-family home" if line == "home" else "Apartment"}
        elif line == "health":
            plan = r.choice(C.HEALTH_PLANS)
            pol["plan_id"] = plan["id"]
            pol["id_card"] = {"number": f"HLM{r.randint(10**8, 10**9 - 1)}", "group": "HL-IND", "insured": holder, "plan": plan["name"],
                              "rx_bin": "004336", "valid_from": effective, "valid_to": expires}
        elif line == "pet":
            plan = r.choice(C.PET_PLANS)
            pol["plan_id"] = plan["id"]
            pol["routine_care"] = r.random() < 0.3
            pol["pets"] = []
            for i, name in enumerate(r.sample(C.PET_NAMES, r.choice([1, 1, 2]))):
                species, breed = r.choice(C.PETS)
                pol["pets"].append({"pet_id": f"PET-{pid[-6:]}-{i + 1}", "name": name, "species": species, "breed": breed, "age": r.randint(1, 13)})
            pol["usage"] = {"deductible_met_usd": float(r.choice([0, 0, 60, 120, plan["annual_deductible"]])), "paid_usd": float(r.choice([0, 0, 180, 640]))}
            pol["id_card"] = {"number": f"PET{r.randint(10**7, 10**8 - 1)}", "insured": holder, "plan": plan["name"], "valid_from": effective, "valid_to": expires}
        pol.update(extra)
        if term - elapsed <= 30 and line in ("auto", "home", "renters"):
            change = r.choice([-3, 2, 4, 6, 7, 9, 12])
            pol["renewal"] = {"status": "offered", "offer_premium_usd": round(premium * (1 + change / 100), 2), "change_pct": change,
                              "renews_on": expires, "discounts": []}
        return pol

    def claim(self, pol: dict, age: int, status: str | None = None) -> dict:
        r = self.r
        kind, _ = r.choice(C.LOSS_TYPES[pol["line"]])
        status = status or (r.choice(["submitted", "under_review"]) if age <= 2 else r.choice(["under_review", "inspection_scheduled", "estimate_ready"]) if age <= 9
                            else r.choice(["approved", "paid", "paid", "paid"]))
        self.claim_no += r.randint(1, 60)
        est = r.randint(4, 62) * 100 if C.CLAIM_STEPS.index(status) >= 3 else None
        ded = 0 if kind == "glass" else pol.get("deductible_usd") or 500
        adj = r.choice(C.ADJUSTERS)
        events = [{"at": self.day(-age), "text": "Claim filed in the Harborline app"}, {"at": self.day(-age), "text": f"Assigned to {adj}"}]
        for i, s in enumerate(C.CLAIM_STEPS[1:C.CLAIM_STEPS.index(status) + 1], 1):
            if s == "inspection_scheduled" and pol["line"] == "auto":
                continue
            events.append({"at": self.day(min(0, -age + i * max(1, age // 5))), "text": C.CLAIM_STEP_LABEL[s]})
        return {"claim_id": f"CLM-{self.claim_no}", "policy_id": pol["policy_id"], "line": pol["line"], "loss_type": kind,
                "loss_date": self.day(-age - r.randint(0, 2)), "filed_at": self.day(-age), "status": status,
                "description": C.LOSS_LABEL[kind], "location": "", "adjuster": adj, "deductible_usd": ded, "estimate_usd": est,
                "payout_usd": max(0, est - ded) if est and status == "paid" else None, "drivable": True, "fast_track": False,
                "evidence": [{"kind": "photo", "count": r.randint(2, 8), "at": self.day(-age) + "T12:00:00Z"}], "events": events}

    def trips(self, n: int, skill: float) -> list[dict]:
        r = self.r
        out = []
        for i in range(n):
            miles = round(r.uniform(2, 38), 1)
            hb = sum(r.random() > skill for _ in range(3))
            sp = sum(r.random() > skill + 0.05 for _ in range(2))
            night, phone = r.random() < 0.08, int(r.random() > skill + 0.08)
            out.append({"trip_id": f"TRP-{r.randint(10**7, 10**8 - 1)}", "date": self.day(-(n - i)), "miles": miles, "minutes": int(miles * r.uniform(1.8, 3.2)) + 3,
                        "hard_brakes": hb, "speeding": sp, "night": night, "phone_use": phone, "score": C.trip_score(miles, hb, sp, night, phone)})
        return out

    def telematics(self, vehicle_id: str, program: str = "safe-driver", n: int = 12, skill: float = 0.85) -> dict:
        trips = self.trips(n, skill)
        total = sum(t["miles"] for t in trips) or 1
        per100 = 100 / total
        return {"enrolled": True, "program": program, "vehicle_id": vehicle_id, "device": self.r.choice(C.TELEMATICS_DEVICES),
                "enrolled_at": self.day(-self.r.randint(20, 150)), "score": int(round(sum(t["score"] * t["miles"] for t in trips) / total)),
                "factors": {"braking": int(max(40, 100 - sum(t["hard_brakes"] for t in trips) * per100 * 4)),
                            "speed": int(max(40, 100 - sum(t["speeding"] for t in trips) * per100 * 4)),
                            "night": int(max(40, 100 - 60 * sum(t["miles"] for t in trips if t["night"]) / total)),
                            "phone": int(max(40, 100 - sum(t["phone_use"] for t in trips) * per100 * 5)), "mileage": 92},
                "miles_month": round(total, 1), "miles_term": round(total * self.r.uniform(2, 5), 1), "trips": trips, "redeemed": False}

    # ---- policyholders ---------------------------------------------------------
    def policyholder(self, overrides: dict | None = None, region: str | None = None, group: str | None = None) -> dict:
        r = self.r
        first, last = self.person()
        region = region or r.choice(C.REGIONS)
        row = self.base("policyholder", first, last, region, group or C.REGION_GROUP[region])
        name = f"{first} {last}"
        auto = self.policy("auto", name)
        row["policies"].append(auto)
        second = r.choices(["home", "renters", None], weights=[45, 25, 30])[0]
        if second:
            row["policies"].append(self.policy(second, name, address=row["address"]))
        if r.random() < 0.18:
            row["claims"].append(self.claim(r.choice(row["policies"]), r.randint(0, 40)))
            row["history"]["claims_count"] = 1
        if r.random() < 0.35:
            row["telematics"] = self.telematics(auto["vehicles"][0]["vehicle_id"], r.choice(["safe-driver", "safe-driver", "pay-per-mile"]),
                                                r.randint(3, 20), r.uniform(0.6, 0.97))
        row["roadside"]["uses_this_term"] = r.choice([0, 0, 0, 1, 2])
        self.signals(row)
        if overrides:
            deep_update(row, overrides)
        return row

    # ---- members -----------------------------------------------------------------
    def member(self, overrides: dict | None = None, lines: tuple = (), group: str | None = None) -> dict:
        r = self.r
        first, last = self.person()
        region = r.choice(C.REGIONS)
        lines = lines or r.choice([("health",), ("health",), ("pet",), ("health", "pet")])
        row = self.base("member", first, last, region, group or ("MEM-HEALTH" if "health" in lines else "MEM-PET"))
        name = f"{first} {last}"
        w: dict = {"vet_bills": [], "telehealth": {"visits_used": r.choice([0, 0, 1, 2, 4]), "upcoming": None}, "wearable": {"linked": False}}
        for line in lines:
            pol = self.policy(line, name)
            row["policies"].append(pol)
            if line == "health":
                plan = C.HEALTH_PLAN_BY_ID[pol["plan_id"]]
                met = float(r.choice([0, 120, 400, 900, plan["deductible"]]))
                met = min(met, plan["deductible"])
                w["deductible"] = {"individual_usd": plan["deductible"], "met_usd": met, "oop_max_usd": plan["oop_max"],
                                   "oop_met_usd": round(met + r.choice([0, 80, 260]), 2), "resets": f"{self.today.year + 1}-01-01"}
                if r.random() < 0.4:
                    pts = r.randint(4, 60) * 100
                    w["wearable"] = {"linked": True, "device": r.choice(C.WEARABLES), "linked_at": self.day(-r.randint(10, 300)),
                                     "steps_7d_avg": r.randint(3800, 12500), "goal_days_week": r.randint(1, 7), "points": pts,
                                     "reward_usd": round(pts / C.WELLNESS_POINTS_PER_DOLLAR, 2)}
        if r.random() < 0.2 and "health" in lines:
            row["policies"].append(self.policy("auto", name))
        row["wellness"] = w
        self.signals(row)
        if overrides:
            deep_update(row, overrides)
        return row

    # ---- on-demand customers -------------------------------------------------------
    def past_cover(self, product: str, ended: int, days: int) -> dict:
        prod = C.ON_DEMAND_BY_ID[product]
        q = C.on_demand_quote(product, days)
        return {"coverage_id": f"ODC-{self.r.randint(800000, 899999)}", "product": product, "name": prod["name"], "start": self.day(-ended - days + 1),
                "end": self.day(-ended), "days": days, "price_usd": q["price_usd"], "status": "expired", "covers": prod["covers"], "vehicle": None,
                "destination": None, "trip_cost_usd": None, "purchased_at": self.day(-ended - days) + "T10:00:00Z", "roadside": prod["roadside"],
                "certificate": {"doc_id": f"DOC-{self.r.randint(10**7, 10**8 - 1)}", "type": "coverage_certificate",
                                "title": f"Certificate of coverage · {prod['name']}", "issued": self.day(-ended - days), "status": "ready"}}

    def ondemand(self, overrides: dict | None = None, need: str | None = None, group: str | None = None) -> dict:
        r = self.r
        first, last = self.person()
        region = r.choice(C.REGIONS)
        need = need or r.choice(["drive", "travel"])
        row = self.base("ondemand", first, last, region, group or ("OD-DRIVE" if need == "drive" else "OD-TRAVEL"))
        plans: dict = {}
        if need == "travel":
            depart = r.randint(3, 40)
            plans["trip"] = {"destination": r.choice(C.DESTINATIONS), "depart": self.day(depart), "return": self.day(depart + r.randint(3, 14)),
                             "trip_cost_usd": r.randint(8, 52) * 100}
        else:
            make, model = r.choice(C.VEHICLES)
            plans["drive"] = {"kind": r.choice(["borrowed", "rental"]), "vehicle": f"{r.randint(2016, 2026)} {make} {model}", "start": self.day(r.randint(0, 10)),
                              "days": r.randint(1, 6)}
        row["on_demand"] = {"plans": plans, "coverages": [self.past_cover(r.choice(["rental-car", "borrow-car", "travel"]), r.randint(20, 300), r.randint(1, 6))
                                                           for _ in range(r.choice([0, 1, 1, 2]))]}
        self.signals(row)
        if overrides:
            deep_update(row, overrides)
        return row

    def signals(self, row: dict):
        """Segments and scores, the way the insurer's data platform would compute them."""
        r = self.r
        pols = row["policies"]
        lines = {p["line"] for p in pols}
        renewing = any((p.get("renewal") or {}).get("status") == "offered" for p in pols)
        past_due = any(p["billing"].get("past_due") for p in pols)
        open_claim = any(c["status"] not in ("paid", "closed", "denied") for c in row["claims"])
        tele = row["telematics"].get("enrolled")
        plans = row["on_demand"].get("plans") or {}
        churn = clamp(0.25 + (0.25 if past_due else 0) + (0.15 if renewing else 0) + r.uniform(-0.15, 0.25))
        wear = ((row.get("wellness") or {}).get("wearable") or {}).get("linked")
        row["segments"] = seg("seg-renewal-30" if renewing else None, "seg-bundled" if {"auto", "home"} <= lines else None,
                              "seg-open-claim" if open_claim else None, "seg-past-due" if past_due else None,
                              "seg-telematics" if tele else "seg-telematics-prospect" if "auto" in lines else None,
                              "seg-at-risk" if churn >= 0.6 else None, "seg-health-members" if "health" in lines else None,
                              "seg-pet-parents" if "pet" in lines else None, "seg-wearable-linked" if wear else None,
                              "seg-travel-intent" if plans.get("trip") else None, "seg-occasional-drivers" if plans.get("drive") else None)
        nba = ("pay_past_due" if past_due else "track_claim" if open_claim else "review_renewal" if renewing else
               "activate_trip_cover" if plans.get("trip") else "activate_drive_cover" if plans.get("drive") else
               "join_drivewell" if "auto" in lines and not tele else "link_wearable" if "health" in lines and not wear else "none")
        row["ml_scores"] = {"model_version": MODEL_VERSION,
                            "segment": {"policyholder": "Bundled household" if len(lines) > 1 else "Single-policy driver",
                                        "member": "Engaged member" if wear else "Health & pet member", "ondemand": "Pay-as-you-go"}[row["audience"]],
                            "next_best_action": nba, "churn_risk": churn, "renewal_propensity": clamp(1 - churn + r.uniform(-0.1, 0.1)),
                            "cross_sell_propensity": clamp(0.3 + (0.2 if len(lines) == 1 else 0) + r.uniform(-0.2, 0.3)),
                            "claim_risk": clamp(r.uniform(0.05, 0.6)),
                            "recommended_products": [x for x in (None if "home" in lines or "renters" in lines else "renters",
                                                                  None if tele or "auto" not in lines else "drivewell", "travel" if plans.get("trip") else None) if x]}

    # ---- the three people the demo signs in as --------------------------------------
    def personas(self) -> list[dict]:
        saved = dict(self.n)
        # --- Maya: auto + home, renewal in 21 days, a bill due in 4, an open claim, a DriveWell score worth 15%
        self.n["policyholder"] = 100
        maya = self.policyholder(region="Northeast")
        maya.update({"account_id": "5510101", "first_name": "Maya", "last_name": "Chen", "email": "maya.chen@example.com",
                     "phone": "+1 555 0142 1101", "home_city": "Brooklyn, NY", "address": "418 Prospect Pl, Brooklyn, NY 11238",
                     "group_code": "POL-NE", "preferences": {"communication_channel": "app", "paperless": True, "language": "en"}})
        auto = self.policy("auto", "Maya Chen", elapsed=161, premium=948, bill_state="due_soon")
        auto.update({"policy_id": "HL-AUTO-448120", "deductible_usd": 500,
                     "vehicles": [{"vehicle_id": "VEH-448120-1", "year": 2022, "make": "Subaru", "model": "Outback", "vin_last6": "204417", "plate": "KJM-4821"},
                                  {"vehicle_id": "VEH-448120-2", "year": 2019, "make": "Honda", "model": "Civic", "vin_last6": "771093", "plate": "HTR-2290"}],
                     "renewal": {"status": "offered", "offer_premium_usd": 1012.0, "change_pct": 6.8, "renews_on": self.day(21),
                                 "discounts": ["Bundled with home: 12% off"]}})
        auto["id_card"].update(number="HL-AUTO-448120", insured="Maya Chen")
        auto["billing"].update(installment_usd=158.0, balance_due_usd=158.0, next_due=self.day(4), autopay=False, autopay_day=None,
                               method={"type": "card", "last4": "4417"})
        home = self.policy("home", "Maya Chen", elapsed=200, premium=1620, bill_state="current", address="418 Prospect Pl, Brooklyn, NY 11238")
        home.update({"policy_id": "HL-HOME-207733", "deductible_usd": 1000})
        home["billing"].update(installment_usd=130.0, next_due=self.day(12), autopay=True, autopay_day=min(28, (self.today + dt.timedelta(days=12)).day),
                               balance_due_usd=0, method={"type": "card", "last4": "4417"})
        maya["policies"] = [auto, home]
        maya["claims"] = [{
            "claim_id": "CLM-551207", "policy_id": "HL-AUTO-448120", "line": "auto", "loss_type": "collision", "loss_date": self.day(-6),
            "filed_at": self.day(-6), "status": "estimate_ready", "description": "Rear-ended in a grocery store car park; rear bumper and tailgate damaged.",
            "location": "Atlantic Ave & 4th Ave, Brooklyn, NY", "adjuster": "Priya Raman", "deductible_usd": 500, "estimate_usd": 2340, "payout_usd": None,
            "drivable": True, "fast_track": False, "evidence": [{"kind": "photo", "count": 6, "at": self.day(-6) + "T16:20:00Z"}],
            "events": [{"at": self.day(-6), "text": "Claim filed in the Harborline app"}, {"at": self.day(-6), "text": "Assigned to Priya Raman"},
                       {"at": self.day(-5), "text": "Photos received - review started"}, {"at": self.day(-1), "text": "Estimate ready: $2,340 at Keystone Collision Center"}]}]
        maya["history"] = {"customer_since": self.day(-1460), "claims_count": 1}
        maya["roadside"] = {"uses_this_term": 1, "dispatches": [], "last_location": {"label": "Atlantic Ave & 4th Ave, Brooklyn, NY", "lat": 40.6843, "lon": -73.9779}}
        tele = self.telematics("VEH-448120-1", "safe-driver", 12, 0.9)
        # a steady 88: good, with braking as the thing to work on
        for i, t in enumerate(tele["trips"]):
            t.update(hard_brakes=1 if i % 2 == 0 else 0, speeding=1 if i % 5 == 0 else 0, night=False, phone_use=1 if i % 6 == 3 else 0,
                     score=88 + (i % 5) - 2)
        tele.update(device="phone", score=88, factors={"braking": 82, "speed": 91, "night": 97, "phone": 86, "mileage": 92})
        maya["telematics"] = tele
        maya["on_demand"] = {"coverages": [], "plans": {}}
        maya["segments"] = seg("seg-renewal-30", "seg-bundled", "seg-open-claim", "seg-telematics")
        maya["ml_scores"].update(segment="Bundled household", next_best_action="review_renewal", churn_risk=0.34, renewal_propensity=0.71,
                                 cross_sell_propensity=0.38, claim_risk=0.22, recommended_products=[])

        # --- Daniel: health + pet member, a pet premium past due, a deductible in progress, no wearable yet
        self.n["member"] = 200
        daniel = self.member(lines=("health", "pet"))
        daniel.update({"account_id": "5520202", "first_name": "Daniel", "last_name": "Okafor", "email": "daniel.okafor@example.com",
                       "phone": "+1 555 0142 2202", "home_city": "Austin, TX", "region": "Southwest", "address": "2207 Juniper Ln, Austin, TX 78704",
                       "group_code": "MEM-HEALTH", "preferences": {"communication_channel": "app", "paperless": True, "language": "en"}})
        health = self.policy("health", "Daniel Okafor", elapsed=317, premium=4560, bill_state="current")
        health.update({"policy_id": "HL-HLTH-663410", "plan_id": "HLT-SILVER"})
        health["id_card"].update(number="HLM204471906", insured="Daniel Okafor", plan="Harbor Silver PPO")
        health["billing"].update(installment_usd=375.0, next_due=self.day(9), autopay=True, autopay_day=min(28, (self.today + dt.timedelta(days=9)).day),
                                 balance_due_usd=0, method={"type": "bank account", "last4": "9031"})
        pet = self.policy("pet", "Daniel Okafor", elapsed=140, premium=612, bill_state="past_due")
        pet.update({"policy_id": "HL-PET-118052", "plan_id": "PET-COMPLETE", "routine_care": False,
                    "pets": [{"pet_id": "PET-118052-1", "name": "Biscuit", "species": "dog", "breed": "Labrador Retriever", "age": 4},
                             {"pet_id": "PET-118052-2", "name": "Mochi", "species": "cat", "breed": "Domestic Shorthair", "age": 7}],
                    "usage": {"deductible_met_usd": 90.0, "paid_usd": 0.0}})
        pet["id_card"].update(number="PET40118052", insured="Daniel Okafor", plan="Pet Complete")
        pet["billing"].update(installment_usd=51.0, balance_due_usd=51.0, late_fee_usd=15, past_due=True, next_due=self.day(-12),
                              method={"type": "card", "last4": "7702"})
        daniel["policies"] = [health, pet]
        daniel["claims"] = []
        daniel["telematics"] = {"enrolled": False}
        daniel["wellness"] = {
            "deductible": {"individual_usd": 1500, "met_usd": 640.0, "oop_max_usd": 5500, "oop_met_usd": 910.0, "resets": f"{self.today.year + 1}-01-01"},
            "telehealth": {"visits_used": 1, "upcoming": None}, "wearable": {"linked": False},
            "vet_bills": [{"bill_id": "VET-600411", "pet_id": "PET-118052-1", "pet_name": "Biscuit", "amount_usd": 90.0, "clinic": "Greenpoint Veterinary",
                           "visit_date": self.day(-64), "reason": "Ear infection", "photos": 1, "submitted_at": self.day(-63), "status": "approved",
                           "eligible_usd": 90.0, "deductible_applied_usd": 90.0, "reimbursement_usd": 0.0, "routine": False, "pct": 80, "pays_by": None}]}
        daniel["history"] = {"customer_since": self.day(-700), "claims_count": 0}
        daniel["segments"] = seg("seg-past-due", "seg-health-members", "seg-pet-parents")
        daniel["ml_scores"].update(segment="Health & pet member", next_best_action="pay_past_due", churn_risk=0.52, renewal_propensity=0.6,
                                   cross_sell_propensity=0.44, claim_risk=0.18, recommended_products=["drivewell"])

        # --- Sofia: no annual policy; borrowing her sister's car this weekend and flying to Lisbon in 9 days
        self.n["ondemand"] = 300
        sofia = self.ondemand(need="travel")
        sofia.update({"account_id": "5530303", "first_name": "Sofia", "last_name": "Alvarez", "email": "sofia.alvarez@example.com",
                      "phone": "+1 555 0142 3303", "home_city": "Charlotte, NC", "region": "Southeast", "address": "95 Orchard St, Charlotte, NC 28203",
                      "group_code": "OD-TRAVEL", "preferences": {"communication_channel": "app", "paperless": True, "language": "en"}})
        sofia["roadside"] = {"uses_this_term": 0, "dispatches": [], "last_location": {"label": "South End, Charlotte, NC", "lat": 35.2124, "lon": -80.8590}}
        past = self.past_cover("rental-car", 41, 2)
        past["coverage_id"] = "ODC-812044"
        sofia["on_demand"] = {
            "plans": {"trip": {"destination": "Lisbon, Portugal", "depart": self.day(9), "return": self.day(16), "trip_cost_usd": 2400},
                      "drive": {"kind": "borrowed", "vehicle": "2021 Toyota RAV4", "start": self.day(1), "days": 3}},
            "coverages": [past]}
        sofia["history"] = {"customer_since": self.day(-210), "claims_count": 0}
        sofia["segments"] = seg("seg-travel-intent", "seg-occasional-drivers")
        sofia["ml_scores"].update(segment="Pay-as-you-go", next_best_action="activate_drive_cover", churn_risk=0.3, renewal_propensity=0.5,
                                  cross_sell_propensity=0.66, claim_risk=0.12, recommended_products=["travel", "renters"])
        self.n.update(saved)
        rows = [maya, daniel, sofia]
        for row, uid in zip(rows, PERSONAS):
            row["user_id"] = uid
        return rows

    def next_row(self) -> dict:
        x = self.r.random()
        return self.policyholder() if x < 0.62 else self.member() if x < 0.86 else self.ondemand()

    def coverage(self) -> list[dict]:
        """A few users in every group right after the personas, so even a
        small export (tests, the in-memory quick start) covers every group."""
        rows = []
        for code, g in C.GROUPS.items():
            for _ in range(4):
                if g["audience"] == "policyholder":
                    rows.append(self.policyholder(region=g["region"], group=code))
                elif g["audience"] == "member":
                    rows.append(self.member(lines=(g["line"],), group=code))
                else:
                    rows.append(self.ondemand(need=g["need"], group=code))
        return rows


def deep_update(base: dict, upd: dict):
    for k, v in upd.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            deep_update(base[k], v)
        else:
            base[k] = v


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--export-date", default=dt.date.today().isoformat())
    ap.add_argument("--target-mb", type=float, default=24.0, help="approximate total size in MiB")
    ap.add_argument("--parts", type=int, default=2, help="number of part files")
    ap.add_argument("--seed", type=int, default=20261113)
    ap.add_argument("--out", default=os.path.join(HERE, "..", "data", "insurance-export"))
    args = ap.parse_args(argv)

    export_date = dt.date.fromisoformat(args.export_date)
    g = Gen(export_date, args.seed)
    target = int(args.target_mb * 1024 * 1024)
    per_part = target // args.parts + 1
    out_dir = os.path.abspath(os.path.join(args.out, f"exportTime={export_date:%Y%m%d}"))
    os.makedirs(out_dir, exist_ok=True)
    for f in os.listdir(out_dir):
        if f.startswith("part-") or f in ("_SUCCESS", "_manifest.json"):
            os.remove(os.path.join(out_dir, f))

    job_uuid = uuid.UUID(int=g.r.getrandbits(128))
    written, rows = 0, 0
    by_audience = {a: 0 for a in AUDIENCES}
    files = []
    pending = g.personas() + g.coverage()
    for part in range(args.parts):
        name = f"part-{part:05d}-{job_uuid}-c000.json"
        part_bytes, part_rows = 0, 0
        with open(os.path.join(out_dir, name), "w", encoding="utf-8") as fh:
            while pending or (part_bytes < per_part and written < target):
                row = pending.pop(0) if pending else g.next_row()
                line = json.dumps(row, separators=(",", ":"), ensure_ascii=False) + "\n"
                b = len(line.encode("utf-8"))
                fh.write(line)
                part_bytes += b
                written += b
                part_rows += 1
                by_audience[row["audience"]] += 1
        rows += part_rows
        files.append({"file": name, "rows": part_rows, "bytes": part_bytes})
        print(f"  {name}  {part_rows:>7,} rows  {part_bytes / 1048576:6.1f} MiB", flush=True)

    manifest = {
        "system": "harborline-data-platform", "dataset": "insurance_people", "flow": "insurance-nightly-export",
        "sources": {"policyholder": "Policy administration + claims + telematics", "member": "Member platform", "ondemand": "On-demand platform"},
        "export_time": f"{export_date:%Y%m%d}", "export_date": export_date.isoformat(),
        "schema_version": SCHEMA_VERSION, "model_version": MODEL_VERSION,
        "format": "jsonl", "rows": rows, "by_audience": by_audience, "bytes": written, "files": files,
        "generator": "datagen/generate_mock_export.py", "seed": args.seed, "demo_personas": PERSONAS,
    }
    with open(os.path.join(out_dir, "_manifest.json"), "w") as fh:
        json.dump(manifest, fh, indent=2)
    open(os.path.join(out_dir, "_SUCCESS"), "w").close()
    print(f"Wrote {rows:,} people ({by_audience['policyholder']:,} policyholders, {by_audience['member']:,} members, "
          f"{by_audience['ondemand']:,} on-demand customers) = {written / 1048576:.1f} MiB to {out_dir}")


if __name__ == "__main__":
    main()
