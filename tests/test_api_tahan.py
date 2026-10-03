"""Uji ketahanan API — offline total (tanpa Postgres, tanpa Telegram).

Yang diuji:
  - _conn() menyambung ulang saat koneksi bersama tertutup/putus, dan hanya
    SATU koneksi baru dibuat walau banyak request datang bersamaan;
  - _jebakan_error: error DB → 503 + koneksi ditutup supaya tersambung ulang;
  - /health melaporkan task worker, worker_status, job running tertua, tanpa
    membocorkan `value` (data pribadi);
  - shutdown lifespan tidak meledak walau koneksinya sudah tertutup/diganti
    (TelegramConnector, db.connect, run_worker semuanya tiruan);
  - DDL user_logs hanya dijalankan sekali per proses;
  - verify_login/create_user/set_password tetap benar setelah PBKDF2
    dipindah ke thread.

Endpoint dipanggil langsung sebagai coroutine (bukan TestClient), sama seperti
tests/test_health.py, supaya lifespan asli (yang konek Telegram) tidak jalan.
"""
import asyncio
import json
import types

import psycopg
import pytest

import api
import appauth
import db


# ------------------------------------------------------------------ tiruan

class KursorPalsu:
    """Kursor async minimal: mencatat SQL, menjawab dari antrean `jawaban`."""

    def __init__(self, koneksi):
        self.k = koneksi
        self.rowcount = 1

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, sql, params=None):
        self.k.sql.append((" ".join(sql.split()), params))
        if self.k.gagal_execute:
            raise self.k.gagal_execute

    async def fetchone(self):
        return self.k.jawaban.pop(0) if self.k.jawaban else None

    async def fetchall(self):
        return self.k.jawaban.pop(0) if self.k.jawaban else []


class KoneksiPalsu:
    def __init__(self, nama="k", closed=False, broken=False, close_gagal=False):
        self.nama = nama
        self.closed = closed
        self.broken = broken
        self.close_gagal = close_gagal
        self.ditutup = 0
        self.sql: list = []
        self.jawaban: list = []
        self.gagal_execute = None

    def cursor(self):
        return KursorPalsu(self)

    async def close(self):
        self.ditutup += 1
        if self.close_gagal:
            raise psycopg.OperationalError("sudah putus")
        self.closed = True


@pytest.fixture()
def pabrik(monkeypatch):
    """Ganti db.connect dengan pembuat KoneksiPalsu; catat yang dibuat."""
    dibuat = []

    async def connect():
        await asyncio.sleep(0)  # beri kesempatan request lain menyalip
        k = KoneksiPalsu(nama=f"baru{len(dibuat)}")
        dibuat.append(k)
        return k

    monkeypatch.setattr(api.db, "connect", connect)
    return dibuat


@pytest.fixture(autouse=True)
def _state_bersih(monkeypatch):
    # monkeypatch.setitem memulihkan api.state setelah tiap test, supaya test
    # lain (test_health.py) tidak mewarisi task/conn tiruan dari sini.
    for kunci in ("conn", "task", "stop", "tg"):
        monkeypatch.delitem(api.state, kunci, raising=False)
    yield


# -------------------------------------------------------------- A: _conn()

async def test_conn_sehat_tidak_reconnect(pabrik, monkeypatch):
    lama = KoneksiPalsu("lama")
    monkeypatch.setitem(api.state, "conn", lama)
    assert await api._conn() is lama
    assert pabrik == []


@pytest.mark.parametrize("rusak", [{"closed": True}, {"broken": True}])
async def test_conn_rusak_disambung_ulang(pabrik, monkeypatch, rusak):
    lama = KoneksiPalsu("lama", **rusak)
    monkeypatch.setitem(api.state, "conn", lama)
    baru = await api._conn()
    assert baru is pabrik[0]
    assert api.state["conn"] is baru
    assert lama.ditutup == 1
    # panggilan berikutnya memakai koneksi baru, tanpa connect lagi
    assert await api._conn() is baru
    assert len(pabrik) == 1


