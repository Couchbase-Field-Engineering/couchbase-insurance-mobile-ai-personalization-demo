"""The AOM-governed path, against tests/fake_aom.py (same routes and shapes as
the real AOM): KB publishing, document-scoped retrieval, two RAG applications
that keep general and member-only knowledge apart, LLM cache across users,
tool calls over real MCP, the human-approval tier and the specialist agents.
"""
import json
import os
import subprocess
import sys
import time
import uuid

import httpx
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BACKEND = os.path.join(ROOT, "backend")
AOM, API = "http://127.0.0.1:18094", "http://127.0.0.1:18204"
MAYA, DANIEL, SOFIA = ("5510101", "Chen"), ("5520202", "Okafor"), ("5530303", "Alvarez")
KEY = {"Authorization": "Bearer fake-agent-key"}
SPECIALISTS = ["insurance-claims-agent", "insurance-roadside-agent", "insurance-billing-agent", "insurance-drive-agent",
               "insurance-wellness-agent", "insurance-coverage-agent"]


def wait(url, tries=80):
    for _ in range(tries):
        try:
            if httpx.get(url, timeout=1).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.25)
    raise RuntimeError(f"{url} never came up")


@pytest.fixture(scope="module")
def stack(tmp_path_factory):
    dump = tmp_path_factory.mktemp("dump")
    subprocess.run([sys.executable, os.path.join(ROOT, "datagen", "generate_mock_export.py"), "--export-date",
                    "2026-11-13", "--target-mb", "2", "--out", str(dump)], check=True, capture_output=True)
    env = {**os.environ, "STORE_DRIVER": "memory", "EXPORT_DIR": str(dump), "SOR_MOCK_LATENCY_MS": "1,2", "AOM_URL": AOM,
           "AOM_AGENT_API_KEY": "fake-agent-key", "AOM_SPECIALIST_AGENT_KEYS": json.dumps({a: "fake-agent-key" for a in SPECIALISTS}),
           "AOM_ADMIN_PASSWORD": "x",
           "KB_PROFILE_LIMIT": "10", "SG_ADMIN_URL": "", "REQUEST_POLL_SECONDS": "0.3", "FAKE_MCP_URL": f"{API}/ins/mcp"}
    uv = [sys.executable, "-m", "uvicorn"]
    procs = [subprocess.Popen(uv + ["tests.fake_aom:app", "--port", "18094"], cwd=BACKEND, env=env,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)]
    wait(f"{AOM}/api/health")
    procs.append(subprocess.Popen(uv + ["app.main:app", "--port", "18204"], cwd=BACKEND, env=env,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    wait(f"{API}/api/health")
    for _ in range(60):
        st = httpx.get(f"{API}/api/status").json()
        if (st["load"].get("kb") or {}).get("state") == "published":
            break
        time.sleep(0.25)
    yield
    for p in procs:
        p.terminate()


def login(account, last):
    r = httpx.post(f"{API}/api/auth/login", json={"account_id": account, "last_name": last})
    return {"Authorization": f"Bearer {r.json()['token']}"}, r.json()["user_id"]


def ask(h, q):
    return httpx.post(f"{API}/api/chat", headers=h, json={"message": q}, timeout=30).json()


def state():
    return httpx.get(f"{AOM}/test/state").json()


def push(h, uid, tool, args, until=("confirmed", "failed", "submitted")):
    rid = f"req::{uid}::{uuid.uuid4().hex[:8]}"
    httpx.post(f"{API}/api/sync/push", headers=h, json={"docs": [{"collection": "requests", "id": rid, "doc": {
        "type": "request", "user_id": uid, "tool": tool, "title": tool, "args": args, "created_at": "2026-11-13T15:00:00Z"}}]})

    def req():
        docs = httpx.get(f"{API}/api/sync/pull", headers=h).json()["docs"]
        return next(d["doc"] for d in docs if d["id"] == rid)

    for _ in range(40):
        if req()["status"] in until:
            break
        time.sleep(0.2)
    return req(), req


def test_kb_published_and_scoped(stack):
    titles = list(state()["docs"].values())
    assert any(t.startswith("Harborline Help Center") for t in titles)
    assert any(t.startswith("Harborline Member Care Guide") for t in titles)
    assert any("P00000101" in t for t in titles)
    h, _ = login(*MAYA)
    a = ask(h, "What's the status of my claim?")
    assert a["context"]["kb_mode"] == "aom" and a["governed"]
    searched = [c[1] for c in state()["calls"] if c[0] == "kb_search"]
    assert all(d is not None for d in searched), "every KB search must be scoped to one document"


def test_two_rag_applications_keep_knowledge_apart(stack):
    st = state()
    helpcenter = [d for d, t in st["docs"].items() if t.startswith("Harborline Help Center")]
    guide = [d for d, t in st["docs"].items() if t.startswith("Harborline Member Care Guide")]
    cust, well = st["rag_apps"]["insurance-assistant"], st["rag_apps"]["insurance-wellness"]
    assert cust["enabled"] and cust["document_ids"] == helpcenter
    assert well["enabled"] and well["document_ids"] == guide
    assert set(cust["allowed_roles"]) == {"support_agent", "admin"}

    hm, _ = login(*MAYA)
    q = "How does roadside assistance work?"
    a, b = ask(hm, q), ask(hm, q)
    assert a["context"]["source"] == "aom-rag" and a["llm"]["rag_app"] == "insurance-assistant"
    assert b["context"]["status"] == "hit" and b["llm"]["status"] == "hit_exact"
    assert "25 to 40 minutes" in a["reply"] and a["sources"]

    hd, _ = login(*DANIEL)
    w = ask(hd, "How do telehealth visits work?")
    assert w["context"]["rag_app"] == "insurance-wellness" and "no copay" in w["reply"]
    # a member's general question still goes to the general app
    assert ask(hd, "How does AutoPay work?")["context"]["rag_app"] == "insurance-assistant"

    before = len([c for c in state()["calls"] if c[0] in ("rag_query", "kb_search", "llm")])
    r = ask(hm, "How do I get a vet bill reimbursed?")
    assert r["restricted"] and "members" in r["reply"]
    assert len([c for c in state()["calls"] if c[0] in ("rag_query", "kb_search", "llm")]) == before, "the gate retrieves nothing"

    rag = [c for c in state()["calls"] if c[0] == "rag_query"]
    assert all(set(c[3]) <= set(helpcenter) for c in rag if c[1] == "insurance-assistant")
    assert all(set(c[3]) <= set(guide) for c in rag if c[1] == "insurance-wellness")


def test_llm_cache_shared_for_shared_questions_only(stack):
    h1, _ = login(*MAYA)
    h2, _ = login(*DANIEL)
    a = ask(h1, "How do I file a claim?")
    b = ask(h2, "How do I file a claim?")
    assert a["personal"] is False and b["llm"]["status"] == "hit_exact"
    p1 = ask(h1, "Show me my insurance card")
    p2 = ask(h2, "Show me my insurance card")
    assert p1["llm"]["namespace"] == "rag:insurance-assistant:personal" and p2["llm"]["status"] == "miss"


def test_personal_context_cached_in_aom_per_app(stack):
    h, uid = login(*MAYA)
    q = "When is my next payment due?"
    first, second = ask(h, q), ask(h, q)
    assert first["context"]["status"] in ("miss", "hit")
    assert second["context"]["status"] == "hit" and second["context"]["source"] == "aom"
    sets = [c for c in state()["calls"] if c[0] == "ctx_set" and c[2].startswith(f"{uid}:billing:")]
    assert sets and sets[0][1] == "rag:insurance-assistant:user-context" and sets[0][3] is not None
    hd, did = login(*DANIEL)
    ask(hd, "How much of my deductible have I met?")
    sets = [c for c in state()["calls"] if c[0] == "ctx_set" and c[2].startswith(f"{did}:wellness:")]
    assert sets and sets[0][1] == "rag:insurance-wellness:user-context"


def test_fee_waiver_waits_for_a_human_and_runs_as_the_billing_agent(stack):
    h, uid = login(*DANIEL)
    a = ask(h, "How much do I owe?")
    act = next(x for x in a["actions"] if x.get("tool") == "request_fee_waiver")
    assert a["intent"] == "billing" and act["args"]["policy_id"] == "HL-PET-118052"
    doc, req = push(h, uid, "request_fee_waiver", act["args"], until=("awaiting_approval", "failed"))
    assert doc["status"] == "awaiting_approval" and doc["governed"], doc
    httpx.post(f"{AOM}/test/approve/{doc['approval_id']}")
    for _ in range(30):
        if req()["status"] == "confirmed":
            break
        time.sleep(0.2)
    doc = req()
    assert doc["status"] == "confirmed" and doc["agent"] == "insurance-billing-agent" and doc["remembered"] is True


def test_coverage_change_waits_for_a_human(stack):
    h, uid = login(*MAYA)
    doc, _ = push(h, uid, "request_policy_change", {"policy_id": "HL-HOME-207733", "change": "update_mortgagee", "details": "Loan moved to First Harbor Bank"})
    assert doc["status"] == "confirmed" and doc["agent"] == "insurance-assistant", doc          # a simple update needs nobody
    doc, req = push(h, uid, "request_coverage_change", {"policy_id": "HL-AUTO-448120", "change": "add_driver", "details": "Add my daughter Lily, 17"},
                    until=("awaiting_approval", "failed"))
    assert doc["status"] == "awaiting_approval", doc
    httpx.post(f"{AOM}/test/approve/{doc['approval_id']}")
    for _ in range(30):
        if req()["status"] == "confirmed":
            break
        time.sleep(0.2)
    assert req()["status"] == "confirmed" and req()["agent"] == "insurance-assistant"


def test_each_area_runs_as_its_own_agent_with_memory(stack):
    """Confirm in the app -> a request document -> the specialist agent for
    that area runs it through AOM and writes to Agent Memory, which the
    assistant then recalls."""
    h, uid = login(*MAYA)
    before = state()["memory"]
    for tool, args, agent in (
            ("file_claim", {"policy_id": "HL-AUTO-448120", "loss_type": "glass", "loss_date": "2026-11-12",
                            "description": "A stone chipped the windshield on the expressway", "photos": 3}, "insurance-claims-agent"),
            ("request_roadside", {"service": "jump", "lat": 40.6782, "lon": -73.9442}, "insurance-roadside-agent"),
            ("make_payment", {"policy_id": "HL-AUTO-448120"}, "insurance-billing-agent"),
            ("record_trip", {"miles": 12.4, "minutes": 31, "hard_brakes": 1}, "insurance-drive-agent"),
            ("activate_coverage", {"product": "rental-car", "days": 2}, "insurance-coverage-agent")):
        doc, _ = push(h, uid, tool, args)
        assert doc["status"] == "confirmed", doc
        assert doc["governed"] and doc["agent"] == agent and doc["remembered"] is True, doc
    assert state()["memory"] >= before + 5            # one episode per agent
    hd, did = login(*DANIEL)
    doc, _ = push(hd, did, "link_wearable", {"device": "Garmin"})
    assert doc["agent"] == "insurance-wellness-agent" and doc["remembered"] is True
    a = ask(h, "Any update on my claim?")
    assert a["memory_recalled"] >= 1


def test_workload_hits_aom_caches(stack):
    """The app-wide workload through the fake AOM: shared questions repeat
    across users (exact LLM hits), personal follow-ups reuse the person's
    context (context hits), and the CLI reports it."""
    body = {"users_per_group": 2, "turns_per_user": 6, "concurrency": 4, "seed": 11}
    r = httpx.post(f"{API}/api/demo/workload", json=body, timeout=30)
    assert r.status_code == 200, r.text
    for _ in range(600):
        run = httpx.get(f"{API}/api/demo/workload").json()
        if run["state"] != "running":
            break
        time.sleep(0.2)
    assert run["state"] == "done", run.get("error")
    t = run["total"]
    assert t["errors"] == 0 and t["turns"] == 9 * 2 * 6
    assert t["llm_exact_hit"] > 0, t           # the same shared question from a second person
    assert t["llm_miss"] > 0                    # the first person paid for it
    assert t["context_hit"] > 0                 # follow-ups in the same intent reuse the person's context
    assert t["rag_app"] > 0                     # shared questions went to a RAG application
    assert len(run["by_group"]) == 9 and set(run["by_area"]) >= {"claims", "billing", "wellness", "coverage"}
    # the CLI summarizes the same run
    out = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "run_chatbot_workload.py"),
                          "--backend", API, "--status"], capture_output=True, text=True, check=True).stdout
    assert '"state": "done"' in out


