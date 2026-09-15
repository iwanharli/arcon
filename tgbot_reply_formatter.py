"""Formatter balasan Telegram untuk command ``/nikbyphone``, ``/nik``, ``/kk``, dan ``/track``."""
from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Any, Callable


SEPARATOR = "━━━━━━━━━━━━━━━━━━"
_EMPTY = (None, "", "-")
_SECRET_KEYS = {"salt", "kata_sandi_terenkripsi"}

_LABELS = {
    "nik": "NIK",
    "nomor": "Nomor",
    "no_hp": "No. HP",
    "nomor_kk": "No. KK",
    "provider": "Provider",
    "whatsapp": "WhatsApp",
    "cek_update_manual": "Link",
    "tanggal_aktivasi": "Aktivasi",
    "terakhir_terdaftar": "Terakhir Terdaftar",
    "nama_lengkap": "Nama",
    "jenis_kelamin": "Jenis Kelamin",
    "status_kawin": "Status Kawin",
    "tempat_lahir": "Tempat Lahir",
    "tanggal_lahir": "Tanggal Lahir",
    "status_hubungan": "Status Hubungan",
    "alamat": "Alamat",
    "adres": "Alamat",
    "dusun": "Dusun",
    "rt/rw": "RT/RW",
    "kelurahan": "Kelurahan",
    "kecamatan": "Kecamatan",
    "kabupaten": "Kabupaten",
    "kab_kota": "Kabupaten",
    "provinsi": "Provinsi",
    "kode_pos": "Kode Pos",
    "google_maps": "Maps",
    "pekerjaan": "Pekerjaan",
    "pendidikan": "Pendidikan",
    "gol._darah": "Gol. Darah",
    "penyandang_cacat": "Disabilitas",
    "no._akta_lahir": "Akta Lahir",
    "no._akta_kawin": "Akta Kawin",
    "tgl_kawin": "Tgl. Kawin",
    "no._akta_cerai": "Akta Cerai",
    "tgl_cerai": "Tgl. Cerai",
    "ayah": "Ayah",
    "ibu": "Ibu",
    "merk": "Merk",
    "tipe": "Tipe",
    "tahun": "Tahun",
    "warna": "Warna",
    "no_rangka": "No. Rangka",
    "no_mesin": "No. Mesin",
    "no_bpkb": "No. BPKB",
    "pemilik": "Pemilik",
}

_EMOJIS = {
    "nik": "🪪",
    "nomor": "📞",
    "provider": "📡",
    "whatsapp": "💬",
    "cek_update_manual": "🔗",
    "tanggal_aktivasi": "📅",
    "terakhir_terdaftar": "🕐",
    "nama_lengkap": "👤",
    "jenis_kelamin": "🚻",
    "tempat_lahir": "📍",
    "tanggal_lahir": "🎂",
    "status_kawin": "💍",
    "status_hubungan": "👥",
    "alamat": "🏠",
    "google_maps": "🗺️",
    "pekerjaan": "💼",
    "pendidikan": "🎓",
    "gol._darah": "🩸",
    "penyandang_cacat": "♿",
    "ibu": "👩",
    "ayah": "👨",
    "merk": "🏭",
    "tipe": "🚙",
    "tahun": "📅",
    "warna": "🎨",
    "no_rangka": "🔩",
    "no_mesin": "⚙️",
    "no_bpkb": "📕",
    "pemilik": "👤",
}

_CODE_KEYS = {"nik", "nomor", "no_hp", "nomor_kk", "no._akta_lahir", "no._akta_kawin",
              "no._akta_cerai", "no_rangka", "no_mesin", "no_bpkb", "nomor_paspor"}


def _present(value: Any) -> bool:
    return value not in _EMPTY


def _text(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value).strip()


def _label(key: str) -> str:
    if key in _LABELS:
        return _LABELS[key]
    return re.sub(r"\s+", " ", key.replace("_", " ").replace(".", ". ")).strip().title()


def _line(key: str, value: Any, *, label: str | None = None, emoji: str | None = None) -> str:
    prefix = f"{emoji or _EMOJIS.get(key, '')} " if (emoji or _EMOJIS.get(key)) else ""
    shown = f"`{_text(value)}`" if key in _CODE_KEYS else _text(value)
    return f"{prefix}{label or _label(key)}: {shown}"


def _record_lines(record: Mapping[str, Any], order: list[str] | None = None,
                  *, skip: set[str] | None = None) -> list[str]:
    skip = skip or set()
    keys = order if order is not None else list(record)
    return [
        _line(key, record[key])
        for key in keys
        if key in record and key not in skip and key not in _SECRET_KEYS and _present(record[key])
    ]


def _block(title: str, lines: list[str], *, emoji: str = "") -> str:
    if not lines:
        return ""
    heading = f"{emoji} *{title}*" if emoji else f"*{title}*"
    return f"{heading}\n\n" + "\n".join(lines)


def _section(title: str, body: str) -> str:
    if not body:
        return ""
    return f"{title}\n{SEPARATOR}\n\n{body}\n\n{SEPARATOR}"


def _records(fields: Any) -> list[dict[str, Any]]:
    values = fields if isinstance(fields, list) else [fields]
    return [dict(value) for value in values if isinstance(value, Mapping)]


def _take(records: list[dict[str, Any]], used: set[int],
          predicate: Callable[[dict[str, Any]], bool]) -> dict[str, Any] | None:
    for index, record in enumerate(records):
        if index not in used and predicate(record):
            used.add(index)
            return record
    return None


def _first(records: tuple[Mapping[str, Any], ...], key: str) -> Any:
    for record in records:
        if _present(record.get(key)):
            return record[key]
    return None


def _parent(value: Any) -> tuple[str, str | None]:
    text = _text(value) if _present(value) else ""
    match = re.match(r"(.+?)\s*\((\d{16})\)$", text)
    return (match.group(1).strip(), match.group(2)) if match else (text, None)


def _wilayah(value: Any) -> str:
    pairs = re.findall(r"(PROV|KAB|KEC|KEL)\s*:\s*([^\s]+)", _text(value), re.I)
    values = {key.upper(): item for key, item in pairs}
    labels = {"PROV": "Provinsi", "KAB": "Kabupaten", "KEC": "Kecamatan", "KEL": "Kelurahan"}
    return "\n".join(f"{labels[key]}: {values[key]}" for key in ("PROV", "KAB", "KEC", "KEL")
                     if key in values)


def _url(value: Any) -> str:
    text = _text(value)
    if text.startswith("(") and text.endswith(")"):
        return text[1:-1]
    return text


def _plain_line(label: str, value: Any, *, code: bool = False, bold: bool = False) -> str:
    shown = _text(value)
    if code:
        shown = f"`{shown}`"
    if bold:
        shown = f"*{shown}*"
    return f"{label}: {shown}"


def _record_group(record: Mapping[str, Any]) -> str:
    """Nama kelompok record; respons API lama memakai ``nama``, yang baru ``bagian``."""
    return _text(record.get("bagian") or record.get("nama") or "").upper()


def _render_a_phone(records: list[dict[str, Any]], used: set[int]) -> str:
    registration = _take(records, used, lambda r: _record_group(r) == "REGISTRASI REAL-TIME") or {}
    detail = {}
    if registration:
        detail = _take(
            records, used,
            lambda r: not _record_group(r) and {"nomor", "whatsapp"}.issubset(r)
            and (not registration.get("nomor") or r.get("nomor") == registration.get("nomor")),
        ) or {}
    else:
        # Tetap tampilkan bagian telepon walau record registrasi real-time tidak
        # tersedia. Record fallback tidak ditandai used agar masih muncul di MSISDN.
        registration = next(
            (r for r in records if "nomor" in r and any(key in r for key in ("nik", "provider", "whatsapp"))),
            {},
        )
        detail = registration

    lines = []
    for label, key, code in (
        ("Nomor", "nomor", True),
        ("Provider", "provider", True),
        ("NIK", "nik", True),
        ("Aktivasi", "tanggal_aktivasi", False),
        ("Terakhir Terdaftar", "terakhir_terdaftar", False),
    ):
        value = _first((registration, detail), key)
        if _present(value):
            lines.append(_plain_line(label, value, code=code))

    if registration or detail:
        if _present(detail.get("whatsapp")):
            lines.extend(["", "💬 *WhatsApp*", "", _plain_line("Status", detail["whatsapp"])])
        checked = _first((detail, registration), "tanggal_pengecekan")
        checked_time = _first((detail, registration), "waktu_pengecekan")
        if _present(checked) or _present(checked_time):
            value = " ".join(str(v) for v in (checked, checked_time) if _present(v)) + " WIB"
            lines.append(_plain_line("Dicek", value))
        link = detail.get("cek_update_manual") or detail.get("cek_manual")
        if _present(link):
            lines.append(_plain_line("Link", _url(link)))
    if not lines:
        lines.append("Data telepon belum tersedia.")
    body = _block("REGISTRASI REAL-TIME", lines, emoji="🔥")
    return _section("📱 *INFORMASI TELEPON*", body)


