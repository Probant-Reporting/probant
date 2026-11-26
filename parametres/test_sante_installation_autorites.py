"""Page Paramètres › Santé : ligne « Autorités de certification ajoutées » (``sante_installation._ligne_autorites``).

Détail pour l'IT seulement (``detail_installation_permis``) et seulement quand l'IT a ajouté des autorités
(``EXTRA_CA_CERTS``) : nom du sujet et date d'expiration de chacune ; « À regarder » si l'une expire dans moins de 30 jours
ou a expiré, si un fichier est écarté (pas une autorité, illisible…), ou si le fichier réuni n'est pas en service."""
import os
import shutil
import tempfile
from pathlib import Path

from django.test import override_settings

from config import autorites_certificats as AC
from espaces.aides_tests import creer
from espaces.essais import EspacesTestCase

from . import sante_installation as SI
from .aides_tests.serveurs_tls import Autorite
from .test_sante_installation_page import URL, connecter


def ligne(rep, cle="autorites"):
    return next((x for x in rep.context["lignes"] if x["cle"] == cle), None)


class LigneAutoritesTests(EspacesTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.admin = creer("admin@exemple.example", "admin")  # gestionnaire des espaces
        cls.admin.langue = "en"
        cls.admin.save()
        cls.admin_essai = creer("admin.essai@exemple.example", "admin", "essai")

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.reuni = self.tmp / AC.FICHIER
        self.reuni.write_text("", encoding="ascii")

    def page(self, valeur, en_service=True, utilisateur=None, espace="principal"):
        """La page, avec les réglages que config/settings.py prépare au démarrage pour ``valeur`` (EXTRA_CA_CERTS)."""
        env = {AC.MARQUE: str(self.reuni), "SSL_CERT_FILE": str(self.reuni)} if en_service else {}
        with override_settings(AUTORITES_AJOUTEES=str(valeur), AUTORITES_BILAN=AC.lire(str(valeur)),
                               AUTORITES_EN_SERVICE=AC.en_service(env) is not None):
            prefixe = "" if espace == "principal" else f"/espace/{espace}"
            return connecter(utilisateur or self.admin, espace).get(prefixe + URL)

    def test_rien_d_ajoute_pas_de_ligne(self):
        rep = self.page("")
        self.assertIsNone(ligne(rep))
        dossier = self.tmp / "ca"  # dossier vide de l'image Docker
        dossier.mkdir()
        self.assertIsNone(ligne(self.page(dossier)))

    def test_autorite_en_service_sujet_et_expiration(self):
        a = Autorite("Acme Test Internal Root", jours=400)
        fichier = a.ecrire(self.tmp, "interne.pem")
        rep = self.page(fichier)
        x = ligne(rep)
        self.assertEqual(x["etat"], SI.BON)
        self.assertIn("Acme Test Internal Root", x["constat"])
        self.assertIn(a.expire.strftime("%Y"), x["constat"])
        self.assertIn("outgoing connections", x["constat"])
        self.assertEqual(x["detail"], str(fichier))  # détail pour l'IT : le fichier
        # place : après la ligne des e-mails
        cles = [y["cle"] for y in rep.context["lignes"]]
        self.assertEqual(cles.index("autorites"), cles.index("email") + 1)

    def test_reservee_au_detail_pour_l_it(self):
        fichier = Autorite().ecrire(self.tmp)
        rep = self.page(fichier, utilisateur=self.admin_essai, espace="essai")
        self.assertEqual(rep.status_code, 200)
        self.assertIsNone(ligne(rep))

    def test_expire_bientot_ou_expiree_a_regarder(self):
        for jours in (10, -3):
            with self.subTest(jours=jours):
                fichier = Autorite("Bientot CA", jours=jours).ecrire(self.tmp, f"a{jours}.pem")
                x = ligne(self.page(fichier))
                self.assertEqual(x["etat"], SI.A_REGARDER)
                self.assertIn("Expired, or expires within 30 days: Bientot CA", x["constat"])
                self.assertIn("new certificate of the authority", x["quoi"])
        # 40 jours : bon
        self.assertEqual(ligne(self.page(Autorite(jours=40).ecrire(self.tmp, "b.pem")))["etat"], SI.BON)

    def test_fichier_ecarte_a_regarder(self):
        a = Autorite()
        serveur, _ = a.certificat_serveur(self.tmp, noms=("serveur.example.test",))
        valeur = os.pathsep.join([str(a.ecrire(self.tmp)), str(serveur), str(self.tmp / "absent.pem")])
        x = ligne(self.page(valeur))
        self.assertEqual(x["etat"], SI.A_REGARDER)
        self.assertIn(f"{serveur.name} (not the certificate of an authority)", x["constat"])
        self.assertNotIn(str(self.tmp), x["constat"])  # le nom du fichier seulement ; les chemins dans le détail
        self.assertIn("absent.pem (not found)", x["constat"])
        self.assertIn("PEM format", x["quoi"])

    def test_aucune_valable(self):
        a = Autorite()
        serveur, _ = a.certificat_serveur(self.tmp, noms=("serveur.example.test",))
        x = ligne(self.page(serveur, en_service=False))
        self.assertEqual(x["etat"], SI.A_REGARDER)
        self.assertIn("No added authority is in use", x["constat"])

    def test_pas_en_service_dans_ce_processus(self):
        x = ligne(self.page(Autorite().ecrire(self.tmp), en_service=False))
        self.assertEqual(x["etat"], SI.A_REGARDER)
        self.assertIn("Not in use", x["constat"])
        self.assertIn("log of the tool", x["quoi"])

    def test_dans_la_langue_de_la_personne(self):
        self.admin.langue = "fr"
        self.admin.save()
        x = ligne(self.page(Autorite("Interne").ecrire(self.tmp)))
        self.assertEqual(x["titre"], "Autorités de certification ajoutées")
        self.assertIn("En service pour les connexions sortantes", x["constat"])
        self.assertIn("Interne (expire le ", x["constat"])
