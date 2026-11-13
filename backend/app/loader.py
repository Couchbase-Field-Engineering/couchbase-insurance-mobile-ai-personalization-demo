"""Nightly Harborline export -> Couchbase + AOM Knowledge Base.

Run by the backend on startup and every EXPORT_POLL_SECONDS (it only does work
when a newer `exportTime=YYYYMMDD/_SUCCESS` partition lands), or by hand:

    python -m app.loader [--export-dir PATH] [--force] [--no-kb]

1. Stream every JSON Lines part file of the newest complete partition - one
   row per policyholder, member or on-demand customer (datagen/README.md).
2. Upsert one `profiles` document per person. Live state the person changed
   since the last export (a claim filed in the app, a payment, cover bought
   for the weekend, a trip recorded) is carried forward - in production that
   state would already be in the next night's row.
3. Index accounts for sign-in, publish the catalog (for everyone) and the
   member reference document (health and pet members only), rank each
   person's For You feed.
4. Publish to the AOM Knowledge Base: the Help Center and the Member Care
   Guide, rendered from the CMS entries, and one profile document per person
   in the KB window (demo personas always), replacing yesterday's version of
   each. The two AOM RAG Applications are then re-scoped to the new documents.

Context caches need no sweep: every cached context records the export date it
was built from, so the new export makes them all stale at once.
"""
from __future__ import annotations

import argparse
import asyncio
import glob
import hashlib
import json
import logging
import os
import time

from . import catalog as C
from . import config, knowledge, personalization, rag_app, sources
from .aom_client import AOMError, aom
from .docs import CATALOG_CHANNEL, CATALOG_ID, MEMBER_CHANNEL, STATE, WELLNESS_ID, now_iso, profile_id, user_channel
from .store import store

log = logging.getLogger("insurance.loader")
PERSONAS = ["P00000101", "M00000201", "O00000301"]
# What a person can change through Harborline between two exports.
LIVE_FIELDS = ("policies", "claims", "payments", "fee_waivers", "emergencies", "roadside", "telematics", "wellness", "on_demand", "support",
               "history", "email", "phone", "address")
STATUS = {"state": "idle"}
_TASKS: list = []  # keep a reference so background KB publishing is not garbage-collected


PARTITION_PREFIX = "exportTime="


def partition_date(partition: str) -> str:
    """exportTime=20261113[HHMMSS] -> 2026-11-13."""
    stamp = os.path.basename(partition).split("=", 1)[1]
    digits = "".join(ch for ch in stamp if ch.isdigit())
    return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}" if len(digits) >= 8 else stamp


def latest_partition(export_dir: str) -> str | None:
    parts = [p for p in glob.glob(os.path.join(export_dir, PARTITION_PREFIX + "*"))
             if os.path.exists(os.path.join(p, "_SUCCESS"))]
    parts.sort(key=lambda p: (partition_date(p), os.path.basename(p)))
    return parts[-1] if parts else None


def partition_id(partition: str) -> str:
    """Identifies one export's contents: folder name, part file names and
    sizes. A re-exported partition (new generator, new catalog, same date -
    even with the same deterministic file names) gets a different id, so the
    backend reloads it instead of trusting the previous load."""
    parts = sorted(glob.glob(os.path.join(partition, "part-*.json")))
    sig = [os.path.basename(partition)] + [f"{os.path.basename(p)}:{os.path.getsize(p)}" for p in parts]
    return hashlib.sha1("|".join(sig).encode()).hexdigest()[:12]


def read_rows(partition: str):
    for path in sorted(glob.glob(os.path.join(partition, "part-*.json"))):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    yield json.loads(line)


def profile_doc(row: dict) -> dict:
    return {**row, "type": "profile", "rev": 0, "channels": [user_channel(row["user_id"])], "loaded_at": now_iso()}


async def mark_live(user_id: str):
    """Called after an action - remembers which people have state newer than the export."""
    doc = await store.get("lookups", "live_users") or {"users": []}
    if user_id not in doc["users"]:
        doc["users"].append(user_id)
        await store.upsert("lookups", "live_users", doc)


async def publish_reference(export_date: str):
    """`catalog::v1` for every phone; `wellness::v1` only on the members channel."""
    cat = C.public_catalog()
    cat.update({"type": "catalog", "faq": knowledge.faq_public(knowledge.CUSTOMER_FAQ), "export_date": export_date,
                "channels": [CATALOG_CHANNEL], "updated_at": now_iso()})
    await store.upsert("catalog", CATALOG_ID, cat)
    hb = C.member_catalog()
    hb.update({"type": "member_guide", "faq": knowledge.faq_public(knowledge.MEMBER_FAQ), "export_date": export_date,
               "channels": [MEMBER_CHANNEL], "updated_at": now_iso()})
    await store.upsert("catalog", WELLNESS_ID, hb)


