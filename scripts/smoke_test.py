"""Standalone connectivity check for running Tool 2 on SaraAlt.

Checks two things independently, since either one can be broken without the
other: (1) the DB is reachable with the credentials in .env, and (2) at least
one EMISORAS_MENCION-opted-in testigo's backup share (e.g.
\\Dbackup04\\backup\\...) is reachable -- resolved via a real query rather
than a fixed share template, since backup file locations aren't uniform
across hosts. Meant to be run as smoke_test.exe on SaraAlt before relying on
Tool 2's real pipeline -- see docs/handoff.md.

Usage: smoke_test.exe [station]   (station defaults to matching any opted-in
                                   station; pass a callsign substring, e.g.
                                   "XHLUPE", to check a specific pilot station)
"""

import sys


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


def find_sample_backup_path(station: str | None) -> str | None:
    """Resolves one real backup-storage path via the same join
    fetch_discarded_segments() uses, for the most recent EMISORAS_MENCION
    -opted-in testigo (optionally narrowed to one station's callsign) --
    doesn't require a discarded segment to exist, just a backed-up testigo,
    so this can pass even before any segment has been through Tool 2's real
    query."""
    import os

    from sqlalchemy import text

    from src.db.db import engine

    station_filter = "1 = 1" if station is None else "t.ARCHIVO LIKE :station"
    query = text(
        rf"""
        SELECT TOP 1 '\\' + ho.NOM_HOST + '\' + mm.RUTA + '\' + mm.ARCHIVO AS RUTA
        FROM TESTIGO_SARA t
        JOIN EMISORAS_MENCION ee ON ee.ID_EMISORA = t.ID_EMISORA
        JOIN MULTIMEDIA_ARCHIVO mua ON t.ID_MULTIMEDIA_ARCHIVO = mua.ID_MULTIMEDIA_ARCHIVO
        JOIN MULTIMEDIA mm ON mm.ID_MULTIMEDIA_ARCHIVO = mua.ID_MULTIMEDIA_ARCHIVO AND mm.CANAL = 1
        JOIN HOST ho ON mm.ID_HOST = ho.ID_HOST
        WHERE ee.MENCIONES = 1
          AND ee.FECHA_MENCION IS NOT NULL
          AND ee.FECHA_MENCION <= t.FECHA_INICIO
          AND t.ID_ESTATUS_TESTIGO IN (10, 20)
          AND {station_filter}
        ORDER BY t.ID_TESTIGO DESC
        """
    )
    params = {"station": f"%{station.upper()}%"} if station is not None else {}
    with engine.connect() as conn:
        return conn.execute(query, params).scalar()


def test_share(station: str | None) -> tuple[bool, str]:
    import os

    ruta = find_sample_backup_path(station)
    if ruta is None:
        return (
            False,
            "FAILED -- no EMISORAS_MENCION-opted-in, backed-up testigo found "
            f"{'for station ' + station if station else 'at all'} -- check "
            "EMISORAS_MENCION.MENCIONES/FECHA_MENCION and whether that "
            "station's testigos have been archived yet",
        )

    if not os.path.isfile(ruta):
        return False, f"FAILED -- resolved path {ruta} is not reachable"

    return True, f"reachable OK -- {ruta}"


def main() -> None:
    station = sys.argv[1] if len(sys.argv) > 1 else None

    print("=" * 60)
    print("Tool 2 smoke test")
    print("=" * 60)

    print("\n[1/2] Checking DB connectivity...")
    db_ok, db_msg = test_db()
    print(f"  {'PASS' if db_ok else 'FAIL'}: {db_msg}")

    station_label = station or "any opted-in station"
    print(f"\n[2/2] Checking backup share for {station_label}...")
    share_ok, share_msg = test_share(station)
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
