"""Check of the readable table in Excel formulas: recalculated outside the tool, the formulas give the tool's figures.

    python3 manage.py load_demo        # or any copy of a database
    python3 qa/formula_check.py [--years 2021 2026] [--user validateur] [--keep /path/folder]

Steps: export of the readable table (all years by default, administrator, with N-1) in figures and in Excel formulas;
recalculation of the formulas file by LibreOffice on the command line (``soffice --headless --convert-to xlsx``, which
calculates every formula on load); comparison, cell by cell, of each formula's result with the figure of the export in
figures (percentages: 0-100 in figures, fraction in formulas). Exit code: 0 if every formula gives the tool's figure, 1 otherwise.
"""
# Messages en anglais (comme les autres scripts de qa/) ; commentaires et identifiants en français.
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")


def comparer(chiffres, formules, recalcule):
    """(nombre de formules, [(onglet, case, KPI, formule, attendu, obtenu)] des écarts)."""
    from openpyxl import load_workbook

    wc, wf, wr = (load_workbook(c, data_only=d) for c, d in ((chiffres, True), (formules, False), (recalcule, True)))
    n, ecarts = 0, []
    for nom in wf.sheetnames[1:]:  # « À lire » d'abord
        a, f, r = wc[nom], wf[nom], wr[nom]
        for ligne in f.iter_rows():
            for c in ligne:
                if not (isinstance(c.value, str) and c.value.startswith("=")):
                    continue
                n += 1
                attendu = a.cell(c.row, c.column)
                v = attendu.value
                if isinstance(v, (int, float)) and attendu.number_format.endswith('" %"'):
                    v = v / 100
                obtenu = r.cell(c.row, c.column).value
                if not isinstance(obtenu, (int, float)) or not isinstance(v, (int, float)) or abs(obtenu - v) > 1e-9 + 1e-9 * abs(v):
                    ecarts.append((nom, c.coordinate, f.cell(c.row, 1).value, c.value, v, obtenu))
    return n, ecarts


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--years", nargs="*", default=["tous"], help="reporting years (default: all)")
    parser.add_argument("--user", help="account that exports (default: the first administrator); its scope applies")
    parser.add_argument("--keep", help="folder where the three files are kept")
    args = parser.parse_args()
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        print("LibreOffice (soffice) not found: install it to recalculate the formulas.")
        return 2
    import django

    django.setup()
    from collecte import exports as E
    from referentiel.models import Utilisateur

    comptes = Utilisateur.objects.filter(username=args.user) if args.user else \
        Utilisateur.objects.filter(role=Utilisateur.Role.ADMIN).order_by("pk")
    admin = comptes.first()
    if admin is None:
        print("Account not found in this database.")
        return 2
    dossier = args.keep or tempfile.mkdtemp()
    os.makedirs(dossier, exist_ok=True)
    try:
        chemins = {}
        for valeurs in ("chiffres", "formules"):
            p = E.Parametres.depuis({"presentation": "tableau", "format": "xlsx", "exercices": args.years, "n1": True,
                                     "valeurs": valeurs})
            debut = time.time()
            reponse = E.exporter(admin, p)
            chemins[valeurs] = os.path.join(dossier, f"table_{valeurs}.xlsx")
            Path(chemins[valeurs]).write_bytes(reponse.content)
            print(f"Export in {'figures' if valeurs == 'chiffres' else 'formulas'}: {time.time() - debut:.1f} s, "
                  f"{len(reponse.content) // 1024} KB")
            if valeurs == "formules":
                compte = p._formules.compte
                print("  cells as formulas:", compte["formules"], "· kept as figures:",
                      ", ".join(f"{k} {v}" for k, v in compte.items() if k != "formules" and v) or "none")
        sortie = os.path.join(dossier, "recalculated")
        profil = "file://" + os.path.join(dossier, "lo-profile")
        debut = time.time()
        subprocess.run([soffice, f"-env:UserInstallation={profil}", "--headless", "--calc", "--convert-to", "xlsx",
                        "--outdir", sortie, chemins["formules"]], check=True, capture_output=True, timeout=900)
        print(f"Recalculation by LibreOffice: {time.time() - debut:.1f} s")
        n, ecarts = comparer(chemins["chiffres"], chemins["formules"], os.path.join(sortie, "table_formules.xlsx"))
        print(f"Formulas checked: {n} · differences: {len(ecarts)}")
        for e in ecarts[:20]:
            print("  ", e)
        if not n:
            print("No calculated cell in this export (scope of the account): nothing to check.")
        return 1 if ecarts else 0
    finally:
        if not args.keep:
            shutil.rmtree(dossier, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
