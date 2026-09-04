"""Standalone connectivity check for running Tool 2 on SaraAlt.

Checks two things independently, since either one can be broken without the
other: (1) the OrbitMedia_Test DB is reachable with the credentials in .env,
and (2) the SARA3 network share (\\sara3\\sara, and its MP3 subfolder where
ARCHIVO values actually point) is reachable and has files in it. Meant to be
run as smoke_test.exe on SaraAlt before relying on Tool 2's real pipeline --
see docs/handoff.md "File access" section.

Usage: smoke_test.exe [hostname]   (hostname defaults to sara3)
"""

import sys

from src.tool2 import TESTIGO_SHARE_TEMPLATE

DEFAULT_HOSTNAME = "sara3"


def test_db() -> tuple[bool, str]:
    try:
        from sqlalchemy import text

        from src.db.db import engine

        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            latest = conn.execute(
                text("SELECT MAX(FECHA_INICIO) FROM TESTIGO_SARA")
            ).scalar()
        return True, f"connected OK -- latest TESTIGO_SARA.FECHA_INICIO = {latest}"
    except Exception as e:
        return False, f"FAILED -- {e}"


def test_share(hostname: str) -> tuple[bool, str]:
    """Checks both the share root (what resolve_testigo_path() actually joins
    ARCHIVO onto) and its MP3 subfolder (where TESTIGO_SARA.ARCHIVO values
    for SARA3 have been observed to point, e.g. "MP3\\XHRED-...MP3") -- the
    subfolder check is what actually matters for real segment resolution."""
    import os

    share_root = TESTIGO_SHARE_TEMPLATE.format(hostname=hostname.lower())
    mp3_dir = os.path.join(share_root, "MP3")

    if not os.path.isdir(share_root):
        return False, f"FAILED -- {share_root} is not reachable/does not exist"

    try:
        root_entries = os.listdir(share_root)
    except Exception as e:
        return False, f"FAILED -- {share_root} -- {e}"

    if not os.path.isdir(mp3_dir):
        return (
            False,
            f"share root {share_root} reachable ({len(root_entries)} entries), "
            f"but {mp3_dir} is not -- resolve_testigo_path() expects ARCHIVO's "
            f"own subfolder to live here",
        )

    mp3_entries = os.listdir(mp3_dir)
    return (
        True,
        f"reachable OK -- {mp3_dir} has {len(mp3_entries)} entries, "
        f"sample: {mp3_entries[:5]}",
    )


def main() -> None:
    hostname = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_HOSTNAME

    print("=" * 60)
    print("Tool 2 smoke test")
    print("=" * 60)

    print("\n[1/2] Checking DB connectivity (OrbitMedia_Test)...")
    db_ok, db_msg = test_db()
    print(f"  {'PASS' if db_ok else 'FAIL'}: {db_msg}")

    print(f"\n[2/2] Checking network share for host '{hostname}'...")
    share_ok, share_msg = test_share(hostname)
    print(f"  {'PASS' if share_ok else 'FAIL'}: {share_msg}")

    print("\n" + "=" * 60)
    if db_ok and share_ok:
        print("RESULT: all checks passed.")
    else:
        print("RESULT: one or more checks FAILED -- see above.")
    print("=" * 60)


if __name__ == "__main__":
    main()
    input("\nPress Enter to exit...")