def _render_b_identity(records: list[dict[str, Any]], used: set[int]) -> str:
    selected = (
        _take(
            records,
            used,
            lambda r: {"nik", "nama_lengkap"}.issubset(r)
            and any(key in r for key in ("alamat", "nomor_kk", "rt/rw", "nomor_wilayah")),
        )
        or _take(records, used, lambda r: {"nik", "nama_lengkap"}.issubset(r))
        or _take(
            records,
            used,
            lambda r: any(key in r for key in ("nama_lengkap", "alamat", "nomor_kk", "tanggal_lahir"))
            and _record_group(r) not in {"REGISTRASI REAL-TIME", "DATA AYAH", "DATA IBU", "LAINNYA", "AKTA"},
        )
    )
    profile = dict(selected or {})

    # Lengkapi identitas dari record lain jika respons API memecah field ke
    # beberapa record atau hanya mengembalikan sebagian data.
    aliases = {"nomor_kk": ("nomor_kk", "no._kk"), "nama_lengkap": ("nama_lengkap",)}
    identity_keys = (
        "nik", "nama_lengkap", "nomor_kk", "jenis_kelamin", "tempat_lahir", "tanggal_lahir",
        "status_kawin", "status_hubungan", "alamat", "rt/rw", "kelurahan", "kecamatan",
        "kabupaten", "provinsi", "kode_pos", "google_maps", "nomor_wilayah",
    )
    for key in identity_keys:
        if _present(profile.get(key)):
            continue
        source_keys = aliases.get(key, (key,))
        value = next(
            (record.get(source_key) for record in records for source_key in source_keys
             if _present(record.get(source_key))),
            None,
        )
        if _present(value):
            profile[key] = value
    if not _present(profile.get("nama_lengkap")):
        name_row = next((record for record in records if _record_group(record) == "NAMA LENGKAP"), {})
        name = name_row.get("wni") or name_row.get("wni_c")
        if _present(name):
            profile["nama_lengkap"] = name

    family_head = next((r for r in records if {"status_hubungan", "ayah", "ibu"}.issubset(r)), {})
    lines = []
    for label, key, code, bold in (
        ("Nama", "nama_lengkap", False, True),
        ("NIK", "nik", True, False),
        ("No. KK", "nomor_kk", True, False),
        ("Jenis Kelamin", "jenis_kelamin", False, False),
        ("Tempat Lahir", "tempat_lahir", False, False),
        ("Tanggal Lahir", "tanggal_lahir", False, False),
        ("Status Kawin", "status_kawin", False, False),
        ("Status Hubungan", "status_hubungan", False, False),
    ):
        if _present(profile.get(key)):
            lines.append(_plain_line(label, profile[key], code=code, bold=bold))

    if _present(profile.get("alamat")):
        lines.extend(["", "🏠 *Alamat*", _text(profile["alamat"])])
    for label, key in (
        ("RT/RW", "rt/rw"), ("Kelurahan", "kelurahan"), ("Kecamatan", "kecamatan"),
        ("Kabupaten", "kabupaten"), ("Provinsi", "provinsi"), ("Kode Pos", "kode_pos"),
    ):
        if _present(profile.get(key)):
            lines.append(_plain_line(label, profile[key]))
    if _present(profile.get("google_maps")):
        lines.extend(["", "🗺️ *Google Maps*", _url(profile["google_maps"])])
    wilayah = _wilayah(profile.get("nomor_wilayah"))
    if wilayah:
        lines.extend(["", "📍 *Kode Wilayah*", wilayah])

    blocks = ["\n".join(lines or ["Data identitas belum tersedia."])]

    father = _take(records, used, lambda r: _record_group(r) == "DATA AYAH")
    mother = _take(records, used, lambda r: _record_group(r) == "DATA IBU")
    parent_records = [father, mother]
    for index, parent_record in enumerate(parent_records):
        if parent_record:
            continue
        found = _take(
            records, used,
            lambda r: set(r) <= {"nama", "nik"} and r.get("nama") not in {"AKTA", "LAINNYA"}
            and not re.fullmatch(r"\d+\.", _text(r.get("nama", ""))),
        )
        parent_records[index] = found
    fallback = (_parent(family_head.get("ayah")), _parent(family_head.get("ibu")))
    for index, title in enumerate(("Ayah", "Ibu")):
        if parent_records[index]:
            name = _text(parent_records[index].get("nama", ""))
            nik = parent_records[index].get("nik")
        else:
            name, nik = fallback[index]
        lines = [_plain_line("Nama", name)] if name else []
        if _present(nik) and _text(nik) != "N/A":
            lines.append(_plain_line("NIK", nik, code=True))
        if lines:
            blocks.append(_block(title, lines, emoji="👨" if title == "Ayah" else "👩"))

    lainnya = _take(records, used, lambda r: _record_group(r) == "LAINNYA")
    if lainnya:
        other_lines = []
        for label, key in (("Pendidikan", "pendidikan"), ("Pekerjaan", "pekerjaan"),
                           ("Gol. Darah", "gol._darah"), ("Disabilitas", "penyandang_cacat")):
            if _present(lainnya.get(key)):
                other_lines.append(_plain_line(label, lainnya[key]))
        blocks.append(_block("Informasi Lain", other_lines, emoji="📋"))

    akta = _take(records, used, lambda r: _record_group(r) == "AKTA")
    if akta:
        act_lines = []
        for label, key in (("Akta Lahir", "no._akta_lahir"), ("Akta Kawin", "no._akta_kawin"),
                           ("Tgl. Kawin", "tgl_kawin"), ("Akta Cerai", "no._akta_cerai"),
                           ("Tgl. Cerai", "tgl_cerai")):
            if _present(akta.get(key)):
                act_lines.append(_plain_line(label, akta[key]))
        blocks.append(_block("Akta", act_lines, emoji="📜"))
    return _section("🪪 *INFORMASI IDENTITAS*", "\n\n".join(blocks))


def _member_names(records: list[dict[str, Any]]) -> dict[str, str]:
    names = {}
    for record in records:
        name, nik = _parent(record.get("anggota"))
        if name and nik:
            names[nik] = name
        for key in ("ayah", "ibu"):
            name, nik = _parent(record.get(key))
            if name and nik:
                names[nik] = name
        direct_nik = record.get("nik")
        direct_name = record.get("nama") or record.get("nama_lengkap")
        if _present(direct_nik) and _present(direct_name) and _text(direct_nik) != "N/A":
            names[_text(direct_nik)] = _text(direct_name)
    return names


def _render_c_family(records: list[dict[str, Any]], used: set[int]) -> str:
    family = []
    for index, record in enumerate(records):
        if index not in used and {"nik", "status_hubungan"}.issubset(record):
            used.add(index)
            family.append(record)
    if not family:
        return ""
    kk = _take(records, used, lambda r: set(r) == {"nomor_kk"})
    names = _member_names(records)
    body = []
    if kk:
        body.append(_plain_line("No. KK", kk["nomor_kk"], code=True))
    for number, record in enumerate(family, 1):
        name = record.get("nama") or names.get(_text(record.get("nik")), f"NIK {_text(record.get('nik', ''))}")
        lines = []
        for label, key, code in (("NIK", "nik", True), ("JK", "jenis_kelamin", False)):
            if _present(record.get(key)):
                lines.append(_plain_line(label, record[key], code=code))
        birth = [_text(record[key]) for key in ("tempat_lahir", "tanggal_lahir")
                 if _present(record.get(key))]
        if birth:
            lines.append(f"Lahir: {', '.join(birth)}")
        for label, key in (("Hubungan", "status_hubungan"), ("Ayah", "ayah"), ("Ibu", "ibu"),
                           ("Pekerjaan", "pekerjaan"), ("Pendidikan", "pendidikan"), ("No. HP", "no_hp")):
            value = record.get(key)
            if key in {"ayah", "ibu"} and _present(value):
                value, _ = _parent(value)
            if _present(value):
                lines.append(_plain_line(label, value))
        body.append(_block(f"{number}. {_text(name)}", lines, emoji="👤"))
    for index, record in enumerate(records):
        if index not in used and ("anggota" in record or record.get("nama") == "JENIS KELAMIN"):
            used.add(index)
    return _section("👨‍👩‍👧‍👦 *ANGGOTA KELUARGA*", "\n\n".join(body))


def _render_d_msisdn(records: list[dict[str, Any]], used: set[int]) -> str:
    numbered, unnamed, indexes = [], [], []
    for index, record in enumerate(records):
        if index in used or not {"nik", "nomor", "provider"}.issubset(record):
            continue
        indexes.append(index)
        (numbered if re.fullmatch(r"\d+\.", _text(record.get("nama", ""))) else unnamed).append(record)
    phone_records = unnamed or numbered
    if not phone_records:
        return ""
    used.update(indexes)
    _take(records, used, lambda r: "b._jumlah_data" in r)
    nik = next((_text(record["nik"]) for record in phone_records if _present(record.get("nik"))), "")
    body = [_plain_line("🪪 NIK", nik, code=True)] if nik else []
    for number, record in enumerate(phone_records, 1):
        lines = []
        for label, key, code in (("Nomor", "nomor", True), ("Provider", "provider", False),
                                 ("Terakhir Terdaftar", "terakhir_terdaftar", False),
                                 ("WhatsApp", "whatsapp", False)):
            if _present(record.get(key)):
                lines.append(_plain_line(label, record[key], code=code))
        checked = _first((record,), "tanggal_pengecekan")
        checked_time = _first((record,), "waktu_pengecekan")
        if _present(checked) or _present(checked_time):
            value = " ".join(str(v) for v in (checked, checked_time) if _present(v)) + " WIB"
            lines.append(_plain_line("Dicek", value))
        link = record.get("cek_update_manual") or record.get("cek_manual")
        if _present(link):
            lines.append(_plain_line("Link", _url(link)))
        body.append(_block(f"Nomor {number}", lines, emoji="📱"))
    return _section("📶 *DATA MSISDN*", "\n\n".join(body))


