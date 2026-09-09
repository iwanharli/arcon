"""Connector Telegram berbasis Telethon untuk baca/tulis ke beberapa bot.

Login sebagai akun user (bukan bot token), karena bot tidak bisa mengirim
pesan ke bot lain. Session disimpan di file <TG_SESSION>.session sehingga
login OTP hanya diperlukan sekali.
"""
import asyncio
import logging
import re
from typing import Awaitable, Callable, Iterable

from telethon import TelegramClient, events
from telethon.tl.custom.message import Message

import config

log = logging.getLogger("artemis.telegram")


class BatasHarian(RuntimeError):
    """Kuota harian fitur di bot habis — kondisi sementara, bukan kegagalan."""


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
                # ini. Bot data sering mengirim jawaban tidak berurutan;
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

    # Bot menu-driven (mis. teamkhususantibanditbot) tidak menerima
    # "/cmd nilai" sekali kirim. Alurnya: kirim label menu -> bot membalas
    # penjelasan + "Silakan masukkan ..." -> baru nilai dikirim. Penanda di
    # bawah dipakai untuk mengenali pesan ajakan input itu.
    PROMPT_MARKERS = ("silakan masukkan", "silahkan masukkan", "masukkan ",
                      "kirimkan ", "ketik ")

    # Bot bisa TERSANGKUT di alur lain: state percakapan sebelumnya belum
    # selesai, dan tombol Batal tidak selalu membersihkannya (terbukti pada
    # cancel_celldum_data — 29 tombol Batal, /start, dan tombol Batal pada
    # prompt asli semuanya gagal). Kalau itu terjadi, label menu kita ditelan
    # sebagai nilai dan bot membalas keluhan format. Nilai TIDAK BOLEH dikirim
    # dalam keadaan ini: ia akan masuk ke pencarian yang salah.
    STUCK_MARKERS = ("tidak valid", "format yang benar", "coba lagi dengan format")

    async def cancel_pending(self, bot: str, scan: int = 8) -> bool:
        """Tekan tombol "❌ Batal" kalau bot masih menunggu input.

        Dicari hanya di beberapa pesan terakhir: tombol Batal dari prompt lama
        yang sudah selesai tidak boleh ikut ditekan. Kembalikan True kalau ada
        yang ditekan.
        """
        try:
            msgs = await self.history(bot, limit=scan)
        except Exception as exc:                       # noqa: BLE001
            log.warning("gagal membaca riwayat untuk batal: %s", exc)
            return False

        for m in msgs:                                 # terbaru dulu
            mk = m.reply_markup
            if not mk or not getattr(mk, "rows", None):
                continue
            for row_i, row in enumerate(mk.rows):
                for col_i, b in enumerate(row.buttons):
                    if "batal" in (b.text or "").lower() or "cancel" in (b.text or "").lower():
                        try:
                            await m.click(row_i, col_i)
                            log.info("state %s dibatalkan lewat tombol %r", bot, b.text)
                            return True
                        except Exception as exc:       # noqa: BLE001
                            log.warning("gagal menekan Batal di %s: %s", bot, exc)
                            return False
        return False

    @staticmethod
    def _pastikan_kuota(bot: str, menu: str, msgs) -> None:
        """Batas harian per fitur -> error yang jelas, bukan 'tombol tidak ada'.

        Kalau kuota fitur habis, bot menolak MEMBUKA menunya: tidak ada tombol
        submenu sama sekali, sehingga pencarian tombol gagal dan errornya
        menyesatkan. Terbukti pada VERIFIKASI PERIZINAN dan TRACKING NUMBER.
        """
        import parser as _p
        for m in msgs:
            if _p.is_limited(m.text):
                raise BatasHarian((m.text or "").strip())

    @classmethod
    def _pastikan_tidak_tersangkut(cls, bot: str, menu: str, msgs) -> None:
        """Batalkan alur kalau bot ternyata masih menunggu input alur LAIN.

        Gejalanya: label menu kita dijawab keluhan format ("Format koordinat
        tidak valid"). Kalau diteruskan, nilai pengguna dikirim ke pencarian
        yang salah — lebih baik gagal keras daripada menyimpan hasil nyasar.
        """
        for m in msgs:
            t = (m.text or "").lower()
            if any(x in t for x in cls.STUCK_MARKERS) and "❌" in (m.text or ""):
                raise RuntimeError(
                    f"{bot} tersangkut di alur lain saat membuka {menu!r}: "
                    f"{(m.text or '')[:120]!r}. Selesaikan/batalkan alur itu "
                    f"dulu lewat aplikasi Telegram."
                )

    async def ask_menu(self, bot: str, menu: str, value: str, *,
                       reset_cmd: str | None = "/start",
                       prompt_timeout: float = 60,
                       timeout: float | None = None,
                       ack_markers: Iterable[str] = (),
                       accept: "Callable[[Message], bool] | None" = None,
                       linger: float = 0) -> list[Message]:
        """Alur dua langkah untuk bot berbasis menu ReplyKeyboard.

        1. kirim `menu` (mis. "BUKA NIK"), tunggu pesan ajakan input;
        2. kirim `value`, tunggu jawaban asli (non-ack) seperti ask().

        Kalau langkah 1 tidak menghasilkan ajakan input dalam `prompt_timeout`,
        nilai tetap dikirim: sebagian menu langsung meminta input tanpa kalimat
        pemicu yang kita kenali. Yang tidak boleh adalah mengirim nilai sebelum
        bot siap — nilainya akan ditelan sebagai perintah menu yang tidak dikenal.
        """
        markers = tuple(ack_markers)

        # Bot menyimpan state percakapan: kalau query sebelumnya berhenti di
        # tengah (timeout saat menunggu hasil), bot masih menunggu INPUT, dan
        # label menu berikutnya ditelan sebagai nilai — terbukti waktu
        # "/remaining" dijawab "Invalid NIK format".
        #
        # /start TIDAK cukup: bot tetap membalas "Format nomor telepon tidak
        # valid" untuk pesan berikutnya, bahkan menganggap "/start" itu sendiri
        # sebagai nilai. Yang benar-benar membatalkan adalah tombol inline
        # "❌ Batal" (callback cancel_*) di pesan ajakan input.
        if await self.cancel_pending(bot):
            await asyncio.sleep(2)
        elif reset_cmd:
            await self.ask(bot, reset_cmd, timeout=20, collect=1)
            await asyncio.sleep(1)

        def _is_prompt(msg: Message) -> bool:
            t = (msg.text or "").lower()
            if any(m in t for m in markers):
                return False                     # masih ack antrian, bukan ajakan
            return any(p in t for p in self.PROMPT_MARKERS)

        prompts = await self.ask(bot, menu, timeout=prompt_timeout,
                                 wait_final=True, ack_markers=markers,
                                 accept=_is_prompt)
        self._pastikan_kuota(bot, menu, prompts)
        self._pastikan_tidak_tersangkut(bot, menu, prompts)
        if not any(_is_prompt(m) for m in prompts):
            log.warning("menu %r di %s tidak memberi ajakan input; nilai tetap dikirim",
                        menu, bot)

        return await self.ask(bot, value, timeout=timeout, wait_final=True,
                              ack_markers=markers, accept=accept, linger=linger)

    async def _tunggu(self, entity, cocok, timeout: float,
                      ikut_edit: bool = True, aksi=None) -> list[Message]:
        """Tunggu pesan (baru ATAU hasil edit) dari `entity` yang lolos `cocok`.

        Menekan tombol inline sering dijawab bot dengan MENGEDIT pesan yang
        sama, bukan mengirim pesan baru — jadi events.NewMessage saja tidak
        cukup untuk menunggu langkah setelah klik.
        """
        kena: list[Message] = []
        selesai = asyncio.Event()

        async def _h(event) -> None:
            msg = event.message
            kena.append(msg)
            if cocok(msg):
                selesai.set()

        handlers = [(_h, events.NewMessage(from_users=entity.id))]
        if ikut_edit:
            handlers.append((_h, events.MessageEdited(from_users=entity.id)))
        # Handler HARUS terpasang sebelum aksi dijalankan: balasan bot atas
        # klik tombol bisa datang dalam hitungan milidetik, dan kalau aksinya
        # dijalankan lebih dulu, event itu lewat begitu saja.
        for h, ev in handlers:
            self.client.add_event_handler(h, ev)
        try:
            if aksi is not None:
                await aksi()
            await asyncio.wait_for(selesai.wait(), timeout)
        except asyncio.TimeoutError:
            log.warning("timeout %.0fs menunggu langkah berikutnya", timeout)
        finally:
            for h, ev in handlers:
                self.client.remove_event_handler(h, ev)
        return kena

    @staticmethod
    def _cari_tombol(msgs, target: str):
        """Cari tombol inline yang cocok dengan `target` (callback data atau
        teks tombol). Kembalikan (message, baris, kolom) atau None."""
        t = target.lower()
        for m in msgs:
            mk = m.reply_markup
            if not mk or not getattr(mk, "rows", None):
                continue
            for i, row in enumerate(mk.rows):
                for j, b in enumerate(row.buttons):
                    data = (getattr(b, "data", None) or b"").decode("utf8", "replace")
                    if data.lower() == t or t in data.lower() or t in (b.text or "").lower():
                        return m, i, j
        return None

    async def ask_submenu(self, bot: str, menu: str, choice, value: str, *,
                          timeout: float | None = None,
                          step_timeout: float = 60,
                          ack_markers: Iterable[str] = (),
                          accept: "Callable[[Message], bool] | None" = None,
                          linger: float = 0) -> list[Message]:
        """Alur TIGA langkah: label menu -> tombol submenu -> nilai.

        Sebagian menu (DATA TELEGRAM, DOMPET DIGITAL, GURU AGAMA, ...) tidak
        langsung meminta input; mereka menampilkan tombol inline "pilih metode
        pencarian" dulu. `choice` = callback data tombolnya (mis.
        "telegram_profiling_by_username") atau potongan teks tombolnya.

        `choice` boleh berupa RANTAI (tuple/list) untuk submenu berlapis, mis.
        ("track_by_resi", "courier_jne") pada TRACKING NUMBER > Lacak by Resi >
        pilih kurir. Tiap elemen diklik berurutan; tombol berikutnya dicari di
        pesan hasil klik sebelumnya.
        """
        markers = tuple(ack_markers)
        rantai = [choice] if isinstance(choice, str) else list(choice)
        target = config.resolve(bot)
        entity = await self.client.get_entity(target)

        def _is_prompt(m: Message) -> bool:
            t = (m.text or "").lower()
            if any(x in t for x in markers):
                return False
            return any(p in t for p in self.PROMPT_MARKERS)

        if await self.cancel_pending(bot):
            await asyncio.sleep(2)

        # Langkah 1: buka menu, tunggu pesan yang memuat tombol pertama.
        pertama = rantai[0]
        pesan = await self.ask(
            bot, menu, timeout=step_timeout, wait_final=True, ack_markers=markers,
            accept=lambda m: self._cari_tombol([m], pertama) is not None,
        )

        # Langkah 2..n: klik tiap tombol di rantai. Tombol berikutnya dicari di
        # pesan hasil klik sebelumnya, karena submenu berlapis mengganti isinya.
        self._pastikan_kuota(bot, menu, pesan)
        for ke, ch in enumerate(rantai, 1):
            found = self._cari_tombol(pesan, ch)
            if not found:
                raise RuntimeError(
                    f"tombol {ch!r} (rantai ke-{ke}) tidak ditemukan di {menu!r} pada {bot}")
            msg, baris, kolom = found
            terakhir = ke == len(rantai)

            def _berhenti(m: Message, _t=terakhir, _ch=ch) -> bool:
                if _t:
                    return _is_prompt(m)
                # bukan langkah terakhir: cukup tunggu pesan yang memuat
                # tombol rantai berikutnya.
                return self._cari_tombol([m], rantai[ke]) is not None

            async def _klik(_m=msg, _b=baris, _k=kolom, _ch=ch):
                await _m.click(_b, _k)
                log.info("-> %s: klik %r di %r", target, _ch, menu)

            pesan = await self._tunggu(entity, _berhenti, step_timeout, aksi=_klik)

        self._pastikan_tidak_tersangkut(bot, menu, pesan)
        if not any(_is_prompt(m) for m in pesan):
            log.warning("rantai %r di %r tidak berakhir pada ajakan input; "
                        "nilai tetap dikirim", rantai, menu)

        # Langkah terakhir: kirim nilainya, tunggu jawaban asli.
        return await self.ask(bot, value, timeout=timeout, wait_final=True,
                              ack_markers=markers, accept=accept, linger=linger)

    # Tombol "halaman berikutnya" pada daftar hasil. Tiap fitur memberi nama
    # callback-nya sendiri (bpom_page:2, notaris_page:2, ...), jadi dicocokkan
    # lewat pola umum, bukan daftar tetap.
    NEXT_RE = re.compile(r"(page|halaman)\s*[:_-]?\s*\d+", re.IGNORECASE)
    NEXT_TEKS = ("next", "selanjutnya", "berikutnya", "➡", "▶")

    @classmethod
    def _tombol_next(cls, msgs):
        """Cari tombol 'halaman berikutnya'. Kembalikan (message, baris, kolom)."""
        for m in msgs:
            mk = m.reply_markup
            if not mk or not getattr(mk, "rows", None):
                continue
            for i, row in enumerate(mk.rows):
                for j, b in enumerate(row.buttons):
                    data = (getattr(b, "data", None) or b"").decode("utf8", "replace")
                    teks = (b.text or "").lower()
                    if "noop" in data.lower():
                        continue                      # indikator "1/283", bukan tombol
                    if any(t in teks for t in cls.NEXT_TEKS) or cls.NEXT_RE.search(data):
                        return m, i, j
        return None

    async def telusuri_halaman(self, bot: str, pesan, maks: int = 1, *,
                               step_timeout: float = 60,
                               ack_markers: Iterable[str] = ()) -> list[Message]:
        """Ikuti tombol Next dan kumpulkan halaman berikutnya.

        Bot mengirim daftar hasil terpotong ("Menampilkan 1-5" dari 1.412
        hasil, tombol "📄 1/283"). Tanpa ini hanya halaman pertama yang
        tersimpan.

        `maks` = jumlah halaman TAMBAHAN yang diambil. Bot MENGEDIT pesan yang
        sama saat halaman berganti, jadi yang ditunggu adalah MessageEdited
        dengan teks yang berbeda dari halaman sebelumnya.
        """
        if maks < 1:
            return []
        markers = tuple(ack_markers)
        entity = await self.client.get_entity(config.resolve(bot))
        terkumpul: list[Message] = []
        terakhir = pesan
        sebelumnya = {(m.text or "") for m in pesan}

        for ke in range(1, maks + 1):
            found = self._tombol_next(terakhir)
            if not found:
                break                                  # sudah halaman terakhir
            msg, baris, kolom = found

            def _baru(m: Message) -> bool:
                t = m.text or ""
                if any(x in t.lower() for x in markers):
                    return False
                return bool(t.strip()) and t not in sebelumnya

            async def _klik(_m=msg, _b=baris, _k=kolom):
                await _m.click(_b, _k)

            hasil = await self._tunggu(entity, _baru, step_timeout, aksi=_klik)
            halaman = [m for m in hasil if _baru(m)]
            if not halaman:
                log.warning("halaman %d di %s tidak kunjung datang", ke + 1, bot)
                break
            log.info("halaman %d %s terkumpul", ke + 1, bot)
            terkumpul += halaman
            sebelumnya |= {(m.text or "") for m in halaman}
            terakhir = halaman
        return terkumpul

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
