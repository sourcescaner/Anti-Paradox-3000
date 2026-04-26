import asyncpg
import os
import logging

logger = logging.getLogger(__name__)

_pool = None


async def get_pool():
    global _pool
    if _pool is None:
        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            raise RuntimeError("DATABASE_URL not set")
        _pool = await asyncpg.create_pool(database_url)
    return _pool


async def init_db():
    """Создаёт таблицу users если её нет."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id     BIGINT PRIMARY KEY,
                used        INTEGER DEFAULT 0,
                paid        INTEGER DEFAULT 0,
                created_at  TIMESTAMP DEFAULT NOW(),
                updated_at  TIMESTAMP DEFAULT NOW()
            )
        """)
    logger.info("Database initialized OK")


async def get_user(user_id: int) -> dict:
    """Возвращает запись пользователя или дефолт если не найден."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT user_id, used, paid FROM users WHERE user_id = $1", user_id
        )
    if row is None:
        return {"user_id": user_id, "used": 0, "paid": 0}
    return dict(row)


async def increment_used(user_id: int):
    """Увеличивает счётчик использованных анализов на 1."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO users (user_id, used, paid, updated_at)
            VALUES ($1, 1, 0, NOW())
            ON CONFLICT (user_id) DO UPDATE
            SET used = users.used + 1, updated_at = NOW()
        """, user_id)


async def add_paid(user_id: int, amount: int):
    """Зачисляет оплаченные анализы."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO users (user_id, used, paid, updated_at)
            VALUES ($1, 0, $2, NOW())
            ON CONFLICT (user_id) DO UPDATE
            SET paid = users.paid + $2, updated_at = NOW()
        """, user_id, amount)


async def is_limit_reached(user_id: int) -> bool:
    """Проверяет достиг ли пользователь лимита анализов."""
    from config import MAX_FREE_ANALYSES
    user = await get_user(user_id)
    allowed = MAX_FREE_ANALYSES + user["paid"]
    return user["used"] >= allowed


async def get_remaining(user_id: int) -> int:
    """Возвращает сколько анализов осталось."""
    from config import MAX_FREE_ANALYSES
    user = await get_user(user_id)
    allowed = MAX_FREE_ANALYSES + user["paid"]
    return max(0, allowed - user["used"])


async def get_all_users() -> list:
    """Возвращает всех пользователей для /stats."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT user_id, used, paid FROM users ORDER BY used DESC"
        )
    return [dict(r) for r in rows]
