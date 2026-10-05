#!/usr/bin/env python3
"""Start Waypoint:  poetry run python run.py  [--port 8765]  then open http://localhost:8765
(first time: poetry install --no-root)

Backups:  poetry run python run.py backup [file.json.gz]   save everything to a file
          poetry run python run.py restore file.json.gz    replace everything with a backup (asks first; --yes to skip;
                                                           stop Waypoint first)
Sample:   poetry run python run.py demo                     fill an empty database with made-up data (for previews)
Verify:   poetry run python run.py verify [page…]           run the app on made-up data in a browser at phone, tablet and
                                                           desktop widths; screenshots and a report go to artifacts/verify/
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from waypoint.server import serve

if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Waypoint, a household travel app")
    p.add_argument("--port", type=int, default=int(os.environ.get("WAYPOINT_PORT", "8765")))
    p.add_argument("--host", default=os.environ.get("WAYPOINT_HOST", "127.0.0.1"),
                   help="address to listen on; 0.0.0.0 for other devices (needs OIDC sign-in, see "
                        "https://anthonypluth.github.io/waypoint/start/docker/)")
    p.add_argument("command", nargs="?", choices=["serve", "backup", "restore", "demo", "verify"], default="serve")
    p.add_argument("file", nargs="*", help="backup file (for backup / restore), or the pages to visit (for verify; default all)")
    p.add_argument("--yes", action="store_true", help="restore without asking")
    a = p.parse_args()
    if a.command == "verify":
        from waypoint import verify
        sys.exit(verify.run(a.file))
    if len(a.file) > 1:
        p.error("only one file, please")
    a.file = a.file[0] if a.file else None
    if a.command == "serve":
        serve(host=a.host, port=a.port)
    else:
        from datetime import date
        from waypoint.storage import backup, db
        db.init()
        if a.command == "demo":
            from waypoint.domain import demo
            with db.session() as conn:
                print(f"Added sample data ({demo.seed(conn)} rows) to {db.describe()}.")
        elif a.command == "backup":
            # Without a file name: this folder, or the data folder when Waypoint has one set (in Docker, /data: the code
            # folder there is read-only).
            name = f"waypoint-backup-{date.today().isoformat()}.json.gz"
            out = a.file or (os.path.join(db.data_dir(), name) if os.environ.get("WAYPOINT_DATA") else name)
            with db.session() as conn:
                data = backup.dump(conn)
            with open(out, "wb") as f:
                f.write(data)
            os.chmod(out, 0o600)
            print(f"Saved {out} ({len(data) / 1024:.0f} KB) from {db.describe()}. Your saved secrets are in it "
                  f"encrypted: restoring it elsewhere needs the same WAYPOINT_SECRET_KEY (or secret.key).")
        else:
            if not a.file:
                sys.exit("Which backup file? python3 run.py restore waypoint-backup.json.gz")
            try:
                with open(a.file, "rb") as f:
                    restored = backup.load(f.read())
            except (OSError, ValueError) as e:
                sys.exit(str(e))
            print(f"Backup from {restored.get('created')} ({restored.get('source')}): "
                  f"{backup.preview(restored)['counts']['total']} rows.")
            # A running Waypoint's background jobs can't be held off from here: one writing during the restore would mix
            # its rows in with the backup's.
            print("Stop Waypoint first if it's running: anything it saves during the restore would be mixed in.")
            if not a.yes and input(f"Replace everything in {db.describe()} with it? Type yes: ").strip().lower() != "yes":
                sys.exit("Nothing changed.")
            try:
                done = backup.restore_all(restored)
            except ValueError as e:
                sys.exit(str(e))
            except OSError as e:
                sys.exit(f"Couldn't save a copy of what's here first ({e.strerror or e}), so nothing was restored.")
            print(f"Restored {sum(done['counts'].values())} rows into {db.describe()}.")
            if done["safety_copy"]:
                print(f"A copy of what was here before is at {done['safety_copy']}.")
            if done["unreadable_secrets"]:
                print(f"These can't be read with this Waypoint's secret key: {backup.unreadable_summary(done['unreadable_secrets'])}. Set the key "
                      "the backup was made with as WAYPOINT_SECRET_KEY_OLD and start Waypoint, or enter them again in Settings.")
