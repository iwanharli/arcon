-- Pengecekan kesehatan command secara berkala (sehari sekali).
--
-- Tujuannya menjawab: "command mana yang mati / providernya bermasalah?"
--
-- Supaya hasilnya berarti, tiap command butuh probe berupa nilai yang SUDAH
-- TERBUKTI ada datanya. Tanpa itu, balasan 'not_found' ambigu: entah command
-- rusak, entah datanya memang tidak ada (contoh nyata: /dosen "Siti Aminah"
-- selalu not_found karena nama itu karangan, padahal commandnya sehat).

CREATE TABLE IF NOT EXISTS command_probes (
    bot           TEXT NOT NULL,
    cmd           TEXT NOT NULL,
    probe_value   TEXT NOT NULL,
    -- status yang dianggap "sehat" untuk probe ini. Umumnya 'found', tapi
    -- untuk nomor yang memang mati, 'not_found' pun bukti command jalan.
    expect_status TEXT NOT NULL DEFAULT 'found'
                  CHECK (expect_status IN ('found', 'not_found')),
    enabled       BOOLEAN NOT NULL DEFAULT true,
    note          TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (bot, cmd)
);

-- Riwayat tiap pengecekan (untuk melihat sejak kapan sebuah command mati).
CREATE TABLE IF NOT EXISTS command_health_checks (
    id           BIGSERIAL PRIMARY KEY,
    bot          TEXT        NOT NULL,
    cmd          TEXT        NOT NULL,
    checked_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    status       TEXT,                    -- found / not_found / queue_without_data / no_response
    ok           BOOLEAN     NOT NULL,    -- status == expect_status
    duration_ms  INTEGER,
    msg          TEXT,
    probe_value  TEXT,
    job_id       UUID
);

CREATE INDEX IF NOT EXISTS idx_health_checks_cmd
    ON command_health_checks (bot, cmd, checked_at DESC);
CREATE INDEX IF NOT EXISTS idx_health_checks_waktu
    ON command_health_checks (checked_at DESC);

-- Ringkasan terkini per command, diperbarui tiap kali pengecekan jalan.
CREATE TABLE IF NOT EXISTS command_health (
    bot                  TEXT NOT NULL,
    cmd                  TEXT NOT NULL,
    last_checked_at      TIMESTAMPTZ,
    last_status          TEXT,
    ok                   BOOLEAN,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    last_ok_at           TIMESTAMPTZ,     -- terakhir kali command ini sehat
    last_msg             TEXT,
    PRIMARY KEY (bot, cmd)
);

-- Command yang perlu diperhatikan: gagal beruntun >= 2 kali.
CREATE OR REPLACE VIEW command_bermasalah AS
    SELECT bot, cmd, last_status, consecutive_failures, last_ok_at, last_msg,
           CASE WHEN last_ok_at IS NULL THEN NULL
                ELSE now() - last_ok_at END AS sejak_terakhir_sehat
      FROM command_health
     WHERE consecutive_failures >= 2
     ORDER BY consecutive_failures DESC, bot, cmd;
