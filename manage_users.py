"""CLI kelola akun login aplikasi (tabel app_users).

  python manage_users.py add <username> <password> [admin|user]
  python manage_users.py list
  python manage_users.py passwd <username> <password>
  python manage_users.py role <username> <admin|user>
  python manage_users.py disable <username>
  python manage_users.py enable <username>
  python manage_users.py del <username>
"""
import asyncio
import sys

import appauth
import db


async def main() -> int:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 1
    cmd, rest = args[0], args[1:]
    conn = await db.connect()
    try:
        if cmd == "add" and len(rest) >= 2:
            role = rest[2] if len(rest) > 2 else "user"
            await appauth.create_user(conn, rest[0], rest[1], role)
            print(f"OK: user '{rest[0]}' ({role}) dibuat/diupdate.")
        elif cmd == "list":
            rows = await appauth.list_users(conn)
            if not rows:
                print("(belum ada user)")
            for r in rows:
                aktif = "aktif" if r["active"] else "nonaktif"
                last = r["last_login_at"] or "-"
                print(f"  {r['username']:20} {r['role']:6} {aktif:9} login_terakhir={last}")
        elif cmd == "passwd" and len(rest) >= 2:
            ok = await appauth.set_password(conn, rest[0], rest[1])
            print("OK" if ok else "user tidak ditemukan")
        elif cmd == "role" and len(rest) >= 2:
            ok = await appauth.set_role(conn, rest[0], rest[1])
            print("OK" if ok else "user tidak ditemukan")
        elif cmd == "disable" and rest:
            ok = await appauth.set_active(conn, rest[0], False)
            print("OK" if ok else "user tidak ditemukan")
        elif cmd == "enable" and rest:
            ok = await appauth.set_active(conn, rest[0], True)
            print("OK" if ok else "user tidak ditemukan")
        elif cmd == "del" and rest:
            ok = await appauth.delete_user(conn, rest[0])
            print("OK" if ok else "user tidak ditemukan")
        else:
            print(__doc__)
            return 1
    finally:
        await conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
