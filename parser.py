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
)

# Penanda bahwa provider tidak menemukan data.
NOT_FOUND_MARKERS = (
    "tidak ditemukan", "tidak tersedia", "data not found", "not found for",
    "image not found", "waktu tunggu habis",
)

DIVIDER_RE = re.compile(r"^[━\-─=_]{5,}$")
RECORD_HEADER_RE = re.compile(r"^(?:Data\s*(\d+)\.?|#(\d+))\s*(.*)$")
KV_RE = re.compile(r"^([A-Za-zÀ-ÿ0-9 /_.]{2,40}?)\s*:\s*(.*)$")
EMOJI_RE = re.compile(r"[\U0001F000-\U0001FFFF☀-➿←-⇿⬀-⯿]")

# Blok yang isinya cuma info pagination, bukan record data.
SUMMARY_ONLY = {"page", "total_tampil", "total", "halaman"}

# Baris peringatan hukum yang ditempel bot di tiap balasan.
DISCLAIMER_MARKERS = ("PENYALAH GUNAAN", "PROSES HUKUM")


def strip_emoji(s: str) -> str:
    return EMOJI_RE.sub("", s).strip()


def is_ack(text: str | None) -> bool:
    """True kalau pesan cuma ack antrian, bukan hasil."""
    t = (text or "").lower()
    return any(m in t for m in ACK_MARKERS)


def is_not_found(text: str | None) -> bool:
    t = (text or "").lower()
    return any(m in t for m in NOT_FOUND_MARKERS)


def _parse_kv_block(lines: list[str]) -> tuple[dict, list[str]]:
    fields, notes = {}, []
    for line in lines:
        line = line.strip()
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

    blocks: list[list[str]] = [[]]
    headers: list[str | None] = [None]
    for line in lines:
        stripped = line.strip()
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

    final = non_ack[-1]
    records, note = parse_reply(final)

    if records:
        fields = records[0] if len(records) == 1 else records
        return {"status": "found", "msg": note, "fields": fields}

    # Bot menjawab tapi tanpa data terstruktur: entah memang tidak ketemu,
    # entah balasan error/validasi ("/bpjs harus 16 digit"). Keduanya masuk
    # not_found supaya query berikutnya dicoba ulang, bukan dijawab dari cache.
    return {"status": "not_found", "msg": note or final, "fields": None}
