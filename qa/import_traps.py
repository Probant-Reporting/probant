"""Trapped imports: generates hundreds of damaged or odd files (values, configuration, framework package,
translations, organisations; Excel and CSV) and sends each one through the tool's pages with Django's test client
(preview, then confirmation), as the administrator and as a contributor.

    DATA_DIR=/path/to/a/copy/of/the/demo DJANGO_DEBUG=1 python3 qa/import_traps.py [--only valeurs,config,...]
        [--keep-files /folder] [--big] [--report result.json]

Works on a demo database (python3 manage.py load_demo: Exemplia, open 2026 campaign; no real data): use a COPY (DATA_DIR pointing to
a temporary folder), never a real installation. Each case runs inside a transaction that is rolled back at the end:
the database is left as it was.

Checked for every file:
- never a server error (exception, status 500), at the preview, the confirmation or the download of the rejected rows;
- the preview writes nothing (fingerprint of every table except the sessions);
- a refused file (whole file refused) writes nothing at the confirmation;
- nothing written in a closed campaign by a contributor; an admin never replaces a value entered in the tool there;
- a clear message: no Python text (Traceback, Error, None, object…) in what the person reads;
- the rejected rows are listed and can be downloaded (Excel and CSV) and re-imported without error.

Exit code 1 if a case fails; details in the JSON report (--report) and on screen.
"""
import argparse
import codecs
import csv
import datetime
import gc
import hashlib
import io
import itertools
import json
import os
import random
import re
import sys
import time
import traceback
import zipfile

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RACINE)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

from django.contrib.messages import get_messages  # noqa: E402,F401
from django.core.files.uploadedfile import SimpleUploadedFile  # noqa: E402
from django.db import connection, transaction  # noqa: E402
from django.test import Client  # noqa: E402
from django.test.utils import setup_test_environment  # noqa: E402
from django.urls import reverse  # noqa: E402
from openpyxl import Workbook, load_workbook  # noqa: E402

setup_test_environment()

from collecte import saisie as S  # noqa: E402
from collecte.models import Campagne, Reponse  # noqa: E402
from referentiel.models import KPI, Referentiel, Utilisateur  # noqa: E402

# Texte qui ne doit jamais arriver à l'écran (message technique)
TECHNIQUE = re.compile(r"Traceback|Exception|Error\b|errno|\bNone\b|<[a-zA-Z_.]+ object at|\bobject\b|KeyError|ValueError|"
                       r"TypeError|IndexError|AttributeError|InvalidOperation|UnicodeDecode|\bb'|\\x[0-9a-f]{2}")
TABLES_IGNOREES = {"django_session", "sqlite_sequence"}


# ---------------------------------------------------------------- empreinte de la base
def empreinte():
    """{table: sha256 de toutes ses lignes} (hors sessions)."""
    sortie = {}
    with connection.cursor() as cur:
        tables = [t for t in connection.introspection.table_names(cur) if t not in TABLES_IGNOREES]
        for t in tables:
            cur.execute(f'SELECT * FROM "{t}" ORDER BY 1')
            h = hashlib.sha256()
            for ligne in cur.fetchall():
                h.update(repr(ligne).encode())
            sortie[t] = h.hexdigest()
    return sortie


def etat():
    """Repère d'écriture : sous SQLite, le nombre de lignes écrites depuis l'ouverture de la connexion (les sessions sont
    gardées en mémoire, voir main) ; sinon l'empreinte de toutes les tables."""
    if connection.vendor == "sqlite":
        connection.ensure_connection()
        return connection.connection.total_changes
    return empreinte()


def differences(avant, apres):
    if isinstance(avant, int):
        return [f"{apres - avant} row(s)"] if apres != avant else []
    return sorted(t for t in set(avant) | set(apres) if avant.get(t) != apres.get(t))


# ---------------------------------------------------------------- fabrication des fichiers
def xlsx(feuilles, proprietes=None):
    """feuilles : [(titre, lignes, options)] ; options : cachee, fusions [plages], formats {cellule: format}."""
    wb = Workbook()
    wb.remove(wb.active)
    for titre, lignes, opts in feuilles:
        ws = wb.create_sheet(titre)
        for ligne in lignes:
            ws.append(list(ligne))
        for plage in (opts or {}).get("fusions", []):
            ws.merge_cells(plage)
        for cel, fmt in (opts or {}).get("formats", {}).items():
            ws[cel].number_format = fmt
        if (opts or {}).get("cachee"):
            ws.sheet_state = (opts or {}).get("cachee")
    if not wb.worksheets:
        wb.create_sheet("Vide")
    tampon = io.BytesIO()
    wb.save(tampon)
    return tampon.getvalue()


def xlsx_vite(entetes, lignes):
    """Gros classeur en écriture seule (100 000 lignes)."""
    wb = Workbook(write_only=True)
    ws = wb.create_sheet("Saisie")
    ws.append(entetes)
    for ligne in lignes:
        ws.append(ligne)
    tampon = io.BytesIO()
    wb.save(tampon)
    return tampon.getvalue()


def csv_octets(lignes, sep=";", encodage="utf-8", fin="\r\n"):
    tampon = io.StringIO()
    w = csv.writer(tampon, delimiter=sep, lineterminator=fin)
    for ligne in lignes:
        w.writerow(["" if v is None else v for v in ligne])
    return tampon.getvalue().encode(encodage, errors="replace") if encodage != "utf-8-sig" else codecs.BOM_UTF8 + tampon.getvalue().encode("utf-8")


def tronque(octets, part=0.5):
    return octets[: max(1, int(len(octets) * part))]


def zip_bidon():
    tampon = io.BytesIO()
    with zipfile.ZipFile(tampon, "w") as z:
        z.writestr("bonjour.txt", "pas un classeur")
    return tampon.getvalue()


