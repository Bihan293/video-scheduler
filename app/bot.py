"""Telegram bot for posting videos through the same TikTok backend."""

from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from . import config, posting, storage

log = logging.getLogger(__name__)

WELCOME = (
    "<b>{app}</b>\n\n"
    "Загружаю видео в TikTok через официальный Content Posting API.\n\n"
    "1. Подключите аккаунт кнопкой ниже.\n"
    "2. Отправьте видео с подписью.\n"
    "3. Выберите «В черновики» или «Опубликовать».\n\n"
    "Пароль TikTok вводится только на tiktok.com — бот его не видит."
)

HELP = (
    "<b>Команды</b>\n"
    "/start — подключение и инструкция\n"
    "/status — аккаунт и последние публикации\n"
    "/help — эта справка\n\n"
    "Видео до 20 МБ можно отправить файлом или как видео. "
    "Большие ролики загружайте через сайт {base}/dashboard."
)


def connect_keyboard(telegram_user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔗 Подключить TikTok",
                    url=f"{config.BASE_URL}/auth/tiktok?tg={telegram_user_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🌐 Открыть кабинет", url=f"{config.BASE_URL}/dashboard"
                )
            ],
        ]
    )


def mode_keyboard(pending_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📥 В черновики",
                    callback_data=f"post:inbox:{pending_id}",
                ),
                InlineKeyboardButton(
                    text="🚀 Опубликовать",
                    callback_data=f"post:direct:{pending_id}",
                ),
            ]
        ]
    )


