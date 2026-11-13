"""In-process counters for the story page's live chapter (/api/status ->
metrics). They reset when the backend restarts; AOM keeps the durable view
(traces, cache pages, audit log)."""
from __future__ import annotations

import datetime as dt

STATS: dict = {
    "assistant_turns": 0, "restricted_turns": 0, "by_area": {"documents": 0, "claims": 0, "roadside": 0, "billing": 0, "telematics": 0, "support": 0, "wellness": 0, "coverage": 0}, "context_hits": 0, "context_misses": 0, "rag_app_turns": 0,
    "llm_calls": 0, "llm_hits": 0,
    "requests": 0, "requests_confirmed": 0, "requests_failed": 0, "requests_awaiting_approval": 0,
    # Created on the phone well before the backend saw it: queued in
    # Couchbase Lite while the person had no connection.
    "requests_queued_offline": 0,
    "since": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
}
OFFLINE_GAP_SECONDS = 20


def assistant(result: dict) -> None:
    STATS["assistant_turns"] += 1
    area = result.get("area")
    if area in STATS["by_area"]:
        STATS["by_area"][area] += 1
    if result.get("restricted"):
        STATS["restricted_turns"] += 1
    ctx = (result.get("context") or {}).get("status")
    if ctx == "hit":
        STATS["context_hits"] += 1
    elif ctx:
        STATS["context_misses"] += 1
    if (result.get("context") or {}).get("source") == "aom-rag":
        STATS["rag_app_turns"] += 1
    llm = (result.get("llm") or {}).get("status") or ""
    if llm and llm not in ("local", "error", "skipped"):
        STATS["llm_calls"] += 1
        if llm.startswith("hit"):
            STATS["llm_hits"] += 1


def request(doc: dict, first: bool) -> None:
    """Count a request's outcome. `first` = its first pass through the worker
    (an approval that resolves later is a second pass of the same request)."""
    status = doc.get("status")
    if status in ("processing", "pending"):
        return
    if first:
        STATS["requests"] += 1
    key = {"confirmed": "requests_confirmed", "accepted": "requests_confirmed", "submitted": "requests_confirmed",
           "failed": "requests_failed", "awaiting_approval": "requests_awaiting_approval"}.get(status)
    if key:
        STATS[key] += 1
    if not first:
        return
    try:
        created = dt.datetime.fromisoformat(str(doc.get("created_at")).replace("Z", "+00:00"))
        if (dt.datetime.now(dt.timezone.utc) - created).total_seconds() > OFFLINE_GAP_SECONDS:
            STATS["requests_queued_offline"] += 1
    except (TypeError, ValueError):
        pass


def reset() -> None:
    for k, v in list(STATS.items()):
        if isinstance(v, int):
            STATS[k] = 0
        elif isinstance(v, dict):
            STATS[k] = {a: 0 for a in v}
    STATS["since"] = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def snapshot() -> dict:
    s = dict(STATS, by_area=dict(STATS["by_area"]))
    turns = s["context_hits"] + s["context_misses"]
    s["context_hit_rate"] = round(100 * s["context_hits"] / turns, 1) if turns else None
    s["llm_hit_rate"] = round(100 * s["llm_hits"] / s["llm_calls"], 1) if s["llm_calls"] else None
    return s
