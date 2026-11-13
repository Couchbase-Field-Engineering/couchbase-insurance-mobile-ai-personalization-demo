"""Harborline's specialist agents - one AOM agent identity per use case.

The **Harborline Assistant** answers in chat and handles ID cards, documents
and support requests itself. Everything else a person confirms in the app
is handed by the worker to the specialist that owns that part of the
business:

| agent                         | triggered by (the `requests` document's tool)              |
|-------------------------------|------------------------------------------------------------|
| Harborline Claims Agent       | file_claim, add_claim_evidence                             |
| Harborline Roadside Agent     | request_roadside, send_sos                                 |
| Harborline Billing Agent      | make_payment, set_autopay, renew_policy, request_fee_waiver|
| Harborline DriveWell Agent    | enroll_telematics, record_trip, redeem_drive_discount      |
| Harborline Wellness Agent     | book_telehealth, submit_vet_bill, link_wearable            |
| Harborline Coverage Agent     | activate_coverage                                          |

One request = one AOM run, attributed to that agent on AOM's Agents, Traces
and Audit pages and limited to its own tool scope: the Billing Agent cannot
file a claim and the Roadside Agent cannot take a payment, whatever it is
asked to do.

What makes each one an agent rather than a tool call is **AOM Agent Memory**:

1. Before processing it recalls what AOM already remembers about this
   customer in its own domain (`POST /v1/memory/search`): earlier claims,
   where the car broke down last time, how they like to pay.
2. After the action it writes an episodic memory (`POST /v1/memory`) of what
   happened, so the assistant - which recalls the same memories on its next
   turn - can say "that's the second flat on the Outback this year".

Agent keys are issued by scripts/register_with_aom.py (written to `.env` as
the JSON map `AOM_SPECIALIST_AGENT_KEYS`) or by aom_bootstrap.py. A specialist
without a key runs as the assistant, without memory.
"""
from __future__ import annotations

import logging

from . import tool_gateway
from .aom_client import AOMError, specialist_client
from .store import store
from .docs import profile_id

log = logging.getLogger("insurance.agents")

ASSISTANT_ID = "insurance-assistant"
_READ = ["get_customer_context", "get_policies"]

SPECIALISTS: dict[str, dict] = {
    "insurance-claims-agent": {
        "name": "Harborline Claims Agent", "short": "Claims Agent", "area": "claims", "memory_label": "Claim history",
        "triggers": ["file_claim", "add_claim_evidence"], "tools": _READ + ["get_claims", "file_claim", "add_claim_evidence"],
        "recall": "claim accident damage loss photos adjuster repair shop",
        "description": ("Harborline claims agent. Triggered when a customer files a claim or adds photos and documents in the mobile "
                        "app: recalls their claim history from Agent Memory, files the claim as a governed tool call and remembers the outcome."),
    },
    "insurance-roadside-agent": {
        "name": "Harborline Roadside Agent", "short": "Roadside Agent", "area": "roadside", "memory_label": "Roadside history",
        "triggers": ["request_roadside", "send_sos"], "tools": _READ + ["get_roadside_status", "request_roadside", "send_sos"],
        "recall": "roadside tow flat tire battery breakdown emergency location vehicle",
        "description": ("Harborline roadside and emergency agent. Triggered when a customer requests a tow, tire change or jump-start, "
                        "or raises an SOS: dispatches help to their GPS position and remembers what happened to which vehicle."),
    },
    "insurance-billing-agent": {
        "name": "Harborline Billing Agent", "short": "Billing Agent", "area": "billing", "memory_label": "Billing history",
        "triggers": ["make_payment", "set_autopay", "renew_policy", "request_fee_waiver"],
        "tools": _READ + ["get_billing", "make_payment", "set_autopay", "renew_policy", "request_fee_waiver"],
        "recall": "payment autopay renewal premium late fee waiver pay in full",
        "description": ("Harborline billing agent. Triggered by a payment, an AutoPay change, a renewal or a late-fee waiver request "
                        "(which waits for a billing supervisor): processes it and remembers how the customer prefers to pay."),
    },
    "insurance-drive-agent": {
        "name": "Harborline DriveWell Agent", "short": "DriveWell Agent", "area": "telematics", "memory_label": "Driving history",
        "triggers": ["enroll_telematics", "record_trip", "redeem_drive_discount"],
        "tools": _READ + ["get_driving_summary", "enroll_telematics", "record_trip", "redeem_drive_discount"],
        "recall": "driving score trip miles braking speeding discount telematics",
        "description": ("Harborline telematics agent. Triggered when a customer joins DriveWell, when the phone syncs a recorded trip "
                        "or when they redeem a safe-driver discount: scores the trip and remembers how their driving is trending."),
    },
    "insurance-wellness-agent": {
        "name": "Harborline Wellness Agent", "short": "Wellness Agent", "area": "wellness", "memory_label": "Health and pet history",
        "triggers": ["book_telehealth", "submit_vet_bill", "link_wearable"],
        "tools": _READ + ["get_wellness_summary", "book_telehealth", "submit_vet_bill", "link_wearable"],
        "recall": "telehealth visit vet bill pet deductible wearable steps",
        "description": ("Harborline health and pet agent, for members only. Triggered by a telehealth booking, a vet bill upload or a "
                        "wearable link: applies the plan's rules and remembers the visit or the pet's history."),
    },
    "insurance-coverage-agent": {
        "name": "Harborline Coverage Agent", "short": "Coverage Agent", "area": "coverage", "memory_label": "On-demand cover history",
        "triggers": ["activate_coverage"], "tools": _READ + ["get_coverage_options", "activate_coverage"],
        "recall": "on-demand cover borrowed car rental trip travel destination short-term",
        "description": ("Harborline on-demand coverage agent. Triggered when a customer buys short-term cover on the go - a borrowed "
                        "car, a rental, a trip: prices and activates it and remembers what they buy and when."),
    },
}
ASSISTANT_TOOLS_ONLY = ["request_document", "update_contact_details", "request_policy_change", "request_coverage_change", "request_live_agent"]
AGENT_OF_TOOL = {t: aid for aid, a in SPECIALISTS.items() for t in a["triggers"]}
SHORT_NAME = {ASSISTANT_ID: "Harborline Assistant", **{aid: a["short"] for aid, a in SPECIALISTS.items()}}


