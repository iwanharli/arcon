"""Uji guard --force di healthcheck.py — tanpa DB/Telegram/psycopg.

Motif (King, 2026-09-23): penjadwalan otomatis harian pm2 (cron_restart, jam
02:00/03:00 WIB) yang hit bot sungguhan tiap hari DIHAPUS karena mengganggu.
Sekarang healthcheck.py HARUS keluar tanpa menyentuh apa pun kalau dipanggil
tanpa --force — supaya proses pm2 lama di VPS yang masih memanggilnya polos
berhenti hit bot begitu deploy berikutnya jalan, tanpa perlu masuk VPS untuk
menghapus job pm2 secara terpisah.

Pendekatan: baca source healthcheck.py sebagai teks dan pastikan struktur
guard-nya benar (posisi --force check SEBELUM jalankan()/laporan() dipanggil
untuk kasus default), bukan import modul (butuh psycopg yang tidak selalu
terpasang di lingkungan test ringan) — sama seperti prinsip pengujian di
ArtemisID untuk fungsi yang berat dependensinya.

Jalankan: pytest tests/test_healthcheck_guard.py
"""
from __future__ import annotations

import re
from pathlib import Path

SRC = (Path(__file__).parent.parent / "healthcheck.py").read_text()


def test_default_tanpa_argumen_keluar_tanpa_force():
    """Tanpa --report DAN tanpa --force, harus SystemExit(0) tanpa memanggil
    jalankan() (satu-satunya jalur yang menyentuh API/bot)."""
    blok_main = SRC[SRC.index('if __name__ == "__main__":'):]
    # "--force" not in args harus dicek SEBELUM baris yang memanggil jalankan(...)
    idx_cek_force = blok_main.index('"--force" not in args')
    idx_panggil_jalankan = blok_main.index("asyncio.run(jalankan(target))")
    assert idx_cek_force < idx_panggil_jalankan, (
        "pengecekan --force harus terjadi SEBELUM jalankan() dipanggil, supaya "
        "jalur default (tanpa argumen, seperti dipanggil pm2 cron_restart lama) "
        "tidak pernah menyentuh API/bot"
    )
    # Guard harus benar-benar keluar (SystemExit), bukan sekadar log lalu lanjut.
    segmen_guard = blok_main[idx_cek_force:idx_panggil_jalankan]
    assert "raise SystemExit(0)" in segmen_guard, \
        "guard harus SystemExit(0), bukan hanya warning lalu tetap jalan"


def test_report_tetap_bisa_tanpa_force():
    """--report tidak boleh kena guard --force (itu jalur baca-saja, tanpa hit bot)."""
    blok_main = SRC[SRC.index('if __name__ == "__main__":'):]
    idx_report = blok_main.index('"--report" in args')
    idx_cek_force = blok_main.index('"--force" not in args')
    assert idx_report < idx_cek_force, \
        "--report harus dicek dan boleh lolos SEBELUM guard --force"


def test_docstring_menyatakan_dihapus_bukan_dijadwalkan():
    """Docstring BOLEH menyebut cron_restart sebagai konteks historis ("dulu
    begini, sekarang dihapus"), tapi TIDAK BOLEH lagi mengklaim itu masih
    aktif ("Dijadwalkan lewat pm2 ... tiap hari") seperti sebelumnya."""
    docstring = SRC.split('"""')[1]
    assert "DIHAPUS" in docstring, "harus ada catatan eksplisit bahwa penjadwalan dihapus"
    assert not re.search(r"Dijadwalkan lewat pm2.*tiap hari", docstring), \
        "docstring tidak boleh lagi mengklaim ada penjadwalan pm2 aktif"


def test_force_dibuang_dari_args_sebelum_dipakai_sebagai_target_bot():
    """"--force" jangan sampai kebawa jadi nilai `target` (nama bot) di jalankan()."""
    blok_main = SRC[SRC.index('if __name__ == "__main__":'):]
    assert 'args = [a for a in args if a != "--force"]' in blok_main, \
        "--force harus disaring dari args sebelum dipakai sebagai target bot"
