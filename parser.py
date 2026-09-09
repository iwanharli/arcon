"""Ubah teks balasan bot jadi struktur data + tentukan statusnya.

Bot membalas teks bebas dengan beberapa gaya berbeda:

    Nama: BUDI SANTOSO          <- pasangan key: value
    NIK: 3201010101010001

    Data 1. SITI RAHAYU    <- banyak record, dipisah "Data N." / "#N"
    ━━━━━━━━━━━━━━━━━             (kadang pakai garis pemisah, kadang tidak)
    Data 2. AGUS WIJAYA

Modul ini menyeragamkannya jadi list/dict, lalu mengklasifikasikan hasilnya ke
salah satu dari 4 status yang dipakai db_artemis.
"""
from __future__ import annotations

import re

# Pesan "sedang diproses" — bukan hasil, cuma tanda masuk antrian.
ACK_MARKERS = (
    "giliran anda", "sistem sedang sibuk", "processing your request",
    "request diterima", "sedang diproses", "mohon tunggu",
    # teamkhususantibanditbot mengirim progress bar sebagai pesan TERPISAH
    # ("T•E•K•A•B REBORN\n[░░░░░░░░░░] 0%"). Tanpa ditandai ack, wait_final
    # berhenti di bar itu dan menganggapnya jawaban.
    "░", "█",
    # ...dan beberapa fitur mengirim pesan progres berbentuk kalimat sebelum
    # hasilnya. Terbukti pada /hukum ("⏳ Mencari data peraturan untuk kata
    # kunci ...") dan /pddikti ("🔍 Sedang mencari data PDDIKTI dengan kata
    # kunci: ..."): keduanya tersimpan sebagai not_found padahal hasil aslinya
    # menyusul beberapa detik kemudian.
    "mencari data", "sedang mencari", "sedang memuat", "memuat ",
    "⏳", "sedang menganalisis", "harap tunggu",
)

# Kuota/limit habis — BUKAN "data tidak ada". Balasannya harus dianggap
# sementara supaya bisa dicoba lagi besok, bukan dicatat not_found yang
# membuat healthcheck menyimpulkan fiturnya rusak. Terbukti pada bulk run
# 9 Sep 2026: 38 dari 55 not_found sebenarnya "Batas Penggunaan Tercapai".
LIMIT_MARKERS = (
    "batas penggunaan tercapai", "batas penggunaan harian",
    "limit tercapai", "kuota anda habis", "quota exceeded",
    "coba lagi besok",
)


# Bot memantulkan balik pesan kita ("You said: 3275...") kalau ia TIDAK sedang
# menunggu input — artinya alur menunya gagal dan nilai kita jatuh ke ruang
# kosong. Dulu ini tersimpan sebagai found dengan field {you_said: ...} dan
# terkunci di cache; padahal tidak ada data sama sekali dan harus diulang.
ECHO_RE = re.compile(r"^\s*you\s+said\s*:", re.IGNORECASE)


def is_echo(text: str | None) -> bool:
    """True kalau bot cuma memantulkan pesan kita, bukan menjawab."""
    return bool(ECHO_RE.match(text or ""))


def is_limited(text: str | None) -> bool:
    """True kalau bot menolak karena kuota/limit, bukan karena data tidak ada."""
    t = (text or "").lower()
    return any(m in t for m in LIMIT_MARKERS)


# Penanda bahwa provider tidak menemukan data.
NOT_FOUND_MARKERS = (
    "tidak ditemukan", "tidak tersedia", "data not found", "not found for",
    "image not found", "waktu tunggu habis",
)

DIVIDER_RE = re.compile(r"^[━\-─=_]{5,}$")
RECORD_HEADER_RE = re.compile(r"^(?:Data\s*(\d+)\.?|#(\d+))\s*(.*)$")

# teamkhususantibanditbot memberi nomor hasil dengan gaya polos "1. Judul",
# bukan "Data 1." atau "#1". Tanpa ini seluruh daftar hasil dianggap SATU
# record: /bpom mengembalikan 5 produk berdetail dalam satu pesan, dan hanya
# produk pertama yang tersimpan.
#
# Nomor polos terlalu umum untuk dipakai begitu saja (baris biasa bisa diawali
# "1. "), jadi baru diperlakukan sebagai header kalau dalam satu pesan ada
# MINIMAL DUA nomor berurutan yang masing-masing diikuti pasangan key:value.
NUMBERED_HEADER_RE = re.compile(r"^(\d{1,3})[.)]\s+(\S.*)$")
KV_RE = re.compile(r"^([A-Za-zÀ-ÿ0-9 /_.]{2,40}?)\s*:\s*(.*)$")
EMOJI_RE = re.compile(r"[\U0001F000-\U0001FFFF☀-➿←-⇿⬀-⯿]")

