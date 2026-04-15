import os

OSU_CLIENT_ID = os.getenv("OSU_OAUTH_CLIENT_ID")
OSU_CLIENT_SECRET = os.getenv("OSU_OAUTH_CLIENT_SECRET")
OSU_REDIRECT_URL = os.getenv("OSU_OAUTH_REDIRECT_URL")

BOT_LINK_COMMAND = os.getenv("BOT_LINK_COMMAND", "s link")

LINK_DB_DSN = os.getenv("LINK_DB_DSN")
LINK_DB_HOST = os.getenv("LINK_DB_HOST", "link_db")
LINK_DB_PORT = int(os.getenv("LINK_DB_PORT", "5432"))
LINK_DB_NAME = os.getenv("LINK_DB_NAME", "osu_link")
LINK_DB_USER = os.getenv("LINK_DB_USER", "osu_link")
LINK_DB_PASSWORD = os.getenv("LINK_DB_PASSWORD", "osu_link")
LINK_DB_SSLMODE = os.getenv("LINK_DB_SSLMODE", "").lower()

LINK_DB_CONNECT_RETRIES = int(os.getenv("LINK_DB_CONNECT_RETRIES", "30"))
LINK_DB_CONNECT_DELAY_SECONDS = float(os.getenv("LINK_DB_CONNECT_DELAY_SECONDS", "1"))

LINK_CODE_TTL_SECONDS = int(os.getenv("LINK_CODE_TTL_SECONDS", "600"))
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "true").lower() == "true"
