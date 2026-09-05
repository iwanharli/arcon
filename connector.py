"""Connector Telegram berbasis Telethon untuk baca/tulis ke beberapa bot.

Login sebagai akun user (bukan bot token), karena bot tidak bisa mengirim
pesan ke bot lain. Session disimpan di file <TG_SESSION>.session sehingga
login OTP hanya diperlukan sekali.
"""
import asyncio
import logging
from typing import Awaitable, Callable, Iterable

from telethon import TelegramClient, events
from telethon.tl.custom.message import Message

import config

log = logging.getLogger("artemis.telegram")


class TelegramConnector:
    def __init__(self, session: str = config.SESSION):
        self.client = TelegramClient(session, config.API_ID, config.API_HASH)

    # ---------- lifecycle ----------

    async def __aenter__(self) -> "TelegramConnector":
        await self.start()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.stop()

    async def start(self) -> None:
        await self.client.start(phone=config.PHONE)
        me = await self.client.get_me()
        log.info("login sebagai %s (id=%s)", me.username or me.first_name, me.id)

    async def stop(self) -> None:
        await self.client.disconnect()

    # ---------- write ----------

    async def send(self, bot: str, text: str, **kwargs) -> Message:
        """Kirim pesan ke satu bot, tanpa menunggu balasan."""
        target = config.resolve(bot)
        msg = await self.client.send_message(target, text, **kwargs)
        log.info("-> %s: %s", target, text)
        return msg

    async def send_all(self, text: str, bots: Iterable[str] | None = None) -> dict[str, Message]:
        """Broadcast teks yang sama ke semua bot terkonfigurasi."""
        names = list(bots or config.BOTS)
        results = await asyncio.gather(*(self.send(n, text) for n in names))
        return dict(zip(names, results))

    # ---------- read ----------

    async def ask(self, bot: str, text: str, timeout: float | None = None,
                  collect: int = 1, wait_final: bool = False,
                  ack_markers: Iterable[str] = (),
                  accept: "Callable[[Message], bool] | None" = None,
                  linger: float = 0) -> list[Message]:
        """Kirim pesan lalu tunggu balasan bot.

        Dua mode:
        - default: berhenti setelah `collect` pesan terkumpul.
        - wait_final=True: berhenti begitu ada pesan yang BUKAN ack antrian
          (mis. "Processing...", "Giliran Anda"). Bot data sering mengirim ack
          dulu lalu jawaban asli menyusul lama; mode ini menunggu jawaban asli
          itu, bukan menyerah pada ack. `ack_markers` = frasa penanda ack
          (lowercase).

        Balasan yang datang setelah timeout diabaikan; yang sudah terkumpul
        tetap dikembalikan.
        """
        target = config.resolve(bot)
        entity = await self.client.get_entity(target)
        timeout = config.BOT_TIMEOUT if timeout is None else timeout
        markers = tuple(ack_markers)

        replies: list[Message] = []
        done = asyncio.Event()

        def _is_ack(msg: Message) -> bool:
            t = (msg.text or "").lower()
            return any(m in t for m in markers)

        async def _handler(event: events.NewMessage.Event) -> None:
            msg = event.message
            replies.append(msg)
            if wait_final:
                # Selesai hanya pada pesan non-ack yang MEMANG milik permintaan
                # ini. cleojktbot dkk sering mengirim jawaban tidak berurutan;
                # jawaban milik permintaan lain (accept=False) dilewati supaya
                # kita terus menunggu jawaban yang benar sampai timeout.
                if not _is_ack(msg) and (accept is None or accept(msg)):
                    done.set()
            elif len(replies) >= collect:
                done.set()

        self.client.add_event_handler(_handler, events.NewMessage(from_users=entity.id))
        try:
            await self.client.send_message(entity, text)
            log.info("-> %s: %s", target, text)
            try:
                await asyncio.wait_for(done.wait(), timeout)
            except asyncio.TimeoutError:
                log.warning("timeout %.0fs menunggu balasan %s (dapat %d)",
                            timeout, target, len(replies))
            # Foto (mis. E-KTP) sering menyusul sebagai pesan terpisah setelah
            # teks jawaban. Tunggu sebentar untuk menangkapnya.
            if linger > 0 and done.is_set():
                await asyncio.sleep(linger)
        finally:
            self.client.remove_event_handler(_handler)

        for m in replies:
            log.info("<- %s: %s", target, (m.text or "").replace("\n", " ")[:200])
        return replies

    async def download_media(self, msg: Message) -> tuple[bytes, str] | None:
        """Unduh media (foto) dari sebuah pesan. Kembalikan (bytes, content_type)
        atau None kalau pesan tak bermedia / bukan foto."""
        if msg is None or msg.media is None:
            return None
        # hanya foto & dokumen gambar; abaikan preview webpage
        from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument
        if not isinstance(msg.media, (MessageMediaPhoto, MessageMediaDocument)):
            return None
        try:
            data = await self.client.download_media(msg, file=bytes)
        except Exception as exc:  # noqa: BLE001
            log.warning("gagal unduh media: %s", exc)
            return None
        if not data:
            return None
        ctype = "image/jpeg"
        if isinstance(msg.media, MessageMediaDocument) and msg.media.document:
            mt = getattr(msg.media.document, "mime_type", "") or ""
            if mt:
                ctype = mt
        return data, ctype

    async def ask_all(self, text: str, bots: Iterable[str] | None = None,
                      **kwargs) -> dict[str, list[Message]]:
        """Tanya semua bot secara paralel, kembalikan balasan per bot."""
        names = list(bots or config.BOTS)
        out = await asyncio.gather(*(self.ask(n, text, **kwargs) for n in names))
        return dict(zip(names, out))

    async def history(self, bot: str, limit: int = 20) -> list[Message]:
        """Baca riwayat chat dengan bot (terbaru dulu)."""
        target = config.resolve(bot)
        return await self.client.get_messages(target, limit=limit)

    # ---------- listen ----------

    def on_bot_message(
        self,
        callback: Callable[[str, Message], Awaitable[None]],
        bots: Iterable[str] | None = None,
    ) -> None:
        """Daftarkan callback untuk setiap pesan masuk dari bot-bot tersebut.

        callback(nama_logis, message).
        """
        names = list(bots or config.BOTS)
        usernames = [config.resolve(n) for n in names]
        by_username = dict(zip(usernames, names))

        @self.client.on(events.NewMessage(from_users=usernames))
        async def _dispatch(event: events.NewMessage.Event) -> None:
            sender = await event.get_sender()
            name = by_username.get(sender.username, sender.username or str(sender.id))
            await callback(name, event.message)

    async def run_forever(self) -> None:
        await self.client.run_until_disconnected()
