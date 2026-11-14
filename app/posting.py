"""Publishing logic shared by the website and the Telegram bot."""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable

from . import config, storage, tiktok

ProgressCallback = Callable[[str, str], Awaitable[None]] | None

STATUS_RU = {
    "CREATED": "Создано",
    "PROCESSING_UPLOAD": "Загружаем видео",
    "PROCESSING_DOWNLOAD": "TikTok обрабатывает видео",
    "SEND_TO_USER_INBOX": "Отправлено в черновики TikTok",
    "PUBLISH_COMPLETE": "Опубликовано",
    "FAILED": "Ошибка",
}

PRIVACY_RU = {
    "PUBLIC_TO_EVERYONE": "Все пользователи",
    "MUTUAL_FOLLOW_FRIENDS": "Взаимные подписки",
    "FOLLOWER_OF_CREATOR": "Мои подписчики",
    "SELF_ONLY": "Только я",
}

PRIVACY_LEVELS = tuple(PRIVACY_RU.keys())


def create_demo_account(telegram_user_id: int | None = None) -> dict[str, Any]:
    if telegram_user_id is not None:
        existing = storage.get_latest_account_for_telegram(telegram_user_id)
        if existing and existing["open_id"].startswith("demo_"):
            return existing
    suffix = uuid.uuid4().hex[:12]
    now = time.time()
    return storage.upsert_account(
        open_id=f"demo_{suffix}",
        union_id=None,
        access_token="demo-token",
        refresh_token="demo-refresh",
        expires_at=now + 365 * 86400,
        refresh_expires_at=now + 365 * 86400,
        scope=config.TIKTOK_SCOPES,
        display_name="Video Scheduler Demo",
        username="video.scheduler",
        avatar_url=None,
        telegram_user_id=telegram_user_id,
    )


async def ensure_access_token(account: dict[str, Any]) -> str:
    if config.DEMO_MODE or str(account.get("open_id", "")).startswith("demo_"):
        return "demo-token"
    if account.get("access_token") and (
        not account.get("expires_at") or account["expires_at"] - time.time() > 120
    ):
        return account["access_token"]
    refresh_value = account.get("refresh_token")
    if not refresh_value:
        raise tiktok.TikTokError(
            "Сессия TikTok истекла. Подключите аккаунт заново."
        )
    data = await tiktok.refresh_token(refresh_value)
    expires_at = time.time() + int(data.get("expires_in", 86400))
    refresh_expires_at = time.time() + int(
        data.get("refresh_expires_in", 31536000)
    )
    storage.update_account_tokens(
        account["id"],
        access_token=data["access_token"],
        refresh_token=data.get("refresh_token", refresh_value),
        expires_at=expires_at,
        refresh_expires_at=refresh_expires_at,
    )
    return data["access_token"]


async def publish(
    account: dict[str, Any],
    *,
    mode: str,
    title: str,
    privacy_level: str,
    video_path: Path,
    progress: ProgressCallback = None,
) -> dict[str, Any]:
    """Upload a video and return ``{publish_id, status}``.

    ``mode='inbox'`` sends the video to the creator's TikTok inbox as a draft
    (works for unaudited apps). ``mode='direct'`` publishes immediately and
    requires an audited Content Posting API client.
    """
    if mode not in {"inbox", "direct"}:
        raise tiktok.TikTokError("Неизвестный режим публикации")
    if not video_path.exists() or video_path.stat().st_size == 0:
        raise tiktok.TikTokError("Видеофайл не найден или пуст")

    video_size = video_path.stat().st_size

    if config.DEMO_MODE or str(account.get("open_id", "")).startswith("demo_"):
        if progress:
            await progress("PROCESSING_UPLOAD", "Демо-режим: загружаем видео")
        return {
            "publish_id": f"demo_{uuid.uuid4().hex[:20]}",
            "status": "PROCESSING_UPLOAD",
        }

    token = await ensure_access_token(account)

    if progress:
        await progress("PROCESSING_UPLOAD", "Проверяем настройки аккаунта")
    creator = await tiktok.get_creator_info(token)
    options = creator.get("privacy_level_options") or ["SELF_ONLY"]
    if privacy_level not in options:
        if mode == "direct":
            raise tiktok.TikTokError(
                "TikTok не разрешает выбранный уровень приватности для этого "
                "аккаунта. Доступны: "
                + ", ".join(PRIVACY_RU.get(item, item) for item in options)
            )
        privacy_level = "SELF_ONLY"

    if mode == "direct":
        result = await tiktok.init_direct_post(
            token,
            title=title,
            privacy_level=privacy_level,
            video_size=video_size,
        )
    else:
        result = await tiktok.init_inbox_upload(token, video_size=video_size)

    publish_id = result.get("publish_id")
    upload_url = result.get("upload_url")
    if not publish_id or not upload_url:
        raise tiktok.TikTokError("TikTok не вернул publish_id/upload_url")

    if progress:
        await progress("PROCESSING_UPLOAD", "Загружаем видео в TikTok")
    await tiktok.upload_video(upload_url, video_path)

    return {"publish_id": publish_id, "status": "PROCESSING_UPLOAD"}


async def refresh_post_status(post: dict[str, Any]) -> dict[str, Any]:
    """Fetch the current status for a post and persist it."""
    if post["status"] in {"PUBLISH_COMPLETE", "SEND_TO_USER_INBOX", "FAILED"}:
        return post

    if config.DEMO_MODE or str(post.get("publish_id", "")).startswith("demo_"):
        status = demo_status(post)
        if status != post["status"]:
            storage.update_post(post["id"], status=status)
            post = {**post, "status": status}
        return post

    if not post.get("publish_id"):
        return post
    account = storage.get_account(post["account_id"])
    if not account:
        storage.update_post(
            post["id"], status="FAILED", fail_reason="Аккаунт удалён"
        )
        return {**post, "status": "FAILED", "fail_reason": "Аккаунт удалён"}

    token = await ensure_access_token(account)
    data = await tiktok.fetch_status(token, post["publish_id"])
    status = data.get("status", "PROCESSING_UPLOAD")
    fail_reason = data.get("fail_reason") or None
    if status != post["status"] or fail_reason:
        storage.update_post(
            post["id"], status=status, fail_reason=fail_reason
        )
        post = {**post, "status": status, "fail_reason": fail_reason}
    return post


def demo_status(post: dict[str, Any]) -> str:
    created_at = post.get("created_at")
    if created_at is None:
        created_at = time.time()
    elapsed = time.time() - float(created_at)
    if elapsed < 3.5:
        return "PROCESSING_UPLOAD"
    if elapsed < 7.0:
        return "PROCESSING_DOWNLOAD"
    if post["mode"] == "inbox":
        return "SEND_TO_USER_INBOX"
    return "PUBLISH_COMPLETE"
