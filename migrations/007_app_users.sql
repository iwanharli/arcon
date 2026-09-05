-- Akun login aplikasi (ArtemisID dsb) — dipusatkan di sini, bukan lagi di .env.
-- Password disimpan sebagai hash PBKDF2-HMAC-SHA256 (lihat appauth.py),
-- bukan plaintext.

CREATE TABLE IF NOT EXISTS app_users (
    username      TEXT PRIMARY KEY,
    password      TEXT NOT NULL,                 -- format: pbkdf2$iter$salt$hash
    role          TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('admin', 'user')),
    active         BOOLEAN NOT NULL DEFAULT true,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_app_users_role ON app_users (role);
