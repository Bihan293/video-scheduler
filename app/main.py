"""FastAPI application: website, OAuth callback and posting API."""

from __future__ import annotations

import secrets
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from . import config, posting, storage, tiktok

BASE_DIR = Path(__file__).resolve().parent
SITE_DIR = config.BASE_DIR / "site"

ALLOWED_EXTENSIONS = {".mp4", ".mov", ".webm", ".m4v"}


@asynccontextmanager
async def lifespan(_: FastAPI):
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    storage.init_db()
    yield


app = FastAPI(title=config.APP_NAME, lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=config.SECRET_KEY,
    same_site="lax",
    https_only=config.BASE_URL.startswith("https"),
)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

templates = Jinja2Templates(directory=BASE_DIR / "templates")
templates.env.globals.update(
    app_name=config.APP_NAME,
    base_url=config.BASE_URL,
    contact_email=config.CONTACT_EMAIL,
    demo_mode=config.DEMO_MODE,
    privacy_levels=posting.PRIVACY_RU,
    status_ru=posting.STATUS_RU,
    max_upload_mb=config.MAX_UPLOAD_MB,
    year=time.gmtime().tm_year,
)


def current_account(request: Request) -> dict[str, Any] | None:
    raw = request.session.get("account_id")
    if not raw:
        return None
    account = storage.get_account(int(raw))
    if account is None:
        request.session.pop("account_id", None)
    return account


def account_public(account: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": account["id"],
        "display_name": account["display_name"] or "TikTok аккаунт",
        "username": account["username"] or "",
        "avatar_url": account["avatar_url"] or "",
        "open_id": account["open_id"],
        "linked_telegram": account["telegram_user_id"],
        "demo": str(account["open_id"]).startswith("demo_"),
    }


def post_public(post: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": post["id"],
        "mode": post["mode"],
        "title": post["title"],
        "privacy_level": post["privacy_level"],
        "privacy_label": posting.PRIVACY_RU.get(
            post["privacy_level"], post["privacy_level"]
        ),
        "status": post["status"],
        "status_label": posting.STATUS_RU.get(post["status"], post["status"]),
        "fail_reason": post["fail_reason"],
        "publish_id": post["publish_id"],
        "video_size": post["video_size"],
        "created_at": post["created_at"],
        "updated_at": post["updated_at"],
    }


# --------------------------------------------------------------------- pages


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    account = current_account(request)
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"account": account_public(account) if account else None},
    )


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    account = current_account(request)
    if account is None:
        return RedirectResponse("/?need_connect=1", status_code=303)
    posts = [post_public(p) for p in storage.list_posts(account["id"], 10)]
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "account": account_public(account),
            "posts": posts,
            "connected": request.query_params.get("connected") == "1",
        },
    )


@app.get("/demo/consent", response_class=HTMLResponse)
async def demo_consent(request: Request, state: str = ""):
    if not config.DEMO_MODE:
        raise HTTPException(status_code=404)
    if not state:
        raise HTTPException(status_code=400, detail="Missing OAuth state")
    scopes = [s.strip() for s in config.TIKTOK_SCOPES.split(",") if s.strip()]
    return templates.TemplateResponse(
        request=request,
        name="demo_consent.html",
        context={"state": state, "scopes": scopes},
    )


@app.get("/error", response_class=HTMLResponse)
async def error_page(request: Request, message: str = "Что-то пошло не так"):
    return templates.TemplateResponse(
        request=request, name="error.html", context={"message": message}
    )


def _serve_site_file(name: str) -> HTMLResponse:
    path = SITE_DIR / name
    if not path.exists():
        raise HTTPException(status_code=404)
    text = path.read_text(encoding="utf-8")
    replacements = {
        "__APP_NAME__": config.APP_NAME,
        "__APP_URL__": config.BASE_URL,
        "__CONTACT_EMAIL__": config.CONTACT_EMAIL or "support@example.com",
        "__YEAR__": str(time.gmtime().tm_year),
        "__UPDATED__": time.strftime("%Y-%m-%d", time.gmtime()),
    }
    for key, value in replacements.items():
        text = text.replace(key, value)
    return HTMLResponse(text)


@app.get("/privacy")
@app.get("/privacy.html")
async def privacy():
    return _serve_site_file("privacy.html")


@app.get("/terms")
@app.get("/terms.html")
async def terms():
    return _serve_site_file("terms.html")


# --------------------------------------------------------------------- OAuth


@app.get("/auth/tiktok")
async def auth_tiktok(request: Request):
    tg_raw = request.query_params.get("tg", "")
    telegram_user_id = int(tg_raw) if tg_raw.isdigit() else None
    state = secrets.token_urlsafe(32)
    storage.create_oauth_state(state, telegram_user_id)
    if config.DEMO_MODE:
        return RedirectResponse(f"/demo/consent?state={state}", status_code=303)
    return RedirectResponse(tiktok.authorize_url(state), status_code=303)