def agent_for(tool: str) -> str:
    """Which agent identity runs a request for this tool."""
    return AGENT_OF_TOOL.get(tool, ASSISTANT_ID)


def enabled(agent_id: str) -> bool:
    return specialist_client(agent_id).enabled


async def recall(agent_id: str, user_id: str) -> list[str]:
    if not enabled(agent_id):
        return []
    try:
        res = await specialist_client(agent_id).memory_search(user_id, SPECIALISTS[agent_id]["recall"], top_k=4)
        return [e.get("content", "") for e in res.get("entries", []) if e.get("content")]
    except AOMError as exc:
        log.info("memory search skipped: %s", exc)
        return []


def _episode(agent_id: str, profile: dict, result: dict) -> str:
    a = SPECIALISTS[agent_id]
    item = result.get("item") or {}
    lines = sorted({x["line"] for x in profile.get("policies", []) if x.get("status") == "active"})
    return (f"{a['memory_label']}: {item.get('title') or 'request processed'} on {item.get('date')}. "
            f"{(result.get('summary') or '').strip()[:320]}" + (f" Customer holds {', '.join(lines)} cover." if lines else ""))


async def run(doc: dict, args: dict, approval_id: str | None = None) -> dict:
    """Process one request as its specialist agent. Returns the tool result
    plus `agent`, `memories_recalled` and `remembered`."""
    user_id, tool = doc.get("user_id"), doc.get("tool")
    agent_id = agent_for(tool)
    a = SPECIALISTS[agent_id]
    on = enabled(agent_id)
    memories = await recall(agent_id, user_id)
    result = await tool_gateway.invoke(tool, args, approval_id=approval_id, client=specialist_client(agent_id) if on else None)
    result.update({"agent": agent_id, "memories_recalled": len(memories), "remembered": False})

    if result.get("ok") and result.get("status") in ("ok", "confirmed", "accepted", "submitted") and on:
        try:
            after = await store.get("profiles", profile_id(user_id)) or {}
            await specialist_client(agent_id).memory_add(
                user_id, _episode(agent_id, after, result), session_id=doc.get("session_id"), memory_type="episodic",
                metadata={"agent": agent_id, "tool": tool, "area": a["area"], "trace_id": result.get("trace_id"), "app": "insurance-mobile"})
            result["remembered"] = True
        except AOMError as exc:
            log.info("memory add skipped: %s", exc)
    if memories and result.get("summary"):
        last = next((m for m in memories if m.startswith(a["memory_label"] + ":")), None)
        if last:
            note = last[len(a["memory_label"]) + 2:].split(". ")[0].rstrip(".")
            result["summary"] += f" (The {a['short'].lower()} remembered: {note}.)"
    return result
