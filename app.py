import asyncio
import secrets
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from servers import SERVERS, OAuthServer
from settings import (
    COOKIE_SECURE,
    LINK_CODE_TTL_SECONDS,
    LINK_DB_CONNECT_DELAY_SECONDS,
    LINK_DB_CONNECT_RETRIES,
)
from storage import close_pool, consume_link_code, create_link_code, get_pool, init_db
from strings import select_locale, tr

APP = FastAPI()
BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
APP.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


def get_server(name: str) -> OAuthServer:
    server = SERVERS.get(name)
    if server is None or not server.configured:
        raise HTTPException(status_code=404, detail="unsupported_server")
    return server


def error_page(request: Request, locale: str, key: str = "error_subtitle", status_code: int = 400):
    return templates.TemplateResponse(
        request,
        "error.html",
        {
            "request": request,
            "locale": locale,
            "title": tr(locale, "error_title"),
            "subtitle": "",
            "error_text": tr(locale, key),
        },
        status_code=status_code,
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


@APP.get("/api/servers")
async def supported_servers():
    return {"servers": [server.id for server in SERVERS.values() if server.configured]}


@APP.get("/")
@APP.get("/link")
async def link_page(request: Request, server: Optional[str] = None):
    locale = select_locale(request)
    available = [get_server(server)] if server is not None else [s for s in SERVERS.values() if s.configured]
    if not available:
        return error_page(request, locale, "missing_config", 503)
    return templates.TemplateResponse(
        request,
        "link.html",
        {
            "request": request,
            "locale": locale,
            "title": tr(locale, "title"),
            "subtitle": tr(locale, "subtitle"),
            "servers": [
                {"auth_url": "/auth?" + urlencode({"server": s.id}), "button_text": tr(locale, "button", server=s.name)}
                for s in available
            ],
        },
    )


@APP.get("/auth")
async def auth(request: Request, server: str = "bancho"):
    provider = get_server(server)
    state = secrets.token_urlsafe(16)
    params = {
        "client_id": provider.client_id,
        "response_type": "code",
        "scope": "identify",
        "redirect_uri": provider.redirect_url,
        "state": state,
    }
    response = RedirectResponse(provider.base_url + "/oauth/authorize?" + urlencode(params))
    response.set_cookie(
        provider.state_cookie, state, max_age=300, httponly=True, secure=COOKIE_SECURE, samesite="lax"
    )
    return response


async def handle_callback(request: Request, server: str, code: Optional[str], state: Optional[str]):
    provider = get_server(server)
    locale = select_locale(request)
    expected_state = request.cookies.get(provider.state_cookie)

    def fail():
        response = error_page(request, locale)
        response.delete_cookie(provider.state_cookie)
        return response

    if not code or not expected_state or not state:
        return fail()
    if not secrets.compare_digest(expected_state.encode(), state.encode()):
        return fail()

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            token_resp = await client.post(
                provider.base_url + "/oauth/token",
                json={
                    "grant_type": "authorization_code",
                    "client_id": provider.client_id,
                    "client_secret": provider.client_secret,
                    "redirect_uri": provider.redirect_url,
                    "code": code,
                },
            )
            token_resp.raise_for_status()
            access_token = token_resp.json().get("access_token")
            if not isinstance(access_token, str) or not access_token:
                return fail()
            user_resp = await client.get(
                provider.base_url + "/api/v2/me",
                headers={"Authorization": f"Bearer {access_token}", "x-api-version": "20241130"},
            )
            user_resp.raise_for_status()
            user_data = user_resp.json()
        user_id = int(user_data.get("id", 0))
        if user_id <= 0:
            return fail()
    except (httpx.HTTPError, ValueError, TypeError, AttributeError):
        return fail()

    code_value = await create_link_code(str(user_id), bool(user_data.get("is_restricted")), server=provider.id)
    if not code_value:
        return fail()

    minutes = max(1, int(LINK_CODE_TTL_SECONDS / 60)) if LINK_CODE_TTL_SECONDS > 0 else 0
    response = templates.TemplateResponse(
        request,
        "success.html",
        {
            "request": request,
            "locale": locale,
            "title": tr(locale, "success_title"),
            "subtitle": tr(locale, "success_subtitle", command=provider.bot_command, code=code_value),
            "code_label": tr(locale, "code_label"),
            "full_command": f"{provider.bot_command} {code_value}",
            "expires_text": tr(locale, "expires", minutes=minutes),
            "username": str(user_data.get("username") or provider.name + " player"),
            "copy_text": tr(locale, "copy"),
            "copied_text": tr(locale, "copied"),
            "back_text": tr(locale, "back"),
            "back_url": "/link?" + urlencode({"server": provider.id}),
        },
    )
    response.delete_cookie(provider.state_cookie)
    return response


@APP.get("/callback/bancho")
async def callback(request: Request, code: Optional[str] = None, state: Optional[str] = None):
    return await handle_callback(request, "bancho", code, state)


@APP.get("/callback/morasooma")
async def morasooma_callback(request: Request, code: Optional[str] = None, state: Optional[str] = None):
    return await handle_callback(request, "morasooma", code, state)


@APP.get("/api/verify")
async def verify(code: Optional[str] = None, server: str = "bancho"):
    get_server(server)
    if not code:
        raise HTTPException(status_code=400, detail="code_required")
    result = await consume_link_code(code, server=server)
    if not result:
        raise HTTPException(status_code=404, detail="invalid_code")
    user_id, is_restrict = result
    return JSONResponse({"server": server, "user_id": user_id, "is_restrict": is_restrict})
