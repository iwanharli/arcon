"""Nilai input untuk test fitur bot — ISI SENDIRI.

Salin jadi tests/values.py lalu isi. File values.py masuk .gitignore karena
bisa berisi data pribadi; yang di-commit hanya template ini.

    cp tests/values.example.py tests/values.py

Command yang nilainya None otomatis di-SKIP, jadi bisa diisi sedikit-sedikit.
Format tiap kolom di bawah BUKAN tebakan — diambil dari kalimat ajakan input
bot itu sendiri (probe 9 Sep 2026), termasuk contoh yang bot tampilkan.

PERINGATAN: test benar-benar menembak bot lewat akun user yang sudah login,
jadi MEMOTONG KUOTA. Jalankan seperlunya:

    pytest -s tests/test_bot1.py -k nik      # satu command saja
    pytest -s tests/test_bot2.py             # bot2 saja
"""

# ============================================================================
# 1. Identitas dasar — isi sekali, dipakai ulang oleh banyak command di bawah.
# ============================================================================
NIK        = None   # NIK 16 digit          contoh bot: 3174014106580000
KK         = None   # No. KK 16 digit       contoh bot: 3314123456789012
NAMA       = None   # Nama lengkap
HP         = None   # Nomor HP 62xxx        contoh bot: +628123456789
HP_08      = None   # Nomor HP 08xxx        contoh bot: 08123456789
                    #   /nikbyphone & /statuskartu contohnya pakai format 08.

# ============================================================================
# 2. bot1 — teamkhususantibanditbot (dialek MENU, dua langkah)
#    Kolom "input" = kalimat ajakan input asli dari bot.
# ============================================================================

# --- Kependudukan ---
V_NIK         = NIK    # BUKA NIK          "masukkan NIK (Nomor Induk Kependudukan)"
V_KK          = KK     # BUKA KK           "masukkan Nomor KK (16 digit)"
V_FOTO        = NIK    # BUKA FOTO         "masukkan NIK untuk mendapatkan foto"
V_DUKCAPIL    = NIK    # DATA DUKCAPIL     "masukkan NIK, nomor HP, atau nama"
V_NIKINSIGHT  = NIK    # NIK INSIGHT       "masukkan NIK (16 digit)"

# --- Nomor HP ---
V_NIKBYPHONE  = HP_08  # NIK BY PHONE      "nomor telepon (format: 08xxxxxxxxxx)"
V_PHONEBYNIK  = NIK    # PHONE BY NIK      "masukkan NIK ... untuk mencari nomor telepon"
V_VERIFNOMOR  = HP     # VERIFIKASI NOMOR  "08123456789 atau +628123456789"
V_STATUSKARTU = HP_08  # STATUS KARTU      "masukkan nomor HP yang ingin Anda cek"

# --- Lokasi & perangkat ---
V_TRACK       = HP     # TRACKING PHONE    "nomor handphone yang ingin dilacak"
V_LBS         = HP     # LBS PLUS          "masukkan nomor HP yang ingin dicari"
V_LBSAREA     = None   # LBS QUERY         KOORDINAT, bukan nomor HP.
                       #   contoh bot: -6.218148,106.7979595
                       #   atau: https://maps.google.com/?q=-6.243846,106.6208904
V_IMEI        = None   # DETAIL IMEI       "nomor IMEI (14-15 digit)"
                       #   contoh bot: 355551370383427

# --- Kendaraan ---
V_TNKB        = None   # DATA KENDARAAN    nopol / nomor mesin / nomor rangka

# --- Data lain ---
V_PLN         = None   # PLN INSIGHT       ID pelanggan, atau tarif/daya (R1 / 1300 VA)
V_DPO         = None   # DATA DPO          nama, MINIMAL 4 HURUF
V_PASPOR      = None   # DATA PASPOR       no. paspor (contoh: AB656119) atau nama
V_IMIGRASI    = NIK    # DATA IMIGRASI     "masukkan NIK (16 digit)"
V_BANK        = None   # DATA BANK         "Ketik langsung untuk mencari" (bebas)
V_DJP         = NIK    # DATA DJP          "Masukkan NIK"

