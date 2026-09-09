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

## API untuk aplikasi (ArtemisID dsb.)

```bash
# terapkan semua migrasi (001..010), lalu:
for f in migrations/*.sql; do psql -d db_artemis -f "$f"; done
uvicorn api:app --host 127.0.0.1 --port 8765
```

Satu akun Telegram hanya bisa melayani satu percakapan efektif pada satu waktu,
jadi permintaan **tidak** diproses paralel: API menerima input, menaruhnya di
antrian **global serial**, dan satu worker mengerjakannya berurutan.

Semua endpoint (kecuali `GET /health` dan `/monitor`) wajib header
`X-API-Key` (nilai dari `API_KEY` di `.env`). `bot` ditentukan lewat **path**
(`/search/{bot}`), bukan body — karena beberapa command (mis. `/nik`, `/kk`)
ada di lebih dari satu bot.

```
POST /search/bot1  {"cmd":"/nik","value":"327...","requested_by":"artemisid:admin"}

  sudah ada di cache -> {"state":"done","status":"found","from_cache":true,"fields":{...},"media":[...]}
  belum ada          -> {"job_id":"1b1b...","state":"queued","queue_position":3}

GET /jobs/{job_id}          -> pantau statusnya
GET /jobs/{job_id}?wait=120 -> long-poll, tunggu selesai (maks 300 detik)
```

### Pencarian & data
| Endpoint | Kegunaan |
|---|---|
| `POST /search/{bot}` | kirim pencarian (cache dulu; kalau tidak ada masuk antrian). Body: `cmd`, `value`, opsional `requested_by`, `priority`, `force` |
| `GET /jobs/{job_id}` | ambil status/hasil, opsional `?wait=` untuk long-poll |
| `GET /queue` | isi antrian saat ini |
| `GET /commands` | daftar command tersedia per bot |
| `GET /profiles/{nik}` | profil dari database, tanpa menyentuh Telegram |
| `GET /media/{id}` | ambil gambar (foto E-KTP dll); id dari field `media` hasil |
| `GET /health` | cek API + ringkasan antrian (tanpa API key) |
| `GET /health/commands` | hasil pengecekan command harian |
| `GET /monitor` | halaman pemantauan command (HTML) |

### Login aplikasi (tabel `app_users`, role admin/user)
| Endpoint | Kegunaan |
|---|---|
| `POST /auth/login` | verifikasi `{username,password}` → `{ok, username, role}` atau 401 |
| `GET /auth/users` | daftar user |
| `POST /auth/users` | buat/timpa user `{username,password,role}` |
| `POST /auth/users/{u}/password` | ganti sandi `{password}` |
| `POST /auth/users/{u}/role?role=admin\|user` | ubah role |
| `DELETE /auth/users/{u}` | hapus user |

Kelola cepat dari server: `python manage_users.py add <user> <pass> [admin|user]`
(juga `list`, `passwd`, `role`, `disable`, `enable`, `del`). Password di-hash
PBKDF2-HMAC-SHA256.

### Riwayat pencarian aplikasi per user (tabel `app_sessions`)
| Endpoint | Kegunaan |
|---|---|
| `POST /app/sessions/upsert` | simpan/perbarui sesi `{id,user,data}` |
| `GET /app/sessions?user=` | daftar sesi milik user |
| `GET /app/sessions/{id}?user=` | detail satu sesi |

`state` job: `queued` → `running` → `done`/`failed`. `status` hasil: `found`,
`not_found`, `queue_without_data`, `no_response`. Prioritas: `"priority": 10`
untuk menyalip antrian (default `0`). `"force": true` memaksa hit bot walau ada
di cache (dipakai healthcheck).

### Siapa yang mencari (audit)
- `search_jobs.requested_by` — identitas pemanggil: `artemisid:<user>` atau
  `tgbot:@<username>`.
- `bot_audit` — pencarian lewat bot Telegram: `telegram_id`, `username`, `name`.

## Pengecekan command berkala (harian)

```bash
psql -d db_artemis -f migrations/003_command_health.sql

python healthcheck.py            # cek semua command yang punya probe
python healthcheck.py bot1       # satu bot saja
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

pytest                        # HANYA test offline (database/parser) — tanpa kuota
pytest -m kuota -s            # menembak bot sungguhan, MEMOTONG KUOTA
pytest -m kuota -s -k nik     # satu command saja
pytest -m kuota -s --force    # abaikan cache, paksa hit bot
```

Test yang menembak bot ditandai marker `kuota` dan **tidak ikut jalan secara
default**. Tanpa itu, `pytest` polos langsung memotong kuota harian — pembatas
paling mahal di sistem ini, dan pernah kejadian.

- **`tests/values.py` adalah satu-satunya tempat menentukan input test.** Satu
  variabel per fitur (`V_NIK`, `V_IMEI`, `V_LBSAREA`, …), masing-masing dengan
  komentar berisi format yang diminta bot **beserta contoh dari bot itu sendiri**
  — bukan tebakan, tapi hasil membaca kalimat ajakan input tiap menu.
- Variabel yang `None` otomatis **di-skip**, jadi bisa diisi sedikit-sedikit.
- Ada juga slot untuk fitur yang **belum didukung** connector (submenu tiga
  langkah, input gambar, dan yang belum diverifikasi) — belum dibaca test,
  disediakan supaya siap saat dukungannya ditambahkan.
- Test memanggil `service.query()`, bukan connector langsung. Jadi yang diuji
  bukan cuma "bot menjawab", tapi juga parser, pilihan normalizer, tabel
  tujuan, dan penyimpanan ke database. Hasil normalisasi ikut dicetak, dan
  test memberi peringatan kalau normalizer mengembalikan dict kosong (tanda
  routing salah).
