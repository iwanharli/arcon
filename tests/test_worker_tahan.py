"""Worker antrian harus tahan banting — offline penuh.

Tidak menyentuh Postgres maupun Telegram: koneksi, service.query dan db.connect
semuanya palsu. Aman dijalankan kapan saja:

    pytest -q tests/test_worker_tahan.py
"""
import asyncio

import psycopg
import pytest

import jobs

pytestmark = pytest.mark.asyncio

NIK = "3201999988887777"     # nilai "rahasia" yang tidak boleh bocor ke status
_PULIH_ASLI = jobs.pulihkan_tersangkut   # sebelum diganti fixture autouse


# ----------------------------------------------------------------- palsu

class CursorPalsu:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, sql, params=None):
        self.conn.executed.append((sql, params))

    async def fetchall(self):
        return self.conn.rows

    async def fetchone(self):
        return self.conn.rows[0] if self.conn.rows else None


class ConnPalsu:
    def __init__(self, nama="asli", rows=None):
        self.nama = nama
        self.closed = False
        self.broken = False
        self.executed = []
        self.rows = rows or []

    def cursor(self):
        return CursorPalsu(self)

    async def close(self):
        self.closed = True

    def __repr__(self):
        return f"<ConnPalsu {self.nama}>"


def job(n, bot="bot1", cmd="/nik", value=NIK):
    return {"job_id": f"00000000-0000-0000-0000-00000000000{n}", "bot": bot,
            "cmd": cmd, "value": value, "force": False}


def hasil_ok(from_cache=False):
    return {"status": "found", "msg": "ok", "fields": {}, "from_cache": from_cache}


@pytest.fixture(autouse=True)
def lingkungan(monkeypatch):
    """Reset status modul + percepat semua jeda worker."""
    jobs._status.update(running=False, poll_interval=2.0, last_beat=None,
                        current_job=None, last_error=None, last_error_at=None,
                        reconnects=0)
    tidur = []

    async def tidur_cepat(detik):
        tidur.append(detik)
        await asyncio.sleep(0)

    async def pulih_palsu(conn):
        return 0

    monkeypatch.setattr(jobs, "_tidur", tidur_cepat)
    monkeypatch.setattr(jobs, "pulihkan_tersangkut", pulih_palsu)
    return tidur


class Rekam:
    """Rekam panggilan _finish/_fail dan hentikan worker setelah N job."""

    def __init__(self, monkeypatch, stop, target):
        self.selesai, self.gagal = [], []
        self.stop, self.target = stop, target

        async def finish(conn, jid, hasil):
            self.selesai.append((conn, jid, hasil))
            self._cek()

        async def fail(conn, jid, error):
            self.gagal.append((conn, jid, error))
            self._cek()

        monkeypatch.setattr(jobs, "_finish", finish)
        monkeypatch.setattr(jobs, "_fail", fail)

    def _cek(self):
        if len(self.selesai) + len(self.gagal) >= self.target:
            self.stop.set()


def antrian(monkeypatch, *isi):
    """_claim_next palsu: item Exception dilempar, dict dikembalikan, lalu None."""
    sisa = list(isi)
    dipanggil = []

    async def claim(conn):
        dipanggil.append(conn)
        if not sisa:
            return None
        x = sisa.pop(0)
        if isinstance(x, BaseException):
            raise x
        return x

    monkeypatch.setattr(jobs, "_claim_next", claim)
    return dipanggil


async def jalankan(conn, stop, timeout=5):
    await asyncio.wait_for(
        jobs.run_worker(object(), conn, poll_interval=0.01, stop_event=stop), timeout)


# ----------------------------------------------------------------- tests