async def test_conn_close_gagal_tetap_reconnect(pabrik, monkeypatch):
    lama = KoneksiPalsu("lama", broken=True, close_gagal=True)
    monkeypatch.setitem(api.state, "conn", lama)
    assert await api._conn() is pabrik[0]


async def test_conn_serentak_hanya_satu_koneksi_baru(pabrik, monkeypatch):
    monkeypatch.setitem(api.state, "conn", KoneksiPalsu("lama", broken=True))
    hasil = await asyncio.gather(*(api._conn() for _ in range(10)))
    assert len(pabrik) == 1
    assert all(h is pabrik[0] for h in hasil)


async def test_conn_db_masih_mati_lalu_pulih(monkeypatch):
    monkeypatch.setitem(api.state, "conn", KoneksiPalsu("lama", closed=True))
    hidup = {"ya": False}

    async def connect():
        if not hidup["ya"]:
            raise psycopg.OperationalError("connection refused")
        return KoneksiPalsu("pulih")

    monkeypatch.setattr(api.db, "connect", connect)
    with pytest.raises(psycopg.OperationalError):
        await api._conn()
    hidup["ya"] = True
    assert (await api._conn()).nama == "pulih"


async def test_endpoint_memakai_koneksi_tersambung_ulang(pabrik, monkeypatch):
    """POST /auth/login (jalur login ArtemisID) pulih tanpa restart server."""
    monkeypatch.setitem(api.state, "conn", KoneksiPalsu("lama", broken=True))
    dipakai = []

    async def verify_login(conn, u, p):
        dipakai.append(conn)
        return {"username": u, "role": "user"}

    monkeypatch.setattr(api.appauth, "verify_login", verify_login)
    out = await api.auth_login(api.LoginReq(username="a", password="b"))
    assert out["ok"] is True
    assert dipakai == [pabrik[0]]


# ------------------------------------------------------- A: _jebakan_error

def _req():
    return types.SimpleNamespace(method="POST", url=types.SimpleNamespace(path="/auth/login"))


@pytest.mark.parametrize("exc", [psycopg.OperationalError("server closed the connection"),
                                 psycopg.InterfaceError("connection already closed")])
async def test_error_db_jadi_503_dan_reconnect(pabrik, monkeypatch, exc):
    lama = KoneksiPalsu("lama")
    monkeypatch.setitem(api.state, "conn", lama)
    resp = await api._jebakan_error(_req(), exc)
    assert resp.status_code == 503
    assert json.loads(resp.body) == {"ok": False, "detail": "database sementara tidak tersedia"}
    assert lama.ditutup == 1
    assert await api._conn() is pabrik[0]


async def test_error_db_conn_sudah_putus_tidak_meledak(monkeypatch):
    monkeypatch.setitem(api.state, "conn", KoneksiPalsu("lama", close_gagal=True))
    resp = await api._jebakan_error(_req(), psycopg.OperationalError("x"))
    assert resp.status_code == 503


async def test_error_lain_tetap_500(monkeypatch):
    lama = KoneksiPalsu("lama")
    monkeypatch.setitem(api.state, "conn", lama)
    resp = await api._jebakan_error(_req(), ValueError("bug"))
    assert resp.status_code == 500
    assert lama.ditutup == 0


# ------------------------------------------------------------- B: /health

async def _task_selesai(coro):
    t = asyncio.create_task(coro)
    try:
        await t
    except BaseException:
        pass
    return t


def _conn_health(monkeypatch, umur=None, stats=None):
    k = KoneksiPalsu("health")
    k.jawaban = [{"umur": umur}]
    monkeypatch.setitem(api.state, "conn", k)

    async def queue_stats(conn):
        return stats if stats is not None else {"queued": 3, "running": 1, "done": 9}

    monkeypatch.setattr(api.jobs, "queue_stats", queue_stats)
    return k


