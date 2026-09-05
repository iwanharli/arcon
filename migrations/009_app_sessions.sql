-- Riwayat pencarian aplikasi (mis. ArtemisID) per user, terpusat di DB —
-- menggantikan penyimpanan lokal .sessions.json. Satu baris = satu sesi
-- pencarian (query + command yang dijalankan). Isi lengkap disimpan di `data`.

CREATE TABLE IF NOT EXISTS app_sessions (
    id         TEXT PRIMARY KEY,
    username   TEXT NOT NULL,
    data       JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_app_sessions_user ON app_sessions (username, updated_at DESC);
