"""Read-only probe of the database of a group-life run, for the browser journeys (``browser.js``).

    DATA_DIR=… python3 qa/group_life/probe.py ids                    # campaign 2026, a site, its contributor…
    DATA_DIR=… python3 qa/group_life/probe.py cell <campaign> <kpi> <org>
    DATA_DIR=… python3 qa/group_life/probe.py campaign <campaign>
    DATA_DIR=… python3 qa/group_life/probe.py file <path.xlsx> <kpi> <org> <value>   # writes a small import file

Prints JSON. Writes nothing in the database.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")


def main():
    import django

    django.setup()
    from collecte.models import Campagne, Reponse
    from referentiel.models import Attribution, Organisation

    cmd, args = sys.argv[1], sys.argv[2:]
    if cmd == "ids":
        c = Campagne.objects.filter(referentiel_id="GROUPREP", exercice=2026).first()
        a = Attribution.objects.filter(utilisateur__username="gl-con-1-1", kpi_id="WATER", organisation__actif=True).order_by("organisation__rang").first()
        out = {"campaign2026": c.pk if c else None, "campaign2026_status": c.statut if c else None,
               "site": a.organisation_id if a else None, "site_name": a.organisation.nom if a else None,
               "second_site": Attribution.objects.filter(utilisateur__username="gl-con-1-1", kpi_id="WATER", organisation__actif=True)
               .exclude(organisation_id=a.organisation_id if a else 0).values_list("organisation_id", flat=True).first()}
    elif cmd == "cell":
        c = Campagne.objects.get(pk=args[0])
        r = Reponse.objects.filter(periode=c.periode, kpi_id=args[1], organisation_id=args[2]).first()
        out = {"exists": r is not None, "valeur": str(r.valeur) if r and r.valeur is not None else None,
               "statut": r.statut if r else None, "commentaire": r.commentaire if r else None}
    elif cmd == "campaign":
        c = Campagne.objects.get(pk=args[0])
        out = {"statut": c.statut}
    elif cmd == "file":
        from openpyxl import Workbook

        path, kpi, org, value = args
        o = Organisation.objects.get(pk=org)
        wb = Workbook()
        ws = wb.active
        ws.title = "Saisie"
        ws.append(["KPI ID", "Organisation code", "Organisation", "Value", "Comment"])
        ws.append([kpi, o.code, o.nom, float(value), "Imported in the browser"])
        ws.append(["NOPE", o.code, o.nom, 1, "Rejected line"])
        wb.save(path)
        out = {"file": path}
    else:
        sys.exit(f"unknown command {cmd}")
    print(json.dumps(out))


if __name__ == "__main__":
    main()
