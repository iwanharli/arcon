"""Bangun ulang lapis ternormalisasi dari cache mentah — TANPA menyentuh Telegram.

    python rebuild.py            # bangun ulang semua
    python rebuild.py /nik /kk   # command tertentu saja
    python rebuild.py --dry      # laporkan saja, jangan menulis

Kenapa perlu: bot_query_cache menyimpan `fields` hasil parse apa adanya, jadi
setiap kali normalizer/routing diperbaiki, lapis profiles/profile_records bisa
diisi ulang dari sana tanpa memotong kuota. Ini yang membuat perbaikan
pemetaan atribut bisa diiterasi berkali-kali dengan murah.
"""
from __future__ import annotations

import asyncio
import logging
import sys

import db
import parser
import routes

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("artemis.rebuild")


async def rebuild(cmds: list[str] | None = None, dry: bool = False) -> dict:
    conn = await db.connect()
    try:
        sql = ("SELECT id, bot, cmd, value, status, msg, fields, raw_text "
               "FROM bot_query_cache WHERE status = 'found'")
        params: tuple = ()
        if cmds:
            sql += " AND cmd = ANY(%s)"
            params = (cmds,)
        sql += " ORDER BY cmd, id"
        async with conn.cursor() as cur:
            await cur.execute(sql, params)
            rows = await cur.fetchall()

        # Record yatim (source_query_id NULL) tidak bisa dibangun ulang karena
        # baris cache asalnya sudah dihapus — ON DELETE SET NULL meninggalkannya.
        # Lapis 2 didefinisikan sebagai turunan lapis 1, jadi sisa ini dibuang
        # supaya tidak ada data basah dengan skema key versi lama.
        async with conn.cursor() as cur:
            await cur.execute("SELECT count(*) AS n FROM profile_records "
                              "WHERE source_query_id IS NULL")
            stat_yatim = (await cur.fetchone())["n"]
            if stat_yatim and not dry:
                await cur.execute("DELETE FROM profile_records WHERE source_query_id IS NULL")

        # Hapus record untuk SEMUA query yang tercakup, bukan hanya yang
        # status-nya found sekarang. Kalau tidak, query yang statusnya berubah
        # (mis. found -> queue_without_data setelah echo terdeteksi) akan
        # meninggalkan record basi yang tidak pernah dibersihkan.
        if not dry:
            hapus = "DELETE FROM profile_records WHERE source_query_id IN (SELECT id FROM bot_query_cache"
            async with conn.cursor() as cur:
                if cmds:
                    await cur.execute(hapus + " WHERE cmd = ANY(%s))", (cmds,))
                else:
                    await cur.execute(hapus + ")")

        stat = {"query": len(rows), "record": 0, "tanpa_route": 0, "kosong": 0,
                "diurai_ulang": 0, "yatim_dibuang": stat_yatim}
        for r in rows:
            route = routes.get_route(r["bot"], r["cmd"])
            if route is None:
                stat["tanpa_route"] += 1
                continue
            fields, msg = r["fields"], r["msg"]
            if r["raw_text"]:
                # Teks mentah tersedia -> urai ULANG dengan parser terkini.
                # Ini yang membuat perbaikan parser (mis. penomoran hasil
                # "1. Judul") bisa diterapkan tanpa menembak bot lagi.
                hasil = parser.classify([t for t in r["raw_text"].split("\n\n---\n\n") if t])
                if hasil["status"] == "found":
                    fields, msg = hasil["fields"], hasil["msg"]
                    stat["diurai_ulang"] += 1
            if not fields:
                stat["kosong"] += 1
                continue
            if dry:
                continue
            await db.store_result(conn, r["bot"], r["cmd"], r["value"], r["status"],
                                  msg=msg, fields=fields, raw_text=r["raw_text"])

        async with conn.cursor() as cur:
            await cur.execute("SELECT count(*) AS n FROM profile_records")
            stat["record"] = (await cur.fetchone())["n"]
        return stat
    finally:
        await conn.close()


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    hasil = asyncio.run(rebuild(args or None, dry="--dry" in sys.argv))
    print(f"query found : {hasil['query']}")
    print(f"tanpa route : {hasil['tanpa_route']}")
    print(f"fields kosong: {hasil['kosong']}")
    print(f"diurai ulang dari teks mentah: {hasil['diurai_ulang']}")
    print(f"record yatim dibuang: {hasil['yatim_dibuang']}")
    print(f"profile_records sekarang: {hasil['record']}")
