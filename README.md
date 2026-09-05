# artemis-tele-connector

Connector Telethon untuk baca/tulis ke 3 bot Telegram dari satu akun user.

## Kenapa akun user, bukan bot token
Bot Telegram tidak bisa mengirim pesan ke bot lain. Jadi login memakai
akun user (`api_id` + `api_hash` + nomor HP), lalu akun itu yang chat ke bot.

## Setup
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # isi TG_API_ID, TG_API_HASH, TG_PHONE, BOT_1..BOT_3
python main.py login   # masukkan kode OTP sekali; session tersimpan
```
`TG_API_ID`/`TG_API_HASH` diambil di https://my.telegram.org → API development tools.

## Pakai
```bash
python main.py send bot1 "halo"
python main.py ask  bot1 "/start"
python main.py ask-all "/status"
python main.py history bot2 10
python main.py listen
```

## Sebagai library
```python
import asyncio
from connector import TelegramConnector

async def main():
    async with TelegramConnector() as tg:
        await tg.send("bot1", "halo")
        msgs = await tg.ask("bot2", "/status", timeout=20, collect=2)
        print([m.text for m in msgs])
        hasil = await tg.ask_all("/ping")   # ketiga bot paralel

asyncio.run(main())
```

## API untuk aplikasi Artemis

```bash
psql -d db_artemis -f migrations/002_search_jobs.sql
uvicorn api:app --host 127.0.0.1 --port 8000
```

Satu akun Telegram hanya bisa melayani satu percakapan efektif pada satu waktu,
jadi permintaan **tidak** diproses paralel: API menerima input, menaruhnya di
antrian, dan satu worker mengerjakannya berurutan.

```
POST /search  {"bot":"bot1","cmd":"/nik","value":"327...","requested_by":"artemis-web"}

  sudah ada di cache -> {"state":"done","status":"found","from_cache":true,"fields":{...}}
  belum ada          -> {"job_id":"1b1b...","state":"queued","queue_position":3}

GET /search/{job_id}            -> pantau statusnya
GET /search/{job_id}?wait=120   -> long-poll, tunggu sampai selesai (maks 300 detik)
```

| Endpoint | Kegunaan |
|---|---|
| `POST /search` | kirim pencarian (cache dulu, kalau tidak ada baru masuk antrian) |
| `GET /search/{job_id}` | ambil status/hasil, opsional `?wait=` untuk long-poll |
| `GET /queue` | isi antrian saat ini |
| `GET /commands` | daftar command yang tersedia per bot |
| `GET /profiles/{nik}` | profil dari database, tanpa menyentuh Telegram |
| `GET /health` | cek API + ringkasan antrian |

`state` job: `queued` → `running` → `done`/`failed`. `status` hasil memakai 4
nilai yang sama dengan tabel cache (`found`, `not_found`, `queue_without_data`,
`no_response`). Isi `API_KEY` di `.env` kalau mau mewajibkan header
`X-API-Key`.

Prioritas: kirim `"priority": 10` untuk menyalip antrian (default `0`).

## Pengecekan command berkala (harian)

```bash
psql -d db_artemis -f migrations/003_command_health.sql

