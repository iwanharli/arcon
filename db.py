"""Lapisan database db_artemis: cache query + penyimpanan hasil ternormalisasi.

Alur pemakaian (lihat store_result / lookup):

    cached = await db.lookup(bot, cmd, value)
    if cached:                      # status 'found' & command tidak volatile
        return cached["fields"]     # tidak perlu hit Telegram
    ...hit Telegram...
    await db.store_result(bot, cmd, value, status, msg, fields)
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

import normalize as N
import routes

DSN = os.getenv("PG_DSN", "postgresql:///db_artemis")

# Kolom profiles yang boleh di-upsert (selain nik yang jadi conflict target).
_PROFILE_COLS = [
    "kk", "shdk", "nama", "tempat_lahir", "tanggal_lahir", "jenis_kelamin",
    "status_kawin", "pekerjaan", "agama", "pendidikan", "alamat", "rt", "rw",
    "kel_desa", "kecamatan", "kab_kota", "provinsi",
    "nik_ayah", "nama_ayah", "nik_ibu", "nama_ibu",
]


async def connect() -> psycopg.AsyncConnection:
    return await psycopg.AsyncConnection.connect(DSN, row_factory=dict_row, autocommit=True)


# ------------------------------------------------------------------- cache

async def lookup(conn, bot: str, cmd: str, value: str) -> dict | None:
    """Kembalikan baris cache kalau boleh dipakai tanpa hit Telegram.

    Aturan:
      - status 'found'                     -> pakai cache
      - status lain (not_found / queue /
        no_response)                       -> None, harus hit Telegram lagi
      - command volatile (lokasi, masa
        aktif)                             -> None, selalu hit ulang
    """
    if routes.is_volatile(bot, cmd):
        return None

    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT * FROM bot_query_cache
             WHERE bot = %s AND cmd = %s AND value = %s AND status = 'found'
            """,
            (bot, cmd, value),
        )
        return await cur.fetchone()


async def upsert_cache(conn, bot: str, cmd: str, value: str, status: str,
                       msg: str | None, fields: Any,
                       tested_at: datetime | None = None) -> int:
    """Simpan/replace hasil query mentah. Kembalikan id baris cache."""
    tested_at = tested_at or datetime.now(timezone.utc)
    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO bot_query_cache (bot, cmd, value, status, msg, fields, tested_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (bot, cmd, value) DO UPDATE SET
                status    = EXCLUDED.status,
                msg       = EXCLUDED.msg,
                fields    = EXCLUDED.fields,
                tested_at = EXCLUDED.tested_at,
                hit_count = bot_query_cache.hit_count + 1
            RETURNING id
            """,
            (bot, cmd, value, status, msg,
             Jsonb(fields) if fields is not None else None, tested_at),
        )
        return (await cur.fetchone())["id"]


# -------------------------------------------------------- app_sessions (riwayat)

async def app_session_upsert(conn, sid: str, username: str, data: dict) -> None:
    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO app_sessions (id, username, data, updated_at)
            VALUES (%s, %s, %s, now())
            ON CONFLICT (id) DO UPDATE SET data = EXCLUDED.data, updated_at = now()
            """,
            (sid, username, Jsonb(data)),
        )


async def app_session_list(conn, username: str) -> list[dict]:
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT data FROM app_sessions WHERE username = %s ORDER BY updated_at DESC",
            (username,))
        return [r["data"] for r in await cur.fetchall()]


async def app_session_get(conn, sid: str, username: str) -> dict | None:
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT data FROM app_sessions WHERE id = %s AND username = %s",
            (sid, username))
        row = await cur.fetchone()
    return row["data"] if row else None


# ------------------------------------------------------------------- media