# --- Pendidikan ---
V_PDDIKTI     = None   # DATA PDDIKTI      "masukkan kata kunci pencarian"
V_PENDIDIKAN  = NIK    # PROFIL PENDIDIKAN contoh bot: 3514122403990001
V_GURU        = None   # GURU UMUM         NIK atau nama (contoh: budi / agus santoso)
# --- Baru terverifikasi (pemetaan 61 menu, 9 Sep 2026) ---
V_SOCMED      = None   # SOCIAL MEDIA      username / email / nomor telepon
V_PERTAMINA   = None   # PERTAMINA         nama / email / nomor HP / NIK
V_HUNTER      = None   # HUNTER            nopol (B1234ABC) / no. rangka /
                       #                   no. mesin / nama penghutang
V_PASPORKERJA = None   # PASPOR PEKERJA    nomor paspor   contoh bot: C8425694
V_IP          = None   # CEKPOS IP         IP atau domain
                       #   contoh bot: 103.49.221.211 atau detik.com
V_MAPPING     = None   # MAPPING AREA      "Latitude dan Longitude"
                       #   contoh bot: -8.781814,115.178598
V_DIGITAL     = None   # DATA DIGITAL      keyword bebas
V_DATACENTER  = None   # DATA CENTER       "jenis data apa pun"

# ============================================================================
# 2b. bot1 — alur TIGA langkah (menu -> tombol submenu -> nilai)
#     Didukung sejak connector.ask_submenu(). Tanda (v) = ajakan inputnya
#     sudah dibuka & dibaca langsung; sisanya tombol sekerabat.
# ============================================================================
V_NAMA_BIODATA = None  # PENCARIAN BIODATA > CARI NAMA      (v) nama
V_NAMA_ORTU    = None  # PENCARIAN BIODATA > CARI BY ORTU   nama ayah / ibu
V_WHATSAPP     = None  # DATA WHATSAPP > Nomor              (v) contoh: 6281234567890
V_WHATSAPP_MAIL= None  # DATA WHATSAPP > Email              email
V_TELEGRAM     = None  # DATA TELEGRAM > Username           (v) username
V_TELEGRAM_ID  = None  # DATA TELEGRAM > Telegram ID        id numerik
V_TELEGRAM_NAMA= None  # DATA TELEGRAM > Nama               nama
V_LOOKUP       = None  # LOOKUP NUMBER > by Nomor           (v) 08xx / +62xx
V_LOOKUP_NAMA  = None  # LOOKUP NUMBER > by Nama            nama
V_GURUAGAMA    = None  # GURU AGAMA > Islam                 (v) nama / NUPTK / PEGID
                       #   Agama lain: ganti `choice` di routes.py
                       #   (guru_agama_agama:kristen, :katolik, :hindu, :budha, :konghucu)

# Dompet digital — semuanya minta NOMOR TELEPON. (v) contoh dari DANA: 085889451023
V_OVO          = None
V_GOPAY        = None
V_DANA         = None
V_LINKAJA      = None
V_SHOPEEPAY    = None
V_ISAKU        = None