async def load(export_dir: str | None = None, force=False, kb=True) -> dict:
    export_dir = os.path.abspath(export_dir or config.EXPORT_DIR)
    part = latest_partition(export_dir)
    if not part:
        log.warning("No complete export (exportTime=*/_SUCCESS) under %s", export_dir)
        STATUS.update(state="no_export", export_dir=export_dir)
        return STATUS
    export_date = partition_date(part)
    state = await store.get("lookups", "load_state") or {}
    pid = partition_id(part)
    if (state.get("export_date") == export_date and state.get("partition_id") == pid and not force
            and state.get("driver") == store.driver and store.driver == "couchbase"):
        STATE["export_date"] = export_date
        STATUS.update(state="loaded", **state)
        log.info("Export %s already loaded", export_date)
        hc = await store.get("lookups", "kbdoc::helpcenter") or {}
        if kb and config.KB_ENABLED and aom.admin_enabled and hc.get("export_date") != export_date:
            # Loaded before AOM was configured (first run) - publish the KB now.
            _TASKS.append(asyncio.create_task(publish_kb(export_date, await _kb_window())))
        elif kb and aom.admin_enabled and hc.get("document_id"):
            # KB is current; make sure the RAG applications point at it.
            hb = await store.get("lookups", "kbdoc::memberguide") or {}
            _TASKS.append(asyncio.create_task(rag_app.sync_all({"helpcenter": hc["document_id"], "memberguide": hb.get("document_id")})))
        return STATUS

    t0 = time.time()
    STATE["export_date"] = export_date
    STATUS.update(state="loading", export_date=export_date, partition=part, started_at=now_iso())
    live = set((await store.get("lookups", "live_users") or {}).get("users", []))
    accounts: dict[str, dict] = {}
    batch: dict[str, dict] = {}
    rows = skipped = carried = 0
    by_audience = {"policyholder": 0, "member": 0, "ondemand": 0}
    loaded: list[str] = []
    nbytes = sum(os.path.getsize(p) for p in glob.glob(os.path.join(part, "part-*.json")))

    for row in read_rows(part):
        uid = row["user_id"]
        if store.driver == "memory" and rows >= config.MEMORY_MAX_PROFILES and uid not in PERSONAS:
            skipped += 1
            continue
        doc = profile_doc(row)
        if uid in live:
            prev = await store.get("profiles", profile_id(uid))
            if prev and prev.get("account_id") == row.get("account_id"):
                for f in LIVE_FIELDS:
                    if f in prev:
                        doc[f] = prev[f]
                doc["rev"] = int(prev.get("rev", 0)) + 1
                carried += 1
        batch[profile_id(uid)] = doc
        a = accounts.setdefault(str(row["account_id"]), {"type": "account_index", "users": [], "last_names": []})
        a["users"].append(uid)
        ln = row["last_name"].lower()
        if ln not in a["last_names"]:
            a["last_names"].append(ln)
        by_audience[row["audience"]] = by_audience.get(row["audience"], 0) + 1
        loaded.append(uid)
        rows += 1
        if len(batch) >= 1000:
            await store.upsert_many("profiles", batch)
            batch = {}
            STATUS["rows"] = rows
    await store.upsert_many("profiles", batch)
    await store.upsert_many("lookups", {f"account::{k}": v for k, v in accounts.items()})
    await publish_reference(export_date)

    # Feeds are ranked up front for the personas and on sign-in for everyone
    # else (main.login), so a large export doesn't hold the load up.
    for uid in PERSONAS:
        await personalization.refresh_feed(uid)

    summary = {"export_date": export_date, "partition": part, "partition_id": pid, "rows": rows, "accounts": len(accounts),
               "by_audience": by_audience, "skipped_over_memory_limit": skipped, "carried_live_state": carried, "bytes": nbytes,
               "load_seconds": round(time.time() - t0, 1), "driver": store.driver, "loaded_at": now_iso()}
    await store.upsert("lookups", "load_state", summary)
    STATUS.update(state="loaded", **summary)
    log.info("Loaded export %s: %s rows (%s) in %.1fs", export_date, rows, by_audience, time.time() - t0)

    if kb and config.KB_ENABLED and aom.admin_enabled:
        window = PERSONAS + [u for u in loaded if u not in PERSONAS]
        _TASKS.append(asyncio.create_task(publish_kb(export_date, window[: max(config.KB_PROFILE_LIMIT, len(PERSONAS))])))
    elif kb and config.KB_ENABLED:
        STATUS["kb"] = {"state": "skipped", "reason": "AOM_URL / AOM_ADMIN_PASSWORD not set"}
    return STATUS


