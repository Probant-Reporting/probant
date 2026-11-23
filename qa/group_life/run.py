"""Play the life of the fictitious group, outside the test suite.

    DATA_DIR=/empty/folder python3 qa/group_life/run.py [--size tiny|small|large] [--seed 1] [--out report.json]
             [--export-threshold CELLS]   # large exports in the background from this many cells
             [--keep]   # keep the data folder after the run (to open it in a browser: runserver with the same DATA_DIR)

Refuses to run without DATA_DIR (or DATABASE_URL), and on a database that already holds data. Creates the database
(``migrate``), builds the starting state (``world.py``) and plays the scenario (``scenario.py``); writes the anomalies
found in ``--out`` (JSON) and on screen. Exit code 1 if an anomaly is found. Fictitious data only.
"""
import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
os.environ.setdefault("IMPORT_ARRIERE_PLAN_LIGNES", "0")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--size", default="small", choices=["micro", "tiny", "small", "large"])
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", default="")
    ap.add_argument("--years", type=int, default=3, help="number of reporting years to play (1 to 3)")
    ap.add_argument("--no-spaces", action="store_true", help="play only the main space")
    ap.add_argument("--export-threshold", type=int, default=None, metavar="CELLS",
                    help="cells above which an export is made in the background (default: the setting, 100,000); "
                         "lower it to play the large exports on a small group")
    args = ap.parse_args()
    if not os.environ.get("DATA_DIR") and not os.environ.get("DATABASE_URL"):
        sys.exit("Set DATA_DIR to an empty folder (or DATABASE_URL to an empty database).")

    import django

    django.setup()
    from django.conf import settings
    from django.core.management import call_command
    from django.test.utils import setup_test_environment

    settings.IMPORT_ARRIERE_PLAN_LIGNES = 0
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    settings.EMAIL_HOST = "smtp.exemple.test"  # reminders are sent only when IT has set a mail server
    call_command("migrate", verbosity=0)
    from referentiel.models import KPI, Organisation

    if Organisation.objects.exists() or KPI.objects.exists():
        sys.exit("The database already holds data: give an empty DATA_DIR.")
    setup_test_environment()  # test client: page contexts, "testserver" host, e-mails kept in memory
    settings.ALLOWED_HOSTS = ["*"]
    from qa.group_life import scenario

    t0 = time.time()
    log = scenario.play(size=args.size, seed=args.seed, years=args.years, spaces=not args.no_spaces,
                        echo=lambda s: print(f"[{time.time() - t0:6.0f}s] {s}", flush=True), standalone=True,
                        second_space="division", export_threshold=args.export_threshold)
    report = {"size": args.size, "seed": args.seed, "seconds": round(time.time() - t0), "anomalies": log.anomalies,
              "events": len(log.events)}
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=1, default=str)
    print("\nTime by step: " + ", ".join(f"{k or 'start'} {v:.0f} s" for k, v in log.durations.items()))
    print(f"\n{len(log.anomalies)} anomaly(ies) in {report['seconds']} s")
    for a in log.anomalies:
        print(f" - {a['code']} [{a['step']}] {a['detail'][:400]}")
    sys.exit(1 if log.anomalies else 0)


if __name__ == "__main__":
    main()