async def store_media(conn, data: bytes, content_type: str, *, bot: str, cmd: str,
                      value: str, source_query_id: int | None = None) -> str:
    """Simpan satu media, kembalikan id (sha256). Dedup otomatis."""
    import hashlib
    mid = hashlib.sha256(data).hexdigest()
    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO media_blobs (id, content_type, bytes, size, bot, cmd, value, source_query_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO NOTHING
            """,
            (mid, content_type, data, len(data), bot, cmd, value, source_query_id),
        )
    return mid


async def get_media(conn, mid: str) -> dict | None:
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT content_type, bytes FROM media_blobs WHERE id = %s", (mid,))
        return await cur.fetchone()


async def set_cache_media(conn, query_id: int, media_ids: list[str]) -> None:
    async with conn.cursor() as cur:
        await cur.execute(
            "UPDATE bot_query_cache SET media = %s WHERE id = %s",
            (Jsonb(media_ids), query_id))


# ---------------------------------------------------------------- profiles

async def upsert_profile(conn, person: dict, source_query_id: int | None = None) -> int | None:
    """Upsert satu orang ke profiles, dikunci pada NIK.

    Pakai COALESCE: nilai baru yang NULL tidak boleh menimpa data lama yang
    sudah terisi (bot sering mengirim '-' yang dinormalisasi jadi NULL).
    """
    nik = person.get("nik")
    nama = person.get("nama")
    if not nik or not nama:
        return None  # tanpa NIK/nama tidak bisa jadi baris profiles

    cols = [c for c in _PROFILE_COLS]
    values = [person.get(c) for c in cols]
    placeholders = ", ".join(["%s"] * (len(cols) + 1))
    updates = ", ".join(
        f"{c} = COALESCE(EXCLUDED.{c}, profiles.{c})" for c in cols
    )

    async with conn.cursor() as cur:
        await cur.execute(
            f"""
            INSERT INTO profiles (nik, {", ".join(cols)})
            VALUES ({placeholders})
            ON CONFLICT (nik) DO UPDATE SET {updates}
            RETURNING id
            """,
            (nik, *values),
        )
        row = await cur.fetchone()
    return row["id"] if row else None


async def find_profile_id(conn, nik: str | None) -> int | None:
    if not nik:
        return None
    async with conn.cursor() as cur:
        await cur.execute("SELECT id FROM profiles WHERE nik = %s", (nik,))
        row = await cur.fetchone()
    return row["id"] if row else None


# ------------------------------------------------------------ tabel turunan

async def insert_phone(conn, phone: dict, source_query_id: int | None = None) -> None:
    if not phone.get("msisdn"):
        return
    profile_id = await find_profile_id(conn, phone.get("nik"))
    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO profile_phones
                (profile_id, nik, msisdn, operator, pemilik, registered_at, source_query_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (msisdn, nik, registered_at) DO NOTHING
            """,
            (profile_id, phone.get("nik"), phone["msisdn"], phone.get("operator"),
             phone.get("pemilik"), phone.get("registered_at"), source_query_id),
        )


async def insert_vehicle(conn, vehicle: dict, source_query_id: int | None = None) -> None:
    if not any(vehicle.get(k) for k in ("nopol", "nomor_mesin", "nomor_rangka")):
        return
    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO profile_vehicles
                (nopol, nomor_mesin, nomor_rangka, merk, tipe, tahun, warna,
                 pemilik, alamat, source_query_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (nopol, nomor_rangka, nomor_mesin) DO NOTHING
            """,
            (vehicle.get("nopol"), vehicle.get("nomor_mesin"), vehicle.get("nomor_rangka"),
             vehicle.get("merk"), vehicle.get("tipe"), vehicle.get("tahun"),
             vehicle.get("warna"), vehicle.get("pemilik"), vehicle.get("alamat"),
             source_query_id),
        )


async def insert_record(conn, kind: str, subject: str | None, data: dict,
                        source_query_id: int | None = None) -> None:
    if not data:
        return
    profile_id = await find_profile_id(conn, data.get("nik") or subject)
    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO profile_records (profile_id, subject, kind, data, source_query_id)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (kind, subject, data) DO NOTHING
            """,
            (profile_id, subject, kind, Jsonb(_jsonable(data)), source_query_id),
        )


def _jsonable(data: dict) -> dict:
    """date/datetime -> ISO string supaya bisa masuk jsonb."""
    out = {}
    for k, v in data.items():
        out[k] = v.isoformat() if hasattr(v, "isoformat") else v
    return out


# -------------------------------------------------------------- orkestrasi

async def store_result(conn, bot: str, cmd: str, value: str, status: str,
                       msg: str | None = None, fields: Any = None,
                       tested_at: datetime | None = None,
                       media: list[tuple[bytes, str]] | None = None) -> int:
    """Simpan hasil query: cache mentah + normalisasi + media.

    `media` = daftar (bytes, content_type) foto yang menyertai jawaban.
    """
    query_id = await upsert_cache(conn, bot, cmd, value, status, msg, fields, tested_at)

    if media:
        ids = []
        for data, ctype in media:
            ids.append(await store_media(conn, data, ctype, bot=bot, cmd=cmd,
                                         value=value, source_query_id=query_id))
        if ids:
            await set_cache_media(conn, query_id, ids)

    if status != "found" or not fields:
        return query_id

    route = routes.get_route(bot, cmd)
    if route is None:
        return query_id

    records = fields if isinstance(fields, list) else [fields]
    for raw in records:
        data = route.normalizer(raw)
        if not data:
            continue

        if route.target == "profiles":
            await upsert_profile(conn, data, query_id)
        elif route.target == "phones":
            await insert_phone(conn, data, query_id)
        elif route.target == "vehicles":
            await insert_vehicle(conn, data, query_id)
        else:  # records
            subject = data.get("nik") or data.get("msisdn") or data.get("id_pelanggan") or value
            # data orang yang menempel di record khusus tetap dinaikkan ke profiles
            if route.normalizer is N.normalize_person:
                await upsert_profile(conn, data, query_id)
            await insert_record(conn, route.kind or cmd.lstrip("/"), subject, data, query_id)

    return query_id