- `status='not_found'` tidak dianggap gagal (data memang bisa tidak ada);
  yang gagal hanya `no_response` — itu berarti alur menunya yang bermasalah.
- **Test benar-benar menembak bot asli dan memotong kuota.** Jalankan
  seperlunya, dan cek `/quota` (bot2) sebelum mulai.
- `tests/values.py` masuk `.gitignore`; yang di-commit hanya template
  `tests/values.example.py`.

## Catatan
- `ask()` menunggu balasan lewat event handler, bukan polling — aman terhadap
  bot yang balas lambat. Kalau bot membalas beberapa pesan beruntun, naikkan
  `collect`.
- File `.session` = kredensial login. Sudah masuk `.gitignore`, jangan di-commit.
- Jangan kirim pesan bertubi-tubi; Telethon otomatis menangani `FloodWaitError`
  singkat, tapi rate limit tetap berlaku.

## Bot yang sudah terkoneksi

Dicek langsung via `ask` (2026-09-09). Keduanya bot data pencarian/OSINT —
gunakan hanya untuk keperluan yang sah dan terotorisasi.

Keduanya memakai **dialek yang berbeda**, dan itu tercermin di `routes.py`:

| | bot1 | bot2 |
|---|---|---|
| Username | `teamkhususantibanditbot` | `Getphoneplusbot` |
| Dialek | menu ReplyKeyboard, **dua langkah** | command satu tembakan |
| Cara kirim | `connector.ask_menu()` | `connector.ask()` |

### bot1 — `teamkhususantibanditbot`

"TEKAB REBORN / ProfilingBot". `/help` **hanya** berisi command akun
(`/start`, `/register`, `/help`, `/profile`, `/remaining`, `/history`) —
tidak ada satu pun command data.

Fitur datanya dipicu lewat ±60 tombol `ReplyKeyboardMarkup`, dan alurnya dua
langkah:

```
kirim "BUKA NIK"   -> bot balas penjelasan + "Silakan masukkan NIK:"
kirim "3201..."    -> hasil
```

Karena itu `Route` punya kolom `menu`: aplikasi tetap memanggil
`/search/bot1` dengan `cmd` bergaya `/nik`, lalu `service.py` menerjemahkannya
ke label tombol. Bot ini juga mengirim ack + progress bar (`[░░░░░░░░░░] 0%`)
sebelum hasil, jadi `wait_final=True` wajib.

Seluruh **61 menu** sudah dipetakan satu per satu (9 Sep 2026) dengan menekan
tiap tombol dan merekam balasan serta submenunya — tanpa mengirim nilai, jadi
tanpa memotong kuota. Hasilnya: **28 menu input langsung** (dua langkah),
**28 submenu** (tiga langkah atau lebih), dan **5 menu** yang bukan alur
pencarian.

#### Dua langkah — `connector.ask_menu()`

| `cmd` (API) | Label menu | Input |
|---|---|---|
| `/bank` | DATA BANK | Bebas |
| `/datacenter` | DATA CENTER | Bebas |
| `/digital` | DATA DIGITAL | Keyword |
| `/djp` | DATA DJP | NIK |
| `/dpo` | DATA DPO | Nama (min. 4 huruf) |
| `/dukcapil` | DATA DUKCAPIL | NIK, HP, atau nama |
| `/foto` | BUKA FOTO | NIK |
| `/guru` | GURU UMUM | NIK / nama / UKG / NUPTK |
| `/hunter` | HUNTER | Nopol / rangka / mesin / nama |
| `/imei` | DETAIL IMEI | IMEI 14-15 digit |
| `/imigrasi` | DATA IMIGRASI | NIK |
| `/ip` | CEKPOS IP | IP atau domain |
| `/kk` | BUKA KK | No. KK 16 digit |
| `/lbs` | LBS PLUS | HP |
| `/lbsarea` | LBS QUERY | Koordinat / link Maps |
| `/mapping` | MAPPING AREA | Latitude,Longitude |
| `/nik` | BUKA NIK | NIK 16 digit |
| `/nikbyphone` | NIK BY PHONE | HP (08xxx) |
| `/nikinsight` | NIK INSIGHT | NIK |
| `/paspor` | DATA PASPOR | No. paspor atau nama |
| `/pasporkerja` | PASPOR PEKERJA | Nomor paspor |
| `/pddikti` | DATA PDDIKTI | Kata kunci |
| `/pendidikan` | PROFIL PENDIDIKAN | NIK / NISN / peserta_didik_id |
| `/pertamina` | PERTAMINA | Nama / email / HP / NIK |
| `/phonebynik` | PHONE BY NIK | NIK |
| `/pln` | PLN INSIGHT | No. meter / nama / koordinat |
| `/socmed` | SOCIAL MEDIA | Username / email / nomor |
| `/statuskartu` | STATUS KARTU | HP |
| `/tnkb` | DATA KENDARAAN | Nopol / nosin / noka |
| `/track` | TRACKING PHONE | HP |
| `/verifnomor` | VERIFIKASI NOMOR | HP (08/+62) |

#### Tiga langkah — `connector.ask_submenu()`

Menu membuka tombol inline dulu; `Route.choice` menyimpan callback data
tombolnya. **Seluruh 99 tombol submenu tingkat-1 dan 61 tombol tingkat-2 sudah
ditekan satu per satu** — kolom input di bawah adalah kalimat ajakan input asli
bot, bukan tebakan.

