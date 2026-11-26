"""Rotation des sauvegardes (``sauvegardes.tourner`` pour un espace, ``creer_registre`` pour le registre commun) : les
archives « before-update » de la dernière mise à jour (la plus récente, et celles faites moins d'un jour avant elle :
update.sh avec l'ancienne version, puis le démarrage de la nouvelle) sont toujours gardées, hors du nombre d'archives
conservées ; sans elles, le retour à la version précédente serait impossible au bout de ``SAUVEGARDE_CONSERVER``
sauvegardes. Les « before-update » des mises à jour d'avant tournent comme les autres."""
from pathlib import Path

from django.conf import settings
from django.test import TestCase, override_settings

from espaces import contexte as ESP

from . import sauvegardes as SV
from .aides_tests.hebergement import DossiersTemporaires


class RotationAvantMiseAJourTests(DossiersTemporaires, TestCase):
    databases = {"default", "commun"}

    def test_espace_derniere_before_update_gardee(self):
        d = Path(settings.SAUVEGARDES_DIR)
        d.mkdir()
        noms = ["backup-20261001-023000-before-update.zip", "sauvegarde-20261002-023000-avant-mise-a-jour.zip",
                "backup-20261002-024500-before-update.zip"]  # même mise à jour : update.sh, puis le démarrage
        noms += [f"backup-202610{j:02d}-023000-auto.zip" for j in range(3, 9)]
        for nom in noms:
            (d / nom).write_bytes(b"x")
        supprimees = SV.tourner(2)
        restantes = [a.nom for a in SV.archives()]
        self.assertEqual(restantes, ["backup-20261008-023000-auto.zip", "backup-20261007-023000-auto.zip",
                                     "backup-20261002-024500-before-update.zip",
                                     "sauvegarde-20261002-023000-avant-mise-a-jour.zip"])
        self.assertIn("backup-20261001-023000-before-update.zip", supprimees)  # la plus ancienne tourne

    def test_registre_derniere_before_update_gardee(self):
        with override_settings(SAUVEGARDE_CONSERVER=2):
            avant = SV.creer_registre("before-update")
            plus_ancienne = avant.with_name("registry-20200101-000000-before-update.zip")
            plus_ancienne.write_bytes(avant.read_bytes())
            for _ in range(3):
                SV.creer_registre("auto")
        restantes = [p.name for p in SV.archives_registre()]
        self.assertEqual(len(restantes), 3, restantes)
        self.assertIn(avant.name, restantes)
        self.assertNotIn(plus_ancienne.name, restantes)
        self.assertEqual(ESP.dossier_sauvegardes_commun(), avant.parent)
