import asyncio
import secrets
from typing import Optional
from urllib.parse import urlencode
from pathlib import Path

import httpx
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from settings import (
    BOT_LINK_COMMAND,
    COOKIE_SECURE,
    LINK_CODE_TTL_SECONDS,
    LINK_DB_CONNECT_DELAY_SECONDS,
    LINK_DB_CONNECT_RETRIES,
    OSU_CLIENT_ID,
    OSU_CLIENT_SECRET,
    OSU_REDIRECT_URL_BASE,
)
from storage import close_pool, consume_link_code, create_link_code, get_pool, init_db
from strings import select_locale, tr

APP = FastAPI()
BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
APP.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


def require_config(request: Request, locale: str):
    if OSU_CLIENT_ID and OSU_CLIENT_SECRET and OSU_REDIRECT_URL_BASE:
        return None
    return templates.TemplateResponse(
        "error.html",
        {
            "request": request,
            "locale": locale,
            "title": tr(locale, "error_title"),
            "subtitle": "",
            "error_text": tr(locale, "missing_config"),
        },
    )


@APP.on_event("startup")
async def on_startup() -> None:
    last_error: Exception | None = None
    for attempt in range(1, LINK_DB_CONNECT_RETRIES + 1):
        try:
            pool = await get_pool()
            async with pool.acquire() as conn:
                await conn.execute("SELECT 1")
            await init_db(pool)
            return
        except Exception as exc:
            last_error = exc
            await close_pool()
            if attempt < LINK_DB_CONNECT_RETRIES:
                await asyncio.sleep(LINK_DB_CONNECT_DELAY_SECONDS)

    if last_error:
        raise last_error


@APP.on_event("shutdown")
async def on_shutdown() -> None:
    await close_pool()


@APP.get("/")
async def root(request: Request):
    return await link_page(request)


@APP.get("/link")
async def link_page(request: Request):
    locale = select_locale(request)
    error_page = require_config(request, locale)
    if error_page:
        return error_page

    return templates.TemplateResponse(
        "link.html",
        {
            "request": request,
            "locale": locale,
            "title": tr(locale, "title"),
            "subtitle": tr(locale, "subtitle"),
            "body_text": "",
            "button_text": tr(locale, "button"),
        },
    )


@APP.get("/auth")
async def auth(request: Request):
    locale = select_locale(request)
    error_page = require_config(request, locale)
    if error_page:
        return error_page

    state = secrets.token_urlsafe(16)
    params = {
        "client_id": OSU_CLIENT_ID,
        "response_type": "code",
        "scope": "identify",
        "redirect_uri": OSU_REDIRECT_URL_BASE,
        "state": state,
    }
    url = "https://osu.ppy.sh/oauth/authorize?" + urlencode(params)
    response = RedirectResponse(url)
    response.set_cookie(
        "osu_link_state",
        state,
        max_age=300,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="lax",
    )
    return response


@APP.get("/callback")
async def callback(request: Request, code: Optional[str] = None, state: Optional[str] = None):
    locale = select_locale(request)
    error_page = require_config(request, locale)
    if error_page:
        return error_page

    if not code:
        return templates.TemplateResponse(
            "error.html",
            {
                "request": request,
                "locale": locale,
                "title": tr(locale, "error_title"),
                "subtitle": "",
                "error_text": tr(locale, "error_subtitle"),
            },
        )

    expected_state = request.cookies.get("osu_link_state")
    if expected_state and state and expected_state != state:
        return templates.TemplateResponse(
            "error.html",
            {
                "request": request,
                "locale": locale,
                "title": tr(locale, "error_title"),
                "subtitle": "",
                "error_text": tr(locale, "error_subtitle"),
            },
        )

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            token_resp = await client.post(
                "https://osu.ppy.sh/oauth/token",
                json={
                    "grant_type": "authorization_code",
                    "client_id": OSU_CLIENT_ID,
                    "client_secret": OSU_CLIENT_SECRET,
                    "redirect_uri": OSU_REDIRECT_URL_BASE + "/callback",
                    "code": code,
                },
            )
            token_resp.raise_for_status()
            token_data = token_resp.json()
            access_token = token_data.get("access_token")
            if not access_token:
                raise RuntimeError("no_access_token")

            user_resp = await client.get(
                "https://osu.ppy.sh/api/v2/me",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "x-api-version": "20241130",
                },
            )
            user_resp.raise_for_status()
            user_data = user_resp.json()
    except Exception:
        return templates.TemplateResponse(
            "error.html",
            {
                "request": request,
                "locale": locale,
                "title": tr(locale, "error_title"),
                "subtitle": "",
                "error_text": tr(locale, "error_subtitle"),
            },
        )

    user_id = user_data.get("id")
    username = user_data.get("username") or "osu! player"
    is_restrict = bool(user_data.get("is_restricted"))

    if not user_id:
        return templates.TemplateResponse(
            "error.html",
            {
                "request": request,
                "locale": locale,
                "title": tr(locale, "error_title"),
                "subtitle": "",
                "error_text": tr(locale, "error_subtitle"),
            },
        )

    code_value = await create_link_code(str(user_id), is_restrict)

    if not code_value:
        return templates.TemplateResponse(
            "error.html",
            {
                "request": request,
                "locale": locale,
                "title": tr(locale, "error_title"),
                "subtitle": "",
                "error_text": tr(locale, "error_subtitle"),
            },
        )

    safe_command = BOT_LINK_COMMAND
    safe_code = code_value
    safe_full_command = f"{BOT_LINK_COMMAND} {code_value}"
    safe_user = str(username)
    minutes = max(1, int(LINK_CODE_TTL_SECONDS / 60)) if LINK_CODE_TTL_SECONDS > 0 else 0
    subtitle = tr(locale, "success_subtitle", command=safe_command, code=safe_code)

    return templates.TemplateResponse(
        "success.html",
        {
            "request": request,
            "locale": locale,
            "title": tr(locale, "success_title"),
            "subtitle": subtitle,
            "code_label": tr(locale, "code_label"),
            "full_command": safe_full_command,
            "expires_text": tr(locale, "expires", minutes=minutes),
            "username": safe_user,
            "copy_text": tr(locale, "copy"),
            "copied_text": tr(locale, "copied"),
            "back_text": tr(locale, "back"),
        },
    )


@APP.get("/api/verify")
async def verify(code: Optional[str] = None):
    if not code:
        raise HTTPException(status_code=400, detail="code_required")

    result = await consume_link_code(code)
    if not result:
        raise HTTPException(status_code=404, detail="invalid_code")

    user_id, is_restrict = result
    return JSONResponse({"user_id": user_id, "is_restrict": is_restrict})