def _render_e_assets(records: list[dict[str, Any]], used: set[int]) -> str:
    assets = []
    for index, record in enumerate(records):
        if index not in used and {"merk", "tipe"}.issubset(record):
            used.add(index)
            assets.append(record)
    if not assets:
        return ""
    body = []
    order = ["pemilik", "merk", "tipe", "tahun", "warna", "no_rangka", "no_mesin", "no_bpkb", "no_hp"]
    for record in assets:
        title = _text(record.get("nama", "DATA ASET"))
        lines = []
        for label, key, code, bold in (("Pemilik", "pemilik", False, True), ("Merk", "merk", False, False),
                                       ("Tipe", "tipe", False, False), ("Tahun", "tahun", False, False),
                                       ("Warna", "warna", False, False), ("No. Rangka", "no_rangka", True, False),
                                       ("No. Mesin", "no_mesin", True, False), ("No. BPKB", "no_bpkb", True, False),
                                       ("No. HP", "no_hp", False, False)):
            if _present(record.get(key)):
                lines.append(_plain_line(label, record[key], code=code, bold=bold))
        if _present(record.get("alamat")):
            lines.extend(["", "🏠 Alamat:", _text(record["alamat"])])
        body.append(_block(title, lines, emoji="🚘"))
    return _section("🚗 *DATA ASET*", "\n\n".join(body))


def _render_f_bansos(records: list[dict[str, Any]], used: set[int]) -> str:
    keys = {"desil", "status_sembako", "periode_sembako", "status_pkh", "periode_pkh",
            "status_pbi_jk", "periode_pbi_jk", "status_bansos", "keterangan_bansos",
            "sembako", "pkh", "pbi-jk"}
    record = _take(records, used, lambda r: bool(keys.intersection(r)))
    if not record:
        return ""
    lines = []
    name = record.get("nama_lengkap") or record.get("nama")
    if _present(name):
        lines.append(_plain_line("Nama", name, bold=True))

    def add_status(label: str, *keys: str) -> None:
        value = next((record.get(key) for key in keys if _present(record.get(key))), None)
        if not _present(value):
            return
        match = re.match(r"(.+?)\s*\(\s*PERIODE\s*:\s*(.*?)\s*\)$", _text(value), re.I)
        if match:
            lines.append(_plain_line(label, match.group(1).strip()))
            lines.append(_plain_line("Periode", match.group(2).strip()))
        else:
            lines.append(_plain_line(label, value))

    if _present(record.get("desil")):
        lines.append(_plain_line("Desil", record["desil"]))
    add_status("Sembako", "status_sembako", "sembako")
    add_status("PKH", "status_pkh", "pkh")
    add_status("PBI-JK", "status_pbi_jk", "pbi-jk")
    if _present(record.get("status_bansos")):
        lines.append(_plain_line("Status", record["status_bansos"]))
    elif _present(record.get("status")):
        lines.append(_plain_line("Status", record["status"]))
    if _present(record.get("keterangan_bansos")):
        lines.append(_plain_line("Keterangan", record["keterangan_bansos"]))
    elif _present(record.get("keterangan")):
        lines.append(_plain_line("Keterangan", record["keterangan"]))
    return _section("💰 *DATA BANSOS*", "\n".join(lines))


def _comparison_value(records: list[dict[str, Any]], name: str) -> Any:
    row = next((record for record in records if record.get("nama") == name), {})
    for key in ("wni", "wni_c", "dukcapil_1", "dukcapil_2", "dukcapil_3", "dukcapil_4"):
        if _present(row.get(key)):
            return row[key]
    return None


def _render_g_wni(records: list[dict[str, Any]], used: set[int]) -> str:
    candidates = []
    for index, record in enumerate(records):
        if index not in used and any(key.startswith(("wni", "dukcapil")) for key in record):
            used.add(index)
            candidates.append(record)
    admin = _take(
        records,
        used,
        lambda r: {"nik", "nama_lengkap"}.issubset(r)
        and any(key in r for key in ("no._kk", "agama", "nama_ayah", "nama_ibu")),
    ) or {}
    if not candidates and not admin:
        return ""
    profile = next((record for record in records if "nama_lengkap" in record and "nik" in record), {})
    family_head = next((record for record in records if {"status_hubungan", "ayah", "ibu"}.issubset(record)), {})
    lainnya = next((record for record in records if record.get("nama") == "LAINNYA"), {})
    def value(key: str, fallback: Any = None) -> Any:
        return admin.get(key) or profile.get(key) or fallback

    lines = []
    for label, value, code, bold in (
        ("Nama", value("nama_lengkap"), False, True), ("NIK", value("nik"), True, False),
        ("No. KTP", value("no_ktp"), True, False),
        ("No. KK", value("no._kk", profile.get("nomor_kk")), True, False),
        ("Jenis Kelamin", value("jenis_kelamin"), False, False),
        ("Tempat Lahir", value("tempat_lahir"), False, False),
        ("Tanggal Lahir", value("tanggal_lahir", _comparison_value(records, "TANGGAL LAHIR")), False, False),
        ("Gol. Darah", value("golongan_darah", lainnya.get("gol._darah")), False, False),
        ("Agama", value("agama"), False, False),
        ("Status Kawin", value("status_kawin", _comparison_value(records, "STATUS KAWIN")), False, False),
    ):
        if _present(value):
            lines.append(_plain_line(label, value, code=code, bold=bold))
    pendidikan = admin.get("pendidikan_akhir") or profile.get("pendidikan") or lainnya.get("pendidikan")
    pekerjaan = admin.get("jenis_pekerjaan") or _comparison_value(records, "PEKERJAAN") or lainnya.get("pekerjaan")
    if _present(pendidikan):
        lines.extend(["", _plain_line("Pendidikan", pendidikan)])
    if _present(pekerjaan):
        lines.append(_plain_line("Pekerjaan", pekerjaan))
    for label, key, admin_key in (("Ayah", "ayah", "nama_ayah"), ("Ibu", "ibu", "nama_ibu")):
        value, _ = _parent(admin.get(admin_key) or family_head.get(key))
        if value:
            lines.append(_plain_line(label, value))

    wilayah = []
    for label, key in (("Provinsi", "provinsi"), ("Kabupaten", "kabupaten"),
                       ("Kecamatan", "kecamatan"), ("Kelurahan", "kelurahan")):
        if _present(profile.get(key)):
            wilayah.append(_plain_line(label, profile[key]))
    if wilayah:
        lines.extend(["", "📍 *Wilayah*", *wilayah])

    akta = next((record for record in records if record.get("nama") == "AKTA"), {})
    administrasi = []
    for label, keys in (("Akta Lahir", ("akta_lahir", "no._akta_lahir")),
                        ("Akta Kawin", ("akta_kawin", "no._akta_kawin")),
                        ("Akta Cerai", ("akta_cerai", "no._akta_cerai")),
                        ("Status Keluarga", ("status_hubungan_keluarga", "status_hubungan")),
                        ("Kelas Fiskal", ("kelas_fiskal",)), ("Disabilitas", ("penyandang_cacat",)),
                        ("Tgl. Ubah", ("tgl_ubah",)), ("Isu Pendatang", ("isu_pendatang",))):
        item = next((admin.get(key) or profile.get(key) or akta.get(key)
                     for key in keys if _present(admin.get(key) or profile.get(key) or akta.get(key))), None)
        if _present(item):
            administrasi.append(_plain_line(label, item))
    if administrasi:
        lines.extend(["", "📜 *Administrasi*", *administrasi])
    return _section("🇮🇩 *DATA WNI*", "\n".join(lines))


def _render_h_tax(records: list[dict[str, Any]], used: set[int]) -> str:
    keys = {"npwp", "kode_klu", "jenis_wajib_pajak", "kantor_pajak", "profil_risiko", "status_wajib_pajak"}
    candidates = []
    for index, record in enumerate(records):
        if index not in used and keys.intersection(record):
            used.add(index)
            candidates.append(record)
    if not candidates:
        return ""
    blocks = []
    for record in candidates:
        lines = []
        for label, key, code in (("Nama", "nama_wajib_pajak", False), ("NPWP", "npwp", True),
                                 ("Tipe", "tipe_wajib_pajak", False), ("Alamat", "alamat_wajib_pajak", False),
                                 ("Jenis WP", "jenis_wajib_pajak", False), ("Kode KLU", "kode_klu", True),
                                 ("Keterangan", "keterangan_klu", False), ("Tanggal", "tanggal_registrasi_pajak", False),
                                 ("Kantor Pajak", "kantor_pajak", False), ("Wilayah Pajak", "wilayah_pajak", False),
                                 ("Tempat Kerja", "tempat_kerja", False), ("Profil Risiko", "profil_risiko", False),
                                 ("Dalam Penagihan", "status_penagihan", False),
                                 ("Status WP", "status_wajib_pajak", False)):
            if _present(record.get(key)):
                lines.append(_plain_line(label, record[key], code=code,
                                         bold=label == "Nama"))
        blocks.append(_block("Wajib Pajak", lines, emoji="👤"))
    return _section("🧾 *DATA PERPAJAKAN*", "\n\n".join(blocks))


def _render_sections(fields: Any) -> list[str]:
    records = _records(fields)
    used: set[int] = set()
    sections = [
        _render_a_phone(records, used),
        _render_b_identity(records, used),
        _render_c_family(records, used),
        _render_d_msisdn(records, used),
        _render_e_assets(records, used),
        _render_f_bansos(records, used),
        _render_g_wni(records, used),
        _render_h_tax(records, used),
    ]
    sections = [section for section in sections if section]
    if sections:
        sections[0] = f"🔎 *HASIL PENCARIAN DATA*\n\n{SEPARATOR}\n" + sections[0]
        sections[-1] += f"\n✅ *AKHIR HASIL*\n{SEPARATOR}"
    return sections


def _available(value: Any) -> bool:
    """Nilai yang masih layak ditampilkan pada output NIK."""
    return value is not None and (not isinstance(value, str) or bool(value.strip()))


