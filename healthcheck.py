"""Pengecekan kesehatan seluruh command, dijalankan sehari sekali.

    python healthcheck.py            # cek semua command yang punya probe
    python healthcheck.py bot3       # cek satu bot saja
    python healthcheck.py --report   # tampilkan hasil terakhir, tanpa hit bot

Dijadwalkan lewat pm2 (cron_restart) tiap hari jam 02:00 WIB.

Cara kerja penting:

* Healthcheck TIDAK membuka koneksi Telegram sendiri. Ia mengirim job ke API
  lokal (POST /search dengan force=true) dan menunggu hasilnya. Hanya proses
  API yang boleh memegang file session Telegram; kalau healthcheck ikut
  membukanya, file session (SQLite) akan terkunci.
* force=true memaksa job menembak bot sungguhan, bukan membaca cache — kalau
  membaca cache, pengecekan tidak membuktikan kondisi bot.
* Tiap probe memakai nilai yang SUDAH TERBUKTI kondisinya (kolom expect_status),
  supaya 'not_found' tidak ambigu antara "command rusak" dan "data memang tidak
  ada".
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import urllib.error
import urllib.request

import db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("artemis.health")

API_BASE = os.getenv("API_BASE", "http://127.0.0.1:8765")
API_KEY = os.getenv("API_KEY")
JEDA_ANTAR_PROBE = 3       # detik; antrian job sendiri sudah menahan laju hit
POLL_TIMEOUT = 180         # detik maksimal menunggu satu job selesai


def _headers() -> dict:
    h = {"Content-Type": "application/json"}
    if API_KEY:
        h["X-API-Key"] = API_KEY
    return h


def _post_search(bot: str, cmd: str, value: str) -> str:
    """Kirim job force ke API, kembalikan job_id."""
    body = json.dumps({
        "cmd": cmd, "value": value,
        "requested_by": "healthcheck", "priority": -10, "force": True,
    }).encode()
    req = urllib.request.Request(f"{API_BASE}/search/{bot}", data=body,
                                 headers=_headers(), method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)["job_id"]


def _wait_result(job_id: str) -> dict:
    """Long-poll job sampai selesai."""
    req = urllib.request.Request(
        f"{API_BASE}/jobs/{job_id}?wait={POLL_TIMEOUT}", headers=_headers())
    with urllib.request.urlopen(req, timeout=POLL_TIMEOUT + 15) as r:
        return json.load(r)


# ------------------------------------------------------------- probe & catat

async def seed_probes_dari_cache(conn) -> int:
    """Isi command_probes otomatis dari hasil query yang terbukti di cache.

    Berguna di server yang baru: begitu Artemis melakukan pencarian sungguhan,
    nilai yang 'found'/'not_found' diadopsi jadi probe. Command volatile
    (lokasi/masa aktif) dilewati karena hasilnya berubah terus.
    """
    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO command_probes (bot, cmd, probe_value, expect_status, note)
            SELECT DISTINCT ON (bot, cmd) bot, cmd, value, status,
                   'auto-seed dari cache'
              FROM bot_query_cache
             WHERE status IN ('found', 'not_found')
             ORDER BY bot, cmd, tested_at DESC
            ON CONFLICT (bot, cmd) DO NOTHING
            """
        )
        return cur.rowcount


async def ambil_probe(conn, bot: str | None = None) -> list[dict]:
    sql = "SELECT * FROM command_probes WHERE enabled"
    params: tuple = ()
    if bot:
        sql += " AND bot = %s"
        params = (bot,)
    sql += " ORDER BY bot, cmd"
    async with conn.cursor() as cur:
        await cur.execute(sql, params)
        return await cur.fetchall()


