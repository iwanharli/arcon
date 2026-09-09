"""Katalog bentuk data JSON per command — dibangun dari hasil nyata.

    python skema.py            # tampilkan katalog
    python skema.py --tulis    # tulis docs/skema.json + docs/SKEMA.md

Setiap command menghasilkan JSON dengan bentuk yang konsisten. Katalog ini
merekamnya dari data yang benar-benar dikembalikan bot, bukan dari tebakan,
sehingga aplikasi pemakai (ArtemisID dsb.) tahu atribut apa yang tersedia.

Command yang belum pernah menghasilkan data ditandai `terverifikasi: false` —
bentuknya belum diketahui, bukan berarti tidak ada.
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import sys

import db
import routes

DOCS = pathlib.Path(__file__).parent / "docs"


async def bangun() -> dict:
    conn = await db.connect()
    try:
        async with conn.cursor() as cur:
            await cur.execute("""
                SELECT c.bot, c.cmd, c.status, r.kind, r.data
                  FROM bot_query_cache c
                  LEFT JOIN profile_records r ON r.source_query_id = c.id
                 ORDER BY c.cmd
            """)
            rows = await cur.fetchall()
    finally:
        await conn.close()

    per_cmd: dict[tuple[str, str], dict] = {}
    for (bot, cmd), route in sorted(routes.ROUTES.items()):
        per_cmd[(bot, cmd)] = {
            "bot": bot, "cmd": cmd,
            "menu": route.menu,
            "submenu": list(route.choice) if isinstance(route.choice, tuple)
                       else ([route.choice] if route.choice else []),
            "tabel": route.target,
            "kind": route.kind,
            "volatile": route.volatile,
            "normalizer": route.normalizer.__name__,
            "terverifikasi": False,
            "status_terakhir": None,
            "atribut": [],
        }

    for r in rows:
        kunci = (r["bot"], r["cmd"])
        if kunci not in per_cmd:
            continue
        entri = per_cmd[kunci]
        entri["status_terakhir"] = r["status"]
        if r["data"]:
            entri["terverifikasi"] = True
            for k in r["data"]:
                if k not in entri["atribut"]:
                    entri["atribut"].append(k)
    for e in per_cmd.values():
        e["atribut"].sort()
    return {f"{b}{c}": v for (b, c), v in per_cmd.items()}


def tulis(katalog: dict) -> None:
    DOCS.mkdir(exist_ok=True)
    (DOCS / "skema.json").write_text(
        json.dumps(katalog, ensure_ascii=False, indent=2), encoding="utf8")

    ver = [v for v in katalog.values() if v["terverifikasi"]]
    baris = ["# Skema data per command", "",
             f"Dibangun otomatis oleh `skema.py` dari hasil nyata. "
             f"**{len(ver)} dari {len(katalog)}** command sudah terverifikasi "
             f"bentuk datanya.", "",
             "Command yang belum terverifikasi bukan berarti tidak berfungsi — "
             "bentuk datanya saja yang belum pernah terlihat (umumnya karena "
             "kuota harian habis saat pengujian).", "",
             "## Terverifikasi", "",
             "| command | menu | tabel | atribut |", "|---|---|---|---|"]
    for v in sorted(ver, key=lambda x: x["cmd"]):
        baris.append(f"| `{v['cmd']}` | {v['menu'] or '-'} | "
                     f"{v['tabel']}{'[' + v['kind'] + ']' if v['kind'] else ''} | "
                     f"{', '.join('`' + a + '`' for a in v['atribut']) or '-'} |")
    belum = [v for v in katalog.values() if not v["terverifikasi"]]
    baris += ["", "## Belum terverifikasi", "",
              ", ".join(f"`{v['cmd']}`" for v in sorted(belum, key=lambda x: x["cmd"]))]
    (DOCS / "SKEMA.md").write_text("\n".join(baris) + "\n", encoding="utf8")


if __name__ == "__main__":
    kat = asyncio.run(bangun())
    ver = sum(1 for v in kat.values() if v["terverifikasi"])
    if "--tulis" in sys.argv:
        tulis(kat)
        print(f"docs/skema.json + docs/SKEMA.md ditulis ({ver}/{len(kat)} terverifikasi)")
    else:
        for k, v in sorted(kat.items()):
            if v["terverifikasi"]:
                print(f"{v['cmd']:20} {v['tabel']:9} {len(v['atribut']):2} atribut  "
                      f"{', '.join(v['atribut'][:6])}")
        print(f"\nterverifikasi: {ver}/{len(kat)}")
