"""Bagian bersama test bot: jalankan satu command, cetak hasilnya, periksa
apakah normalizer & tabel tujuannya masuk akal.

Test ini MEMOTONG KUOTA — tiap command yang nilainya terisi menembak bot asli.
"""
import asyncio
import os
import time

import pytest

import routes
import service

# Jeda antar tembakan ke bot, meniru jobs.JEDA_ANTAR_JOB di produksi.
#
# Tanpa ini test menembak beruntun tanpa jeda, dan bot membalas TANPA reply_to:
# balasan yang telat bisa jatuh ke jendela tunggu query berikutnya.
# service.relates_to_request() hanya bisa menolaknya kalau input punya >=8
# digit; untuk pencarian nama/keyword ia mengembalikan None (tak bisa
# dipastikan) dan balasan nyasar tetap diterima.
#
# Kasus terparah: satu nilai yang SAMA dipakai beruntun oleh beberapa command
# (6 e-wallet DOMPET DIGITAL sama-sama memakai satu nomor HP). Di situ tidak
# ada cara membedakan balasan DANA dari GOPAY selain menunggu.
JEDA = float(os.getenv("JEDA_TEST", "10"))

_terakhir = 0.0


async def _tunggu_giliran():
    global _terakhir
    sisa = JEDA - (time.monotonic() - _terakhir)
    if sisa > 0:
        await asyncio.sleep(sisa)


async def jalankan(tg, conn, bot: str, cmd: str, value, force: bool):
    if not value:
        pytest.skip(f"{bot} {cmd}: nilainya belum diisi di tests/values.py")

    route = routes.get_route(bot, cmd)
    assert route is not None, f"{bot} {cmd} tidak ada di ROUTES"

    await _tunggu_giliran()
    hasil = await service.query(tg, conn, bot, cmd, value, force=force)
    global _terakhir
    if not hasil.get("from_cache"):
        _terakhir = time.monotonic()

    print(f"\n{'='*66}")
    print(f"{bot} {cmd}  value={value!r}"
          + (f"  menu={route.menu!r}" if route.menu else "  (dialek command)"))
    print(f"status={hasil['status']}  from_cache={hasil['from_cache']}"
          f"  media={len(hasil.get('media') or [])}")
    if hasil.get("msg"):
        print("msg:", str(hasil["msg"])[:300])

    fields = hasil.get("fields")
    records = fields if isinstance(fields, list) else [fields] if fields else []
    for i, rec in enumerate(records[:3], 1):
        print(f"--- record {i} ({len(rec)} field)")
        for k, val in list(rec.items())[:18]:
            print(f"    {k:20} = {str(val)[:70]}")
        ternormalisasi = route.normalizer(rec)
        print(f"    -> {route.normalizer.__name__} -> {route.target}"
              + (f"[{route.kind}]" if route.kind else ""))
        print(f"    -> {ternormalisasi}")
        if not ternormalisasi:
            print("    !! normalizer mengembalikan KOSONG — routing kemungkinan salah")

    # 'no_response' = bot tidak menjawab sama sekali; itu kegagalan alur, bukan
    # sekadar data tidak ada. not_found tetap dianggap lulus (data memang bisa
    # tidak ada), tapi dicetak supaya kelihatan.
    assert hasil["status"] != "no_response", \
        f"{bot} {cmd}: bot tidak menjawab — cek alur menu / timeout"
    return hasil
