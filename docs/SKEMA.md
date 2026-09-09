# Skema data per command

Dibangun otomatis oleh `skema.py` dari hasil nyata. **29 dari 139** command sudah terverifikasi bentuk datanya.

Command yang belum terverifikasi bukan berarti tidak berfungsi — bentuk datanya saja yang belum pernah terlihat (umumnya karena kuota harian habis saat pengujian).

## Terverifikasi

| command | menu | tabel | atribut |
|---|---|---|---|
| `/alkesjenis` | DITIPIDEKSUS | records[perusahaan] | `kategori`, `keterangan`, `nie`, `pendaftar`, `produk`, `produsen`, `status_nie`, `tipe` |
| `/alkesnie` | DITIPIDEKSUS | records[perusahaan] | `kategori` |
| `/alkespendaftar` | DITIPIDEKSUS | records[perusahaan] | `kategori`, `keterangan`, `nie`, `pendaftar`, `produk`, `produsen`, `status_nie`, `tipe` |
| `/alkesproduk` | DITIPIDEKSUS | records[perusahaan] | `kategori`, `keterangan`, `nie`, `pendaftar`, `produk`, `produsen`, `status_nie`, `tipe` |
| `/alkesprodusen` | DITIPIDEKSUS | records[perusahaan] | `kategori`, `keterangan`, `nie`, `pendaftar`, `produk`, `produsen`, `status_nie`, `tipe` |
| `/alkestipe` | DITIPIDEKSUS | records[perusahaan] | `kategori`, `keterangan`, `nie`, `pendaftar`, `produk`, `produsen`, `status_nie`, `tipe` |
| `/bpom` | DITTIPIDTER | records[perusahaan] | `berlaku_sampai`, `jenis_pendaftaran`, `kategori`, `kemasan`, `merk`, `nama`, `nie`, `pendaftar`, `status`, `tanggal_daftar` |
| `/btscellid` | DF TRACKING | records[device] | `address`, `azimuth`, `cell_id`, `cell_name`, `city`, `lac`, `lacci`, `latitude`, `longitude`, `mcc`, `mnc`, `network`, `plmn_id`, `province`, `site_id`, `site_name`, `status`, `sub_district` |
| `/btskoordinat` | DF TRACKING | records[device] | `lat` |
| `/btslac` | DF TRACKING | records[device] | `lac` |
| `/datacenter` | DATA CENTER | records[data_center] | `hasil_pencarian_untuk`, `total_database` |
| `/dpr` | DATA PEMERINTAH | records[pemerintah] | `dapil`, `email`, `fraksi`, `id_anggota`, `nama`, `nomor_anggota`, `periode`, `singkatan_fraksi`, `tahun_2013`, `tahun_2015`, `tahun_2016`, `tahun_2019`, `tanggal_lahir`, `tempat_lahir` |
| `/getphone` | - | records[number_info] | `cek_link_whatsapp`, `contact_tags`, `dana`, `gopay`, `identitas_utama`, `isaku`, `keterangan`, `linkaja`, `msisdn`, `nama_teridentifikasi`, `nomor`, `ovo`, `primary`, `search_engine`, `shopeepay`, `total`, `whatsapp`, `wilayah` |
| `/halalproduk` | DITTIPIDTER | records[perusahaan] | `nama_produsen`, `nomor_sertifikat` |
| `/halalprodusen` | DITTIPIDTER | records[perusahaan] | `nama_produsen`, `nomor_sertifikat` |
| `/imei` | DETAIL IMEI | records[device] | `brand`, `imei`, `model`, `model_name` |
| `/ip` | CEKPOS IP | records[ip_domain] | `abuse_email`, `asn`, `calling_code`, `capital`, `city`, `contact_person`, `continent`, `coordinates`, `country`, `domain`, `email`, `hasil_cekpos_ip_untuk`, `input_type`, `ip_address`, `ip_range`, `isp`, `last_modified`, `network_name`, `organization`, `origin_as`, `phone`, `postal_code`, `region`, `route`, `status`, `timestamp`, `timezone`, `type`, `utc_offset` |
| `/konsorsium` | DITIPIDEKSUS | records[perusahaan] | `jenis_pencarian`, `kab_kota`, `provinsi` |
| `/lbs` | LBS PLUS | records[device] | `nomor` |
| `/lbsarea` | LBS QUERY | records[device] | `latitude`, `longitude` |
| `/linimasa` | MONITORING TEKAB | records[device] | `nomor_hp` |
| `/mapping` | MAPPING AREA | records[device] | `latitude`, `longitude` |
| `/mkri` | DATA MK-RI | records[hukum] | `di_unduh`, `file_pendukung`, `pokok_perkara`, `tanggal` |
| `/nikinsight` | NIK INSIGHT | profiles | `budaya`, `desa_kelurahan`, `desa_kode_pos`, `generasi`, `hari`, `jenis_kelamin`, `kalender`, `kecamatan`, `kelompok_usia`, `kode_pos`, `kota_kabupaten`, `neptu`, `nik`, `provinsi`, `pulau`, `rentang`, `shio`, `struktur`, `tanggal_lahir`, `tipe_data`, `total_hari`, `total_minggu`, `ulang_tahun_berikutnya`, `usia`, `usia_produktif`, `zodiak`, `zona_waktu` |
| `/paspor` | DATA PASPOR | records[paspor] | `berlaku_sampai`, `jenis_kelamin`, `nama`, `nikim`, `nomor_paspor`, `tanggal_lahir` |
| `/pasporkerja` | PASPOR PEKERJA | records[paspor] | `alamat`, `berlaku_sampai`, `diterbitkan_di`, `lembaga_perusahaan`, `nama`, `negara_penempatan`, `nomor_id`, `nomor_paspor` |
| `/tracenumber` | MONITORING TEKAB | records[device] | `imei`, `waktu` |
| `/tracingimsi` | MONITORING TEKAB | records[device] | `nomor_hp_terhubung`, `tracing_imsi` |
| `/track` | TRACKING PHONE | records[device] | `data_imsi`, `data_koordinat`, `kediaman`, `lac`, `lainnya`, `mobile_number`, `terakhir_aktif`, `whatsapp` |

