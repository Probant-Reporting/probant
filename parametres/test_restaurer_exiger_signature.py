"""``sauvegardes.restaurer(exiger_signature=True)`` : la restauration refuse elle-même, avant tout changement, une archive
sans signature valide de cette installation, sans compter sur le contrôle fait plus tôt par la page (une archive peut être
remplacée entre les deux)."""
from django.test import TransactionTestCase

from referentiel.models import Utilisateur

from . import sauvegardes as SV
from .aides_tests.hebergement import MDP, DossiersTemporaires
from .test_signature_valide_archives import recopier, sans_signature


class RestaurerExigeLaSignatureTests(DossiersTemporaires, TransactionTestCase):
    def setUp(self):
        super().setUp()
        Utilisateur.objects.create_user("admin", email="admin@exemple.test", password=MDP, role=Utilisateur.Role.ADMIN)
        self.a = SV.creer("essai", "json")
        self.non_signee = recopier(self.a.chemin, SV.dossier() / "backup-20261101-000099.zip", changer={"backup.json": sans_signature})
        Utilisateur.objects.create_user("apres", email="apres@exemple.test", password=MDP)

    def test_archive_non_signee_refusee_sans_rien_changer(self):
        with self.assertRaises(SV.ErreurSauvegarde):
            SV.restaurer(self.non_signee, sauvegarder_avant=False, exiger_signature=True)
        self.assertTrue(Utilisateur.objects.filter(username="apres").exists())

    def test_archive_signee_acceptee(self):
        SV.restaurer(self.a.chemin, sauvegarder_avant=False, exiger_signature=True)
        self.assertFalse(Utilisateur.objects.filter(username="apres").exists())