async def test_error_db_di_claim_sambung_ulang_dan_lanjut(monkeypatch, lingkungan):
    stop = asyncio.Event()
    rek = Rekam(monkeypatch, stop, target=1)
    dipanggil = antrian(monkeypatch,
                        psycopg.OperationalError("server closed the connection"),
                        job(1))
    asli, baru = ConnPalsu("asli"), ConnPalsu("baru")
    percobaan = []

    async def connect():
        percobaan.append(1)
        if len(percobaan) == 1:       # percobaan pertama gagal -> backoff
            raise psycopg.OperationalError("connection refused")
        return baru

    async def query(tg, conn, bot, cmd, value, *, force=False):
        return hasil_ok()

    monkeypatch.setattr(jobs.db, "connect", connect)
    monkeypatch.setattr(jobs.service, "query", query)

    await jalankan(asli, stop)

    assert dipanggil[0] is asli and dipanggil[-1] is baru
    assert asli.closed, "koneksi lama harus ditutup"
    assert len(percobaan) == 2
    assert rek.selesai and rek.selesai[0][0] is baru
    assert jobs.worker_status()["reconnects"] == 1
    assert 1.0 in lingkungan, "backoff sambung ulang harus menunggu"
    assert baru.closed, "koneksi pengganti milik worker, ditutup saat keluar"


async def test_koneksi_closed_memicu_sambung_ulang(monkeypatch):
    stop = asyncio.Event()
    rek = Rekam(monkeypatch, stop, target=1)
    antrian(monkeypatch, job(1))
    asli, baru = ConnPalsu("asli"), ConnPalsu("baru")
    asli.broken = True

    async def connect():
        return baru

    async def query(tg, conn, bot, cmd, value, *, force=False):
        return hasil_ok(from_cache=True)

    monkeypatch.setattr(jobs.db, "connect", connect)
    monkeypatch.setattr(jobs.service, "query", query)
    await jalankan(asli, stop)
    assert rek.selesai[0][0] is baru


async def test_exception_query_ditandai_gagal_lalu_lanjut(monkeypatch, lingkungan):
    stop = asyncio.Event()
    rek = Rekam(monkeypatch, stop, target=2)
    antrian(monkeypatch, job(1), job(2))

    async def query(tg, conn, bot, cmd, value, *, force=False):
        if not rek.gagal:
            raise ValueError(f"parser rusak untuk {value}")
        return hasil_ok()

    monkeypatch.setattr(jobs.service, "query", query)
    await jalankan(ConnPalsu(), stop)

    assert len(rek.gagal) == 1 and "ValueError" in rek.gagal[0][2]
    assert len(rek.selesai) == 1, "job berikutnya tetap diproses"
    assert jobs.JEDA_ANTAR_JOB in lingkungan


async def test_gagal_simpan_hasil_diulang_setelah_sambung_ulang(monkeypatch):
    """Bot sudah dijawab; hasilnya jangan dibuang hanya karena DB putus."""
    stop = asyncio.Event()
    asli, baru = ConnPalsu("asli"), ConnPalsu("baru")
    selesai = []

    async def finish(conn, jid, hasil):
        if conn is asli:
            raise psycopg.OperationalError("SSL connection has been closed")
        selesai.append((conn, jid))
        stop.set()

    async def fail(conn, jid, error):
        raise AssertionError("tidak boleh ditandai gagal")

    async def connect():
        return baru

    async def query(tg, conn, bot, cmd, value, *, force=False):
        return hasil_ok()

    antrian(monkeypatch, job(1))
    monkeypatch.setattr(jobs, "_finish", finish)
    monkeypatch.setattr(jobs, "_fail", fail)
    monkeypatch.setattr(jobs.db, "connect", connect)
    monkeypatch.setattr(jobs.service, "query", query)
    await jalankan(asli, stop)
    assert selesai == [(baru, job(1)["job_id"])]


async def test_fail_kena_error_db_diulang_setelah_sambung_ulang(monkeypatch):
    stop = asyncio.Event()
    asli, baru = ConnPalsu("asli"), ConnPalsu("baru")
    gagal = []

    async def fail(conn, jid, error):
        if conn is asli:
            raise psycopg.InterfaceError("connection already closed")
        gagal.append((conn, error))
        stop.set()

    async def connect():
        return baru

    async def query(tg, conn, bot, cmd, value, *, force=False):
        raise RuntimeError("bot error")

    antrian(monkeypatch, job(1))
    monkeypatch.setattr(jobs, "_fail", fail)
    monkeypatch.setattr(jobs.db, "connect", connect)
    monkeypatch.setattr(jobs.service, "query", query)
    await jalankan(asli, stop)
    assert gagal and gagal[0][0] is baru and "RuntimeError" in gagal[0][1]