def _nik_codes(value: Any) -> list[str]:
    pairs = re.findall(r"(PROV|KAB|KEC|KEL)\s*:\s*([^\s]+)", _text(value), re.I)
    values = {key.upper(): item for key, item in pairs}
    labels = {"PROV": "Provinsi", "KAB": "Kabupaten", "KEC": "Kecamatan", "KEL": "Kelurahan"}
    return [_plain_line(labels[key], values[key], code=True)
            for key in ("PROV", "KAB", "KEC", "KEL") if key in values]


def _nik_identity_name(record: Mapping[str, Any]) -> Any:
    name = record.get("nama_lengkap") or record.get("nama")
    structural_names = {"IDENTITAS", "AKTA", "LAINNYA", "SEKOLAH", "ℹMETADATA", "TANGGA"}
    if not _available(name) or _text(name).upper() in structural_names:
        return None
    return name


def _is_nik_identity(record: Mapping[str, Any]) -> bool:
    nik = record.get("nik")
    return (_available(nik) and _text(nik) not in {"N/A", "-"}
            and _available(_nik_identity_name(record)))


def _nik_profile(records: list[dict[str, Any]]) -> dict[str, Any]:
    preferred = next((record for record in records
                      if _is_nik_identity(record) and _available(record.get("nama_lengkap"))), None)
    selected = preferred or next((record for record in records if _is_nik_identity(record)), None)
    if not selected:
        return {}
    profile = dict(selected)
    profile.setdefault("nama_lengkap", _nik_identity_name(selected))
    return profile


def _nik_parent_records(records: list[dict[str, Any]], used: set[int]) -> tuple[dict[str, Any], dict[str, Any]]:
    found = []
    for _ in range(2):
        record = _take(
            records,
            used,
            lambda r: set(r) <= {"nama", "nik"}
            and r.get("nama") not in {"AKTA", "LAINNYA"}
            and not re.fullmatch(r"\d+\.", _text(r.get("nama", ""))),
        )
        if record:
            found.append(record)
    while len(found) < 2:
        found.append({})
    return found[0], found[1]


def _nik_person_block(title: str, name: Any, nik: Any, emoji: str) -> str:
    lines = []
    if _available(name):
        lines.append(_plain_line("Nama", name))
    if _available(nik) and _text(nik) != "N/A":
        lines.append(_plain_line("NIK", nik, code=True))
    return _block(title, lines, emoji=emoji)


def _display_date(value: Any) -> str:
    text = _text(value)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}T.*", text):
        return text.split("T", 1)[0]
    return text


def _render_nik_population(records: list[dict[str, Any]], used: set[int]) -> str:
    selected = (
        _take(records, used, lambda r: _is_nik_identity(r) and _available(r.get("nama_lengkap")))
        or _take(records, used, _is_nik_identity)
    )
    if not selected:
        return ""
    profile = dict(selected)
    profile.setdefault("nama_lengkap", _nik_identity_name(selected))
    identity = []
    for label, key, code, bold in (
        ("Nama Lengkap", "nama_lengkap", False, True), ("NIK", "nik", True, False),
        ("No. KK", "nomor_kk", True, False), ("Jenis Kelamin", "jenis_kelamin", False, False),
    ):
        if _available(profile.get(key)):
            identity.append(_plain_line(label, profile[key], code=code, bold=bold))
    identity.append("")
    for label, key in (("Tempat Lahir", "tempat_lahir"), ("Tanggal Lahir", "tanggal_lahir"),
                       ("Status Kawin", "status_kawin"), ("Status Hubungan", "status_hubungan")):
        if _available(profile.get(key)):
            value = _display_date(profile[key]) if key == "tanggal_lahir" else profile[key]
            identity.append(_plain_line(label, value))
    blocks = [_block("Identitas", identity, emoji="👤")]

    address = [_text(profile["alamat"])] if _available(profile.get("alamat")) else []
    for label, key in (("RT/RW", "rt/rw"), ("Dusun", "dusun"), ("Kelurahan", "kelurahan"),
                       ("Kecamatan", "kecamatan"), ("Kabupaten", "kabupaten"),
                       ("Provinsi", "provinsi"), ("Kode Pos", "kode_pos")):
        if _available(profile.get(key)):
            address.append(_plain_line(label, profile[key]))
    if address:
        blocks.append(_block("Alamat", address, emoji="🏠"))
    if _available(profile.get("google_maps")):
        blocks.append(_block("Google Maps", [_url(profile["google_maps"])], emoji="🗺️"))
    codes = _nik_codes(profile.get("nomor_wilayah"))
    if codes:
        blocks.append(_block("Kode Wilayah", codes, emoji="📍"))

    family_head = next((record for record in records if {"status_hubungan", "ayah", "ibu"}.issubset(record)), {})
    father, mother = _nik_parent_records(records, used)
    parent_values = (
        ("Data Ayah", father.get("nama") or _parent(family_head.get("ayah"))[0], father.get("nik"), "👨"),
        ("Data Ibu", mother.get("nama") or _parent(family_head.get("ibu"))[0], mother.get("nik"), "👩"),
    )
    for title, name, nik, emoji in parent_values:
        block = _nik_person_block(title, name, nik, emoji)
        if block:
            blocks.append(block)

    lainnya = _take(records, used, lambda r: _record_group(r) == "LAINNYA") or {}
    other_lines = []
    for label, key in (("Pendidikan", "pendidikan"), ("Pekerjaan", "pekerjaan"),
                       ("Gol. Darah", "gol._darah"), ("Disabilitas", "penyandang_cacat")):
        if _available(lainnya.get(key)):
            other_lines.append(_plain_line(label, lainnya[key]))
    other = _block("Informasi Lain", other_lines, emoji="📋")
    if other:
        blocks.append(other)

    akta = _take(records, used, lambda r: _record_group(r) == "AKTA") or {}
    act_lines = []
    for label, key in (("No. Akta Lahir", "no._akta_lahir"), ("No. Akta Kawin", "no._akta_kawin"),
                       ("Tgl. Kawin", "tgl_kawin"), ("No. Akta Cerai", "no._akta_cerai"),
                       ("Tgl. Cerai", "tgl_cerai")):
        if _available(akta.get(key)):
            act_lines.append(_plain_line(label, akta[key]))
    act = _block("Data Akta", act_lines, emoji="📜")
    if act:
        blocks.append(act)
    return _section("🪪 *INFORMASI KEPENDUDUKAN*", "\n\n".join(blocks))


def _is_family_continuation(record: Mapping[str, Any]) -> bool:
    return (
        not {"nik", "status_hubungan"}.intersection(record)
        and bool({"no_hp", "pendidikan"}.intersection(record))
        and set(record).issubset({"nama", "bagian", "no_hp", "pendidikan"})
    )


def _merge_family_continuation(member: dict[str, Any], continuation: Mapping[str, Any]) -> None:
    if _available(continuation.get("no_hp")):
        member["no_hp"] = continuation["no_hp"]
    if _available(continuation.get("pendidikan")):
        member["pendidikan"] = continuation["pendidikan"]

    suffix = continuation.get("bagian") or continuation.get("nama")
    if not _available(suffix):
        return
    suffix_text = _text(suffix)
    pekerjaan = _text(member.get("pekerjaan")) if _available(member.get("pekerjaan")) else ""
    pendidikan = _text(member.get("pendidikan")) if _available(member.get("pendidikan")) else ""
    if pekerjaan.upper().endswith("MENGURUS RUMAH") and suffix_text.upper() == "TANGGA":
        member["pekerjaan"] = f"{pekerjaan} {suffix_text}"
    elif pendidikan.upper().endswith("BELUM TAMAT"):
        member["pendidikan"] = f"{pendidikan} {suffix_text}"


def _render_nik_family(records: list[dict[str, Any]], used: set[int]) -> str:
    family = []
    for index, record in enumerate(records):
        if index in used or not {"nik", "status_hubungan"}.issubset(record):
            continue
        used.add(index)
        member = dict(record)
        next_index = index + 1
        while next_index < len(records) and next_index not in used and _is_family_continuation(records[next_index]):
            used.add(next_index)
            _merge_family_continuation(member, records[next_index])
            next_index += 1
        family.append(member)
    if not family:
        return ""
    kk = _take(records, used, lambda r: set(r) == {"nomor_kk"})
    names = _member_names(records)
    body = [_plain_line("No. KK", kk["nomor_kk"], code=True)] if kk else []
    for number, record in enumerate(family, 1):
        name = record.get("nama") or names.get(_text(record.get("nik")), f"NIK {_text(record.get('nik', ''))}")
        lines = []
        if _available(record.get("nik")):
            lines.append(_plain_line("NIK", record["nik"], code=True))
        if _available(record.get("jenis_kelamin")):
            lines.append(_plain_line("Jenis Kelamin", record["jenis_kelamin"]))
        birth = [(_display_date(record[key]) if key == "tanggal_lahir" else _text(record[key]))
                 for key in ("tempat_lahir", "tanggal_lahir") if _available(record.get(key))]
        if birth:
            lines.append(f"Lahir: {', '.join(birth)}")
        if _available(record.get("status_hubungan")):
            lines.append(_plain_line("Hubungan", record["status_hubungan"]))
        lines.append("")
        for label, key in (("Ayah", "ayah"), ("Ibu", "ibu"), ("Pekerjaan", "pekerjaan"),
                           ("Pendidikan", "pendidikan"), ("No. HP", "no_hp")):
            value = record.get(key)
            if key in {"ayah", "ibu"} and _available(value):
                value, _ = _parent(value)
            if _available(value):
                lines.append(_plain_line(label, value))
        body.append(_block(f"{number}. {_text(name)}", lines, emoji="👤"))
    for index, record in enumerate(records):
        if index not in used and ("anggota" in record or record.get("nama") == "JENIS KELAMIN"):
            used.add(index)
    return _section("👨‍👩‍👧‍👦 *ANGGOTA KELUARGA*", "\n\n".join(body))


