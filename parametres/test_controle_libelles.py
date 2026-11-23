"""Contrôle des fichiers de langue de l'interface, pour toute langue présente dans ``libelles/`` :
mêmes clés, mêmes paramètres, mêmes balises, mêmes formes que l'anglais ; aucune mention de « RSE » ; réglages de format de
chaque langue ; une langue incomplète n'est jamais proposée. Ajouter une langue ne demande aucun code : ces tests la prennent
en charge dès que ses fichiers existent."""
import json
import re
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase, TestCase

from collecte.periodes import MOIS
from collecte.templatetags.collecte import avec_pourcent, nombre, separateurs
from parametres import controle_libelles as C
from parametres import langues as L
from parametres import libelles as LB
from parametres import zones_langue as Z

PRESENTES = C.langues_presentes()


class ToutesLesLanguesPresentesTests(SimpleTestCase):
    def test_langues_presentes_comprennent_le_socle(self):
        self.assertEqual(PRESENTES[0], "en")
        self.assertTrue({"fr", "en", "es"} <= set(PRESENTES))

    def test_chaque_fichier_present_est_exact(self):
        """Chaque fichier de langue présent a les clés de l'anglais, ni plus ni moins, mêmes paramètres, balises et formes,
        aucun texte vide. Une langue en cours de traduction (des zones sans fichier) n'est pas proposée : voir
        ``test_langues_proposees_sont_les_langues_completes``."""
        for langue in PRESENTES:
            with self.subTest(langue=langue):
                p = [e for e in C.problemes(langue) if e[0] != "fichier"]
                self.assertEqual(p[:8], [], f"{len(p)} écart(s) : voir qa/translation_check.py check {langue}")

    def test_langues_proposees_sont_les_langues_completes(self):
        completes = [c for c in PRESENTES if not C.problemes(c)]
        self.assertEqual(LB.langues_disponibles(), completes)
        self.assertTrue({"fr", "en", "es", "de"} <= set(completes), f"complètes : {completes}")

    def test_noms_de_fichiers_et_balises_permises(self):
        for p in C.dossier().glob("*.json"):
            zone, langue, _ = p.name.split(".")
            with self.subTest(fichier=p.name):
                self.assertIn(zone, Z.ZONES)
                self.assertRegex(langue, r"^[a-z]{2,3}(-[A-Z]{2})?$")
                for cle, texte in json.loads(p.read_text(encoding="utf-8")).items():
                    self.assertTrue(set(C.balises(texte)) <= C.BALISES_PERMISES, f"{cle} : balise non permise")
                    self.assertTrue(cle.startswith(Z.prefixes(zone)), f"{cle} : préfixe hors de la zone {zone}")

    def test_aucune_mention_de_rse(self):
        """« RSE » n'apparaît jamais dans l'interface (outil générique), dans aucune langue."""
        for p in C.dossier().glob("*.json"):
            for cle, texte in json.loads(p.read_text(encoding="utf-8")).items():
                for t in C.textes(texte):
                    self.assertIsNone(re.search(r"\bRSE\b", t), f"{p.name} {cle}")


class ReglagesDeLangueTests(TestCase):
    """Ce qui change d'une langue à l'autre vit dans ses fichiers : séparateurs, signe %, pluriel, nom, mois."""

    def test_reglages_de_format_presents_partout(self):
        for langue in PRESENTES:
            t = LB.table(langue)
            with self.subTest(langue=langue):
                self.assertIn("{valeur}", t["format.pourcent"])
                self.assertIn(t["format.decimal"], (",", "."))
                self.assertIn(t["format.zero_singulier"], ("0", "1"))
                self.assertNotEqual(t["format.milliers"], t["format.decimal"])

    def test_nombres_et_pourcentages_suivent_les_fichiers(self):
        for langue in PRESENTES:
            milliers, decimale = separateurs(langue)
            with self.subTest(langue=langue):
                self.assertEqual(nombre(1234.5, 1, langue), f"1{milliers}234{decimale}5")
                self.assertEqual(avec_pourcent("12", langue), LB.table(langue)["format.pourcent"].replace("{valeur}", "12"))

    def test_allemand(self):
        """Allemand : 1.234,5 · 12,5 % (espace fine insécable) · « 0 » au pluriel · date en toutes lettres."""
        self.assertEqual(separateurs("de"), (".", ","))
        self.assertEqual(nombre(1234.5, 1, "de"), "1.234,5")
        self.assertEqual(avec_pourcent("12,5", "de"), "12,5\u202f%")
        self.assertIn("de", L.langues_interface())
        with L.activer_interface("de"):
            self.assertEqual(LB.libelle("cadre.menu.saisie"), "Datenerfassung")
            self.assertEqual(LB.libelle("visu.kpi.nb", n=0), "0 KPIs")
            self.assertEqual(LB.libelle("visu.kpi.nb", n=1), "1 KPI")
            from collecte.templatetags.collecte import date_longue
            import datetime

            self.assertEqual(date_longue(datetime.date(2026, 3, 4)), "4. März 2026")

    def test_pluriel_selon_la_langue(self):
        un = {"one": "x", "other": "y"}
        for langue in PRESENTES:
            zero_un_singulier = LB.table(langue)["format.zero_singulier"] == "1"
            with self.subTest(langue=langue):
                self.assertEqual(LB.forme(un, 1, langue), "x")
                self.assertEqual(LB.forme(un, 2, langue), "y")
                self.assertEqual(LB.forme(un, 0, langue), "x" if zero_un_singulier else "y")
        self.assertEqual(LB.forme(un, 0, "fr"), "x")  # français : 0 et 1 au singulier
        self.assertEqual(LB.forme(un, 0, "en"), "y")

    def test_noms_de_langue_dans_chaque_langue(self):
        """Chaque langue présente a son nom (« Deutsch ») et son nom dans toutes les autres (« German », « allemand »)."""
        for langue in PRESENTES:
            for autre in PRESENTES:
                with self.subTest(langue=langue, dans=autre):
                    self.assertTrue(LB.table(autre).get(f"commun.langue_nom.{langue}"))
            self.assertTrue(LB.table(langue).get("cadre.langue.nom"))

    def test_mois_de_chaque_langue(self):
        for langue in PRESENTES:
            with self.subTest(langue=langue):
                self.assertEqual(len(MOIS[langue]), 12)
                self.assertEqual(len(set(MOIS[langue])), 12)


