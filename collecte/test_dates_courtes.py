"""Date courte affichée : une seule fonction (``collecte/dates_courtes.py``), un format par langue (clé « format.date_courte »
des fichiers de langue, comme « format.decimal »). Les formats d'échange (fichiers à réimporter, ISO, noms de fichiers) ne
passent pas par elle : la liste de ce qui reste en jj/mm/aaaa à dessein est dans ce test."""
import datetime
import re
from pathlib import Path

from django.template import Context, Template
from django.test import SimpleTestCase
from django.utils import timezone

from parametres import langues as L

from . import dates_courtes as DC

RACINE = Path(__file__).resolve().parent.parent
JOUR = datetime.date(2026, 3, 1)
ATTENDU = {"fr": "01/03/2026", "en": "01 Mar 2026", "es": "01/03/2026", "de": "01.03.2026", "it": "01/03/2026",
           "nl": "01-03-2026", "pt": "01/03/2026"}

# Formats d'échange gardés en jj/mm/aaaa : ils se relisent à l'import ou sont écrits dans un fichier échangé.
GARDES = {
    "collecte/fichiers.py",  # cellules lues à l'import ; CSV « fr » (jj/mm/aaaa) ou « intl » (ISO), choix de l'exportateur
    "collecte/configuration.py",  # colonne « jour » du classeur de configuration, relue à l'import (formats acceptés ligne 239 et suivantes)
    "collecte/paquets/extraction.py",  # champ « exporte_le » du paquet d'échange de référentiel
    "collecte/paquets/application.py",  # note d'origine enregistrée avec le référentiel importé
}


class DateCourteTests(SimpleTestCase):
    def test_une_date_par_langue(self):
        for langue, attendu in ATTENDU.items():
            self.assertEqual(DC.date_courte(JOUR, langue), attendu, langue)

    def test_date_et_heure_en_heure_locale(self):
        quand = datetime.datetime(2026, 3, 1, 23, 30, tzinfo=datetime.timezone.utc)
        local = timezone.localtime(quand)
        self.assertEqual(DC.date_heure_courte(quand, "de"), f"{local:%d.%m.%Y} {local:%H:%M}")

    def test_vide(self):
        self.assertEqual((DC.date_courte(None), DC.date_courte(""), DC.date_heure_courte(None)), ("", "", ""))

    def test_filtres_de_gabarit_suivent_la_langue_de_l_interface(self):
        modele = Template("{% load collecte %}{{ j|date_courte }}|{{ j|date_heure_courte }}")
        with L.activer_interface("de"):
            sortie = modele.render(Context({"j": datetime.date(2026, 3, 1)}))
        self.assertEqual(sortie.split("|")[0], "01.03.2026")
        with L.activer_interface("fr"):
            self.assertEqual(modele.render(Context({"j": datetime.date(2026, 3, 1)})).split("|")[0], "01/03/2026")


class AucunFormatCodeEnDurTests(SimpleTestCase):
    """Aucun gabarit ni code de l'outil n'écrit une date courte en dur : tout passe par ``dates_courtes``."""

    def test_gabarits(self):
        restes = []
        for chemin in RACINE.rglob("*.html"):
            if any(p in chemin.relative_to(RACINE).parts for p in ("node_modules", ".claude", "staticfiles", "local-data")):
                continue
            for n, ligne in enumerate(chemin.read_text(encoding="utf-8").splitlines(), 1):
                if re.search(r"date:\"d/m/Y|date:'d/m/Y", ligne):
                    restes.append(f"{chemin.relative_to(RACINE)}:{n}")
        self.assertEqual(restes, [])

    def test_code_python(self):
        restes = []
        for chemin in RACINE.rglob("*.py"):
            rel = str(chemin.relative_to(RACINE))
            if (any(p in chemin.relative_to(RACINE).parts for p in ("migrations", "node_modules", ".claude", "qa", "aides_tests"))
                    or chemin.name.startswith("test_") or rel in GARDES or rel.endswith("dates_courtes.py")):
                continue
            for n, ligne in enumerate(chemin.read_text(encoding="utf-8").splitlines(), 1):
                if re.search(r"%d/%m/%Y|:%d/%m/%Y\}", ligne):
                    restes.append(f"{rel}:{n}")
        self.assertEqual(restes, [])

