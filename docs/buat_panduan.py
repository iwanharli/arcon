"""Membuat docs/panduan_api_artemis.pdf.

Dokumennya sengaja dibuat dari skrip, bukan diketik di editor PDF, supaya
setiap kali API berubah panduannya bisa dilahirkan ulang persis:

    .venv/bin/pip install reportlab      # hanya untuk membangun dokumen
    .venv/bin/python docs/buat_panduan.py

reportlab TIDAK dimasukkan ke requirements.txt karena tidak dipakai saat API
berjalan — hanya saat menulis ulang panduan ini.
"""
import json
import os
import pathlib
import sys

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (BaseDocTemplate, Frame, NextPageTemplate,
                                PageBreak, PageTemplate, Paragraph, Preformatted,
                                Spacer, Table, TableStyle)

KELUARAN = pathlib.Path(__file__).parent / "panduan_api_artemis.pdf"
VERSI = "Versi 2.0 - 10 September 2026"


def _kunci() -> str:
    """API key produksi, dibaca dari .env saat dokumen dibangun.

    Sengaja TIDAK ditulis di dalam skrip: skrip ini ikut masuk git, sedangkan
    PDF hasilnya justru di-.gitignore karena memuat key tersebut.

    .env di mesin pengembang biasanya memakai key lain dari produksi, jadi saat
    membangun panduan untuk dibagikan isikan key produksinya lewat environment
    variable API_KEY.
    """
    if (dari_env := os.getenv("API_KEY", "").strip()):
        return dari_env
    berkas = pathlib.Path(__file__).parent.parent / ".env"
    try:
        for baris in berkas.read_text(encoding="utf8").splitlines():
            if baris.startswith("API_KEY="):
                return baris.split("=", 1)[1].strip()
    except OSError:
        pass
    return "<API_KEY - isi API_KEY di .env lalu bangun ulang>"


KUNCI = _kunci()

TINTA = colors.HexColor("#1b2430")
AKSEN = colors.HexColor("#8c2f39")
ABU = colors.HexColor("#5c6672")
GARIS = colors.HexColor("#d5d9de")
BLOK = colors.HexColor("#f4f5f7")

ss = getSampleStyleSheet()
S = {
    "judul": ParagraphStyle("judul", parent=ss["Title"], fontName="Helvetica-Bold",
                            fontSize=26, leading=31, textColor=TINTA, spaceAfter=4),
    "subjudul": ParagraphStyle("subjudul", parent=ss["Normal"], fontName="Helvetica",
                               fontSize=13, leading=18, textColor=ABU,
                               alignment=TA_CENTER, spaceAfter=2),
    "bab": ParagraphStyle("bab", parent=ss["Heading1"], fontName="Helvetica-Bold",
                          fontSize=16, leading=20, textColor=TINTA,
                          spaceBefore=14, spaceAfter=8),
    "sub": ParagraphStyle("sub", parent=ss["Heading2"], fontName="Helvetica-Bold",
                          fontSize=12, leading=16, textColor=AKSEN,
                          spaceBefore=12, spaceAfter=5),
    "teks": ParagraphStyle("teks", parent=ss["BodyText"], fontName="Helvetica",
                           fontSize=9.5, leading=14, textColor=TINTA, spaceAfter=6),
    "kecil": ParagraphStyle("kecil", parent=ss["BodyText"], fontName="Helvetica",
                            fontSize=8.5, leading=12, textColor=ABU, spaceAfter=4),
    "kode": ParagraphStyle("kode", parent=ss["Code"], fontName="Courier",
                           fontSize=7.6, leading=10.2, textColor=TINTA,
                           backColor=BLOK, borderPadding=6,
                           leftIndent=0, spaceBefore=3, spaceAfter=8),
}


def P(t, gaya="teks"):
    return Paragraph(t, S[gaya])


def K(t):
    return Preformatted(t.strip("\n"), S["kode"])


def poin(baris):
    isi = "".join(f"<br/>&bull;&nbsp; {b}" for b in baris)
    return P(isi.replace("<br/>", "", 1), "teks")


def tabel(baris, lebar):
    t = Table(baris, colWidths=lebar, hAlign="LEFT")
    t.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8.5),
        ("FONT", (0, 1), (0, -1), "Courier", 8),
        ("FONT", (1, 1), (-1, -1), "Helvetica", 8.5),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BACKGROUND", (0, 0), (-1, 0), TINTA),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BLOK]),
        ("GRID", (0, 0), (-1, -1), 0.4, GARIS),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def kotak(judul, isi, warna=AKSEN):
    t = Table([[Paragraph(f"<b>{judul}</b><br/>{isi}", S["kecil"])]],
              colWidths=[165 * mm], hAlign="LEFT")
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BLOK),
        ("LINEBEFORE", (0, 0), (0, -1), 2.5, warna),
        ("LEFTPADDING", (0, 0), (-1, -1), 9),
        ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return t


