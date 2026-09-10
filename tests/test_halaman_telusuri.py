"""Penelusuran halaman tombol Next + penggabungan record dari semua halaman.

Latar: bot memotong daftar hasil ("Ditemukan: **17** data | Halaman 1/5",
tombol "📄 2/5"). `HALAMAN_MAKS_CMD=nik=4` membuat service memanggil
`telusuri_halaman()`; tanpa itu cache berhenti di halaman pertama (4 dari 17
record IMIGRASI) — dan kartu di aplikasi menampilkan 4 seolah itu datanya.

Uji ini tidak menyentuh Telegram: klien dan pesan dipalsukan, sedangkan kode
yang diuji asli (`TelegramConnector.telusuri_halaman`, `_tombol_next`,
`parser.classify`). Isi record SINTETIS; yang diuji jumlah halaman + record.
"""

import asyncio

from connector import TelegramConnector
from parser import classify


class Tombol:
    def __init__(self, text, data):
        self.text = text
        self.data = data


class Baris:
    def __init__(self, *tombol):
        self.buttons = list(tombol)


class Markup:
    def __init__(self, *baris):
        self.rows = list(baris)


class Pesan:
    """Pesan palsu: klik() menaikkan nomor halaman yang sedang ditampilkan."""

    def __init__(self, teks, markup=None, kursor=None):
        self.text = teks
        self.reply_markup = markup
        self._kursor = kursor if kursor is not None else {}

    async def click(self, _baris, _kolom):
        self._kursor["klik"] = self._kursor.get("klik", 0) + 1


def _record(n, waktu, jenis):
    kunci = "Tanggal Kedatangan" if jenis.startswith("Kedatangan") else "Tanggal Keberangkatan"
    tujuan = "Tujuan Kedatangan" if jenis.startswith("Kedatangan") else "Tujuan Keberangkatan"
    return "\n".join([
        f"**#{n}**",
        "**Nama Depan:** CONTOH SUBJEK",
        "**Nama Belakang:** N/A",
        "**Tempat Pemeriksaan:** BANDARA SOEKARNO-HATTA",
        "**Nomor Paspor:** X0000000",
        "**Kewarganegaraan:** INDONESIA",
        f"**Jenis Perjalanan:** {jenis}",
        "**Tanggal Lahir:** 1987-03-07",
        f"**{tujuan}:** SINGAPORE CHANGI APT SINGAPORE",
        f"**{kunci}:** {waktu}",
    ])


def _halaman(n, jumlah, awal):
    baris = [
        "**IMIGRASI** — DATA PENDUKUNG",
        "━━━━━━━━━━━━━━━━━━━━━━━━",
        "**Keyword (NIK):** `3216010101900001`",
        f"Ditemukan: **17** data | Halaman {n}/5",
    ]
    for i in range(jumlah):
        jenis = "Kedatangan (Arrival)" if i % 2 == 0 else "Keberangkatan (Departure)"
        baris.append(_record(awal + i, f"20{30 - awal - i:02d}-01-0{i % 9 + 1} / 1{i}:00:00", jenis))
    return "\n".join(baris)


class TgPalsu(TelegramConnector):
    """Ganti `_tunggu` + klien: tiap klik menampilkan halaman berikutnya."""

    def __init__(self, halaman):
        self.halaman = halaman
        self.kursor = {"klik": 0}
        self.client = self

    async def get_entity(self, _nama):        # dipakai telusuri_halaman
        return self

    @property
    def id(self):                             # dibaca _tunggu asli
        return 1

    async def _tunggu(self, entity, cocok, timeout, ikut_edit=True, aksi=None):
        assert ikut_edit, "halaman bot datang sebagai pesan yang DIEDIT"
        await aksi()
        n = self.kursor["klik"]                        # halaman 2 = klik pertama
        if n >= len(self.halaman):
            return []                                  # sudah halaman terakhir
        berikut = n + 2                                # halaman berikutnya
        pesan = [_pesan_dengan_tombol(
            self.halaman[n], berikut, akhir=berikut > len(self.halaman),
            kursor=self.kursor)]
        return [m for m in pesan if cocok(m)]


def _pesan_dengan_tombol(teks, berikut: int, akhir: bool, kursor: dict):
    tombol = [Tombol("⬅️", b"imigrasi_page:1")]
    if akhir:
        tombol.append(Tombol("📄 5/5", b"noop"))
    else:
        tombol.append(Tombol("📄 %d/5" % berikut, b"imigrasi_page:%d" % berikut))
        tombol.append(Tombol("Next ➡️", b"imigrasi_page:%d" % berikut))
    return Pesan(teks, Markup(Baris(*tombol)), kursor)


def test_telusuri_halaman_mengumpulkan_sisa_halaman():
    halaman = [_halaman(i + 1, 4 if i < 4 else 1, i * 4 + 1) for i in range(5)]
    tg = TgPalsu(halaman)
    awal = [_pesan_dengan_tombol(halaman[0], 2, akhir=False, kursor=tg.kursor)]

    tambahan = asyncio.run(
        tg.telusuri_halaman("bot1", awal, 4, step_timeout=1))

    assert len(tambahan) == 4, f"harus 4 halaman tambahan, dapat {len(tambahan)}"
    teks = [m.text for m in tambahan]
    assert all("IMIGRASI" in t for t in teks)

    # semua halaman digabung -> classify harus melihat 17 record, bukan 4
    hasil = classify([awal[0].text] + teks)
    assert hasil["status"] == "found", hasil["status"]
    recs = hasil["fields"]
    recs = recs if isinstance(recs, list) else [recs]
    paspor = [r for r in recs if r.get("nomor_paspor") == "X0000000"]
    assert len(paspor) == 17, f"harus 17 record imigrasi, dapat {len(paspor)}"


def test_berhenti_saat_tombol_next_tidak_ada():
    """Sudah di halaman terakhir: tidak ada klik tambahan, tidak menggantung."""
    tg = TgPalsu([_halaman(1, 17, 1)])
    pesan = [_pesan_dengan_tombol(_halaman(1, 17, 1), 5, akhir=True, kursor=tg.kursor)]

    tambahan = asyncio.run(tg.telusuri_halaman("bot1", pesan, 4, step_timeout=1))

    assert tambahan == [], "tidak boleh menarik halaman saat tombol Next sudah habis"
    assert tg.kursor["klik"] == 0, "tidak boleh ada klik sia-sia"
