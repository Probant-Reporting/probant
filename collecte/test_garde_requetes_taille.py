"""Taille des envois bornée avant réception complète (GardeRequetesMiddleware) : connecté, plus que la plus grande des
tailles d'import et de preuve (plus une marge) → 413 avec un message lisible ; seule exception : le dépôt d'une
sauvegarde par un administrateur, borné par MAX_BACKUP_UPLOAD_MB."""
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from parametres import sauvegardes as SV
from referentiel.models import Utilisateur

from . import garde_requetes as G

MO = 1024 * 1024


@override_settings(IMPORT_TAILLE_MAX=10 * MO, PREUVE_TAILLE_MAX=5 * MO, SAUVEGARDE_DEPOT_MAX=50 * MO)
class TailleEnvoisTests(TestCase):
    def setUp(self):
        self.admin = Utilisateur.objects.create_user("admin", email="admin@exemple.test", password="x",
                                                     role=Utilisateur.Role.ADMIN)
        self.contrib = Utilisateur.objects.create_user("contrib", email="contrib@exemple.test", password="x")

    def envoyer(self, url, taille):
        """POST annoncé de ``taille`` octets (le corps réel est court : le refus se fait sur l'annonce)."""
        return self.client.post(url, data=b"x", content_type="application/octet-stream", CONTENT_LENGTH=str(taille))

    def test_limite(self):
        self.assertEqual(G.envoi_max(), 11 * MO)

    def test_envoi_trop_gros_refuse(self):
        self.client.force_login(self.contrib)
        rep = self.envoyer(reverse("collecte:saisie"), 12 * MO)
        self.assertEqual(rep.status_code, 413)
        self.assertIn("10", rep.content.decode())
        self.assertIn("text/plain", rep["Content-Type"])

    def test_envoi_dans_la_limite_passe_la_garde(self):
        self.client.force_login(self.contrib)
        rep = self.envoyer(reverse("collecte:saisie"), 10 * MO + 1000)
        self.assertNotEqual(rep.status_code, 413)

    def test_depot_de_sauvegarde_par_l_admin(self):
        url = reverse("parametres:sauvegarde_deposer")
        self.client.force_login(self.admin)
        self.assertNotEqual(self.envoyer(url, 40 * MO).status_code, 413)  # sa propre limite
        self.assertEqual(self.envoyer(url, 51 * MO).status_code, 413)  # bornée aussi
        self.client.force_login(self.contrib)
        self.assertEqual(self.envoyer(url, 40 * MO).status_code, 413)  # pas d'exception pour un autre rôle

    def test_depot_de_sauvegarde_dans_un_espace(self):
        r = RequestFactory().post("/x/")
        r.path_info = reverse("parametres:sauvegarde_deposer")
        self.assertTrue(G._depot_sauvegarde(r))
        r.path_info = "/saisie/"
        self.assertFalse(G._depot_sauvegarde(r))

    def test_deposer_borne(self):
        f = SimpleUploadedFile("b.zip", b"x")
        f.size = 51 * MO
        with self.assertRaises(SV.ErreurSauvegarde):
            SV.deposer(f)
