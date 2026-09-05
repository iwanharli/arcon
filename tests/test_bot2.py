"""Test fitur bot2 (mahalini2bot). Isi nilai di tests/values.py."""
import pytest

from tests.values import BOT2

BOT = "bot2"


@pytest.mark.asyncio
@pytest.mark.parametrize("cmd, value", BOT2.items())
async def test_command(tg, cmd, value):
    if not value:
        pytest.skip(f"isi nilai untuk {cmd} di tests/values.py::BOT2")

    replies = await tg.ask(BOT, f"{cmd} {value}", collect=1)

    assert replies, f"{cmd}: tidak ada balasan dari bot"
    text = replies[0].text or ""
    print(f"\n--- {cmd} {value} ---\n{text}")
    assert text.strip(), f"{cmd}: balasan kosong"


@pytest.mark.asyncio
async def test_kredit(tg):
    replies = await tg.ask(BOT, "/kredit", collect=1)
    assert replies, "/kredit: tidak ada balasan dari bot"
    print(f"\n--- /kredit ---\n{replies[0].text}")
