"""Routing command bot -> normalizer + tabel tujuan.

Normalizer di normalize.py sengaja dibuat shape-agnostic (cuma melihat nama
field), jadi kalau record orang dilempar ke normalize_vehicle dia tetap balik
{pemilik, alamat}. Routing di sini yang menentukan normalizer mana yang benar
untuk tiap command, supaya tidak ada data nyasar ke tabel yang salah.

Dua dialek bot:

* **command** (Getphoneplusbot) — satu tembakan: "/getphone 0812...".
* **menu** (teamkhususantibanditbot) — ReplyKeyboard dua langkah: kirim label
  menu ("BUKA NIK"), bot membalas ajakan input, baru nilainya dikirim.
  Route-nya mengisi kolom `menu`; service.py memakai connector.ask_menu().

Nama command di sini adalah kontrak dengan aplikasi Artemis (`/search/{bot}`),
jadi untuk dialek menu pun tetap dipakai bentuk "/nik" dsb. — bukan label
menunya — supaya pemanggil tidak perlu tahu bot mana yang menu-driven.
"""
from __future__ import annotations

from typing import Callable, NamedTuple

import normalize as N


class Route(NamedTuple):
    normalizer: Callable[[dict], dict]
    target: str          # 'profiles' | 'phones' | 'vehicles' | 'records'
    kind: str | None     # dipakai kalau target = 'records'
    volatile: bool       # True = jangan pakai cache walau status 'found'
    menu: str | None = None   # label ReplyKeyboard; None = dialek command
    choice: str | None = None  # callback data tombol submenu (alur 3 langkah)
    berkas: bool = False       # True = langkah terakhir mengirim FOTO, bukan teks
    kandidat: str | None = None  # pola callback tombol hasil yang perlu diklik


def _p(target="profiles", kind=None, volatile=False, menu=None, choice=None):
    return Route(N.normalize_person, target, kind, volatile, menu, choice)