## Belum terverifikasi

`/bank`, `/bca`, `/bjbsyariah`, `/blue`, `/bni`, `/bri`, `/bsi`, `/btpn`, `/celldum`, `/cimb`, `/cuaca`, `/dana`, `/digital`, `/djp`, `/dpd`, `/dpo`, `/dukcapil`, `/ecommerce`, `/ecommercehp`, `/ecommercemail`, `/foto`, `/gopay`, `/guru`, `/guruagama`, `/guruagamabudha`, `/guruagamahindu`, `/guruagamakatolik`, `/guruagamakonghucu`, `/guruagamakristen`, `/halalpetugas`, `/halalsertifikat`, `/hukum`, `/hunter`, `/imigrasi`, `/infonomor`, `/isaku`, `/kk`, `/konsorsiumnik`, `/linkaja`, `/lookup`, `/lookupnama`, `/mandiri`, `/mariag`, `/marimil`, `/maripdt`, `/maripdtsus`, `/maripid`, `/maripidsus`, `/maritun`, `/mkriputusan`, `/mkririsalah`, `/muamalat`, `/nama`, `/namaayah`, `/namaibu`, `/namaortu`, `/namausaha`, `/nib`, `/nik`, `/nikbyphone`, `/notaris`, `/notarisbadan`, `/notarisbn`, `/notaristahun`, `/notaristbn`, `/ovo`, `/pddikti`, `/pendidikan`, `/perkumpulan`, `/perseroan`, `/perseroanorang`, `/pertamina`, `/perusahaan`, `/phonebynik`, `/pln`, `/produkpangan`, `/resianteraja`, `/resiasal`, `/resifirst`, `/resiide`, `/resijet`, `/resijne`, `/resijnt`, `/resijntcargo`, `/resikurir`, `/resilion`, `/resininja`, `/resipcp`, `/resipenerima`, `/resipengirim`, `/resipos`, `/resirex`, `/resisicepat`, `/resitiki`, `/resitujuan`, `/resiwahana`, `/shopeepay`, `/socmed`, `/sppirt`, `/statuskartu`, `/telegram`, `/telegramid`, `/telegrammail`, `/telegramnama`, `/tnkb`, `/traceimei`, `/tracingimei`, `/verifnomor`, `/whatsapp`, `/whatsappmail`