async def test_health_lengkap_tanpa_value(monkeypatch):
    _conn_health(monkeypatch, umur=1234.56)
    stop = asyncio.Event()
    task = asyncio.create_task(stop.wait())
    monkeypatch.setitem(api.state, "task", task)

    def worker_status():
        return {"alive": True, "last_beat": "2026-10-03T00:00:00Z",
                "current_job": {"job_id": "j1", "bot": "bot1", "cmd": "/nik",
                                "value": "3201010101010001", "started": "t", "age_s": 1234.5},
                "last_error": None, "last_error_at": None, "reconnects": 2}

    monkeypatch.setattr(api.jobs, "worker_status", worker_status, raising=False)
    try:
        data = await api.health()
    finally:
        stop.set()
        await task
    assert data["ok"] is True
    assert data["db"] == "ok"
    assert data["antrian"] == {"queued": 3, "running": 1, "done": 9}
    assert data["worker_task"] == "running"
    assert data["running_oldest_s"] == 1234.6
    assert data["queued"] == 3
    assert data["worker"]["reconnects"] == 2
    assert data["worker"]["current_job"]["job_id"] == "j1"
    assert "3201010101010001" not in json.dumps(data, default=str)


async def test_health_worker_mati_ok_false(monkeypatch):
    _conn_health(monkeypatch, umur=None)

    async def meledak():
        raise RuntimeError("worker crash")

    monkeypatch.setitem(api.state, "task", await _task_selesai(meledak()))
    monkeypatch.delattr(api.jobs, "worker_status", raising=False)
    data = await api.health()
    assert data["db"] == "ok"
    assert data["worker_task"] == "dead: RuntimeError"
    assert data["ok"] is False
    assert data["worker"] is None
    assert data["running_oldest_s"] is None


async def test_health_worker_berhenti_normal_atau_dibatalkan(monkeypatch):
    _conn_health(monkeypatch)

    async def tidur():
        await asyncio.sleep(10)

    t = asyncio.create_task(tidur())
    await asyncio.sleep(0)
    t.cancel()
    await _task_selesai(asyncio.sleep(0))
    try:
        await t
    except asyncio.CancelledError:
        pass
    monkeypatch.setitem(api.state, "task", t)
    data = await api.health()
    assert data["worker_task"] == "stopped"
    assert data["ok"] is True

    async def selesai():
        return None

    monkeypatch.setitem(api.state, "task", await _task_selesai(selesai()))
    assert (await api.health())["worker_task"] == "stopped"


async def test_health_db_mati_tetap_200_dan_paksa_reconnect(monkeypatch):
    k = KoneksiPalsu("lama")
    monkeypatch.setitem(api.state, "conn", k)

    async def queue_stats(conn):
        raise psycopg.OperationalError("connection refused")

    monkeypatch.setattr(api.jobs, "queue_stats", queue_stats)
    data = await api.health()
    assert data["ok"] is False
    assert data["db"] == "error: OperationalError"
    assert data["antrian"] is None and data["queued"] is None
    assert k.ditutup == 1  # request berikutnya akan menyambung ulang


async def test_health_worker_status_gagal_tidak_merusak(monkeypatch):
    _conn_health(monkeypatch)

    def worker_status():
        raise KeyError("x")

    monkeypatch.setattr(api.jobs, "worker_status", worker_status, raising=False)
    data = await api.health()
    assert data["worker"] == {"error": "KeyError"}
    assert data["db"] == "ok"


# ------------------------------------------- A: shutdown lifespan tahan banting

async def test_lifespan_shutdown_aman_walau_conn_sudah_diganti(monkeypatch, pabrik):
    class TgPalsu:
        berhenti = False

        async def start(self):
            pass

        async def stop(self):
            TgPalsu.berhenti = True

    async def run_worker(tg, conn, stop_event=None):
        await stop_event.wait()

    monkeypatch.setattr(api, "TelegramConnector", TgPalsu)
    monkeypatch.setattr(api.jobs, "run_worker", run_worker)
    monkeypatch.setattr(db, "_user_logs_siap", False)

    async with api.lifespan(api.app):
        conn_awal = api.state["conn"]
        assert db._user_logs_siap is True  # DDL dijalankan sekali saat start
        # koneksi putus dan sudah diganti oleh _conn()
        conn_awal.broken = True
        conn_awal.close_gagal = True
        pengganti = await api._conn()
        pengganti.close_gagal = True
    assert TgPalsu.berhenti is True
    assert conn_awal.ditutup >= 1 and pengganti.ditutup == 1


