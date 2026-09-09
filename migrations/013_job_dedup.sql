-- Cegah job kembar di antrian.
--
-- jobs.enqueue() dulu INSERT polos, jadi dua permintaan identik yang datang
-- bersamaan menghasilkan dua job dan bot ditembak DUA KALI untuk nilai yang
-- sama. Itu memboroskan kuota harian per fitur — pembatas paling ketat di
-- sistem ini, bukan kecepatan antrian.
--
-- Index parsial hanya berlaku selama job masih mengantre; setelah diproses,
-- permintaan yang sama boleh masuk lagi (mis. untuk data volatile).
-- `force` ikut jadi kunci karena job paksa tidak boleh digabung dengan job
-- biasa yang mungkin dijawab dari cache.
CREATE UNIQUE INDEX IF NOT EXISTS uq_jobs_antre
    ON search_jobs (bot, cmd, value, force)
 WHERE state = 'queued';
