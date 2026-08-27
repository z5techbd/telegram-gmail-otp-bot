import aiosqlite
import json
import time
from config import DB_PATH

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                first_name TEXT,
                username TEXT,
                step_state TEXT DEFAULT NULL,
                step_data TEXT DEFAULT NULL,
                created_at INTEGER
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS gmail_accounts (
                user_id INTEGER PRIMARY KEY,
                email TEXT,
                access_token TEXT,
                refresh_token TEXT,
                expires_at INTEGER,
                updated_at INTEGER,
                last_otp TEXT DEFAULT NULL,
                last_msg_id TEXT DEFAULT NULL
            )
        """)
        # Safe migration for existing DB
        try:
            await db.execute("ALTER TABLE gmail_accounts ADD COLUMN last_otp TEXT DEFAULT NULL")
        except:
            pass
        try:
            await db.execute("ALTER TABLE gmail_accounts ADD COLUMN last_msg_id TEXT DEFAULT NULL")
        except:
            pass
        await db.execute("""
            CREATE TABLE IF NOT EXISTS tempmail_accounts (
                user_id INTEGER PRIMARY KEY,
                email TEXT,
                token TEXT,
                password TEXT,
                created_at INTEGER,
                last_otp TEXT DEFAULT NULL,
                last_msg_id TEXT DEFAULT NULL
            )
        """)
        try:
            await db.execute("ALTER TABLE tempmail_accounts ADD COLUMN last_otp TEXT DEFAULT NULL")
        except:
            pass
        try:
            await db.execute("ALTER TABLE tempmail_accounts ADD COLUMN last_msg_id TEXT DEFAULT NULL")
        except:
            pass
        await db.commit()

async def get_user_state(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT step_state, step_data FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                state, data = row
                try:
                    parsed_data = json.loads(data) if data else {}
                except:
                    parsed_data = {}
                return state, parsed_data
    return None, {}

async def set_user_state(user_id: int, state: str = None, data: dict = None, first_name: str = "", username: str = ""):
    data_str = json.dumps(data) if data else None
    now = int(time.time())
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO users (user_id, first_name, username, step_state, step_data, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                step_state = excluded.step_state,
                step_data = excluded.step_data,
                first_name = COALESCE(NULLIF(excluded.first_name, ''), users.first_name),
                username = COALESCE(NULLIF(excluded.username, ''), users.username)
        """, (user_id, first_name, username, state, data_str, now))
        await db.commit()

async def save_gmail_account(user_id: int, email: str, access_token: str, refresh_token: str, expires_in: int):
    expires_at = int(time.time()) + int(expires_in)
    now = int(time.time())
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO gmail_accounts (user_id, email, access_token, refresh_token, expires_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                email = excluded.email,
                access_token = excluded.access_token,
                refresh_token = COALESCE(NULLIF(excluded.refresh_token, ''), gmail_accounts.refresh_token),
                expires_at = excluded.expires_at,
                updated_at = excluded.updated_at
        """, (user_id, email, access_token, refresh_token, expires_at, now))
        await db.commit()

async def get_gmail_account(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT email, access_token, refresh_token, expires_at, last_otp, last_msg_id FROM gmail_accounts WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return {
                    "email": row[0],
                    "access_token": row[1],
                    "refresh_token": row[2],
                    "expires_at": row[3],
                    "last_otp": row[4],
                    "last_msg_id": row[5]
                }
    return None

async def update_last_delivered_otp(user_id: int, msg_id: str, otp: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE gmail_accounts SET last_msg_id = ?, last_otp = ? WHERE user_id = ?", (msg_id, otp, user_id))
        await db.commit()

async def delete_gmail_account(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM gmail_accounts WHERE user_id = ?", (user_id,))
        await db.commit()

async def save_tempmail(user_id: int, email: str, token: str = "", password: str = ""):
    now = int(time.time())
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO tempmail_accounts (user_id, email, token, password, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                email = excluded.email,
                token = excluded.token,
                password = excluded.password,
                created_at = excluded.created_at
        """, (user_id, email, token, password, now))
        await db.commit()

async def get_tempmail(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT email, token, password, last_otp, last_msg_id FROM tempmail_accounts WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return {
                    "email": row[0],
                    "token": row[1],
                    "password": row[2],
                    "last_otp": row[3],
                    "last_msg_id": row[4]
                }
    return None

async def update_last_delivered_tempmail_otp(user_id: int, msg_id: str, otp: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE tempmail_accounts SET last_msg_id = ?, last_otp = ? WHERE user_id = ?", (msg_id, otp, user_id))
        await db.commit()

async def delete_tempmail(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM tempmail_accounts WHERE user_id = ?", (user_id,))
        await db.commit()
