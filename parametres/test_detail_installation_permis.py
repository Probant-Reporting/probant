"""Qui voit le détail de l'installation (règle du projet) : une seule
fonction (``sante_installation.detail_installation_permis``) pour /sante/, la page Paramètres › Santé et le volet « Pour
l'IT » de la page Hébergement. Le gestionnaire des espaces, l'administrateur de l'espace principal et l'appel local sans
proxy (supervision de l'IT, contrôle de santé de Docker) voient tout ; l'administrateur d'un espace secondaire ne reçoit
que l'état de son espace, sans le nom des autres espaces, leurs pannes, leurs exports bloqués ni les chemins du disque."""
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.test import Client, TestCase, override_settings

from espaces import contexte as E
from espaces.aides_tests import creer
from espaces.essais import EspacesTestCase
from espaces.models import Compte
from referentiel.models import Utilisateur

from . import sante_installation as SI
from . import vues_hebergement as VH

SECRET = Path("/chemin/secret/des/donnees")
DISTANT = {"REMOTE_ADDR": "203.0.113.9", "HTTP_X_FORWARDED_FOR": "203.0.113.9"}


def connecter(u, espace="principal"):
    c = Client()
    with E.activer(espace):
        c.force_login(Utilisateur.objects.get(pk=u.pk))
    return c


def bases_en_panne(seulement=None):
    """Mesure simulée : un autre espace, « confidentiel », ne répond plus."""
    panne = seulement is None or "confidentiel" in seulement
    return ("unreachable (space confidentiel)" if panne else "ok", "ok", ["principal", "essai"])  # sans déclarer sa base


def exports_bloques(codes):
    return {"running": 1, "waiting": 0, "stuck": 1, "message": "background export stuck: #7 (space confidentiel)"} \
        if "confidentiel" in codes or len(codes) > 1 else {"running": 0, "waiting": 0, "stuck": 0}


class SanteSupervisionTests(EspacesTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.admin = creer("admin@exemple.example", "admin")  # gestionnaire des espaces
        cls.contrib = creer("contrib@exemple.example")
        cls.admin_essai = creer("admin.essai@exemple.example", "admin", "essai")  # administrateur de « essai » seulement
        cls.contrib_essai = creer("contrib.essai@exemple.example", "contributeur", "essai")

    def get(self, client, espace="principal", **meta):
        url = "/sante/" if espace == "principal" else f"/espace/{espace}/sante/"
        with mock.patch.object(VH, "_sante_bases", side_effect=bases_en_panne), \
                mock.patch.object(VH, "espace_disque", return_value=(1024, SECRET)), \
                mock.patch("collecte.exports_arriere_plan.pour_sante", side_effect=exports_bloques):
            return client.get(url, **(meta or DISTANT))

    def test_admin_espace_secondaire_etat_de_son_espace_seulement(self):
        rep = self.get(connecter(self.admin_essai, "essai"), "essai")
        corps = rep.content.decode()
        self.assertIn("version", rep.json())  # l'état de son espace, avec le détail utile
        self.assertNotIn("confidentiel", corps)  # ni le code ni la panne d'un autre espace
        self.assertNotIn("#7", corps)  # ni ses exports bloqués
        self.assertNotIn(str(SECRET), corps)  # ni les chemins du disque
        self.assertIn("disk almost full", corps)  # mais le disque presque plein, qui le concerne aussi
        self.assertEqual(rep.status_code, 503)

    def test_gestionnaire_voit_tout_depuis_un_espace_secondaire(self):
        Compte.objects.filter(pk=self.admin_essai.pk).update(gestionnaire=True)
        corps = self.get(connecter(self.admin_essai, "essai"), "essai").content.decode()
        self.assertIn("confidentiel", corps)
        self.assertIn(str(SECRET), corps)

    def test_admin_principal_voit_tout(self):
        Compte.objects.filter(pk=self.admin.pk).update(gestionnaire=False)
        corps = self.get(connecter(self.admin)).content.decode()
        self.assertIn("confidentiel", corps)
        self.assertIn("#7", corps)
        self.assertIn(str(SECRET), corps)

    def test_appel_local_sans_proxy_voit_tout_meme_dans_un_espace_secondaire(self):
        for espace in ("principal", "essai"):
            corps = self.get(Client(), espace, REMOTE_ADDR="127.0.0.1").content.decode()
            self.assertIn("confidentiel", corps, espace)
            self.assertIn(str(SECRET), corps, espace)

    def test_anonyme_et_non_admin_l_etat_seul(self):
        for client, espace in ((Client(), "principal"), (Client(), "essai"), (connecter(self.contrib), "principal"),
                               (connecter(self.contrib_essai, "essai"), "essai")):
            rep = self.get(client, espace)
            self.assertEqual(rep.json(), {"etat": "erreur"})
            self.assertEqual(rep.status_code, 503)

    def test_une_seule_fonction(self):
        """La page Santé et la page Hébergement décident par la même fonction que /sante/."""
        with mock.patch.object(SI, "detail_installation_permis", return_value=False) as f:
            connecter(self.admin).get("/sante/", **DISTANT)
            connecter(self.admin).get("/administration/parametres/sante/")
            connecter(self.admin).get("/administration/parametres/hebergement/")
        self.assertEqual(f.call_count, 3)


class ControleDockerTests(TestCase):
    def test_controle_de_sante_docker_inchange(self):
        """Le contrôle de santé de l'image (127.0.0.1, sans en-tête de proxy, sans connexion) : 200 et le détail."""
        rep = Client().get("/sante/", REMOTE_ADDR="127.0.0.1")
        self.assertEqual(rep.status_code, 200, rep.json())
        self.assertEqual(rep.json()["etat"], "ok")
        self.assertIn("version", rep.json())
        rep = Client().get("/sante/", REMOTE_ADDR="203.0.113.9")
        self.assertEqual((rep.status_code, rep.json()), (200, {"etat": "ok"}))


@override_settings(EMAIL_HOST="smtp.exemple.test", EMAIL_HOST_USER="compte-smtp-secret",
                   ALLOWED_HOSTS=["hote-secret.exemple.test", "testserver"])
class HebergementPourITTests(EspacesTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.admin = creer("admin@exemple.example", "admin")
        cls.admin_essai = creer("admin.essai@exemple.example", "admin", "essai")

    URL = "/administration/parametres/hebergement/"

    def test_admin_espace_secondaire_sans_detail_de_l_installation(self):
        rep = connecter(self.admin_essai, "essai").get(f"/espace/essai{self.URL}")
        self.assertEqual(rep.status_code, 200)
        self.assertNotContains(rep, "compte-smtp-secret")
        self.assertNotContains(rep, "hote-secret.exemple.test")
        self.assertNotContains(rep, str(settings.DOSSIER_DONNEES))
        self.assertContains(rep, "smtp.exemple.test")  # le serveur d'envoi reste dit (les e-mails partent-ils ?)

    def test_gestionnaire_et_espace_principal_voient_le_detail(self):
        rep = connecter(self.admin).get(self.URL)
        self.assertContains(rep, "compte-smtp-secret")
        self.assertContains(rep, "hote-secret.exemple.test")
        self.assertContains(rep, str(settings.DOSSIER_DONNEES))
        Compte.objects.filter(pk=self.admin_essai.pk).update(gestionnaire=True)
        rep = connecter(self.admin_essai, "essai").get(f"/espace/essai{self.URL}")
        self.assertContains(rep, "compte-smtp-secret")
        self.assertContains(rep, str(settings.DOSSIER_DONNEES))