def _render_nik_msisdn(records: list[dict[str, Any]], used: set[int]) -> str:
    phones = []
    for index, record in enumerate(records):
        if index not in used and {"nik", "nomor", "provider"}.issubset(record):
            used.add(index)
            phones.append(record)
    if not phones:
        return ""
    nik = next((_text(record["nik"]) for record in phones if _available(record.get("nik"))), "")
    body = [_plain_line("🪪 NIK", nik, code=True)] if nik else []
    for number, record in enumerate(phones, 1):
        lines = []
        for label, key, code in (("Nomor", "nomor", True), ("Provider", "provider", False),
                                 ("Terakhir Terdaftar", "terakhir_terdaftar", False)):
            if _available(record.get(key)):
                lines.append(_plain_line(label, record[key], code=code))
        lines.append("")
        if _available(record.get("whatsapp")):
            lines.append(_plain_line("WhatsApp", record["whatsapp"]))
        if _available(record.get("keterangan_whatsapp")):
            lines.append(_text(record["keterangan_whatsapp"]))
        checked = _first((record,), "tanggal_pengecekan")
        checked_time = _first((record,), "waktu_pengecekan")
        if _available(checked) or _available(checked_time):
            value = " ".join(str(v) for v in (checked, checked_time) if _available(v)) + " WIB"
            lines.append(_plain_line("Dicek", value))
        link = record.get("cek_update_manual") or record.get("cek_manual")
        if _available(link):
            lines.append(f"🔗 {_url(link)}")
        body.append(_block(f"Nomor {number}", lines, emoji="📱"))
    return _section("📶 *DATA MSISDN*", "\n\n".join(body))


def _render_nik_assets(records: list[dict[str, Any]], used: set[int]) -> str:
    assets = []
    for index, record in enumerate(records):
        if index not in used and {"merk", "tipe"}.issubset(record):
            used.add(index)
            assets.append(record)
    if not assets:
        return ""
    body = []
    for record in assets:
        title = _text(record.get("nama", "DATA ASET"))
        lines = []
        for label, key, code, bold in (("Pemilik", "pemilik", False, True), ("Merk", "merk", False, False),
                                       ("Tipe", "tipe", False, False), ("Tahun", "tahun", False, False),
                                       ("Warna", "warna", False, False), ("No. Rangka", "no_rangka", True, False),
                                       ("No. Mesin", "no_mesin", True, False), ("No. BPKB", "no_bpkb", True, False),
                                       ("No. HP", "no_hp", False, False)):
            if _available(record.get(key)):
                lines.append(_plain_line(label, record[key], code=code, bold=bold))
        if _available(record.get("alamat")):
            lines.extend(["", "🏠 *Alamat*", _text(record["alamat"])])
        body.append(_block(title, lines, emoji="🚘"))
    return _section("🚗 *DATA ASET*", "\n\n".join(body))


def _render_nik_bansos(records: list[dict[str, Any]], used: set[int]) -> str:
    keys = {"desil", "status_sembako", "periode_sembako", "status_pkh", "periode_pkh",
            "status_pbi_jk", "periode_pbi_jk", "status_bansos", "keterangan_bansos",
            "sembako", "pkh", "pbi-jk"}
    record = _take(records, used, lambda r: bool(keys.intersection(r)))
    if not record:
        return ""
    lines = []
    name = record.get("nama_lengkap") or record.get("nama")
    if _available(name):
        lines.append(_plain_line("👤 Nama", name, bold=True))
    if _available(record.get("desil")):
        lines.extend(["", _plain_line("Desil", record["desil"])])

    def status(label: str, *field_names: str) -> None:
        value = next((record.get(key) for key in field_names if _available(record.get(key))), None)
        if not _available(value):
            return
        match = re.match(r"(.+?)\s*\(\s*PERIODE\s*:\s*(.*?)\s*\)$", _text(value), re.I)
        if match:
            lines.extend([_plain_line(label, match.group(1).strip()),
                          _plain_line("Periode", match.group(2).strip())])
        else:
            lines.append(_plain_line(label, value))

    status("🛒 Sembako", "status_sembako", "sembako")
    status("💵 PKH", "status_pkh", "pkh")
    status("🏥 PBI-JK", "status_pbi_jk", "pbi-jk")
    value = record.get("status_bansos") or record.get("status")
    if _available(value):
        lines.append(_plain_line("Status", value))
    value = record.get("keterangan_bansos") or record.get("keterangan")
    if _available(value):
        lines.append(_plain_line("Keterangan", value))
    return _section("💰 *DATA BANSOS & EKONOMI*", "\n".join(lines))


def _render_nik_supporting(records: list[dict[str, Any]], used: set[int]) -> str:
    support = []
    support_keys = {"adres", "telepon", "nomor_paspor", "penyedia"}
    for index, record in enumerate(records):
        if index not in used and support_keys.intersection(record):
            used.add(index)
            support.append(record)
    if not support:
        return ""
    profile = _nik_profile(records)
    record = support[0]
    nik = record.get("nik") or record.get("nomor_paspor") or profile.get("nik")
    phone = record.get("telepon") or record.get("nomor")
    name = record.get("nama_lengkap") or record.get("nama") or profile.get("nama_lengkap")
    address = record.get("adres") or record.get("alamat")
    lines = []
    for label, value, code, bold in (("NIK", nik, True, False), ("MSISDN", phone, False, False),
                                     ("Nama", name, False, True)):
        if _available(value):
            lines.append(_plain_line(label, value, code=code, bold=bold))
    if _available(address):
        lines.extend(["", "🏠 *Alamat*", _text(address)])
    return _section("📋 *DATA IDENTITAS PENDUKUNG*", "\n".join(lines))


def _render_nik_wni(records: list[dict[str, Any]], used: set[int]) -> str:
    candidates = []
    for index, record in enumerate(records):
        if index not in used and any(key.startswith(("wni", "dukcapil")) for key in record):
            used.add(index)
            candidates.append(record)
    admin = _take(
        records, used,
        lambda r: {"nik", "nama_lengkap"}.issubset(r)
        and any(key in r for key in ("no._kk", "agama", "nama_ayah", "nama_ibu")),
    ) or {}
    if not candidates and not admin:
        return ""
    profile = _nik_profile(records)
    family_head = next((record for record in records if {"status_hubungan", "ayah", "ibu"}.issubset(record)), {})
    lainnya = next((record for record in records if record.get("nama") == "LAINNYA"), {})

    def value(key: str, fallback: Any = None) -> Any:
        return admin.get(key) or profile.get(key) or fallback

    identity = []
    for label, item, code, bold in (
        ("Nama", value("nama_lengkap"), False, True), ("NIK", value("nik"), True, False),
        ("No. KTP", value("no_ktp"), True, False), ("No. KK", value("no._kk", profile.get("nomor_kk")), True, False),
        ("Tempat Sebelumnya", value("tempat_sebelumnya"), False, False),
        ("Jenis Kelamin", value("jenis_kelamin"), False, False),
        ("Tempat Lahir", value("tempat_lahir"), False, False),
        ("Tanggal Lahir", value("tanggal_lahir", _comparison_value(records, "TANGGAL LAHIR")), False, False),
        ("Gol. Darah", value("golongan_darah", lainnya.get("gol._darah")), False, False),
        ("Agama", value("agama"), False, False),
        ("Status Kawin", value("status_kawin", _comparison_value(records, "STATUS KAWIN")), False, False),
    ):
        if _available(item):
            identity.append(_plain_line(label, item, code=code, bold=bold))

    family = []
    relationship = value("status_hubungan_keluarga", profile.get("status_hubungan"))
    if _available(relationship):
        family.append(_plain_line("Status Hubungan", relationship))
    for label, key, admin_key in (("Ayah", "ayah", "nama_ayah"), ("Ibu", "ibu", "nama_ibu")):
        item, _ = _parent(admin.get(admin_key) or family_head.get(key))
        if _available(item):
            family.append(_plain_line(label, item))

    education = []
    for label, item in (("Pendidikan", admin.get("pendidikan_akhir") or lainnya.get("pendidikan")),
                        ("Pekerjaan", admin.get("jenis_pekerjaan") or _comparison_value(records, "PEKERJAAN")
                         or lainnya.get("pekerjaan"))):
        if _available(item):
            education.append(_plain_line(label, item))

    documents = []
    for label, key in (("Akta Lahir", "akta_lahir"), ("Akta Kawin", "akta_kawin"),
                       ("Akta Cerai", "akta_cerai")):
        if _available(admin.get(key)):
            documents.append(_plain_line(label, admin[key]))

    wilayah = []
    for label, key in (("Provinsi", "provinsi"), ("Kabupaten", "kabupaten"),
                       ("Kecamatan", "kecamatan"), ("Kelurahan", "kelurahan")):
        if _available(profile.get(key)):
            wilayah.append(_plain_line(label, profile[key]))

    administration = []
    for label, key in (("Kelas Fiskal", "kelas_fiskal"), ("Disabilitas", "penyandang_cacat"),
                       ("Tgl. Ubah", "tgl_ubah"), ("Isu Pendatang", "isu_pendatang"),
                       ("Jumlah KTP", "jumlah_ktp"), ("Jumlah Biodata", "jumlah_biodata")):
        if _available(admin.get(key)):
            administration.append(_plain_line(label, admin[key]))

    blocks = []
    for title, items, emoji in (("Identitas", identity, "👤"), ("Keluarga", family, "👨‍👩‍👦"),
                                ("Pendidikan & Pekerjaan", education, "🎓"), ("Dokumen", documents, "📜"),
                                ("Wilayah", wilayah, "📍"), ("Administrasi", administration, "📋")):
        block = _block(title, items, emoji=emoji)
        if block:
            blocks.append(block)
    return _section("🇮🇩 *DATA WNI*", "\n\n".join(blocks))


