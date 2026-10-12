"""KoneksiPulih menyambung ulang setelah koneksi mati (bot Telegram dulu macet sampai restart)."""
import asyncio

import db


class _Cur:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *e):
        return False


class _Conn:
    def __init__(self):
        self.closed = False
        self.broken = False

    async def execute(self, q, **k):
        return None

    async def close(self):
        self.closed = True

    def cursor(self, *a, **k):
        return _Cur()


def test_sambung_ulang_setelah_koneksi_mati(monkeypatch):
    dibuat = []

    async def fake_connect():
        c = _Conn()
        dibuat.append(c)
        return c

    monkeypatch.setattr(db, "connect", fake_connect)

    async def jalan():
        p = await db.connect_pulih()
        async with p.cursor():
            pass
        dibuat[0].closed = True  # Postgres restart
        async with p.cursor():
            pass

    asyncio.run(jalan())
    assert len(dibuat) == 2
