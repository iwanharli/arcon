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
import logging
import os
from datetime import datetime, timezone
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

import config
import normalize as N
import routes

log = logging.getLogger("artemis.db")

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

    # Slot logis ('bot1') dipakai ulang saat bot target diganti, jadi baris
    # lama bisa punya cmd yang namanya sama tapi berasal dari bot yang sudah
    # tidak dipakai. Hanya baris dari bot yang sekarang aktif yang boleh
    # menjawab; baris tanpa bot_username (sebelum migrasi 010) tidak dipercaya.
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT * FROM bot_query_cache
             WHERE bot = %s AND cmd = %s AND value = %s AND status = 'found'
               AND bot_username = %s
            """,
            (bot, cmd, value, config.resolve(bot)),
        )
        return await cur.fetchone()


async def cached_row(conn, bot: str, cmd: str, value: str) -> dict | None:
    """Baris cache TERBARU untuk (bot, cmd, value) status 'found'.

    Beda dengan lookup: TIDAK memfilter command volatile — dipakai recheck
    Artemis yang hanya membaca database (tanpa hit Telegram), jadi hasil
    volatile (mis. /cptsel) yang sudah pernah tersimpan tetap bisa diambil.
    """
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT * FROM bot_query_cache
             WHERE bot = %s AND cmd = %s AND value = %s AND status = 'found'
             ORDER BY tested_at DESC
             LIMIT 1
            """,
            (bot, cmd, value),
        )
        return await cur.fetchone()


async def upsert_cache(conn, bot: str, cmd: str, value: str, status: str,
                       msg: str | None, fields: Any,
                       tested_at: datetime | None = None,
                       raw_text: str | None = None) -> int:
    """Simpan/replace hasil query mentah. Kembalikan id baris cache."""
    tested_at = tested_at or datetime.now(timezone.utc)
    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO bot_query_cache
                   (bot, cmd, value, status, msg, fields, tested_at, bot_username,
                    raw_text)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (bot, cmd, value) DO UPDATE SET
                status       = EXCLUDED.status,
                msg          = EXCLUDED.msg,
                fields       = EXCLUDED.fields,
                tested_at    = EXCLUDED.tested_at,
                bot_username = EXCLUDED.bot_username,
                raw_text     = COALESCE(EXCLUDED.raw_text, bot_query_cache.raw_text),
                hit_count    = bot_query_cache.hit_count + 1
            RETURNING id
            """,
            (bot, cmd, value, status, msg,
             Jsonb(fields) if fields is not None else None, tested_at,
             config.resolve(bot), raw_text),
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


async def app_session_clear(conn, username: str) -> int:
    """Hapus semua sesi milik user. Kembalikan jumlah baris terhapus."""
    async with conn.cursor() as cur:
        await cur.execute("DELETE FROM app_sessions WHERE username = %s", (username,))
        return cur.rowcount


# ------------------------------------------------------------- user_logs

async def log_insert(conn, username: str, event: str,
                     detail: dict | None = None) -> int:
    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO user_logs (username, event, detail)
            VALUES (%s, %s, %s)
            RETURNING id
            """,
            (username, event, Jsonb(detail) if detail else None),
        )
        return (await cur.fetchone())["id"]


