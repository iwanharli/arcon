-- Tambah opsi force di job: paksa hit Telegram walau ada di cache.
-- Dipakai healthcheck agar pengecekannya benar-benar menembak bot, bukan
-- membaca cache. Job diproses lewat worker yang sama (satu pemegang session
-- Telegram), sehingga tidak ada bentrok file session.

ALTER TABLE search_jobs ADD COLUMN IF NOT EXISTS force BOOLEAN NOT NULL DEFAULT false;
