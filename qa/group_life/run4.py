"""Play the fourth year of the fictitious group (``year4.py``), outside the test suite.

    DATA_DIR=/empty/folder python3 qa/group_life/run4.py [--size micro|tiny|small|large] [--years 1..3] [--seed 1]
             [--out report.json] [--no-spaces]

Same rules as ``run.py`` (empty data folder or empty database; fictitious data only). Plays ``--years`` years first
(1 by default: the fourth year needs only the first one; 3 for the whole life), the second space, then the events of the
fourth year. Prints the table of the events played and the anomalies; exit code 1 if an anomaly is found.
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
    ap.add_argument("--size", default="micro", choices=["micro", "tiny", "small", "large"])
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--years", type=int, default=1, help="reporting years played before the fourth one (1 to 3)")
    ap.add_argument("--out", default="")
    ap.add_argument("--no-spaces", action="store_true")
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
    settings.EMAIL_HOST = "smtp.exemple.test"
    call_command("migrate", verbosity=0)
    from referentiel.models import KPI, Organisation

    if Organisation.objects.exists() or KPI.objects.exists():
        sys.exit("The database already holds data: give an empty DATA_DIR.")
    setup_test_environment()
    settings.ALLOWED_HOSTS = ["*"]
    from qa.group_life import year4

    t0 = time.time()
    log = year4.play4(size=args.size, seed=args.seed, years=args.years, spaces=not args.no_spaces, standalone=True,
                      second_space="division", echo=lambda s: print(f"[{time.time() - t0:6.0f}s] {s}", flush=True))
    report = {"size": args.size, "seed": args.seed, "years": args.years, "seconds": round(time.time() - t0),
              "played": log.played, "anomalies": log.anomalies}
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=1, default=str)
    print("\nEvents of the fourth year:")
    for p in log.played:
        print(f" - {p['event']}: {p['status']} — {p['detail'][:200]}")
    print(f"\n{len(log.anomalies)} anomaly(ies) in {report['seconds']} s")
    for a in log.anomalies:
        print(f" - {a['code']} [{a['step']}]{' (rule)' if a.get('rule') else ''} {a['detail'][:400]}")
    sys.exit(1 if log.anomalies else 0)


if __name__ == "__main__":
    main()
