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
    """
    Confirm the URL + credentials work, and check the account can post styled HTML.
    Returns {ok, user, user_id, unfiltered_html, warning?} or {ok: False, error}.
    """
    if not enabled():
        return {"ok": False, "error": "WordPress isn't configured "
                "(set WORDPRESS_URL / WORDPRESS_USER / WORDPRESS_APP_PASSWORD)."}
    try:
        with httpx.Client(timeout=20) as client:
            r = client.get(_api("/users/me"), auth=_auth(),
                           params={"context": "edit"})
        data = _handle(r)
        caps = data.get("capabilities") or {}
        unfiltered = bool(caps.get("unfiltered_html"))
        out = {"ok": True, "user": data.get("name") or data.get("slug") or "connected",
               "user_id": data.get("id"), "unfiltered_html": unfiltered}
        if not unfiltered:
            out["warning"] = ("This account lacks the 'unfiltered_html' capability, so "
                              "WordPress will strip the post's <style> block and most "
                              "attributes on save — posts arrive unstyled. Use an "
                              "Administrator account (or an Editor on a single-site install).")
        return out
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def list_categories() -> list[dict]:
    """Post categories from WordPress (id + name), for the Content editor dropdown."""
    if not enabled():
        return []
    try:
        with httpx.Client(timeout=20) as client:
            r = client.get(_api("/categories"), auth=_auth(),
                           params={"per_page": 100, "orderby": "name", "order": "asc"})
        rows = _handle(r)
        if isinstance(rows, list):
            return [{"id": c.get("id"), "name": c.get("name", "")} for c in rows if c.get("id")]
    except Exception:  # noqa: BLE001
        pass
    return []


def upload_media(content_bytes: bytes, filename: str, mime: str,
                 alt: Optional[str] = None) -> dict:
    """
    Upload an image to the WordPress media library. Returns
    {"id", "source_url"} — source_url is the absolute URL to use in a post.
    """
    if not enabled():
        raise RuntimeError("WordPress isn't configured.")
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Content-Type": mime or "application/octet-stream",
    }
    with httpx.Client(timeout=60) as client:
        r = client.post(_api("/media"), auth=_auth(), headers=headers, content=content_bytes)
    data = _handle(r)
    media_id = data.get("id")
    source_url = data.get("source_url") or data.get("guid", {}).get("rendered", "")
    # Set alt text (best-effort) so the post keeps meaningful alt attributes.
    if media_id and alt:
        try:
            with httpx.Client(timeout=20) as client:
                client.post(_api(f"/media/{media_id}"), auth=_auth(), json={"alt_text": alt})
        except Exception:  # noqa: BLE001
            pass
    if not media_id or not source_url:
        raise RuntimeError(f"WordPress did not return a usable media record: {str(data)[:200]}")
    return {"id": str(media_id), "source_url": source_url}


def create_or_update_post(title: str, content_html: str, status: str,
                          excerpt: Optional[str] = None, slug: Optional[str] = None,
                          category_id: Optional[str] = None,
                          featured_media: Optional[str] = None,
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
    if slug:
        body["slug"] = slug
    if category_id:
        try:
            body["categories"] = [int(category_id)]
        except (ValueError, TypeError):
            pass
    if featured_media:
        try:
            body["featured_media"] = int(featured_media)
        except (ValueError, TypeError):
            pass
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
    edit_link = f"{config.WORDPRESS_URL}/wp-admin/post.php?post={pid}&action=edit" if pid else ""
    return {"id": str(pid) if pid else "", "link": link,
            "status": data.get("status", status), "edit_link": edit_link}
