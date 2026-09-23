"""Formatter khusus untuk hasil command Telegram ``/tnkb``."""
from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any


_EMPTY = (None, "", "-")
_SECRET_KEYS = {"salt", "kata_sandi_terenkripsi"}
_CODE_KEYS = {"nik", "no_bpkb", "no_mesin", "no_rangka"}
_RECORD_SEPARATOR = "--------"
_LABELS = {
    "no_bpkb": "No. BPKB",
    "no_mesin": "No. Mesin",
    "no_rangka": "No. Rangka",
}


def _present(value: Any) -> bool:
    return value not in _EMPTY


def _text(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value).strip()


def _label(key: str) -> str:
    return _LABELS.get(key, re.sub(r"\s+", " ", key.replace("_", " ")).strip().title())


def _plain_line(label: str, value: Any, *, code: bool = False) -> str:
    shown = _text(value)
    if code:
        shown = f"`{shown}`"
    return f"{label}: {shown}"


def _records(fields: Any) -> list[dict[str, Any]]:
    values = fields if isinstance(fields, list) else [fields]
    return [dict(value) for value in values if isinstance(value, Mapping)]


def _split_section(section: str, max_chars: int) -> list[str]:
    if len(section) <= max_chars:
        return [section]
    chunks, current = [], ""
    for line in section.splitlines():
        candidate = line if not current else f"{current}\n{line}"
        if current and len(candidate) > max_chars:
            chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def _lines(record: Mapping[str, Any]) -> list[str]:
    lines = []
    used = set()

    prioritized = (
        ("NO. POL", ("nopol", "no_pol", "nomor_polisi", "no_polisi", "tnkb", "bagian", "nama")),
        ("Pemilik", ("pemilik",)),
    )
    for label, keys in prioritized:
        key = next((candidate for candidate in keys if _present(record.get(candidate))), None)
        if key:
            value = record[key]
            if key == "bagian":
                # Parser stores numbered record headers such as "1. B1172TUC"
                # in `bagian`; for vehicle results that header is the plate.
                value = re.sub(r"^\s*\d+[.)]\s*", "", _text(value))
            lines.append(_plain_line(label, value))
            used.update(keys)

    nik = record.get("nik")
    if _present(nik):
        digits = re.sub(r"\D", "", _text(nik))
        label = "NIB" if len(digits) == 13 else "NIK"
        lines.append(_plain_line(label, nik, code=True))
        used.add("nik")

    for key, value in record.items():
        if key in used or key == "bagian" or key in _SECRET_KEYS or not _present(value):
            continue
        lines.append(_plain_line(_label(key), value, code=key in _CODE_KEYS))
    return lines


def _vehicle_block(record: Mapping[str, Any]) -> str:
    body = "\n".join(_lines(record)) or "Data kendaraan belum tersedia."
    return f"{_RECORD_SEPARATOR}\n{body}\n{_RECORD_SEPARATOR}"


def _is_vehicle_record(record: Mapping[str, Any]) -> bool:
    """Identify the vehicle portion of a long personal `/tnkb` response."""
    owner_row = {"nik", "nama", "pemilik"}.issubset(record)
    vehicle_fields = {
        "merk", "tipe", "tahun", "warna", "no_bpkb", "no_stnk",
        "no_mesin", "no_rangka",
    }
    return owner_row or bool(vehicle_fields.intersection(record))


def _vehicle_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep only the leading vehicle records from a personal response."""
    selected = []
    for record in records:
        if not _is_vehicle_record(record):
            break
        selected.append(record)
    return selected


def format_tnkb_sections(fields: Any) -> list[str]:
    """Render data kendaraan sebagai pasangan key-value sederhana."""
    records = _records(fields)
    if not records:
        return ["*DATA KENDARAAN*\n\nData kendaraan belum tersedia."]

    if isinstance(fields, list):
        records = _vehicle_records(records)
        if not records:
            return ["*DATA KENDARAAN*\n\nData kendaraan belum tersedia."]

        first = _vehicle_block(records[0])
        if len(records) > 1:
            loop = "\n\n".join(
                _vehicle_block(record)
                for record in records[1:]
            )
            first = f"{first}\n\n*DAFTAR KENDARAAN*\n\n{loop}"
        return [f"*DATA KENDARAAN*\n\n{first}"]

    sections = []
    for number, record in enumerate(records, 1):
        title = "DATA KENDARAAN" if len(records) == 1 else f"DATA KENDARAAN {number}"
        lines = _lines(record)
        body = "\n".join(lines) or "Data kendaraan belum tersedia."
        sections.append(f"*{title}*\n\n{body}")
    return sections


def format_tnkb_messages(fields: Any, max_chars: int = 4000) -> list[str]:
    """Render data kendaraan sebagai pesan Telegram yang mudah dibaca."""
    return [_chunk for section in format_tnkb_sections(fields)
            for _chunk in _split_section(section, max_chars)]


def format_tnkb(fields: Any) -> str:
    """Render data kendaraan sebagai satu string gabungan."""
    return "\n\n".join(format_tnkb_sections(fields))
