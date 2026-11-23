"""Fichier de langue abîmé (``libelles.langues_disponibles``, ``controle_libelles.problemes``) : une langue autre que
l'anglais et le français dont un fichier n'est pas du JSON valide, ou dont une valeur n'est ni un texte ni un pluriel,
n'est plus proposée, et l'outil reste debout (même la page de connexion) ; ``manage.py check`` le signale. L'anglais ou le
français abîmé reste une erreur franche (``check`` en erreur, le démarrage s'arrête)."""
import json
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from django.core import checks
from django.test import TestCase, override_settings
from django.urls import reverse

from . import controle_libelles as C
from . import libelles as LB

ORIGINAUX = Path(__file__).resolve().parent.parent / "libelles"


class FichierDeLangueAbimeTests(TestCase):
    def setUp(self):
        self.racine = Path(tempfile.mkdtemp())
        shutil.copytree(ORIGINAUX, self.racine / "libelles")
        self.addCleanup(shutil.rmtree, self.racine, ignore_errors=True)
        p = mock.patch.object(C, "RACINE", self.racine)
        p.start()
        self.addCleanup(p.stop)
        r = override_settings(BASE_DIR=self.racine)
        r.enable()
        self.addCleanup(r.disable)
        self.vider()
        self.addCleanup(self.vider)

    def vider(self):
        LB.table.cache_clear()
        LB.langues_disponibles.cache_clear()

    def abimer(self, langue, contenu=None, valeur=None, zone="cadre"):
        shutil.copytree(ORIGINAUX, self.racine / "libelles", dirs_exist_ok=True)  # cas précédent effacé
        p = self.racine / "libelles" / f"{zone}.{langue}.json"
        if valeur is not None:
            d = json.loads(p.read_text(encoding="utf-8"))
            d[next(iter(d))] = valeur
            contenu = json.dumps(d)
        p.write_text(contenu, encoding="utf-8")
        self.vider()

    def messages_check(self):
        return [m for m in checks.run_checks() if m.id and m.id.startswith("parametres.L")]

    def test_langue_abimee_n_est_plus_proposee_et_l_outil_reste_debout(self):
        self.assertIn("de", LB.langues_disponibles())
        for motif, abimer in (("JSON invalide", {"contenu": '{"cadre.x": "a",'}),
                              ("nombre", {"valeur": 3}),
                              ("liste", {"valeur": ["a"]}),
                              ("pluriel non texte", {"valeur": {"one": 1, "other": "x"}}),
                              ("pas un dictionnaire", {"contenu": '["a"]'})):
            with self.subTest(motif):
                self.abimer("de", **abimer)
                proposees = LB.langues_disponibles()
                self.assertNotIn("de", proposees)
                self.assertTrue({"en", "fr", "es"} <= set(proposees))
                self.assertEqual(self.client.get(reverse("login"), follow=True).status_code, 200)
                # repli habituel : langue par défaut de l'installation (le français ici)
                self.assertEqual(LB.libelle("cadre.deconnexion", "de"), LB.libelle("cadre.deconnexion", "fr"))
                avertis = self.messages_check()
                self.assertEqual([m.level for m in avertis], [checks.WARNING], avertis)
                self.assertIn("cadre.de.json", avertis[0].msg)
                shutil.copy(ORIGINAUX / "cadre.de.json", self.racine / "libelles")
                self.vider()

    def test_anglais_ou_francais_abime_erreur_franche(self):
        for langue in ("en", "fr"):
            with self.subTest(langue):
                self.abimer(langue, contenu='{"cadre.x": ')
                with self.assertRaises(ValueError):
                    LB.langues_disponibles()
                erreurs = self.messages_check()
                self.assertTrue(erreurs and all(m.level == checks.ERROR for m in erreurs), erreurs)
                shutil.copy(ORIGINAUX / f"cadre.{langue}.json", self.racine / "libelles")
                self.vider()

    def test_fichiers_intacts_rien_a_signaler(self):
        self.assertEqual(self.messages_check(), [])
