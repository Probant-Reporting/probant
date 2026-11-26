"""Version tout-en-un construite avec ``--data`` (``portable/build_package.py``) : le registre commun copié ne garde ni
le serveur d'e-mails, ni la destination de la copie externe, ni le réglage et les liens de la connexion d'entreprise,
ni l'état des alertes et de la copie (hôtes, identifiants, « sub » des personnes, secrets chiffrés). Chaque table du
registre est classée explicitement, vidée ou gardée : une table ajoutée plus tard au registre et non classée fait
échouer ce test."""
import shutil
import sqlite3
import tempfile
from pathlib import Path

from django.apps import apps
from django.test import SimpleTestCase

from espaces.routeur import MODELES_COMMUNS

from . import sauvegardes as SV
from .test_build_package_donnees import module

SECRET = "secret-du-registre-7c2e"


def tables_du_registre():
    return {apps.get_model(m)._meta.db_table for m in MODELES_COMMUNS}


class RegistreTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.bp = module()

    def test_chaque_table_du_registre_classee(self):
        videes, gardees = set(self.bp.TABLES_VIDEES), set(self.bp.TABLES_GARDEES)
        self.assertEqual(videes & gardees, set())
        self.assertEqual(tables_du_registre() - videes - gardees, set())

    def test_reglages_de_l_installation_vides(self):
        for m in ("espaces.serveurenvoi", "espaces.destinationcopie", "espaces.reglagealertes", "espaces.etatalertes",
                  "espaces.problemesignale", "espaces.etatcopie", "connexion_entreprise.reglageentreprise",
                  "connexion_entreprise.lienentreprise", "sessions.session"):
            self.assertIn(apps.get_model(m)._meta.db_table, self.bp.TABLES_VIDEES, m)

    def test_tables_videes_dans_la_copie_d_une_sauvegarde_aussi(self):
        self.assertLessEqual(set(SV._tables(SV.TABLES_VIDEES_DANS_LA_COPIE)), set(self.bp.TABLES_VIDEES))

    def test_registre_copie(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        f = tmp / "shared.sqlite3"
        con = sqlite3.connect(f)
        for t in tables_du_registre():
            con.execute(f'CREATE TABLE "{t}" (id INTEGER PRIMARY KEY, valeur TEXT)')
            con.execute(f'INSERT INTO "{t}" (valeur) VALUES (?)', (f"{SECRET}-{t}",))
        con.commit()
        con.close()
        self.bp.vider_bases(tmp)
        con = sqlite3.connect(f)
        for t in tables_du_registre():
            n = con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            self.assertEqual(n, 0 if t in self.bp.TABLES_VIDEES else 1, t)
        con.close()
        contenu = f.read_bytes()
        for t in self.bp.TABLES_VIDEES:
            if t in tables_du_registre():
                self.assertNotIn(f"{SECRET}-{t}".encode(), contenu, t)  # effacé dans le fichier (secure_delete)
