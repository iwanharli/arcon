-- Lapis turunan ikut terhapus bersama baris cache asalnya.
--
-- ON DELETE SET NULL meninggalkan record yatim yang tidak bisa dibangun ulang
-- (rebuild.py bekerja dari bot_query_cache). Lebih buruk lagi: karena
-- profile_records punya UNIQUE (kind, subject, data) dengan ON CONFLICT DO
-- NOTHING, baris yatim MENAHAN insert baru yang isinya sama — hasil query
-- terbaru diam-diam tidak tersimpan. Terbukti pada /bpom: 9 record terurai,
-- hanya 6 masuk, 3 sisanya diblokir baris yatim dari query yang cache-nya
-- sudah dihapus.
--
-- Lapis 2 memang didefinisikan sebagai turunan lapis 1 (lihat 001_init.sql),
-- jadi CASCADE yang benar, bukan SET NULL.

DELETE FROM profile_records WHERE source_query_id IS NULL;

ALTER TABLE profile_records  DROP CONSTRAINT IF EXISTS profile_records_source_query_id_fkey;
ALTER TABLE profile_records  ADD  CONSTRAINT profile_records_source_query_id_fkey
    FOREIGN KEY (source_query_id) REFERENCES bot_query_cache(id) ON DELETE CASCADE;

ALTER TABLE profile_phones   DROP CONSTRAINT IF EXISTS profile_phones_source_query_id_fkey;
ALTER TABLE profile_phones   ADD  CONSTRAINT profile_phones_source_query_id_fkey
    FOREIGN KEY (source_query_id) REFERENCES bot_query_cache(id) ON DELETE CASCADE;

ALTER TABLE profile_vehicles DROP CONSTRAINT IF EXISTS profile_vehicles_source_query_id_fkey;
ALTER TABLE profile_vehicles ADD  CONSTRAINT profile_vehicles_source_query_id_fkey
    FOREIGN KEY (source_query_id) REFERENCES bot_query_cache(id) ON DELETE CASCADE;
