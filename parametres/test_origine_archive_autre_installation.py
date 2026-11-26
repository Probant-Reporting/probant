"""Origine d'une archive (``sauvegardes_ailleurs.origine``) : « d'ici » seulement si sa signature est valide ET que
l'identifiant de l'installation et l'espace correspondent ; sinon « d'ailleurs », signée ou non.

Avant : une archive faite par une autre installation qui avait la MÊME clé secrète (serveur reconstruit avec le même
``DJANGO_SECRET_KEY``, ``.env`` recopié) avait une signature valide : le dépôt prenait l'ancien chemin et la page
refusait (« comes from another installation »), même pour un gestionnaire sur une installation vide."""
import shutil
import tempfile
from pathlib import Path

from django.conf import settings
from django.contrib.auth import authenticate
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TransactionTestCase
from django.urls import reverse

from espaces.aides_tests import MDP, creer
from espaces.models import Compte, Espace, Installation
from referentiel.models import Utilisateur

from . import sauvegardes as SV
from . import sauvegardes_ailleurs as SA
from .aides_tests.autre_installation import AUTRE_IDENTIFIANT, archive_d_ailleurs, compte
from .aides_tests.hebergement import DossiersTemporaires

ICI = "a" * 32


class Origine(DossiersTemporaires, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.ext = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.ext, True)
        Installation.objects.all().delete()
        Installation.objects.create(identifiant=ICI)
        Espace.objects.get_or_create(code="principal", defaults={"nom": "Principal", "etat": "actif"})
        self.gest = creer("gest@exemple.test", "admin")
        self.admin = creer("admin@exemple.test", "admin")  # pas gestionnaire
        self.contrib = creer("contrib@exemple.test", "contributeur")

    def archive(self, nom, **descriptif):
        """Archive signée avec la clé d'ICI (même DJANGO_SECRET_KEY), descriptif choisi."""
        return archive_d_ailleurs(self.ext / nom, [compte(900, "alice@exemple.test", "admin")], secret=settings.SECRET_KEY,
                                  descriptif=descriptif)

    def deposer(self, qui, chemin):
        self.client.force_login(qui)
        return self.client.post(reverse("parametres:sauvegarde_deposer"),
                                {"fichier": SimpleUploadedFile("a.zip", Path(chemin).read_bytes(), "application/zip")})

    def etat(self):
        return sorted(Utilisateur.objects.values_list("pk", "email", "role")), sorted(Compte.objects.values_list("pk", "email"))

    def test_origine(self):
        cas = {"ici": {"identifiant_installation": ICI},
               "ailleurs": {"identifiant_installation": AUTRE_IDENTIFIANT},
               "autre_espace": {"identifiant_installation": ICI, "espace": "achats"}}
        for attendu, descriptif in cas.items():
            a = self.archive(f"{attendu}.zip", **descriptif)
            self.assertTrue(SV.signature_valide(a))
            self.assertEqual(SA.origine(a, SV.lire_descriptif(a)), attendu)
        sans = self.archive("sans.zip", identifiant_installation="")  # signée ici, sans identifiant : rien ne le prouve
        self.assertEqual(SA.origine(sans, SV.lire_descriptif(sans)), "ailleurs")
        non_signee = archive_d_ailleurs(self.ext / "ns.zip", [compte(900, "alice@exemple.test")],
                                        descriptif={"identifiant_installation": ICI})
        self.assertEqual(SA.origine(non_signee, SV.lire_descriptif(non_signee)), "ailleurs")

    def test_meme_cle_autre_installation_gestionnaire_par_le_nouveau_chemin(self):
        a = self.archive("a.zip", identifiant_installation=AUTRE_IDENTIFIANT)
        rep = self.deposer(self.gest, a)
        depot = next(SA.dossier().iterdir())
        url = reverse("parametres:sauvegarde_restaurer_ailleurs", args=[depot.name])
        self.assertRedirects(rep, url, fetch_redirect_response=False)
        self.assertEqual(SV.archives(), [])
        page = self.client.get(url).context
        self.assertEqual(page["plan"].admins, ["alice@exemple.test"])
        rep = self.client.post(url, {"compris": "on", "origine_connue": "on", "confirmation": page["mot"],
                                     "empreinte": page["empreinte"]})
        self.assertEqual(rep.status_code, 302)
        self.assertTrue(authenticate(None, username="gest@exemple.test", password=MDP).est_admin)
        self.assertEqual(Utilisateur.objects.get(email="alice@exemple.test").password, SV.MOT_DE_PASSE_RETIRE)

    def test_meme_cle_autre_installation_refusee_aux_autres_roles(self):
        a = self.archive("a.zip", identifiant_installation=AUTRE_IDENTIFIANT)
        avant = self.etat()
        self.deposer(self.admin, a)  # refus d'avant : l'archive va dans la liste, la page la refuse
        self.assertFalse(SA.dossier().exists() and any(SA.dossier().iterdir()))
        nom = SV.archives()[0].nom
        url = reverse("parametres:sauvegarde_restaurer", args=[nom])
        rep = self.client.get(url, follow=True)
        self.assertContains(rep, "autre installation")
        self.client.post(url, {"compris": "on", "confirmation": "RESTAURER"})
        self.assertEqual(self.etat(), avant)
        self.assertEqual(self.deposer(self.contrib, a).status_code, 403)
        self.client.force_login(self.contrib)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.etat(), avant)
        self.assertFalse(SV.historique_restaurations())

    def test_archive_d_ailleurs_deja_dans_la_liste(self):
        """Bouton « Restaurer… » de la liste sur une archive d'ailleurs (copiée par l'IT, déposée par un autre) : un
        gestionnaire passe par la page d'une autre installation (copie mise à part), jamais par l'ancien chemin."""
        a = self.archive("a.zip", identifiant_installation=AUTRE_IDENTIFIANT)
        SV.dossier().mkdir(parents=True, exist_ok=True)
        dans_la_liste = SV.dossier() / "backup-20261126-120000-manuelle.zip"
        shutil.copy(a, dans_la_liste)
        self.client.force_login(self.gest)
        rep = self.client.get(reverse("parametres:sauvegarde_restaurer", args=[dans_la_liste.name]))
        depot = next(SA.dossier().iterdir())
        self.assertRedirects(rep, reverse("parametres:sauvegarde_restaurer_ailleurs", args=[depot.name]),
                             fetch_redirect_response=False)
        avant = self.etat()  # un POST sur l'ancienne page ne restaure pas non plus
        self.client.post(reverse("parametres:sauvegarde_restaurer", args=[dans_la_liste.name]),
                         {"compris": "on", "confirmation": "RESTAURER"})
        self.assertEqual(self.etat(), avant)
        self.assertFalse(SV.historique_restaurations())

    def test_meme_installation_autre_espace_reste_reserve_a_l_it(self):
        a = self.archive("e.zip", identifiant_installation=ICI, espace="achats")
        self.deposer(self.gest, a)
        self.assertFalse(SA.dossier().exists() and any(SA.dossier().iterdir()))
        url = reverse("parametres:sauvegarde_restaurer", args=[SV.archives()[0].nom])
        avant = self.etat()
        rep = self.client.post(url, {"compris": "on", "confirmation": "RESTAURER"})
        self.assertContains(rep, "achats")  # message d'avant : l'archive d'un autre espace
        self.assertEqual(self.etat(), avant)

    def test_archive_d_ici_garde_l_ancien_chemin(self):
        propre = SV.creer("manuelle", "json")
        shutil.copy(propre.chemin, self.ext / "p.zip")
        propre.chemin.unlink()
        for qui in (self.gest, self.admin):
            rep = self.deposer(qui, self.ext / "p.zip")
            nom = SV.archives()[0].nom
            self.assertRedirects(rep, reverse("parametres:sauvegarde_restaurer", args=[nom]), fetch_redirect_response=False)
            self.assertEqual(self.client.get(reverse("parametres:sauvegarde_restaurer", args=[nom])).status_code, 200)
            SV.archive(nom).chemin.unlink()
        self.assertFalse(SA.dossier().exists() and any(SA.dossier().iterdir()))
