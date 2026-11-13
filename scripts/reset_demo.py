#!/usr/bin/env python3
"""Reset the Harborline demo to the state of today's export.

Calls the backend's `POST /api/demo/reset`: for the three personas plus
everyone who changed something since the load (or the users you name), it
removes their requests, chat and cached context, reloads their profile from
the export (policies, claims, bills, trips, wellness, on-demand cover),
reopens telehealth appointments, re-ranks their feed, deletes their
AOM Agent Memory entries and purges Harborline's AOM LLM / Context Cache
namespaces. Sync Gateway carries the result to the phone; reload the app
afterwards.

    python scripts/reset_demo.py                       # mother (backend :8204)
    python scripts/reset_demo.py --users L00000201     # just Daniel
    python scripts/reset_demo.py --keep-aom-caches     # leave AOM's cache pages as they are
    python scripts/reset_demo.py --backend http://localhost:8204

Standard library only.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

DEFAULT_BACKEND = "http://192.168.111.4:8204"


def call(base, path, method="GET", body=None, timeout=120):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as exc:
        sys.exit(f"{method} {path} -> HTTP {exc.code}: {exc.read().decode(errors='replace')[:400]}")
    except urllib.error.URLError as exc:
        sys.exit(f"Cannot reach {base}{path}: {exc.reason}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backend", default=DEFAULT_BACKEND)
    ap.add_argument("--users", help="comma-separated user ids (default: personas + everyone with live changes)")
    ap.add_argument("--keep-aom-memory", action="store_true", help="don't delete these people's AOM memories")
    ap.add_argument("--keep-aom-caches", action="store_true", help="don't purge Harborline's AOM cache namespaces")
    ap.add_argument("--keep-counters", action="store_true", help="keep the story page's counters and last workload report")
    ap.add_argument("--dry-run", action="store_true", help="show who would be reset")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    if a.dry_run:
        info = call(a.backend, "/api/demo/reset")
        print("Would reset:", ", ".join(info["default_users"]))
        last = info.get("last") or {}
        if last.get("at"):
            print(f"Last reset: {last['at']} - {last.get('summary')}")
        return
    body = {"users": [g.strip() for g in a.users.split(",")] if a.users else None,
            "aom_memory": not a.keep_aom_memory, "aom_caches": not a.keep_aom_caches, "counters": not a.keep_counters}
    res = call(a.backend, "/api/demo/reset", "POST", body)
    if a.json:
        print(json.dumps(res, indent=1)); return
    s = res["summary"]
    print(f"Reset done in {res['seconds']}s (export {res['export_date']}): {s['users']} people, "
          f"{s['requests_removed']} requests removed, {s['profiles_reloaded']} profiles reloaded, "
          f"{s['memories_deleted']} AOM memories deleted")
    for g in res["users"]:
        err = f"  (memory: {g['memory_error']})" if g.get("memory_error") else ""
        print(f"  {g['user_id']}: profile {g['profile']}, {g['requests']} requests, docs {g['docs'] or '-'}, "
              f"{g['memories']} memories{err}")
    if res.get("inventory_restored"):
        print("  Stock and consultation slots restored")
    caches = res.get("aom_caches") or {}
    if "skipped" in caches:
        print(f"  AOM caches: skipped ({caches['skipped']})")
    elif "error" in caches:
        print(f"  AOM caches: error {caches['error']}")
    elif caches:
        llm = sum(v.get("llm_purged", 0) for v in caches.values() if isinstance(v, dict))
        ctx = sum(v.get("context_purged", 0) for v in caches.values() if isinstance(v, dict))
        print(f"  AOM caches: {llm} LLM Cache and {ctx} Context Cache entries purged across {len(caches)} namespace(s)")
    print("Reload the app (or let Couchbase Lite sync) and the personas are back to the export.")


if __name__ == "__main__":
    main()