class LanguesProposeesTests(TestCase):
    """Une langue incomplète n'est jamais proposée : le contrôle est automatique, sans réglage à la main."""

    def setUp(self):
        self.dossier = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dossier, ignore_errors=True)
        for p in C.dossier().glob("*.en.json"):
            shutil.copy(p, self.dossier / p.name)
            shutil.copy(p, self.dossier / p.name.replace(".en.", ".xx."))
        self.addCleanup(self.vider)
        patch = mock.patch.object(C, "dossier", return_value=self.dossier)
        patch.start()
        self.addCleanup(patch.stop)
        self.vider()

    @staticmethod
    def vider():
        LB.langues_disponibles.cache_clear()
        LB.table.cache_clear()

    def test_langue_complete_proposee(self):
        self.assertEqual(C.problemes("xx"), [])
        self.assertIn("xx", LB.langues_disponibles())
        self.assertIn("xx", L.langues_interface())

    def test_cle_manquante_ou_fichier_absent(self):
        f = self.dossier / "saisie.xx.json"
        d = json.loads(f.read_text(encoding="utf-8"))
        cle = next(iter(d))
        del d[cle]
        f.write_text(json.dumps(d), encoding="utf-8")
        self.assertEqual([(t, z, c) for t, z, c, _ in C.problemes("xx")], [("manquante", "saisie", cle)])
        self.vider()
        self.assertNotIn("xx", LB.langues_disponibles())
        self.assertNotIn("xx", L.langues_interface())
        (self.dossier / "mcp.xx.json").unlink()
        self.assertIn(("fichier", "mcp", "", "mcp.xx.json"), C.problemes("xx"))

    def test_parametre_balise_et_forme_differents(self):
        f = self.dossier / "cadre.xx.json"
        d = json.loads(f.read_text(encoding="utf-8"))
        avec_param = next(k for k, v in d.items() if isinstance(v, str) and "{" in v)
        pluriel = next(k for k, v in d.items() if isinstance(v, dict))
        d[avec_param] = "sans paramètre"
        d[pluriel] = "pas de pluriel"
        f.write_text(json.dumps(d), encoding="utf-8")
        g = self.dossier / "admin.xx.json"
        e = json.loads(g.read_text(encoding="utf-8"))
        avec_balise = next(k for k, v in e.items() if isinstance(v, str) and "<b>" in v)
        e[avec_balise] = e[avec_balise].replace("<b>", "").replace("</b>", "")
        g.write_text(json.dumps(e), encoding="utf-8")
        types = {(t, c) for t, _, c, _ in C.problemes("xx")}
        self.assertEqual(types, {("parametres", avec_param), ("balises", avec_balise), ("forme", pluriel)})

    def test_langue_incomplete_jamais_choisie_par_une_personne(self):
        (self.dossier / "mcp.xx.json").unlink()
        self.vider()
        self.assertEqual(L.interface_de("xx"), L.interface_de(""))
        self.assertNotIn("xx", LB.candidates("xx"))
        self.assertEqual(LB.libelle("cadre.menu.saisie", "xx"), LB.libelle("cadre.menu.saisie", "en"))
