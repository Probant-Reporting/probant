"""Garde-fou de l'open source sur tout le dépôt : aucun fichier (code, gabarits, libellés, documentation, contenu des
classeurs xlsx et autres archives zip) ne contient un mot ou une couleur de la liste interdite, tenue hors du dépôt
(``parametres/aides_tests/interdits.py``, variable ``PROBANT_FORBIDDEN``). Sans la liste : sauté. Un échec ne donne que
le chemin du fichier, jamais le mot."""
import unittest
import zipfile
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from .aides_tests import interdits as INTERDITS

RACINE = Path(settings.BASE_DIR)
EXCLUS = {".git", "node_modules", "local-data", "staticfiles", "resources", "__pycache__", "worktrees", ".venv", "venv"}


def fichiers():
    for p in sorted(RACINE.rglob("*")):
        if p.is_file() and not EXCLUS & set(p.relative_to(RACINE).parts):
            yield p


def textes(chemin):
    """[(où, texte)] : le fichier s'il est du texte, sinon le contenu de chaque membre d'une archive zip."""
    brut = chemin.read_bytes()
    if b"\x00" not in brut[:8000]:
        return [("", brut.decode("utf-8", "replace"))]
    if zipfile.is_zipfile(chemin):
        with zipfile.ZipFile(chemin) as z:
            return [(f":{n}", z.read(n).decode("utf-8", "replace")) for n in z.namelist()] + [(":noms", " ".join(z.namelist()))]
    return []


@unittest.skipUnless(INTERDITS.present(), INTERDITS.SAUTE)
class DepotSansNomInterditTests(SimpleTestCase):
    def test_aucun_fichier(self):
        mots, couleurs = INTERDITS.interdits()
        fautifs = []
        for chemin in fichiers():
            rel = str(chemin.relative_to(RACINE))
            if INTERDITS.nombre_trouves(rel, mots, set()):
                fautifs.append(f"{rel} (nom du fichier)")
            for ou, texte in textes(chemin):
                if INTERDITS.nombre_trouves(texte, mots, couleurs):
                    fautifs.append(rel + ou)
        self.assertEqual(fautifs, [])