def _render_nik_tax(records: list[dict[str, Any]], used: set[int]) -> tuple[str, str]:
    taxpayer_keys = {"nama_wajib_pajak", "npwp", "tipe_wajib_pajak", "nama_sensor", "nama_aktivitas"}
    tax_keys = {"kode_klu", "jenis_wajib_pajak", "kantor_pajak", "profil_risiko",
                "status_wajib_pajak", "tanggal_registrasi_pajak"}
    taxpayer = []
    taxation = []
    for index, record in enumerate(records):
        if index in used:
            continue
        if taxpayer_keys.intersection(record):
            used.add(index)
            taxpayer.append(record)
        elif tax_keys.intersection(record):
            used.add(index)
            taxation.append(record)

    wajib_blocks = []
    for record in taxpayer:
        identity = []
        for label, key, code in (("Nama", "nama_wajib_pajak", False), ("NPWP", "npwp", True),
                                 ("Tipe", "tipe_wajib_pajak", False)):
            if _available(record.get(key)):
                identity.append(_plain_line(label, record[key], code=code))
        address = []
        if _available(record.get("alamat_wajib_pajak")):
            address.append(_text(record["alamat_wajib_pajak"]))
        activity = []
        for label, key in (("Nama", "nama_sensor"), ("Nama Aktivitas", "nama_aktivitas"),
                           ("Jenis Kelamin", "jenis_kelamin_wp"), ("Tanggal Lahir", "tanggal_lahir_wp"),
                           ("Alamat", "alamat_wp"), ("Kode Pos", "kode_pos_wp")):
            if _available(record.get(key)):
                activity.append(_plain_line(label, record[key]))
        for title, items, emoji in (("Identitas Wajib Pajak", identity, "👤"), ("Alamat", address, "🏠"),
                                    ("Data Aktivitas", activity, "📋")):
            block = _block(title, items, emoji=emoji)
            if block:
                wajib_blocks.append(block)

    pajak_blocks = []
    for record in taxation:
        groups = []
        classification = []
        for label, key, code in (("Jenis Wajib Pajak", "jenis_wajib_pajak", False), ("Kode KLU", "kode_klu", True),
                                 ("Keterangan KLU", "keterangan_klu", False)):
            if _available(record.get(key)):
                classification.append(_plain_line(label, record[key], code=code))
        registration = []
        for label, key in (("Tanggal Registrasi", "tanggal_registrasi_pajak"), ("Kantor Pajak", "kantor_pajak"),
                           ("Wilayah Pajak", "wilayah_pajak"), ("Tempat Kerja", "tempat_kerja")):
            if _available(record.get(key)):
                registration.append(_plain_line(label, record[key]))
        compliance = []
        for label, key in (("Profil Risiko", "profil_risiko"), ("Dalam Penagihan", "status_penagihan"),
                           ("Status Wajib Pajak", "status_wajib_pajak")):
            if _available(record.get(key)):
                compliance.append(_plain_line(label, record[key]))
        for title, items, emoji in (("Klasifikasi", classification, "🏷️"), ("Registrasi", registration, "🏢"),
                                    ("Status Kepatuhan", compliance, "📊")):
            block = _block(title, items, emoji=emoji)
            if block:
                groups.append(block)
        pajak_blocks.extend(groups)

    wajib = _section("🧾 *DATA WAJIB PAJAK*", "\n\n".join(wajib_blocks))
    pajak = _section("🏛️ *DATA PERPAJAKAN*", "\n\n".join(pajak_blocks))
    return wajib, pajak


def _render_nik_sections(fields: Any) -> list[str]:
    records = _records(fields)
    used: set[int] = set()
    wajib_pajak, perpajakan = _render_nik_tax(records, used)
    sections = [
        _render_nik_population(records, used),
        _render_nik_family(records, used),
        _render_nik_msisdn(records, used),
        _render_nik_assets(records, used),
        _render_nik_bansos(records, used),
        _render_nik_supporting(records, used),
        _render_nik_wni(records, used),
        wajib_pajak,
        perpajakan,
    ]
    sections = [section for section in sections if section]
    if sections:
        sections[0] = f"🔎 *HASIL PENCARIAN DATA*\n\n{SEPARATOR}\n" + sections[0]
        sections[-1] += f"\n✅ *AKHIR HASIL*\n{SEPARATOR}"
    return sections


def _kk_codes(value: Any) -> list[str]:
    pairs = re.findall(r"(PROV|KAB|KEC|KEL)\s*:\s*([^\s]+)", _text(value), re.I)
    values = {key.upper(): item for key, item in pairs}
    labels = {
        "PROV": "Provinsi",
        "KAB": "Kabupaten/Kota",
        "KEC": "Kecamatan",
        "KEL": "Desa/Kelurahan",
    }
    return [_plain_line(labels[key], values[key], code=True)
            for key in ("PROV", "KAB", "KEC", "KEL") if key in values]


def _kk_profile(records: list[dict[str, Any]]) -> dict[str, Any]:
    profile_keys = {
        "nama_lengkap", "nik", "nomor_kk", "jenis_kelamin", "tempat_lahir",
        "tanggal_lahir", "status_kawin", "status_hubungan", "alamat",
        "nomor_wilayah", "google_maps", "kelurahan", "kecamatan", "kabupaten",
        "provinsi",
    }
    candidates = [
        record for record in records
        if _record_group(record) not in {"DATA AYAH", "DATA IBU", "LAINNYA", "AKTA"}
        and any(_available(record.get(key)) for key in profile_keys)
    ]
    if not candidates:
        return {}

    def score(record: Mapping[str, Any]) -> int:
        return (
            20 * int(_available(record.get("nama_lengkap")))
            + 10 * int(_is_nik_identity(record))
            + 4 * int(_available(record.get("nomor_kk")))
            + sum(int(_available(record.get(key))) for key in profile_keys)
        )

    selected = max(candidates, key=score)
    profile = dict(selected)
    selected_nik = _text(profile["nik"]) if _available(profile.get("nik")) else ""
    for record in candidates:
        record_nik = _text(record["nik"]) if _available(record.get("nik")) else ""
        if selected_nik and record_nik and record_nik != selected_nik:
            continue
        for key, value in record.items():
            current = profile.get(key)
            if (_available(value)
                    and (not _available(current) or _text(current).upper() in {"N/A", "-"})):
                profile[key] = value
    name = _nik_identity_name(profile)
    if _available(name) and not _available(profile.get("nama_lengkap")):
        profile["nama_lengkap"] = name
    return profile


def _kk_parent(records: list[dict[str, Any]], group: str) -> dict[str, Any]:
    explicit = next((record for record in records if _record_group(record) == group), None)
    if explicit:
        return explicit
    candidates = [record for record in records
                  if set(record).issubset({"nama", "nik"}) and _available(record.get("nama"))]
    index = 0 if group == "DATA AYAH" else 1
    return candidates[index] if index < len(candidates) else {}


def _render_kk_information(records: list[dict[str, Any]]) -> str:
    profile = _kk_profile(records)
    identity_main = []
    for label, key, code, bold in (
        ("Nama Lengkap", "nama_lengkap", False, True), ("NIK", "nik", True, False),
        ("No. KK", "nomor_kk", True, False), ("Jenis Kelamin", "jenis_kelamin", False, False),
    ):
        if _available(profile.get(key)):
            identity_main.append(_plain_line(label, profile[key], code=code, bold=bold))
    identity_detail = []
    for label, key in (("Tempat Lahir", "tempat_lahir"), ("Tanggal Lahir", "tanggal_lahir"),
                       ("Status Kawin", "status_kawin"), ("Status Hubungan", "status_hubungan")):
        if _available(profile.get(key)):
            value = _display_date(profile[key]) if key == "tanggal_lahir" else profile[key]
            identity_detail.append(_plain_line(label, value))
    identity = identity_main + ([""] if identity_main and identity_detail else []) + identity_detail
    blocks = []
    block = _block("Identitas", identity, emoji="👤")
    if block:
        blocks.append(block)

    address = []
    if _available(profile.get("alamat")):
        address.append(_text(profile["alamat"]))
    for label, key in (("RT/RW", "rt/rw"), ("Dusun", "dusun"),
                       ("Desa/Kelurahan", "kelurahan"), ("Kecamatan", "kecamatan"),
                       ("Kabupaten/Kota", "kabupaten"), ("Provinsi", "provinsi"),
                       ("Kode Pos", "kode_pos")):
        if _available(profile.get(key)):
            address.append(_plain_line(label, profile[key]))
    block = _block("Alamat", address, emoji="🏠")
    if block:
        blocks.append(block)
    if _available(profile.get("google_maps")):
        blocks.append(_block("Google Maps", [_url(profile["google_maps"])], emoji="🗺️"))
    codes = _kk_codes(profile.get("nomor_wilayah"))
    if codes:
        blocks.append(_block("Kode Wilayah", codes, emoji="📍"))

    for title, group, emoji in (("Data Ayah", "DATA AYAH", "👨"), ("Data Ibu", "DATA IBU", "👩")):
        parent = _kk_parent(records, group)
        lines = []
        if _available(parent.get("nama")):
            lines.append(_plain_line("Nama", parent["nama"]))
        if _available(parent.get("nik")):
            lines.append(_plain_line("NIK", parent["nik"], code=True))
        block = _block(title, lines, emoji=emoji)
        if block:
            blocks.append(block)

    lainnya = next((record for record in records if _record_group(record) == "LAINNYA"), {})
    other_lines = []
    for label, key in (("Pendidikan", "pendidikan"), ("Pekerjaan", "pekerjaan"),
                       ("Gol. Darah", "gol._darah"), ("Disabilitas", "penyandang_cacat")):
        if _available(lainnya.get(key)):
            other_lines.append(_plain_line(label, lainnya[key]))
    block = _block("Informasi Lain", other_lines, emoji="📋")
    if block:
        blocks.append(block)

    akta = next((record for record in records if _record_group(record) == "AKTA"), {})
    act_lines = []
    for label, key in (("No. Akta Lahir", "no._akta_lahir"), ("No. Akta Kawin", "no._akta_kawin"),
                       ("Tgl. Kawin", "tgl_kawin"), ("No. Akta Cerai", "no._akta_cerai"),
                       ("Tgl. Cerai", "tgl_cerai")):
        if _available(akta.get(key)):
            act_lines.append(_plain_line(label, akta[key]))
    block = _block("Data Akta", act_lines, emoji="📜")
    if block:
        blocks.append(block)
    if not blocks:
        blocks.append("Data kartu keluarga belum tersedia.")
    return _section("👨‍👩‍👧‍👦 *INFORMASI KARTU KELUARGA*", "\n\n".join(blocks))


