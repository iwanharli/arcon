"""Jaring pengaman penyimpanan — TIDAK menyentuh Telegram, jadi tanpa kuota.

Menguji bahwa hasil ber-status 'found' tidak pernah hilang senyap walaupun
normalizer tidak mengenalinya atau tabel tujuannya menolak.
"""
import uuid

import pytest

import db

pytestmark = pytest.mark.asyncio


@pytest.fixture()
def nilai():
    """Nilai unik tiap kali dijalankan.

    profile_records punya UNIQUE (kind, subject, data) dengan ON CONFLICT DO
    NOTHING, jadi memakai nilai tetap membuat test lulus sekali lalu gagal di
    jalan kedua: barisnya sudah ada dan source_query_id-nya milik query lama.
    """
    return f"UJI-{uuid.uuid4().hex[:8]}"


@pytest.fixture(autouse=True)
async def bersihkan(conn):
    yield
    async with conn.cursor() as cur:
        await cur.execute("DELETE FROM bot_query_cache WHERE value LIKE 'UJI-%%'")
        await cur.execute("DELETE FROM profile_records WHERE subject LIKE 'UJI-%%'")
        await cur.execute("DELETE FROM profiles WHERE nama LIKE 'UJI-%%'")


async def _records(conn, query_id):
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT kind, subject, data FROM profile_records WHERE source_query_id = %s",
            (query_id,))
        return await cur.fetchall()


async def test_atribut_luar_kolom_turun_ke_records(conn, nilai):
    """profiles cuma punya kolom kependudukan baku. Atribut lain (mis. NIK
    INSIGHT mengembalikan 28 field seperti neptu/generasi) harus tetap
    tersimpan di profile_records, bukan dibuang."""
    qid = await db.store_result(
        conn, "bot1", "/nama", nilai, "found",
        fields={"nama": nilai, "alamat": "JL MAWAR 1",
                "neptu": "13", "generasi": "MILENIAL"})
    rows = await _records(conn, qid)
    assert rows, "atribut di luar kolom profiles hilang"
    data = rows[0]["data"]
    assert data.get("neptu") == "13" and data.get("generasi") == "MILENIAL"
    assert "alamat" not in data, "kolom profiles tidak perlu digandakan"


async def test_bentuk_asing_tetap_tersimpan(conn, nilai):
    """Balasan yang tidak dikenali normalizer (mis. data non-orang di route
    yang memakai normalize_person) harus tetap tersimpan mentah."""
    qid = await db.store_result(
        conn, "bot1", "/nik", nilai, "found",
        fields={"asn": nilai, "isp": "PT CONTOH", "route": "10.0.0.0/8"})
    rows = await _records(conn, qid)
    assert rows, "bentuk asing hilang — jaring pengaman tidak bekerja"
    assert rows[0]["data"].get("asn") == nilai.upper()


async def test_profil_tanpa_nik_tersimpan(conn, nilai):
    """Skema merancang `nik` nullable untuk hasil cari-by-nama, tapi
    upsert_profile dulu menolaknya. Harus masuk profiles, dan tidak boleh
    menumpuk duplikat kalau query yang sama diulang."""
    async def simpan():
        return await db.store_result(
            conn, "bot1", "/paspor", nilai, "found",
            fields={"nama": nilai, "tgl._lahir": "09/07/1974",
                    "no._paspor": "AB000000"})

    await simpan()
    await simpan()                      # ulangi: harus idempoten
    async with conn.cursor() as cur:
        await cur.execute("SELECT id, nik FROM profiles WHERE lower(nama) = lower(%s)",
                          (nilai,))
        rows = await cur.fetchall()
    assert len(rows) == 1, f"profil tanpa NIK menumpuk: {len(rows)} baris"
    assert rows[0]["nik"] is None


async def test_not_found_tidak_bikin_record(conn, nilai):
    """Status selain found memang hanya boleh masuk cache."""
    qid = await db.store_result(
        conn, "bot1", "/nik", nilai, "not_found",
        fields=None, msg="Tidak ditemukan")
    assert await _records(conn, qid) == []


async def test_cache_selalu_tersimpan(conn, nilai):
    """Lapis cache tidak boleh punya syarat apa pun."""
    for status in ("found", "not_found", "queue_without_data", "no_response"):
        qid = await db.store_result(conn, "bot1", "/nik", f"{nilai}-{status}", status)
        async with conn.cursor() as cur:
            await cur.execute("SELECT status, bot_username FROM bot_query_cache WHERE id = %s",
                              (qid,))
            row = await cur.fetchone()
        assert row["status"] == status
        assert row["bot_username"] == "teamkhususantibanditbot"


