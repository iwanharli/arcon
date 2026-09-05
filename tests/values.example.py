"""Nilai input untuk test fitur bot — ISI SENDIRI sesuai data yang mau dipakai.

Isi variabel identitas dasar di bagian atas sekali saja — otomatis dipakai
ulang untuk command bot1 & bot3 yang butuh input sama (nik, kk, nama, hp,
nama guru). Command yang formatnya beda antar bot (mis. /bpjs) sengaja
dipisah, jangan disamakan.

Kosongkan (None) command yang tidak mau ditest; test-nya otomatis di-skip.
Jangan commit file ini kalau sudah diisi data pribadi/sensitif — sudah masuk
.gitignore (yang di-commit cuma tests/values.example.py).
"""

# ==================== Identitas dasar (isi sekali, dipakai ulang) ====================
NIK = None          # NIK 16 digit, dipakai di banyak command bot1 & bot3
KK = None           # No. KK 16 digit
NAMA = None         # Nama lengkap
NAMA_URUTAN = 1     # bot3 butuh format "Nama#N" / "NIK#N" untuk beberapa command
HP = None           # Nomor HP format 628xxxxxxxxxx
GURU_NAMA = None    # Nama guru, dipakai bot1 /guru & bot3 /guru /guru1

# Data yang formatnya khas satu bot saja (tidak overlap) — isi terpisah kalau perlu.
NOPOL = None            # Nomor polisi kendaraan, mis. B1234XYZ
NOMOR_MESIN = None
NOMOR_RANGKA = None
WSID = None
IDPEL_PLN = None
DOSEN_NAMA = None
MAHASISWA_NAMA = None


CPTSEL_TELKOMSEL = None     # bot3 /cptsel, /track, /lm: nomor Telkomsel
EMAIL = None                # bot3 /emailstalker
LEAK_QUERY = None           # bot3 /leak: email/nomor/nama/nik
NAMA_PERUSAHAAN = None      # bot3 /pt
NIB = None
NPWP = None


def _u(v):
    """Tempel '#urutan' — dipakai command bot3 yang butuh pilih hasil ke-N."""
    return f"{v}#{NAMA_URUTAN}" if v else None


# ==================== bot1 (cielodespejadobot) ====================
BOT1 = {
    "/nik": NIK,
    "/kk": KK,
    "/nama": NAMA,
    "/bionik": NIK,
    "/biokk": KK,
    "/bionama": NAMA,
    "/foto": NIK,
    "/reg": HP,
    "/nohp": NIK,
    "/profnumber": HP,
    "/tnkb": NOPOL,
    "/nosin": NOMOR_MESIN,
    "/noka": NOMOR_RANGKA,
    "/niknopol": NIK,
    "/namanopol": NAMA,
    "/bpjs": NIK,
    "/wsid": WSID,
    "/dpo": NAMA,
    "/pln": IDPEL_PLN,
    "/guru": GURU_NAMA,
    "/dosen": DOSEN_NAMA,
    "/mahasiswa": MAHASISWA_NAMA,
}

# ==================== bot2 (mahalini2bot) ====================
BOT2 = {
    "/cp": HP,
}

# ==================== bot3 (cleojktbot) ====================
BOT3 = {
    # Lokasi
    "/cptsel": CPTSEL_TELKOMSEL,
    "/track": CPTSEL_TELKOMSEL,
    "/lm": CPTSEL_TELKOMSEL,
    # Profiling
    "/prof": HP,
    "/cekinfo": HP,
    "/reg": HP,
    "/kk": KK,
    "/nik": NIK,
    "/nohp": _u(NIK),
    "/nama": _u(NAMA),
    "/photo": NIK,
    "/bpjs": NIK,   # bot3 minta 16 digit = NIK, bukan nomor BPJS (13 digit)
    "/bpjs2": NIK,
    "/guru": GURU_NAMA,
    "/guru1": GURU_NAMA,
    "/siswa": NIK,
    "/cekkpu": NIK,
    "/cekanggota": _u(NAMA),
    "/leak": LEAK_QUERY,
    "/emailstalker": EMAIL,
    "/pt": NAMA_PERUSAHAAN,
    "/nib": NIB,
    "/npwp": NPWP,
    "/nopol": NOPOL,
}
