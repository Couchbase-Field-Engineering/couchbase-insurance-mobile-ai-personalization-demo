#!/usr/bin/env python3
"""Register the Couchbase insurance demo with the Couchbase Agent Operations Manager.

Idempotent. Standard library only. Does five things through AOM's API, signed
in as an AOM dashboard admin:

  1. Registers this backend's MCP server `insurance-services` as a trusted
     server (POST /v1/servers) - or re-ingests it if it is already registered -
     so AOM pulls its 28 tools into the vetted catalog, open to the
     `support_agent` and `admin` roles.
  2. Issues seven agent identities (POST /v1/agents, role support_agent):
     **Harborline Assistant**, scoped to all 28 tools and written to ../.env as
     AOM_AGENT_API_KEY, and one specialist per area of the app - **Claims**,
     **Roadside**, **Billing**, **DriveWell**, **Wellness** and **Coverage**
     agents, each scoped to its own handful of tools. Their keys are written
     as one JSON map, AOM_SPECIALIST_AGENT_KEYS. A specialist runs every
     Confirm in its area and keeps the outcome in AOM Agent Memory. With
     --rotate, rotates the keys of existing agents instead.
  3. Turns on AOM's human-approval tier for
     `insurance-services::request_coverage_change` and
     `insurance-services::request_fee_waiver` (changes to who or what is
     covered wait for an underwriter, late-fee waivers for a billing
     supervisor), leaving every other approval setting as it was.
  4. Registers the app's two RAG Applications (POST /v1/rag/apps, or PUT if
     they exist), queryable by the `support_agent` and `admin` roles:
     `insurance-assistant`, scoped to the Help Center document, and
     `insurance-wellness`, scoped to the Member Care Guide. Their activity
     (queries, LLM cache hits, Context Cache retrievals) shows on AOM's RAG
     Applications page. The backend re-points them at each night's new
     documents after the load.
  5. Writes AOM_ADMIN_* into ../.env so the backend's nightly loader can
     publish Knowledge Base documents and manage the RAG applications.

    python scripts/register_with_aom.py --aom-url https://localhost:8090 \
        --admin-user admin --admin-password '<your AOM admin password>'
"""
from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import ssl
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(HERE, "..", ".env")
SERVER_ID = "insurance-services"
OWNER = "Harborline Digital"
# Keep in step with backend/app/actions.py (TOOLS, APPROVAL_TOOLS) and backend/app/agents.py (SPECIALISTS).
READ_TOOLS = ["get_customer_context", "get_policies", "get_claims", "get_roadside_status", "get_billing", "get_driving_summary",
              "get_wellness_summary", "get_coverage_options"]
WRITE_TOOLS = ["request_document", "update_contact_details", "request_policy_change", "request_coverage_change", "request_live_agent",
               "file_claim", "add_claim_evidence", "request_roadside", "send_sos", "make_payment", "set_autopay", "renew_policy",
               "request_fee_waiver", "enroll_telematics", "record_trip", "redeem_drive_discount", "book_telehealth", "submit_vet_bill",
               "link_wearable", "activate_coverage"]
