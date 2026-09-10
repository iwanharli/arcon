"""Batas halaman per command (env HALAMAN_MAKS_CMD).

Latar: bot memotong daftar hasil ("Ditemukan: **17** data | Halaman 1/5").
Tanpa mengikuti tombol Next, hanya halaman pertama yang masuk cache — blok
IMIGRASI pada `/nik` berhenti di 4 dari 17 record. `HALAMAN_MAKS` global
berguna, tapi menarik 5 halaman untuk SEMUA command memakan kuota fitur yang
kuotanya dihitung per hari, jadi disediakan peta per command.
"""

import importlib

import service


def _muat(monkeypatch, **env):
    """Impor ulang service dengan env yang diinginkan."""
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    modul = importlib.reload(service)
    return modul


def test_default_mati(monkeypatch):
    """Tanpa env apa pun: hanya halaman pertama (perilaku lama)."""
    monkeypatch.delenv("HALAMAN_MAKS", raising=False)
    monkeypatch.delenv("HALAMAN_MAKS_CMD", raising=False)
    s = _muat(monkeypatch)
    assert s.batas_halaman("/nik") == 0
    assert s.batas_halaman("imigrasi") == 0


def test_global_berlaku_semua_command(monkeypatch):
    s = _muat(monkeypatch, HALAMAN_MAKS="2", HALAMAN_MAKS_CMD="")
    assert s.batas_halaman("/bpom") == 2
    assert s.batas_halaman("/nik") == 2


def test_peta_per_command_menang_atas_global(monkeypatch):
    s = _muat(monkeypatch, HALAMAN_MAKS="1", HALAMAN_MAKS_CMD="nik=4,imigrasi=4")
    assert s.batas_halaman("/nik") == 4        # dari peta
    assert s.batas_halaman("imigrasi") == 4    # tanpa garis miring pun cocok
    assert s.batas_halaman("/IMIGRASI") == 4   # huruf besar/kecil sama saja
    assert s.batas_halaman("/kk") == 1         # jatuh ke global


def test_peta_tanpa_global_cuma_command_terdaftar(monkeypatch):
    s = _muat(monkeypatch, HALAMAN_MAKS="0", HALAMAN_MAKS_CMD=" nik = 4 ")
    assert s.batas_halaman("/nik") == 4
    assert s.batas_halaman("/kk") == 0


def test_nilai_ngawur_diabaikan(monkeypatch):
    """Env rusak tidak boleh membuat proses gagal jalan saat start."""
    s = _muat(monkeypatch, HALAMAN_MAKS_CMD="nik=,=3,kk=-2,xx=banyak, ,nik=4")
    assert s.batas_halaman("/nik") == 4        # entri sah terakhir dipakai
    assert s.batas_halaman("/kk") == 0         # -2 ditolak
    assert s.batas_halaman("/xx") == 0         # non-angka ditolak