def xlsx_xml_casse(octets):
    """Classeur dont la feuille 1 contient du XML invalide."""
    entree, sortie = io.BytesIO(octets), io.BytesIO()
    with zipfile.ZipFile(entree) as zin, zipfile.ZipFile(sortie, "w") as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename.startswith("xl/worksheets/sheet"):
                data = data[: len(data) // 2] + b"<<<&&&"
            zout.writestr(item, data)
    return sortie.getvalue()


def xlsx_sans_feuille(octets):
    """Classeur dont un fichier de feuille annoncé manque."""
    entree, sortie = io.BytesIO(octets), io.BytesIO()
    with zipfile.ZipFile(entree) as zin, zipfile.ZipFile(sortie, "w") as zout:
        for item in zin.infolist():
            if not item.filename.startswith("xl/worksheets/sheet1"):
                zout.writestr(item, zin.read(item.filename))
    return sortie.getvalue()


# ---------------------------------------------------------------- contexte de la démo
class Demo:
    def __init__(self):
        self.admin = Utilisateur.objects.get(username="admin")
        self.contributeur = Utilisateur.objects.get(username="contributeur")
        self.validateur = Utilisateur.objects.get(username="validateur")
        self.ouverte = Campagne.objects.filter(statut=Campagne.Statut.OUVERTE).order_by("-exercice").first()
        self.cloturee = Campagne.objects.filter(statut=Campagne.Statut.CLOTUREE).order_by("-exercice").first()
        cel = [(k, o) for k, o in S.cellules(self.contributeur, campagne=self.ouverte)
               if k.est_numerique and not k.est_pourcentage and not k.est_entier and not k.est_calcule]
        self.cases = cel[:40]
        self.k, self.o = self.cases[0]
        self.pourcent = next(((k, o) for k, o in S.cellules(self.contributeur, campagne=self.ouverte)
                              if k.est_pourcentage and not k.est_calcule), None)
        self.entier = next(((k, o) for k, o in S.cellules(self.contributeur, campagne=self.ouverte)
                            if k.est_entier and not k.est_calcule), None)
        self.texte = next(((k, o) for k, o in S.cellules(self.admin, campagne=self.ouverte)
                           if not k.est_numerique and not k.est_calcule), None)
        self.calcule = KPI.objects.filter(type_saisie__comportement="calcul", actif=True).first()
        # une case saisie dans l'outil d'une campagne clôturée (pour l'admin : jamais remplacée)
        self.saisie_cloturee = None
        self.referentiel = Referentiel.objects.filter(actif=True).order_by("ordre").first()


def entetes_valeurs():
    return ["ID KPI", "Organisation", "Exercice", "Valeur", "N/A", "Commentaire"]


def valeurs_cas(d, gros=False):
    """[(nom, nom_fichier, octets, attente)] pour l'import des valeurs. attente : {'refus': True} quand le fichier entier
    doit être refusé (rien d'écrit)."""
    ex = d.ouverte.exercice
    exc = d.cloturee.exercice
    k, o = d.k.code, d.o.nom
    E = entetes_valeurs()
    bons = [[kk.code, oo.nom, ex, 100 + i, "", f"essai {i}"] for i, (kk, oo) in enumerate(d.cases[:10])]
    cas = []

    def ajoute(nom, fichier, octets, **attente):
        cas.append((nom, fichier, octets, attente))

    # --- en-têtes
    ajoute("entetes-ok", "ok.xlsx", xlsx([("Saisie", [E] + bons, {})]))
    ajoute("entetes-manque-kpi", "a.xlsx", xlsx([("Saisie", [E[1:]] + [r[1:] for r in bons], {})]), refus=True)
    ajoute("entetes-manque-valeur", "a.xlsx", xlsx([("Saisie", [[h for h in E if h != "Valeur"]] + [r[:3] + r[4:] for r in bons], {})]), refus=True)
    ajoute("entetes-manque-org", "a.xlsx", xlsx([("Saisie", [[E[0]] + E[2:]] + [[r[0]] + r[2:] for r in bons], {})]), refus=True)
    ajoute("entetes-aucun", "a.xlsx", xlsx([("Saisie", bons, {})]), refus=True)
    ajoute("entetes-doublon-valeur", "a.xlsx", xlsx([("Saisie", [E + ["Valeur"]] + [r + [999] for r in bons], {})]))
    ajoute("entetes-doublon-kpi", "a.xlsx", xlsx([("Saisie", [["ID KPI"] + E] + [["XXX"] + r for r in bons], {})]))
    ordre = [3, 5, 0, 2, 1, 4]
    ajoute("entetes-desordre", "a.xlsx", xlsx([("Saisie", [[E[i] for i in ordre]] + [[r[i] for i in ordre] for r in bons], {})]))
    ajoute("entetes-ligne-10", "a.xlsx", xlsx([("Saisie", [["titre"]] * 9 + [E] + bons, {})]))
    ajoute("entetes-ligne-20", "a.xlsx", xlsx([("Saisie", [["titre"]] * 19 + [E] + bons, {})]), refus=True)
    ajoute("entetes-anglais", "a.xlsx", xlsx([("Input", [["KPI code", "Organization", "Year", "Value", "N/A", "Comment"]] + bons, {})]))
    ajoute("entetes-espagnol", "a.csv", csv_octets([["Código KPI", "Organización", "Ejercicio", "Valor", "N/A", "Comentario"]] + bons))
    ajoute("entetes-casse-espaces", "a.xlsx", xlsx([("Saisie", [["  id kpi ", "ORGANISATION", " exercice", "VALEUR ", "n/a", "commentaire"]] + bons, {})]))
    ajoute("entetes-vides-intercalees", "a.xlsx", xlsx([("Saisie", [["", "ID KPI", None, "Organisation", "Exercice", "Valeur"]]
                                                                 + [["", r[0], None, r[1], r[2], r[3]] for r in bons], {})]))
    ajoute("entetes-nombres", "a.xlsx", xlsx([("Saisie", [[1, 2, 3, 4, 5]] + bons, {})]), refus=True)
    # --- structure Excel
    ajoute("fusion-entetes", "a.xlsx", xlsx([("Saisie", [E, E] + bons, {"fusions": ["A1:F1"]})]))
    ajoute("fusion-donnees", "a.xlsx", xlsx([("Saisie", [E] + bons, {"fusions": ["B2:B6", "D3:E4"]})]))
    ajoute("formules", "a.xlsx", xlsx([("Saisie", [E] + [[r[0], r[1], r[2], "=1+1", "", "=A2"] for r in bons], {})]))
    ajoute("formules-org", "a.xlsx", xlsx([("Saisie", [E] + [[r[0], "=\"" + r[1] + "\"", r[2], 5] for r in bons], {})]))
    for err in ("#DIV/0!", "#N/A", "#REF!", "#VALUE!", "#NAME?", "#NUM!", "#NULL!"):
        ajoute(f"erreur-excel-{err}", "a.xlsx", xlsx([("Saisie", [E] + [[r[0], r[1], r[2], err] for r in bons], {})]))
    ajoute("erreur-excel-kpi", "a.xlsx", xlsx([("Saisie", [E] + [["#N/A", r[1], r[2], 5] for r in bons], {})]))
    ajoute("dates-valeur", "a.xlsx", xlsx([("Saisie", [E] + [[r[0], r[1], r[2], datetime.datetime(2026, 3, 1)] for r in bons], {})]))
    ajoute("dates-exercice", "a.xlsx", xlsx([("Saisie", [E] + [[r[0], r[1], datetime.datetime(ex, 1, 1), 5] for r in bons], {})]))
    ajoute("date-seule-exercice", "a.xlsx", xlsx([("Saisie", [E] + [[r[0], r[1], datetime.date(ex, 12, 31), 5] for r in bons], {})]))
    ajoute("heure-valeur", "a.xlsx", xlsx([("Saisie", [E] + [[r[0], r[1], r[2], datetime.time(12, 30)] for r in bons], {})]))
    ajoute("duree-valeur", "a.xlsx", xlsx([("Saisie", [E] + [[r[0], r[1], r[2], datetime.timedelta(days=2)] for r in bons], {})]))
    ajoute("booleens", "a.xlsx", xlsx([("Saisie", [E] + [[r[0], r[1], r[2], True, False] for r in bons], {})]))
    ajoute("booleen-na", "a.xlsx", xlsx([("Saisie", [E] + [[r[0], r[1], r[2], None, True] for r in bons], {})]))
    ajoute("onglet-cache", "a.xlsx", xlsx([("Notes", [["rien"]], {}), ("Saisie", [E] + bons, {"cachee": "hidden"})]))
    ajoute("onglet-tres-cache", "a.xlsx", xlsx([("Saisie", [E] + bons, {"cachee": "veryHidden"}), ("Autre", [["x"]], {})]))
    ajoute("deux-onglets-contradictoires", "a.xlsx", xlsx([("Saisie", [E] + bons, {}),
                                                           ("Valeurs", [E] + [r[:3] + [r[3] + 1] for r in bons], {})]))
    ajoute("pourcent-format-excel", "a.xlsx", xlsx([("Saisie", [E] + [[r[0], r[1], r[2], 0.5] for r in bons],
                                                     {"formats": {f"D{i}": "0%" for i in range(2, 12)}})]))
    ajoute("classeur-vide", "a.xlsx", xlsx([("Saisie", [], {})]), refus=True)
    ajoute("seulement-entetes", "a.xlsx", xlsx([("Saisie", [E], {})]))
    ajoute("lignes-vides", "a.xlsx", xlsx([("Saisie", [E] + [[None] * 6] * 30 + bons + [[""] * 6] * 30, {})]))
    ajoute("cent-onglets", "a.xlsx", xlsx([(f"Org {i}", [E] + bons[:1], {}) for i in range(100)]))
    # --- valeurs bizarres
    bizarres = ["abc", "12abc", "1e5", "1E+16", "1e400", "-1e400", "NaN", "nan", "inf", "-Infinity", "1" * 40, "-5",
                "-0", "0", "  1 234,5  ", "1.234.567", "1,234", "1.234", "1,234.56", "1.234,56", "12 %", "%", "€ 12", "12€",
                "(12)", "１２", "1 234", "1 234", "0x1F", "1_000", "+12", "12-", "=1+1", "'=1+1", "1/2", "½",
                "Ⅻ", "١٢٣", "--5", "1..2", ",5", "5,", ".", ",", "1 2 3", "9" * 15 + ",99", "0,0000000000001", "1e-30",
                "N/A", "na", "n.a.", "-", "—", "?", "TRUE", "oui", "\t12", "12\n", "\x00", "<script>", "${7*7}"]
    for i, v in enumerate(bizarres):
        if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", v):  # interdit dans un classeur : en CSV
            ajoute(f"valeur-{i:02d}-{v[:12]!r}", "a.csv", csv_octets([E, [k, o, ex, v, "", ""]]))
        else:
            ajoute(f"valeur-{i:02d}-{v[:12]!r}", "a.xlsx", xlsx([("Saisie", [E, [k, o, ex, v, "", ""]], {})]))
    for v in (1e30, -1e30, 1e15, 123456789012.5, -5, 0.1 + 0.2, 1e-12, float(2 ** 63), -0.0):
        ajoute(f"nombre-excel-{v!r}", "a.xlsx", xlsx([("Saisie", [E, [k, o, ex, v]], {})]))
    if d.pourcent:
        pk, po = d.pourcent
        for v in ("50", "50 %", "150", "-1", "0,5", 0.5, "1e2", "100,0001"):
            ajoute(f"pourcentage-{v!r}", "a.xlsx", xlsx([("Saisie", [E, [pk.code, po.nom, ex, v]], {})]))
    if d.entier:
        ek, eo = d.entier
        for v in ("12", "12,5", "1e3", "1,000", 12.0, 12.5):
            ajoute(f"entier-{v!r}", "a.xlsx", xlsx([("Saisie", [E, [ek.code, eo.nom, ex, v]], {})]))
    if d.texte:
        tk, to = d.texte
        for v in ("Oui", "Non", "peut-être", "", "1", "YES", "sí", "x" * 300):
            ajoute(f"oui-non-liste-{v[:10]!r}", "a.xlsx", xlsx([("Saisie", [E, [tk.code, to.nom, ex, v]], {})]))
    # --- codes et organisations
    ajoute("kpi-minuscules", "a.xlsx", xlsx([("Saisie", [E] + [[r[0].lower()] + r[1:] for r in bons], {})]))
    ajoute("kpi-espaces", "a.xlsx", xlsx([("Saisie", [E] + [[f"  {r[0]} "] + r[1:] for r in bons], {})]))
    ajoute("kpi-espace-insecable", "a.xlsx", xlsx([("Saisie", [E] + [[f" {r[0]} "] + r[1:] for r in bons], {})]))
    ajoute("kpi-apostrophe", "a.xlsx", xlsx([("Saisie", [E] + [[f"'{r[0]}"] + r[1:] for r in bons], {})]))
    ajoute("kpi-nombre", "a.xlsx", xlsx([("Saisie", [E] + [[int(r[0]) if r[0].isdigit() else r[0]] + r[1:] for r in bons], {})]))
    ajoute("kpi-nombre-decimal", "a.xlsx", xlsx([("Saisie", [E] + [[float(r[0]) if r[0].isdigit() else r[0]] + r[1:] for r in bons], {})]))
    ajoute("kpi-inconnus", "a.xlsx", xlsx([("Saisie", [E] + [["ZZZ" + str(i)] + r[1:] for i, r in enumerate(bons)], {})]))
    ajoute("kpi-calcule", "a.xlsx", xlsx([("Saisie", [E, [d.calcule.code, o, ex, 5]], {})]))
    ajoute("org-inconnue", "a.xlsx", xlsx([("Saisie", [E] + [[r[0], "Atlantide"] + r[2:] for r in bons], {})]))
    ajoute("org-casse", "a.xlsx", xlsx([("Saisie", [E] + [[r[0], r[1].upper()] + r[2:] for r in bons], {})]))
    ajoute("org-espaces", "a.xlsx", xlsx([("Saisie", [E] + [[r[0], f"  {r[1]}  "] + r[2:] for r in bons], {})]))
    ajoute("org-mauvais-niveau", "a.xlsx", xlsx([("Saisie", [E] + [[r[0], racine()] + r[2:] for r in bons], {})]))
    ajoute("doublons-contradictoires", "a.xlsx", xlsx([("Saisie", [E] + bons + [r[:3] + [r[3] * 2] for r in bons], {})]))
    ajoute("doublons-identiques", "a.xlsx", xlsx([("Saisie", [E] + bons + bons, {})]))
    # --- périodes et campagnes
    ajoute("campagne-cloturee", "a.xlsx", xlsx([("Saisie", [E] + [r[:2] + [exc] + r[3:] for r in bons], {})]))
    ajoute("campagne-cloturee-csv", "a.csv", csv_octets([E] + [r[:2] + [exc] + r[3:] for r in bons]))
    ajoute("campagne-future", "a.xlsx", xlsx([("Saisie", [E] + [r[:2] + [2099] + r[3:] for r in bons], {})]))
    for v in ("abc", "0000", "0", "26", "2026-2027", "FY2026", "12345", "99999999", "-2026", "2026.5", "1e3"):
        ajoute(f"exercice-{v}", "a.xlsx", xlsx([("Saisie", [E, [k, o, v, 5]], {})]))
    for v in ("13/2026", "00/2026", "T5 2026", "2026-02-30", "janvier", "S3 2026", "Q1 2026", "2026", "mars 2026", "x" * 200):
        ajoute(f"periode-{v[:12]}", "a.xlsx", xlsx([("Saisie", [["ID KPI", "Organisation", "Période", "Valeur"], [k, o, v, 5]], {})]))
    ajoute("sans-periode", "a.xlsx", xlsx([("Saisie", [["ID KPI", "Organisation", "Valeur"], [k, o, 5]], {})]))
    ajoute("referentiel-inconnu", "a.xlsx", xlsx([("Saisie", [E + ["Référentiel"]] + [r + ["Inconnu"] for r in bons], {})]))
    ajoute("commentaire-immense", "a.xlsx", xlsx([("Saisie", [E, [k, o, ex, 5, "", "c" * 32000]], {})]))
    ajoute("na-et-valeur", "a.xlsx", xlsx([("Saisie", [E, [k, o, ex, 5, "Oui", "les deux"]], {})]))
    ajoute("na-bizarre", "a.xlsx", xlsx([("Saisie", [E, [k, o, ex, None, "peut-être", ""]], {})]))
    # --- CSV : séparateurs, encodages, formes
    lignes = [E] + bons
    for sep in (";", ",", "\t", "|"):
        ajoute(f"csv-sep-{sep!r}", "a.csv", csv_octets(lignes, sep=sep), **({"refus": True} if sep == "|" else {}))
    for enc in ("utf-8", "utf-8-sig", "latin-1", "cp1252", "utf-16", "utf-16-le", "utf-16-be", "utf-32", "mac_roman", "cp850"):
        accent = [E, [k, o, ex, 5, "", "été à Noël €"]]
        ajoute(f"csv-encodage-{enc}", "a.csv", csv_octets(accent, encodage=enc))
    ajoute("csv-fins-de-ligne-cr", "a.csv", csv_octets(lignes, fin="\r"))
    ajoute("csv-fins-de-ligne-lf", "a.csv", csv_octets(lignes, fin="\n"))
    ajoute("csv-guillemet-ouvert", "a.csv", ("ID KPI;Organisation;Exercice;Valeur\n" + f'{k};"{o};{ex};5\n{k};{o};{ex};6\n').encode())
    ajoute("csv-nul", "a.csv", (f"ID KPI;Organisation;Exercice;Valeur\n{k};{o}\x00;{ex};5\n").encode())
    ajoute("csv-champ-immense", "a.csv", (f"ID KPI;Organisation;Exercice;Valeur;Commentaire\n{k};{o};{ex};5;\"" + "x" * 200_000 + "\"\n").encode())
    ajoute("csv-champ-immense-sans-guillemets", "a.csv", (f"ID KPI;Organisation;Exercice;Valeur;Commentaire\n{k};{o};{ex};5;" + "x" * 200_000 + "\n").encode())
    ajoute("csv-vide", "a.csv", b"", refus=True)
    ajoute("csv-bom-seul", "a.csv", codecs.BOM_UTF8, refus=True)
    ajoute("csv-espaces", "a.csv", b"   \n  \n", refus=True)
    ajoute("csv-binaire", "a.csv", bytes(random.Random(1).randrange(256) for _ in range(5000)), refus=True)
    ajoute("csv-une-colonne", "a.csv", b"ID KPI\nX\n", refus=True)
    ajoute("csv-lignes-inegales", "a.csv", (f"ID KPI;Organisation;Exercice;Valeur\n{k}\n{k};{o}\n{k};{o};{ex};5;6;7;8\n").encode())
    ajoute("csv-txt", "a.txt", csv_octets(lignes))
    ajoute("csv-majuscule-ext", "A.CSV", csv_octets(lignes))
    ajoute("csv-excel-renomme", "a.csv", xlsx([("Saisie", lignes, {})]), refus=True)
    # --- fichiers abîmés
    bon = xlsx([("Saisie", lignes, {})])
    ajoute("xlsx-tronque-moitie", "a.xlsx", tronque(bon), refus=True)
    ajoute("xlsx-tronque-1-octet", "a.xlsx", bon[:-1], refus=True)
    ajoute("xlsx-pas-un-zip", "a.xlsx", b"Bonjour, je ne suis pas un classeur", refus=True)
    ajoute("xlsx-zip-bidon", "a.xlsx", zip_bidon(), refus=True)
    ajoute("xlsx-vide-0-octet", "a.xlsx", b"", refus=True)
    ajoute("xlsx-xml-casse", "a.xlsx", xlsx_xml_casse(bon), refus=True)
    ajoute("xlsx-feuille-manquante", "a.xlsx", xlsx_sans_feuille(bon), refus=True)
    ajoute("xlsx-csv-renomme", "a.xlsx", csv_octets(lignes), refus=True)
    ajoute("xlsm", "a.xlsm", bon)
    ajoute("xls-ancien", "a.xls", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 500, refus=True)
    ajoute("ods", "a.ods", zip_bidon(), refus=True)
    ajoute("pdf", "a.pdf", b"%PDF-1.4\n", refus=True)
    ajoute("sans-extension", "fichier", bon, refus=True)
    ajoute("nom-bizarre", "../../etc/passwd‮.xlsx", bon)
    ajoute("nom-tres-long", "x" * 300 + ".xlsx", bon)
    if gros:
        n = 100_000
        lignes_g = [[kk.code, oo.nom, ex, i] for i, (kk, oo) in zip(range(n), (d.cases[i % len(d.cases)] for i in range(n)))]
        ajoute("cent-mille-lignes", "gros.xlsx", xlsx_vite(E[:4], lignes_g), gros=True)
        ajoute("cent-mille-lignes-csv", "gros.csv", csv_octets([E[:4]] + lignes_g), gros=True)
        ajoute("cent-mille-lignes-vides", "gros.csv", csv_octets([E[:4]] + [["", "", "", ""]] * n + bons), gros=True)
    return cas


# ---------------------------------------------------------------- appels aux pages
class Resultat:
    def __init__(self, cible, nom, role):
        self.cible, self.nom, self.role = cible, nom, role
        self.problemes = []
        self.notes = []

    def probleme(self, texte):
        self.problemes.append(texte)

    def en_dict(self):
        return {"cible": self.cible, "cas": self.nom, "role": self.role, "problemes": self.problemes, "notes": self.notes}


def appel(res, client, etape, methode, url, **kw):
    try:
        r = getattr(client, methode)(url, **kw)
    except Exception as e:  # noqa: BLE001 — c'est justement ce que l'on cherche
        res.probleme(f"{etape}: exception {type(e).__name__}: {e} | {traceback.format_exc().splitlines()[-3:]}")
        return None
    if r.status_code >= 500:
        res.probleme(f"{etape}: statut {r.status_code}")
    return r


def textes_visibles(r):
    """Messages et erreurs montrés à la personne (messages Django, erreur d'analyse, motifs des lignes)."""
    textes = []
    if r is None:
        return textes
    ctx = r.context
    if ctx is None:
        return textes
    try:
        for m in ctx.get("messages", []) or []:
            textes.append(str(m))
    except Exception:  # noqa: BLE001
        pass
    a = ctx.get("analyse")
    if a is not None:
        if getattr(a, "erreur", ""):
            textes.append(str(a.erreur))
        for l in list(getattr(a, "lignes", []) or [])[:300]:
            for champ in ("motif", "echec"):
                if getattr(l, champ, ""):
                    textes.append(str(getattr(l, champ)))
    return textes


def verifier_textes(res, textes):
    for t in textes:
        if TECHNIQUE.search(t):
            res.probleme(f"message technique : {t[:200]!r}")


def reponses_cloturees():
    """Réponses des périodes dont toutes les campagnes sont clôturées : {(période, kpi, org): (valeur, texte, na, origine)}."""
    fermees = set(Campagne.objects.filter(statut=Campagne.Statut.CLOTUREE).values_list("periode_id", flat=True)) - \
        set(Campagne.objects.exclude(statut=Campagne.Statut.CLOTUREE).values_list("periode_id", flat=True))
    return {(p, k, o): reste for p, k, o, *reste in Reponse.objects.filter(periode_id__in=fermees).values_list(
        "periode_id", "kpi_id", "organisation_id", "valeur", "texte", "non_applicable", "origine")}


class Annuler(Exception):
    pass


def dans_une_transaction(fonction):
    """Exécute ``fonction`` puis annule tout ce qu'elle a écrit."""
    try:
        with transaction.atomic():
            fonction()
            raise Annuler
    except Annuler:
        pass
    connection.queries_log.clear()  # requêtes gardées en mode développement : la mémoire reste bornée sur 1 000 cas
    gc.collect()


def lancer_valeurs(cas, clients, d, resultats, garder=None):
    url = reverse("collecte:echanges_importer")
    for nom, fichier, octets, attente in cas:
        if garder:
            with open(os.path.join(garder, f"valeurs-{nom.replace('/', '_')[:60]}-{os.path.basename(fichier)[-12:]}"), "wb") as f:
                f.write(octets)
        for role in (["admin", "contributeur"] if not attente.get("gros") else ["admin", "contributeur"]):
            res = Resultat("valeurs", nom, role)
            client = clients[role]
            t0 = time.time()

            def un_cas():
                avant = etat()
                fermees_avant = reponses_cloturees()
                r = appel(res, client, "aperçu", "post", url, data={
                    "action": "verifier", "campagne": d.ouverte.pk, "fichier": SimpleUploadedFile(os.path.basename(fichier) or "f", octets)})
                if r is None:
                    return
                apres = etat()
                if differences(avant, apres):
                    res.probleme(f"l'aperçu a écrit : {differences(avant, apres)}")
                textes = textes_visibles(r)
                if r.status_code == 302:
                    r2 = appel(res, client, "aperçu (page suivante)", "get", r["Location"])
                    textes += textes_visibles(r2)
                verifier_textes(res, textes)
                a = r.context.get("analyse") if r.context else None
                refuse = a is None or bool(a.erreur)
                if attente.get("refus") and not refuse:
                    res.notes.append("attendu refusé, accepté")
                if refuse and not textes:
                    res.probleme("refusé sans message")
                if a is not None and a.rejets:
                    fichiers_rejets = {}
                    for fmt in ("xlsx", "csv"):
                        rr = appel(res, client, f"rejets {fmt}", "get", reverse("collecte:echanges_rejets") + ("?format=csv" if fmt == "csv" else ""))
                        if rr is None:
                            continue
                        if rr.status_code != 200:
                            res.probleme(f"rejets {fmt}: statut {rr.status_code}")
                            continue
                        fichiers_rejets[fmt] = b"".join(rr.streaming_content) if getattr(rr, "streaming", False) else rr.content
                    if "xlsx" in fichiers_rejets:
                        try:
                            wb = load_workbook(io.BytesIO(fichiers_rejets["xlsx"]), read_only=True)
                            if sum(1 for ws in wb.worksheets for row in ws.iter_rows(values_only=True) if any(row)) < 1:
                                res.probleme("fichier des rejets vide")
                        except Exception as e:  # noqa: BLE001
                            res.probleme(f"fichier des rejets illisible : {e}")
                    for fmt, contenu in fichiers_rejets.items():
                        # réimport du fichier des rejets : aperçu sans erreur, rien n'est accepté qui était refusé
                        avant2 = etat()
                        r3 = appel(res, client, f"réimport des rejets {fmt}", "post", url, data={
                            "action": "verifier", "campagne": d.ouverte.pk, "fichier": SimpleUploadedFile(f"rejets.{fmt}", contenu)})
                        if r3 is not None and r3.context and r3.context.get("analyse") is not None:
                            a3 = r3.context["analyse"]
                            if a3.erreur:
                                res.probleme(f"réimport des rejets {fmt} refusé : {a3.erreur}")
                            elif len(a3.rejets) + a3.compte("ignore") < len(a.rejets):
                                res.notes.append(f"réimport des rejets {fmt} : {len(a3.rejets)} rejets pour {len(a.rejets)}")
                        if differences(avant2, etat()):
                            res.probleme("le réimport des rejets (aperçu) a écrit")
                    # le dernier aperçu est celui des rejets : on redépose le fichier d'origine
                    appel(res, client, "aperçu (à nouveau)", "post", url, data={
                        "action": "verifier", "campagne": d.ouverte.pk, "fichier": SimpleUploadedFile(os.path.basename(fichier) or "f", octets)})
                    # correction dans l'aperçu (valeurs farfelues) : nouvel aperçu sans erreur
                    rc = appel(res, client, "corriger", "post", url, data={
                        "action": "corriger", "nb_rejets": "abc" if nom.endswith("0") else "3", "cle_0": a.rejets[0].cle,
                        "kpi_0": "\x00", "valeur_0": "1e999", "organisation_0": "<b>", "na_0": "on"})
                    if rc is not None and rc.status_code == 200:
                        verifier_textes(res, textes_visibles(rc))
                    # le fichier doit être redéposé : l'aperçu après correction l'a gardé
                avant_conf = etat()
                rc = appel(res, client, "confirmation", "post", url, data={"action": "confirmer"})
                if rc is None:
                    return
                textes_c = textes_visibles(rc)
                if rc.status_code == 302:
                    textes_c += textes_visibles(appel(res, client, "confirmation (page suivante)", "get", rc["Location"]))
                verifier_textes(res, textes_c)
                apres_conf = etat()
                ecrit = differences(avant_conf, apres_conf)
                if refuse and ecrit:
                    res.probleme(f"fichier refusé mais écrit : {ecrit}")
                fermees_apres = reponses_cloturees() if ecrit else fermees_avant
                changees = [c for c in set(fermees_avant) | set(fermees_apres) if fermees_avant.get(c) != fermees_apres.get(c)]
                if changees and role != "admin":
                    res.probleme(f"{len(changees)} valeur(s) écrites dans une campagne clôturée par {role}")
                if changees and role == "admin":
                    remplacees = [c for c in changees if c in fermees_avant and fermees_avant[c][3] == Reponse.Origine.SAISIE
                                  and (fermees_avant[c][0] is not None or fermees_avant[c][2])]
                    if remplacees:
                        res.probleme(f"{len(remplacees)} valeur(s) saisies dans l'outil remplacées dans une campagne clôturée")
                if rc.context and rc.context.get("analyse") is not None:
                    a2 = rc.context["analyse"]
                    if a is not None and not a.erreur and len(a2.rejets) != len(a.rejets):
                        res.notes.append(f"rejets différents entre aperçu ({len(a.rejets)}) et import ({len(a2.rejets)})")
                    res.notes.append(f"écrites={rc.context.get('ecrites')} rejets={len(a2.rejets)}")
            dans_une_transaction(un_cas)
            res.notes.append(f"{time.time() - t0:.1f} s")
            resultats.append(res)
            afficher(res)


def afficher(res):
    etat = "ÉCHEC" if res.problemes else "ok"
    print(f"[{etat:5}] {res.cible:12} {res.role:13} {res.nom[:60]:60} {' | '.join(res.problemes)[:400]}", flush=True)


# ---------------------------------------------------------------- configuration, organisations, paquet, traductions
def feuilles_de(octets):
    wb = load_workbook(io.BytesIO(octets))
    return wb


def classeur_octets(wb):
    t = io.BytesIO()
    wb.save(t)
    return t.getvalue()


def mutations_classeur(base, prefixe, refus_si_vide=True):
    """Variantes génériques d'un classeur exporté par l'outil : chaque onglet abîmé tour à tour. Générées au fur et à
    mesure (un classeur à la fois en mémoire)."""
    cas = []
    wb0 = feuilles_de(base)
    noms = wb0.sheetnames
    yield (f"{prefixe}-tel-quel", "a.xlsx", base, {})
    for nom in noms:
        def variante(fonction, etiquette, **attente):
            wb = feuilles_de(base)
            ws = wb[nom]
            try:
                fonction(wb, ws)
            except Exception as e:  # noqa: BLE001
                print("génération impossible", etiquette, e)
                return
            cas.append((f"{prefixe}-{nom}-{etiquette}", "a.xlsx", classeur_octets(wb), attente))

        variante(lambda wb, ws: ws.delete_rows(1, 1), "sans-entetes")
        variante(lambda wb, ws: ws.delete_cols(1, 1), "sans-colonne-1")
        variante(lambda wb, ws: ws.delete_cols(2, 1), "sans-colonne-2")
        variante(lambda wb, ws: ws.insert_cols(1) or ws.cell(1, 1, ws.cell(1, 3).value), "colonne-en-double")
        variante(lambda wb, ws: ws.move_range(f"A1:A{ws.max_row}", cols=ws.max_column + 1) or ws.delete_cols(1, 1), "colonnes-desordre")
        variante(lambda wb, ws: ws.merge_cells(start_row=2, start_column=1, end_row=min(4, max(2, ws.max_row)), end_column=2), "fusion")
        variante(lambda wb, ws: [ws.cell(r, 2, "=1/0") for r in range(2, min(ws.max_row, 6) + 1)], "formules")
        variante(lambda wb, ws: [ws.cell(r, 2, "#DIV/0!") for r in range(2, min(ws.max_row, 6) + 1)], "erreurs-excel")
        variante(lambda wb, ws: [ws.cell(r, c, datetime.datetime(2026, 1, 1)) for r in range(2, min(ws.max_row, 4) + 1)
                                 for c in range(1, min(ws.max_column, 8) + 1)], "dates")
        variante(lambda wb, ws: [ws.cell(r, c, True) for r in range(2, min(ws.max_row, 4) + 1)
                                 for c in range(1, min(ws.max_column, 8) + 1)], "booleens")
        variante(lambda wb, ws: [ws.cell(r, c, -1e308) for r in range(2, min(ws.max_row, 4) + 1)
                                 for c in range(1, min(ws.max_column, 8) + 1)], "nombres-immenses")
        variante(lambda wb, ws: [ws.cell(r, c, "x" * 5000) for r in range(2, min(ws.max_row, 3) + 1)
                                 for c in range(1, min(ws.max_column, 8) + 1)], "texte-long")
        variante(lambda wb, ws: [ws.cell(r, 1, str(ws.cell(r, 1).value or "").lower() + "  ") for r in range(2, ws.max_row + 1)],
                 "codes-minuscules-espaces")
        variante(lambda wb, ws: [ws.append([c.value for c in row]) for row in list(ws.iter_rows(min_row=2, max_row=min(ws.max_row, 6)))],
                 "doublons")

        def contradictoires(wb, ws):
            for row in list(ws.iter_rows(min_row=2, max_row=min(ws.max_row, 6))):
                valeurs = [c.value for c in row]
                if len(valeurs) > 1:
                    valeurs[1] = f"{valeurs[1]}-autre"
                ws.append(valeurs)
        variante(contradictoires, "doublons-contradictoires")
        variante(lambda wb, ws: ws.delete_rows(2, ws.max_row), "zero-ligne")
        variante(lambda wb, ws: setattr(ws, "sheet_state", "hidden") if len(wb.sheetnames) > 1 else None, "onglet-cache")
        variante(lambda wb, ws: [ws.insert_rows(3) for _ in range(5)], "lignes-vides")
        variante(lambda wb, ws: [ws.cell(r, 1, None) for r in range(2, ws.max_row + 1)], "premiere-colonne-vide")
        variante(lambda wb, ws: [wb.remove(wb[n]) for n in wb.sheetnames if n != ws.title], "seul-onglet")
        variante(lambda wb, ws: wb.remove(ws) if len(wb.sheetnames) > 1 else None, "onglet-retire")

        def melange(wb, ws):
            lignes = [[c.value for c in row] for row in ws.iter_rows(min_row=2)]
            random.Random(3).shuffle(lignes)
            ws.delete_rows(2, ws.max_row)
            for l in lignes:
                ws.append(l)
        variante(melange, "lignes-melangees")
        yield from cas
        cas.clear()
    cas.append((f"{prefixe}-tronque", "a.xlsx", tronque(base), {"refus": True}))
    cas.append((f"{prefixe}-pas-un-zip", "a.xlsx", b"PK\x03\x04 rien", {"refus": True}))
    cas.append((f"{prefixe}-zip-bidon", "a.xlsx", zip_bidon(), {"refus": True}))
    cas.append((f"{prefixe}-vide", "a.xlsx", xlsx([("Feuil1", [], {})]), {"refus": True}))
    cas.append((f"{prefixe}-xml-casse", "a.xlsx", xlsx_xml_casse(base), {"refus": True}))
    cas.append((f"{prefixe}-feuille-manquante", "a.xlsx", xlsx_sans_feuille(base), {"refus": True}))
    # en CSV : premier onglet seulement, sous plusieurs encodages
    wb = feuilles_de(base)
    for nom in noms[:6]:
        lignes = [[("" if c is None else c) for c in row] for row in wb[nom].iter_rows(values_only=True)]
        for enc in ("utf-8-sig", "latin-1", "utf-16"):
            cas.append((f"{prefixe}-csv-{nom}-{enc}", "a.csv", csv_octets(lignes, encodage=enc), {}))
        cas.append((f"{prefixe}-csv-{nom}-virgule", "a.csv", csv_octets(lignes, sep=","), {}))
    cas.append((f"{prefixe}-csv-vide", "a.csv", b"", {"refus": True}))
    cas.append((f"{prefixe}-csv-binaire", "a.csv", bytes(random.Random(2).randrange(256) for _ in range(3000)), {"refus": True}))
    yield from cas


def lancer_generique(cible, cas, client, url_verifier, donnees_verifier, url_confirmer, donnees_confirmer, resultats, garder=None,
                     confirmations=None):
    for nom, fichier, octets, attente in cas:
        if garder:
            with open(os.path.join(garder, f"{cible}-{nom[:70]}{os.path.splitext(fichier)[1]}"), "wb") as f:
                f.write(octets)
        res = Resultat(cible, nom, "admin")
        t0 = time.time()

        def un_cas():
            avant = etat()
            r = appel(res, client, "aperçu", "post", url_verifier, data={**donnees_verifier, "fichier": SimpleUploadedFile(fichier, octets)})
            if r is None:
                return
            textes = textes_visibles(r)
            if r.status_code == 302:
                r2 = appel(res, client, "aperçu (page suivante)", "get", r["Location"])
                textes += textes_visibles(r2)
            verifier_textes(res, textes)
            ecrit = differences(avant, etat())
            ecrit = [t for t in ecrit if t != "collecte_journal" or cible != "paquet"]
            if ecrit:
                res.probleme(f"l'aperçu a écrit : {ecrit}")
            refuse = r.status_code == 302 or (r.context is not None and getattr(r.context.get("analyse"), "erreur", ""))
            for donnees in (confirmations or [donnees_confirmer]):
                avant_c = etat()
                rc = appel(res, client, "confirmation", "post", url_confirmer, data=donnees)
                if rc is None:
                    return
                tc = textes_visibles(rc)
                if rc.status_code == 302:
                    tc += textes_visibles(appel(res, client, "confirmation (page suivante)", "get", rc["Location"]))
                verifier_textes(res, tc)
                ecrit = differences(avant_c, etat())
                if refuse and ecrit:
                    res.probleme(f"fichier refusé mais écrit : {ecrit}")
                res.notes.append(f"écrit : {','.join(ecrit) or 'rien'}")
        dans_une_transaction(un_cas)
        res.notes.append(f"{time.time() - t0:.1f} s")
        resultats.append(res)
        afficher(res)


def paquets_json(base):
    """Paquets JSON abîmés : chaque rubrique d'un vrai paquet remplacée par une valeur du mauvais type, éléments
    abîmés un à un, clés retirées, texte qui n'est pas du JSON ou pas de l'UTF-8."""
    d0 = json.loads(base.decode("utf-8"))
    yield ("json-tel-quel", "a.json", base, {})
    mauvais = {"texte": "abc", "nombre": 12, "liste": [1, "x", None], "nul": None, "objet": {"a": {"b": []}}, "booleen": True,
               "immense": "x" * 100000}

    def copie():
        return json.loads(base.decode("utf-8"))

    for cle in list(d0):
        for nom, v in mauvais.items():
            d = copie()
            d[cle] = v
            yield (f"json-{cle}-{nom}", "a.json", json.dumps(d).encode(), {})
        d = copie()
        del d[cle]
        yield (f"json-sans-{cle}", "a.json", json.dumps(d).encode(), {})
        if isinstance(d0[cle], list) and d0[cle]:
            for nom, v in mauvais.items():
                d = copie()
                d[cle] = [v] + d[cle][1:]
                yield (f"json-{cle}[0]-{nom}", "a.json", json.dumps(d).encode(), {})
            premier = d0[cle][0]
            if isinstance(premier, dict):
                for champ in list(premier):
                    for nom in ("texte", "nombre", "liste", "nul", "objet"):
                        d = copie()
                        d[cle][0][champ] = mauvais[nom]
                        yield (f"json-{cle}[0].{champ}-{nom}", "a.json", json.dumps(d).encode(), {})
        if isinstance(d0[cle], dict):
            for champ in list(d0[cle]):
                for nom in ("texte", "nombre", "liste", "nul", "objet"):
                    d = copie()
                    d[cle][champ] = mauvais[nom]
                    yield (f"json-{cle}.{champ}-{nom}", "a.json", json.dumps(d).encode(), {})
    latin1 = json.dumps({"référentiel": 1}, ensure_ascii=False).encode("latin-1")
    for nom, octets in (("vide", b""), ("pas-json", b"bonjour"), ("liste", b"[1,2]"), ("nul", b"null"), ("latin1", latin1),
                        ("profond", b"[" * 5000 + b"]" * 5000), ("utf16", json.dumps(d0).encode("utf-16")), ("tronque", base[: len(base) // 2])):
        yield (f"json-{nom}", "a.json", octets, {"refus": True})


def racine():
    """Nom de l'organisation au sommet de l'arbre de la base essayée (« Exemplia Groupe » dans la démo)."""
    from referentiel.models import Organisation

    return Organisation.objects.filter(parent__isnull=True).values_list("nom", flat=True).first() or "Groupe"


def arbres_organisations():
    """Textes collés dans « Plusieurs organisations » (saisie décalée ou collage depuis Excel)."""
    return [
        ("vide", ""), ("espaces", "   \n\t\n"), ("simple", "Nouvelle\n\tSite neuf"), ("tabulations-folles", "\t\t\t\tX\n\tY"),
        ("doublon", "France\n\tParis\n\tParis"), ("existant", f"{racine()}\n\tFrance"), ("cycle", "A\n\tB\n\t\tA"),
        ("beaucoup", "\n".join(f"Org {i}" for i in range(40))), ("nom-long", "x" * 500), ("nul", "A\x00B"),
        ("html", "<script>alert(1)</script>"), ("excel-colle", "Pays\tEntité\tSite\nFrance\tVP X\tSite X\n"),
        ("excel-colonnes-vides", "\t\t\n\t\t\n"), ("crlf", "Racine X\r\n\tSite Y\r\n"), ("unicode", "Zürich ☃\n\t東京"),
        ("profondeur", "\n".join("\t" * i + f"N{i}" for i in range(12))), ("formule", "=1+1\n\t+cmd"),
    ]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", default="valeurs,config,organisations,paquet,paquet-json,traductions")
    ap.add_argument("--big", action="store_true", help="also the 100,000-line files (several minutes)")
    ap.add_argument("--keep-files", default="", help="folder where the generated files are written")
    ap.add_argument("--report", default="", help="JSON report")
    ap.add_argument("--filter", default="", help="only the cases whose name contains this text")
    args = ap.parse_args()
    if not os.environ.get("DATA_DIR") and not os.environ.get("DOSSIER_DONNEES"):
        sys.exit("Set DATA_DIR to a COPY of a demo database (see --help): this tool must not run on local-data/ or a real installation.")
    from django.conf import settings

    settings.SESSION_ENGINE = "django.contrib.sessions.backends.cache"  # sessions hors base : toute écriture en base compte
    d = Demo()
    clients = {}
    for role, u in (("admin", d.admin), ("contributeur", d.contributeur), ("validateur", d.validateur)):
        c = Client()
        c.force_login(u)
        clients[role] = c
    if args.keep_files:
        os.makedirs(args.keep_files, exist_ok=True)
    resultats = []
    cibles = set(args.only.split(","))

    def filtre(cas):
        return (c for c in cas if args.filter in c[0])  # au fur et à mesure : mémoire bornée

    if "valeurs" in cibles:
        lancer_valeurs(filtre(valeurs_cas(d, args.big)), clients, d, resultats, args.keep_files)
    admin = clients["admin"]
    if "config" in cibles or "organisations" in cibles:
        base = admin.get(reverse("collecte:admin_fichiers") + "?telecharger=xlsx").content
        url = reverse("collecte:admin_fichiers")
        cas = mutations_classeur(base, "config")
        if "organisations" in cibles:  # l'onglet Organisations seul, abîmé
            wb = feuilles_de(base)
            for n in [n for n in wb.sheetnames if n not in ("Organisations",)]:
                wb.remove(wb[n])
            cas = itertools.chain(cas, mutations_classeur(classeur_octets(wb), "organisations"))
        lancer_generique("config", filtre(cas), admin, url, {"action": "verifier", "desactiver_absents": "on"}, url, {"action": "confirmer"},
                         resultats, args.keep_files)
    if "organisations" in cibles:
        url = reverse("collecte:admin_organisations_plusieurs")
        for nom, texte in arbres_organisations():
            if args.filter not in nom:
                continue
            res = Resultat("org-collees", nom, "admin")

            def un_cas(texte=texte, res=res):
                for action in ("apercu", "creer"):
                    r = appel(res, admin, action, "post", url, data={"arbre": texte, "action": action})
                    if r is not None and r.status_code == 200 and r.context:
                        verifier_textes(res, [str(e) for e in r.context.get("erreurs_arbre") or []])
            dans_une_transaction(un_cas)
            resultats.append(res)
            afficher(res)
    if "paquet" in cibles:
        ref = d.referentiel
        base = admin.get(reverse("parametres:paquet_exporter", args=[ref.code])).content
        url = reverse("parametres:paquet_importer")
        lancer_generique("paquet", filtre(mutations_classeur(base, "paquet")), admin, url, {"action": "verifier"}, url,
                         {"action": "confirmer"}, resultats, args.keep_files,
                         confirmations=[{"action": "confirmer"}, {"action": "confirmer", "mode": "nouveau", "code": "PIEGE"}])
    if "paquet-json" in cibles:
        ref = d.referentiel
        base = admin.get(reverse("parametres:paquet_exporter", args=[ref.code]) + "?format=json").content
        url = reverse("parametres:paquet_importer")
        lancer_generique("paquet-json", filtre(paquets_json(base)), admin, url, {"action": "verifier"}, url,
                         {"action": "confirmer"}, resultats, args.keep_files,
                         confirmations=[{"action": "confirmer"}, {"action": "confirmer", "mode": "nouveau", "code": "PIEGE"}])
    if "traductions" in cibles:
        for code in ("en", "toutes"):
            base = admin.get(reverse("parametres:traductions_export", args=[code])).content
            url = reverse("parametres:traductions_import", args=[code])
            lancer_generique(f"traductions-{code}", filtre(mutations_classeur(base, f"trad-{code}")), admin, url, {}, url,
                             {"action": "appliquer"}, resultats, args.keep_files)
    echecs = [r for r in resultats if r.problemes]
    print(f"\n{len(resultats)} cases, {len(echecs)} failed")
    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            json.dump([r.en_dict() for r in resultats], f, ensure_ascii=False, indent=1, default=str)
    sys.exit(1 if echecs else 0)


if __name__ == "__main__":
    main()
