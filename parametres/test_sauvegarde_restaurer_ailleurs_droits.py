"""Droits de la restauration d'une sauvegarde d'une autre installation depuis l'écran (``sauvegarde_restaurer_ailleurs``,
dépôt par ``sauvegarde_deposer``) : gestionnaire des espaces seulement. Un administrateur d'espace qui ne l'est pas, un
validateur, un contributeur, un lecteur, un auditeur sont refusés, y compris par l'adresse directe et en POST ; une archive
signée par cette installation garde les contrôles d'avant pour tout le monde."""
import shutil
import tempfile
from pathlib import Path

from django.contrib.auth import authenticate
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TransactionTestCase
from django.urls import reverse

from espaces.aides_tests import MDP, creer
from espaces.models import Compte, Espace
from referentiel.models import Utilisateur

from . import sauvegardes as SV
from . import sauvegardes_ailleurs as SA
from .aides_tests.autre_installation import ORIGINE, archive_d_ailleurs, compte
from .aides_tests.hebergement import DossiersTemporaires


class Droits(DossiersTemporaires, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.ext = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.ext, True)
        Espace.objects.get_or_create(code="principal", defaults={"nom": "Principal", "etat": "actif"})
        self.gest = creer("gest@exemple.test", "admin")  # premier administrateur : gestionnaire des espaces
        self.admin = creer("admin@exemple.test", "admin")  # administrateur de l'espace, pas gestionnaire
        self.autres = [creer(f"{r}@exemple.test", r) for r in ("validateur", "contributeur", "lecteur", "auditeur")]
        self.assertTrue(Compte.objects.get(pk=self.gest.pk).gestionnaire)
        self.assertFalse(Compte.objects.get(pk=self.admin.pk).gestionnaire)
        self.fichier = archive_d_ailleurs(self.ext / "ailleurs.zip", [compte(900, "alice@exemple.test", "admin")])

    def deposer(self, qui, chemin=None):
        self.client.force_login(qui)
        donnees = Path(chemin or self.fichier).read_bytes()
        return self.client.post(reverse("parametres:sauvegarde_deposer"),
                                {"fichier": SimpleUploadedFile("backup.zip", donnees, "application/zip")})

    def en_quarantaine(self):
        """Archive d'ailleurs déposée par un gestionnaire (comme le fait l'écran)."""
        rep = self.deposer(self.gest)
        a = next(SA.dossier().iterdir())
        self.assertRedirects(rep, reverse("parametres:sauvegarde_restaurer_ailleurs", args=[a.name]),
                             fetch_redirect_response=False)
        self.client.logout()
        return a

    def etat(self):
        return sorted(Utilisateur.objects.values_list("pk", "email", "role", "is_active")), \
            sorted(Compte.objects.values_list("pk", "email", "gestionnaire"))

    def test_depot_refuse_a_l_administrateur_qui_n_est_pas_gestionnaire(self):
        rep = self.deposer(self.admin)
        self.assertRedirects(rep, reverse("parametres:hebergement"), fetch_redirect_response=False)
        self.assertFalse(SA.dossier().exists() and any(SA.dossier().iterdir()))
        self.assertEqual(SV.archives(), [])
        rep = self.client.get(reverse("parametres:hebergement"))
        self.assertContains(rep, "pas été faite par cette installation")  # message d'avant, inchangé

    def test_depot_refuse_aux_autres_roles(self):
        for u in self.autres:
            with self.subTest(u.role):
                self.assertEqual(self.deposer(u).status_code, 403)
        self.assertFalse(SA.dossier().exists() and any(SA.dossier().iterdir()))

    def test_depot_par_le_gestionnaire_rangé_a_part(self):
        a = self.en_quarantaine()
        self.assertEqual(SV.archives(), [])  # jamais dans la liste, la rotation, la copie externe
        self.assertIsNone(SV.derniere_archive_saine())
        self.assertRegex(a.name, r"^backup-\d{8}-\d{6}-other-installation-[0-9a-f]{8}\.zip$")

    def test_adresse_directe_refusee_sauf_au_gestionnaire(self):
        a = self.en_quarantaine()
        url = reverse("parametres:sauvegarde_restaurer_ailleurs", args=[a.name])
        corps = {"compris": "on", "origine_connue": "on", "confirmation": "RESTAURER"}
        avant = self.etat()
        for u in [self.admin, *self.autres]:
            self.client.force_login(u)
            with self.subTest(u.role, envoi="GET"):
                self.assertEqual(self.client.get(url).status_code, 403)
            with self.subTest(u.role, envoi="POST"):
                self.assertEqual(self.client.post(url, corps).status_code, 403)
        self.assertEqual(self.etat(), avant)
        self.assertFalse(SV.historique_restaurations())
        # ni par la page des sauvegardes de cette installation (nom pris dans le dossier caché : introuvable)
        self.client.force_login(self.gest)
        rep = self.client.post(reverse("parametres:sauvegarde_restaurer", args=[a.name]), corps)
        self.assertRedirects(rep, reverse("parametres:hebergement"), fetch_redirect_response=False)
        self.assertEqual(self.etat(), avant)

    def test_gestionnaire_page_de_confirmation_puis_restauration(self):
        a = self.en_quarantaine()
        url = reverse("parametres:sauvegarde_restaurer_ailleurs", args=[a.name])
        self.client.force_login(self.gest)
        rep = self.client.get(url)
        self.assertContains(rep, ORIGINE.replace("'", "&#x27;"))
        self.assertContains(rep, "ne peut pas vérifier que personne n'a modifié ce fichier")
        self.assertContains(rep, "Votre compte (gest@exemple.test) n'est pas dans la sauvegarde")
        self.assertContains(rep, "Administrateurs dans la sauvegarde : alice@exemple.test.")
        self.assertContains(rep, "avant une restauration")  # sauvegarde « avant » faite d'abord
        # une case manquante : rien ne change
        rep = self.client.post(url, {"compris": "on", "confirmation": "RESTAURER"})
        self.assertContains(rep, "cochez les deux cases")
        self.assertFalse(SV.historique_restaurations())
        empreinte = self.client.get(url).context["empreinte"]
        rep = self.client.post(url, {"compris": "on", "origine_connue": "on", "confirmation": "RESTAURER",
                                     "empreinte": empreinte}, follow=True)
        self.assertContains(rep, "Reconnectez-vous avec votre propre mot de passe")
        self.assertContains(rep, "Administration › Comptes")
        u = authenticate(None, username="gest@exemple.test", password=MDP)
        self.assertTrue(u.est_admin)
        self.assertTrue(Compte.objects.get(pk=u.pk).gestionnaire)
        self.assertFalse(a.exists())  # contenu non fiable : pas gardé après la restauration
        self.assertEqual([x.motif for x in SV.archives()], ["before-restore"])
        self.assertTrue(SV.historique_restaurations()[0]["autre_installation"])

    def test_gestionnaire_qui_perd_son_role_entre_les_deux_pages(self):
        a = self.en_quarantaine()
        url = reverse("parametres:sauvegarde_restaurer_ailleurs", args=[a.name])
        self.client.force_login(self.gest)
        Compte.objects.filter(pk=self.gest.pk).update(gestionnaire=False)
        avant = self.etat()
        rep = self.client.post(url, {"compris": "on", "origine_connue": "on", "confirmation": "RESTAURER"})
        self.assertEqual(rep.status_code, 403)
        self.assertEqual(self.etat(), avant)

    def test_archive_signee_ici_garde_les_controles_d_avant(self):
        """Archive de cette installation : déposée dans la liste et restaurée par le chemin d'avant, pour le gestionnaire
        comme pour l'administrateur (jamais rangée à part)."""
        propre = SV.creer("manuelle", "json")
        shutil.copy(propre.chemin, self.ext / "propre.zip")
        propre.chemin.unlink()
        for qui in (self.gest, self.admin):
            with self.subTest(qui.email):
                rep = self.deposer(qui, self.ext / "propre.zip")
                nom = SV.archives()[0].nom
                self.assertRedirects(rep, reverse("parametres:sauvegarde_restaurer", args=[nom]),
                                     fetch_redirect_response=False)
                SV.archive(nom).chemin.unlink()
        self.assertFalse(SA.dossier().exists() and any(SA.dossier().iterdir()))