def kaki(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(ABU)
    if doc.page > 1:
        canvas.drawString(22 * mm, 287 * mm, "Panduan API - Artemis Telegram Connector")
        canvas.drawRightString(188 * mm, 287 * mm, "RAHASIA / INTERNAL")
        canvas.setStrokeColor(GARIS)
        canvas.line(22 * mm, 284 * mm, 188 * mm, 284 * mm)
    canvas.drawRightString(188 * mm, 12 * mm, f"Halaman {doc.page}")
    canvas.restoreState()


def _katalog_baris():
    """Semua command dari routes.py + docs/skema.json, diurutkan per menu bot.

    Dibaca langsung dari kode, bukan disalin ke dalam dokumen, supaya katalog
    di panduan tidak pernah ketinggalan dari rute yang sebenarnya dilayani.
    """
    sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
    import routes  # noqa: E402 - butuh sys.path di atas

    try:
        skema = json.loads((pathlib.Path(__file__).parent / "skema.json")
                           .read_text(encoding="utf8"))
    except (OSError, ValueError):
        skema = {}

    baris = []
    for (bot, cmd), r in routes.ROUTES.items():
        # Nama menu di bot memuat emoji yang tidak punya rupa di font PDF dan
        # tercetak jadi kotak hitam; hanya bagian ASCII-nya yang dipakai.
        tanda = []
        if r.volatile:
            tanda.append("RT")
        if r.berkas:
            tanda.append("FOTO")
        if skema.get(f"{bot}{cmd}", {}).get("terverifikasi"):
            tanda.append("OK")
        menu = "".join(ch for ch in (r.menu or "") if ch.isascii()).strip()
        baris.append((menu or "(command langsung)", cmd, bot, r.kind or r.target,
                      " ".join(tanda)))
    baris.sort(key=lambda b: (b[0], b[1]))
    return baris


def katalog_command():
    baris = _katalog_baris()
    isi = [["menu di bot", "command", "bot", "jenis data", "sifat"]]
    menu_sebelumnya = None
    for menu, cmd, bot, jenis, tanda in baris:
        # Nama menu hanya dicetak sekali per kelompok supaya kolomnya tidak
        # jadi dinding teks berulang.
        isi.append([menu if menu != menu_sebelumnya else "", cmd, bot, jenis, tanda])
        menu_sebelumnya = menu

    t = Table(isi, colWidths=[46 * mm, 40 * mm, 13 * mm, 34 * mm, 19 * mm],
              hAlign="LEFT", repeatRows=1)
    gaya = [
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 7.5),
        ("FONT", (0, 1), (0, -1), "Helvetica", 7),
        ("FONT", (1, 1), (1, -1), "Courier", 7),
        ("FONT", (2, 1), (-1, -1), "Helvetica", 7),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BACKGROUND", (0, 0), (-1, 0), TINTA),
        ("GRID", (0, 0), (-1, -1), 0.3, GARIS),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]
    # Garis tebal di awal tiap kelompok menu, sebagai ganti judul terpisah.
    for i in range(1, len(isi)):
        if isi[i][0]:
            gaya.append(("LINEABOVE", (0, i), (-1, i), 0.9, TINTA))
    t.setStyle(TableStyle(gaya))
    return t, len(baris)


