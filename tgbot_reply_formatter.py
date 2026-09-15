"""Formatter balasan Telegram untuk command ``/nikbyphone``."""
from __future__ import annotations

import json
import re
from collections.abc import Mapping
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
    return "\n".join(f"{key.title()}: {values[key]}" for key in ("PROV", "KAB", "KEC", "KEL")
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


def _render_a_phone(records: list[dict[str, Any]], used: set[int]) -> str:
    registration = _take(records, used, lambda r: r.get("nama") == "REGISTRASI REAL-TIME") or {}
    detail = _take(
        records, used,
        lambda r: not r.get("nama") and {"nomor", "whatsapp"}.issubset(r),
    ) or {}

    lines = []
    for label, key, code in (
        ("Nomor", "nomor", True),
        ("Provider", "provider", False),
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
        if _present(detail.get("cek_update_manual")):
            lines.append(_plain_line("Link", _url(detail["cek_update_manual"])))
    body = _block("REGISTRASI REAL-TIME", lines, emoji="🔥")
    return _section("📱 *INFORMASI TELEPON*", body)


def _render_b_identity(records: list[dict[str, Any]], used: set[int]) -> str:
    profile = _take(records, used, lambda r: {"nik", "nama_lengkap", "alamat"}.issubset(r)) or {}
    if not profile:
        return ""

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
        lines.extend(["", "🗺️ Maps:", _url(profile["google_maps"])])
    wilayah = _wilayah(profile.get("nomor_wilayah"))
    if wilayah:
        lines.extend(["", "📍 *Kode Wilayah*", wilayah])

    blocks = ["\n".join(lines)] if lines else []

    name_only = []
    for _ in range(2):
        found = _take(
            records, used,
            lambda r: set(r) <= {"nama", "nik"} and r.get("nama") not in {"AKTA", "LAINNYA"}
            and not re.fullmatch(r"\d+\.", _text(r.get("nama", ""))),
        )
        if found:
            name_only.append(found)
    fallback = (_parent(family_head.get("ayah")), _parent(family_head.get("ibu")))
    for index, title in enumerate(("Ayah", "Ibu")):
        if index < len(name_only):
            name, nik = _text(name_only[index].get("nama", "")), name_only[index].get("nik")
        else:
            name, nik = fallback[index]
        lines = [_plain_line("Nama", name)] if name else []
        if _present(nik) and _text(nik) != "N/A":
            lines.append(_plain_line("NIK", nik, code=True))
        if lines:
            blocks.append(_block(title, lines, emoji="👨" if title == "Ayah" else "👩"))

    lainnya = _take(records, used, lambda r: r.get("nama") == "LAINNYA")
    if lainnya:
        other_lines = []
        for label, key in (("Pendidikan", "pendidikan"), ("Pekerjaan", "pekerjaan"),
                           ("Gol. Darah", "gol._darah"), ("Disabilitas", "penyandang_cacat")):
            if _present(lainnya.get(key)):
                other_lines.append(_plain_line(label, lainnya[key]))
        blocks.append(_block("Informasi Lain", other_lines, emoji="📋"))

    akta = _take(records, used, lambda r: r.get("nama") == "AKTA")
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
        if _present(record.get("cek_update_manual")):
            lines.append(_plain_line("Link", _url(record["cek_update_manual"])))
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
            "status_pbi_jk", "periode_pbi_jk", "status_bansos", "keterangan_bansos"}
    record = _take(records, used, lambda r: bool(keys.intersection(r)))
    if not record:
        return ""
    lines = []
    if _present(record.get("nama_lengkap")):
        lines.append(_plain_line("Nama", record["nama_lengkap"], bold=True))
    for label, key in (("Desil", "desil"), ("Sembako", "status_sembako"),
                       ("Periode", "periode_sembako"), ("PKH", "status_pkh"),
                       ("Periode", "periode_pkh"), ("PBI-JK", "status_pbi_jk"),
                       ("Periode", "periode_pbi_jk"), ("Status", "status_bansos"),
                       ("Keterangan", "keterangan_bansos")):
        if _present(record.get(key)):
            lines.append(_plain_line(label, record[key]))
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
    if not candidates:
        return ""
    profile = next((record for record in records if "nama_lengkap" in record and "nik" in record), {})
    family_head = next((record for record in records if {"status_hubungan", "ayah", "ibu"}.issubset(record)), {})
    lainnya = next((record for record in records if record.get("nama") == "LAINNYA"), {})
    lines = []
    for label, value, code, bold in (
        ("Nama", profile.get("nama_lengkap"), False, True), ("NIK", profile.get("nik"), True, False),
        ("No. KTP", profile.get("no_ktp"), True, False), ("No. KK", profile.get("nomor_kk"), True, False),
        ("Jenis Kelamin", profile.get("jenis_kelamin"), False, False),
        ("Tempat Lahir", profile.get("tempat_lahir"), False, False),
        ("Tanggal Lahir", _comparison_value(records, "TANGGAL LAHIR") or profile.get("tanggal_lahir"), False, False),
        ("Gol. Darah", lainnya.get("gol._darah"), False, False),
        ("Agama", profile.get("agama"), False, False),
        ("Status Kawin", _comparison_value(records, "STATUS KAWIN") or profile.get("status_kawin"), False, False),
    ):
        if _present(value):
            lines.append(_plain_line(label, value, code=code, bold=bold))
    pendidikan = profile.get("pendidikan") or lainnya.get("pendidikan")
    pekerjaan = _comparison_value(records, "PEKERJAAN") or lainnya.get("pekerjaan")
    if _present(pendidikan):
        lines.extend(["", _plain_line("Pendidikan", pendidikan)])
    if _present(pekerjaan):
        lines.append(_plain_line("Pekerjaan", pekerjaan))
    for label, key in (("Ayah", "ayah"), ("Ibu", "ibu")):
        value, _ = _parent(family_head.get(key))
        if value:
            lines.append(_plain_line(label, value))

    wilayah = []
    for label, key in (("Provinsi", "provinsi"), ("Kabupaten", "kabupaten"),
                       ("Kecamatan", "kecamatan"), ("Kelurahan", "kelurahan")):
        if _present(profile.get(key)):
            wilayah.append(_plain_line(label, profile[key]))
    if wilayah:
        lines.extend(["", "📍 *Wilayah*", *wilayah])

    administrasi = []
    for label, key in (("Akta Lahir", "no._akta_lahir"), ("Akta Kawin", "no._akta_kawin"),
                       ("Akta Cerai", "no._akta_cerai")):
        akta = next((record for record in records if record.get("nama") == "AKTA"), {})
        if _present(akta.get(key)):
            administrasi.append(_plain_line(label, akta[key]))
    if _present(profile.get("status_hubungan")):
        administrasi.append(_plain_line("Status Keluarga", profile["status_hubungan"]))
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
