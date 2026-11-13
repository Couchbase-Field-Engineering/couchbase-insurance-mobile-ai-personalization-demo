#!/usr/bin/env python3
"""Run the Harborline app-wide assistant workload against AOM and watch it land.

Drives the demo backend's `POST /api/demo/workload`: policyholders from every
region, health and pet members and on-demand customers ask the assistant
what such people ask (ID cards, claims, roadside, bills and renewals,
driving scores, address changes, telehealth, vet bills, cover for a trip
or a borrowed car...), through the real path - AOM RAG Applications,
Context Cache, Knowledge Base, governed MCP tools, Agent Memory and
`/v1/llm/complete`. Then open AOM's LLM Cache and Context Cache pages: that
is the workload.

    # the deployment on mother (backend :8204, AOM dashboard :3111)
    python scripts/run_chatbot_workload.py
    # bigger / faster / a few groups only
    python scripts/run_chatbot_workload.py --users-per-group 6 --turns 8 --concurrency 8 --groups CUS-NE,LEAD-SMB,EMP-TECH
    # local docker compose
    python scripts/run_chatbot_workload.py --backend http://localhost:8204 --aom https://localhost:8090

Only the Python standard library is needed.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

DEFAULT_BACKEND = "http://192.168.111.4:8204"
DEFAULT_AOM = "https://192.168.111.4:3111"


def call(base: str, path: str, method="GET", body=None, timeout=30):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:400]
        sys.exit(f"{method} {path} -> HTTP {exc.code}: {detail}")
    except urllib.error.URLError as exc:
        sys.exit(f"Cannot reach {base}{path}: {exc.reason}")


def pct(v):
    return "-" if v is None else f"{v:>5.1f}%"


def bar(done, total, width=28):
    n = int(width * done / total) if total else 0
    return "[" + "#" * n + "." * (width - n) + "]"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backend", default=DEFAULT_BACKEND, help=f"demo backend (default {DEFAULT_BACKEND})")
    ap.add_argument("--aom", default=DEFAULT_AOM, help=f"AOM dashboard, for the links printed at the end (default {DEFAULT_AOM})")
    ap.add_argument("--users-per-group", type=int, default=3)
    ap.add_argument("--turns", type=int, default=6, help="turns per session")
    ap.add_argument("--concurrency", type=int, default=4, help="people chatting at the same time")
    ap.add_argument("--groups", help="comma-separated group codes (default: the whole company; see /api/demo/workload/catalog)")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--repeat-ratio", type=float, default=0.5)
    ap.add_argument("--paraphrase-ratio", type=float, default=0.3)
    ap.add_argument("--pace-ms", type=int, default=0)
    ap.add_argument("--hours", type=float, help="spread the run over this many hours with a day/night traffic curve "
                    "(e.g. --users-per-group 300 --concurrency 4 --hours 24); the script can be Ctrl-C'd, the run continues")
    ap.add_argument("--plan", action="store_true", help="print who would ask what, run nothing")
    ap.add_argument("--stop", action="store_true", help="stop a running workload")
    ap.add_argument("--status", action="store_true", help="show the current/last run and exit")
    ap.add_argument("--json", action="store_true", help="print the final report as JSON")
    a = ap.parse_args()

    if a.stop:
        print(json.dumps(call(a.backend, "/api/demo/workload", "DELETE"), indent=1)[:2000]); return
    if a.status:
        print(json.dumps(call(a.backend, "/api/demo/workload"), indent=1)[:6000]); return

    st = call(a.backend, "/api/status")
    aom = st.get("aom") or {}
    print(f"Backend {a.backend}: export {st.get('export_date')}, store {st.get('store')}")
    reg = (aom.get("registration") or {}).get("state")
    apps = ", ".join(f"{v.get('app_id')} {v.get('state')}" for v in (aom.get("rag_apps") or {}).values())
    print(f"AOM: {aom.get('url')} - {reg}, RAG apps: {apps}")
    if not aom.get("configured"):
        print("WARNING: the backend has no AOM configured - Harborline will answer locally and nothing will reach AOM.")

    groups = [s.strip().upper() for s in a.groups.split(",")] if a.groups else None
    if a.plan:
        q = f"?users_per_group={a.users_per_group}&turns_per_user={a.turns}&seed={a.seed}"
        if groups:
            q += "&groups=" + ",".join(groups)
        sessions = call(a.backend, "/api/demo/workload/plan" + q)["sessions"]
        for s in sessions:
            print(f"\n{s['group_name']} ({s['group_code']}) - user {s['user_id']}")
            for t in s["turns"]:
                print(f"   {'personal' if t['personal'] else 'shared':8} {t['area']:10} {t['use_case']:18} {t['message']}")
        print(f"\n{len(sessions)} sessions, {sum(len(s['turns']) for s in sessions)} turns")
        return

    body = {"users_per_group": a.users_per_group, "turns_per_user": a.turns, "concurrency": a.concurrency,
            "groups": groups, "seed": a.seed, "repeat_ratio": a.repeat_ratio, "paraphrase_ratio": a.paraphrase_ratio,
            "pace_ms": a.pace_ms, "duration_hours": a.hours}
    run = call(a.backend, "/api/demo/workload", "POST", body)
    print(f"\nStarted run {run['run_id']}: {run['total_users']} people in {len(run['groups_covered'])}/{run['group_count']} groups, "
          f"{run['total_turns']} turns, {a.concurrency} concurrent sessions"
          + (f", paced over {a.hours} h (day/night curve), ends {run.get('ends_at')}" if a.hours else "") + "\n")
    try:
        while run.get("state") == "running":
            time.sleep(1.5)
            run = call(a.backend, "/api/demo/workload")
            t = run.get("total") or {}
            line = (f"\r{bar(run.get('done_turns', 0), run.get('total_turns', 1))} {run.get('done_turns', 0)}/{run.get('total_turns')} turns  "
                    f"LLM hit {pct(t.get('llm_hit_rate'))}  context hit {pct(t.get('context_hit_rate'))}  "
                    f"tokens saved {t.get('tokens_saved', 0):,}  errors {t.get('errors', 0)}   ")
            sys.stdout.write(line); sys.stdout.flush()
    except KeyboardInterrupt:
        if a.hours:
            print(f"\nDetached - the run continues on the backend until {run.get('ends_at')}; --status to check, --stop to end it.")
            return
        print("\nStopping ...")
        run = call(a.backend, "/api/demo/workload", "DELETE")
    print()
    if a.json:
        print(json.dumps(run, indent=1)); return

    t = run.get("total") or {}
    print(f"\nRun {run.get('run_id')} {run.get('state')} in {run.get('seconds')}s - {t.get('turns')} turns, "
          f"{run.get('done_users')} people, {len(run.get('groups_covered') or [])} groups")
    print(f"  LLM Cache:     {t.get('llm_exact_hit', 0)} exact + {t.get('llm_semantic_hit', 0)} semantic hits, "
          f"{t.get('llm_miss', 0)} provider calls  -> hit rate {pct(t.get('llm_hit_rate'))}")
    print(f"  Context Cache: {t.get('context_hit', 0)} hits, {t.get('context_miss', 0)} builds  -> hit rate {pct(t.get('context_hit_rate'))}")
    print(f"  RAG app turns: {t.get('rag_app', 0)}   refused by the audience gate: {t.get('restricted', 0)}   memory writes: {t.get('memory_writes', 0)}   "
          f"tokens saved: {t.get('tokens_saved', 0):,}   est. cost saved: ${t.get('cost_saved_usd', 0):.4f}   errors: {t.get('errors', 0)}")

    print(f"\n  {'Area':22} {'turns':>5} {'LLM hit':>8} {'ctx hit':>8} {'tokens':>7}")
    for area, b in sorted((run.get("by_area") or {}).items(), key=lambda kv: -kv[1]["turns"]):
        print(f"  {area:22} {b['turns']:>5} {pct(b.get('llm_hit_rate')):>8} {pct(b.get('context_hit_rate')):>8} {b.get('tokens_saved', 0):>7,}")

    print(f"\n  {'Group':36} {'users':>5} {'turns':>5} {'LLM hit':>8} {'ctx hit':>8} {'tokens':>7} {'avg ms':>7}")
    for code, b in (run.get("by_group") or {}).items():
        print(f"  {b['group_name']:36} {b['users']:>5} {b['turns']:>5} {pct(b.get('llm_hit_rate')):>8} "
              f"{pct(b.get('context_hit_rate')):>8} {b.get('tokens_saved', 0):>7,} {b.get('avg_latency_ms') or 0:>7.0f}")

    print(f"\n  {'Use case':20} {'turns':>5} {'exact':>5} {'seman':>5} {'miss':>5} {'ctx hit':>8}")
    for uc, b in sorted((run.get("by_use_case") or {}).items(), key=lambda kv: -kv[1]["turns"])[:20]:
        print(f"  {uc:20} {b['turns']:>5} {b['llm_exact_hit']:>5} {b['llm_semantic_hit']:>5} {b['llm_miss']:>5} {pct(b.get('context_hit_rate')):>8}")

    recent = run.get("recent") or []
    stub = any(r.get("stub") for r in recent)
    if stub:
        print("\n  Note: AOM answered with labelled stubs (no LLM provider key configured) - the caches still count hits, "
              "Harborline composed the replies locally.")
    print(f"\nNow open AOM:\n  LLM Cache        {a.aom}/llm-caching\n  Context Cache    {a.aom}/context-cache\n"
          f"  RAG Applications {a.aom}/rag-applications\n  Traces           {a.aom}/traces\n  Agent Memory     {a.aom}/memory")


if __name__ == "__main__":
    main()