async def log_list(conn, username: str | None = None, limit: int = 200) -> list[dict]:
    """Log aktivitas, terbaru dulu. `username=None` = semua user (admin)."""
    async with conn.cursor() as cur:
        if username:
            await cur.execute(
                """
                SELECT id, username, event, detail, created_at
                  FROM user_logs
                 WHERE username = %s
                 ORDER BY created_at DESC, id DESC
                 LIMIT %s
                """,
                (username, limit),
            )
        else:
            await cur.execute(
                """
                SELECT id, username, event, detail, created_at
                  FROM user_logs
                 ORDER BY created_at DESC, id DESC
                 LIMIT %s
                """,
                (limit,),
            )
        rows = await cur.fetchall()
    out = []
    for r in rows:
        out.append({
            "id": r["id"],
            "username": r["username"],
            "event": r["event"],
            "detail": r["detail"],
            "created_at": str(r["created_at"]),
        })
    return out


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
    """Upsert satu orang ke profiles.

    Dua kunci, sesuai rancangan skema (`nik` nullable, `nama` NOT NULL):

    * ada NIK  -> dikunci pada NIK (UNIQUE nik).
    * tanpa NIK -> dikunci pada (nama, tanggal_lahir) lewat index parsial
      uq_profiles_nama_tanpa_nik (migrasi 012). Pencarian by-nama memang
      sering tidak mengembalikan NIK; sebelum ini hasilnya dibuang.

    Pakai COALESCE: nilai baru yang NULL tidak boleh menimpa data lama yang
    sudah terisi (bot sering mengirim '-' yang dinormalisasi jadi NULL).
    """
    nik = person.get("nik")
    nama = person.get("nama")
    if not nama:
        return None  # nama NOT NULL — tanpa itu tidak ada yang bisa disimpan

    cols = [c for c in _PROFILE_COLS]
    values = [person.get(c) for c in cols]
    placeholders = ", ".join(["%s"] * (len(cols) + 1))
    updates = ", ".join(
        f"{c} = COALESCE(EXCLUDED.{c}, profiles.{c})" for c in cols
    )
    konflik = ("(nik)" if nik else
               "(lower(nama), COALESCE(tanggal_lahir, DATE '0001-01-01')) "
               "WHERE nik IS NULL")

    async with conn.cursor() as cur:
        await cur.execute(
            f"""
            INSERT INTO profiles (nik, {", ".join(cols)})
            VALUES ({placeholders})
            ON CONFLICT {konflik} DO UPDATE SET {updates}
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


async def phones_by_nik(conn, nik: str) -> list[dict]:
    """Ambil nomor HP terdaftar untuk NIK (relasi yang disimpan /reg)."""
    if not nik:
        return []
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT nik, msisdn, operator, registered_at FROM profile_phones "
            "WHERE nik = %s ORDER BY registered_at DESC NULLS LAST",
            (nik,),
        )
        rows = await cur.fetchall()
    out = []
    for r in rows:
        reg = r.get("registered_at")
        out.append({
            "nik": r.get("nik"),
            "nomor": r.get("msisdn"),
            "operator": r.get("operator"),
            "register": reg.isoformat() if hasattr(reg, "isoformat") else reg,
        })
    return out


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
                        source_query_id: int | None = None,
                        profile_id: int | None = None) -> None:
    """Simpan satu record long-tail.

    `profile_id` boleh diberikan langsung oleh pemanggil. Perlu karena
    find_profile_id() hanya bisa mencari lewat NIK, sedangkan profil hasil
    cari-by-nama boleh ber-NIK NULL (migrasi 012) — tanpa ini catatannya
    tersimpan tapi tidak tertaut ke profilnya.
    """
    if not data:
        return
    if profile_id is None:
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


async def _simpan_cadangan(conn, kind: str, value: str, data: dict,
                           query_id: int | None, alasan: str,
                           profile_id: int | None = None) -> None:
    """Jaring pengaman: simpan field apa adanya ke profile_records.

    Dipakai saat hasil ber-status found tapi tidak bisa masuk tabel tujuannya.
    Lebih baik tersimpan mentah dan bisa di-query daripada hilang senyap.
    """
    mentah = N.normalize_raw(data)
    if not mentah:
        log.warning("%s — dan tidak ada field tersisa untuk disimpan", alasan)
        return
    log.warning("%s; disimpan mentah ke profile_records[%s]", alasan, kind)
    subject = mentah.get("nik") or mentah.get("msisdn") or value
    await insert_record(conn, kind, subject, mentah, query_id, profile_id)


# -------------------------------------------------------------- orkestrasi

async def store_result(conn, bot: str, cmd: str, value: str, status: str,
                       msg: str | None = None, fields: Any = None,
                       tested_at: datetime | None = None,
                       media: list[tuple[bytes, str]] | None = None,
                       raw_text: str | None = None) -> int:
    """Simpan hasil query: cache mentah + normalisasi + media.

    `media` = daftar (bytes, content_type) foto yang menyertai jawaban.
    """
    query_id = await upsert_cache(conn, bot, cmd, value, status, msg, fields,
                                  tested_at, raw_text)

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
    kind_cadangan = route.kind or cmd.lstrip("/")
    for raw in records:
        data = route.normalizer(raw)
        if not data:
            # Normalizer tidak mengenali bentuk balasan ini. Dulu record-nya
            # dibuang diam-diam — hasil hanya tersisa di cache dan tidak bisa
            # di-query. Terbukti pada /cuaca: status found, 0 baris tersimpan.
            # Simpan mentahnya supaya lapis queryable tidak bolong.
            await _simpan_cadangan(conn, kind_cadangan, value, raw, query_id,
                                   f"{bot} {cmd}: normalizer "
                                   f"{route.normalizer.__name__} tidak mengenali balasan")
            continue

        if route.target == "profiles":
            pid = await upsert_profile(conn, data, query_id)
            if pid is not None:
                # profiles hanya punya kolom kependudukan baku. Atribut lain
                # yang dikembalikan bot (NIK INSIGHT mengembalikan 28 field:
                # neptu, generasi, kelompok usia, ...) tidak punya kolom dan
                # dulu hilang. Simpan sisanya ke profile_records supaya tetap
                # bisa di-query, tanpa mengotori skema profiles.
                sisa = {k: v for k, v in N.normalize_raw(raw).items()
                        if k not in N.PROFILE_COLUMNS and k != "nik"}
                if sisa:
                    await insert_record(conn, kind_cadangan,
                                        data.get("nik") or value, sisa, query_id,
                                        profile_id=pid)
            if pid is None:
                # profiles dikunci pada NIK dan nama NOT NULL. Hasil pencarian
                # by-nama yang tidak menyertakan NIK tidak bisa masuk ke sana,
                # jadi jangan dibuang — turunkan ke profile_records.
                # Bawa SELURUH atribut, bukan hanya yang punya kolom profiles —
                # kalau tidak, /nikinsight yang mengembalikan 28 field cuma
                # tersimpan 7.
                await _simpan_cadangan(conn, kind_cadangan, value,
                                       {**N.normalize_raw(raw), **data}, query_id,
                                       f"{bot} {cmd}: tanpa NIK/nama, "
                                       f"tidak bisa masuk profiles")
        elif route.target == "phones":
            await insert_phone(conn, data, query_id)
        elif route.target == "vehicles":
            await insert_vehicle(conn, data, query_id)
        else:  # records
            # Normalizer khusus (device/pln/number_info) hanya mengenali
            # sebagian kecil field; sisanya dulu HILANG walau kolom `data`
            # bertipe jsonb. Terbukti pada /btscellid: 22 field mentah, cuma 2
            # tersimpan. Karena itu field kanonik ditumpuk DI ATAS field mentah
            # — nama kanonik menang, tapi tidak ada atribut yang terbuang.
            data = {**N.normalize_raw(raw), **data}
            subject = data.get("nik") or data.get("msisdn") or data.get("id_pelanggan") or value
            # data orang yang menempel di record khusus tetap dinaikkan ke
            # profiles, dan id-nya dipakai supaya record ini TERTAUT ke profil
            # itu — find_profile_id() tidak bisa menemukannya lewat NIK kalau
            # profilnya ber-NIK NULL (hasil cari-by-nama).
            pid = None
            if route.normalizer is N.normalize_person:
                pid = await upsert_profile(conn, data, query_id)
            await insert_record(conn, route.kind or cmd.lstrip("/"), subject, data,
                                query_id, profile_id=pid)

    return query_id
