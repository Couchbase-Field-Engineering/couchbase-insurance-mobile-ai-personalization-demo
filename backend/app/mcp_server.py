"""`insurance-services` - the MCP server registered with AOM.

Streamable HTTP at /ins/mcp/. AOM ingests these tool definitions into its
vetted catalog (embeddings for discovery, RBAC per role, drift detection)
and is the only caller the demo expects: the app, the assistant and the
specialist agents reach these tools through `POST /v1/tools/invoke`, never
directly.

Business errors (no policy of that line, a slot just taken, nothing due)
come back as `{"ok": false, ...}` results rather than MCP errors, so AOM
records a completed call and the person gets a useful message instead of a
gateway failure.
"""
from __future__ import annotations

import logging

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from . import actions

log = logging.getLogger("insurance.mcp")

mcp = FastMCP(
    "insurance-services",
    instructions=("Harborline insurance services, one tool set for the mobile app's agents: digital ID cards and policy "
                  "documents; claim filing, evidence and tracking; roadside dispatch and SOS; premium payments, AutoPay and "
                  "renewals; DriveWell telematics; contact and policy changes and hand-off to a licensed agent; telehealth, "
                  "vet bills and wearables for health and pet members; and on-demand short-term cover."),
    stateless_http=True,
    # Called by AOM over the Docker host gateway, so the Host header is not
    # localhost; same reasoning as AOM's own bundled sample servers.
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


async def _run(fn, **kw) -> dict:
    try:
        res = await fn(**kw)
    except actions.ToolError as exc:
        return {"ok": False, "status": "failed", "summary": str(exc)}
    return res if isinstance(res, dict) and "ok" in res else {"ok": True, "status": "ok", "data": res}


# ---- read ---------------------------------------------------------------------
@mcp.tool()
async def get_customer_context(user_id: str) -> dict:
    """Read who a Harborline customer is: contact details, active policies, open claims, amount due, segment and next best action."""
    return await _run(actions.get_customer_context, user_id=user_id)


@mcp.tool()
async def get_policies(user_id: str) -> dict:
    """List a customer's policies with coverages, vehicles or property, digital ID cards and policy documents, plus on-demand cover certificates."""
    return await _run(actions.get_policies, user_id=user_id)


@mcp.tool()
async def get_claims(user_id: str, claim_id: str = "") -> dict:
    """List a customer's claims with status, adjuster, evidence received, estimate, payout and next step, and the policies a new claim can be filed on."""
    return await _run(actions.get_claims, user_id=user_id, claim_id=claim_id)


@mcp.tool()
async def get_roadside_status(user_id: str) -> dict:
    """Read how a customer's next roadside call is covered (included, on-demand or pay-per-use), their vehicles, last known location and any truck on the way."""
    return await _run(actions.get_roadside_status, user_id=user_id)


@mcp.tool()
async def get_billing(user_id: str) -> dict:
    """Read premiums per policy: next due date, amount due, late fees, AutoPay, recent payments and renewal offers."""
    return await _run(actions.get_billing, user_id=user_id)


@mcp.tool()
async def get_driving_summary(user_id: str) -> dict:
    """Read a customer's DriveWell telematics: program, driving score and factors, miles, recent trips and the renewal discount earned."""
    return await _run(actions.get_driving_summary, user_id=user_id)


@mcp.tool()
async def get_wellness_summary(user_id: str) -> dict:
    """Read a health or pet member's deductible progress, telehealth visits and open appointments, vet bills and wearable rewards. Members only."""
    return await _run(actions.get_wellness_summary, user_id=user_id)


@mcp.tool()
async def get_coverage_options(user_id: str) -> dict:
    """List on-demand short-term cover (borrowed car, rental car, trip protection, one-day event) with a quote for the customer's plans, and cover already active."""
    return await _run(actions.get_coverage_options, user_id=user_id)


# ---- documents and support --------------------------------------------------------
@mcp.tool()
async def request_document(user_id: str, policy_id: str, doc_type: str, delivery: str = "app", recipient: str = "") -> dict:
    """Issue a policy document: id_card, declarations, policy_booklet, proof_of_insurance, lender_letter (needs recipient), claims_history or benefits_summary. delivery app, email or mail."""
    return await _run(actions.request_document, user_id=user_id, policy_id=policy_id, doc_type=doc_type, delivery=delivery, recipient=recipient)


@mcp.tool()
async def update_contact_details(user_id: str, email: str = "", phone: str = "", address: str = "") -> dict:
    """Update a customer's email, phone or mailing address (give at least one)."""
    return await _run(actions.update_contact_details, user_id=user_id, email=email, phone=phone, address=address)


@mcp.tool()
async def request_policy_change(user_id: str, policy_id: str, change: str, details: str) -> dict:
    """Apply a simple policy update that doesn't change coverage or price: add_rental, update_mortgagee or name_correction, with details."""
    return await _run(actions.request_policy_change, user_id=user_id, policy_id=policy_id, change=change, details=details)


@mcp.tool()
async def request_coverage_change(user_id: str, policy_id: str, change: str, details: str) -> dict:
    """Change who or what is covered: add_driver, remove_driver, add_vehicle, change_deductible or raise_liability. Requires details; held for underwriting approval."""
    return await _run(actions.request_coverage_change, user_id=user_id, policy_id=policy_id, change=change, details=details)


@mcp.tool()
async def request_live_agent(user_id: str, topic: str, channel: str = "chat", note: str = "") -> dict:
    """Hand the conversation to a licensed human agent by chat, callback or video, with the topic and context."""
    return await _run(actions.request_live_agent, user_id=user_id, topic=topic, channel=channel, note=note)


# ---- claims -------------------------------------------------------------------------
@mcp.tool()
async def file_claim(user_id: str, policy_id: str, loss_type: str, loss_date: str, description: str, location: str = "",
                     photos: int = 0, videos: int = 0, police_report: bool = False, drivable: bool = True) -> dict:
    """File a claim on an auto, home or renters policy. loss_type e.g. collision, glass, weather, theft, vandalism, water, wind_hail, fire; loss_date YYYY-MM-DD; photos and videos are the counts captured in the app."""
    return await _run(actions.file_claim, user_id=user_id, policy_id=policy_id, loss_type=loss_type, loss_date=loss_date,
                      description=description, location=location, photos=photos, videos=videos, police_report=police_report, drivable=drivable)


@mcp.tool()
async def add_claim_evidence(user_id: str, claim_id: str, kind: str = "photo", count: int = 1, note: str = "") -> dict:
    """Attach evidence to an open claim: photo, video, police_report, receipt or estimate."""
    return await _run(actions.add_claim_evidence, user_id=user_id, claim_id=claim_id, kind=kind, count=count, note=note)


# ---- roadside and emergency -----------------------------------------------------------
@mcp.tool()
async def request_roadside(user_id: str, service: str, vehicle_id: str = "", location: str = "", lat: float = 0.0, lon: float = 0.0,
                           note: str = "") -> dict:
    """Dispatch roadside assistance to the customer's GPS position or a typed location: tow, flat, jump, lockout or fuel."""
    return await _run(actions.request_roadside, user_id=user_id, service=service, vehicle_id=vehicle_id, location=location, lat=lat, lon=lon, note=note)


@mcp.tool()
async def send_sos(user_id: str, kind: str, location: str = "", lat: float = 0.0, lon: float = 0.0, note: str = "") -> dict:
    """Raise an emergency with the 24/7 desk and share the customer's location: accident, medical or travel."""
    return await _run(actions.send_sos, user_id=user_id, kind=kind, location=location, lat=lat, lon=lon, note=note)


# ---- payments and renewals --------------------------------------------------------------
@mcp.tool()
async def make_payment(user_id: str, policy_id: str = "", amount_usd: float = 0, method: str = "card on file") -> dict:
    """Pay a premium. Blank policy_id pays the policy due first; amount 0 pays the amount due. method is 'card on file' or 'bank account'."""
    return await _run(actions.make_payment, user_id=user_id, policy_id=policy_id, amount_usd=amount_usd, method=method)


@mcp.tool()
async def set_autopay(user_id: str, policy_id: str = "", enabled: bool = True, day: int = 0) -> dict:
    """Turn AutoPay on or off for a monthly policy, optionally on a day of the month (1-28)."""
    return await _run(actions.set_autopay, user_id=user_id, policy_id=policy_id, enabled=enabled, day=day)


@mcp.tool()
async def renew_policy(user_id: str, policy_id: str = "", pay_plan: str = "monthly") -> dict:
    """Accept a renewal offer. pay_plan is 'monthly' or 'pay_in_full' (6% off, charged now)."""
    return await _run(actions.renew_policy, user_id=user_id, policy_id=policy_id, pay_plan=pay_plan)


@mcp.tool()
async def request_fee_waiver(user_id: str, policy_id: str, reason: str) -> dict:
    """Waive a late fee (up to $50, once a year) as a goodwill gesture. Requires a reason; held for a billing supervisor's approval."""
    return await _run(actions.request_fee_waiver, user_id=user_id, policy_id=policy_id, reason=reason)


# ---- telematics ------------------------------------------------------------------------------
@mcp.tool()
async def enroll_telematics(user_id: str, vehicle_id: str = "", program: str = "safe-driver", device: str = "phone") -> dict:
    """Join DriveWell usage-based insurance: program 'safe-driver' or 'pay-per-mile'; device 'phone', 'plug-in beacon' or 'connected car'."""
    return await _run(actions.enroll_telematics, user_id=user_id, vehicle_id=vehicle_id, program=program, device=device)


@mcp.tool()
async def record_trip(user_id: str, miles: float, minutes: int, hard_brakes: int = 0, speeding_events: int = 0, night: bool = False,
                      phone_use: int = 0, trip_date: str = "") -> dict:
    """Record one trip summary from the phone's sensors or the beacon and update the DriveWell score and mileage."""
    return await _run(actions.record_trip, user_id=user_id, miles=miles, minutes=minutes, hard_brakes=hard_brakes,
                      speeding_events=speeding_events, night=night, phone_use=phone_use, trip_date=trip_date)


@mcp.tool()
async def redeem_drive_discount(user_id: str) -> dict:
    """Apply the safe-driver discount a DriveWell score has earned to the customer's auto renewal offer."""
    return await _run(actions.redeem_drive_discount, user_id=user_id)


# ---- health and wellness (members) ---------------------------------------------------------------
@mcp.tool()
async def book_telehealth(user_id: str, date: str, time: str, visit_type: str = "primary", reason: str = "") -> dict:
    """Book a telehealth video visit for a member. date YYYY-MM-DD, time HH:MM, visit_type primary, urgent, mental, derm or vet."""
    return await _run(actions.book_telehealth, user_id=user_id, date=date, time=time, visit_type=visit_type, reason=reason)


@mcp.tool()
async def submit_vet_bill(user_id: str, pet_id: str, amount_usd: float, clinic: str, visit_date: str, reason: str, photos: int = 1) -> dict:
    """Submit a veterinary invoice for reimbursement under a pet plan: the pet, bill total, clinic, visit date, reason and photos of the invoice."""
    return await _run(actions.submit_vet_bill, user_id=user_id, pet_id=pet_id, amount_usd=amount_usd, clinic=clinic,
                      visit_date=visit_date, reason=reason, photos=photos)


@mcp.tool()
async def link_wearable(user_id: str, device: str) -> dict:
    """Link a wearable (Apple Watch, Fitbit, Garmin, Oura Ring, Google Pixel Watch) to a health member's wellness rewards."""
    return await _run(actions.link_wearable, user_id=user_id, device=device)


# ---- on-demand coverage ------------------------------------------------------------------------------
@mcp.tool()
async def activate_coverage(user_id: str, product: str, start_date: str = "", days: int = 1, vehicle: str = "", destination: str = "",
                            trip_cost_usd: float = 0) -> dict:
    """Buy and activate short-term cover: borrow-car (needs vehicle), rental-car, travel (needs destination, optional trip cost) or event-day. Starts today when start_date is blank."""
    return await _run(actions.activate_coverage, user_id=user_id, product=product, start_date=start_date, days=days, vehicle=vehicle,
                      destination=destination, trip_cost_usd=trip_cost_usd)
