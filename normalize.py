"""Normalisasi hasil parsing bot jadi bentuk kanonik sebelum masuk database.

Tiap bot memformat data yang sama dengan cara berbeda (alamat "RT 7/13" vs
"RT 7 RW 13", nama field "kab/kota" vs "kabupaten", nomor "0812..." vs
"62812..."). Modul ini menyeragamkannya supaya satu orang = satu baris di
tabel profiles, bukan dua baris yang beda format.
"""
from __future__ import annotations

import re
from datetime import date

# Placeholder yang artinya "tidak ada data", bukan nilai sebenarnya.
EMPTY_MARKERS = {"", "-", "--", "n/a", "null", "none", "tidak ada"}

# Nilai yang disensor bot, mis. "32••••••••••••05", "•••••••••••99", "KATIN**".
# Bot kadang mengirim mask dengan escape markdown ("KATIN\*\*"), jadi escape
# dibersihkan dulu sebelum dicek (lihat _unescape).
MASK_RE = re.compile(r"[•*x]{2,}", re.IGNORECASE)
MD_ESCAPE_RE = re.compile(r"\\([*_`~\[\]()])")

MARITAL_VALUES = {"KAWIN", "BELUM KAWIN", "CERAI HIDUP", "CERAI MATI", "JANDA", "DUDA"}

GENDER_MAP = {
    "L": "LAKI-LAKI", "P": "PEREMPUAN",
    "LAKI-LAKI": "LAKI-LAKI", "LAKI LAKI": "LAKI-LAKI", "PRIA": "LAKI-LAKI",
    "PEREMPUAN": "PEREMPUAN", "WANITA": "PEREMPUAN",
}

# Field yang bukan data (pagination, echo input ter-mask, link turunan).
DROP_KEYS = {"page", "total_tampil", "target", "maps"}

# Nama field mentah -> nama kolom kanonik.
FIELD_ALIASES = {
    "kab/kota": "kab_kota", "kabupaten": "kab_kota", "kota": "kab_kota",
    "kel/desa": "kel_desa", "kelurahan": "kel_desa", "desa": "kel_desa",
    "ayah": "nama_ayah",
    "ibu": "nama_ibu",
    "tempat_lahir": "tempat_lahir",
    "jk": "jenis_kelamin",
}

# Kolom yang diakui tabel profiles.
PROFILE_COLUMNS = {
    "nik", "kk", "shdk", "nama", "tempat_lahir", "tanggal_lahir", "jenis_kelamin",
    "status_kawin", "pekerjaan", "agama", "pendidikan", "alamat", "rt", "rw",
    "kel_desa", "kecamatan", "kab_kota", "provinsi",
    "nik_ayah", "nama_ayah", "nik_ibu", "nama_ibu",
}


# ---------------------------------------------------------------- primitives

def _unescape(value) -> str:
    """Buang escape markdown dari balasan bot: 'KATIN\\*\\*' -> 'KATIN**'."""
    return MD_ESCAPE_RE.sub(r"\1", str(value))


def is_masked(value) -> bool:
    """True kalau nilainya disensor bot (tidak boleh disimpan sebagai data)."""
    return bool(value) and bool(MASK_RE.search(_unescape(value)))


def clean(value, zero_is_empty: bool = False) -> str | None:
    """Rapikan string; kembalikan None untuk placeholder/nilai ter-mask."""
    if value is None:
        return None
    s = re.sub(r"\s+", " ", _unescape(value)).strip()
    if s.lower() in EMPTY_MARKERS:
        return None
    if zero_is_empty and s.strip("0") == "":
        return None
    if is_masked(s):
        return None
    return s


def norm_text(value) -> str | None:
    """Teks bebas -> UPPERCASE rapi (nama, alamat, wilayah)."""
    s = clean(value)
    return s.upper() if s else None


def norm_digits(value, length: int | None = None) -> str | None:
    """Ambil digitnya saja; tolak kalau panjangnya tidak sesuai."""
    s = clean(value, zero_is_empty=True)
    if not s:
        return None
    digits = re.sub(r"\D", "", s)
    if not digits or digits.strip("0") == "":
        return None
    if length is not None and len(digits) != length:
        return None
    return digits


def norm_nik(value) -> str | None:
    return norm_digits(value, length=16)