# Command yang hasilnya berubah terus (lokasi/masa aktif) ditandai volatile
# supaya selalu hit ulang ke Telegram meski di cache statusnya 'found'.
ROUTES: dict[tuple[str, str], Route] = {
    # ------------------------------------------- bot1 (teamkhususantibanditbot)
    # Dialek menu. Label diambil persis dari ReplyKeyboard /start — huruf
    # besar dan spasinya harus sama, bot mencocokkan teks mentah.
    ("bot1", "/nik"):        _p(menu="BUKA NIK"),
    ("bot1", "/kk"):         _p(menu="BUKA KK"),
    ("bot1", "/foto"):       Route(N.normalize_person, "records", "foto", False, "BUKA FOTO"),
    ("bot1", "/dukcapil"):   _p(menu="DATA DUKCAPIL"),
    ("bot1", "/nikinsight"): _p(menu="NIK INSIGHT"),

    ("bot1", "/nikbyphone"): _p(menu="NIK BY PHONE"),
    ("bot1", "/phonebynik"): Route(N.normalize_phone, "phones", None, False, "PHONE BY NIK"),
    ("bot1", "/verifnomor"): Route(N.normalize_number_info, "records", "number_info", True, "VERIFIKASI NOMOR"),
    ("bot1", "/statuskartu"): Route(N.normalize_number_info, "records", "number_info", True, "STATUS KARTU"),

    ("bot1", "/track"):      Route(N.normalize_device, "records", "device", True, "TRACKING PHONE"),
    ("bot1", "/lbs"):        Route(N.normalize_device, "records", "device", True, "LBS PLUS"),
    # LBS QUERY minta KOORDINAT/lokasi ("-6.218148,106.7979595" atau link
    # maps), bukan nomor HP — beda dari LBS PLUS.
    ("bot1", "/lbsarea"):    Route(N.normalize_device, "records", "device", True, "LBS QUERY"),
    ("bot1", "/imei"):       Route(N.normalize_device, "records", "device", True, "DETAIL IMEI"),

    ("bot1", "/tnkb"):       Route(N.normalize_vehicle, "vehicles", None, False, "DATA KENDARAAN"),
    ("bot1", "/pln"):        Route(N.normalize_pln, "records", "pln", True, "PLN INSIGHT"),
    ("bot1", "/dpo"):        Route(N.normalize_person, "records", "dpo", False, "DATA DPO"),
    ("bot1", "/paspor"):     Route(N.normalize_person, "records", "paspor", False, "DATA PASPOR"),
    ("bot1", "/imigrasi"):   Route(N.normalize_person, "records", "imigrasi", False, "DATA IMIGRASI"),
    ("bot1", "/bank"):       Route(N.normalize_person, "records", "bank", False, "DATA BANK"),
    ("bot1", "/pddikti"):    Route(N.normalize_raw, "records", "pddikti", False, "DATA PDDIKTI"),
    ("bot1", "/pendidikan"): Route(N.normalize_person, "records", "pendidikan", False, "PROFIL PENDIDIKAN"),
    ("bot1", "/guru"):       Route(N.normalize_person, "records", "guru", False, "GURU UMUM"),
    ("bot1", "/djp"):        Route(N.normalize_raw, "records", "perusahaan", False, "DATA DJP"),

    # --- Menu dua langkah yang baru terverifikasi lewat pemetaan 61 menu ---
    # Semuanya "input langsung": menu -> ajakan input -> nilai.
    ("bot1", "/socmed"):     Route(N.normalize_person, "records", "social_media", False, "SOCIAL MEDIA"),
    ("bot1", "/pertamina"):  Route(N.normalize_person, "records", "pertamina", False, "PERTAMINA"),
    ("bot1", "/hunter"):     Route(N.normalize_vehicle, "vehicles", None, False, "HUNTER"),
    ("bot1", "/pasporkerja"): Route(N.normalize_person, "records", "paspor", False, "PASPOR PEKERJA"),
    ("bot1", "/ip"):         Route(N.normalize_raw, "records", "ip_domain", False, "CEKPOS IP"),
    ("bot1", "/mapping"):    Route(N.normalize_device, "records", "device", True, "MAPPING AREA"),
    ("bot1", "/digital"):    Route(N.normalize_raw, "records", "data_digital", False, "DATA DIGITAL"),
    ("bot1", "/datacenter"): Route(N.normalize_raw, "records", "data_center", False, "DATA CENTER"),

    # ------------------------------------------------ bot1: input berupa FOTO
    # Ada DUA fitur berbasis wajah, dan keduanya berbeda:
    #
    #   FACE RECOGNITION  -> pengenalan wajah. Balasannya sebuah FOTO berjudul
    #     "CONTOH UPLOAD FOTO", tanpa kalimat ajakan — sempat dikira cuma
    #     pajangan contoh. Ternyata ia memang menunggu foto: menekan Batal di
    #     situ dijawab "Proses pengenalan wajah dibatalkan".
    #   FR SOCIAL MEDIA   -> penelusuran wajah di media sosial, mengembalikan
    #     daftar situs tempat wajah itu muncul.
    # FACE RECOGNITION butuh EMPAT langkah: menu -> kirim foto -> pilih mode
    # -> hasil. Mode dicocokkan lewat TEKS tombolnya, bukan callback data,
    # supaya tidak bergantung penamaan internal bot.
    #
    # Botnya menawarkan tiga mode (Deep / Quick / Multiple Match); yang dipakai
    # Artemis hanya Quick Match, jadi hanya itu yang dirutekan.
    # `kandidat`: hasilnya berupa daftar kecocokan yang detailnya baru muncul
    # setelah tombolnya diklik ("Lihat Data NIK ..." -> view_nik_<nik>).
    ("bot1", "/fr"): Route(N.normalize_person, "records", "face", False,
                           "FACE RECOGNITION", "Quick Match", True, "view_nik_"),
    ("bot1", "/frsocmed"): Route(N.normalize_person, "records", "face_socmed", False,
                                 "\U0001F525 FR SOCIAL MEDIA", None, True),

    # ------------------------------------------------- bot1: alur TIGA langkah
    # menu -> klik tombol submenu (callback data di kolom `choice`) -> nilai.
    # Ajakan input yang ditandai (v) sudah dibuka & dibaca langsung; sisanya
    # tombol sekerabat yang jenis inputnya jelas dari nama tombolnya sendiri.
    ("bot1", "/nama"):       _p(menu="PENCARIAN BIODATA", choice="pb_cari_nama"),          # (v) nama
    ("bot1", "/namaortu"):   _p(menu="PENCARIAN BIODATA", choice="pb_cari_ortu"),          # nama ayah/ibu
    ("bot1", "/whatsapp"):   Route(N.normalize_person, "records", "whatsapp", True,
                                   "DATA WHATSAPP", "wa_profiling_phone"),                 # (v) nomor
    ("bot1", "/whatsappmail"): Route(N.normalize_person, "records", "whatsapp", True,
                                   "DATA WHATSAPP", "wa_profiling_email"),                 # email
    ("bot1", "/telegram"):   Route(N.normalize_person, "records", "telegram", True,
                                   "DATA TELEGRAM", "telegram_profiling_by_username"),     # (v) username
    ("bot1", "/telegramid"): Route(N.normalize_person, "records", "telegram", True,
                                   "DATA TELEGRAM", "telegram_profiling_by_id"),           # telegram id
    ("bot1", "/telegramnama"): Route(N.normalize_person, "records", "telegram", True,
                                   "DATA TELEGRAM", "telegram_profiling_by_name"),         # nama
    ("bot1", "/lookup"):     Route(N.normalize_number_info, "records", "number_info", True,
                                   "LOOKUP NUMBER", "lookup_by_phone"),                    # (v) nomor
    ("bot1", "/lookupnama"): Route(N.normalize_number_info, "records", "number_info", True,
                                   "LOOKUP NUMBER", "lookup_by_name"),                     # nama
    ("bot1", "/guruagama"):  Route(N.normalize_person, "records", "guru", False,
                                   "GURU AGAMA", "guru_agama_agama:islam"),                # (v) nama/NUPTK/PEGID
    # Dompet digital: satu route per e-wallet, semuanya minta nomor telepon.
    ("bot1", "/ovo"):        Route(N.normalize_person, "records", "dompet_digital", True,
                                   "DOMPET DIGITAL", "ewallet_pick_OVO"),
    ("bot1", "/gopay"):      Route(N.normalize_person, "records", "dompet_digital", True,
                                   "DOMPET DIGITAL", "ewallet_pick_GOPAY"),
    ("bot1", "/dana"):       Route(N.normalize_person, "records", "dompet_digital", True,
                                   "DOMPET DIGITAL", "ewallet_pick_DANA"),                 # (v) nomor
    ("bot1", "/linkaja"):    Route(N.normalize_person, "records", "dompet_digital", True,
                                   "DOMPET DIGITAL", "ewallet_pick_LINKAJA"),
    ("bot1", "/shopeepay"):  Route(N.normalize_person, "records", "dompet_digital", True,
                                   "DOMPET DIGITAL", "ewallet_pick_SHOPEEPAY"),
    ("bot1", "/isaku"):      Route(N.normalize_person, "records", "dompet_digital", True,
                                   "DOMPET DIGITAL", "ewallet_pick_ISAKU"),

    # Dua menu ini sempat salah diklasifikasi sebagai submenu: pesannya panjang
    # dan memuat kata "pilih", padahal hanya bertombol Batal dan langsung
    # menunggu input.
    ("bot1", "/infonomor"):  Route(N.normalize_number_info, "records", "number_info", True, "INFO NOMOR"),
    ("bot1", "/hukum"):      Route(N.normalize_raw, "records", "hukum", False, "BASIS DATA HUKUM"),

    # ---------------------------------- bot1: tiga langkah (batch verifikasi 2)
    # Seluruh 99 tombol submenu ditekan satu per satu (9 Sep 2026); yang di
    # bawah ini terbukti langsung meminta input, jadi cukup satu klik.

    # --- DATA NOTARIS ---
    ("bot1", "/notaris"): Route(N.normalize_raw, "records", "notaris", False, "DATA NOTARIS", "notaris_sel:nama"),
    ("bot1", "/notarisbadan"): Route(N.normalize_raw, "records", "notaris", False, "DATA NOTARIS", "notaris_sel:badan_hukum"),
    ("bot1", "/notarisbn"): Route(N.normalize_raw, "records", "notaris", False, "DATA NOTARIS", "notaris_sel:no_bn"),
    ("bot1", "/notaristbn"): Route(N.normalize_raw, "records", "notaris", False, "DATA NOTARIS", "notaris_sel:no_tbn"),
    ("bot1", "/notaristahun"): Route(N.normalize_raw, "records", "notaris", False, "DATA NOTARIS", "notaris_sel:tahun"),

    # --- DATA MA-RI ---
    ("bot1", "/maripid"): Route(N.normalize_raw, "records", "hukum", False, "DATA MA-RI", "mari_ri_panmud_PID"),
    ("bot1", "/maripidsus"): Route(N.normalize_raw, "records", "hukum", False, "DATA MA-RI", "mari_ri_panmud_PID.SUS"),
    ("bot1", "/maripdt"): Route(N.normalize_raw, "records", "hukum", False, "DATA MA-RI", "mari_ri_panmud_PDT"),
    ("bot1", "/maripdtsus"): Route(N.normalize_raw, "records", "hukum", False, "DATA MA-RI", "mari_ri_panmud_PDT.SUS"),
    ("bot1", "/mariag"): Route(N.normalize_raw, "records", "hukum", False, "DATA MA-RI", "mari_ri_panmud_AG"),
    ("bot1", "/maritun"): Route(N.normalize_raw, "records", "hukum", False, "DATA MA-RI", "mari_ri_panmud_TUN"),
    ("bot1", "/marimil"): Route(N.normalize_raw, "records", "hukum", False, "DATA MA-RI", "mari_ri_panmud_MIL"),

    # --- DATA MK-RI ---
    ("bot1", "/mkri"): Route(N.normalize_raw, "records", "hukum", False, "DATA MK-RI", "mkri_sub_ikhtisar"),
    ("bot1", "/mkriputusan"): Route(N.normalize_raw, "records", "hukum", False, "DATA MK-RI", "mkri_sub_putusan"),
    ("bot1", "/mkririsalah"): Route(N.normalize_raw, "records", "hukum", False, "DATA MK-RI", "mkri_sub_risalah"),

    # --- DATA BMKG ---
    ("bot1", "/cuaca"): Route(N.normalize_raw, "records", "bmkg", True, "DATA BMKG", "bmkg_prakiraan_cuaca"),

    # --- DF TRACKING ---
    ("bot1", "/btslac"): Route(N.normalize_device, "records", "device", True, "DF TRACKING", "bts_type_lac"),
    ("bot1", "/btscellid"): Route(N.normalize_device, "records", "device", True, "DF TRACKING", "bts_type_cell_id"),
    ("bot1", "/btskoordinat"): Route(N.normalize_device, "records", "device", True, "DF TRACKING", "bts_type_coordinate"),

    # --- DATA ECOMMERCE ---
    ("bot1", "/ecommerce"): Route(N.normalize_person, "records", "ecommerce", False, "DATA ECOMMERCE", "ecommerce_search:name"),
    ("bot1", "/ecommercehp"): Route(N.normalize_person, "records", "ecommerce", False, "DATA ECOMMERCE", "ecommerce_search:phone"),
    ("bot1", "/ecommercemail"): Route(N.normalize_person, "records", "ecommerce", False, "DATA ECOMMERCE", "ecommerce_search:email"),

    # --- DATA BANK ---
    ("bot1", "/bca"): Route(N.normalize_person, "records", "bank", False, "DATA BANK", "bank_select:270"),
    ("bot1", "/mandiri"): Route(N.normalize_person, "records", "bank", False, "DATA BANK", "bank_select:271"),
    ("bot1", "/bni"): Route(N.normalize_person, "records", "bank", False, "DATA BANK", "bank_select:272"),
    ("bot1", "/bjbsyariah"): Route(N.normalize_person, "records", "bank", False, "DATA BANK", "bank_select:273"),
    ("bot1", "/bri"): Route(N.normalize_person, "records", "bank", False, "DATA BANK", "bank_select:274"),
    ("bot1", "/bsi"): Route(N.normalize_person, "records", "bank", False, "DATA BANK", "bank_select:275"),
    ("bot1", "/cimb"): Route(N.normalize_person, "records", "bank", False, "DATA BANK", "bank_select:276"),
    ("bot1", "/muamalat"): Route(N.normalize_person, "records", "bank", False, "DATA BANK", "bank_select:277"),
    ("bot1", "/btpn"): Route(N.normalize_person, "records", "bank", False, "DATA BANK", "bank_select:279"),
    ("bot1", "/blue"): Route(N.normalize_person, "records", "bank", False, "DATA BANK", "bank_select:280"),

    # --- DATA TELEGRAM ---
    ("bot1", "/telegrammail"): Route(N.normalize_person, "records", "telegram", True, "DATA TELEGRAM", "telegram_profiling_by_email"),

    # --- TRACKING NUMBER ---
    ("bot1", "/resitujuan"): Route(N.normalize_raw, "records", "resi", False, "TRACKING NUMBER", "track_search_destination"),
    ("bot1", "/resiasal"): Route(N.normalize_raw, "records", "resi", False, "TRACKING NUMBER", "track_search_origin"),
    ("bot1", "/resipengirim"): Route(N.normalize_raw, "records", "resi", False, "TRACKING NUMBER", "track_search_shipper"),
    ("bot1", "/resipenerima"): Route(N.normalize_raw, "records", "resi", False, "TRACKING NUMBER", "track_search_receiver"),
    ("bot1", "/resikurir"): Route(N.normalize_raw, "records", "resi", False, "TRACKING NUMBER", "track_search_courier"),

    # --- GURU AGAMA ---
    ("bot1", "/guruagamakristen"): Route(N.normalize_person, "records", "guru", False, "GURU AGAMA", "guru_agama_agama:kristen"),
    ("bot1", "/guruagamakatolik"): Route(N.normalize_person, "records", "guru", False, "GURU AGAMA", "guru_agama_agama:katolik"),
    ("bot1", "/guruagamahindu"): Route(N.normalize_person, "records", "guru", False, "GURU AGAMA", "guru_agama_agama:hindu"),
    ("bot1", "/guruagamabudha"): Route(N.normalize_person, "records", "guru", False, "GURU AGAMA", "guru_agama_agama:budha"),
    ("bot1", "/guruagamakonghucu"): Route(N.normalize_person, "records", "guru", False, "GURU AGAMA", "guru_agama_agama:konghucu"),

    # --- DITTIPIDTER ---
    ("bot1", "/bpom"): Route(N.normalize_raw, "records", "perusahaan", False, "DITTIPIDTER", "dittipidter_bpom"),

    # --- DITIPIDEKSUS ---
    ("bot1", "/perusahaan"): Route(N.normalize_raw, "records", "perusahaan", False, "DITIPIDEKSUS", "ditipideksus_profil_perusahaan"),

    # --- VERIFIKASI PERIZINAN ---
    ("bot1", "/sppirt"): Route(N.normalize_raw, "records", "perizinan", False, "VERIFIKASI PERIZINAN", "sppirt_select_no_sppirt"),
    ("bot1", "/nib"): Route(N.normalize_raw, "records", "perizinan", False, "VERIFIKASI PERIZINAN", "sppirt_select_nib"),
    ("bot1", "/namausaha"): Route(N.normalize_raw, "records", "perizinan", False, "VERIFIKASI PERIZINAN", "sppirt_select_nama_usaha"),
    ("bot1", "/produkpangan"): Route(N.normalize_raw, "records", "perizinan", False, "VERIFIKASI PERIZINAN", "sppirt_select_nama_produk_pangan"),

    # --- MONITORING TEKAB ---
    ("bot1", "/traceimei"): Route(N.normalize_device, "records", "device", True, "MONITORING TEKAB", "trace_imei"),
    ("bot1", "/tracingimei"): Route(N.normalize_device, "records", "device", True, "MONITORING TEKAB", "tracing_imei"),
    ("bot1", "/tracenumber"): Route(N.normalize_device, "records", "device", True, "MONITORING TEKAB", "trace_number"),
    ("bot1", "/tracingimsi"): Route(N.normalize_device, "records", "device", True, "MONITORING TEKAB", "tracing_imsi"),
    ("bot1", "/linimasa"): Route(N.normalize_device, "records", "device", True, "MONITORING TEKAB", "linimasa"),
    ("bot1", "/celldum"): Route(N.normalize_device, "records", "device", True, "MONITORING TEKAB", "celldum_data"),

    # ------------------------------- bot1: rantai DUA klik (menu > sub > sub)
    # Dipetakan dengan menekan tiap tombol tingkat-2 (9 Sep 2026).
    # `choice` berupa tuple: tombol diklik berurutan.
    ("bot1", "/alkesjenis"): Route(N.normalize_raw, "records", 'perusahaan', False, "DITIPIDEKSUS", ("ditipideksus_produk_perusahaan", "alkes_cat_6")),
    ("bot1", "/alkesnie"): Route(N.normalize_raw, "records", 'perusahaan', False, "DITIPIDEKSUS", ("ditipideksus_produk_perusahaan", "alkes_cat_1")),
    ("bot1", "/alkespendaftar"): Route(N.normalize_raw, "records", 'perusahaan', False, "DITIPIDEKSUS", ("ditipideksus_produk_perusahaan", "alkes_cat_3")),
    ("bot1", "/alkesproduk"): Route(N.normalize_raw, "records", 'perusahaan', False, "DITIPIDEKSUS", ("ditipideksus_produk_perusahaan", "alkes_cat_2")),
    ("bot1", "/alkesprodusen"): Route(N.normalize_raw, "records", 'perusahaan', False, "DITIPIDEKSUS", ("ditipideksus_produk_perusahaan", "alkes_cat_5")),
    ("bot1", "/alkestipe"): Route(N.normalize_raw, "records", 'perusahaan', False, "DITIPIDEKSUS", ("ditipideksus_produk_perusahaan", "alkes_cat_4")),
    ("bot1", "/dpd"): Route(N.normalize_person, "records", 'pemerintah', False, "DATA PEMERINTAH", ("pemerintah_sub_dpd", "dpd_sub_cari_nama")),
    ("bot1", "/dpr"): Route(N.normalize_person, "records", 'pemerintah', False, "DATA PEMERINTAH", ("pemerintah_sub_dpr", "dpr_sub_cari_nama")),
    ("bot1", "/halalpetugas"): Route(N.normalize_raw, "records", 'perusahaan', False, "DITTIPIDTER", ("dittipidter_halal", "dittipidter_halal_petugas")),
    ("bot1", "/halalproduk"): Route(N.normalize_raw, "records", 'perusahaan', False, "DITTIPIDTER", ("dittipidter_halalmui", "halalmui_filter:nama_produk")),
    ("bot1", "/halalprodusen"): Route(N.normalize_raw, "records", 'perusahaan', False, "DITTIPIDTER", ("dittipidter_halalmui", "halalmui_filter:nama_produsen")),
    ("bot1", "/halalsertifikat"): Route(N.normalize_raw, "records", 'perusahaan', False, "DITTIPIDTER", ("dittipidter_halalmui", "halalmui_filter:no_sertifikat")),
    ("bot1", "/konsorsium"): Route(N.normalize_raw, "records", 'perusahaan', False, "DITIPIDEKSUS", ("ditipideksus_konsorsium", "company_search:nama_perseroan")),
    ("bot1", "/konsorsiumnik"): Route(N.normalize_raw, "records", 'perusahaan', False, "DITIPIDEKSUS", ("ditipideksus_konsorsium", "company_search:nik")),
    ("bot1", "/namaayah"): Route(N.normalize_person, "profiles", None, False, "PENCARIAN BIODATA", ("pb_cari_ortu", "pb_filter_ayah")),
    ("bot1", "/namaibu"): Route(N.normalize_person, "profiles", None, False, "PENCARIAN BIODATA", ("pb_cari_ortu", "pb_filter_ibu")),
    ("bot1", "/perkumpulan"): Route(N.normalize_raw, "records", 'perusahaan', False, "DITIPIDEKSUS", ("ditipideksus_badan_hukum", "badan_hukum_perkumpulan")),
    ("bot1", "/perseroan"): Route(N.normalize_raw, "records", 'perusahaan', False, "DITIPIDEKSUS", ("ditipideksus_badan_hukum", "badan_hukum_perseroan")),
    ("bot1", "/perseroanorang"): Route(N.normalize_raw, "records", 'perusahaan', False, "DITIPIDEKSUS", ("ditipideksus_badan_hukum", "badan_hukum_perseroan_perorangan")),
    ("bot1", "/resianteraja"): Route(N.normalize_person, "records", 'resi', False, "TRACKING NUMBER", ("track_mode_new", "courier_anteraja")),
    ("bot1", "/resifirst"): Route(N.normalize_person, "records", 'resi', False, "TRACKING NUMBER", ("track_mode_new", "courier_first")),
    ("bot1", "/resiide"): Route(N.normalize_person, "records", 'resi', False, "TRACKING NUMBER", ("track_mode_new", "courier_ide")),
    ("bot1", "/resijet"): Route(N.normalize_person, "records", 'resi', False, "TRACKING NUMBER", ("track_mode_new", "courier_jet")),
    ("bot1", "/resijne"): Route(N.normalize_person, "records", 'resi', False, "TRACKING NUMBER", ("track_mode_new", "courier_jne")),
    ("bot1", "/resijnt"): Route(N.normalize_person, "records", 'resi', False, "TRACKING NUMBER", ("track_mode_new", "courier_jnt")),
    ("bot1", "/resijntcargo"): Route(N.normalize_person, "records", 'resi', False, "TRACKING NUMBER", ("track_mode_new", "courier_jnt_cargo")),
    ("bot1", "/resilion"): Route(N.normalize_person, "records", 'resi', False, "TRACKING NUMBER", ("track_mode_new", "courier_lion")),
    ("bot1", "/resininja"): Route(N.normalize_person, "records", 'resi', False, "TRACKING NUMBER", ("track_mode_new", "courier_ninja")),
    ("bot1", "/resipcp"): Route(N.normalize_person, "records", 'resi', False, "TRACKING NUMBER", ("track_mode_new", "courier_pcp")),
    ("bot1", "/resipos"): Route(N.normalize_person, "records", 'resi', False, "TRACKING NUMBER", ("track_mode_new", "courier_pos")),
    ("bot1", "/resirex"): Route(N.normalize_person, "records", 'resi', False, "TRACKING NUMBER", ("track_mode_new", "courier_rex")),
    ("bot1", "/resisicepat"): Route(N.normalize_person, "records", 'resi', False, "TRACKING NUMBER", ("track_mode_new", "courier_sicepat")),
    ("bot1", "/resitiki"): Route(N.normalize_person, "records", 'resi', False, "TRACKING NUMBER", ("track_mode_new", "courier_tiki")),
    ("bot1", "/resiwahana"): Route(N.normalize_person, "records", 'resi', False, "TRACKING NUMBER", ("track_mode_new", "courier_wahana")),

    # Menu bot1 yang BELUM dirutekan.
    #
    # (a) Butuh TIGA langkah — menu membuka submenu pilihan metode dulu, baru
    #     minta nilai. ask_menu() hanya menangani dua langkah, jadi command
    #     ini akan macet di layar submenu:
    #     PENCARIAN BIODATA, INFO NOMOR, LOOKUP NUMBER, TRACKING NUMBER,
    #     DATA WHATSAPP, DATA TELEGRAM, DATA ECOMMERCE, DOMPET DIGITAL,
    #     PROFIL NAKES, DATA NOTARIS, DATA MA-RI (6 langkah), DATA MK-RI,
    #     GURU AGAMA (pilih agama dulu), DATA PEMERINTAH, DATA BMKG,
    #     DF TRACKING, DITTIPIDTER, DITIPIDEKSUS, ANALISIS FORENSIK DIGITAL,
    #     VERIFIKASI PERIZINAN, MONITORING TEKAB, BASIS DATA HUKUM.
    #     DATA LEMBAGA memakai UI "Lembaga Explorer" sendiri.
    #
    # (b) Butuh input gambar, tidak muat di pipeline value TEXT:
    #     FR SOCIAL MEDIA, FACE RECOGNITION, FORENSIC IMAGE, IMAGE GENERATION.
    #
    # (c) Tidak punya alur input yang bisa dipakai: DATA CCTV, DATA LEMBAGA
    #     ("Lembaga Explorer"), INFORMATION TEKAB, MANAGEMENT TEKAB (halaman
    #     informasi, bukan pencarian).
    #
    # Seluruh 61 menu sudah dipetakan satu per satu (9 Sep 2026); klasifikasi
    # di atas berasal dari pemetaan itu, bukan dari nama menunya.

    # ----------------------------------------------------- bot2 (Getphoneplusbot)
    # Dialek command satu tembakan.
    ("bot2", "/getphone"):   Route(N.normalize_number_info, "records", "number_info", True),
}


def get_route(bot: str, cmd: str) -> Route | None:
    return ROUTES.get((bot, cmd))


def is_volatile(bot: str, cmd: str) -> bool:
    """Command lokasi/masa-aktif tidak boleh dijawab dari cache lama."""
    route = ROUTES.get((bot, cmd))
    return bool(route and route.volatile)


def menu_label(bot: str, cmd: str) -> str | None:
    """Label ReplyKeyboard untuk command ini, None kalau dialek command."""
    route = ROUTES.get((bot, cmd))
    return route.menu if route else None


def pola_kandidat(bot: str, cmd: str) -> str | None:
    """Pola callback tombol kandidat yang perlu ditelusuri, kalau ada."""
    route = ROUTES.get((bot, cmd))
    return route.kandidat if route else None


def butuh_berkas(bot: str, cmd: str) -> bool:
    """True kalau langkah terakhir command ini mengirim foto, bukan teks."""
    route = ROUTES.get((bot, cmd))
    return bool(route and route.berkas)


def submenu_choice(bot: str, cmd: str) -> str | None:
    """Callback data tombol submenu, None kalau alurnya cuma dua langkah."""
    route = ROUTES.get((bot, cmd))
    return route.choice if route else None
