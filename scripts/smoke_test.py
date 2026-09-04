"""Standalone connectivity check for running Tool 2 on SaraAlt.

Checks two things independently, since either one can be broken without the
other: (1) the OrbitMedia_Test DB is reachable with the credentials in .env,
and (2) the SARA3 network share (\\sara3\\sara\\mp3) is reachable and has
files in it. Meant to be run as smoke_test.exe on SaraAlt before relying on
Tool 2's real pipeline -- see docs/handoff.md "File access" section.

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
    import os

    share_dir = TESTIGO_SHARE_TEMPLATE.format(hostname=hostname.lower())
    try:
        if not os.path.isdir(share_dir):
            return False, f"FAILED -- {share_dir} is not reachable/does not exist"

        entries = os.listdir(share_dir)
        sample = entries[:5]
        return (
            True,
            f"reachable OK -- {share_dir} has {len(entries)} entries, "
            f"sample: {sample}",
        )
    except Exception as e:
        return False, f"FAILED -- {share_dir} -- {e}"


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
