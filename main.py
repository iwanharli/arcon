"""CLI contoh pemakaian TelegramConnector.

  python main.py login                      # login sekali, buat file session
  python main.py send bot1 "halo"           # kirim, tidak menunggu balasan
  python main.py ask bot1 "/start"          # kirim + tunggu balasan
  python main.py ask-all "/status"          # tanya ketiga bot sekaligus
  python main.py history bot2 10            # baca 10 pesan terakhir
  python main.py listen                     # dengarkan pesan masuk realtime

  python main.py query bot1 /nik 327505...  # lewat cache db_artemis (hemat kuota)
  python main.py query bot1 /nik 327505... --force   # paksa hit Telegram
"""
import asyncio
import json
import logging
import sys

import config
from connector import TelegramConnector

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


async def main() -> int:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 1
    cmd, rest = args[0], args[1:]

    async with TelegramConnector() as tg:
        if cmd == "login":
            print("session siap:", config.SESSION + ".session")

        elif cmd == "send":
            await tg.send(rest[0], " ".join(rest[1:]))

        elif cmd == "ask":
            replies = await tg.ask(rest[0], " ".join(rest[1:]))
            for m in replies:
                print(m.text)

        elif cmd == "ask-all":
            result = await tg.ask_all(" ".join(rest))
            for bot, msgs in result.items():
                print(f"--- {bot} ({config.resolve(bot)}) ---")
                for m in msgs:
                    print(m.text)

        elif cmd == "query":
            import db
            import service

            force = "--force" in rest
            rest = [a for a in rest if a != "--force"]
            bot, bot_cmd, value = rest[0], rest[1], " ".join(rest[2:])

            conn = await db.connect()
            try:
                hasil = await service.query(tg, conn, bot, bot_cmd, value, force=force)
            finally:
                await conn.close()

            asal = "cache" if hasil["from_cache"] else "telegram"
            print(f"[{asal}] status={hasil['status']}")
            if hasil["msg"]:
                print(hasil["msg"])
            if hasil["fields"]:
                print(json.dumps(hasil["fields"], ensure_ascii=False, indent=2, default=str))

        elif cmd == "history":
            limit = int(rest[1]) if len(rest) > 1 else 20
            for m in reversed(await tg.history(rest[0], limit)):
                who = "me" if m.out else "bot"
                print(f"[{m.date:%Y-%m-%d %H:%M}] {who}: {m.text}")

        elif cmd == "listen":
            async def on_msg(bot: str, msg) -> None:
                print(f"[{bot}] {msg.text}")

            tg.on_bot_message(on_msg)
            print("mendengarkan:", ", ".join(config.BOTS.values()), "(Ctrl+C untuk stop)")
            await tg.run_forever()

        else:
            print(__doc__)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
