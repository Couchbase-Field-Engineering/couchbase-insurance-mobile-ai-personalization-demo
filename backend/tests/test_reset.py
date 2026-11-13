"""The demo reset (app/demo_reset.py) in memory mode: after a payment, a new
claim, a telehealth-free chat and on-demand cover, a persona is back to the
export - requests gone, policies and claims restored, context and chat
cleared, the feed re-ranked.

    cd backend && pytest -q tests/test_reset.py
"""
from test_demo_flows import MAYA, ask, login, pull, push


def test_reset_restores_the_persona(client):
    client.post("/api/demo/reset", json={})            # whatever earlier tests did
    h, uid = login(client, *MAYA)
    ask(client, h, "When is my next payment due?")
    r = push(client, h, uid, "make_payment", {"policy_id": "HL-AUTO-448120"})
    assert r["status"] == "confirmed", r
    r = push(client, h, uid, "file_claim", {"policy_id": "HL-HOME-207733", "loss_type": "water", "loss_date": "2026-11-11",
                                            "description": "The dishwasher hose leaked into the kitchen floor", "photos": 4})
    assert r["status"] == "confirmed", r
    docs = pull(client, h)
    assert len(docs[("profiles", f"profile::{uid}")]["claims"]) == 2
    assert any(c == "requests" for c, _ in docs) and ("chat", f"chat::{uid}") in docs
    assert uid in client.get("/api/demo/reset").json()["default_users"]

    res = client.post("/api/demo/reset", json={}).json()
    assert res["state"] == "done"
    me = next(g for g in res["users"] if g["user_id"] == uid)
    assert me["profile"] == "reloaded" and me["requests"] >= 2 and "chat" in me["docs"]
    assert res["summary"]["profiles_reloaded"] >= 3        # the three personas at least

    docs = pull(client, h)
    p = docs[("profiles", f"profile::{uid}")]
    assert p["rev"] == 0 and len(p["claims"]) == 1 and p["payments"] == []
    assert p["policies"][0]["billing"]["balance_due_usd"] == 158 and p["policies"][0]["renewal"]["status"] == "offered"
    assert not any(c == "requests" for c, _ in docs)
    assert ("chat", f"chat::{uid}") not in docs and ("context_cache", f"ctx::{uid}::billing") not in docs
    assert ("activity", f"activity::{uid}") not in docs
    kinds = [c["kind"] for c in docs[("feed", f"feed::{uid}")]["cards"]]       # re-ranked from the restored profile
    assert "payment" in kinds and "renewal" in kinds and kinds.count("claim") == 1
    assert client.get("/api/status").json()["metrics"]["assistant_turns"] == 0