# Blok yang isinya cuma info pagination, bukan record data.
SUMMARY_ONLY = {
    "page", "total_tampil", "total", "halaman",
    # blok ringkasan di atas daftar hasil bot baru:
    # "Keyword: Indomie / Total ditemukan: 1,412 hasil / Menampilkan: 1-5"
    "keyword", "kata_kunci", "total_ditemukan", "total_hasil", "menampilkan",
    "filter", "ditemukan", "sumber", "jumlah_hasil",
}

# Baris peringatan hukum yang ditempel bot di tiap balasan.
DISCLAIMER_MARKERS = ("PENYALAH GUNAAN", "PROSES HUKUM")

# teamkhususantibanditbot mengirim peringatan hukum sebagai pesan TERPISAH
# sebelum hasilnya. Pesan itu bukan ack antrian dan bukan hasil, jadi kalau
# tidak dikenali, wait_final berhenti di situ dan hasil aslinya — yang datang
# beberapa detik kemudian — terbuang. Terbukti pada /ip: disclaimer tersimpan
# sebagai not_found, padahal hasil CEKPOS IP 3380 karakter menyusul.
PREAMBLE_MARKERS = (
    "data bersifat sangat rahasia",
    "penyelidikan dan penyidikan",
    "dokumen ini disusun khusus",
    "wajib menjaga kerahasiaan",
)


def is_preamble(text: str | None) -> bool:
    """True kalau pesan ini cuma peringatan hukum pengantar, bukan hasil.

    Disclaimer yang MENEMPEL di pesan hasil tidak boleh kena: karena itu
    pesan yang juga memuat data (pasangan key: value atau header "Hasil")
    tetap dianggap hasil.
    """
    t = (text or "").lower()
    if not any(m in t for m in PREAMBLE_MARKERS):
        return False
    isi = [l for l in (text or "").splitlines()
           if KV_RE.match(bersihkan_baris(l))]
    return not isi and "hasil" not in t


def strip_emoji(s: str) -> str:
    return EMOJI_RE.sub("", s).strip()


def is_ack(text: str | None) -> bool:
    """True kalau pesan cuma ack antrian, bukan hasil."""
    t = (text or "").lower()
    return any(m in t for m in ACK_MARKERS)


def is_not_found(text: str | None) -> bool:
    t = (text or "").lower()
    return any(m in t for m in NOT_FOUND_MARKERS)


# teamkhususantibanditbot memformat hasil bergaya pohon + markdown:
#     **Hasil CEKPOS IP untuk: ****detik.com**
#     ├ **Type:** IPv4
#     │  • PT. Detik Ini Juga
#     └ **ISP:** PT. Detik Ini Juga
# KV_RE hanya menerima "Key: value" polos, jadi tanpa pembersihan ini seluruh
# balasan bot baru terbaca sebagai teks bebas dan statusnya jatuh ke
# not_found — terbukti pada /ip yang hasilnya 3380 karakter tapi 0 field.
PREFIX_RE = re.compile(r"^[\s├│└┌┐┘─┤┬┴┼•▪▫◦♦♢·*\-–—>]+")
BOLD_RE = re.compile(r"\*\*|__|`")


def bersihkan_baris(line: str) -> str:
    """Buang gambar pohon, bullet, dan penanda markdown dari satu baris."""
    line = BOLD_RE.sub("", line)
    line = PREFIX_RE.sub("", line)
    return line.strip()


def _parse_kv_block(lines: list[str]) -> tuple[dict, list[str]]:
    fields, notes = {}, []
    for line in lines:
        line = bersihkan_baris(line)
        if not line:
            continue
        m = KV_RE.match(line)
        if m:
            key = strip_emoji(m.group(1)).strip().lower().replace(" ", "_")
            if key:
                fields[key] = m.group(2).strip()
                continue
        notes.append(line)
    return fields, notes


