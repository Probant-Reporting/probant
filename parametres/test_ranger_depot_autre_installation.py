"""Dépôt d'une sauvegarde d'une autre installation (``ranger``, ``SV.deposer``) et lien entre la confirmation et le
fichier contrôlé (empreinte SHA-256), plus la langue des messages après la restauration (``langue_de_la_connexion``).

Avant : un dépôt effaçait l'archive d'une restauration en cours ; deux dépôts dans la même seconde portaient le même nom
(le second écrasait le premier : le fichier restauré pouvait différer du fichier contrôlé) ; le message de réussite
s'écrivait dans la langue du compte qui venait de se déconnecter (allemand sur une page de connexion en français)."""
import json
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TransactionTestCase
from django.urls import reverse

from espaces.aides_tests import creer
from espaces.models import Compte, Espace
from referentiel.models import Utilisateur

from . import sauvegardes as SV
from . import sauvegardes_ailleurs as SA
from .aides_tests.autre_installation import archive_d_ailleurs, compte
from .aides_tests.hebergement import DossiersTemporaires

CONFIRMER = {"compris": "on", "origine_connue": "on", "confirmation": "RESTAURER"}


class Depot(DossiersTemporaires, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.ext = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.ext, True)
        Espace.objects.get_or_create(code="principal", defaults={"nom": "Principal", "etat": "actif"})
        self.inst = creer("inst@exemple.test", "admin")
        self.f = archive_d_ailleurs(self.ext / "a.zip", [compte(900, "alice@exemple.test", "admin")])
        self.client.force_login(self.inst)

    def deposer(self, chemin=None):
        donnees = Path(chemin or self.f).read_bytes()
        return self.client.post(reverse("parametres:sauvegarde_deposer"),
                                {"fichier": SimpleUploadedFile("a.zip", donnees, "application/zip")})

    def test_deux_depots_dans_la_meme_seconde(self):
        partiels = []
        for i in range(2):
            p = SV.dossier() / f".essai-{i}.partiel"
            p.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(self.f, p)
            partiels.append(p)
        with mock.patch.object(SA.timezone, "localtime", return_value=SA.timezone.localtime()):
            a, b = SA.ranger(partiels[0]), SA.ranger(partiels[1])
        self.assertNotEqual(a.nom, b.nom)

    def test_pas_de_depot_pendant_une_restauration_et_son_archive_gardee(self):
        self.deposer()
        a = next(SA.dossier().iterdir())
        SV._ecrire_atomique(SV.dossier() / SV.EN_COURS, json.dumps({"archive": str(a.resolve()), "avant": ""}))
        rep = self.deposer()
        self.assertRedirects(rep, reverse("parametres:hebergement"), fetch_redirect_response=False)
        self.assertEqual([p.name for p in SA.dossier().iterdir()], [a.name])
        p = SV.dossier() / ".essai.partiel"
        shutil.copy(self.f, p)
        b = SA.ranger(p)  # même appelé directement, le dépôt ne touche pas l'archive de la restauration en cours
        self.assertEqual(sorted(x.name for x in SA.dossier().iterdir()), sorted([a.name, b.nom]))

    def test_confirmation_liee_au_fichier_controle(self):
        self.deposer()
        a = next(SA.dossier().iterdir())
        url = reverse("parametres:sauvegarde_restaurer_ailleurs", args=[a.name])
        empreinte = self.client.get(url).context["empreinte"]
        autre = archive_d_ailleurs(self.ext / "b.zip", [compte(900, "pirate@exemple.test", "admin")])
        shutil.copy(autre, a)  # le fichier change entre la page et la confirmation
        avant = sorted(Compte.objects.values_list("pk", "email"))
        rep = self.client.post(url, {**CONFIRMER, "empreinte": empreinte})
        self.assertContains(rep, "Le fichier a changé")
        self.assertEqual(sorted(Compte.objects.values_list("pk", "email")), avant)
        self.assertFalse(SV.historique_restaurations())
        rep = self.client.post(url, CONFIRMER)  # sans empreinte : refusé aussi
        self.assertContains(rep, "Le fichier a changé")
        with self.assertRaises(SV.ErreurSauvegarde):
            SV.restaurer(a, autre_installation=True, restaurateur={"pk": self.inst.pk, "email": self.inst.email},
                         empreinte=empreinte)


class LangueApresRestauration(DossiersTemporaires, TransactionTestCase):
    """Compte en allemand, installation en français : la page de connexion qui suit est en français, ses messages aussi."""

    def setUp(self):
        super().setUp()
        self.ext = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.ext, True)
        Espace.objects.get_or_create(code="principal", defaults={"nom": "Principal", "etat": "actif"})
        self.inst = creer("inst@exemple.test", "admin")
        Utilisateur.objects.filter(pk=self.inst.pk).update(langue="de")
        self.client.force_login(Utilisateur.objects.get(pk=self.inst.pk))

    def assert_en_francais(self, rep):
        self.assertEqual(rep.redirect_chain[0][1], 302)  # la restauration a bien eu lieu
        self.assertContains(rep, '<html lang="fr"')
        self.assertContains(rep, "Restauration réussie")
        self.assertNotContains(rep, "Wiederherstellung")

    def test_sauvegarde_de_cette_installation(self):
        a = SV.creer("manuelle", "json")
        url = reverse("parametres:sauvegarde_restaurer", args=[a.nom])
        mot = self.client.get(url).context["mot"]  # le mot de la langue de l'écran (allemand)
        rep = self.client.post(url, {"compris": "on", "confirmation": mot}, follow=True)
        self.assert_en_francais(rep)

    def test_sauvegarde_d_une_autre_installation(self):
        f = archive_d_ailleurs(self.ext / "a.zip", [compte(900, "alice@exemple.test", "admin")])
        self.client.post(reverse("parametres:sauvegarde_deposer"),
                         {"fichier": SimpleUploadedFile("a.zip", f.read_bytes(), "application/zip")})
        a = next(SA.dossier().iterdir())
        url = reverse("parametres:sauvegarde_restaurer_ailleurs", args=[a.name])
        page = self.client.get(url).context
        rep = self.client.post(url, {**CONFIRMER, "confirmation": page["mot"], "empreinte": page["empreinte"]}, follow=True)
        self.assert_en_francais(rep)
