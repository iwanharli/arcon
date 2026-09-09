-- Izinkan profil tanpa NIK, tapi tetap ter-dedup.
--
-- Skema 001 sudah merancang `nik` nullable ("hasil cari-by-nama kadang tanpa
-- NIK") dengan `nama` NOT NULL, tapi upsert_profile() menolak baris tanpa NIK
-- karena tidak ada kunci untuk ON CONFLICT — akibatnya hasil pencarian
-- by-nama (mis. DATA PASPOR, PASPOR PEKERJA) tidak pernah masuk profiles.
--
-- Index parsial di bawah memberi kunci itu: nama + tanggal lahir, hanya untuk
-- baris tanpa NIK. COALESCE dipakai karena NULL tidak pernah bentrok di
-- UNIQUE, sehingga tanpa itu orang tanpa tanggal lahir akan menumpuk duplikat
-- tiap kali query yang sama diulang.
--
-- Baris ber-NIK tetap memakai UNIQUE (nik) yang sudah ada; keduanya tidak
-- saling mengganggu karena index ini hanya berlaku WHERE nik IS NULL.
CREATE UNIQUE INDEX IF NOT EXISTS uq_profiles_nama_tanpa_nik
    ON profiles (lower(nama), COALESCE(tanggal_lahir, DATE '0001-01-01'))
 WHERE nik IS NULL;