TOOLS = READ_TOOLS + WRITE_TOOLS
APPROVAL_TOOLS = [f"{SERVER_ID}::request_coverage_change", f"{SERVER_ID}::request_fee_waiver"]
SPECIALIST_KEYS_ENV = "AOM_SPECIALIST_AGENT_KEYS"
_READ = ["get_customer_context", "get_policies"]
AGENTS = [
    {"name": "Harborline Assistant", "env": "AOM_AGENT_API_KEY", "tools": TOOLS,
     "description": ("The assistant in the Harborline insurance mobile app: answers about ID cards, claims, roadside, billing, "
                     "telematics, health and pet benefits and on-demand cover, and handles documents and support requests. RAG over "
                     "the nightly Help Center, Member Care Guide and per-person profiles.")},
    {"name": "Harborline Claims Agent", "agent_id": "insurance-claims-agent", "tools": _READ + ["get_claims", "file_claim", "add_claim_evidence"],
     "description": ("Harborline claims agent. Triggered when a customer files a claim or adds photos and documents in the mobile "
                     "app: recalls their claim history from Agent Memory, files the claim as a governed tool call and remembers the outcome.")},
    {"name": "Harborline Roadside Agent", "agent_id": "insurance-roadside-agent", "tools": _READ + ["get_roadside_status", "request_roadside", "send_sos"],
     "description": ("Harborline roadside and emergency agent. Triggered when a customer requests a tow, tire change or jump-start, "
                     "or raises an SOS: dispatches help to their GPS position and remembers what happened to which vehicle.")},
    {"name": "Harborline Billing Agent", "agent_id": "insurance-billing-agent",
     "tools": _READ + ["get_billing", "make_payment", "set_autopay", "renew_policy", "request_fee_waiver"],
     "description": ("Harborline billing agent. Triggered by a payment, an AutoPay change, a renewal or a late-fee waiver request "
                     "(which waits for a billing supervisor): processes it and remembers how the customer prefers to pay.")},
    {"name": "Harborline DriveWell Agent", "agent_id": "insurance-drive-agent",
     "tools": _READ + ["get_driving_summary", "enroll_telematics", "record_trip", "redeem_drive_discount"],
     "description": ("Harborline telematics agent. Triggered when a customer joins DriveWell, when the phone syncs a recorded trip "
                     "or when they redeem a safe-driver discount: scores the trip and remembers how their driving is trending.")},
    {"name": "Harborline Wellness Agent", "agent_id": "insurance-wellness-agent",
     "tools": _READ + ["get_wellness_summary", "book_telehealth", "submit_vet_bill", "link_wearable"],
     "description": ("Harborline health and pet agent, for members only. Triggered by a telehealth booking, a vet bill upload or a "
                     "wearable link: applies the plan's rules and remembers the visit or the pet's history.")},
    {"name": "Harborline Coverage Agent", "agent_id": "insurance-coverage-agent", "tools": _READ + ["get_coverage_options", "activate_coverage"],
     "description": ("Harborline on-demand coverage agent. Triggered when a customer buys short-term cover on the go - a borrowed "
                     "car, a rental, a trip: prices and activates it and remembers what they buy and when.")},
]
# Keep in step with backend/app/rag_app.py, which owns the definitions at runtime.
_RULES = ("Answer concisely (under 120 words) using only the numbered passages. Never invent premiums, coverage limits, "
          "deductibles, dates or claim outcomes. Cite the passages you used as [1], [2].")
RAG_APPS = [
    {"app_id": "insurance-assistant", "title_prefix": "Harborline Help Center", "name": "Harborline Assistant (all customers)",
     "description": ("Harborline's mobile assistant: ID cards and documents, claims, roadside and emergency help, payments and "
                     "renewals, DriveWell telematics, support and on-demand cover. Shared questions are answered here from the "
                     "nightly Help Center document. Personal answers use the asker's own profile, cached in the user-context namespace."),
     "system_prompt": ("You are the Harborline Assistant for insurance customers. " + _RULES +
                       " If the passages do not answer the question, offer to connect the person with a licensed agent."),
     "no_answer_text": "I couldn't find that in the Help Center. I can connect you with a licensed agent."},
    {"app_id": "insurance-wellness", "title_prefix": "Harborline Member Care Guide", "name": "Harborline Wellness (health & pet members)",
     "description": ("Harborline's mobile assistant, health and pet side: telehealth, deductibles and out-of-pocket limits, vet bill "
                     "reimbursement and wearable rewards. Scoped to the nightly Member Care Guide document; only signed-in members "
                     "of a health or pet plan are routed here."),
     "system_prompt": ("You are the Harborline Assistant for health and pet plan members. " + _RULES +
                       " You do not give medical advice; for symptoms, offer a telehealth visit. If the passages do not answer "
                       "the question, offer a licensed agent or the nurse line."),
     "no_answer_text": "I couldn't find that in the Member Care Guide. I can book a telehealth visit or connect you with an agent."},
]


def rag_app_definition(spec: dict, document_id):
    return {
        "app_id": spec["app_id"],
        "name": spec["name"],
        "description": spec["description"],
        "owner": OWNER,
        # Never enabled without a document scope: unscoped, a support_agent
        # query could retrieve any person's profile, or the other audience's knowledge.
        "enabled": bool(document_id),
        "allowed_roles": ["support_agent", "admin"],
        "set_id": "default",
        "document_ids": [document_id] if document_id else [],
        "top_k": 4,
        "retrieval_ttl_seconds": 6 * 3600,
        "semantic_cache": True,
        "system_prompt": spec["system_prompt"],
        "no_answer_text": spec["no_answer_text"],
    }


