"""bot1 = teamkhususantibanditbot (dialek menu, dua langkah).

    pytest -s tests/test_bot1.py            # semua yang nilainya terisi
    pytest -s tests/test_bot1.py -k nik     # satu command
    pytest -s tests/test_bot1.py --force    # abaikan cache
"""
import pytest

from tests._helper import jalankan
from tests import values as V

# Ditandai `kuota`: tidak ikut `pytest` polos, harus diminta eksplisit
# dengan `pytest -m kuota`.
pytestmark = [pytest.mark.asyncio, pytest.mark.kuota]


@pytest.mark.parametrize("cmd", sorted(V.BOT1))
async def test_bot1(tg, conn, force, cmd):
    await jalankan(tg, conn, "bot1", cmd, V.BOT1[cmd], force)
