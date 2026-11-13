"""Sync Gateway admin calls: one SG user per person, and session minting.

A person signs in to this backend (account number + last name); the backend
makes sure an SG user named after the user_id exists with exactly their
channels - `user:<user_id>` and `catalog`, plus `members` for a health or
pet plan member - and mints a session. The phone hands that session to Couchbase
Lite's SessionAuthenticator, the same way mobile_field_service does, so a
replicator can only ever pull its own documents, and the Member Care Guide
document never reaches a phone without one of those plans.
"""
from __future__ import annotations

import logging
import secrets

import httpx

from . import config
from .docs import channels_for
from .store import SYNCED_COLLECTIONS

log = logging.getLogger("insurance.sgw")


def enabled() -> bool:
    return bool(config.SG_ADMIN_URL)


async def mint_session(user_id: str, audience: str) -> dict | None:
    if not enabled():
        return None
    auth = (config.SG_ADMIN_USERNAME, config.SG_ADMIN_PASSWORD)
    base = f"{config.SG_ADMIN_URL}/{config.SG_DB}"
    async with httpx.AsyncClient(timeout=10, auth=auth) as c:
        user = {"name": user_id, "password": secrets.token_urlsafe(24)}
        # Collection-scoped channel grants (SG 3.x named collections).
        user["collection_access"] = {
            config.COUCHBASE_SCOPE: {col: {"admin_channels": channels_for(audience, user_id)} for col in SYNCED_COLLECTIONS}}
        r = await c.put(f"{base}/_user/{user_id}", json=user)
        if r.status_code >= 400:
            log.warning("SG user upsert failed: %s %s", r.status_code, r.text[:200])
            return None
        r = await c.post(f"{base}/_session", json={"name": user_id, "ttl": config.SG_SESSION_TTL_SECONDS})
        if r.status_code >= 400:
            log.warning("SG session failed: %s %s", r.status_code, r.text[:200])
            return None
        s = r.json()
        return {"session_id": s.get("session_id"), "cookie_name": s.get("cookie_name", "SyncGatewaySession"),
                "expires": s.get("expires"), "db": config.SG_DB, "url": config.SG_PUBLIC_URL or None}