class Api:
    def __init__(self, base: str, verify: bool):
        self.base = base.rstrip("/")
        ctx = ssl.create_default_context()
        if not verify:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx),
                                                  urllib.request.HTTPCookieProcessor(self.jar))

    def call(self, method, path, body=None, ok=(200, 201, 202)):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            with self.opener.open(req, timeout=180) as r:
                txt = r.read().decode() or "{}"
                return r.status, json.loads(txt)
        except urllib.error.HTTPError as e:
            txt = e.read().decode()
            try:
                payload = json.loads(txt)
            except json.JSONDecodeError:
                payload = {"detail": txt}
            if e.code in ok:
                return e.code, payload
            return e.code, payload


def set_env(updates: dict):
    lines = open(ENV_PATH).read().splitlines() if os.path.exists(ENV_PATH) else []
    seen = set()
    for i, line in enumerate(lines):
        k = line.split("=", 1)[0].strip()
        if k in updates:
            lines[i] = f"{k}={updates[k]}"
            seen.add(k)
    lines += [f"{k}={v}" for k, v in updates.items() if k not in seen]
    with open(ENV_PATH, "w") as fh:
        fh.write("\n".join(lines) + "\n")


def read_env(key: str) -> str:
    if not os.path.exists(ENV_PATH):
        return ""
    for line in open(ENV_PATH).read().splitlines():
        if line.split("=", 1)[0].strip() == key and "=" in line:
            return line.split("=", 1)[1].strip().strip("'")
    return ""


