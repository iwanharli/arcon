"""Pengecekan kesehatan seluruh command, dijalankan sehari sekali.

    python healthcheck.py            # cek semua command yang punya probe
    python healthcheck.py bot3       # cek satu bot saja
    python healthcheck.py --report   # cuma tampilkan hasil terakhir, tanpa hit bot

Dijadwalkan lewat cron, mis. tiap hari jam 03:00:

    0 3 * * * cd /path/artemis-tele-connector && .venv/bin/python healthcheck.py >> logs/health.log 2>&1

Catatan penting soal cara kerjanya:

* Pengecekan WAJIB melewati cache (force=True). Kalau tidak, ia cuma membaca
  ulang isi database dan tidak membuktikan apa-apa soal kondisi bot.
* Karena itu tiap probe benar-benar menghabiskan kuota. Satu putaran = 46 hit.
* Probe dijalankan lewat antrian yang sama dengan permintaan Artemis, tapi
  dengan priority negatif supaya pencarian dari pengguna selalu didahulukan.
"""
from __future__ import annotations

import asyncio
import logging
import sys
import time

import db
import service
from connector import TelegramConnector

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("artemis.health")

JEDA_ANTAR_PROBE = 12          # detik, hindari rate limit
PRIORITAS_PROBE = -10          # selalu mengalah dari permintaan Artemis

# Timeout khusus health check, jauh lebih longgar dari BOT_TIMEOUT (30s).
# Sebagian bot memang lambat menjawab; kalau timeout-nya pendek, command yang
# sebenarnya sehat akan dilaporkan mati dan laporannya jadi tidak dipercaya.
TIMEOUT_PROBE = 120


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
                      durasi_ms: int, msg: str | None) -> None:
    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO command_health_checks
                (bot, cmd, status, ok, duration_ms, msg, probe_value)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (probe["bot"], probe["cmd"], status, ok, durasi_ms,
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
    probes = await ambil_probe(conn, bot)
    if not probes:
        log.warning("tidak ada probe. Isi tabel command_probes dulu.")
        await conn.close()
        return 1

    log.info("mulai cek %d command", len(probes))
    sehat = gagal = 0

    async with TelegramConnector() as tg:
        for i, probe in enumerate(probes, 1):
            mulai = time.monotonic()
            try:
                # force=True: harus benar-benar hit bot, bukan baca cache.
                hasil = await service.query(
                    tg, conn, probe["bot"], probe["cmd"], probe["probe_value"],
                    force=True, timeout=TIMEOUT_PROBE,
                )
                status, msg = hasil["status"], hasil.get("msg")
            except Exception as exc:                      # noqa: BLE001
                status, msg = "no_response", repr(exc)

            durasi = int((time.monotonic() - mulai) * 1000)
            ok = status == probe["expect_status"]
            sehat, gagal = (sehat + 1, gagal) if ok else (sehat, gagal + 1)

            await catat_hasil(conn, probe, status, ok, durasi, msg)
            log.info("[%2d/%d] %s %-14s %-19s %s (%.1fs)",
                     i, len(probes), probe["bot"], probe["cmd"], status,
                     "OK" if ok else "GAGAL", durasi / 1000)

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
        sejak = r["sejak_terakhir_sehat"]
        print(f"  {r['bot']} {r['cmd']:15} gagal {r['consecutive_failures']}x beruntun"
              f" | status: {r['last_status']}"
              f" | terakhir sehat: {sejak or 'belum pernah'}")


async def laporan() -> int:
    """Tampilkan hasil pengecekan terakhir tanpa menyentuh Telegram."""
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