def isi_dokumen():
    c = []
    # ---------------------------------------------------------------- sampul
    c += [
        Spacer(1, 42 * mm),
        P("PANDUAN TEKNIS API", "subjudul"),
        P("Artemis Telegram Connector", "judul"),
        P("Untuk developer aplikasi Artemis", "subjudul"),
        P(VERSI, "subjudul"),
        Spacer(1, 16 * mm),
        tabel([
            ["Base URL (dari dalam VPS)", "http://127.0.0.1:8765"],
            ["Base URL (dari luar VPS)", "https://be-artemis.kecup.in"],
            ["Header wajib", f"X-API-Key: {KUNCI}"],
            ["Bot data", "bot1 = @teamkhususantibanditbot (140 command)"],
            ["", "bot2 = @Getphoneplusbot (1 command)"],
        ], [52 * mm, 113 * mm]),
        Spacer(1, 8 * mm),
        kotak("Pilih base URL sesuai lokasi aplikasi.",
              "Aplikasi yang berjalan di VPS yang sama (217.76.51.113) memakai "
              "http://127.0.0.1:8765 - lebih cepat, tidak memutar lewat internet. "
              "Aplikasi di luar VPS memakai https://be-artemis.kecup.in. Endpoint, header, "
              "dan bentuk request/response sama persis; hanya awalannya berbeda."),
        Spacer(1, 5 * mm),
        kotak("RAHASIA.", "Dokumen ini memuat API key produksi. Jangan sebarkan ke luar tim."),
        NextPageTemplate("isi"),
        PageBreak(),
    ]

    # -------------------------------------------------------- 1. konsep dasar
    c += [
        P("1. Konsep Dasar", "bab"),
        P("API ini jembatan antara aplikasi Artemis dan <b>2 bot Telegram</b> penyedia data. "
          "Koneksinya memakai akun Telegram biasa (Telethon), bukan bot token - dan satu akun "
          "hanya bisa melayani satu percakapan pada satu waktu. Karena itu permintaan "
          "<b>tidak diproses paralel</b>: setiap pencarian masuk antrian dan dikerjakan satu "
          "worker secara berurutan, dengan jeda 10 detik antar job supaya balasan bot tidak "
          "saling tertukar."),
        P("Alur pemakaian", "sub"),
        poin([
            "Kirim pencarian lewat <font face='Courier'>POST /search/{bot}</font> "
            "(bot ditentukan di path).",
            "Bila nilainya sudah pernah dicari dan <b>umurnya belum 30 hari</b>, hasilnya "
            "langsung dikembalikan saat itu juga (state = done, from_cache = true).",
            "Bila belum ada - atau cache-nya sudah lewat 30 hari - Anda menerima "
            "<font face='Courier'>job_id</font> dan posisi antrian. Ambil hasilnya lewat "
            "<font face='Courier'>GET /jobs/{job_id}</font>, atau pakai long-poll "
            "(<font face='Courier'>?wait=</font>) agar menunggu sampai selesai dalam satu request.",
        ]),
        kotak("Umur cache 30 hari.",
              "Diatur lewat CACHE_HARI di .env. Hasil <i>found</i> yang lebih tua dari itu "
              "dianggap kedaluwarsa dan ditembak ulang ke bot secara otomatis - aplikasi tidak "
              "perlu mengirim force. Command <i>always_fresh</i> tidak pernah dijawab dari cache "
              "sama sekali."),
        Spacer(1, 4 * mm),
        P("Autentikasi", "sub"),
        P("Semua endpoint kecuali <font face='Courier'>GET /health</font> wajib menyertakan "
          "header <font face='Courier'>X-API-Key</font>. Tanpa key yang benar server membalas 401."),
        K(f'curl -H "X-API-Key: {KUNCI}" \\\n     http://127.0.0.1:8765/commands'),
        P("Empat status hasil (field <font face='Courier'>status</font>)", "sub"),
        tabel([
            ["status", "arti"],
            ["found", "data ditemukan, isinya ada di field fields"],
            ["not_found", "bot menjawab tapi datanya tidak ada"],
            ["queue_without_data", "bot baru memberi konfirmasi antrian, hasil final belum datang - coba lagi nanti"],
            ["no_response", "bot tidak menjawab dalam batas waktu - coba lagi"],
        ], [42 * mm, 123 * mm]),
        Spacer(1, 4 * mm),
        P("State job (field <font face='Courier'>state</font>)", "sub"),
        tabel([
            ["state", "arti"],
            ["queued", "menunggu giliran di antrian"],
            ["running", "sedang diproses worker"],
            ["done", "selesai - lihat field status untuk hasilnya"],
            ["failed", "terjadi error saat memproses (lihat field error)"],
        ], [42 * mm, 123 * mm]),
        PageBreak(),
    ]

    # ---------------------------------------------------- 2. daftar endpoint
    c += [
        P("2. Daftar Endpoint", "bab"),
        tabel([
            ["endpoint", "guna"],
            ["POST /search/{bot}", "pencarian dari teks (NIK, nomor HP, nama)"],
            ["POST /search/{bot}/file", "pencarian dari foto (face recognition)"],
            ["GET /jobs/{job_id}", "status/hasil job, bisa long-poll"],
            ["GET /commands", "katalog command + bentuk atributnya"],
            ["GET /queue", "isi antrian saat ini"],
            ["GET /profiles?nama=", "cari profil di database berdasarkan nama"],
            ["GET /profiles/{nik}", "detail profil lewat NIK"],
            ["GET /profiles/id/{id}", "detail profil lewat id (untuk profil tanpa NIK)"],
            ["GET /media/{media_id}", "ambil gambar (foto E-KTP dll)"],
            ["GET /health", "cek API hidup - tanpa API key"],
            ["GET /health/commands", "hasil pengecekan kesehatan command"],
        ], [52 * mm, 113 * mm]),

        P("POST /search/{bot}", "sub"),
        P("Endpoint utama. Bot ditentukan di <b>path</b> (mis. "
          "<font face='Courier'>/search/bot1</font>), bukan di body."),
        tabel([
            ["field", "keterangan"],
            ["cmd", "wajib. command, mis. \"/nikbyphone\" (lihat GET /commands)"],
            ["value", "wajib. nilai yang dicari, mis. NIK / nomor HP / nama"],
            ["requested_by", "opsional. identitas user/modul di Artemis (untuk audit)"],
            ["priority", "opsional. angka; makin besar makin didahulukan (default 0)"],
            ["force", "opsional. true = paksa hit bot walau ada di cache (default false)"],
        ], [30 * mm, 135 * mm]),
        K("""
curl -X POST http://127.0.0.1:8765/search/bot1 \\
  -H "X-API-Key: <API_KEY>" \\
  -H "Content-Type: application/json" \\
  -d '{"cmd":"/nikbyphone","value":"6281234567890",
       "requested_by":"artemis-web"}'
"""),
        P("Respons A - sudah ada di cache dan belum 30 hari (langsung selesai)", "kecil"),
        K("""
{
  "job_id": "", "state": "done", "status": "found",
  "from_cache": true,
  "fields": [ { "nik": "3201010101010001", "nama": "BUDI SANTOSO",
                "nomor": "6281234567890", "provider": "telkomsel" } ],
  "error": null
}
"""),
        P("Respons B - belum ada, masuk antrian", "kecil"),
        K("""
{
  "job_id": "98b6dd4b-d072-4268-ade5-84f5bb8707b4",
  "state": "queued", "status": null, "queue_position": 1,
  "from_cache": false, "fields": null, "error": null
}
"""),
        PageBreak(),

        P("POST /search/{bot}/file", "sub"),
        P("Pencarian yang masukannya <b>berkas foto</b>, bukan teks - dipakai command "
          "<font face='Courier'>/fr</font> dan <font face='Courier'>/frsocmed</font>. "
          "Dikirim sebagai <font face='Courier'>multipart/form-data</font>, bukan JSON."),
        tabel([
            ["field", "keterangan"],
            ["cmd", "wajib. /fr atau /frsocmed"],
            ["file", "wajib. berkas gambar, maksimal 8 MB"],
            ["requested_by", "opsional. identitas user/modul"],
            ["priority", "opsional. angka prioritas antrian"],
        ], [30 * mm, 135 * mm]),
        K("""
curl -X POST http://127.0.0.1:8765/search/bot1/file \\
  -H "X-API-Key: <API_KEY>" \\
  -F "cmd=/fr" \\
  -F "requested_by=artemis-web" \\
  -F "file=@wajah.jpg"
"""),
        kotak("Tipe berkas diperiksa dari isinya, bukan dari header.",
              "Beberapa klien HTTP mengirim Content-Type application/octet-stream untuk file "
              "yang jelas-jelas JPEG. Server menyimpulkan tipe gambar dari magic byte, jadi "
              "kiriman seperti itu tetap diterima. Yang bukan gambar ditolak 400."),
        Spacer(1, 4 * mm),
        P("Balasannya sama bentuknya dengan POST /search/{bot}: job_id + posisi antrian, lalu "
          "hasilnya diambil lewat GET /jobs/{job_id}. Berkas identik (sha256 sama) dipakai ulang "
          "dari penyimpanan, tidak diunggah dua kali."),

        P("GET /jobs/{job_id}", "sub"),
        P("Mengambil status atau hasil sebuah job. Query parameter "
          "<font face='Courier'>wait</font> (0-300 detik): >0 = tunggu sampai job selesai dalam "
          "request ini; 0 = balas kondisi saat ini juga."),
        K("""
# ambil sekali (non-blocking)
curl -H "X-API-Key: <API_KEY>" http://127.0.0.1:8765/jobs/<job_id>

# tunggu sampai selesai, maks 120 detik
curl -H "X-API-Key: <API_KEY>" \\
     "http://127.0.0.1:8765/jobs/<job_id>?wait=120"
"""),
        K("""
{
  "job_id": "98b6dd4b-d072-4268-ade5-84f5bb8707b4",
  "state": "done", "status": "found",
  "queue_position": null, "from_cache": false,
  "fields": [
    { "nik": "3201010101010002", "nama": "SITI RAHAYU",
      "shdk": "ANAK", "ttl": "DEPOK, 02/08/2003" },
    { "nik": "3201010101010003", "nama": "AGUS WIJAYA",
      "shdk": "ANAK", "ttl": "DEPOK, 04/03/2001" }
  ],
  "error": null
}
"""),
        kotak("Field fields bisa OBJECT tunggal atau ARRAY of object.",
              "Satu nomor HP lazim terdaftar atas beberapa NIK, dan face recognition "
              "mengembalikan belasan kandidat - masing-masing jadi satu object dengan field "
              "<font face='Courier'>nik</font> sendiri. Cek tipenya sebelum parsing, dan "
              "kelompokkan per NIK sebelum ditampilkan supaya atribut milik orang berbeda tidak "
              "terbaca sebagai satu berkas."),
        PageBreak(),

        P("GET /commands", "sub"),
        P("Katalog semua command yang bisa dipanggil, dikelompokkan per bot."),
        tabel([
            ["field", "keterangan"],
            ["cmd", "nama command yang dikirim di body /search"],
            ["target", "muara datanya: profiles atau records"],
            ["kind", "jenis catatan (device, face, number_info, ...) - boleh null"],
            ["always_fresh", "true = SELALU menembak bot, tidak pernah dari cache"],
            ["menu", "null = command teks biasa; berisi teks = command lewat menu tombol bot"],
            ["atribut", "daftar field yang pernah dihasilkan command ini"],
            ["terverifikasi", "false = belum pernah menghasilkan data, jadi atribut belum diketahui"],
        ], [32 * mm, 133 * mm]),
        K("""
{
  "bot1": [
    { "cmd": "/nikbyphone", "target": "profiles", "kind": null,
      "always_fresh": false, "menu": "NIK BY PHONE",
      "atribut": ["nik","nama","nomor","provider","alamat", "..."],
      "terverifikasi": true },
    { "cmd": "/track", "target": "records", "kind": "device",
      "always_fresh": true, "menu": "TRACKING PHONE", "atribut": ["..."],
      "terverifikasi": true }
  ],
  "bot2": [
    { "cmd": "/getphone", "target": "records", "kind": "number_info",
      "always_fresh": true, "menu": null, "atribut": ["..."],
      "terverifikasi": true }
  ]
}
"""),
        kotak("Jangan hardcode daftar command di aplikasi.",
              "Katalog ini dibaca dari docs/skema.json yang ikut tumbuh setiap kali sebuah "
              "command menghasilkan data baru. Ambil dari endpoint ini dan simpan sebentar di "
              "memori (mis. 5 menit) supaya aplikasi ikut terbarui tanpa deploy ulang."),
        Spacer(1, 4 * mm),

        P("GET /queue", "sub"),
        P("Isi antrian saat ini (job queued + running). Parameter "
          "<font face='Courier'>limit</font> (1-200, default 20)."),
        K("""
{
  "total": 2,
  "jobs": [
    { "job_id": "...", "bot": "bot1", "cmd": "/nikbyphone",
      "value": "6281...", "state": "running", "priority": 0,
      "requested_by": "artemis-web" }
  ]
}
"""),
        PageBreak(),

        P("GET /profiles?nama=", "sub"),
        P("Mencari profil di database berdasarkan sebagian nama - tanpa menyentuh Telegram, "
          "jadi cepat dan tidak memakan kuota bot. Parameter "
          "<font face='Courier'>nama</font> (wajib, minimal 2 huruf) dan "
          "<font face='Courier'>limit</font> (1-100, default 20)."),
        K("""
{
  "total": 1,
  "profil": [
    { "id": 214, "nik": "3201010101010001", "nama": "BUDI SANTOSO",
      "tempat_lahir": "BEKASI", "tanggal_lahir": "2006-03-05",
      "kab_kota": "KOTA DEPOK", "updated_at": "2026-09-09T23:27:38+07:00" }
  ]
}
"""),
        kotak("Kenapa perlu id, bukan cukup NIK?",
              "Hasil pencarian by-nama sering tidak menyertakan NIK, sehingga profil seperti itu "
              "tidak bisa diambil lewat GET /profiles/{nik} sama sekali. Pakai "
              "<font face='Courier'>id</font> dari sini lalu panggil "
              "<font face='Courier'>GET /profiles/id/{id}</font>."),
        Spacer(1, 4 * mm),

        P("GET /profiles/{nik} &nbsp;&nbsp;dan&nbsp;&nbsp; GET /profiles/id/{id}", "sub"),
        P("Detail satu profil langsung dari database. Balas 404 bila belum pernah ditemukan."),
        K("""
{
  "profil": {
    "nik": "3201010101010001", "kk": "3201010101010009",
    "nama": "BUDI SANTOSO", "tempat_lahir": "BEKASI",
    "tanggal_lahir": "2006-03-05", "jenis_kelamin": "PEREMPUAN",
    "alamat": "JL MELATI NO 4", "rt": "7", "rw": "13",
    "kel_desa": "SUKAMAJU", "kecamatan": "CILODONG",
    "kab_kota": "KOTA DEPOK", "provinsi": "JAWA BARAT"
  },
  "telepon":   [ { "msisdn": "6281234567890", "operator": "TELKOMSEL" } ],
  "kendaraan": [],
  "catatan":   [ { "kind": "device", "data": { "...": "..." } } ]
}
"""),
        P("Bedanya dengan /search: di sini alamat sudah dinormalisasi (RT/RW jadi field sendiri, "
          "tanggal lahir jadi format ISO), sedangkan /search mengembalikan bentuk apa adanya dari "
          "bot.", "kecil"),

        P("GET /media/{media_id}", "sub"),
        P("Menyajikan gambar (foto E-KTP, foto kandidat) sebagai berkas biner. Id-nya muncul di "
          "field <font face='Courier'>media</font> pada hasil pencarian, berbentuk "
          "<font face='Courier'>/media/&lt;id&gt;</font> - tinggal ditempel di belakang base URL. "
          "Tetap perlu API key."),

        P("GET /health &nbsp;dan&nbsp; GET /health/commands", "sub"),
        K("""
GET /health            -> { "ok": true, "antrian": { "done": 35 } }

GET /health/commands   -> { "total": 40, "sehat": 5, "bermasalah": 34,
                            "belum_dicek": 1, "commands": [
     { "bot": "bot1", "cmd": "/bpjs", "probe_value": "3507...",
       "expect_status": "not_found", "enabled": true,
       "last_status": "no_response", "ok": false,
       "consecutive_failures": 3, "last_checked_at": "..." } ] }
"""),
        P("<font face='Courier'>total</font> di sini menghitung command yang <b>punya nilai uji</b>, "
          "bukan seluruh 141 command - sisanya tidak ikut dicek karena setiap pengecekan memakan "
          "kuota bot. ", "kecil"),
        P("<font face='Courier'>/health</font> tidak perlu API key - cocok untuk uptime monitor. "
          "<font face='Courier'>/health/commands</font> memuat hasil pengecekan harian; parameter "
          "<font face='Courier'>hanya_bermasalah=true</font> menyaring yang gagal saja. Ada juga "
          "halaman visual di <font face='Courier'>/monitor</font> (buka di browser, masukkan API "
          "key sekali).", "kecil"),
        PageBreak(),
    ]

    # --------------------------------------------- 3. tiga fitur yang dipakai
    c += [
        P("3. Tiga Fitur yang Dipakai Artemis", "bab"),
        P("Dari 141 command yang tersedia, aplikasi Artemis hanya memakai tiga. Bagian ini "
          "merangkum perilakunya supaya integrasi tidak perlu menebak."),
        tabel([
            ["command", "masukan", "sifat"],
            ["/nikbyphone", "nomor HP", "identitas dari nomor - dicache 30 hari"],
            ["/fr", "foto wajah", "face recognition - dicache per sha256 foto"],
            ["/track", "nomor HP", "lokasi & perangkat - always_fresh, selalu real-time"],
        ], [32 * mm, 32 * mm, 101 * mm]),

        P("/nikbyphone - identitas dari nomor HP", "sub"),
        P("Satu nomor bisa terdaftar atas <b>beberapa NIK</b> (pemilik, keluarga, bekas pemilik). "
          "Hasilnya berupa array; tiap object membawa field "
          "<font face='Courier'>nik</font> sendiri. Kelompokkan per NIK sebelum ditampilkan."),

        P("/fr - face recognition", "sub"),
        P("Dikirim lewat <font face='Courier'>POST /search/bot1/file</font>. Bot membalas "
          "sederet <b>kandidat wajah yang mirip</b> dalam bentuk tombol; connector menelusuri "
          "tombol itu satu per satu dan mengambil detail tiap kandidat, sampai maksimal 10 "
          "kandidat. Semuanya masuk ke satu hasil sebagai array - satu object per NIK kandidat, "
          "lengkap dengan tingkat kemiripannya."),
        kotak("Sekali kirim, banyak kandidat.",
              "Aplikasi tidak perlu mengirim ulang per kandidat. Satu job "
              "<font face='Courier'>/fr</font> menghasilkan seluruh kandidat sekaligus; yang "
              "perlu dilakukan hanya memisahkan array-nya per NIK saat menampilkan."),
        Spacer(1, 4 * mm),

        P("/track - lokasi & perangkat", "sub"),
        P("Ditandai <font face='Courier'>always_fresh</font>, jadi <b>tidak pernah dijawab dari "
          "cache</b> - setiap panggilan menembak bot. Perlakukan waktunya lebih lama daripada dua "
          "command lain, dan jangan panggil berulang untuk nomor yang sama dalam waktu dekat."),

        PageBreak(),
        P("4. Endpoint Pendukung Aplikasi", "bab"),
        P("Di luar pencarian, API ini juga menyimpan kebutuhan aplikasi Artemis sendiri: akun "
          "pengguna, riwayat sesi, dan log aktivitas. Semuanya tetap butuh "
          "<font face='Courier'>X-API-Key</font>."),
        tabel([
            ["endpoint", "guna"],
            ["POST /auth/login", "verifikasi username + password"],
            ["GET/POST /auth/users", "daftar & pembuatan akun"],
            ["POST /auth/users/{u}/password", "ganti kata sandi"],
            ["POST /auth/users/{u}/role", "ganti peran akun"],
            ["DELETE /auth/users/{u}", "hapus akun"],
            ["POST /app/sessions/upsert", "simpan/perbarui satu sesi pencarian"],
            ["GET /app/sessions?user=", "riwayat sesi milik satu user"],
            ["GET /app/sessions/{sid}?user=", "isi satu sesi"],
            ["DELETE /app/sessions?user=", "kosongkan riwayat user"],
            ["POST /app/logs", "catat aktivitas (login/logout/search/export)"],
            ["GET /app/logs", "baca log; tanpa username = semua user"],
            ["GET /app/cached", "baris cache terbaru untuk (bot, cmd, value) - tanpa Telegram"],
        ], [62 * mm, 103 * mm]),
        P("<font face='Courier'>GET /app/cached</font> berguna untuk tombol \"periksa ulang\": ia "
          "membaca hasil yang sudah tersimpan tanpa menembak bot, dan ikut mengembalikan "
          "<font face='Courier'>raw_text</font> - balasan mentah dari bot - untuk keperluan debug.",
          "kecil"),
    ]

    # ------------------------------------------------------ 5. contoh & tips
    c += [
        PageBreak(),
        P("5. Contoh Integrasi", "bab"),
        P("Node.js / JavaScript - pencarian teks", "sub"),
        K("""
const BASE = "http://127.0.0.1:8765";
const KEY  = "<API_KEY>";

async function cariNomor(nomor) {
  // 1. kirim pencarian
  const r = await fetch(`${BASE}/search/bot1`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-API-Key": KEY },
    body: JSON.stringify({ cmd: "/nikbyphone", value: nomor,
                           requested_by: "artemis-web" }),
  });
  const job = await r.json();

  // 2. kalau dari cache, hasil langsung ada
  if (job.state === "done") return job;

  // 3. kalau masuk antrian, tunggu hasilnya (long-poll)
  const res = await fetch(`${BASE}/jobs/${job.job_id}?wait=120`,
                          { headers: { "X-API-Key": KEY } });
  return await res.json();
}
"""),
        P("Node.js - pencarian dari foto (face recognition)", "sub"),
        K("""
async function cariWajah(fileBlob) {
  const fd = new FormData();
  fd.append("cmd", "/fr");
  fd.append("requested_by", "artemis-web");
  fd.append("file", fileBlob, "wajah.jpg");

  const r = await fetch(`${BASE}/search/bot1/file`, {
    method: "POST",
    headers: { "X-API-Key": KEY },   // JANGAN set Content-Type sendiri
    body: fd,
  });
  const job = await r.json();
  if (job.state === "done") return job;

  const res = await fetch(`${BASE}/jobs/${job.job_id}?wait=180`,
                          { headers: { "X-API-Key": KEY } });
  return await res.json();   // fields = array kandidat, satu object per NIK
}
"""),
        PageBreak(),
        P("PHP (cURL)", "sub"),
        K("""
function cariNomor($nomor) {
  $base = "http://127.0.0.1:8765"; $key = "<API_KEY>";
  $ch = curl_init("$base/search/bot1");
  curl_setopt_array($ch, [
    CURLOPT_POST => true,
    CURLOPT_RETURNTRANSFER => true,
    CURLOPT_HTTPHEADER => ["Content-Type: application/json",
                           "X-API-Key: $key"],
    CURLOPT_POSTFIELDS => json_encode([
      "cmd" => "/nikbyphone", "value" => $nomor,
      "requested_by" => "artemis-web"]),
  ]);
  $job = json_decode(curl_exec($ch), true);
  if ($job["state"] === "done") return $job;

  $id = $job["job_id"];
  $ch2 = curl_init("$base/jobs/$id?wait=120");
  curl_setopt_array($ch2, [
    CURLOPT_RETURNTRANSFER => true,
    CURLOPT_HTTPHEADER => ["X-API-Key: $key"]]);
  return json_decode(curl_exec($ch2), true);
}
"""),
        P("6. Tips Penanganan", "bab"),
        poin([
            "Selalu cek field <font face='Courier'>state</font> lebih dulu: baru kalau "
            "<font face='Courier'>done</font> bacalah <font face='Courier'>status</font> dan "
            "<font face='Courier'>fields</font>.",
            "<font face='Courier'>queue_without_data</font> dan "
            "<font face='Courier'>no_response</font> <b>bukan error permanen</b>: beri jeda "
            "lalu kirim ulang permintaan yang sama. Bedakan pesannya di UI dari "
            "<font face='Courier'>not_found</font>, yang berarti datanya memang tidak ada.",
            "<font face='Courier'>fields</font> bisa object ATAU array - cek tipenya dulu, dan "
            "kelompokkan per <font face='Courier'>nik</font> saat menampilkan.",
            "Jangan hardcode daftar command; ambil dari "
            "<font face='Courier'>GET /commands</font> dan cache 5 menit.",
            "Untuk data yang jarang berubah, cukup POST /search biasa - sistem menjawab dari "
            "cache bila umurnya belum 30 hari, dan menembak bot lagi bila sudah lewat. "
            "<font face='Courier'>force</font> hampir tidak pernah perlu.",
            "Antriannya serial dengan jeda 10 detik antar job. Jangan kirim puluhan pencarian "
            "sekaligus lalu menunggu semuanya - kirim bertahap, atau pakai "
            "<font face='Courier'>priority</font> untuk yang mendesak.",
            "Batas berkas 8 MB, dan hanya gambar. Kompres foto di sisi klien bila perlu.",
            "Akses dari luar VPS dijaga API key + rate limit 10 request/detik per IP + TLS. "
            "Port mentah 8765 tertutup dari internet.",
        ]),
    ]

    # ---------------------------------------------------- 7. katalog command
    tabel_katalog, jumlah = katalog_command()
    c += [
        PageBreak(),
        P("7. Katalog Lengkap Command", "bab"),
        P(f"Artemis sendiri hanya memakai tiga command, tetapi connector melayani "
          f"<b>{jumlah} command</b> - semuanya bisa dipanggil lewat endpoint yang sama. "
          "Daftar ini dibangkitkan langsung dari rute yang dilayani, jadi tidak akan "
          "ketinggalan dari kenyataan; sumber yang selalu paling mutakhir tetap "
          "<font face='Courier'>GET /commands</font>."),
        kotak("Command bermenu dipanggil sama saja.",
              "Sebagian besar command di bawah sebenarnya bukan perintah teks, melainkan "
              "rangkaian klik pada menu tombol bot (mis. MONITORING TEKAB &rarr; Trace Number). "
              "Aplikasi tidak perlu tahu itu: cukup kirim "
              "<font face='Courier'>{\"cmd\":\"/tracenumber\",\"value\":\"...\"}</font> dan "
              "connector yang menelusuri menunya."),
        Spacer(1, 3 * mm),
        tabel([
            ["tanda", "arti"],
            ["RT", "always_fresh - selalu real-time, tidak pernah dijawab dari cache"],
            ["FOTO", "masukannya berkas gambar, lewat POST /search/{bot}/file"],
            ["OK", "sudah terverifikasi: pernah menghasilkan data, atribut diketahui"],
        ], [22 * mm, 143 * mm]),
        Spacer(1, 3 * mm),
        P("Kolom <b>jenis data</b> memakai <font face='Courier'>kind</font> dari "
          "<font face='Courier'>GET /commands</font>; bila command itu mengisi profil orang "
          "(bukan catatan), yang tertulis adalah muaranya: "
          "<font face='Courier'>profiles</font>, <font face='Courier'>phones</font>, atau "
          "<font face='Courier'>vehicles</font>.", "kecil"),
        Spacer(1, 3 * mm),
        tabel_katalog,
        Spacer(1, 4 * mm),
        kotak("Tanpa tanda OK bukan berarti command-nya rusak.",
              "Itu hanya berarti command tersebut belum pernah dipanggil dengan nilai yang "
              "menghasilkan data, sehingga daftar atributnya belum terbentuk. Begitu sekali saja "
              "berhasil, atributnya otomatis masuk katalog dan ikut muncul di "
              "<font face='Courier'>GET /commands</font>."),
    ]
    return c


def main():
    doc = BaseDocTemplate(str(KELUARAN), pagesize=A4,
                          title="Panduan API - Artemis Telegram Connector",
                          author="Artemis Telegram Connector", subject=VERSI,
                          leftMargin=22 * mm, rightMargin=22 * mm,
                          topMargin=20 * mm, bottomMargin=18 * mm)
    sampul = Frame(22 * mm, 18 * mm, 166 * mm, 259 * mm, id="sampul")
    isi = Frame(22 * mm, 18 * mm, 166 * mm, 260 * mm, id="isi")
    doc.addPageTemplates([
        PageTemplate(id="sampul", frames=[sampul], onPage=kaki),
        PageTemplate(id="isi", frames=[isi], onPage=kaki),
    ])
    doc.build(isi_dokumen())
    print(f"ditulis: {KELUARAN} ({KELUARAN.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
