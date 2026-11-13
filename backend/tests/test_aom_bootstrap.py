"""Self-registration (AOM_AUTO_REGISTER, used by the Helm chart) against a
*fresh* fake AOM: the backend sets the admin password, registers its MCP
server (AOM ingests it over real MCP), issues its agent identities, turns on
the approval tier, publishes the KB and both RAG applications - then answers
governed questions with no register script and no agent key given.
"""
import os
import subprocess
import sys
import time

import httpx
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BACKEND = os.path.join(ROOT, "backend")
AOM, API = "http://127.0.0.1:18095", "http://127.0.0.1:18205"


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
    env = {**os.environ, "STORE_DRIVER": "memory", "EXPORT_DIR": str(dump), "SOR_MOCK_LATENCY_MS": "1,2", "AOM_URL": AOM, "AOM_AGENT_API_KEY": "",
           "AOM_ADMIN_PASSWORD": "Harborline-Demo-2026", "AOM_AUTO_REGISTER": "true", "KB_PROFILE_LIMIT": "10",
           "AOM_MCP_PUBLIC_URL": f"{API}/ins/mcp", "SG_ADMIN_URL": "", "REQUEST_POLL_SECONDS": "0.3",
           "FAKE_MCP_URL": f"{API}/ins/mcp", "FAKE_FRESH_AOM": "1"}
    uv = [sys.executable, "-m", "uvicorn"]
    procs = [subprocess.Popen(uv + ["tests.fake_aom:app", "--port", "18095"], cwd=BACKEND, env=env,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)]
    wait(f"{AOM}/api/health")
    procs.append(subprocess.Popen(uv + ["app.main:app", "--port", "18205"], cwd=BACKEND, env=env,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    wait(f"{API}/api/health")
    for _ in range(120):
        st = httpx.get(f"{API}/api/status").json()
        if (st["load"].get("kb") or {}).get("state") == "published":
            break
        time.sleep(0.25)
    yield st
    for p in procs:
        p.terminate()


def test_registers_itself_with_a_fresh_aom(stack):
    st = httpx.get(f"{API}/api/status").json()
    assert st["aom"]["registration"]["state"] == "registered" and st["aom"]["configured"]
    fake = httpx.get(f"{AOM}/test/state").json()
    assert fake["admin_pw_set"] and fake["servers"] == ["insurance-services"]
    assert [a["name"] for a in fake["agents"]] == ["Harborline Assistant", "Harborline Claims Agent", "Harborline Roadside Agent", "Harborline Billing Agent",
                                                   "Harborline DriveWell Agent", "Harborline Wellness Agent", "Harborline Coverage Agent"]
    assert len(fake["agents"][0]["allowed_tools"]) == 28 and len(fake["agents"][1]["allowed_tools"]) == 5
    assert "insurance-services::make_payment" not in fake["agents"][1]["allowed_tools"]          # the Claims Agent can't take a payment
    assert fake["approvals_cfg"]["require_for_tools"] == ["insurance-services::request_coverage_change",
                                                          "insurance-services::request_fee_waiver"]
    assert fake["rag_apps"]["insurance-assistant"]["enabled"] and fake["rag_apps"]["insurance-wellness"]["enabled"]


def test_assistant_is_governed_after_self_registration(stack):
    r = httpx.post(f"{API}/api/auth/login", json={"account_id": "5510101", "last_name": "Chen"})
    h = {"Authorization": f"Bearer {r.json()['token']}"}
    a = httpx.post(f"{API}/api/chat", headers=h, json={"message": "What's the status of my claim?"}, timeout=30).json()
    assert a["governed"] and a["context"]["kb_mode"] == "aom"
    b = httpx.post(f"{API}/api/chat", headers=h, json={"message": "How does roadside assistance work?"}, timeout=30).json()
    assert b["context"]["source"] == "aom-rag"