# --------------------------------------------- C: DDL user_logs sekali saja

async def test_ddl_user_logs_sekali(monkeypatch):
    monkeypatch.setattr(db, "_user_logs_siap", False)
    k = KoneksiPalsu()
    k.jawaban = [{"id": 1}, {"id": 2}]
    assert await db.log_insert(k, "budi", "login") == 1
    assert await db.log_insert(k, "budi", "search", {"cmd": "/nik"}) == 2
    await db.log_list(k)
    ddl = [s for s, _ in k.sql if s.startswith("CREATE")]
    assert len(ddl) == 3  # 1 tabel + 2 index, hanya pada panggilan pertama
    assert sum(1 for s, _ in k.sql if s.startswith("INSERT INTO user_logs")) == 2


async def test_ddl_gagal_flag_tetap_kosong(monkeypatch):
    monkeypatch.setattr(db, "_user_logs_siap", False)
    k = KoneksiPalsu()
    k.gagal_execute = psycopg.OperationalError("db berkedip")
    with pytest.raises(psycopg.OperationalError):
        await db.ensure_user_logs(k)
    assert db._user_logs_siap is False
    k.gagal_execute = None
    await db.ensure_user_logs(k)
    assert db._user_logs_siap is True


# ------------------------------------------------ D: PBKDF2 di luar event loop

@pytest.fixture()
def hitung_thread(monkeypatch):
    """Bungkus asyncio.to_thread untuk memastikan hash benar lewat thread."""
    asli = asyncio.to_thread
    dipanggil = []

    async def to_thread(fn, *a, **kw):
        dipanggil.append(fn.__name__)
        return await asli(fn, *a, **kw)

    monkeypatch.setattr(appauth.asyncio, "to_thread", to_thread)
    return dipanggil


async def test_verify_login_lewat_thread(hitung_thread):
    hashed = appauth.hash_password("rahasia")
    k = KoneksiPalsu()
    k.jawaban = [{"username": "budi", "password": hashed, "role": "admin", "active": True}]
    assert await appauth.verify_login(k, "budi", "rahasia") == {"username": "budi", "role": "admin"}
    assert any("last_login_at" in s for s, _ in k.sql)

    k.jawaban = [{"username": "budi", "password": hashed, "role": "admin", "active": True}]
    assert await appauth.verify_login(k, "budi", "salah") is None

    k.jawaban = []  # user tidak ada → cabang hash tiruan
    assert await appauth.verify_login(k, "hantu", "x") is None

    k.jawaban = [{"username": "budi", "password": hashed, "role": "user", "active": False}]
    assert await appauth.verify_login(k, "budi", "rahasia") is None

    assert hitung_thread == ["verify_password"] * 4


async def test_hash_tiruan_sama_mahal_dengan_hash_asli():
    _, iter_s, salt, h = appauth._HASH_TIRUAN.split("$")
    assert int(iter_s) == appauth.PBKDF2_ITER
    assert len(bytes.fromhex(salt)) == 16 and len(bytes.fromhex(h)) == 32
    assert appauth.verify_password("apa saja", appauth._HASH_TIRUAN) is False


async def test_create_user_dan_set_password_lewat_thread(hitung_thread):
    k = KoneksiPalsu()
    await appauth.create_user(k, "budi", "pw1", "user")
    assert appauth.verify_password("pw1", k.sql[-1][1][1])
    assert await appauth.set_password(k, "budi", "pw2") is True
    assert appauth.verify_password("pw2", k.sql[-1][1][0])
    assert hitung_thread == ["hash_password", "hash_password"]
