"""Contrôle « on peut sauter des versions » (qa/update_from_published.py) : les versions publiées se lisent dans
``CHANGELOG.md`` (titre daté), donc une nouvelle version publiée est prise toute seule."""
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from qa import update_from_published as UP

JOURNAL = """# Release notes

## 3.10.0 — 2031-02-03

### Highlights

- text

## 4.0.0 — Unreleased

- not published yet

## 3.9.1 - 2031-01-02

## 3.2.0 — 2030-12-30
"""


class VersionsPubliees(SimpleTestCase):

    def test_titres_dates_seulement_dans_l_ordre_des_numeros(self):
        # 3.10.0 après 3.9.1 (ordre des numéros, pas des lettres) ; le titre sans date n'est pas publié
        self.assertEqual(UP.versions_publiees(JOURNAL), ["3.2.0", "3.9.1", "3.10.0"])

    def test_texte_sans_titre(self):
        self.assertEqual(UP.versions_publiees("# Release notes\n\nrien\n"), [])

    def test_une_ligne_de_texte_n_est_pas_un_titre(self):
        self.assertEqual(UP.versions_publiees("La version 3.4.5 — 2031-01-01 est citée dans une phrase.\n"), [])

    def test_le_journal_du_depot_a_au_moins_une_version_et_la_version_courante(self):
        racine = Path(settings.BASE_DIR)
        versions = UP.versions_publiees((racine / "CHANGELOG.md").read_text(encoding="utf-8"))
        self.assertTrue(versions)
        courante = (racine / "VERSION").read_text(encoding="utf-8").strip()
        self.assertIn(courante, versions, "la version courante doit avoir son titre daté dans CHANGELOG.md")