async def _replace_kb_doc(key: str, title: str, content: str, metadata: dict, source: str = "insurance-export"):
    prev = await store.get("lookups", f"kbdoc::{key}")
    res = await aom.kb_ingest(title, content, metadata, source=source)
    new_id = res["document"]["document_id"]
    await store.upsert("lookups", f"kbdoc::{key}", {"type": "kb_index", "document_id": new_id, "title": title,
                                                    "export_date": metadata.get("export_date"), "at": now_iso()})
    if prev and prev.get("document_id") and prev["document_id"] != new_id:
        await aom.kb_delete(prev["document_id"])
    return new_id


async def publish_kb(export_date: str, user_ids: list[str]):
    t0 = time.time()
    STATUS["kb"] = {"state": "publishing", "total": len(user_ids) + 2, "done": 0, "errors": 0}
    try:
        entries, cms_mode = await sources.kb_entries(export_date)
        meta = {"export_date": export_date, "pii": False, "source": "cms", "cms_mode": cms_mode}
        helpcenter_id = await _replace_kb_doc("helpcenter", f"Harborline Help Center {export_date}",
                                              knowledge.help_center_markdown(export_date, entries),
                                              {**meta, "type": "help_center", "audience": "all"}, source="cms")
        STATUS["kb"]["done"] += 1
        guide_id = await _replace_kb_doc("memberguide", f"Harborline Member Care Guide {export_date}",
                                         knowledge.member_guide_markdown(export_date, entries),
                                         {**meta, "type": "member_guide", "audience": "member"}, source="cms")
        STATUS["kb"]["cms_mode"] = cms_mode
        STATUS["kb"]["done"] += 1
        # Re-point the AOM RAG applications at today's documents.
        await rag_app.sync_all({"helpcenter": helpcenter_id, "memberguide": guide_id})
    except AOMError as exc:
        log.error("KB publish failed: %s", exc)
        STATUS["kb"].update(state="error", error=str(exc)[:300])
        return
    sem = asyncio.Semaphore(4)

    async def one(uid):
        async with sem:
            p = await store.get("profiles", profile_id(uid))
            if not p:
                return
            try:
                await _replace_kb_doc(uid, f"User profile {uid} {export_date}", knowledge.user_profile_markdown(p),
                                      {"type": "user_profile", "user_id": uid, "audience": p["audience"],
                                       "export_date": export_date, "pii": True, "source": "insurance-export"})
                STATUS["kb"]["done"] += 1
            except AOMError as exc:
                STATUS["kb"]["errors"] += 1
                log.warning("KB publish for %s failed: %s", uid, exc)

    await asyncio.gather(*(one(u) for u in user_ids))
    STATUS["kb"].update(state="published", seconds=round(time.time() - t0, 1), export_date=export_date)
    log.info("Published %d KB documents to AOM in %.1fs", STATUS["kb"]["done"], time.time() - t0)


async def poll_forever():
    while True:
        await asyncio.sleep(config.EXPORT_POLL_SECONDS)
        try:
            part = latest_partition(os.path.abspath(config.EXPORT_DIR))
            if part and partition_date(part) != STATE.get("export_date"):
                log.info("New export detected: %s", part)
                await load()
        except Exception as exc:  # noqa: BLE001
            log.warning("export poll failed: %s", exc)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--export-dir", dest="export_dir")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--no-kb", action="store_true")
    args = ap.parse_args()

    async def run():
        await store.connect()
        await load(args.export_dir, force=args.force, kb=False)
        if not args.no_kb and config.KB_ENABLED and aom.admin_enabled:
            state = await store.get("lookups", "load_state")
            await publish_kb(state["export_date"], await _kb_window())
        print(json.dumps({k: v for k, v in STATUS.items()}, indent=2, default=str))

    asyncio.run(run())


async def _kb_window() -> list[str]:
    """Whose profiles get a KB document: the personas, then people in export
    order up to KB_PROFILE_LIMIT."""
    out = list(PERSONAS)
    rows = await store.users_by_group(limit=max(config.KB_PROFILE_LIMIT * 2, 50))
    out += [r["user_id"] for r in rows if r["user_id"] not in out]
    return out[: max(config.KB_PROFILE_LIMIT, len(PERSONAS))]


if __name__ == "__main__":
    main()
