"""Commande ``backup`` lancée seule (hébergement sans tâche de fond, tâches planifiées « cron » du guide de l'hébergement
géré) : elle archive aussi le registre commun (comptes, réglages de l'installation), comme ``backup --schedule``.

Constaté à la relecture : seule la boucle planifiée appelait ``registre_du_jour`` ; sans elle, le registre n'avait jamais
d'archive, donc ni sauvegarde ni copie externe (``backup --copy``)."""
import io
import zipfile

from django.core.management import call_command
from django.test import TransactionTestCase, override_settings

from . import sauvegardes as SV
from .aides_tests.hebergement import DossiersTemporaires
from collecte.aides_tests import jeu_trois_niveaux as J
from espaces import contexte as ESP


class CommandeRegistreTests(DossiersTemporaires, TransactionTestCase):
    databases = {"default", "commun"}

    def setUp(self):
        super().setUp()
        J.charger()

    def test_archive_du_registre(self):
        call_command("backup", stdout=io.StringIO())
        registres = SV.archives_registre()
        self.assertEqual(len(registres), 1)
        with zipfile.ZipFile(registres[0]) as z:
            self.assertIn("registry.json", z.namelist())

    def test_une_seule_par_jour(self):
        # plusieurs espaces sauvegardés l'un après l'autre (une commande par espace) : une archive du registre
        call_command("backup", stdout=io.StringIO())
        call_command("backup", "--reason", "second", stdout=io.StringIO())
        self.assertEqual(len(SV.archives_registre()), 1)
        self.assertEqual(len(SV.archives()), 2)

    @override_settings(SAUVEGARDE_CONSERVER=2)
    def test_rotation_du_registre(self):
        d = ESP.dossier_sauvegardes_commun()
        d.mkdir(parents=True)
        for nom in ("registry-20200101-020000-auto.zip", "registry-20200102-020000-auto.zip",
                    "registry-20200103-020000-auto.zip", "registry-20191231-020000-before-update.zip"):
            (d / nom).write_bytes(b"ancienne")
        call_command("backup", stdout=io.StringIO())
        restent = sorted(p.name for p in SV.archives_registre())
        # les 2 plus récentes, et la dernière « before-update » (retour à la version précédente) toujours gardée
        self.assertEqual(len(restent), 3)
        self.assertIn("registry-20200103-020000-auto.zip", restent)
        self.assertIn("registry-20191231-020000-before-update.zip", restent)
