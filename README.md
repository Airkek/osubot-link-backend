# Link backend

A small OAuth bridge for linking osu! accounts. It generates a one-time code after OAuth and exposes an API for the bot to verify the code.

## Endpoints

- `GET /link` - landing page with a button to start OAuth
- `GET /auth` - redirects to osu! OAuth
- `GET /callback` - OAuth redirect handler, shows the code
- `GET /api/verify?code=...` - returns `{ "user_id": "...", "is_restrict": true|false }`

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
OSU_LINK_API_URL=http://link-backend:8000
OSU_LINK_PAGE_URL=https://link.example.com/link
```
