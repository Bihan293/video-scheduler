"""Thin async client for TikTok Login Kit and the Content Posting API.

Docs:
  https://developers.tiktok.com/doc/login-kit-web
  https://developers.tiktok.com/doc/content-posting-api-get-started

The client only speaks HTTP; persistence and token refresh live in
``app.posting``.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx

from . import config

API_BASE = "https://open.tiktokapis.com"
AUTHORIZE_URL = "https://www.tiktok.com/v2/auth/authorize/"

MIN_CHUNK = 5 * 1024 * 1024
MAX_CHUNK = 64 * 1024 * 1024
MAX_CHUNKS = 1000


class TikTokError(Exception):
    def __init__(self, message: str, code: str = "", log_id: str = ""):
        super().__init__(message)
        self.message = message
        self.code = code
        self.log_id = log_id

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        extra = f" [{self.code}]" if self.code else ""
        return f"{self.message}{extra}"


def _extract_error(payload: Any, status_code: int) -> TikTokError:
    if isinstance(payload, dict):
        err = payload.get("error")
        if isinstance(err, dict):
            return TikTokError(
                err.get("message") or f"TikTok API error (HTTP {status_code})",
                str(err.get("code") or ""),
                str(err.get("log_id") or ""),
            )
        if isinstance(err, str):
            return TikTokError(
                payload.get("error_description") or err,
                err,
            )
    return TikTokError(f"TikTok API error (HTTP {status_code})")


def _check(payload: dict[str, Any], status_code: int) -> dict[str, Any]:
    if status_code >= 400:
        raise _extract_error(payload, status_code)
    err = payload.get("error")
    if isinstance(err, dict) and err.get("code") not in (None, "", "ok"):
        raise TikTokError(
            err.get("message", "TikTok API error"),
            str(err.get("code", "")),
            str(err.get("log_id", "")),
        )
    if isinstance(err, str) and err and err != "ok":
        raise _extract_error(payload, status_code)
    return payload.get("data") or payload


def authorize_url(state: str) -> str:
    params = {
        "client_key": config.TIKTOK_CLIENT_KEY,
        "scope": config.TIKTOK_SCOPES,
        "response_type": "code",
        "redirect_uri": config.TIKTOK_REDIRECT_URI,
        "state": state,
        "disable_auto_auth": "1",
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


async def exchange_code(code: str) -> dict[str, Any]:
    data = {
        "client_key": config.TIKTOK_CLIENT_KEY,
        "client_secret": config.TIKTOK_CLIENT_SECRET,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": config.TIKTOK_REDIRECT_URI,
    }
    async with httpx.AsyncClient(timeout=45) as client:
        resp = await client.post(
            f"{API_BASE}/v2/oauth/token/",
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    return _check(resp.json(), resp.status_code)


async def refresh_token(refresh_token_value: str) -> dict[str, Any]:
    data = {
        "client_key": config.TIKTOK_CLIENT_KEY,
        "client_secret": config.TIKTOK_CLIENT_SECRET,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token_value,
    }
    async with httpx.AsyncClient(timeout=45) as client:
        resp = await client.post(
            f"{API_BASE}/v2/oauth/token/",
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    return _check(resp.json(), resp.status_code)


async def _api(
    method: str,
    path: str,
    *,
    token: str,
    body: dict[str, Any] | None = None,
    timeout: float = 60,
) -> dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=UTF-8",
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.request(
            method, f"{API_BASE}{path}", headers=headers, json=body or {}
        )
    try:
        payload = resp.json()
    except ValueError as exc:  # pragma: no cover - defensive
        raise TikTokError(
            f"TikTok вернул не-JSON ответ (HTTP {resp.status_code})"
        ) from exc
    return _check(payload, resp.status_code)


async def get_user_info(token: str) -> dict[str, Any]:
    fields = "open_id,union_id,avatar_url,display_name,username"
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=45) as client:
        resp = await client.get(
            f"{API_BASE}/v2/user/info/?fields={fields}", headers=headers
        )
    data = _check(resp.json(), resp.status_code)
    return data.get("user", {})


async def get_creator_info(token: str) -> dict[str, Any]:
    return await _api("POST", "/v2/post/publish/creator_info/query/", token=token)


def chunk_plan(video_size: int) -> tuple[int, int]:
    """Return (chunk_size, total_chunk_count) accepted by TikTok.

    TikTok requires ``total_chunk_count = floor(video_size / chunk_size)``.
    The trailing bytes are merged into the final chunk (up to 128 MB), so the
    last chunk may be larger than ``chunk_size``.
    """
    if video_size <= 0:
        raise TikTokError("Пустой видеофайл")
    if video_size <= MIN_CHUNK:
        return video_size, 1
    chunk_size = max(MIN_CHUNK, math.ceil(video_size / 10))
    chunk_size = min(chunk_size, MAX_CHUNK)
    total = max(1, video_size // chunk_size)
    if total > MAX_CHUNKS:  # pragma: no cover - only for enormous files
        raise TikTokError("Видео слишком большое для загрузки по частям")
    return chunk_size, total


async def init_direct_post(
    token: str,
    *,
    title: str,
    privacy_level: str,
    video_size: int,
    disable_comment: bool = False,
    disable_duet: bool = False,
    disable_stitch: bool = False,
) -> dict[str, Any]:
    chunk_size, total_chunks = chunk_plan(video_size)
    body = {
        "post_info": {
            "title": title[:2200],
            "privacy_level": privacy_level,
            "disable_comment": disable_comment,
            "disable_duet": disable_duet,
            "disable_stitch": disable_stitch,
            "video_cover_timestamp_ms": 1000,
            "brand_content_toggle": False,
            "brand_organic_toggle": False,
        },
        "source_info": {
            "source": "FILE_UPLOAD",
            "video_size": video_size,
            "chunk_size": chunk_size,
            "total_chunk_count": total_chunks,
        },
    }
    return await _api("POST", "/v2/post/publish/video/init/", token=token, body=body)


async def init_inbox_upload(
    token: str, *, video_size: int
) -> dict[str, Any]:
    chunk_size, total_chunks = chunk_plan(video_size)
    body = {
        "source_info": {
            "source": "FILE_UPLOAD",
            "video_size": video_size,
            "chunk_size": chunk_size,
            "total_chunk_count": total_chunks,
        }
    }
    return await _api(
        "POST", "/v2/post/publish/inbox/video/init/", token=token, body=body
    )


async def upload_video(upload_url: str, video_path: Path) -> None:
    size = video_path.stat().st_size
    chunk_size, total_chunks = chunk_plan(size)
    mime = {
        ".mp4": "video/mp4",
        ".m4v": "video/mp4",
        ".mov": "video/quicktime",
        ".webm": "video/webm",
    }.get(video_path.suffix.lower(), "video/mp4")
    with video_path.open("rb") as fh:
        for index in range(total_chunks):
            start = index * chunk_size
            # The final chunk absorbs the trailing bytes and may exceed
            # chunk_size (TikTok allows up to 128 MB for the last chunk).
            chunk = fh.read() if index == total_chunks - 1 else fh.read(chunk_size)
            end = start + len(chunk) - 1
            headers = {
                "Content-Type": mime,
                "Content-Length": str(len(chunk)),
                "Content-Range": f"bytes {start}-{end}/{size}",
            }
            last_error: Exception | None = None
            for attempt in range(3):
                try:
                    async with httpx.AsyncClient(timeout=300) as client:
                        resp = await client.put(
                            upload_url, content=chunk, headers=headers
                        )
                    if resp.status_code in (200, 201, 204, 206):
                        last_error = None
                        break
                    last_error = TikTokError(
                        f"Загрузка части {index + 1}/{total_chunks} не удалась "
                        f"(HTTP {resp.status_code})"
                    )
                except httpx.HTTPError as exc:  # pragma: no cover - network
                    last_error = exc
                if attempt < 2:
                    import asyncio

                    await asyncio.sleep(1.5 * (attempt + 1))
            if last_error is not None:
                if isinstance(last_error, TikTokError):
                    raise last_error
                raise TikTokError(f"Сеть при загрузке видео: {last_error}")


async def fetch_status(token: str, publish_id: str) -> dict[str, Any]:
    return await _api(
        "POST",
        "/v2/post/publish/status/fetch/",
        token=token,
        body={"publish_id": publish_id},
    )
