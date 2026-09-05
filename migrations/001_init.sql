-- Skema awal db_artemis.
--
-- Dua lapis:
--   1. bot_query_cache  -> mentah, satu baris per (bot, cmd, value). Sumber
--      kebenaran & jejak audit; dipakai untuk menjawab tanpa hit Telegram.
--   2. profiles + turunannya -> hasil normalisasi & merge, bisa di-rebuild
--      ulang dari lapis 1 kalau logika parsing berubah.

-- ============================================================ lapis 1: cache

CREATE TABLE IF NOT EXISTS bot_query_cache (
    id          BIGSERIAL PRIMARY KEY,
    bot         TEXT        NOT NULL,
    cmd         TEXT        NOT NULL,
    value       TEXT        NOT NULL,
    status      TEXT        NOT NULL
                CHECK (status IN ('found', 'not_found', 'queue_without_data', 'no_response')),
    msg         TEXT,
    fields      JSONB,
    tested_at   TIMESTAMPTZ NOT NULL,
    hit_count   INTEGER     NOT NULL DEFAULT 1,   -- berapa kali di-hit ulang ke bot
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (bot, cmd, value)
);

CREATE INDEX IF NOT EXISTS idx_cache_status  ON bot_query_cache (status);
CREATE INDEX IF NOT EXISTS idx_cache_fields  ON bot_query_cache USING GIN (fields);
CREATE INDEX IF NOT EXISTS idx_cache_lookup  ON bot_query_cache (cmd, value);

-- ========================================================= lapis 2: profiles

CREATE TABLE IF NOT EXISTS profiles (
    id              BIGSERIAL PRIMARY KEY,
    nik             CHAR(16) UNIQUE,       -- nullable: hasil cari-by-nama kadang tanpa NIK
    kk              CHAR(16),
    shdk            TEXT,
    nama            TEXT NOT NULL,
    tempat_lahir    TEXT,
    tanggal_lahir   DATE,
    jenis_kelamin   TEXT,
    status_kawin    TEXT,
    pekerjaan       TEXT,
    agama           TEXT,
    pendidikan      TEXT,
    alamat          TEXT,
    rt              TEXT,
    rw              TEXT,
    kel_desa        TEXT,
    kecamatan       TEXT,
    kab_kota        TEXT,
    provinsi        TEXT,
    nik_ayah        CHAR(16),
    nama_ayah       TEXT,
    nik_ibu         CHAR(16),
    nama_ibu        TEXT,
    first_seen_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_profiles_kk   ON profiles (kk);
CREATE INDEX IF NOT EXISTS idx_profiles_nama ON profiles (lower(nama));

-- Satu nomor HP bisa terdaftar atas banyak NIK (terbukti di uji /reg: 10 NIK).
CREATE TABLE IF NOT EXISTS profile_phones (
    id              BIGSERIAL PRIMARY KEY,
    profile_id      BIGINT REFERENCES profiles(id) ON DELETE CASCADE,
    nik             CHAR(16),              -- disimpan walau profile-nya belum ada
    msisdn          TEXT NOT NULL,
    operator        TEXT,
    pemilik         TEXT,
    registered_at   DATE,
    source_query_id BIGINT REFERENCES bot_query_cache(id) ON DELETE SET NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (msisdn, nik, registered_at)
);

CREATE INDEX IF NOT EXISTS idx_phones_msisdn  ON profile_phones (msisdn);
CREATE INDEX IF NOT EXISTS idx_phones_profile ON profile_phones (profile_id);

CREATE TABLE IF NOT EXISTS profile_vehicles (
    id              BIGSERIAL PRIMARY KEY,
    profile_id      BIGINT REFERENCES profiles(id) ON DELETE CASCADE,
    nopol           TEXT,
    nomor_mesin     TEXT,
    nomor_rangka    TEXT,
    merk            TEXT,
    tipe            TEXT,
    tahun           TEXT,
    warna           TEXT,
    pemilik         TEXT,
    alamat          TEXT,
    detail          JSONB,
    source_query_id BIGINT REFERENCES bot_query_cache(id) ON DELETE SET NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (nopol, nomor_rangka, nomor_mesin)
);

-- Long tail: bpjs, kpu, dpo, guru, siswa, leak, email, pt, pln, device, dst.
-- Sengaja jsonb supaya tidak perlu 15 tabel untuk data yang jarang dipakai.
CREATE TABLE IF NOT EXISTS profile_records (
    id              BIGSERIAL PRIMARY KEY,
    profile_id      BIGINT REFERENCES profiles(id) ON DELETE CASCADE,
    subject         TEXT,                  -- NIK / msisdn / id pelanggan saat profile_id belum diketahui
    kind            TEXT NOT NULL,         -- 'pln' | 'device' | 'number_info' | 'bpjs' | ...
    data            JSONB NOT NULL,
    source_query_id BIGINT REFERENCES bot_query_cache(id) ON DELETE SET NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (kind, subject, data)
);

CREATE INDEX IF NOT EXISTS idx_records_kind    ON profile_records (kind);
CREATE INDEX IF NOT EXISTS idx_records_profile ON profile_records (profile_id);
CREATE INDEX IF NOT EXISTS idx_records_data    ON profile_records USING GIN (data);

-- updated_at otomatis
CREATE OR REPLACE FUNCTION touch_updated_at() RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_cache_touch ON bot_query_cache;
CREATE TRIGGER trg_cache_touch BEFORE UPDATE ON bot_query_cache
    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

DROP TRIGGER IF EXISTS trg_profiles_touch ON profiles;
CREATE TRIGGER trg_profiles_touch BEFORE UPDATE ON profiles
    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();
