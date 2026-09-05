-- Daftar user Telegram yang boleh memakai bot antarmuka (frontend API).
-- Bot menyajikan data pribadi, jadi hanya ID yang terdaftar di sini yang
-- dilayani; selain itu ditolak. Admin bisa menambah user lewat perintah bot.

CREATE TABLE IF NOT EXISTS bot_users (
    telegram_id  BIGINT PRIMARY KEY,
    name         TEXT,
    role         TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('admin', 'user')),
    added_by     BIGINT,
    added_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ
);

-- Catatan pemakaian bot (audit: siapa mencari apa lewat bot).
CREATE TABLE IF NOT EXISTS bot_audit (
    id          BIGSERIAL PRIMARY KEY,
    telegram_id BIGINT,
    bot         TEXT,
    cmd         TEXT,
    value       TEXT,
    status      TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_bot_audit_user ON bot_audit (telegram_id, created_at DESC);
