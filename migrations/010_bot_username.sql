-- Rekam bot ASLI di tiap baris cache, bukan cuma slot logisnya.
--
-- Kenapa perlu: kolom `bot` isinya slot logis ('bot1'), dan slot itu dipakai
-- ulang saat bot target diganti. Waktu bot1 berpindah dari cielodespejadobot
-- ke teamkhususantibanditbot, 12 baris cache lama dengan cmd yang namanya
-- kebetulan sama (/nik, /kk, /nama, /foto, /tnkb, /pln, /dpo, /guru) langsung
-- memenuhi syarat lookup dan akan dijawab sebagai hasil bot baru — padahal
-- sumbernya bot yang sudah tidak dipakai.
--
-- Dengan bot_username terekam, pergantian bot berikutnya bisa dideteksi
-- (bandingkan dengan config.BOTS) tanpa menebak-nebak dari tanggal.

ALTER TABLE bot_query_cache ADD COLUMN IF NOT EXISTS bot_username TEXT;
ALTER TABLE search_jobs     ADD COLUMN IF NOT EXISTS bot_username TEXT;
ALTER TABLE command_probes  ADD COLUMN IF NOT EXISTS bot_username TEXT;

CREATE INDEX IF NOT EXISTS idx_cache_bot_username
    ON bot_query_cache (bot_username, cmd, value);
