-- Log aktivitas user ArtemisID (untuk menu Log khusus admin).
-- Semua aksi tercatat: login/logout, pencarian, pack, export PDF, dsb.
CREATE TABLE IF NOT EXISTS user_logs (
    id         bigserial PRIMARY KEY,
    username   text NOT NULL,
    event      text NOT NULL,
    detail     jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS user_logs_user_time_idx
    ON user_logs (username, created_at DESC);
CREATE INDEX IF NOT EXISTS user_logs_time_idx
    ON user_logs (created_at DESC);
