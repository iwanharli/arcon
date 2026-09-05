"""Test fitur bot1 (cielodespejadobot). Isi nilai di tests/values.py."""
import pytest

from tests.values import BOT1

BOT = "bot1"


@pytest.mark.asyncio
@pytest.mark.parametrize("cmd, value", BOT1.items())
async def test_command(tg, cmd, value):
    if not value:
        pytest.skip(f"isi nilai untuk {cmd} di tests/values.py::BOT1")

    replies = await tg.ask(BOT, f"{cmd} {value}", collect=1)

    assert replies, f"{cmd}: tidak ada balasan dari bot"
    text = replies[0].text or ""
    print(f"\n--- {cmd} {value} ---\n{text}")
    assert text.strip(), f"{cmd}: balasan kosong"