def _kk_members(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    member_markers = {
        "nomor_kk", "status_hubungan", "ayah", "ibu", "nik_ayah", "nik_ibu",
        "tempat/tgl_lahir", "jenis_kelamin", "desa/kelurahan", "kabupaten/kota",
    }
    grouped: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for index, record in enumerate(records):
        if _record_group(record) in {"DATA AYAH", "DATA IBU", "LAINNYA", "AKTA"}:
            continue
        name = record.get("nama_lengkap") or record.get("nama")
        nik = record.get("nik")
        has_identity = _available(nik) or _available(name)
        has_family_data = any(_available(record.get(key)) for key in member_markers)
        if not has_identity or not has_family_data:
            continue

        nik_text = _text(nik) if _available(nik) else ""
        name_text = _text(name).upper() if _available(name) else ""
        key = f"nik:{nik_text}" if nik_text not in {"", "N/A", "-"} else f"name:{name_text or index}"
        if key not in grouped:
            grouped[key] = dict(record)
            order.append(key)
            continue
        merged = grouped[key]
        for field, value in record.items():
            current = merged.get(field)
            if (_available(value)
                    and (not _available(current) or _text(current).upper() in {"N/A", "-"})):
                merged[field] = value
    return [grouped[key] for key in order]


def _split_birth(value: Any) -> tuple[str, str]:
    text = _text(value) if _available(value) else ""
    if "," not in text:
        return text, ""
    place, date = text.rsplit(",", 1)
    return place.strip(), _display_date(date.strip())


def _kk_member_names(records: list[dict[str, Any]], profile: Mapping[str, Any]) -> dict[str, str]:
    names = _member_names(records)
    if _available(profile.get("nik")) and _available(profile.get("nama_lengkap")):
        names[_text(profile["nik"])] = _text(profile["nama_lengkap"])
    for record in records:
        for name_key, nik_key in (("ayah", "nik_ayah"), ("ibu", "nik_ibu")):
            if _available(record.get(name_key)) and _available(record.get(nik_key)):
                nik = _text(record[nik_key])
                if nik not in {"N/A", "-"}:
                    names[nik] = _text(record[name_key])
    return names


def _render_kk_members(records: list[dict[str, Any]]) -> str:
    members = _kk_members(records)
    if not members:
        return _section("👥 *ANGGOTA KELUARGA*", "Data anggota keluarga belum tersedia.")
    names = _kk_member_names(records, _kk_profile(records))
    cards = []
    for number, member in enumerate(members, 1):
        nik = _text(member.get("nik", ""))
        name = member.get("nama") or names.get(nik) or f"NIK {nik}"
        lines = []
        for label, key, code in (("NIK", "nik", True), ("No. KK", "nomor_kk", True),
                                 ("Jenis Kelamin", "jenis_kelamin", False)):
            if _available(member.get(key)):
                lines.append(_plain_line(label, member[key], code=code))
        place, date = _split_birth(member.get("tempat/tgl_lahir"))
        if not place and _available(member.get("tempat_lahir")):
            place = _text(member["tempat_lahir"])
        if not date and _available(member.get("tanggal_lahir")):
            date = _display_date(member["tanggal_lahir"])
        birth = ", ".join(value for value in (place, date) if value)
        if birth:
            lines.append(_plain_line("Lahir", birth))
        for label, key in (("Status Kawin", "status_kawin"), ("Hubungan", "status_hubungan")):
            if _available(member.get(key)):
                lines.append(_plain_line(label, member[key]))

        domicile = []
        for label, keys in (("Alamat", ("alamat",)), ("RT/RW", ("rt/rw",)),
                            ("Desa/Kelurahan", ("desa/kelurahan", "kelurahan")),
                            ("Kecamatan", ("kecamatan",)),
                            ("Kabupaten/Kota", ("kabupaten/kota", "kabupaten")),
                            ("Provinsi", ("provinsi",)), ("Kode Pos", ("kode_pos",))):
            value = next((member.get(key) for key in keys if _available(member.get(key))), None)
            if _available(value):
                domicile.append(_plain_line(label, value))
        if domicile:
            lines.extend(["", _block("Domisili", domicile, emoji="🏠")])

        for emoji, label, name_key, nik_key in (("👨", "Ayah", "ayah", "nik_ayah"),
                                                ("👩", "Ibu", "ibu", "nik_ibu")):
            if _available(member.get(name_key)):
                lines.extend(["", _plain_line(f"{emoji} {label}", member[name_key])])
            if _available(member.get(nik_key)):
                lines.append(_plain_line(f"NIK {label}", member[nik_key], code=True))
        cards.append(_block(f"{number}. {_text(name)}", lines, emoji="👤"))
    return _section("👥 *ANGGOTA KELUARGA*", f"\n\n{'┄' * 10}\n\n".join(cards))


def _render_kk_summary(records: list[dict[str, Any]]) -> str:
    profile = _kk_profile(records)
    members = _kk_members(records)
    total_record = next((record for record in records if _available(record.get("total_anggota"))), {})
    head = next((member for member in members
                 if _text(member.get("status_hubungan", "")).upper() == "KEPALA KELUARGA"), {})
    names = _kk_member_names(records, profile)
    head_nik = _text(head.get("nik", ""))
    head_name = head.get("nama") or names.get(head_nik) or profile.get("nama_lengkap")
    kk = profile.get("nomor_kk") or (members[0].get("nomor_kk") if members else None)
    lines = []
    if _available(kk):
        lines.append(_plain_line("No. KK", kk, code=True))
    if _available(head_name):
        lines.append(_plain_line("Kepala Keluarga", head_name, bold=True))
    total = total_record.get("total_anggota")
    if not _available(total) and members:
        total = len(members)
    if _available(total):
        lines.append(_plain_line("Jumlah Anggota", total))

    kelurahan = profile.get("kelurahan") or head.get("desa/kelurahan")
    kecamatan = profile.get("kecamatan") or head.get("kecamatan")
    kabupaten = profile.get("kabupaten") or head.get("kabupaten/kota")
    provinsi = profile.get("provinsi") or head.get("provinsi")
    first_location = ", ".join(_text(value) for value in (kelurahan, kecamatan) if _available(value))
    second_location = ", ".join(_text(value) for value in (kabupaten, provinsi) if _available(value))
    if first_location or second_location:
        lines.append("")
    if first_location:
        lines.append(f"📍 {first_location}")
    if second_location:
        lines.append(second_location)
    if not lines:
        lines.append("Data ringkasan keluarga belum tersedia.")
    return _section("📊 *RINGKASAN KELUARGA*", "\n".join(lines))


def _track_first(records: list[dict[str, Any]], *keys: str) -> Any:
    for record in records:
        for key in keys:
            if _available(record.get(key)):
                return record[key]
    return None


def _track_timestamp(records: list[dict[str, Any]]) -> tuple[str, str]:
    months = {
        "jan": "Jan", "feb": "Feb", "mar": "Mar", "apr": "Apr",
        "mei": "May", "may": "May", "jun": "Jun", "jul": "Jul",
        "agu": "Aug", "aug": "Aug", "sep": "Sep", "okt": "Oct",
        "oct": "Oct", "nov": "Nov", "des": "Dec", "dec": "Dec",
    }
    for record in records:
        for key, value in record.items():
            match = re.fullmatch(
                r"tanggal_(\d{1,2})_([a-z]+)_(\d{4})_pukul_(\d{1,2})",
                str(key), re.I,
            )
            if not match or not _available(value):
                continue
            day, month, year, hour = match.groups()
            date = f"{int(day):02d} {months.get(month.lower(), month.title())} {year}"
            raw_time = re.sub(r"\s*WIB\s*$", "", _text(value), flags=re.I).strip()
            if re.fullmatch(r"\d{1,2}:\d{2}", raw_time):
                raw_time = f"{int(hour):02d}:{raw_time}"
            elif re.fullmatch(r"\d{2}:\d{2}:\d{2}", raw_time):
                pass
            else:
                raw_time = f"{int(hour):02d}:{raw_time}" if raw_time else f"{int(hour):02d}:00:00"
            return date, raw_time

    date = _track_first(records, "tanggal_tracking", "tanggal_pengecekan")
    time = _track_first(records, "waktu_tracking", "waktu_pengecekan")
    now_gmt7 = datetime.now(timezone(timedelta(hours=7)))
    fallback_date = now_gmt7.strftime("%d %b %Y")
    fallback_time = now_gmt7.strftime("%H:%M:%S")
    return (_text(date) if _available(date) else fallback_date,
            _text(time).removesuffix(" WIB") if _available(time) else fallback_time)


def _track_network(records: list[dict[str, Any]]) -> tuple[str, str, str, str, str]:
    provider = _track_first(records, "provider")
    mcc = _track_first(records, "mcc")
    mnc = _track_first(records, "mnc")
    lac = _track_first(records, "lac")
    cid = _track_first(records, "cid")
    for record in records:
        group = _text(record.get("bagian", ""))
        match = re.search(r"MCC\s*([\w]+)\s*-\s*MNC\s*([\w]+)\s*=\s*(.+)", group, re.I)
        if match:
            mcc = mcc or match.group(1)
            mnc = mnc or match.group(2)
            provider = provider or match.group(3).strip()
        raw_lac = _text(record.get("lac", ""))
        match = re.search(r"LAC\s*[:=]?\s*([\w]+).*?CID\s*[:=]?\s*([\w]+)", raw_lac, re.I)
        if match:
            lac = match.group(1)
            cid = match.group(2)
        elif _available(record.get("lac")):
            match = re.search(r"^\s*([\w]+)\s*-\s*CID\s*[:=]?\s*([\w]+)", raw_lac, re.I)
            if match:
                lac = match.group(1)
                cid = match.group(2)
    return tuple(_text(value) if _available(value) else "N/A"
                 for value in (provider, mcc, mnc, lac, cid))


def _track_coordinates(records: list[dict[str, Any]]) -> tuple[str, str]:
    raw = _track_first(records, "data_koordinat", "koordinat", "coordinates")
    if _available(raw):
        match = re.search(
            r"LAT\s*[:=]?\s*(-?\d+(?:\.\d+)?)\s+.*?LON\s*[:=]?\s*(-?\d+(?:\.\d+)?)",
            _text(raw), re.I,
        )
        if match:
            return match.group(1), match.group(2)
    latitude = _track_first(records, "latitude", "lat")
    longitude = _track_first(records, "longitude", "lon", "lng")
    return (_text(latitude) if _available(latitude) else "N/A",
            _text(longitude) if _available(longitude) else "N/A")


def _track_device(value: Any) -> tuple[str, str]:
    text = _text(value) if _available(value) else "N/A"
    if text == "N/A":
        return text, text
    brands = (
        "APPLE", "SAMSUNG", "XIAOMI", "REDMI", "OPPO", "VIVO", "REALME",
        "HUAWEI", "GOOGLE", "NOKIA", "INFINIX", "TECNO", "ASUS", "SONY",
        "MOTOROLA", "ONEPLUS", "LENOVO", "BLACKBERRY",
    )
    parts = text.split(maxsplit=1)
    if len(parts) == 1:
        return parts[0], "N/A"
    if parts[0].upper() in brands:
        return parts[0], parts[1]
    return parts[0], parts[1]


def _track_maps_url(records: list[dict[str, Any]], latitude: str, longitude: str) -> str:
    direct = _track_first(records, "google_maps", "google_maps_url", "maps_url")
    if _available(direct):
        return _url(direct)
    if latitude != "N/A" and longitude != "N/A":
        return f"https://maps.google.com/?q={latitude},{longitude}"
    return "N/A"


def _track_mapping_url(records: list[dict[str, Any]]) -> str:
    keys = (
        "mapping_url", "mapping", "triangulation_url", "triangulasi_url",
        "visualisasi_url", "visualisasi", "url_mapping",
    )
    value = _track_first(records, *keys)
    return _url(value) if _available(value) else "N/A"


def _track_line(label: str, value: Any, *, code: bool = False) -> str:
    shown = _text(value) if _available(value) else "N/A"
    return _plain_line(label, shown, code=code)


def _render_track(fields: Any) -> str:
    records = _records(fields)
    date, time = _track_timestamp(records)
    phone = _track_first(records, "mobile_number", "nomor", "msisdn", "no_hp")
    whatsapp = _track_first(records, "whatsapp")
    checked_date, checked_time = date, time
    last_active = _track_first(records, "terakhir_aktif")
    whatsapp_url = _track_first(records, "cek_update_manual", "cek_manual", "whatsapp_url")
    provider, mcc, mnc, lac, cid = _track_network(records)
    imsi = _track_first(records, "data_imsi", "imsi")
    imei = _track_first(records, "data_imei", "imei")
    device_type, device_model = _track_device(
        _track_first(records, "jenis_hp_dan_type_hp", "jenis_hp", "tipe_hp")
    )
    latitude, longitude = _track_coordinates(records)
    maps_url = _track_maps_url(records, latitude, longitude)
    residence = _track_first(records, "kediaman", "alamat")
    mapping_url = _track_mapping_url(records)
    keterangan = _track_first(records, "keterangan_whatsapp", "status_whatsapp_detail")

    lines = [
        "📡 *TRACKING PHONE*",
        "",
        f"🕐 {date} • {time} WIB",
        "",
        SEPARATOR,
        "📱 *INFORMASI NOMOR*",
        SEPARATOR,
        "",
        _track_line("Nomor", phone, code=True),
        "",
        "💬 *WhatsApp*",
        "",
        _track_line("Status", whatsapp),
    ]
    if _available(keterangan):
        lines.append(_text(keterangan))
    lines.extend([
        "",
        _track_line("Dicek", f"{checked_date} {checked_time} WIB"),
        f"🔗 {_url(whatsapp_url) if _available(whatsapp_url) else 'N/A'}",
        "",
        "⚡ *Aktivitas*",
        "",
        _track_line("Terakhir Aktif", last_active),
        "",
        SEPARATOR,
        "📶 *INFORMASI JARINGAN*",
        SEPARATOR,
        "",
        _track_line("Provider", provider),
        _track_line("MCC", mcc, code=True),
        _track_line("MNC", mnc, code=True),
        "",
        _track_line("LAC", lac, code=True),
        _track_line("CID", cid, code=True),
        "",
        SEPARATOR,
        "📡 *INFORMASI PERANGKAT*",
        SEPARATOR,
        "",
        _track_line("IMSI", imsi, code=True),
        _track_line("IMEI", imei, code=True),
        "",
        _track_line("📱 Jenis HP", device_type),
        _track_line("📋 Tipe HP", device_model),
        "",
        SEPARATOR,
        "📍 *DATA LOKASI*",
        SEPARATOR,
        "",
        _track_line("Latitude", latitude, code=True),
        _track_line("Longitude", longitude, code=True),
        "",
        _track_line("🏠 Kediaman", residence),
        "",
        "🗺️ *Google Maps*",
        maps_url,
        "",
        SEPARATOR,
        "📡 *MAPPING & TRIANGULASI*",
        SEPARATOR,
        "",
        "Mapping Area, Triangulation & Visualisasi Sektor:",
        "",
        f"🔗 {mapping_url}",
        "",
        SEPARATOR,
        "✅ *AKHIR HASIL*",
        SEPARATOR,
    ])
    return "\n".join(lines)


def _render_kk_sections(fields: Any) -> list[str]:
    records = _records(fields)
    sections = [
        _render_kk_information(records),
        _render_kk_members(records),
        _render_kk_summary(records),
    ]
    if sections:
        sections[0] = f"🔎 *HASIL PENCARIAN DATA*\n\n{SEPARATOR}\n" + sections[0]
        sections[-1] += f"\n✅ *AKHIR HASIL*\n{SEPARATOR}"
    return sections


def _split_section(section: str, max_chars: int) -> list[str]:
    if len(section) <= max_chars:
        return [section]
    chunks, current = [], ""
    for block in section.split("\n\n"):
        candidate = block if not current else f"{current}\n\n{block}"
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                chunks.append(current)
            current = block
    if current:
        chunks.append(current)
    return chunks


def format_nikbyphone_sections(fields: Any) -> list[str]:
    """Render setiap section target sebagai unit pesan terpisah."""
    return _render_sections(fields)


def format_nikbyphone_messages(fields: Any, max_chars: int = 4000) -> list[str]:
    """Satu section = satu pesan; section panjang dipecah di dalam section itu."""
    messages = []
    for section in format_nikbyphone_sections(fields):
        messages.extend(_split_section(section, max_chars))
    return messages


def format_nikbyphone(fields: Any) -> str:
    """Render hasil NIK-by-phone sebagai satu string gabungan."""
    return "\n\n".join(format_nikbyphone_sections(fields))


def format_nik_sections(fields: Any) -> list[str]:
    """Render hasil NIK sesuai template output NIK."""
    return _render_nik_sections(fields)


def format_nik_messages(fields: Any, max_chars: int = 4000) -> list[str]:
    """Render hasil NIK sebagai pesan Telegram per section."""
    return [_chunk for section in format_nik_sections(fields) for _chunk in _split_section(section, max_chars)]


def format_nik(fields: Any) -> str:
    """Render hasil NIK sebagai satu string gabungan."""
    return "\n\n".join(format_nik_sections(fields))


def format_kk_sections(fields: Any) -> list[str]:
    """Render hasil KK sesuai template output kartu keluarga."""
    return _render_kk_sections(fields)


def format_kk_messages(fields: Any, max_chars: int = 4000) -> list[str]:
    """Render hasil KK sebagai pesan Telegram per section."""
    return [_chunk for section in format_kk_sections(fields) for _chunk in _split_section(section, max_chars)]


def format_kk(fields: Any) -> str:
    """Render hasil KK sebagai satu string gabungan."""
    return "\n\n".join(format_kk_sections(fields))


def format_track_sections(fields: Any) -> list[str]:
    """Render hasil tracking phone sesuai template output tracking."""
    return [_render_track(fields)]


def format_track_messages(fields: Any, max_chars: int = 4000) -> list[str]:
    """Render hasil tracking phone sebagai pesan Telegram."""
    return [_chunk for section in format_track_sections(fields)
            for _chunk in _split_section(section, max_chars)]


def format_track(fields: Any) -> str:
    """Render hasil tracking phone sebagai satu string gabungan."""
    return "\n\n".join(format_track_sections(fields))
