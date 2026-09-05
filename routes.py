"""Routing command bot -> normalizer + tabel tujuan.

Normalizer di normalize.py sengaja dibuat shape-agnostic (cuma melihat nama
field), jadi kalau record orang dilempar ke normalize_vehicle dia tetap balik
{pemilik, alamat}. Routing di sini yang menentukan normalizer mana yang benar
untuk tiap command, supaya tidak ada data nyasar ke tabel yang salah.
"""
from __future__ import annotations

from typing import Callable, NamedTuple

import normalize as N


class Route(NamedTuple):
    normalizer: Callable[[dict], dict]
    target: str          # 'profiles' | 'phones' | 'vehicles' | 'records'
    kind: str | None     # dipakai kalau target = 'records'
    volatile: bool       # True = jangan pakai cache walau status 'found'


def _p(target="profiles", kind=None, volatile=False):
    return Route(N.normalize_person, target, kind, volatile)


# Command yang hasilnya berubah terus (lokasi/masa aktif) ditandai volatile
# supaya selalu hit ulang ke Telegram meski di cache statusnya 'found'.
ROUTES: dict[tuple[str, str], Route] = {
    # ---------------------------------------------------- bot1 (cielodespejadobot)
    ("bot1", "/nik"):        _p(),
    ("bot1", "/kk"):         _p(),
    ("bot1", "/nama"):       _p(),
    ("bot1", "/bionik"):     _p(),
    ("bot1", "/biokk"):      _p(),
    ("bot1", "/bionama"):    _p(),
    ("bot1", "/foto"):       Route(N.normalize_person, "records", "foto", False),
    ("bot1", "/reg"):        Route(N.normalize_phone, "phones", None, False),
    ("bot1", "/nohp"):       Route(N.normalize_phone, "phones", None, False),
    ("bot1", "/profnumber"): Route(N.normalize_number_info, "records", "number_info", True),
    ("bot1", "/tnkb"):       Route(N.normalize_vehicle, "vehicles", None, False),
    ("bot1", "/nosin"):      Route(N.normalize_vehicle, "vehicles", None, False),
    ("bot1", "/noka"):       Route(N.normalize_vehicle, "vehicles", None, False),
    ("bot1", "/niknopol"):   Route(N.normalize_vehicle, "vehicles", None, False),
    ("bot1", "/namanopol"):  Route(N.normalize_vehicle, "vehicles", None, False),
    ("bot1", "/bpjs"):       Route(N.normalize_person, "records", "bpjs", False),
    ("bot1", "/wsid"):       Route(N.normalize_person, "records", "wsid", False),
    ("bot1", "/dpo"):        Route(N.normalize_person, "records", "dpo", False),
    ("bot1", "/pln"):        Route(N.normalize_pln, "records", "pln", True),
    ("bot1", "/guru"):       Route(N.normalize_person, "records", "guru", False),
    ("bot1", "/dosen"):      Route(N.normalize_person, "records", "dosen", False),
    ("bot1", "/mahasiswa"):  Route(N.normalize_person, "records", "mahasiswa", False),

    # ---------------------------------------------------------- bot2 (mahalini2bot)
    ("bot2", "/cp"):         Route(N.normalize_number_info, "records", "number_info", True),

    # ------------------------------------------------------------ bot3 (cleojktbot)
    ("bot3", "/cptsel"):     Route(N.normalize_device, "records", "device", True),
    ("bot3", "/track"):      Route(N.normalize_device, "records", "device", True),
    ("bot3", "/lm"):         Route(N.normalize_device, "records", "device", True),
    ("bot3", "/prof"):       Route(N.normalize_number_info, "records", "number_info", True),
    ("bot3", "/cekinfo"):    Route(N.normalize_number_info, "records", "number_info", True),
    ("bot3", "/reg"):        Route(N.normalize_phone, "phones", None, False),
    ("bot3", "/nohp"):       Route(N.normalize_phone, "phones", None, False),
    ("bot3", "/kk"):         _p(),
    ("bot3", "/nik"):        _p(),
    ("bot3", "/nama"):       _p(),
    ("bot3", "/photo"):      Route(N.normalize_person, "records", "foto", False),
    ("bot3", "/bpjs"):       Route(N.normalize_person, "records", "bpjs", False),
    ("bot3", "/bpjs2"):      Route(N.normalize_person, "records", "bpjs", False),
    ("bot3", "/guru"):       Route(N.normalize_person, "records", "guru", False),
    ("bot3", "/guru1"):      Route(N.normalize_person, "records", "guru", False),
    ("bot3", "/siswa"):      _p(),
    ("bot3", "/cekkpu"):     Route(N.normalize_person, "records", "kpu", False),
    ("bot3", "/cekanggota"): Route(N.normalize_person, "records", "polri", False),
    ("bot3", "/leak"):       Route(N.normalize_person, "records", "leak", False),
    ("bot3", "/emailstalker"): Route(N.normalize_person, "records", "email", False),
    ("bot3", "/pt"):         Route(N.normalize_person, "records", "perusahaan", False),
    ("bot3", "/nib"):        Route(N.normalize_person, "records", "perusahaan", False),
    ("bot3", "/npwp"):       Route(N.normalize_person, "records", "perusahaan", False),
    ("bot3", "/nopol"):      Route(N.normalize_vehicle, "vehicles", None, False),
}


def get_route(bot: str, cmd: str) -> Route | None:
    return ROUTES.get((bot, cmd))


def is_volatile(bot: str, cmd: str) -> bool:
    """Command lokasi/masa-aktif tidak boleh dijawab dari cache lama."""
    route = ROUTES.get((bot, cmd))
    return bool(route and route.volatile)