# ============================================================================
# 2c. bot1 — tiga langkah, batch verifikasi ke-2
#     Seluruh 99 tombol submenu sudah ditekan satu per satu; yang di bawah
#     terbukti langsung meminta input. Beberapa command BERBAGI variabel
#     (mis. 10 bank sama-sama minta nomor rekening) — isi sekali, terpakai
#     untuk semuanya.
# ============================================================================
V_NOTARIS_NAMA     = None   # DATA NOTARIS › nama notaris
V_NOTARIS_BADAN    = None   # DATA NOTARIS › nama badan hukum
V_NOTARIS_BN       = None   # DATA NOTARIS › No. Berita Negara   contoh bot: 65
V_NOTARIS_TBN      = None   # DATA NOTARIS › No. Tambahan BN     contoh bot: 020478
V_NOTARIS_TAHUN    = None   # DATA NOTARIS › tahun terbit
V_MARI_PERKARA     = None   # DATA MA-RI › jenis PID — nomor perkara (boleh kosong)
V_MKRI             = None   # DATA MK-RI › kata kunci
V_CUACA            = None   # DATA BMKG › nama kelurahan/desa
V_BTS_LAC          = None   # DF TRACKING › Location Area Code   contoh bot: 35006
V_BTS_CELLID       = None   # DF TRACKING › Cell ID              contoh bot: 12345
V_BTS_KOORDINAT    = None   # DF TRACKING › lat,long
V_ECOM_NAMA        = None   # DATA ECOMMERCE › nama
V_ECOM_HP          = None   # DATA ECOMMERCE › nomor telepon
V_ECOM_EMAIL       = None   # DATA ECOMMERCE › email
V_REKENING         = None   # DATA BANK › nomor rekening — PAKAI REKENING ANDA SENDIRI
V_TELEGRAM_MAIL    = None   # DATA TELEGRAM › email / sebagian email
V_RESI             = None   # TRACKING NUMBER › kata kunci — lokasi tujuan
V_BPOM             = None   # DITTIPIDTER › keyword (nama produk/perusahaan)
V_PERUSAHAAN       = None   # DITIPIDEKSUS › NIB (contoh: 9120001380361)
V_PERIZINAN        = None   # VERIFIKASI PERIZINAN › kata kunci — No. SPPIRT
V_TRACE_HP         = None   # MONITORING TEKAB › nomor handphone
V_IMSI             = None   # MONITORING TEKAB › IMSI            contoh bot: 510116226823359
V_LINIMASA         = None   # MONITORING TEKAB › Linimasa        minta NOMOR HP (terverifikasi)
V_CELLDUM          = None   # MONITORING TEKAB › latitude, longitude
# ============================================================================
# 2d. bot1 — RANTAI dua klik (menu > submenu > submenu > nilai)
#     `Route.choice` berupa tuple. Semua tombol tingkat-2 sudah ditekan dan
#     ajakan inputnya dibaca langsung. 15 kurir berbagi V_NOMOR_RESI.
# ============================================================================
V_DPR                = None   # DATA PEMERINTAH › 🔍 Cari Nama Anggota
V_DPD                = None   # DATA PEMERINTAH › 🔍 Cari Nama Anggota
V_NAMA_AYAH          = None   # PENCARIAN BIODATA › 👨 NAMA AYAH
V_NAMA_IBU           = None   # PENCARIAN BIODATA › 👩 NAMA IBU
V_NOMOR_RESI         = None   # TRACKING NUMBER › nomor resi — PAKAI RESI KIRIMAN ANDA SENDIRI
V_HALAL_PETUGAS      = None   # DITTIPIDTER › 👤 Data Petugas
V_HALAL              = None   # DITTIPIDTER › 📦 Nama Produk
V_PERUSAHAAN_NAMA    = None   # DITIPIDEKSUS › 🏢 Nama Perusahaan
V_NIK_PERUSAHAAN     = None   # DITIPIDEKSUS › 🆔 NIK
V_ALKES              = None   # DITIPIDEKSUS › Nomor Izin Edar (NIE)

V_INFONOMOR_HLR = None   # INFO NOMOR (HLR) — nomor HP
V_HUKUM        = None   # BASIS DATA HUKUM — kata kunci peraturan

# ============================================================================
# 3. bot2 — Getphoneplusbot (dialek COMMAND, satu tembakan)
#    KUOTA TERBATAS — cek dengan /quota sebelum menjalankan.
# ============================================================================
V_GETPHONE    = HP     # /getphone <nomor>

# ============================================================================
# 4. Fitur yang BELUM didukung connector — disediakan supaya siap dipakai
#    begitu dukungannya ada. Sekarang tidak dibaca test mana pun.
# ============================================================================

# (a) Butuh TIGA langkah: menu -> submenu "pilih metode" -> nilai.
V_TRACKNUMBER     = None   # TRACKING NUMBER
V_ECOMMERCE       = None   # DATA ECOMMERCE
V_NAKES           = None   # PROFIL NAKES (pilih profesi dulu)
V_NOTARIS         = None   # DATA NOTARIS (nama / No. TBN / tahun terbit)
V_LEMBAGA         = None   # DATA LEMBAGA ("Lembaga Explorer")
V_MARI            = None   # DATA MA-RI (6 langkah)

