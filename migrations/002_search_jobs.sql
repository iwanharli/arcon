-- Antrian pencarian dari aplikasi Artemis.
--
-- Antrian disimpan di tabel (bukan cuma di memori) supaya:
--   - job tidak hilang kalau worker/API restart
--   - Artemis bisa melihat posisi antrian & riwayatnya
--   - bisa diaudit: siapa mencari apa, kapan

CREATE TABLE IF NOT EXISTS search_jobs (
    id            BIGSERIAL PRIMARY KEY,
    job_id        UUID        NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    bot           TEXT        NOT NULL,
    cmd           TEXT        NOT NULL,
    value         TEXT        NOT NULL,

    state         TEXT        NOT NULL DEFAULT 'queued'
                  CHECK (state IN ('queued', 'running', 'done', 'failed')),
    priority      INTEGER     NOT NULL DEFAULT 0,   -- makin besar makin dulu

    -- hasil (diisi worker setelah selesai)
    status        TEXT        CHECK (status IN ('found','not_found','queue_without_data','no_response')),
    msg           TEXT,
    fields        JSONB,
    from_cache    BOOLEAN     NOT NULL DEFAULT false,
    error         TEXT,

    requested_by  TEXT,                              -- identitas pemanggil dari Artemis
    attempts      INTEGER     NOT NULL DEFAULT 0,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at    TIMESTAMPTZ,
    finished_at   TIMESTAMPTZ
);

-- Worker mengambil job dengan ORDER BY priority DESC, id ASC.
CREATE INDEX IF NOT EXISTS idx_jobs_antrian
    ON search_jobs (state, priority DESC, id)
    WHERE state = 'queued';

CREATE INDEX IF NOT EXISTS idx_jobs_created ON search_jobs (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_lookup  ON search_jobs (bot, cmd, value);
