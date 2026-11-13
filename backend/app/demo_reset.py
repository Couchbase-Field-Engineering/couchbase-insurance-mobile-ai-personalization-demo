"""Reset the demo: put people back to the state of today's export and clear
what they left behind, here and in AOM.

`POST /api/demo/reset` (the story page's **Reset demo** button, or
scripts/reset_demo.py). For each person - by default the three personas plus
everyone who changed something since the export loaded:

1. **Couchbase**: delete their `requests` (the queue the phone shows), `chat`,
   `context_cache` and `activity` documents; reload their `profiles`
   document from the export partition (policies, claims, bills, trips,
   wellness, on-demand cover, `rev` back to the export); restore telehealth
   appointments (`inventory`, rebuilt from the catalog on next use);
   re-rank their feed; drop them from `live_users` so the next nightly load
   doesn't carry the old state forward. Sync Gateway replicates the deletes
   and the fresh profile to the phone, so Couchbase Lite ends up in the same
   state.
2. **AOM Agent Memory**: delete every memory entry for the person (what they
   told the assistant, and what the specialist agents remembered).
3. **AOM caches** (optional, default on): purge both RAG applications' LLM
   Cache and Context Cache namespaces, so the next demo starts with a visible
   `miss` again. Everything else in AOM (traces, audit log, approvals
   history) is left alone - that is the record.
4. The backend's in-process counters and the last workload report.

Nothing here touches the export files, the Knowledge Base or the RAG applications.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time

from . import assistant, config, loader, metrics, personalization, rag_app, workload
from .aom_client import AOMError, aom
from .docs import INVENTORY_ID, STATE, activity_id, chat_id, feed_id, now_iso, profile_id
from .store import store

log = logging.getLogger("insurance.reset")
LAST: dict = {"state": "never"}


async def default_users() -> list[str]:
    live = (await store.get("lookups", "live_users") or {}).get("users", [])
    return list(dict.fromkeys(loader.PERSONAS + list(live)))


def _export_rows(user_ids: set[str]) -> dict[str, dict]:
    """The export rows of these people (personas are first in part-00000)."""
    part = loader.latest_partition(os.path.abspath(config.EXPORT_DIR))
    found: dict[str, dict] = {}
    if not part:
        return found
    for row in loader.read_rows(part):
        if row["user_id"] in user_ids:
            found[row["user_id"]] = row
            if len(found) == len(user_ids):
                break
    return found


async def _reset_user(uid: str, row: dict | None, aom_memory: bool) -> dict:
    out = {"user_id": uid, "requests": 0, "docs": [], "profile": "kept", "memories": 0}
    for d in await store.requests_for_user(uid):
        await store.remove("requests", d["_id"])
        out["requests"] += 1
    for col, key in (("chat", chat_id(uid)), ("activity", activity_id(uid)), ("feed", feed_id(uid))):
        if await store.get(col, key):
            await store.remove(col, key)
            out["docs"].append(col)
    await assistant.invalidate_context(uid)
    prev = await store.get("profiles", profile_id(uid))
    if row:
        await store.upsert("profiles", profile_id(uid), loader.profile_doc(row))
        out["profile"] = "reloaded"
    elif prev:
        out["profile"] = "not in export"
    if await store.get("profiles", profile_id(uid)):
        await personalization.refresh_feed(uid)
    if aom_memory and aom.enabled:
        try:
            for m in await aom.memory_list(uid):
                if m.get("memory_id") and await aom.memory_delete(m["memory_id"]):
                    out["memories"] += 1
        except AOMError as exc:
            out["memory_error"] = str(exc)[:200]
    return out


async def _purge_aom_caches() -> dict:
    """Purge every AOM cache namespace that belongs to Harborline's two RAG
    applications: the namespaces the assistant calls directly
    (`rag:<app>:playbook|personal|user-context`) and the ones AOM's RAG
    applications made for themselves (`rag:<app>` and `rag:<app>:<fingerprint>`).
    AOM purges by exact namespace, so list first."""
    out: dict = {}
    try:
        for app_id in rag_app.app_ids():
            prefix = f"rag:{app_id}"
            llm_ns = {config.llm_namespace(app_id, False), config.llm_namespace(app_id, True)}
            ctx_ns = {config.context_namespace(app_id)}
            for _ in range(4):  # the listing is capped at 500 entries; look again until nothing is left
                more_llm = {n for n in await aom.llm_cache_namespaces(prefix) if n == prefix or n.startswith(prefix + ":")} - llm_ns
                more_ctx = {n for n in await aom.context_cache_namespaces(prefix) if n == prefix or n.startswith(prefix + ":")} - ctx_ns
                llm_ns |= more_llm
                ctx_ns |= more_ctx
                for ns in sorted(llm_ns):
                    out.setdefault(ns, {})["llm_purged"] = out.get(ns, {}).get("llm_purged", 0) + await aom.purge_llm_cache(ns)
                for ns in sorted(ctx_ns):
                    out.setdefault(ns, {})["context_purged"] = out.get(ns, {}).get("context_purged", 0) + await aom.purge_context_cache(ns)
                if not more_llm and not more_ctx:
                    break
    except AOMError as exc:
        out["error"] = str(exc)[:200]
    return out


async def run(users: list[str] | None = None, aom_memory: bool = True, aom_caches: bool = True,
              counters: bool = True) -> dict:
    t0 = time.time()
    uids = list(dict.fromkeys(users)) if users else await default_users()
    rows = await asyncio.to_thread(_export_rows, set(uids))
    results = [await _reset_user(u, rows.get(u), aom_memory) for u in uids]
    # Booked telehealth appointments open up again: the document is rebuilt from the catalog on next use.
    inventory = bool(await store.get("inventory", INVENTORY_ID))
    if inventory:
        await store.remove("inventory", INVENTORY_ID)
        for u in uids:
            if await store.get("profiles", profile_id(u)):
                await personalization.refresh_feed(u)
    live = await store.get("lookups", "live_users")
    if live:
        live["users"] = [u for u in live.get("users", []) if u not in uids]
        await store.upsert("lookups", "live_users", live)
    caches: dict = {}
    if aom_caches and aom.admin_enabled:
        caches = await _purge_aom_caches()
    elif aom_caches:
        caches = {"skipped": "AOM admin password not configured" if aom.enabled else "AOM not configured"}
    if counters:
        metrics.reset()
        if workload.RUN.get("state") != "running":
            workload.RUN.clear()
            workload.RUN["state"] = "idle"
    LAST.clear()
    LAST.update(state="done", at=now_iso(), seconds=round(time.time() - t0, 1), export_date=STATE.get("export_date"),
                users=results, inventory_restored=inventory, aom_memory=aom_memory, aom_caches=caches, counters=counters,
                summary={"users": len(results), "requests_removed": sum(r["requests"] for r in results),
                         "profiles_reloaded": sum(r["profile"] == "reloaded" for r in results),
                         "memories_deleted": sum(r["memories"] for r in results)})
    log.info("Demo reset: %s", LAST["summary"])
    return dict(LAST)