def die(msg):
    print(f"\n✗ {msg}", file=sys.stderr)
    sys.exit(1)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--aom-url", default=os.getenv("AOM_URL_HOST", "https://localhost:8090"),
                    help="AOM as reachable from THIS machine")
    ap.add_argument("--admin-user", default=os.getenv("AOM_ADMIN_USERNAME", "admin"))
    ap.add_argument("--admin-password", default=os.getenv("AOM_ADMIN_PASSWORD"))
    ap.add_argument("--mcp-url", default="http://host.docker.internal:8204/ins/mcp",
                    help="this backend's MCP endpoint as reachable FROM the AOM container")
    ap.add_argument("--aom-url-for-backend", default="https://host.docker.internal:8090",
                    help="AOM as reachable from the demo backend container (written to .env)")
    ap.add_argument("--rotate", action="store_true", help="rotate the agent keys if the agents already exist")
    ap.add_argument("--verify-tls", action="store_true")
    args = ap.parse_args()
    if not args.admin_password:
        die("Pass --admin-password (the AOM dashboard admin password you set at first login)")

    api = Api(args.aom_url, args.verify_tls)
    print(f"→ Signing in to AOM at {args.aom_url} as {args.admin_user}")
    st, body = api.call("POST", "/v1/auth/login", {"username": args.admin_user, "password": args.admin_password})
    if st != 200:
        die(f"AOM login failed ({st}): {body.get('detail')}")

    # 1. MCP server ----------------------------------------------------------
    print(f"→ Registering MCP server '{SERVER_ID}' at {args.mcp_url}")
    st, body = api.call("POST", "/v1/servers", {
        "server_id": SERVER_ID, "label": "Harborline Insurance Services", "owner": OWNER, "mcp_url": args.mcp_url,
        "trust_status": "trusted", "default_allowed_roles": ["support_agent", "admin"],
    })
    if st == 409:
        st, body = api.call("POST", f"/v1/servers/{SERVER_ID}/reingest")
        if st != 200:
            die(f"Re-ingest failed ({st}): {body.get('detail')}")
        print(f"  already registered - re-ingested {body.get('ingested_tools')} tools")
    elif st == 200:
        if body.get("ingest_error"):
            die(f"Registered, but AOM could not reach {args.mcp_url}: {body['ingest_error']}\n"
                "  Is the demo backend running (docker compose up) and reachable from the AOM container?")
        print(f"  registered - {body.get('ingested_tools')} tools ingested into the vetted catalog")
    else:
        die(f"Server registration failed ({st}): {body.get('detail')}")

    # 2. agent identities -------------------------------------------------------
    st, body = api.call("GET", "/v1/agents")
    if st != 200:
        die(f"Listing agents failed ({st}): {body.get('detail')}")
    agents = body.get("agents", [])
    updates = {"AOM_URL": args.aom_url_for_backend, "AOM_ADMIN_USERNAME": args.admin_user,
               "AOM_ADMIN_PASSWORD": args.admin_password}
    try:
        specialist_keys = json.loads(read_env(SPECIALIST_KEYS_ENV) or "{}")
    except json.JSONDecodeError:
        specialist_keys = {}

    def keep(spec, key):
        if spec.get("env"):
            updates[spec["env"]] = key
        else:
            specialist_keys[spec["agent_id"]] = key

    for spec in AGENTS:
        existing = next((a for a in agents if a.get("name") == spec["name"] and a.get("status") == "active"), None)
        if existing and args.rotate:
            print(f"→ Rotating key for agent '{spec['name']}' ({existing['agent_id']})")
            st, body = api.call("POST", f"/v1/agents/{existing['agent_id']}/rotate", {"revoke_immediately": False})
            if st != 200:
                die(f"Rotate failed ({st}): {body.get('detail')}")
            keep(spec, body["api_key"])
        elif existing:
            print(f"  agent '{spec['name']}' already exists ({existing['agent_id']}); keeping its key (use --rotate for a new one)")
        else:
            print(f"→ Issuing agent identity '{spec['name']}' (role support_agent, {len(spec['tools'])} scoped tools)")
            st, body = api.call("POST", "/v1/agents", {
                "name": spec["name"], "role": "support_agent", "owner": OWNER, "description": spec["description"],
                "allowed_tools": [f"{SERVER_ID}::{t}" for t in spec["tools"]],
            })
            if st != 200:
                die(f"Agent creation failed ({st}): {body.get('detail')}")
            keep(spec, body["api_key"])
            print(f"  agent {body['agent']['agent_id']} issued")
    missing = [a["name"] for a in AGENTS if a.get("agent_id") and a["agent_id"] not in specialist_keys]
    if missing:
        print(f"  ! no key on file for {', '.join(missing)} - they will run as the assistant; re-run with --rotate to issue new keys")
    if specialist_keys:
        # single-quoted so docker compose's env_file passes the JSON through untouched
        updates[SPECIALIST_KEYS_ENV] = "'" + json.dumps(specialist_keys, separators=(",", ":")) + "'"

    # 3. approval tier ---------------------------------------------------------------
    st, body = api.call("GET", "/v1/approvals-config")
    if st == 200:
        cfg = body["config"]
        cfg["enabled"] = True
        cfg["require_for_tools"] = sorted(set(cfg.get("require_for_tools") or []) | set(APPROVAL_TOOLS))
        st, body = api.call("PUT", "/v1/approvals-config", {"config": cfg})
        print("→ Approval tier: coverage changes and late-fee waivers now wait for a person" if st == 200
              else f"  ! could not update approvals ({st}): {body.get('detail')}")

    # 4. RAG applications ------------------------------------------------------------
    st, kb = api.call("GET", "/v1/knowledge")
    docs = (kb.get("documents") or []) if st == 200 else []
    for spec in RAG_APPS:
        mine = sorted((d for d in docs if str(d.get("title", "")).startswith(spec["title_prefix"])),
                      key=lambda d: str(d.get("created_at") or d.get("ingested_at") or d.get("title")))
        doc_id = mine[-1].get("document_id") if mine else None
        app = rag_app_definition(spec, doc_id)
        print(f"→ Registering RAG application '{spec['app_id']}'")
        st, body = api.call("POST", "/v1/rag/apps", {"app": app, "issue_key": False})
        verb = "registered"
        if st == 409:
            st, body = api.call("PUT", f"/v1/rag/apps/{spec['app_id']}", {"app": app})
            verb = "updated"
        if st == 200:
            if doc_id:
                print(f"  {verb}, scoped to {spec['title_prefix']} document {doc_id}")
            else:
                print(f"  {verb} (disabled until the backend publishes today's {spec['title_prefix']} to the Knowledge Base;\n"
                      "  the backend enables it and scopes it to that document on its next load)")
        elif st in (404, 405):
            print("  ! this AOM build has no RAG Applications API - update AOM to see the app there")
            break
        else:
            print(f"  ! RAG application registration failed ({st}): {body.get('detail')}")

    # 5. .env + reload -----------------------------------------------------------------
    set_env(updates)
    print(f"→ Wrote {', '.join(updates)} to {os.path.abspath(ENV_PATH)}")
    if updates.get("AOM_AGENT_API_KEY"):
        print(f"\n  Agent API key (shown once by AOM, now in .env): {updates['AOM_AGENT_API_KEY'][:10]}…")
    print("\nNext: docker compose up -d --build backend   (rebuilds and recreates the backend with the new .env;\n"
          "      it publishes the Knowledge Base to AOM and scopes the RAG applications to today's documents)")


if __name__ == "__main__":
    main()
