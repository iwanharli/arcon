"""Akun login aplikasi (tabel app_users) + hashing password.

Login diverifikasi ke DB db_artemis, bukan .env. Password di-hash PBKDF2-HMAC
-SHA256 dengan salt per-user. Dipakai oleh endpoint /auth/* di api.py dan CLI
manage_users.py.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets

PBKDF2_ITER = 200_000


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITER)
    return f"pbkdf2${PBKDF2_ITER}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iter_s, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(),
                                 bytes.fromhex(salt_hex), int(iter_s))
        return hmac.compare_digest(dk.hex(), hash_hex)
    except (ValueError, AttributeError):
        return False


# --------------------------------------------------------------- operasi DB

async def create_user(conn, username: str, password: str, role: str = "user") -> None:
    if role not in ("admin", "user"):
        raise ValueError("role harus 'admin' atau 'user'")
    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO app_users (username, password, role)
            VALUES (%s, %s, %s)
            ON CONFLICT (username) DO UPDATE SET password = EXCLUDED.password,
                                                 role = EXCLUDED.role
            """,
            (username, hash_password(password), role),
        )


async def verify_login(conn, username: str, password: str) -> dict | None:
    """Kembalikan {username, role} kalau valid & aktif, else None."""
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT username, password, role, active FROM app_users WHERE username = %s",
            (username,))
        row = await cur.fetchone()
    if not row or not row["active"]:
        # tetap hitung hash dummy supaya waktu respons seragam
        verify_password(password, "pbkdf2$1$00$00")
        return None
    if not verify_password(password, row["password"]):
        return None
    async with conn.cursor() as cur:
        await cur.execute(
            "UPDATE app_users SET last_login_at = now() WHERE username = %s", (username,))
    return {"username": row["username"], "role": row["role"]}


async def list_users(conn) -> list[dict]:
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT username, role, active, created_at, last_login_at "
            "FROM app_users ORDER BY username")
        return await cur.fetchall()


async def set_password(conn, username: str, password: str) -> bool:
    async with conn.cursor() as cur:
        await cur.execute(
            "UPDATE app_users SET password = %s WHERE username = %s",
            (hash_password(password), username))
        return cur.rowcount > 0


async def set_role(conn, username: str, role: str) -> bool:
    if role not in ("admin", "user"):
        raise ValueError("role harus 'admin' atau 'user'")
    async with conn.cursor() as cur:
        await cur.execute(
            "UPDATE app_users SET role = %s WHERE username = %s", (role, username))
        return cur.rowcount > 0


async def set_active(conn, username: str, active: bool) -> bool:
    async with conn.cursor() as cur:
        await cur.execute(
            "UPDATE app_users SET active = %s WHERE username = %s", (active, username))
        return cur.rowcount > 0


async def delete_user(conn, username: str) -> bool:
    async with conn.cursor() as cur:
        await cur.execute("DELETE FROM app_users WHERE username = %s", (username,))
        return cur.rowcount > 0
