"""Konfigurasi terpusat, dibaca dari .env."""
import os

from dotenv import load_dotenv

load_dotenv()


def _req(name: str) -> str:
    val = os.getenv(name)
    if not val:
        raise RuntimeError(f"{name} belum diisi di .env")
    return val


API_ID = int(_req("TG_API_ID"))
API_HASH = _req("TG_API_HASH")
PHONE = os.getenv("TG_PHONE")
SESSION = os.getenv("TG_SESSION", "artemis")

BOT_TIMEOUT = float(os.getenv("BOT_TIMEOUT", "30"))

# Nama logis -> username/id bot. Nama logis dipakai di seluruh kode.
BOTS = {
    "bot1": os.getenv("BOT_1", ""),
    "bot2": os.getenv("BOT_2", ""),
    "bot3": os.getenv("BOT_3", ""),
}
BOTS = {k: v for k, v in BOTS.items() if v}


def resolve(name: str) -> str:
    """Terima nama logis ('bot1') atau username langsung ('foo_bot')."""
    return BOTS.get(name, name)