python healthcheck.py            # cek semua command yang punya probe
python healthcheck.py bot3       # satu bot saja
python healthcheck.py --report   # lihat hasil terakhir, tanpa menyentuh Telegram
```

Penjadwalan harian dilakukan saat deploy di VPS memakai pm2 (`cron_restart`
menjalankan ulang script tiap hari jam 03:00, `autorestart: false` supaya tidak
langsung jalan lagi setelah selesai):

```js
// ecosystem.config.js
{
  name: "artemis-healthcheck",
  script: ".venv/bin/python",
  args: "healthcheck.py",
  cwd: "/path/artemis-tele-connector",
  autorestart: false,
  cron_restart: "0 3 * * *",
}
```

Tiga tabel yang dipakai:

| Tabel | Isi |
|---|---|
| `command_probes` | nilai probe per command + status yang dianggap sehat |
| `command_health_checks` | riwayat tiap pengecekan (untuk melihat sejak kapan mati) |
| `command_health` | ringkasan terkini + hitungan gagal beruntun |
| `command_bermasalah` (view) | command yang gagal ≥ 2 kali beruntun |

Pantau lewat halaman **`/monitor`** (buka di browser) atau `GET /health/commands`
(tambah `?hanya_bermasalah=true`).

Halaman `/monitor` menampilkan ringkasan aktif/bermasalah/belum-dicek, tabel
seluruh command dengan hitungan gagal beruntun, filter, dan muat ulang otomatis
tiap 60 detik. API key dimasukkan sekali lalu disimpan di `localStorage`
browser. Daftarnya diambil dari `command_probes` (bukan `command_health`),
supaya command yang belum pernah dicek tetap terlihat — kalau tidak, dashboard
terlihat "semua aman" padahal baru sebagian yang diperiksa.

**Kenapa perlu tabel probe.** Supaya hasilnya berarti, tiap command diuji
dengan nilai yang sudah terbukti kondisinya — bukan nilai sembarangan. Tanpa
itu, `not_found` jadi ambigu: entah command rusak, entah datanya memang tidak
ada. Contoh nyata dari pengujian: `/dosen "Siti Aminah"` selalu `not_found`
karena nama itu karangan, padahal commandnya sehat. Kolom `expect_status`
menyimpan hasil yang dianggap normal untuk probe tersebut — untuk sebagian
command, jawaban "tidak ditemukan" yang tegas justru bukti bot masih hidup.

Dua hal yang membuat laporannya bisa dipercaya:

* **Selalu `force=True`** — pengecekan wajib menembak bot sungguhan. Kalau
  membaca cache, ia hanya membuktikan isi database, bukan kondisi bot. Satu
  putaran penuh = 46 hit, jadi memang menghabiskan kuota.
* **Timeout longgar (120 detik)**, jauh di atas `BOT_TIMEOUT` biasa. Saat
  diuji dengan timeout 30 detik, `/nik` sempat dilaporkan mati padahal sehat —
  jawabannya cuma telat. Alarm palsu semacam itu membuat laporan tidak
  dipercaya.

### Kenapa ada pengawal korelasi

Bot membalas tanpa `reply_to`, jadi balasan hanya bisa dicocokkan lewat urutan
waktu. Kalau jawaban permintaan sebelumnya datang terlambat, ia bisa jatuh ke
jendela tunggu permintaan berikutnya — pernah terjadi saat pengujian: query
`/bionik <nik>` menerima data registrasi HP milik NIK lain, dan sempat
tersimpan sebagai hasil yang sah.

`service.relates_to_request()` membandingkan identitas di balasan dengan input
yang diminta. Kalau jelas berbeda, hasilnya dibuang dan job ditandai
`queue_without_data` supaya dicoba ulang — bukan `found`, agar data orang lain
tidak masuk ke profil.

## Database (db_artemis)

Hasil query disimpan di Postgres dengan dua lapis: `bot_query_cache` (mentah,
sumber kebenaran & jejak audit) dan `profiles` + turunannya (hasil normalisasi,
bisa di-rebuild ulang dari lapis mentah).

```bash
createdb db_artemis
psql -d db_artemis -f migrations/001_init.sql
# lalu isi PG_DSN di .env (default: postgresql:///db_artemis)
```

Alur cache — hemat kuota tanpa menyajikan data basi:

| Kondisi di cache | Aksi |
|---|---|
| `found`, command biasa | pakai cache, **tidak** hit Telegram |
| `not_found` | hit Telegram lagi (siapa tahu datanya sudah ada) |
| `queue_without_data` | hit Telegram lagi (hasil final belum sempat tertangkap) |
| `no_response` | hit Telegram lagi |
| command *volatile* (`/track`, `/cptsel`, `/lm`, `/pln`, `/cekinfo`, …) | selalu hit Telegram walau `found` — lokasi & masa aktif berubah terus |

Pemakaian lewat CLI:

```bash
python main.py query bot1 /nik 3201010101010001            # cache dulu
python main.py query bot1 /nik 3201010101010001 --force    # paksa hit Telegram
```

Atau sebagai library — `service.query()` mengurus seluruh alurnya:

```python
import db, service

async with TelegramConnector() as tg:
    conn = await db.connect()
    hasil = await service.query(tg, conn, "bot1", "/nik", nik)
    print(hasil["from_cache"], hasil["status"], hasil["fields"])