# (b) Butuh input GAMBAR — pipeline sekarang cuma menerima value TEXT.
V_FR_SOCMED       = None   # FR SOCIAL MEDIA
V_FACE_RECOG      = None   # FACE RECOGNITION
V_FORENSIC_IMAGE  = None   # FORENSIC IMAGE
V_IMAGE_GEN       = None   # IMAGE GENERATION

# (c) Belum diverifikasi sama sekali.
V_CCTV            = None
V_BMKG            = None
V_DF_TRACKING     = None
V_CEKPOS_IP       = None
V_DATA_CENTER     = None
V_DATA_DIGITAL    = None
V_MAPPING_AREA    = None
V_PASPOR_PEKERJA  = None
V_DITTIPIDTER     = None
V_DITIPIDEKSUS    = None
V_FORENSIK_DIGITAL= None
V_BASIS_HUKUM     = None
V_VERIF_PERIZINAN = None
V_SOCIAL_MEDIA    = None
V_DATA_PEMERINTAH = None
V_TEKAB           = None


# ============================================================================
# Peta command -> nilai. Dibaca test; jangan diubah strukturnya.
# ============================================================================
BOT1 = {
    "/nik": V_NIK,                 "/kk": V_KK,
    "/foto": V_FOTO,               "/dukcapil": V_DUKCAPIL,
    "/nikinsight": V_NIKINSIGHT,   "/nikbyphone": V_NIKBYPHONE,
    "/phonebynik": V_PHONEBYNIK,   "/verifnomor": V_VERIFNOMOR,
    "/statuskartu": V_STATUSKARTU, "/track": V_TRACK,
    "/lbs": V_LBS,                 "/lbsarea": V_LBSAREA,
    "/imei": V_IMEI,               "/tnkb": V_TNKB,
    "/pln": V_PLN,                 "/dpo": V_DPO,
    "/paspor": V_PASPOR,           "/imigrasi": V_IMIGRASI,
    "/bank": V_BANK,               "/djp": V_DJP,
    "/pddikti": V_PDDIKTI,         "/pendidikan": V_PENDIDIKAN,
    "/guru": V_GURU,
    "/socmed": V_SOCMED,           "/pertamina": V_PERTAMINA,
    "/hunter": V_HUNTER,           "/pasporkerja": V_PASPORKERJA,
    "/ip": V_IP,                   "/mapping": V_MAPPING,
    "/digital": V_DIGITAL,         "/datacenter": V_DATACENTER,

    # --- alur tiga langkah ---
    "/nama": V_NAMA_BIODATA,       "/namaortu": V_NAMA_ORTU,
    "/whatsapp": V_WHATSAPP,       "/whatsappmail": V_WHATSAPP_MAIL,
    "/telegram": V_TELEGRAM,       "/telegramid": V_TELEGRAM_ID,
    "/telegramnama": V_TELEGRAM_NAMA,
    "/lookup": V_LOOKUP,           "/lookupnama": V_LOOKUP_NAMA,
    "/guruagama": V_GURUAGAMA,
    "/ovo": V_OVO,                 "/gopay": V_GOPAY,
    "/dana": V_DANA,               "/linkaja": V_LINKAJA,
    "/shopeepay": V_SHOPEEPAY,     "/isaku": V_ISAKU,

    # --- batch verifikasi ke-2 ---
    "/notaris": V_NOTARIS_NAMA,
    "/notarisbadan": V_NOTARIS_BADAN,
    "/notarisbn": V_NOTARIS_BN,
    "/notaristbn": V_NOTARIS_TBN,
    "/notaristahun": V_NOTARIS_TAHUN,
    "/maripid": V_MARI_PERKARA,
    "/maripidsus": V_MARI_PERKARA,
    "/maripdt": V_MARI_PERKARA,
    "/maripdtsus": V_MARI_PERKARA,
    "/mariag": V_MARI_PERKARA,
    "/maritun": V_MARI_PERKARA,
    "/marimil": V_MARI_PERKARA,
    "/mkri": V_MKRI,
    "/mkriputusan": V_MKRI,
    "/mkririsalah": V_MKRI,
    "/cuaca": V_CUACA,
    "/btslac": V_BTS_LAC,
    "/btscellid": V_BTS_CELLID,
    "/btskoordinat": V_BTS_KOORDINAT,
    "/ecommerce": V_ECOM_NAMA,
    "/ecommercehp": V_ECOM_HP,
    "/ecommercemail": V_ECOM_EMAIL,
    "/bca": V_REKENING,
    "/mandiri": V_REKENING,
    "/bni": V_REKENING,
    "/bjbsyariah": V_REKENING,
    "/bri": V_REKENING,
    "/bsi": V_REKENING,
    "/cimb": V_REKENING,
    "/muamalat": V_REKENING,
    "/btpn": V_REKENING,
    "/blue": V_REKENING,
    "/telegrammail": V_TELEGRAM_MAIL,
    "/resitujuan": V_RESI,
    "/resiasal": V_RESI,
    "/resipengirim": V_RESI,
    "/resipenerima": V_RESI,
    "/resikurir": V_RESI,
    "/guruagamakristen": V_GURUAGAMA,
    "/guruagamakatolik": V_GURUAGAMA,
    "/guruagamahindu": V_GURUAGAMA,
    "/guruagamabudha": V_GURUAGAMA,
    "/guruagamakonghucu": V_GURUAGAMA,
    "/bpom": V_BPOM,
    "/perusahaan": V_PERUSAHAAN,
    "/sppirt": V_PERIZINAN,
    "/nib": V_PERIZINAN,
    "/namausaha": V_PERIZINAN,
    "/produkpangan": V_PERIZINAN,
    "/traceimei": V_IMEI,
    "/tracingimei": V_IMEI,
    "/tracenumber": V_TRACE_HP,
    "/tracingimsi": V_IMSI,
    "/linimasa": V_LINIMASA,
    "/celldum": V_CELLDUM,
    "/infonomor": V_INFONOMOR_HLR,
    "/hukum": V_HUKUM,

    # --- rantai dua klik ---
    "/alkesjenis": V_ALKES,
    "/alkesnie": V_ALKES,
    "/alkespendaftar": V_ALKES,
    "/alkesproduk": V_ALKES,
    "/alkesprodusen": V_ALKES,
    "/alkestipe": V_ALKES,
    "/dpd": V_DPD,
    "/dpr": V_DPR,
    "/halalpetugas": V_HALAL_PETUGAS,
    "/halalproduk": V_HALAL,
    "/halalprodusen": V_HALAL,
    "/halalsertifikat": V_HALAL,
    "/konsorsium": V_PERUSAHAAN_NAMA,
    "/konsorsiumnik": V_NIK_PERUSAHAAN,
    "/namaayah": V_NAMA_AYAH,
    "/namaibu": V_NAMA_IBU,
    "/perkumpulan": V_PERUSAHAAN_NAMA,
    "/perseroan": V_PERUSAHAAN_NAMA,
    "/perseroanorang": V_PERUSAHAAN_NAMA,
    "/resianteraja": V_NOMOR_RESI,
    "/resifirst": V_NOMOR_RESI,
    "/resiide": V_NOMOR_RESI,
    "/resijet": V_NOMOR_RESI,
    "/resijne": V_NOMOR_RESI,
    "/resijnt": V_NOMOR_RESI,
    "/resijntcargo": V_NOMOR_RESI,
    "/resilion": V_NOMOR_RESI,
    "/resininja": V_NOMOR_RESI,
    "/resipcp": V_NOMOR_RESI,
    "/resipos": V_NOMOR_RESI,
    "/resirex": V_NOMOR_RESI,
    "/resisicepat": V_NOMOR_RESI,
    "/resitiki": V_NOMOR_RESI,
    "/resiwahana": V_NOMOR_RESI,
}

BOT2 = {
    "/getphone": V_GETPHONE,
}