async def test_timeout_job_ditandai_gagal(monkeypatch, lingkungan):
    stop = asyncio.Event()
    rek = Rekam(monkeypatch, stop, target=1)
    antrian(monkeypatch, job(1))
    monkeypatch.setattr(jobs, "JOB_TIMEOUT", 0.05)

    async def query(tg, conn, bot, cmd, value, *, force=False):
        await asyncio.Event().wait()          # bot tidak pernah menjawab

    monkeypatch.setattr(jobs.service, "query", query)
    await jalankan(ConnPalsu(), stop)

    assert len(rek.gagal) == 1
    assert rek.gagal[0][2].startswith("timeout: bot tidak menjawab dalam")
    st = jobs.worker_status()
    assert "timeout" in st["last_error"]
    assert jobs.JEDA_ANTAR_JOB in lingkungan, "bot sudah tersentuh -> tetap jeda"


async def test_timeout_job_berkas_lebih_longgar(monkeypatch):
    monkeypatch.setattr(jobs, "JOB_TIMEOUT", 900)
    monkeypatch.setattr(jobs, "JOB_TIMEOUT_BERKAS", 1800)
    assert jobs._batas_waktu("bot1", "/fr") == 1800
    assert jobs._batas_waktu("bot1", "/nik") == 900


async def test_pulihkan_tersangkut_sql():
    # Fixture autouse mengganti pulihkan_tersangkut; pakai fungsi aslinya.
    conn = ConnPalsu(rows=[{"job_id": "a"}, {"job_id": "b"}])
    n = await _PULIH_ASLI(conn)
    assert n == 2
    sql = " ".join(conn.executed[0][0].split())
    assert "SET state = 'failed'" in sql
    assert "WHERE state = 'running'" in sql
    assert "finished_at = now()" in sql
    assert "dibatalkan: proses connector restart saat job berjalan" in sql
    assert "'queued'" not in sql, "jangan antre ulang: bot ditembak dua kali"


async def test_worker_status_bentuk_dan_tanpa_value(monkeypatch):
    stop = asyncio.Event()
    rek = Rekam(monkeypatch, stop, target=2)
    antrian(monkeypatch, job(1), job(2))
    terlihat = []

    async def query(tg, conn, bot, cmd, value, *, force=False):
        terlihat.append(jobs.worker_status())
        if len(terlihat) == 1:
            raise ValueError(f"nilai {value} tidak valid")   # memuat NIK
        return hasil_ok()

    monkeypatch.setattr(jobs.service, "query", query)
    await jalankan(ConnPalsu(), stop)

    kunci = {"alive", "last_beat", "current_job", "last_error",
             "last_error_at", "reconnects"}
    st = terlihat[0]
    assert set(st) == kunci
    assert st["alive"] is True
    assert set(st["current_job"]) == {"job_id", "bot", "cmd", "started", "age_s"}
    assert st["current_job"]["bot"] == "bot1" and st["current_job"]["cmd"] == "/nik"
    assert isinstance(st["current_job"]["age_s"], int)
    assert isinstance(st["last_beat"], float)

    akhir = jobs.worker_status()
    assert set(akhir) == kunci
    assert akhir["current_job"] is None
    assert akhir["alive"] is False, "worker sudah keluar"
    assert akhir["last_error"] and isinstance(akhir["last_error_at"], float)
    for s in terlihat + [akhir]:
        assert NIK not in repr(s), "value job (data pribadi) bocor ke status"
    assert rek.gagal and rek.selesai


async def test_worker_status_belum_jalan():
    st = jobs.worker_status()
    assert st["alive"] is False and st["current_job"] is None


async def test_cancel_tetap_propagasi(monkeypatch):
    antrian(monkeypatch)                      # antrian kosong, loop poll
    asli = ConnPalsu()
    task = asyncio.create_task(
        jobs.run_worker(object(), asli, poll_interval=0.01))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not asli.closed, "koneksi asli milik pemanggil, jangan ditutup"
    assert jobs.worker_status()["alive"] is False
