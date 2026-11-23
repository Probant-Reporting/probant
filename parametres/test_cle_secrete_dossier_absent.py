"""Clé secrète : un dossier des données qui n'existe pas est dit « absent », pas « non inscriptible »."""
import tempfile
from pathlib import Path

from django.test import SimpleTestCase

from parametres.aides_tests.hebergement import reglages


class DossierDesDonneesAbsentTests(SimpleTestCase):
    def test_message_dit_que_le_dossier_n_existe_pas(self):
        with tempfile.TemporaryDirectory() as t:
            absent = Path(t) / "inexistant"
            with self.assertRaises(AssertionError) as ctx:
                reglages({"DOSSIER_DONNEES": str(absent)}, "print(json.dumps(s.SECRET_KEY))")
        message = str(ctx.exception)
        self.assertIn("does not exist", message)
        self.assertNotIn("must be writable", message)

    def test_dossier_present_mais_non_inscriptible_garde_l_ancien_message(self):
        with tempfile.TemporaryDirectory() as t:
            fichier = Path(t) / "un-fichier"
            fichier.write_text("x")  # « dossier » qui est un fichier : la clé ne peut pas y être créée
            with self.assertRaises(AssertionError) as ctx:
                reglages({"DOSSIER_DONNEES": str(fichier)}, "print(json.dumps(s.SECRET_KEY))")
        self.assertNotIn("does not exist", str(ctx.exception))
