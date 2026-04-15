import secrets
from typing import Optional, Tuple

import asyncpg

from settings import (
    LINK_CODE_TTL_SECONDS,
    LINK_DB_DSN,
    LINK_DB_HOST,
    LINK_DB_NAME,
    LINK_DB_PASSWORD,
    LINK_DB_PORT,
    LINK_DB_SSLMODE,
    LINK_DB_USER,
)

DB_POOL: Optional[asyncpg.Pool] = None
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def generate_code(length: int = 8) -> str:
    rng = secrets.SystemRandom()
    return "".join(rng.choice(CODE_ALPHABET) for _ in range(length))


async def get_pool() -> asyncpg.Pool:
    global DB_POOL
    if DB_POOL:
        return DB_POOL

    ssl = None
    if LINK_DB_SSLMODE and LINK_DB_SSLMODE != "disable":
        ssl = True

    if LINK_DB_DSN:
        DB_POOL = await asyncpg.create_pool(dsn=LINK_DB_DSN, min_size=1, max_size=5, ssl=ssl)
    else:
        DB_POOL = await asyncpg.create_pool(
            host=LINK_DB_HOST,
            port=LINK_DB_PORT,
            user=LINK_DB_USER,
            password=LINK_DB_PASSWORD,
            database=LINK_DB_NAME,
            min_size=1,
            max_size=5,
            ssl=ssl,
        )

    return DB_POOL


async def close_pool() -> None:
    global DB_POOL
    if DB_POOL:
        await DB_POOL.close()
        DB_POOL = None


async def init_db(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS link_codes (
                code TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                is_restrict BOOLEAN NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                used_at TIMESTAMPTZ
            )
            """
        )
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_link_codes_created_at ON link_codes(created_at)")


async def purge_expired(conn: asyncpg.Connection) -> None:
    if LINK_CODE_TTL_SECONDS <= 0:
        return
    await conn.execute(
        "DELETE FROM link_codes WHERE created_at < NOW() - ($1 * INTERVAL '1 second')",
        LINK_CODE_TTL_SECONDS,
    )


async def create_link_code(user_id: str, is_restrict: bool, attempts: int = 10) -> Optional[str]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await purge_expired(conn)
        for _ in range(attempts):
            candidate = generate_code(8)
            row = await conn.fetchrow(
                """
                INSERT INTO link_codes (code, user_id, is_restrict)
                VALUES ($1, $2, $3)
                ON CONFLICT DO NOTHING
                RETURNING code
                """,
                candidate,
                user_id,
                is_restrict,
            )
            if row:
                return candidate

    return None


async def consume_link_code(code: str) -> Optional[Tuple[str, bool]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await purge_expired(conn)
            row = await conn.fetchrow(
                """
                SELECT code, user_id, is_restrict, created_at, used_at
                FROM link_codes
                WHERE code = $1
                FOR UPDATE
                """,
                code,
            )
            if not row or row["used_at"] is not None:
                return None

            await conn.execute("UPDATE link_codes SET used_at = NOW() WHERE code = $1", code)
            return row["user_id"], bool(row["is_restrict"])