def parse_reply(text: str | None) -> tuple[list[dict], str | None]:
    """Teks balasan -> (list record, catatan teks bebas).

    Satu record = satu blok pasangan key:value. Blok baru dimulai oleh garis
    pemisah ATAU header "Data N."/"#N" — keduanya perlu ditangani karena tiap
    bot memakai gaya yang berbeda.
    """
    if not text:
        return [], None

    lines, disclaimer = [], None
    for line in text.split("\n"):
        if any(m in line for m in DISCLAIMER_MARKERS):
            disclaimer = line.strip()
            continue
        lines.append(line)

    # Deteksi gaya penomoran polos "1. Judul" (lihat NUMBERED_HEADER_RE).
    bernomor = [m.group(1) for m in
                (NUMBERED_HEADER_RE.match(bersihkan_baris(l)) for l in lines) if m]
    pakai_nomor = len(bernomor) >= 2

    blocks: list[list[str]] = [[]]
    headers: list[str | None] = [None]
    for line in lines:
        stripped = bersihkan_baris(line)
        if not stripped:
            continue
        if DIVIDER_RE.match(stripped):
            blocks.append([])
            headers.append(None)
            continue
        m = RECORD_HEADER_RE.match(stripped)
        if m:
            if blocks[-1]:          # blok sekarang sudah terisi -> record baru
                blocks.append([])
                headers.append(None)
            headers[-1] = strip_emoji(m.group(3)) or None
            continue
        if pakai_nomor:
            m = NUMBERED_HEADER_RE.match(stripped)
            if m and not KV_RE.match(stripped):
                if blocks[-1]:
                    blocks.append([])
                    headers.append(None)
                headers[-1] = strip_emoji(m.group(2)) or None
                continue
        blocks[-1].append(line)

    records, notes = [], []
    for i, block in enumerate(blocks):
        fields, block_notes = _parse_kv_block(block)
        notes.extend(block_notes)
        if not fields or set(fields) <= SUMMARY_ONLY:
            continue
        if headers[i]:
            fields.setdefault("nama", headers[i])
        records.append(fields)

    note_text = "\n".join(n for n in notes if len(strip_emoji(n)) > 1) or None
    if not records and not note_text:
        note_text = text.strip()
    if disclaimer and not records:
        note_text = f"{note_text}\n{disclaimer}" if note_text else disclaimer

    return records, note_text


def classify(replies: list[str]) -> dict:
    """Kumpulan pesan balasan -> {status, msg, fields} siap disimpan.

    Status:
      found              - ada data terstruktur
      not_found          - bot menjawab tapi datanya tidak ada
      queue_without_data - cuma dapat ack antrian, hasil final belum datang
      no_response        - tidak ada balasan sama sekali
    """
    texts = [t for t in replies if t]
    if not texts:
        return {"status": "no_response", "msg": None, "fields": None}

    non_ack = [t for t in texts if not is_ack(t)]
    if not non_ack:
        return {"status": "queue_without_data", "msg": texts[-1], "fields": None}

    final = non_ack[-1]     # dipakai sebagai pesan fallback saat tidak ada data

    # Limit harian dicek sebelum apa pun: balasannya sering tetap berisi
    # pasangan key:value sehingga bisa lolos jadi found/not_found.
    if any(is_limited(t) for t in non_ack):
        batas = next(t for t in non_ack if is_limited(t))
        return {"status": "queue_without_data", "msg": batas, "fields": None}

    if all(is_echo(t) for t in non_ack):
        return {"status": "queue_without_data",
                "msg": "bot memantulkan input (alur menu tidak aktif)",
                "fields": None}

    # Gabungkan SEMUA pesan hasil, bukan cuma yang terakhir: satu permintaan
    # bisa dijawab beberapa pesan (halaman berikutnya dari daftar berpaginasi,
    # atau jawaban yang dipecah bot). Dulu hanya non_ack[-1] yang diurai,
    # sehingga halaman pertama tertimpa halaman terakhir.
    records, catatan = [], []
    for teks in non_ack:
        rec, note = parse_reply(teks)
        # record identik antar halaman (mis. blok ringkasan) tidak digandakan
        for r in rec:
            if r not in records:
                records.append(r)
        if note:
            catatan.append(note)
    note = "\n".join(dict.fromkeys(catatan)) or None

    # Balasan "tidak ditemukan" sering tetap menggemakan input sebagai pasangan
    # key:value ("Kata Kunci: UUD 1945"), sehingga records TIDAK kosong dan
    # dulu tercatat found. Penanda not-found yang muncul di teks bebas (bukan
    # di baris key:value) harus menang — terbukti pada /hukum yang menjawab
    # "Tidak ditemukan hasil." tapi tersimpan sebagai found.
    tidak_ada = bool(note) and any(m in note.lower() for m in NOT_FOUND_MARKERS)

    if records and not tidak_ada:
        fields = records[0] if len(records) == 1 else records
        return {"status": "found", "msg": note, "fields": fields}

    # Bot menjawab tapi tanpa data terstruktur: entah memang tidak ketemu,
    # entah balasan error/validasi ("/bpjs harus 16 digit"). Keduanya masuk
    # not_found supaya query berikutnya dicoba ulang, bukan dijawab dari cache.
    return {"status": "not_found", "msg": note or final, "fields": None}