def norm_kk(value) -> str | None:
    return norm_digits(value, length=16)


def norm_msisdn(value) -> str | None:
    """Nomor HP -> format kanonik 62xxxxxxxxx."""
    s = clean(value)
    if not s:
        return None
    digits = re.sub(r"\D", "", s)
    if not digits:
        return None
    if digits.startswith("62"):
        pass
    elif digits.startswith("0"):
        digits = "62" + digits.lstrip("0")
    elif digits.startswith("8"):
        digits = "62" + digits
    if not (10 <= len(digits) <= 15):
        return None
    return digits


def norm_date(value) -> date | None:
    """'05/03/2006' atau '05-03-2006' (dd-mm-yyyy) -> date."""
    s = clean(value)
    if not s:
        return None
    m = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", s)
    if m:
        d, mo, y = (int(x) for x in m.groups())
    else:
        m = re.search(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", s)  # yyyy-mm-dd
        if not m:
            return None
        y, mo, d = (int(x) for x in m.groups())
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def norm_gender(value) -> str | None:
    s = clean(value)
    if not s:
        return None
    return GENDER_MAP.get(s.upper(), s.upper())


def norm_ttl(value) -> tuple[str | None, date | None]:
    """'BEKASI, 05/03/2006' -> ('BEKASI', date(2006, 3, 5))."""
    s = clean(value)
    if not s:
        return None, None
    tanggal = norm_date(s)
    tempat = re.split(r"[,;]", s)[0]
    tempat = re.sub(r"\d{1,2}[/-]\d{1,2}[/-]\d{4}", "", tempat)
    return norm_text(tempat), tanggal


def norm_address(value) -> tuple[str | None, str | None, str | None]:
    """Pisahkan RT/RW dari alamat supaya format antar-bot jadi seragam.

    'JL MELATI NO 4 RT 7/13'    -> ('JL MELATI NO 4', '7', '13')
    'JL MELATI NO 4 RT 7 RW 13' -> ('JL MELATI NO 4', '7', '13')
    """
    s = norm_text(value)
    if not s:
        return None, None, None

    rt = rw = None
    patterns = (
        r"\bRT[\s.:]*(\d{1,3})\s*[/\\]\s*(?:RW[\s.:]*)?(\d{1,3})\b",  # RT 7/13, RT 007/RW 013
        r"\bRT[\s.:]*(\d{1,3})\s+RW[\s.:]*(\d{1,3})\b",               # RT 7 RW 13
    )
    for pat in patterns:
        m = re.search(pat, s)
        if m:
            rt, rw = m.group(1), m.group(2)
            s = (s[:m.start()] + " " + s[m.end():])
            break
    else:
        m = re.search(r"\bRT[\s.:]*(\d{1,3})\b", s)
        if m:
            rt = m.group(1)
            s = s[:m.start()] + " " + s[m.end():]
        m = re.search(r"\bRW[\s.:]*(\d{1,3})\b", s)
        if m:
            rw = m.group(1)
            s = s[:m.start()] + " " + s[m.end():]

    alamat = re.sub(r"\s+", " ", s).strip(" ,.-") or None
    strip0 = lambda x: x.lstrip("0") or "0" if x else None  # noqa: E731
    return alamat, strip0(rt), strip0(rw)


def norm_money(value) -> int | None:
    """'Rp 26.169' -> 26169. Format Indonesia: '.' = pemisah ribuan.

    Kalau ada penanda 'Rp', hanya nominal setelahnya yang diambil supaya
    angka lain di kalimat yang sama (mis. 'Stand: 00012461-00012527') tidak
    ikut terbaca.
    """
    s = clean(value)
    if not s:
        return None
    m = re.search(r"Rp\.?\s*([\d.,]+)", s, re.IGNORECASE)
    token = m.group(1) if m else s
    digits = re.sub(r"[^\d]", "", token.split(",")[0])  # buang titik ribuan & sen
    return int(digits) if digits else None


def norm_bool(value) -> bool | None:
    """'No'/'Ya'/'Yes'/'Tidak' -> bool."""
    s = clean(value)
    if not s:
        return None
    low = s.lower()
    if low in ("ya", "yes", "y", "true", "1", "aktif", "active"):
        return True
    if low in ("tidak", "no", "n", "false", "0", "nonaktif", "inactive"):
        return False
    return None


def norm_pair(value) -> tuple[str | None, str | None]:
    """'510/10' -> ('510', '10'); dipakai untuk MCC/MNC dan LAC/CI."""
    s = clean(value)
    if not s or "/" not in s:
        return None, None
    left, _, right = s.partition("/")
    return clean(left), clean(right)


def norm_coordinate(value) -> tuple[float, float] | tuple[None, None]:
    """'-6.282954, 107.16658' -> (-6.282954, 107.16658)."""
    s = clean(value)
    if not s:
        return None, None
    m = re.search(r"(-?\d+\.?\d*)\s*,\s*(-?\d+\.?\d*)", s)
    if not m:
        return None, None
    try:
        return float(m.group(1)), float(m.group(2))
    except ValueError:
        return None, None


# ------------------------------------------------------------------ mappers

def normalize_person(raw: dict) -> dict:
    """Field mentah dari bot -> kolom kanonik tabel profiles.

    Key yang tidak dikenal diabaikan (lihat normalize_person_extra kalau
    butuh sisanya). Nilai kosong/ter-mask jadi None, bukan '-' atau ''.
    """
    if not raw:
        return {}

    out: dict = {}
    for key, value in raw.items():
        key = FIELD_ALIASES.get(key.lower(), key.lower())
        if key in DROP_KEYS:
            continue

        if key == "nik":
            out["nik"] = norm_nik(value)
        elif key == "kk":
            out["kk"] = norm_kk(value)
        elif key in ("nik_ayah", "nik_ibu"):
            out[key] = norm_nik(value)
        elif key == "ttl":
            tempat, tanggal = norm_ttl(value)
            out.setdefault("tempat_lahir", tempat)
            out.setdefault("tanggal_lahir", tanggal)
        elif key == "tanggal_lahir":
            out["tanggal_lahir"] = norm_date(value)
        elif key == "jenis_kelamin":
            out["jenis_kelamin"] = norm_gender(value)
        elif key == "alamat":
            alamat, rt, rw = norm_address(value)
            out["alamat"] = alamat
            if rt:
                out["rt"] = rt
            if rw:
                out["rw"] = rw
        elif key == "status":
            # 'status' ambigu: bisa status kawin, bisa status nomor HP.
            s = norm_text(value)
            if s in MARITAL_VALUES:
                out["status_kawin"] = s
        elif key == "status_kawin":
            out["status_kawin"] = norm_text(value)
        elif key in PROFILE_COLUMNS:
            out[key] = norm_text(value)

    return {k: v for k, v in out.items() if v is not None}


def normalize_phone(raw: dict) -> dict:
    """Field mentah -> baris tabel profile_phones (registrasi nomor HP)."""
    if not raw:
        return {}
    out = {
        "msisdn": norm_msisdn(raw.get("nomor") or raw.get("msisdn")),
        "operator": norm_text(raw.get("operator")),
        "registered_at": norm_date(raw.get("register")),
        "nik": norm_nik(raw.get("nik")),
        "pemilik": norm_text(raw.get("pemilik")),
    }
    return {k: v for k, v in out.items() if v is not None}


# Bulan Indonesia untuk key tagihan dinamis, mis. "september_2026".
BULAN = {
    "januari": 1, "februari": 2, "maret": 3, "april": 4, "mei": 5, "juni": 6,
    "juli": 7, "agustus": 8, "september": 9, "oktober": 10, "november": 11,
    "desember": 12,
}


def normalize_pln(raw: dict) -> dict:
    """Field mentah /pln -> record tagihan listrik.

    Key periode tagihan bersifat dinamis ('september_2026'), jadi dikumpulkan
    ke list `tagihan` alih-alih jadi kolom sendiri.
    """
    if not raw:
        return {}
    out = {
        "id_pelanggan": norm_digits(raw.get("id_pelanggan")),
        "nama": norm_text(raw.get("nama")),          # sering ter-mask -> None
        "daya": norm_text(raw.get("daya")),
        "tipe": norm_text(raw.get("type") or raw.get("tipe")),
        "total_tagihan": norm_money(raw.get("total_tagihan")),
        "biaya_admin": norm_money(raw.get("biaya_admin")),
        "total_bayar": norm_money(raw.get("total_bayar")),
    }

    tagihan = []
    for key, value in raw.items():
        m = re.fullmatch(r"([a-z]+)[_\s](\d{4})", key.lower())
        if not m or m.group(1) not in BULAN:
            continue
        detail = clean(value)
        if not detail:
            continue
        item = {
            "periode": f"{m.group(2)}-{BULAN[m.group(1)]:02d}",
            "jumlah": norm_money(detail),
        }
        stand = re.search(r"Stand:\s*([\d\-]+)", detail)
        if stand:
            item["stand"] = stand.group(1)
        jt = re.search(r"Jt:\s*(\d{4}-\d{2}-\d{2})", detail)
        if jt:
            item["jatuh_tempo"] = jt.group(1)
        tagihan.append(item)
    if tagihan:
        out["tagihan"] = sorted(tagihan, key=lambda x: x["periode"])

    return {k: v for k, v in out.items() if v is not None}


def normalize_device(raw: dict) -> dict:
    """Field mentah /track -> record perangkat & lokasi terakhir."""
    if not raw:
        return {}
    mcc, mnc = norm_pair(raw.get("mcc/mnc"))
    lac, ci = norm_pair(raw.get("lac/ci"))
    lat, lon = norm_coordinate(raw.get("coordinate"))
    out = {
        "msisdn": norm_msisdn(raw.get("msisdn")),   # sering ter-mask -> None
        "brand": norm_text(raw.get("brand")),
        "model": clean(raw.get("model")),           # jaga huruf asli: 'Galaxy Z Fold3 5G'
        "operator": norm_text(raw.get("operator")),
        "imei": norm_digits(raw.get("imei")),
        "imsi": norm_digits(raw.get("imsi")),
        "roaming": norm_bool(raw.get("roaming")),
        "network": norm_text(raw.get("network")),
        "mcc": mcc, "mnc": mnc, "lac": lac, "ci": ci,
        "cid": clean(raw.get("cid")),
        "cluster": norm_text(raw.get("cluster")),
        "district": norm_text(raw.get("district")),
        "latitude": lat, "longitude": lon,
        "status": norm_text(raw.get("status")),
        "pesan": clean(raw.get("pesan")),
    }
    return {k: v for k, v in out.items() if v is not None}


def normalize_number_info(raw: dict) -> dict:
    """Field mentah /cekinfo -> record status & masa aktif nomor."""
    if not raw:
        return {}
    out = {
        "msisdn": norm_msisdn(raw.get("nomor") or raw.get("msisdn")),
        "registrasi": norm_text(raw.get("registrasi")),
        "area_jaringan": norm_text(raw.get("area_jaringan")),
        "status_perangkat": norm_text(raw.get("status_perangkat")),
        "aktif_hingga": norm_date(raw.get("aktif_hingga")),
        "sisa_masa_aktif": clean(raw.get("sisa_masa_aktif")),
        "sisa_masa_tenggang": clean(raw.get("sisa_masa_tenggang")),
    }
    return {k: v for k, v in out.items() if v is not None}


def normalize_vehicle(raw: dict) -> dict:
    """Field mentah /tnkb, /nosin, /noka -> baris tabel profile_vehicles.

    Catatan: semua percobaan uji mengembalikan 'tidak ditemukan', jadi nama
    field aslinya belum terverifikasi; alias di bawah masih perlu dicek ulang
    begitu ada balasan berisi data.
    """
    if not raw:
        return {}
    out = {
        "nopol": norm_text(raw.get("nopol") or raw.get("no_polisi") or raw.get("tnkb")),
        "nomor_mesin": norm_text(raw.get("nomor_mesin") or raw.get("no_mesin") or raw.get("nosin")),
        "nomor_rangka": norm_text(raw.get("nomor_rangka") or raw.get("no_rangka") or raw.get("noka")),
        "merk": norm_text(raw.get("merk") or raw.get("merek")),
        "tipe": norm_text(raw.get("tipe") or raw.get("type")),
        "tahun": norm_digits(raw.get("tahun")),
        "warna": norm_text(raw.get("warna")),
        "pemilik": norm_text(raw.get("pemilik") or raw.get("nama")),
        "alamat": norm_text(raw.get("alamat")),
    }
    return {k: v for k, v in out.items() if v is not None}
