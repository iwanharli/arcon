"""Test fitur bot3 (cleojktbot). Isi nilai di tests/values.py.

Catatan: mengetik command + argumen langsung (bukan klik tombol menu) akan
menjalankan query sungguhan ke provider dan bisa memotong kuota/kredit akun.
"""
import pytest

from tests.values import BOT3

BOT = "bot3"


@pytest.mark.asyncio
@pytest.mark.parametrize("cmd, value", BOT3.items())
async def test_command(tg, cmd, value):
    if not value:
        pytest.skip(f"isi nilai untuk {cmd} di tests/values.py::BOT3")

    replies = await tg.ask(BOT, f"{cmd} {value}", collect=1)

    assert replies, f"{cmd}: tidak ada balasan dari bot"
    text = replies[0].text or ""
    print(f"\n--- {cmd} {value} ---\n{text}")
    assert text.strip(), f"{cmd}: balasan kosong"