async def catat_hasil(conn, probe: dict, status: str | None, ok: bool,
                      msg: str | None) -> None:
    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO command_health_checks
                (bot, cmd, status, ok, msg, probe_value)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (probe["bot"], probe["cmd"], status, ok,
             (msg or "")[:500] or None, probe["probe_value"]),
        )
        await cur.execute(
            """
            INSERT INTO command_health
                (bot, cmd, last_checked_at, last_status, ok,
                 consecutive_failures, last_ok_at, last_msg)
            VALUES (%s, %s, now(), %s, %s, %s, CASE WHEN %s THEN now() END, %s)
            ON CONFLICT (bot, cmd) DO UPDATE SET
                last_checked_at      = now(),
                last_status          = EXCLUDED.last_status,
                ok                   = EXCLUDED.ok,
                consecutive_failures = CASE WHEN EXCLUDED.ok THEN 0
                                            ELSE command_health.consecutive_failures + 1 END,
                last_ok_at           = CASE WHEN EXCLUDED.ok THEN now()
                                            ELSE command_health.last_ok_at END,
                last_msg             = EXCLUDED.last_msg
            """,
            (probe["bot"], probe["cmd"], status, ok, 0 if ok else 1, ok,
             (msg or "")[:500] or None),
        )


async def jalankan(bot: str | None = None) -> int:
    conn = await db.connect()

    n_seed = await seed_probes_dari_cache(conn)
    if n_seed:
        log.info("auto-seed %d probe baru dari cache", n_seed)

    probes = await ambil_probe(conn, bot)
    if not probes:
        log.warning("belum ada probe — jalankan beberapa pencarian dulu supaya "
                    "cache terisi, probe akan terbentuk otomatis.")
        await conn.close()
        return 0

    log.info("mulai cek %d command lewat API %s", len(probes), API_BASE)
    sehat = gagal = 0

    for i, probe in enumerate(probes, 1):
        try:
            job_id = _post_search(probe["bot"], probe["cmd"], probe["probe_value"])
            hasil = _wait_result(job_id)
            status = hasil.get("status")
            msg = hasil.get("msg")
        except (urllib.error.URLError, TimeoutError, KeyError) as exc:
            status, msg = "no_response", f"gagal panggil API: {exc!r}"

        ok = status == probe["expect_status"]
        sehat, gagal = (sehat + 1, gagal) if ok else (sehat, gagal + 1)
        await catat_hasil(conn, probe, status, ok, msg)
        log.info("[%2d/%d] %s %-14s %-19s %s",
                 i, len(probes), probe["bot"], probe["cmd"], status,
                 "OK" if ok else "GAGAL")

        if i < len(probes):
            await asyncio.sleep(JEDA_ANTAR_PROBE)

    log.info("selesai: %d sehat, %d gagal", sehat, gagal)
    await tampilkan_bermasalah(conn)
    await conn.close()
    return 0


async def tampilkan_bermasalah(conn) -> None:
    async with conn.cursor() as cur:
        await cur.execute("SELECT * FROM command_bermasalah")
        rows = await cur.fetchall()
    if not rows:
        print("\nTidak ada command yang gagal beruntun.")
        return
    print(f"\nCommand bermasalah ({len(rows)}):")
    for r in rows:
        print(f"  {r['bot']} {r['cmd']:15} gagal {r['consecutive_failures']}x beruntun"
              f" | status: {r['last_status']}"
              f" | terakhir sehat: {r['sejak_terakhir_sehat'] or 'belum pernah'}")


async def laporan() -> int:
    conn = await db.connect()
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT bot, cmd, last_status, ok, consecutive_failures, last_checked_at
              FROM command_health ORDER BY ok NULLS FIRST, bot, cmd
            """
        )
        rows = await cur.fetchall()
    if not rows:
        print("Belum ada hasil pengecekan.")
    else:
        print(f"{'BOT':6} {'COMMAND':16} {'STATUS':20} {'OK':4} GAGAL-BERUNTUN")
        for r in rows:
            print(f"{r['bot']:6} {r['cmd']:16} {str(r['last_status']):20} "
                  f"{'v' if r['ok'] else 'x':4} {r['consecutive_failures']}")
    await tampilkan_bermasalah(conn)
    await conn.close()
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--report" in args:
        raise SystemExit(asyncio.run(laporan()))
    target = args[0] if args and not args[0].startswith("-") else None
    raise SystemExit(asyncio.run(jalankan(target)))
