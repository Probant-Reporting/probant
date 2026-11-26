"""« Partir d'une sauvegarde » dans l'assistant de mise en place (``installation_vide``, ``depart_sauvegarde_permis``) :
proposé tant que l'installation est vide, à la personne qui vient de créer le compte de l'étape 1 (gestionnaire des
espaces) ; jamais à un visiteur non connecté ; disparaît dès que l'installation n'est plus vide."""
import shutil
import tempfile
from pathlib import Path

from django.contrib.auth import authenticate
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TransactionTestCase
from django.urls import reverse

from espaces.models import Compte, Espace
from referentiel.models import Organisation, Utilisateur

from . import sauvegardes as SV
from . import sauvegardes_ailleurs as SA
from .aides_tests.autre_installation import archive_d_ailleurs, compte
from .aides_tests.hebergement import DossiersTemporaires
from .models import Instance, NiveauHierarchique

MDP = "Mise-en-place-2026!"
DEPART = "Partir d'une sauvegarde"


class InstallationVide(DossiersTemporaires, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.ext = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.ext, True)
        Espace.objects.get_or_create(code="principal", defaults={"nom": "Principal", "etat": "actif"})
        Instance.objects.filter(pk=1).update(mise_en_place_terminee=False, mise_en_place_etape=0)

    def etape_1(self):
        rep = self.client.post(reverse("parametres:mise_en_place"), {
            "prenom": "Ines", "nom": "Martin", "email": "ines@exemple.test", "mot_de_passe": MDP, "confirmation": MDP})
        self.assertRedirects(rep, reverse("parametres:mise_en_place_etape", args=[2]), fetch_redirect_response=False)
        return Utilisateur.objects.get(email="ines@exemple.test")

    def test_visiteur_sans_compte_jamais_de_depot(self):
        rep = self.client.get(reverse("parametres:mise_en_place"))
        self.assertNotContains(rep, 'name="fichier"')
        self.assertContains(rep, "Créez d'abord votre compte")
        rep =self.client.post(reverse("parametres:sauvegarde_deposer"),
                               {"fichier": SimpleUploadedFile("b.zip", b"PK", "application/zip")})
        self.assertEqual(rep.status_code, 302)
        self.assertNotIn(reverse("parametres:hebergement"), rep["Location"])
        self.assertFalse(SA.dossier().exists())
        self.assertFalse(Compte.objects.exists())

    def test_proposee_apres_l_etape_1_puis_restauree(self):
        ines = self.etape_1()
        self.assertTrue(SA.installation_vide())
        self.assertTrue(Compte.objects.get(pk=ines.pk).gestionnaire)
        rep = self.client.get(reverse("parametres:mise_en_place_etape", args=[2]))
        self.assertContains(rep, DEPART)
        f = archive_d_ailleurs(self.ext / "a.zip", [compte(ines.pk, "alice@exemple.test", "admin"),
                                                     compte(ines.pk + 1, "bob@exemple.test")])
        rep = self.client.post(reverse("parametres:sauvegarde_deposer"), {
            "depuis": "mise_en_place", "fichier": SimpleUploadedFile("backup.zip", f.read_bytes(), "application/zip")})
        a = next(SA.dossier().iterdir())
        url = reverse("parametres:sauvegarde_restaurer_ailleurs", args=[a.name])
        self.assertRedirects(rep, url, fetch_redirect_response=False)
        rep = self.client.get(url)
        self.assertContains(rep, "Votre compte (ines@exemple.test) n'est pas dans la sauvegarde")
        self.assertContains(rep, "2 autres comptes n'auront pas de mot de passe")
        rep = self.client.post(url, {"compris": "on", "origine_connue": "on", "confirmation": "RESTAURER",
                                     "empreinte": rep.context["empreinte"]})
        self.assertEqual(rep.status_code, 302, rep.context and rep.context.get("erreur"))
        u = authenticate(None, username="ines@exemple.test", password=MDP)
        self.assertIsNotNone(u)
        self.assertTrue(u.est_admin)
        self.assertEqual(Utilisateur.objects.get(pk=ines.pk).email, "alice@exemple.test")
        self.assertFalse(SA.installation_vide())  # la sauvegarde a des comptes : plus vide

    def test_disparait_des_que_l_installation_n_est_plus_vide(self):
        ines = self.etape_1()
        url = reverse("parametres:mise_en_place_etape", args=[2])
        cas = {
            "organisation": lambda: Organisation.objects.create(nom="Siège", niveau=NiveauHierarchique.objects.get_or_create(
                code="Z", defaults={"rang": 1, "nom": "Z", "nom_pluriel": "Z", "couleur": "#123456"})[0]),
            "second compte": lambda: Utilisateur.objects.create(username="b@exemple.test", email="b@exemple.test"),
            "second espace": lambda: Espace.objects.create(code="achats", nom="Achats", etat="creation"),
            "mise en place terminée": lambda: Instance.objects.filter(pk=1).update(mise_en_place_terminee=True),
        }
        for nom, faire in cas.items():
            with self.subTest(nom):
                self.assertTrue(SA.installation_vide())
                objet = faire()
                self.assertFalse(SA.installation_vide())
                if nom != "mise en place terminée":
                    self.assertNotContains(self.client.get(url), DEPART)
                if hasattr(objet, "delete"):
                    objet.delete()
                Instance.objects.filter(pk=1).update(mise_en_place_terminee=False)
        self.assertTrue(Compte.objects.get(pk=ines.pk).gestionnaire)

    def test_administrateur_non_gestionnaire_ne_la_voit_pas(self):
        ines = self.etape_1()
        Compte.objects.filter(pk=ines.pk).update(gestionnaire=False)
        self.assertNotContains(self.client.get(reverse("parametres:mise_en_place_etape", args=[2])), DEPART)
        self.assertEqual(SV.archives(), [])
