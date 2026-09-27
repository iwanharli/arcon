"""GetContact adalah otomasi samping dari NIK BY PHONE, bukan hasil akhir pencarian.

Bot dapat mengirim peringatan kuota GetContact lebih dulu, lalu melanjutkan
respons NIK BY PHONE. Peringatan itu tidak boleh mengakhiri penantian atau
masuk ke kumpulan pesan yang diklasifikasi sebagai hasil utama.

Jalankan: pytest -q tests/test_nikbyphone_getcontact.py
"""

import pytest

import connector
import parser
import service


GETCONTACT_LIMIT = """
⚠️ **Batas Penggunaan Tercapai**
Anda telah mencapai batas penggunaan harian untuk fitur GetContact.
"""

NIKBYPHONE_DATA = """
INFORMASI NIK
NOMOR: 082278585107
NIK: 3201010101010001
NAMA: CONTOH PENGUJI
"""


def test_limit_getcontact_bukan_hasil_akhir_nikbyphone():
    assert service.is_acceptable_result_message(
        "/nikbyphone", "082278585107", GETCONTACT_LIMIT
    ) is False


def test_data_nikbyphone_setelah_limit_tetap_diterima():
    assert service.is_acceptable_result_message(
        "/nikbyphone", "082278585107", NIKBYPHONE_DATA
    ) is True


def test_limit_getcontact_tidak_mengakhiri_command_lain():
    assert service.is_acceptable_result_message(
        "/track", "082278585107", GETCONTACT_LIMIT
    ) is False


def test_classifier_mengabaikan_limit_getcontact_bila_data_ada():
    result = parser.classify([GETCONTACT_LIMIT, NIKBYPHONE_DATA])
    assert result["status"] == "found"
    assert result["fields"], "data setelah limit GetContact harus tetap diparse"


def test_classifier_menyembunyikan_limit_getcontact_bila_tanpa_data():
    result = parser.classify([GETCONTACT_LIMIT])
    assert result["status"] == "queue_without_data"
    assert "getcontact" not in str(result["msg"]).lower()


def test_guard_menu_melewati_limit_getcontact():
    connector.TelegramConnector._pastikan_kuota(
        "bot1", "TRACKING PHONE", [PesanPalsu(GETCONTACT_LIMIT)]
    )


def test_guard_menu_tetap_menolak_limit_fitur_utama():
    with pytest.raises(connector.BatasHarian):
        connector.TelegramConnector._pastikan_kuota(
            "bot1", "TRACKING PHONE", [PesanPalsu("Batas penggunaan harian fitur Tracking Phone")]
        )


class PesanPalsu:
    def __init__(self, text):
        self.text = text


class TelegramPalsu:
    def __init__(self, replies):
        self.replies = [PesanPalsu(text) for text in replies]
        self.accepted = []

    async def ask_menu(self, _bot, _menu, _value, *, accept, **_kwargs):
        self.accepted = [accept(message) for message in self.replies]
        return self.replies


@pytest.mark.asyncio
async def test_alur_command_lain_melewati_limit_getcontact_lalu_parse_data():
    tg = TelegramPalsu([GETCONTACT_LIMIT, NIKBYPHONE_DATA])

    result = await service._ask_and_parse(
        tg, "bot1", "/track", "082278585107", None, 3
    )

    assert tg.accepted == [False, True]
    assert result["status"] == "found"
    assert result["fields"], "GetContact tidak boleh memutus command lain"


@pytest.mark.asyncio
async def test_alur_nikbyphone_melewati_limit_getcontact_lalu_parse_data():
    tg = TelegramPalsu([GETCONTACT_LIMIT, NIKBYPHONE_DATA])

    result = await service._ask_and_parse(
        tg, "bot1", "/nikbyphone", "082278585107", None, 3
    )

    assert tg.accepted == [False, True]
    assert result["status"] == "found"
    assert result["fields"], "data setelah limit GetContact harus tetap diparse"
