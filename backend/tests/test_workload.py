"""The app-wide assistant workload (app/workload.py) in memory mode: every
group gets users, every turn goes through the assistant, the report adds up.

    cd backend && pytest -q tests/test_workload.py
"""
import time

from app import catalog as C

N = len(C.GROUPS)


def _wait(client):
    for _ in range(600):
        run = client.get("/api/demo/workload").json()
        if run["state"] != "running":
            return run
        time.sleep(0.1)
    raise AssertionError("workload did not finish")


def test_catalog_covers_every_group_and_use_case(client):
    cat = client.get("/api/demo/workload/catalog").json()
    assert len(cat["groups"]) == N == 9
    assert {g["audience"] for g in cat["groups"]} == {"policyholder", "member", "ondemand"}
    ids = [u["id"] for u in cat["use_cases"]]
    assert len(ids) == len(set(ids))
    # the eight things the app is for
    assert {u["area"] for u in cat["use_cases"]} == {"documents", "claims", "roadside", "billing", "telematics", "support", "wellness", "coverage"}
    intents = {u["intent"] for u in cat["use_cases"]}
    assert {"general", "documents", "claim", "roadside", "emergency", "billing", "telematics", "account", "handoff", "wellness", "coverage"} <= intents


def test_use_cases_classify_the_way_they_are_labelled(client):
    from app import assistant, workload
    for u in workload.USE_CASES:
        for aud in u["audiences"]:
            for v in u["variants"]:
                assert assistant.classify(v, aud) == (u["intent"], u["personal"]), (aud, u["id"], v)


def test_plan_has_a_session_per_group(client):
    plan = client.get("/api/demo/workload/plan?users_per_group=1&turns_per_user=6").json()["sessions"]
    assert {s["group_code"] for s in plan} == set(C.GROUPS)
    for s in plan:
        assert len(s["turns"]) == 6
        assert any(t["personal"] for t in s["turns"]) and any(not t["personal"] for t in s["turns"])
        if s["audience"] != "member":         # non-members only ask a wellness question to show the gate
            assert all(t["area"] != "wellness" or t["use_case"] == "gate_wellness" for t in s["turns"])


def test_workload_runs_every_group_and_reports(client):
    r = client.post("/api/demo/workload", json={"users_per_group": 1, "turns_per_user": 5, "concurrency": 6, "seed": 3, "pace_ms": 100})
    assert r.status_code == 200, r.text
    started = r.json()
    assert started["state"] == "running" and started["total_turns"] == N * 5
    # a second start while running is refused (pace_ms keeps the first one busy)
    assert client.post("/api/demo/workload", json={}).status_code == 409
    run = _wait(client)
    assert run["state"] == "done", run.get("error")
    t = run["total"]
    assert t["turns"] == N * 5 and t["errors"] == 0
    assert sum(b["turns"] for b in run["by_group"].values()) == N * 5
    assert set(run["by_group"]) == set(C.GROUPS)
    assert sum(b["turns"] for b in run["by_use_case"].values()) == N * 5
    assert sum(b["turns"] for b in run["by_area"].values()) == N * 5
    # no AOM in tests: the LLM is answered locally, but context caching still happens in Couchbase/memory
    assert t["llm_other"] == N * 5 and t["context_hit"] + t["context_miss"] > 0
    assert run["recent"] and all(rec["reply"] for rec in run["recent"])
    # status summary is on /api/status for the story page
    assert client.get("/api/status").json()["workload"]["state"] == "done"


def test_unknown_group_is_rejected(client):
    r = client.post("/api/demo/workload", json={"groups": ["MARS"]})
    assert r.status_code == 400 and "unknown group" in r.text


def test_paced_run_follows_the_schedule_and_can_be_stopped(client):
    """duration_hours spreads the turns over time: a 24-turn run paced over
    ~20 s cannot finish in 2 s, and Stop ends it early."""
    from app import workload
    # the diurnal integral covers a whole day
    start = workload.dt.datetime(2026, 11, 5, 0, 0, tzinfo=workload.WORKLOAD_TZ)
    assert abs(workload._traffic_integral(start, 24) - sum(workload.DIURNAL)) < 1e-6
    r = client.post("/api/demo/workload", json={"users_per_group": 1, "turns_per_user": 2, "concurrency": 4, "duration_hours": 20 / 3600})
    assert r.status_code == 200, r.text
    assert r.json()["ends_at"]
    time.sleep(2)
    run = client.get("/api/demo/workload").json()
    assert run["state"] == "running" and run["done_turns"] < run["total_turns"]
    assert run["params"]["duration_hours"] == 20 / 3600 and "elapsed_hours" in run
    stopped = client.delete("/api/demo/workload").json()
    assert stopped["state"] == "cancelled"
