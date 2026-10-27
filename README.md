# Link backend

A small OAuth bridge for linking Bancho and optionally Morasooma accounts. It generates a one-time code after OAuth and exposes an API for the bot to verify the code for the selected server.

## Endpoints

- `GET /api/servers` - returns configured servers, e.g. `{ "servers": ["bancho", "morasooma"] }`
- `GET /link` - landing page with buttons for configured servers
- `GET /link?server=morasooma` - landing page for one configured server
- `GET /auth?server=bancho` - redirects to the selected server's OAuth provider; defaults to Bancho
- `GET /callback/bancho` - Bancho OAuth redirect handler
- `GET /callback/morasooma` - Morasooma OAuth redirect handler
- `GET /api/verify?code=...&server=morasooma` - returns `{ "server": "morasooma", "user_id": "...", "is_restrict": true|false }`

Omitting `server` on `/api/verify` preserves the Bancho flow. Codes belong to one server, expire according to `LINK_CODE_TTL_SECONDS`, and can be used only once. Supplying a code for a different server does not consume it. Existing stored codes are migrated as Bancho codes on startup.

## Optional Morasooma support

Create an OAuth application in Morasooma settings and configure `MORASOOMA_OAUTH_CLIENT_ID` and `MORASOOMA_OAUTH_CLIENT_SECRET`. Register `https://your-link-domain/callback/morasooma` as the callback URL. Configure Bancho to use `https://your-link-domain/callback/bancho`.

The redirect base defaults to `OSU_OAUTH_REDIRECT_URL_BASE`. Set `MORASOOMA_OAUTH_REDIRECT_URL_BASE` separately when needed. Morasooma is omitted from `/api/servers` and the landing page until all of its OAuth settings are present. The success page uses `MORASOOMA_BOT_LINK_COMMAND` (default `m link`); Bancho keeps `BOT_LINK_COMMAND` (default `s link`). Both providers can use the same backend and database.

## Docker

```bash
docker build -t osu-link-backend .
docker run --rm -p 8000:8000 --env-file .env osu-link-backend
```

## Docker compose

```bash
docker compose up --build
```

## Bot configuration

Set these in the bot `.env`:

```
OSU_LINK_API_URL=http://osubot-link-backend:9733
OSU_LINK_PAGE_URL=https://link.example.com/link
```

The bot reads `/api/servers` to decide which servers use code verification. Its verify requests must include the same server ID and check the returned `server` before saving the account.

## Tests

```bash
python -m unittest discover -s tests -v
```