```

Yang terjadi di dalam `service.query()`:

1. `db.lookup()` — kalau `found` dan command tidak volatile, selesai di sini.
2. `tg.ask()` — hit bot.
3. `parser.classify()` — teks balasan jadi record + status (4 status di atas).
4. Kalau kena rate limit (`"Please wait 19 second(s)"`), tunggu lalu ulangi
   sekali — jangan sampai kondisi sementara terkunci jadi `not_found` di cache.
5. `db.store_result()` — simpan mentah ke cache, lalu normalisasi
   ([normalize.py](normalize.py)) dan salurkan ke tabel yang tepat sesuai
   [routes.py](routes.py). Upsert `profiles` memakai `COALESCE` supaya nilai
   kosong (`-`, `0`, nilai ter-mask) tidak menimpa data yang sudah bagus.

| Modul | Tugas |
|---|---|
| [connector.py](connector.py) | kirim/terima pesan Telegram (tidak tahu soal cache) |
| [parser.py](parser.py) | teks balasan bot -> record terstruktur + status |
| [normalize.py](normalize.py) | seragamkan format antar-bot (alamat, tanggal, nomor HP) |
| [routes.py](routes.py) | command -> normalizer + tabel tujuan |
| [db.py](db.py) | cache lookup + upsert ke db_artemis |
| [service.py](service.py) | rangkai semuanya jadi satu alur query |

## Test fitur bot

Ada test integrasi (pakai koneksi live, bukan mock) untuk mencoba semua
command yang terdaftar di bagian "Bot yang sudah terkoneksi" di atas.

```bash
cp tests/values.example.py tests/values.py   # isi nilai testmu sendiri di sini
pytest -s                                     # -s supaya balasan bot ikut tercetak
pytest -s tests/test_bot1.py                  # test satu bot saja
pytest -s -k nik                              # test command tertentu saja
```

- `tests/values.py` punya variabel identitas dasar (`NIK`, `KK`, `NAMA`, `HP`,
  `GURU_NAMA`, dst.) di bagian atas — isi sekali, otomatis dipakai ulang ke
  semua command bot1 & bot3 yang butuh input sama, jadi tidak perlu ketik
  data yang sama berkali-kali. Command yang formatnya beda antar bot (mis.
  `/bpjs` di bot1 dan bot3 sama-sama minta **NIK** 16 digit meski nama
  command-nya BPJS) langsung dipetakan ke variabel yang sama, `NIK`.
- Dict `BOT1`/`BOT2`/`BOT3` di bagian bawah cuma memetakan command ke
  variabel di atas. Command dengan value `None` otomatis di-skip.
- File ini masuk `.gitignore` (bisa berisi data pribadi/sensitif) — yang
  di-commit hanya template `tests/values.example.py`.
- Test benar-benar mengirim pesan ke bot asli lewat akun user yang sudah
  login (`python main.py login`), jadi bisa memotong kuota/kredit dan kena
  rate limit kalau dijalankan berulang-ulang.

## Catatan
- `ask()` menunggu balasan lewat event handler, bukan polling — aman terhadap
  bot yang balas lambat. Kalau bot membalas beberapa pesan beruntun, naikkan
  `collect`.
- File `.session` = kredensial login. Sudah masuk `.gitignore`, jangan di-commit.
- Jangan kirim pesan bertubi-tubi; Telethon otomatis menangani `FloodWaitError`
  singkat, tapi rate limit tetap berlaku.

## Bot yang sudah terkoneksi

Dicek langsung via `ask-all` / `ask` (2026-09-04). Ketiganya adalah bot data
pencarian/OSINT — gunakan hanya untuk keperluan yang sah dan terotorisasi.

### bot1 — `cielodespejadobot`
Bot pencarian data kependudukan & kendaraan, command langsung (tanpa menu
tombol).

| Command | Fungsi |
|---|---|
| `/start` | Memulai bot |
| `/help` | Menampilkan daftar perintah |
| `/nik <nik>` | Demografi dari NIK |
| `/kk <kk>` | Kartu Keluarga |
| `/nama <nama>` | Demografi dari nama |
| `/bionik <nik>` | Biodata dari NIK |
| `/biokk <kk>` | Biodata dari Kartu Keluarga |
| `/bionama <nama>` | Biodata dari nama |
| `/foto <nik>` | Foto (E-KTP) |
| `/reg <hp>` | Registrasi nomor HP |
| `/nohp <nik>` | Registrasi no. HP dari NIK |
| `/profnumber <hp>` | Profiling nomor HP |
| `/tnkb <nopol>` | Cek kendaraan dari nomor polisi |
| `/nosin <mesin>` | Cek kendaraan dari nomor mesin |
| `/noka <rangka>` | Cek kendaraan dari nomor rangka |
| `/niknopol <nik>` | Cek kendaraan dari NIK |
| `/namanopol <nama>` | Cek kendaraan dari nama |
| `/bpjs <nik>` | Cek BPJS |
| `/wsid <wsid>` | Cek WSID |
| `/dpo <nama>` | Cek DPO |
| `/pln <idpel>` | Cek PLN |
| `/guru <nama>` | Cek data guru |
| `/dosen <nama>` | Cek data dosen |
| `/mahasiswa <nama>` | Cek data mahasiswa |
| `/fr` | Face Recognition |

### bot2 — `mahalini2bot`
"CP Bot" — khusus cek nomor HP via provider, satu command inti. Request
diproses lewat antrian (satu per satu) agar hasil akurat.

| Command | Fungsi |
|---|---|
| `/cp <628xxxxxxxxxx>` | Cek CP (nomor HP), alternatif tanpa slash: `cp 08xxxxxxxxxx` |
| `/kredit` | Cek sisa kredit/kuota akun (butuh izin admin — akun uji saat ini menampilkan "quota tidak tersedia") |

### bot3 — `cleojktbot`
"cleo Control Center" — menu berbasis tombol inline (`/menu` atau `/start`),
menampilkan status akses (plan & masa berlaku) lalu kategori Lokasi dan
Profiling. Semua command menampilkan contoh format sebelum masuk antrian.

Kategori **Lokasi**:

| Command | Fungsi |
|---|---|
| `/cptsel <62856xxxx>` | Lokasi nomor Telkomsel |
| `/track <62856xxxx>` | Lokasi nomor (alias umum) |
| `/lm <6285xxxxx>` | Linimasa lokasi Telkomsel |

Kategori **Profiling**:

| Command | Fungsi |
|---|---|
| `/prof <62812345xxxx>` | Profil nomor HP |
| `/cekinfo <628xxx>` | Info masa aktif nomor HP |
| `/reg <62819xxxx>` | Data registrasi nomor HP |
| `/kk <3318xxxxxxxxxxxx>` | Data Kartu Keluarga |
| `/nik <314xxxxxxxxxxxxx>` | Data NIK |
| `/nohp <nik#N>` | Nomor HP berdasarkan NIK |
| `/nama <nama#N>` | Pencarian berdasarkan nama |
| `/photo <nik>` | Foto E-KTP |
| `/bpjs <nik 16 digit>` | No. HP dari data BPJS (input NIK, bukan nomor BPJS) |
| `/bpjs2 <nik 16 digit>` | Informasi keluarga BPJS (input NIK, bukan nomor BPJS) |
| `/guru <nama>` | Data guru (server 1) |
| `/guru1 <nama>` | Data guru (server 2) |
| `/siswa <nik/kk>` | Data siswa |
| `/cekkpu <nik/kk>` | Data pemilih KPU |
| `/cekanggota <nama#N>` | Data anggota Polri |
| `/leak <email/nomor/nama/nik>` | Cek kebocoran data (leak) |
| `/emailstalker <email>` | Informasi terkait email |
| `/pt <nama perusahaan>` | Data perusahaan (PT) |
| `/nib <nomor>` | Data PT dari NIB |
| `/npwp <nomor>` | Data PT dari NPWP |
| `/fr` | Identifikasi wajah (kirim foto/file setelah command) |
| `/nopol <B1622XC/NIK/NoHP>` | Data kendaraan dari nopol/NIK/no. HP |

Menu lain: **Dashboard Akun** (plan & masa berlaku), **Aturan Pakai** (syarat
penggunaan — hanya untuk keperluan sah & terotorisasi, hasil wajib
diverifikasi ulang, setiap request tercatat untuk audit).
