"""Thin GoHighLevel API v2 client.

Auth: Private Integration Token (PIT) as a Bearer token, plus the required
`Version` header. Base URL: https://services.leadconnectorhq.com

NOTE: The GHL host is blocked by the build sandbox's egress policy, so these
calls are verified at deploy time (wherever the agent actually runs), not from
the build environment. The request shapes below follow the GHL API v2 docs.
"""
from __future__ import annotations

from typing import Any, Optional

import requests

from .config import settings


class GHLClient:
    def __init__(
        self,
        location_id: Optional[str] = None,
        token: Optional[str] = None,
        base: Optional[str] = None,
        version: Optional[str] = None,
        timeout: int = 30,
    ):
        self.location_id = location_id or settings.ghl_location_id
        self.token = token or settings.ghl_private_token
        self.base = (base or settings.ghl_api_base).rstrip("/")
        self.version = version or settings.ghl_api_version
        self.timeout = timeout

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Version": self.version,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        url = f"{self.base}/{path.lstrip('/')}"
        resp = requests.request(
            method, url, headers=self._headers, timeout=self.timeout, **kwargs
        )
        resp.raise_for_status()
        return resp.json() if resp.content else {}

    # --- Connectivity check -------------------------------------------------
    def get_location(self) -> dict[str, Any]:
        """Fetch this location's details. Useful smoke test for the token."""
        return self._request("GET", f"/locations/{self.location_id}")

    # --- Contacts -----------------------------------------------------------
    def search_contacts(self, query: str, limit: int = 10) -> dict[str, Any]:
        """Search contacts within this location by name / phone / email."""
        return self._request(
            "POST",
            "/contacts/search",
            json={"locationId": self.location_id, "query": query, "pageLimit": limit},
        )

    def upsert_contact(self, **fields: Any) -> dict[str, Any]:
        """Create or update a contact (dedup by phone/email within location)."""
        payload = {"locationId": self.location_id, **fields}
        return self._request("POST", "/contacts/upsert", json=payload)

    def add_note(self, contact_id: str, body: str) -> dict[str, Any]:
        """Attach a note (e.g. the call summary) to a contact."""
        return self._request(
            "POST", f"/contacts/{contact_id}/notes", json={"body": body}
        )
