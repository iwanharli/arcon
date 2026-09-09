"""bot2 = Getphoneplusbot (dialek command). KUOTA TERBATAS — cek /quota dulu.

    pytest -s tests/test_bot2.py
"""
import pytest

from tests._helper import jalankan
from tests import values as V

# Ditandai `kuota`: tidak ikut `pytest` polos, harus diminta eksplisit
# dengan `pytest -m kuota`.
pytestmark = [pytest.mark.asyncio, pytest.mark.kuota]


@pytest.mark.parametrize("cmd", sorted(V.BOT2))
async def test_bot2(tg, conn, force, cmd):
    await jalankan(tg, conn, "bot2", cmd, V.BOT2[cmd], force)