| `cmd` (API) | Menu › callback | Ajakan input asli |
|---|---|---|
| `/bca` | DATA BANK › bank_select:270 | Silakan masukkan **nomor rekening** (hanya angka): |
| `/bjbsyariah` | DATA BANK › bank_select:273 | Silakan masukkan **nomor rekening** (hanya angka): |
| `/blue` | DATA BANK › bank_select:280 | Silakan masukkan **nomor rekening** (hanya angka): |
| `/bni` | DATA BANK › bank_select:272 | Silakan masukkan **nomor rekening** (hanya angka): |
| `/bpom` | DITTIPIDTER › dittipidter_bpom | Masukkan **keyword** pencarian untuk memulai (contoh: na |
| `/bri` | DATA BANK › bank_select:274 | Silakan masukkan **nomor rekening** (hanya angka): |
| `/bsi` | DATA BANK › bank_select:275 | Silakan masukkan **nomor rekening** (hanya angka): |
| `/btpn` | DATA BANK › bank_select:279 | Silakan masukkan **nomor rekening** (hanya angka): |
| `/btscellid` | DF TRACKING › bts_type_cell_id | Silakan masukkan **Cell ID** yang ingin dicari: |
| `/btskoordinat` | DF TRACKING › bts_type_coordinate | Masukkan **Latitude** dan **Longitude** dipisahkan denga |
| `/btslac` | DF TRACKING › bts_type_lac | Silakan masukkan **Location Area Code** yang ingin dicar |
| `/celldum` | MONITORING TEKAB › celldum_data | Masukkan koordinat **latitude, longitude** untuk melihat |
| `/cimb` | DATA BANK › bank_select:276 | Silakan masukkan **nomor rekening** (hanya angka): |
| `/cuaca` | DATA BMKG › bmkg_prakiraan_cuaca | Silakan masukkan nama **kelurahan/desa** yang ingin dica |
| `/dana` | DOMPET DIGITAL › ewallet_pick_DANA | Masukkan **nomor telepon** yang ingin dicek: |
| `/ecommerce` | DATA ECOMMERCE › ecommerce_search:name | Masukkan nama yang ingin dicari: |
| `/ecommercehp` | DATA ECOMMERCE › ecommerce_search:phone | Masukkan nomor telepon yang ingin dicari: |
| `/ecommercemail` | DATA ECOMMERCE › ecommerce_search:email | Masukkan alamat email yang ingin dicari: |
| `/gopay` | DOMPET DIGITAL › ewallet_pick_GOPAY | Masukkan **nomor telepon** yang ingin dicek: |
| `/guruagama` | GURU AGAMA › guru_agama_agama:islam | Masukkan keyword pencarian: |
| `/guruagamabudha` | GURU AGAMA › guru_agama_agama:budha | Masukkan keyword pencarian: |
| `/guruagamahindu` | GURU AGAMA › guru_agama_agama:hindu | Masukkan keyword pencarian: |
| `/guruagamakatolik` | GURU AGAMA › guru_agama_agama:katolik | Masukkan keyword pencarian: |
| `/guruagamakonghucu` | GURU AGAMA › guru_agama_agama:konghucu | Masukkan keyword pencarian: |
| `/guruagamakristen` | GURU AGAMA › guru_agama_agama:kristen | Masukkan keyword pencarian: |
| `/isaku` | DOMPET DIGITAL › ewallet_pick_ISAKU | Masukkan **nomor telepon** yang ingin dicek: |
| `/linimasa` | MONITORING TEKAB › linimasa | Contoh Penggunaan Linimasa : |
| `/linkaja` | DOMPET DIGITAL › ewallet_pick_LINKAJA | Masukkan **nomor telepon** yang ingin dicek: |
| `/lookup` | LOOKUP NUMBER › lookup_by_phone | Silakan masukkan nomor telepon (contoh: 08123456789 atau |
| `/lookupnama` | LOOKUP NUMBER › lookup_by_name | Silakan masukkan nama yang ingin dicari (minimal 3 karak |
| `/mandiri` | DATA BANK › bank_select:271 | Silakan masukkan **nomor rekening** (hanya angka): |
| `/mariag` | DATA MA-RI › mari_ri_panmud_AG | Masukkan nomor perkara, atau tekan **Lewati** untuk koso |
| `/marimil` | DATA MA-RI › mari_ri_panmud_MIL | Masukkan nomor perkara, atau tekan **Lewati** untuk koso |
| `/maripdt` | DATA MA-RI › mari_ri_panmud_PDT | Masukkan nomor perkara, atau tekan **Lewati** untuk koso |
| `/maripdtsus` | DATA MA-RI › mari_ri_panmud_PDT.SUS | Masukkan nomor perkara, atau tekan **Lewati** untuk koso |
| `/maripid` | DATA MA-RI › mari_ri_panmud_PID | Masukkan nomor perkara, atau tekan **Lewati** untuk koso |
| `/maripidsus` | DATA MA-RI › mari_ri_panmud_PID.SUS | Masukkan nomor perkara, atau tekan **Lewati** untuk koso |
| `/maritun` | DATA MA-RI › mari_ri_panmud_TUN | Masukkan nomor perkara, atau tekan **Lewati** untuk koso |
| `/mkri` | DATA MK-RI › mkri_sub_ikhtisar | Silakan masukkan kata kunci pencarian. Anda dapat menggu |
| `/mkriputusan` | DATA MK-RI › mkri_sub_putusan | Silakan masukkan kata kunci pencarian. Anda dapat menggu |
| `/mkririsalah` | DATA MK-RI › mkri_sub_risalah | Silakan masukkan kata kunci pencarian. Anda dapat menggu |
| `/muamalat` | DATA BANK › bank_select:277 | Silakan masukkan **nomor rekening** (hanya angka): |
| `/nama` | PENCARIAN BIODATA › pb_cari_nama | ▪️Pastikan ejaan nama yang dimasukkan benar, akurat, dan |
| `/namaortu` | PENCARIAN BIODATA › pb_cari_ortu |  |
| `/namausaha` | VERIFIKASI PERIZINAN › sppirt_select_nama_usaha | Masukkan kata kunci pencarian: |
| `/nib` | VERIFIKASI PERIZINAN › sppirt_select_nib | Masukkan kata kunci pencarian: |
| `/notaris` | DATA NOTARIS › notaris_sel:nama | Silakan masukkan **nama notaris** yang ingin dicari: |
| `/notarisbadan` | DATA NOTARIS › notaris_sel:badan_hukum | Silakan masukkan **nama badan hukum** yang ingin dicari: |
| `/notarisbn` | DATA NOTARIS › notaris_sel:no_bn | Silakan masukkan **No. Berita Negara** yang ingin dicari |
| `/notaristahun` | DATA NOTARIS › notaris_sel:tahun | Silakan masukkan **Tahun Terbit** yang ingin dicari: |
| `/notaristbn` | DATA NOTARIS › notaris_sel:no_tbn | Silakan masukkan **No. Tambahan Berita Negara** yang ing |
| `/ovo` | DOMPET DIGITAL › ewallet_pick_OVO | Masukkan **nomor telepon** yang ingin dicek: |
| `/perusahaan` | DITIPIDEKSUS › ditipideksus_profil_perusahaan | ( contoh : `9120001380361`, `2209240018016`, `9120003890 |
| `/produkpangan` | VERIFIKASI PERIZINAN › sppirt_select_nama_produk_pangan | Masukkan kata kunci pencarian: |
| `/resiasal` | TRACKING NUMBER › track_search_origin | Masukkan kata kunci pencarian: |
| `/resikurir` | TRACKING NUMBER › track_search_courier | Masukkan kata kunci pencarian: |
| `/resipenerima` | TRACKING NUMBER › track_search_receiver | Masukkan kata kunci pencarian: |
| `/resipengirim` | TRACKING NUMBER › track_search_shipper | Masukkan kata kunci pencarian: |
| `/resitujuan` | TRACKING NUMBER › track_search_destination | Masukkan kata kunci pencarian: |
| `/shopeepay` | DOMPET DIGITAL › ewallet_pick_SHOPEEPAY | Masukkan **nomor telepon** yang ingin dicek: |
| `/sppirt` | VERIFIKASI PERIZINAN › sppirt_select_no_sppirt | Masukkan kata kunci pencarian: |
| `/telegram` | DATA TELEGRAM › telegram_profiling_by_username |  |
| `/telegramid` | DATA TELEGRAM › telegram_profiling_by_id | Silakan masukkan Telegram ID (contoh: 378410969): |
| `/telegrammail` | DATA TELEGRAM › telegram_profiling_by_email | Silakan masukkan email atau sebagian email: |
| `/telegramnama` | DATA TELEGRAM › telegram_profiling_by_name | Silakan masukkan nama (first name atau last name): |
| `/traceimei` | MONITORING TEKAB › trace_imei | Silakan masukkan nomor IMEI yang ingin dilacak: |
| `/tracenumber` | MONITORING TEKAB › trace_number | Silakan masukkan nomor handphone yang ingin Anda cari: |
| `/tracingimei` | MONITORING TEKAB › tracing_imei | Silakan masukkan nomor IMEI yang ingin Anda cari: |
| `/tracingimsi` | MONITORING TEKAB › tracing_imsi | Silakan masukkan nomor IMSI yang ingin Anda cari: |
| `/whatsapp` | DATA WHATSAPP › wa_profiling_phone | Silakan masukkan nomor telepon (contoh: 6281234567890): |
| `/whatsappmail` | DATA WHATSAPP › wa_profiling_email | Silakan masukkan email bisnis WhatsApp (contoh: business |

#### Empat langkah — rantai dua klik

`Route.choice` berupa tuple; tombol diklik berurutan.

| `cmd` (API) | Menu › callback › callback | Ajakan input asli |
|---|---|---|
| `/alkesjenis` | DITIPIDEKSUS › ditipideksus_produk_perusahaan › alkes_cat_6 | Silakan masukkan kata kunci pencarian: |
| `/alkesnie` | DITIPIDEKSUS › ditipideksus_produk_perusahaan › alkes_cat_1 | Silakan masukkan kata kunci pencarian: |
| `/alkespendaftar` | DITIPIDEKSUS › ditipideksus_produk_perusahaan › alkes_cat_3 | Silakan masukkan kata kunci pencarian: |
| `/alkesproduk` | DITIPIDEKSUS › ditipideksus_produk_perusahaan › alkes_cat_2 | Silakan masukkan kata kunci pencarian: |
| `/alkesprodusen` | DITIPIDEKSUS › ditipideksus_produk_perusahaan › alkes_cat_5 | Silakan masukkan kata kunci pencarian: |
| `/alkestipe` | DITIPIDEKSUS › ditipideksus_produk_perusahaan › alkes_cat_4 | Silakan masukkan kata kunci pencarian: |
| `/dpd` | DATA PEMERINTAH › pemerintah_sub_dpd › dpd_sub_cari_nama | Masukkan nama anggota DPD yang ingin dicari. |
| `/dpr` | DATA PEMERINTAH › pemerintah_sub_dpr › dpr_sub_cari_nama | Masukkan nama anggota DPR yang ingin dicari. |
| `/halalpetugas` | DITTIPIDTER › dittipidter_halal › dittipidter_halal_petugas | Masukkan **Nama Petugas** untuk memulai pencarian. |
| `/halalproduk` | DITTIPIDTER › dittipidter_halalmui › halalmui_filter:nama_produk | Masukkan **keyword** pencarian untuk memulai. |
| `/halalprodusen` | DITTIPIDTER › dittipidter_halalmui › halalmui_filter:nama_produsen | Masukkan **keyword** pencarian untuk memulai. |
| `/halalsertifikat` | DITTIPIDTER › dittipidter_halalmui › halalmui_filter:no_sertifikat | Masukkan **keyword** pencarian untuk memulai. |
| `/konsorsium` | DITIPIDEKSUS › ditipideksus_konsorsium › company_search:nama_perseroan | 🏢 Masukkan nama perusahaan yang ingin dicari: |
| `/konsorsiumnik` | DITIPIDEKSUS › ditipideksus_konsorsium › company_search:nik | 🆔 Masukkan NIK yang ingin dicari: |
| `/namaayah` | PENCARIAN BIODATA › pb_cari_ortu › pb_filter_ayah | Masukkan nama ayah yang ingin dicari: |
| `/namaibu` | PENCARIAN BIODATA › pb_cari_ortu › pb_filter_ibu | Masukkan nama ibu yang ingin dicari: |
| `/perkumpulan` | DITIPIDEKSUS › ditipideksus_badan_hukum › badan_hukum_perkumpulan | Masukkan **nama perusahaan / perkumpulan** yang ingin di |
| `/perseroan` | DITIPIDEKSUS › ditipideksus_badan_hukum › badan_hukum_perseroan | Masukkan nama perusahaan yang ingin dicari. |
| `/perseroanorang` | DITIPIDEKSUS › ditipideksus_badan_hukum › badan_hukum_perseroan_perorangan | Silakan masukkan **nama perusahaan** yang ingin dicari. |
| `/resianteraja` | TRACKING NUMBER › track_mode_new › courier_anteraja | Silakan masukkan nomor resi pengiriman Anda: |
| `/resifirst` | TRACKING NUMBER › track_mode_new › courier_first | Silakan masukkan nomor resi pengiriman Anda: |
| `/resiide` | TRACKING NUMBER › track_mode_new › courier_ide | Silakan masukkan nomor resi pengiriman Anda: |
| `/resijet` | TRACKING NUMBER › track_mode_new › courier_jet | Silakan masukkan nomor resi pengiriman Anda: |
| `/resijne` | TRACKING NUMBER › track_mode_new › courier_jne | Silakan masukkan nomor resi pengiriman Anda: |
| `/resijnt` | TRACKING NUMBER › track_mode_new › courier_jnt | Silakan masukkan nomor resi pengiriman Anda: |
| `/resijntcargo` | TRACKING NUMBER › track_mode_new › courier_jnt_cargo | Silakan masukkan nomor resi pengiriman Anda: |
| `/resilion` | TRACKING NUMBER › track_mode_new › courier_lion | Silakan masukkan nomor resi pengiriman Anda: |
| `/resininja` | TRACKING NUMBER › track_mode_new › courier_ninja | Silakan masukkan nomor resi pengiriman Anda: |
| `/resipcp` | TRACKING NUMBER › track_mode_new › courier_pcp | Silakan masukkan nomor resi pengiriman Anda: |
| `/resipos` | TRACKING NUMBER › track_mode_new › courier_pos | Silakan masukkan nomor resi pengiriman Anda: |
| `/resirex` | TRACKING NUMBER › track_mode_new › courier_rex | Silakan masukkan nomor resi pengiriman Anda: |
| `/resisicepat` | TRACKING NUMBER › track_mode_new › courier_sicepat | Silakan masukkan nomor resi pengiriman Anda: |
| `/resitiki` | TRACKING NUMBER › track_mode_new › courier_tiki | Silakan masukkan nomor resi pengiriman Anda: |
| `/resiwahana` | TRACKING NUMBER › track_mode_new › courier_wahana | Silakan masukkan nomor resi pengiriman Anda: |

**Belum dirutekan**:

- **Butuh unggah file** — pipeline hanya menerima `value TEXT`:
  FR SOCIAL MEDIA, FACE RECOGNITION, FORENSIC IMAGE, IMAGE GENERATION,
  ANALISIS FORENSIK DIGITAL (Cell Dump, Location Intelligence, Analisa CDR,
  Analisa IMEI — semuanya "Silakan kirimkan file Anda").
- **Menu berpaginasi** yang tombolnya berubah tiap halaman: DATA BANK
  (11 halaman), DATA NOTARIS › Pilih Kota, TRACKING NUMBER › daftar kurir
  halaman 2, DITIPIDEKSUS › Perusahaan (35 tombol).
- **Bukan alur pencarian**: DATA CCTV, DATA LEMBAGA, INFORMATION TEKAB,
  MANAGEMENT TEKAB, DATA BMKG › Info Gempa & Peringatan Dini,
  PROFIL NAKES, MONITORING TEKAB › Celldum Area.

### Mengambil profil tanpa NIK

`GET /profiles/{nik}` tidak bisa menjangkau profil ber-NIK NULL — padahal
migrasi 012 justru membuat profil semacam itu bisa tersimpan (hasil
cari-by-nama). Dua endpoint melengkapinya:

```
GET /profiles?nama=puan&limit=20   -> ringkasan, yang ber-NIK didahulukan
GET /profiles/id/{profile_id}      -> detail lengkap, satu-satunya cara
                                      untuk profil tanpa NIK
```

Detailnya kini juga menyertakan `kendaraan`, yang sebelumnya tidak pernah
dikembalikan meski tabelnya ada.

**Penautan record.** `find_profile_id()` hanya mencari lewat NIK, jadi catatan
milik profil ber-NIK NULL tersimpan tapi menggantung. `insert_record()` kini
menerima `profile_id` langsung dari hasil `upsert_profile()`.

### Integrasi API & antrian

```
POST /search/{bot}    X-API-Key: <API_KEY>
{"cmd":"/nik","value":"3275...","requested_by":"artemisid:admin"}
```

* sudah di cache -> langsung `{"state":"done","from_cache":true,"fields":{...}}`
* belum          -> `{"job_id":"...","state":"queued","queue_position":3}`

Ambil hasilnya dengan long-poll: `GET /jobs/{job_id}?wait=120` (maks 300 detik).
`GET /queue` memperlihatkan isi antrian.

**`state` dan `status` berbeda.** `state` = siklus job
(`queued/running/done/failed`); `status` = hasil pencarian
(`found/not_found/queue_without_data/no_response`).

**`queue_without_data` = coba lagi nanti, BUKAN "data tidak ada".** Status ini
dipakai untuk kuota harian habis dan balasan bot yang gagal. Dari 101 query uji,
50 di antaranya berstatus ini. Aplikasi yang memperlakukannya seperti
`not_found` akan memberi tahu pengguna "data tidak ditemukan" padahal cuma
kuotanya habis. Hanya `found` yang disajikan ulang dari cache.

**Job kembar digabung.** Dua permintaan identik yang masih mengantre memakai
job yang sama (migrasi 013) — prioritas tertinggi menang, dan bot tidak
ditembak dua kali. `force` tidak digabung dengan job biasa karena tujuannya
memang melewati cache. Diuji di `tests/test_antrian.py`.

**Kapasitas.** Antrian sengaja serial satu worker (balasan bot tertukar saat
diuji paralel), plus `JEDA_ANTAR_JOB` 10 detik dan ~15 detik per query —
sekitar **2–3 pencarian per menit**. Pembatas sebenarnya bukan itu, melainkan
kuota harian per fitur di bot.

**`GET /commands` memuat bentuk datanya.** Tiap command menyertakan `menu`,
`target`, `kind`, `always_fresh`, `atribut`, dan `terverifikasi`, dibaca dari
`docs/skema.json`. Jalankan `python skema.py --tulis` setelah ada hasil baru;
API membacanya saat diminta, jadi tidak perlu restart.

### Bentuk JSON per command

Setiap command menghasilkan JSON dengan nama field yang konsisten
`^[a-z][a-z0-9_]*$` — tanpa tanda baca, tanpa spasi, tidak diawali angka.
`normalize.slug_key()` menyeragamkannya, karena balasan bot menghasilkan nama
seperti `Berlaku s/d`, `No. Sertifikat`, `Lembaga/Perusahaan`, bahkan key
berupa tahun saja (`2013`, untuk daftar penghargaan anggota DPR):

```
Berlaku s/d          -> berlaku_sampai   (lewat alias)
No. Sertifikat       -> nomor_sertifikat (lewat alias)
Lembaga/Perusahaan   -> lembaga_perusahaan
2013                 -> tahun_2013
```

Key yang **namanya ikut berubah tiap balasan** (mis.
`tanggal_9_sep_2026_pukul_20`) dikumpulkan ke sub-objek `lainnya`, supaya
bentuk JSON tiap command tetap stabil antar pemanggilan dan bisa diandalkan
konsumen.

**Katalognya dibangun dari data nyata**, bukan tebakan:

```bash
python skema.py            # tampilkan
python skema.py --tulis    # tulis docs/skema.json + docs/SKEMA.md
```

`docs/skema.json` memuat, untuk tiap command: menu & callback yang dipakai,
tabel tujuan, `kind`, normalizer, apakah volatile, dan daftar atribut yang
benar-benar pernah dikembalikan. Command yang belum pernah menghasilkan data
ditandai `terverifikasi: false` — bentuknya belum diketahui, bukan tidak ada.

### profiles: NIK opsional

Skema 001 merancang `profiles.nik` **nullable** ("hasil cari-by-nama kadang
tanpa NIK") dengan `nama` NOT NULL — tapi `upsert_profile()` menolak baris
tanpa NIK, karena tidak ada kunci untuk `ON CONFLICT`. Akibatnya hasil
pencarian by-nama (`DATA PASPOR`, `PASPOR PEKERJA`, `DATA PEMERINTAH`) tidak
pernah masuk `profiles` sama sekali.

Migrasi **012** memberi kunci itu: index unik parsial pada
`(lower(nama), COALESCE(tanggal_lahir,'0001-01-01')) WHERE nik IS NULL`.
COALESCE dipakai karena NULL tidak pernah bentrok di UNIQUE — tanpa itu orang
tanpa tanggal lahir akan menumpuk duplikat tiap query diulang.

`upsert_profile()` kini memilih kunci sesuai isinya: `(nik)` kalau ada NIK,
index parsial kalau tidak. Keduanya tidak saling mengganggu.

Diuji idempoten di `tests/test_penyimpanan.py`.

### Pemetaan atribut per command

Diverifikasi dengan bulk run 9 Sep 2026: 97 query bot1 + 1 bot2. Dari hasil
nyata itu, **251 atribut mentah → 189 tersimpan**; selisihnya adalah metadata
pencarian yang sengaja dibuang (`keyword`, `total_ditemukan`, `menampilkan`,
`filter`, `halaman`, `contoh`, `you_said`) — lihat `normalize.DROP_KEYS`.

Tiga aturan yang membuat tidak ada atribut data hilang:

1. **`normalize_raw()` menghormati alias & drop.** Nama field disamakan lewat
   `FIELD_ALIASES` (`kota/kabupaten` → `kab_kota`, `no._paspor` →
   `nomor_paspor`, `nama_lengkap` → `nama`, `gender` → `jenis_kelamin`), lalu
   metadata dibuang.
2. **Field kanonik ditumpuk di atas field mentah** untuk `target='records'`.
   Normalizer khusus hanya mengenali sebagian kecil field — `/btscellid`
   mengembalikan 22 atribut BTS tapi `normalize_device` cuma mengenali 2.
   Sekarang nama kanonik menang, sisanya tetap tersimpan.
3. **`target='profiles'` menyimpan sisanya ke `profile_records`.** `profiles`
   hanya punya kolom kependudukan baku; `/nikinsight` mengembalikan 28 atribut
   (neptu, generasi, kelompok usia, …) yang tidak punya kolom dan dulu hilang.

### Kuota harian per fitur

Bot1 bukan sekadar langganan bulanan — tiap **fitur** punya batas harian:

```
⚠️ Batas Penggunaan Tercapai
Anda telah mencapai batas penggunaan harian untuk fitur Profiling WhatsApp.
```

Dari bulk run, **38 dari 55 `not_found` sebenarnya kuota habis**. Itu keliru:
`not_found` berarti "data memang tidak ada" dan membuat healthcheck
menyimpulkan fiturnya rusak. Sekarang `parser.is_limited()` menggolongkannya
`queue_without_data` supaya bisa dicoba lagi besok.

`healthcheck.py` juga **melewati** probe yang kena kuota — tidak dihitung
gagal dan tidak dicatat, supaya riwayat kesehatan command tidak tercemar
kondisi yang bukan soal command-nya.

Kalau kuota habis, bot bahkan **menolak membuka menunya** — tidak ada tombol
submenu sama sekali. Dulu itu muncul sebagai `RuntimeError: tombol ... tidak
ditemukan` yang menyesatkan; sekarang `connector.BatasHarian` ditangkap
`service` dan dicatat sebagai kondisi sementara.

### Bot memantulkan input

`You said: 3275...` berarti alur menu TIDAK aktif dan nilai kita jatuh ke ruang
kosong. Dulu tersimpan sebagai `found` berisi `{you_said: ...}`.
`parser.is_echo()` kini menggolongkannya `queue_without_data`.

### Jeda antar query wajib

Bot membalas **tanpa `reply_to`**, dan `relates_to_request()` hanya bisa
menolak balasan nyasar kalau input punya ≥8 digit — untuk pencarian
nama/keyword ia tidak bisa memastikan. Kasus terparah: 6 e-wallet DOMPET
DIGITAL memakai satu nomor HP yang sama, jadi balasan DANA dan GOPAY tidak
bisa dibedakan.

`jobs.JEDA_ANTAR_JOB` = 10 detik menangani ini di produksi; test memanggil
`service.query()` langsung sehingga jeda itu terlewat. `tests/_helper.py` kini
menahan jeda yang sama (atur lewat `JEDA_TEST`).

### Urai & normalisasi ulang tanpa kuota

`bot_query_cache.raw_text` (migrasi 011) menyimpan TEKS MENTAH balasan bot,
bukan cuma hasil parse. Tanpa itu, perbaikan **parser** tidak bisa diputar
ulang — dan itu mahal: waktu penomoran `1. Judul` ditemukan, satu-satunya cara
memperbaiki data lama adalah menembak bot lagi.

`python rebuild.py` mengurai ULANG dari `raw_text` dengan parser terkini, lalu
membangun ulang lapis ternormalisasi — tanpa menyentuh Telegram. Setiap kali normalizer, alias,
atau routing diperbaiki, jalankan ini alih-alih menembak bot lagi.

```bash
python rebuild.py            # semua
python rebuild.py /nik /kk   # command tertentu
python rebuild.py --dry      # laporan saja
```

### Paginasi daftar hasil

Bot memotong daftar: `/bpom "Indomie"` menjawab "Total ditemukan 1.412 hasil,
Menampilkan 1–5" dengan tombol `📄 1/283` dan `Next ➡️` (callback
`bpom_page:2`). `connector.telusuri_halaman()` mengikuti tombol itu —
polanya dicocokkan lewat regex (`page`/`halaman` + angka), bukan daftar tetap,
karena tiap fitur menamai callback-nya sendiri. Bot **mengedit pesan yang
sama** saat halaman berganti, jadi yang ditunggu adalah `MessageEdited`.

`parser.classify()` kini menggabungkan record dari **semua** pesan hasil, bukan
hanya yang terakhir — kalau tidak, halaman berikutnya justru menimpa halaman
pertama. Record identik antar halaman tidak digandakan.

Diatur lewat env **`HALAMAN_MAKS`** (default `0` = perilaku lama). Defaultnya
mati karena belum diketahui apakah menekan Next ikut memotong kuota harian per
fitur. Terverifikasi dengan `HALAMAN_MAKS=2`: `/bpom` naik dari 5 menjadi
**9 record**.

### Turunan ikut terhapus (migrasi 014)

`source_query_id` dulu `ON DELETE SET NULL`. Akibatnya menghapus baris cache
meninggalkan record yatim yang tidak bisa dibangun ulang — dan lebih buruk,
karena `UNIQUE (kind, subject, data)` dipakai bersama `ON CONFLICT DO NOTHING`,
baris yatim itu **menahan insert baru** yang isinya sama. Terbukti pada
`/bpom`: 9 record terurai, hanya 6 tersimpan, 3 sisanya diblokir sisa lama.

Sekarang `ON DELETE CASCADE` untuk `profile_records`, `profile_phones`, dan
`profile_vehicles` — sesuai rancangan bahwa lapis 2 adalah turunan lapis 1.

### Jaminan penyimpanan

Dua lapis, dengan jaminan berbeda:

| Lapis | Jaminan |
|---|---|
| `bot_query_cache` | **selalu** tersimpan, semua status, lengkap dengan `fields` mentah dan `bot_username` |
| `profiles` / `profile_records` / `phones` / `vehicles` | hanya untuk status `found`, dan hanya kalau normalizer mengenali bentuknya |

Dulu setiap syarat yang gagal berarti `continue`/`return` **tanpa log** —
hasil ber-status found bisa hilang dari lapis queryable tanpa jejak. Terbukti
pada `/cuaca`: status `found`, nol baris tersimpan.

Sekarang ada jaring pengaman `_simpan_cadangan()`:

- **normalizer mengembalikan `{}`** (bentuk balasan tidak dikenali) → field
  mentahnya disimpan ke `profile_records` dengan `kind` dari route.
- **`target='profiles'` tapi hasil tanpa NIK/nama** → `profiles` mengunci pada
  NIK dan `nama` NOT NULL, jadi hasil cari-by-nama yang tidak menyertakan NIK
  diturunkan ke `profile_records`, bukan dibuang. Ini mengenai 9 route:
  `/nik /kk /nama /nikinsight /dukcapil /nikbyphone /namaayah /namaibu /namaortu`.

Keduanya menulis `log.warning`, jadi bentuk balasan yang belum tertangani
terlihat di log alih-alih senyap.

Diuji di `tests/test_penyimpanan.py` — murni database, tidak menyentuh
Telegram, jadi aman dijalankan kapan saja tanpa memotong kuota.

### Format balasan bot baru

Diverifikasi dengan 5 query nyata bernilai publik (9 Sep 2026). Bot mengirim
**beberapa pesan berurutan** untuk satu permintaan, dan hanya pesan terakhir
yang berisi data:

1. ack antrian — "Permintaan berhasil diterima"
2. progress bar — `T•E•K•A•B REBORN` + `[░░░░░░░░░░] 0%`
3. pesan progres berkalimat — "⏳ Mencari data peraturan untuk kata kunci ..."
4. peringatan hukum — "DATA BERSIFAT SANGAT RAHASIA ..."
5. **hasil**

Empat pesan pertama harus dilewati. Tanpa itu `wait_final` berhenti di salah
satunya dan hasil aslinya terbuang — terbukti pada `/ip`, yang sempat tersimpan
`not_found` padahal hasilnya 3380 karakter. Penanganannya ada di
`parser.ACK_MARKERS` dan `parser.is_preamble()`.

Data hasilnya berformat **pohon + markdown**, bukan `Key: value` polos seperti
bot lama:

```
**Hasil CEKPOS IP untuk: ****detik.com**
├ **Type:** IPv4
├ **Country:** 🇮🇩 Indonesia (ID)
└ **ISP:** PT. Detik Ini Juga
```

`parser.bersihkan_baris()` membuang gambar pohon dan penanda markdown sebelum
`KV_RE` dijalankan. Tanpa itu seluruh balasan terbaca sebagai teks bebas.

### Daftar hasil: dua pola berbeda

Ditelusuri 9 Sep 2026. Balasan yang memuat banyak hasil ternyata ada dua jenis,
dan sempat tertukar:

**1. Daftar bernomor — datanya SUDAH ADA, tidak perlu klik lagi.**
`/bpom`, `/alkes*`, `/halal*`, `/mkri`, `/paspor`, `/konsorsium` mengirim
beberapa hasil berdetail dalam satu pesan:

```
**Keyword:** Indomie
**Total ditemukan:** 1,412 hasil
**Menampilkan:** 1–5

**1. Es Krim Rasa Mi Kari (Indomie Kari Ayam)**
   **Merk:** CHOC ROCKS
   **NIE:** MD 242811002200462
   ...
**2. Indomie Premium BBQ Chicken Flavour**
   ...
```

`RECORD_HEADER_RE` hanya mengenal gaya `Data 1.` dan `#1` milik bot lama, jadi
kelima hasil terbaca sebagai SATU record dan empat sisanya hilang.
`NUMBERED_HEADER_RE` kini mengenali `N. Judul` — tapi hanya kalau dalam satu
pesan ada minimal dua nomor, supaya baris biasa yang kebetulan diawali "1. "
tidak salah dipotong. Blok ringkasan di atasnya (`Keyword`, `Total ditemukan`,
`Menampilkan`) dibuang lewat `SUMMARY_ONLY`.

Terverifikasi: `/bpom "Indomie"` → **5 record**, masing-masing 11 atribut.
Paginasinya (`📄 1/283`, callback `bpom_page_*`) belum diikuti — baru halaman
pertama yang diambil.

**2. Pemilih hasil — datanya BELUM ADA sampai satu dipilih.**
`DATA BMKG › Prakiraan Cuaca` menjawab "Ditemukan 16 kelurahan. Pilih
kelurahan", `DATA PDDIKTI` menjawab hitungan per kategori. Ini yang benar-benar
butuh klik keempat setelah nilai dikirim, dan belum diimplementasikan.

### Peringatan: state bot bisa mengunci

Bot menyimpan state percakapan **per jenis input**, dan sebagian tidak bisa
dibatalkan sama sekali. Terbukti pada `celldum_data` (menunggu koordinat):
29 tombol `❌ Batal`, `/start`, tombol Batal pada pesan prompt asli, dan masuk
ulang lewat MAPPING AREA — semuanya gagal. Satu-satunya jalan keluar adalah
menuntaskan alurnya dengan mengirim nilai yang formatnya benar.

Karena itu `ask_menu()`/`ask_submenu()` memanggil `_pastikan_tidak_tersangkut()`:
kalau membuka menu dibalas keluhan format, alur **digagalkan** sebelum nilai
dikirim. Tanpa ini, NIK pengguna bisa masuk ke prompt koordinat dan hasilnya
tersimpan sebagai jawaban permintaan yang salah.

### Membatalkan state

Bot menyimpan state percakapan. Kalau query berhenti di tengah, bot masih
menunggu input dan pesan berikutnya ditelan sebagai nilai. **`/start` tidak
membatalkannya** — terbukti `/start` sendiri ikut dijawab "Format nomor telepon
tidak valid". Yang berhasil hanya tombol inline `❌ Batal` (callback `cancel_*`)
di pesan ajakan input, jadi `connector.cancel_pending()` menekannya sebelum tiap
alur menu.

### bot2 — `Getphoneplusbot`

Cek nomor HP, satu command inti. Dialek command biasa.

| Command | Fungsi |
|---|---|
| `/getphone <nomor>` | Cek nomor |
| `/apikey` | Generate API key (bot ini punya REST API sendiri) |
| `/quota` | Sisa kuota |
| `/help` | Daftar perintah |