@app.get("/auth/tiktok/callback")
async def auth_callback(
    request: Request, code: str = "", state: str = "", error: str = ""
):
    if error:
        return RedirectResponse(
            f"/error?message={error}", status_code=303
        )
    row = storage.pop_oauth_state(state) if state else None
    if row is None:
        return RedirectResponse(
            "/error?message=Сессия+авторизации+истекла.+Попробуйте+снова",
            status_code=303,
        )
    if not code and not config.DEMO_MODE:
        return RedirectResponse(
            "/error?message=TikTok+не+вернул+код+авторизации", status_code=303
        )

    telegram_user_id = row.get("telegram_user_id")
    try:
        if config.DEMO_MODE or code == "demo":
            account = posting.create_demo_account(telegram_user_id)
        else:
            data = await tiktok.exchange_code(code)
            user = await tiktok.get_user_info(data["access_token"])
            if not user.get("open_id"):
                raise tiktok.TikTokError(
                    "Не удалось получить open_id пользователя TikTok"
                )
            account = storage.upsert_account(
                open_id=user["open_id"],
                union_id=user.get("union_id"),
                access_token=data["access_token"],
                refresh_token=data.get("refresh_token"),
                expires_at=time.time() + int(data.get("expires_in", 86400)),
                refresh_expires_at=time.time()
                + int(data.get("refresh_expires_in", 31536000)),
                scope=data.get("scope", config.TIKTOK_SCOPES),
                display_name=user.get("display_name"),
                username=user.get("username"),
                avatar_url=user.get("avatar_url"),
                telegram_user_id=telegram_user_id,
            )
    except tiktok.TikTokError as exc:
        return RedirectResponse(
            f"/error?message={str(exc)[:300]}", status_code=303
        )

    request.session["account_id"] = account["id"]
    return RedirectResponse("/dashboard?connected=1", status_code=303)


@app.get("/logout")
async def logout(request: Request):
    request.session.pop("account_id", None)
    return RedirectResponse("/", status_code=303)


# ----------------------------------------------------------------------- API


@app.get("/healthz")
@app.get("/health")
async def healthz():
    return {"ok": True, "demo_mode": config.DEMO_MODE}


@app.get("/{filename}")
async def domain_verification(filename: str):
    """Serve TikTok domain-verification files placed in site/."""
    if filename.startswith("tiktok") and filename.endswith(".txt"):
        path = SITE_DIR / filename
        if path.exists():
            return FileResponse(path, media_type="text/plain; charset=utf-8")
    raise HTTPException(status_code=404)


@app.get("/api/account")
async def api_account(request: Request):
    account = current_account(request)
    if account is None:
        raise HTTPException(status_code=401, detail="Not connected")
    return account_public(account)


@app.post("/api/disconnect")
async def api_disconnect(request: Request):
    account = current_account(request)
    if account is not None:
        storage.delete_account(account["id"])
    request.session.pop("account_id", None)
    return {"ok": True}


async def _run_publish(
    post_id: int,
    account: dict[str, Any],
    mode: str,
    title: str,
    privacy_level: str,
    video_path: Path,
) -> None:
    async def progress(status: str, _message: str) -> None:
        storage.update_post(post_id, status=status)

    storage.update_post(post_id, status="PROCESSING_UPLOAD")
    try:
        result = await posting.publish(
            account,
            mode=mode,
            title=title,
            privacy_level=privacy_level,
            video_path=video_path,
            progress=progress,
        )
        storage.update_post(
            post_id,
            publish_id=result["publish_id"],
            status=result.get("status", "PROCESSING_UPLOAD"),
            fail_reason=None,
        )
    except Exception as exc:  # noqa: BLE001 - surface the reason in the UI
        storage.update_post(
            post_id, status="FAILED", fail_reason=str(exc)[:1000]
        )


@app.post("/api/upload")
async def api_upload(
    request: Request,
    background: BackgroundTasks,
    file: UploadFile = File(...),
    title: str = Form(""),
    privacy_level: str = Form("SELF_ONLY"),
    mode: str = Form("inbox"),
):
    account = current_account(request)
    if account is None:
        raise HTTPException(status_code=401, detail="Сначала подключите TikTok")
    if mode not in {"inbox", "direct"}:
        raise HTTPException(status_code=400, detail="Неизвестный режим")
    if privacy_level not in posting.PRIVACY_LEVELS:
        raise HTTPException(status_code=400, detail="Неизвестная приватность")

    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail="Поддерживаются MP4, MOV, WEBM и M4V",
        )

    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    target = config.UPLOAD_DIR / f"{uuid.uuid4().hex}{ext}"
    size = 0
    limit = config.MAX_UPLOAD_MB * 1024 * 1024
    try:
        with target.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Файл больше {config.MAX_UPLOAD_MB} МБ",
                    )
                out.write(chunk)
    except HTTPException:
        target.unlink(missing_ok=True)
        raise
    finally:
        await file.close()

    if size == 0:
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Пустой файл")

    record = storage.create_post(
        account_id=account["id"],
        mode=mode,
        title=title.strip()[:2200],
        privacy_level=privacy_level,
        video_size=size,
        video_path=str(target),
        status="CREATED",
    )
    background.add_task(
        _run_publish,
        record["id"],
        account,
        mode,
        title.strip()[:2200],
        privacy_level,
        target,
    )
    return {"ok": True, "post": post_public(record)}


@app.get("/api/posts")
async def api_posts(request: Request):
    account = current_account(request)
    if account is None:
        raise HTTPException(status_code=401)
    return {
        "posts": [
            post_public(p) for p in storage.list_posts(account["id"], 20)
        ]
    }


@app.get("/api/posts/{post_id}")
async def api_post(request: Request, post_id: int):
    account = current_account(request)
    if account is None:
        raise HTTPException(status_code=401)
    post = storage.get_post(post_id)
    if post is None or post["account_id"] != account["id"]:
        raise HTTPException(status_code=404)
    warning = None
    if post["status"] not in {"PUBLISH_COMPLETE", "FAILED"}:
        try:
            post = await posting.refresh_post_status(post)
        except Exception as exc:  # noqa: BLE001 - keep polling on transient errors
            warning = str(exc)[:300]
    payload = post_public(post)
    if warning:
        payload["warning"] = warning
    return payload


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    if request.url.path.startswith("/api/"):
        return JSONResponse(
            status_code=exc.status_code, content={"error": exc.detail}
        )
    return RedirectResponse(
        f"/error?message={str(exc.detail)[:300]}", status_code=303
    )
