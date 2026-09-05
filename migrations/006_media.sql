-- Penyimpanan media (foto E-KTP dll) yang dikirim bot Telegram.
--
-- Sebagian command (mis. bot1 /foto, /photo, /nik yang menyertakan foto)
-- membalas dengan pesan foto terpisah. Connector mengunduh byte-nya dan
-- menyimpannya di sini; API menyajikannya lewat GET /media/{id}.
--
-- id = sha256 isi file, jadi foto identik otomatis ter-dedup.

CREATE TABLE IF NOT EXISTS media_blobs (
    id            TEXT PRIMARY KEY,              -- sha256 hex dari bytes
    content_type  TEXT NOT NULL DEFAULT 'image/jpeg',
    bytes         BYTEA NOT NULL,
    size          INTEGER NOT NULL,
    bot           TEXT,
    cmd           TEXT,
    value         TEXT,
    source_query_id BIGINT REFERENCES bot_query_cache(id) ON DELETE SET NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_media_query ON media_blobs (bot, cmd, value);

-- Daftar id media per hasil query disimpan di kolom baru bot_query_cache.
ALTER TABLE bot_query_cache ADD COLUMN IF NOT EXISTS media JSONB;

-- Job juga menyimpan daftar URL media hasilnya, agar GET /jobs mengembalikannya.
ALTER TABLE search_jobs ADD COLUMN IF NOT EXISTS media JSONB;
