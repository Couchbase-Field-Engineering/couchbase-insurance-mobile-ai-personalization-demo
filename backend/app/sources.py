"""Clients for the systems of record behind the app. See datagen/README.md.

Two sources, two modes each:

* **Live profile lookup** - the person's *current* record in their system of
  record: the policy administration system for policyholders, the member
  platform for health and pet members, the on-demand platform for people who
  buy cover by the day. Called when the assistant assembles a person's
  context (an AOM Context Cache miss); the round trip is the
  `source_latency_ms` the Context Cache records. With `SOR_PROFILE_API_URL`
  configured it calls `GET <url>/<audience>/<user_id>`; without it (`mock`)
  it answers from the profile the nightly export loaded into Couchbase, with
  the latency such a call has in practice, so the demo shows the same cache
  economics.
* **CMS** - the Help Center and Member Care Guide entries. With
  `CMS_KB_ENDPOINT` configured it fetches them; without it the bundled
  entries in knowledge.FAQ are served in the same shape.

The nightly batch (export -> loader.py) is the third touchpoint and needs no
client here: the files simply land in EXPORT_DIR.
"""
from __future__ import annotations

import asyncio
import logging
import random
import time

import httpx

from . import config

log = logging.getLogger("insurance.sources")

SYSTEM_OF = {"policyholder": ("pas", "Policy administration"), "member": ("members", "Member platform"), "ondemand": ("ondemand", "On-demand platform")}
STATUS: dict = {"profile": {"mode": "mock", "calls": 0, "errors": 0, "last_latency_ms": None, "by_system": {}},
                "cms": {"mode": "mock", "calls": 0, "errors": 0}}


class SourceError(Exception):
    pass


_client = httpx.AsyncClient(timeout=config.SOR_TIMEOUT_SECONDS)


def _mock_view(profile: dict) -> dict:
    """What the system of record returns for this person, from the exported
    profile: identity, realized segments, scores."""
    s = profile.get("ml_scores") or {}
    return {
        "identity": profile.get("identity") or {"user_id": profile["user_id"]},
        "segments": [{"id": a["id"], "name": a["name"], "status": a.get("status", "realized")} for a in (profile.get("segments") or [])],
        "scores": {k: v for k, v in s.items() if isinstance(v, (int, float, str))},
        "consent": profile.get("consent"),
        "profile_updated_at": f"{profile.get('export_date')}T05:00:00Z",
    }


async def profile_view(user_id: str, profile: dict | None) -> dict:
    """The person's current system-of-record view + how long it took.
    `profile` is the exported profile from Couchbase (used by the mock, and
    as the fallback if the live call fails)."""
    t0 = time.perf_counter()
    st = STATUS["profile"]
    st["calls"] += 1
    audience = (profile or {}).get("audience", "policyholder")
    system, label = SYSTEM_OF.get(audience, SYSTEM_OF["policyholder"])
    st["by_system"][system] = st["by_system"].get(system, 0) + 1
    empty = {"identity": {"user_id": user_id}, "segments": [], "scores": {}}
    if config.SOR_PROFILE_API_URL:
        st["mode"] = "live"
        try:
            headers = {"Authorization": f"Bearer {config.SOR_API_TOKEN}"} if config.SOR_API_TOKEN else {}
            r = await _client.get(f"{config.SOR_PROFILE_API_URL}/{audience}/{user_id}", headers=headers)
            if r.status_code >= 400:
                raise SourceError(f"profile lookup: HTTP {r.status_code} {r.text[:200]}")
            data = r.json()
            view = {"identity": data.get("identity") or {"user_id": user_id}, "segments": data.get("segments") or [],
                    "scores": data.get("scores") or {}, "consent": data.get("consent"),
                    "profile_updated_at": data.get("updated_at")}
        except (SourceError, httpx.HTTPError, ValueError) as exc:
            st["errors"] += 1
            log.warning("%s profile lookup failed (%s); using the exported profile", label, exc)
            view = _mock_view(profile) if profile else dict(empty)
            view["fallback"] = str(exc)[:120]
    else:
        st["mode"] = "mock"
        # A profile API answers in roughly 120-350 ms; that latency is the
        # point of caching the assembled context.
        await asyncio.sleep(random.uniform(config.SOR_MOCK_LATENCY_MS[0], config.SOR_MOCK_LATENCY_MS[1]) / 1000)
        view = _mock_view(profile) if profile else dict(empty)
    view.update(source=system, source_label=label, mode=st["mode"],
                latency_ms=round((time.perf_counter() - t0) * 1000, 1))
    st["last_latency_ms"] = view["latency_ms"]
    return view


def segments_text(view: dict) -> str:
    names = [m["name"] for m in view.get("segments", []) if m.get("status", "realized") == "realized"]
    return ", ".join(names) if names else "no segment memberships"


async def kb_entries(today: str) -> tuple[list[dict], str]:
    """Help Center + Member Care Guide entries:
    [{section, audience, intent, q, a, keywords}], mode."""
    from . import knowledge  # late import: knowledge renders with these entries
    st = STATUS["cms"]
    st["calls"] += 1
    if config.CMS_KB_ENDPOINT:
        st["mode"] = "live"
        try:
            headers = {"Authorization": f"Bearer {config.CMS_TOKEN}"} if config.CMS_TOKEN else {}
            r = await _client.get(f"{config.CMS_KB_ENDPOINT}/entries", params={"today": today}, headers=headers)
            if r.status_code >= 400:
                raise SourceError(f"CMS: HTTP {r.status_code} {r.text[:200]}")
            entries = [{"section": i.get("section"), "audience": i.get("audience", "all"), "intent": i.get("intent", "general"),
                        "q": i.get("question"), "a": i.get("answer", ""), "keywords": i.get("keywords") or []}
                       for i in r.json().get("items", []) if i.get("question")]
            if entries:
                return entries, "live"
        except (SourceError, httpx.HTTPError, ValueError) as exc:
            st["errors"] += 1
            log.warning("CMS fetch failed (%s); using the bundled entries", exc)
    st["mode"] = "mock"
    return [dict(f) for f in knowledge.FAQ], "mock"