async def test_record_tertaut_ke_profil_tanpa_nik(conn, nilai):
    """Record harus tertaut ke profilnya walau profil itu ber-NIK NULL.

    find_profile_id() hanya bisa mencari lewat NIK, jadi tanpa profile_id yang
    diteruskan langsung, catatan tersimpan tapi menggantung — GET /profiles/id
    mengembalikan catatan kosong padahal datanya ada.
    """
    await db.store_result(
        conn, "bot1", "/paspor", nilai, "found",
        fields={"nama": nilai, "no._paspor": "AB000000", "nikim": "0001"})
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT count(r.id) AS n
              FROM profiles p JOIN profile_records r ON r.profile_id = p.id
             WHERE lower(p.nama) = lower(%s)
            """, (nilai,))
        n = (await cur.fetchone())["n"]
    assert n >= 1, "record tidak tertaut ke profil tanpa NIK"


async def test_hapus_cache_ikut_hapus_turunan(conn, nilai):
    """Menghapus baris cache harus ikut menghapus lapis turunannya.

    Dengan ON DELETE SET NULL, record yatim tertinggal DAN — karena
    UNIQUE (kind, subject, data) + ON CONFLICT DO NOTHING — ia MENAHAN insert
    baru yang isinya sama, sehingga hasil query terbaru diam-diam hilang.
    """
    qid = await db.store_result(
        conn, "bot1", "/bpom", nilai, "found",
        fields={"nama": nilai, "nie": "MD-UJI-001"})
    assert await _records(conn, qid)

    async with conn.cursor() as cur:
        await cur.execute("DELETE FROM bot_query_cache WHERE id = %s", (qid,))
        await cur.execute(
            "SELECT count(*) AS n FROM profile_records WHERE subject = %s", (nilai,))
        sisa = (await cur.fetchone())["n"]
    assert sisa == 0, "turunan tidak ikut terhapus — akan menahan insert berikutnya"

    # query ulang dengan isi sama harus tersimpan lagi, bukan tertahan
    qid2 = await db.store_result(
        conn, "bot1", "/bpom", nilai, "found",
        fields={"nama": nilai, "nie": "MD-UJI-001"})
    assert await _records(conn, qid2), "insert baru tertahan sisa lama"


def test_nama_field_api_cocok_dengan_katalog():
    """Nama field di respons API harus sama dengan `atribut` di GET /commands.

    Sebelumnya tidak: API mengirim hasil parse mentah ('berlaku_s/d'),
    sedangkan katalog dibangun dari profile_records yang sudah diseragamkan
    ('berlaku_sampai'). Konsumen JSON jadi harus menebak ejaannya.
    """
    import normalize as N

    mentah = {"Berlaku s/d": "2029-08-05", "No. Sertifikat": "0009",
              "Abuse Email": "abuse@detik.net.id", "Keyword": "Indomie",
              "2013": "MURI"}
    api = N.rapikan_nama_field(mentah)
    simpan = N.normalize_raw(mentah)

    assert set(api) == set(simpan), "nama field API beda dengan yang disimpan"
    assert api["abuse_email"] == "abuse@detik.net.id", "nilai tidak boleh diubah"
    assert "keyword" not in api, "metadata pencarian tidak boleh jadi atribut"
    assert api["tahun_2013"] == "MURI"


def test_rapikan_nama_field_menerima_banyak_record():
    import normalize as N

    hasil = N.rapikan_nama_field([{"No. Sertifikat": "1"}, {"No. Sertifikat": "2"}])
    assert [r["nomor_sertifikat"] for r in hasil] == ["1", "2"]


def test_identitas_dibandingkan_per_jenis():
    """Balasan hanya boleh ditolak kalau identitasnya SEJENIS tapi berbeda.

    NIK BY PHONE dicari dengan nomor HP dan memang menjawab dengan NIK yang
    berbeda. Membandingkan lintas jenis membuat seluruh laporannya ditolak
    sebagai balasan nyasar — hanya potongan tanpa NIK yang tersimpan.
    """
    import service as S

    hp = "08163666609"
    assert S.relates_to_request(hp, ["NIK: 3275025503930009"],
                                {"nik": "3275025503930009"}) is not False

    nik = "3275054503060005"
    assert S.relates_to_request(nik, ["x"], {"nik": "3201010101010001"}) is False
    assert S.relates_to_request(hp, ["x"], {"nomor": "6281111111111"}) is False


def test_nama_field_bertanda_hubung_dan_bernomor():
    """Dua kebiasaan bot yang dulu merusak parsing.

    - "4. PBI-JK: TIDAK" tidak dikenali sama sekali karena KV_RE menolak tanda
      hubung, sehingga barisnya HILANG.
    - "1. DESIL:" ikut membawa nomor urut daftar ke nama field, jadi tiap butir
      jadi field berbeda (n_1_desil) dan skemanya berubah mengikuti urutan.
    """
    import normalize as N
    import parser as P

    rec, _ = P.parse_reply("1. DESIL: 6-10\n2. SEMBAKO: TIDAK\n4. PBI-JK: TIDAK")
    assert rec, "baris tidak terurai"
    kunci = set(rec[0])
    assert {"desil", "sembako"} <= kunci, kunci
    assert any("pbi" in k for k in kunci), "baris bertanda hubung hilang"
    assert not any(k.startswith("n_") for k in kunci), "nomor urut ikut jadi nama"

    assert N.slug_key("PBI-JK") == "pbi_jk"
    assert N.slug_key("MA-RI") == "ma_ri"


def test_format_nomor_disamakan():
    """08xxx dan 62xxx adalah nomor yang SAMA.

    Bot menjawab dalam format 62xxx sedangkan pengguna mengetik 08xxx. Tanpa
    penyamaan, bagian laporan yang memuat nomor kita sendiri dinilai "milik
    permintaan lain" lalu dibuang — bagian A dan D pada NIK BY PHONE hilang.
    """
    import service as S

    assert S.relates_to_request("08163666609", ["NOMOR : 628163666609"], None) is True
    assert S.relates_to_request("08163666609", ["x"], {"nomor": "628163666609"}) is not False
    assert S.relates_to_request("08163666609", ["x"], {"nomor": "628111111111"}) is False


def test_hash_berkas_bukan_identitas():
    """Job berbasis foto memakai sha256 sebagai `value`.

    Digit di dalam hash bukan identitas apa pun, tapi _identifier()
    menganggapnya nomor — akibatnya seluruh balasan pencarian wajah ditolak
    sebagai "milik permintaan lain" dan hasilnya hilang.
    """
    import routes
    import service as S

    sha = "61db565b4b0f62fc412136e159560360a5da252a9ab62c71f3089475637e61f0"
    assert S._identifier(sha) is not None, "hash memang terbaca sebagai angka"
    assert routes.butuh_berkas("bot1", "/fr") is True, (
        "jalur berkas harus dikenali supaya pencocokan identitas dilewati")


def test_nama_field_berulang_jadi_record_baru():
    """Daftar kandidat tanpa pemisah harus terpecah per kandidat.

    Hasil FACE RECOGNITION berupa pasangan Match Confidence/NIK yang berulang
    tanpa garis pemisah. Tanpa pemecahan ini semuanya masuk satu dict dan
    saling menimpa — 10 kandidat menyusut jadi 1.
    """
    import parser as P

    teks = "\n".join(
        f"Match Confidence: {90 - i}.00%\nNIK: 33050552119300{i:02d}" for i in range(5))
    rec, _ = P.parse_reply(teks)
    assert len(rec) == 5, f"kandidat menyusut jadi {len(rec)}"
    assert len({r["nik"] for r in rec}) == 5, "NIK antar kandidat tertimpa"


async def test_cache_kedaluwarsa_ditembak_ulang(conn, nilai):
    """Hasil 'found' yang lebih tua dari CACHE_HARI tidak boleh disajikan lagi.

    Tanpa batas umur, hasil hari ini terus dijawab berbulan-bulan kemudian dan
    data yang berubah (registrasi nomor, alamat) disajikan basi tanpa pengguna
    tahu.
    """
    import db as D

    qid = await D.store_result(conn, "bot1", "/nikbyphone", nilai, "found",
                               fields={"nama": nilai})
    assert await D.lookup(conn, "bot1", "/nikbyphone", nilai), "baris baru harus dari cache"

    # tuakan barisnya melewati ambang
    async with conn.cursor() as cur:
        await cur.execute(
            "UPDATE bot_query_cache SET tested_at = now() - "
            "((%s + 1) * INTERVAL '1 day') WHERE id = %s", (D.CACHE_HARI, qid))
    assert await D.lookup(conn, "bot1", "/nikbyphone", nilai) is None, (
        "baris kedaluwarsa masih disajikan dari cache")

    # tepat di dalam ambang harus tetap dipakai
    async with conn.cursor() as cur:
        await cur.execute(
            "UPDATE bot_query_cache SET tested_at = now() - "
            "((%s - 1) * INTERVAL '1 day') WHERE id = %s", (D.CACHE_HARI, qid))
    assert await D.lookup(conn, "bot1", "/nikbyphone", nilai) is not None


def test_judul_kelompok_perbandingan_sumber():
    """Bagian "PERBANDINGAN SUMBER" menuliskan field sebagai JUDUL, nilainya
    per sumber di bawahnya. Tanpa mengenali judul itu, yang tersimpan hanya
    record bernama dukcapil_1/wni — pengguna melihat kartu berlabel aneh tanpa
    tahu field apa yang dibandingkan.
    """
    import parser as P

    teks = (
        "NOMOR KK\n  DUKCAPIL_1: 3275022406080115\n  WNI: 3275020210180042\n\n"
        "STATUS KAWIN\n  DUKCAPIL_1: BELUM KAWIN\n  WNI: BELUM KAWIN"
    )
    rec, _ = P.parse_reply(teks)
    judul = [r.get("nama") for r in rec]
    assert "NOMOR KK" in judul and "STATUS KAWIN" in judul, judul
    kk = next(r for r in rec if r.get("nama") == "NOMOR KK")
    assert kk["dukcapil_1"] == "3275022406080115"
