"""
wordpress.py — pushes blog posts to the WordPress CMS via the REST API.

Auth is a WordPress Application Password (Users → Profile → Application Passwords,
built into WP 5.6+): Basic auth over HTTPS, no plugin required. The dashboard
creates or updates a post at /wp-json/wp/v2/posts; the (headless) website reads
from WordPress as usual, so a published post ends up on the live site.

Set WORDPRESS_URL / WORDPRESS_USER / WORDPRESS_APP_PASSWORD in .env.
"""

from __future__ import annotations

from typing import Optional

import httpx

import config


def enabled() -> bool:
    return config.wordpress_enabled()


def _auth() -> tuple[str, str]:
    # Application passwords are shown with spaces for readability; WP accepts
    # them with or without, so we strip spaces to be safe.
    return (config.WORDPRESS_USER, config.WORDPRESS_APP_PASSWORD.replace(" ", ""))


def _api(path: str) -> str:
    return f"{config.WORDPRESS_URL}/wp-json/wp/v2{path}"


def _handle(r: httpx.Response) -> dict:
    if r.status_code >= 400:
        snippet = (r.text or "").strip()
        if len(snippet) > 300:
            snippet = snippet[:300] + "…"
        raise RuntimeError(f"WordPress returned {r.status_code} for "
                           f"{r.request.url.path}. {snippet}")
    try:
        return r.json()
    except Exception:  # noqa: BLE001
        return {}


def test_connection() -> dict:
    """Confirm the URL + credentials work. Returns {ok, user|error}."""
    if not enabled():
        return {"ok": False, "error": "WordPress isn't configured "
                "(set WORDPRESS_URL / WORDPRESS_USER / WORDPRESS_APP_PASSWORD)."}
    try:
        with httpx.Client(timeout=20) as client:
            r = client.get(_api("/users/me"), auth=_auth(),
                           params={"context": "edit"})
        data = _handle(r)
        return {"ok": True, "user": data.get("name") or data.get("slug") or "connected",
                "user_id": data.get("id")}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def create_or_update_post(title: str, content_html: str, status: str,
                          excerpt: Optional[str] = None,
                          post_id: Optional[str] = None) -> dict:
    """
    Create a new post, or update an existing one when post_id is given. `status`
    is 'draft' or 'publish'. Returns {"id", "link", "status", "edit_link"}.
    """
    if not enabled():
        raise RuntimeError("WordPress isn't configured.")
    if status not in ("draft", "publish"):
        raise ValueError("status must be 'draft' or 'publish'.")

    body: dict = {"title": title or "(untitled)", "content": content_html, "status": status}
    if excerpt:
        body["excerpt"] = excerpt
    if config.WORDPRESS_DEFAULT_AUTHOR:
        try:
            body["author"] = int(config.WORDPRESS_DEFAULT_AUTHOR)
        except ValueError:
            pass

    path = f"/posts/{post_id}" if post_id else "/posts"
    with httpx.Client(timeout=30) as client:
        r = client.post(_api(path), auth=_auth(), json=body)
    data = _handle(r)

    pid = data.get("id")
    link = data.get("link", "")
    # A handy wp-admin edit link, best-effort.
    edit_link = f"{config.WORDPRESS_URL}/wp-admin/post.php?post={pid}&action=edit" if pid else ""
    return {"id": str(pid) if pid else "", "link": link,
            "status": data.get("status", status), "edit_link": edit_link}