def build_dispatcher() -> Dispatcher:
    dp = Dispatcher()

    @dp.message(F.text == "/start")
    async def start(message: Message) -> None:
        account = storage.get_latest_account_for_telegram(message.from_user.id)
        text = WELCOME.format(app=config.APP_NAME)
        if account:
            text += f"\n\nПодключено: <b>@{account['username'] or account['display_name']}</b>"
        await message.answer(
            text,
            reply_markup=connect_keyboard(message.from_user.id),
            disable_web_page_preview=True,
        )

    @dp.message(F.text == "/help")
    async def help_command(message: Message) -> None:
        await message.answer(HELP.format(base=config.BASE_URL))

    @dp.message(F.text == "/status")
    async def status_command(message: Message) -> None:
        account = storage.get_latest_account_for_telegram(message.from_user.id)
        if not account:
            await message.answer(
                "Аккаунт TikTok не подключён.",
                reply_markup=connect_keyboard(message.from_user.id),
            )
            return
        posts = storage.list_posts(account["id"], 5)
        lines = [
            f"<b>@{account['username'] or account['display_name']}</b>",
            f"open_id: <code>{account['open_id']}</code>",
            "",
        ]
        if not posts:
            lines.append("Публикаций пока нет.")
        for post in posts:
            label = posting.STATUS_RU.get(post["status"], post["status"])
            mode = "публикация" if post["mode"] == "direct" else "черновик"
            lines.append(f"• {label} · {mode} · {post['title'][:40] or 'без описания'}")
            if post["fail_reason"]:
                lines.append(f"  <i>{post['fail_reason'][:120]}</i>")
        await message.answer("\n".join(lines))

    @dp.message(F.video | F.document)
    async def receive_video(message: Message) -> None:
        account = storage.get_latest_account_for_telegram(message.from_user.id)
        if account is None:
            await message.answer(
                "Сначала подключите TikTok.",
                reply_markup=connect_keyboard(message.from_user.id),
            )
            return

        file = message.video or message.document
        mime = getattr(file, "mime_type", "") or ""
        name = getattr(file, "file_name", "") or ""
        if message.document and not (
            mime.startswith("video/") or name.lower().endswith((".mp4", ".mov", ".webm", ".m4v"))
        ):
            await message.answer("Это не похоже на видео. Пришлите MP4, MOV или WEBM.")
            return

        file_size = getattr(file, "file_size", 0) or 0
        if file_size > 20 * 1024 * 1024:
            await message.answer(
                "Telegram не даёт ботам скачивать файлы больше 20 МБ. "
                f"Загрузите это видео через сайт: {config.BASE_URL}/dashboard"
            )
            return

        pending_id = storage.create_pending(
            message.from_user.id, file.file_id, message.caption or ""
        )
        await message.answer(
            f"Видео получено ({file_size / 1048576:.1f} МБ).\n"
            "Куда отправить?",
            reply_markup=mode_keyboard(pending_id),
        )

    @dp.callback_query(F.data.startswith("post:"))
    async def choose_mode(callback: CallbackQuery) -> None:
        await callback.answer()
        try:
            _, mode, raw_id = callback.data.split(":", 2)
            pending_id = int(raw_id)
        except (ValueError, AttributeError):
            await callback.message.edit_text("Не понял команду. Отправьте видео заново.")
            return

        pending = storage.get_pending(pending_id)
        if pending is None or pending["telegram_user_id"] != callback.from_user.id:
            await callback.message.edit_text("Заявка устарела. Отправьте видео заново.")
            return

        account = storage.get_latest_account_for_telegram(callback.from_user.id)
        if account is None:
            await callback.message.edit_text(
                "Аккаунт TikTok отключён. Подключите заново.",
                reply_markup=connect_keyboard(callback.from_user.id),
            )
            storage.delete_pending(pending_id)
            return

        mode_label = "публикацию" if mode == "direct" else "черновики"
        await _edit(callback.message, f"Готовлю {mode_label}…")

        download_path = config.UPLOAD_DIR / f"tg_{uuid.uuid4().hex}.mp4"
        config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        try:
            await callback.bot.download(pending["file_id"], destination=download_path)
        except Exception as exc:  # noqa: BLE001
            log.exception("telegram download failed")
            await _edit(callback.message, f"Не удалось скачать видео: {exc}")
            return

        if not download_path.exists() or download_path.stat().st_size == 0:
            await _edit(callback.message, "Telegram отдал пустой файл. Попробуйте ещё раз.")
            return

        record = storage.create_post(
            account_id=account["id"],
            mode=mode,
            title=pending["title"][:2200],
            privacy_level="SELF_ONLY",
            video_size=download_path.stat().st_size,
            video_path=str(download_path),
            status="PROCESSING_UPLOAD",
        )
        storage.delete_pending(pending_id)

        async def progress(status: str, text: str) -> None:
            await _edit(
                callback.message,
                f"{text}\n\n<i>{posting.STATUS_RU.get(status, status)}</i>",
            )

        try:
            result = await posting.publish(
                account,
                mode=mode,
                title=pending["title"],
                privacy_level="SELF_ONLY",
                video_path=download_path,
                progress=progress,
            )
            storage.update_post(
                record["id"],
                publish_id=result["publish_id"],
                status=result.get("status", "PROCESSING_UPLOAD"),
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("publish failed")
            storage.update_post(
                record["id"], status="FAILED", fail_reason=str(exc)[:1000]
            )
            await _edit(callback.message, f"Ошибка публикации:\n<code>{exc}</code>")
            download_path.unlink(missing_ok=True)
            return

        # Poll for a short while so the user sees the final status.
        post = storage.get_post(record["id"])
        for _ in range(20):
            if post is None or post["status"] in {"PUBLISH_COMPLETE", "FAILED", "SEND_TO_USER_INBOX"}:
                break
            await asyncio.sleep(3)
            try:
                post = await posting.refresh_post_status(post)
            except Exception:  # noqa: BLE001 - transient API hiccup
                break

        if post is None:
            await _edit(callback.message, "Видео отправлено. Проверьте /status.")
            return

        label = posting.STATUS_RU.get(post["status"], post["status"])
        if post["status"] == "FAILED":
            await _edit(
                callback.message,
                f"TikTok отклонил публикацию.\n<code>{post['fail_reason'] or 'без причины'}</code>",
            )
        elif post["status"] == "SEND_TO_USER_INBOX":
            await _edit(
                callback.message,
                "Готово: видео в <b>черновиках TikTok</b>.\n"
                "Откройте приложение TikTok → Профиль → Черновики, "
                "добавьте звук и опубликуйте.",
            )
        elif post["status"] == "PUBLISH_COMPLETE":
            await _edit(callback.message, "Готово: видео опубликовано в TikTok.")
        else:
            await _edit(
                callback.message,
                f"Видео принято TikTok. Статус: <b>{label}</b>.\n"
                "Проверить позже: /status",
            )

        download_path.unlink(missing_ok=True)

    @dp.message(F.text)
    async def fallback(message: Message) -> None:
        await message.answer(
            "Пришлите видео с подписью или используйте /help.",
            reply_markup=connect_keyboard(message.from_user.id),
        )

    return dp


async def _edit(message: Message, text: str) -> None:
    try:
        await message.edit_text(text, disable_web_page_preview=True)
    except TelegramBadRequest:
        pass


async def run_bot() -> None:
    bot = Bot(
        config.TELEGRAM_BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = build_dispatcher()
    log.info("Telegram bot polling started")
    await dp.start_polling(bot, handle_signals=False)