def test_demo_reset_clears_aom_memory_and_caches(stack):
    """After the workload and a chat that wrote a memory, the reset deletes
    the people's AOM memories, purges both apps' namespaces, and the next
    question is a cache miss again."""
    h, uid = login(*MAYA)
    ask(h, "I park on the street overnight.")          # -> AOM Agent Memory
    assert httpx.get(f"{AOM}/v1/memory", params={"user_id": uid}, headers=KEY).json()["count"] >= 1
    ask(h, "How does renewal work?")
    res = httpx.post(f"{API}/api/demo/reset", json={}, timeout=60).json()
    assert res["state"] == "done", res
    me = next(g for g in res["users"] if g["user_id"] == uid)
    assert me["memories"] >= 1 and "memory_error" not in me
    assert httpx.get(f"{AOM}/v1/memory", params={"user_id": uid}, headers=KEY).json()["count"] == 0
    assert "error" not in res["aom_caches"], res["aom_caches"]
    assert sum(v.get("llm_purged", 0) for v in res["aom_caches"].values()) >= 1
    assert any(ns.startswith("rag:insurance-wellness") for ns in res["aom_caches"])
    a = ask(h, "How does renewal work?")
    assert a["llm"]["status"] == "miss"
    # the windshield claim filed earlier is gone and the bill is due again
    docs = {d["id"]: d["doc"] for d in httpx.get(f"{API}/api/sync/pull", headers=h).json()["docs"]}
    assert len(docs[f"profile::{uid}"]["claims"]) == 1 and docs[f"profile::{uid}"]["rev"] == 0
