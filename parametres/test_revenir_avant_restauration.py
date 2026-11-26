"""Retour automatique à l'état d'avant (``_revenir_avant``) quand une restauration échoue APRÈS le remplacement de la base.

Avant : la base de l'espace était remplacée, puis une étape suivante échouait (schéma inattendu, réconciliation…) : le
repère « restauration en cours » restait, un compte qui n'avait de copie que dans cet espace avait déjà quitté le
registre (étape validée trop tôt), plus personne n'entrait, l'écran disait « Rien n'a changé » et refusait ensuite toute
restauration. Après : le registre n'est touché qu'une fois la base vérifiée, dans une seule transaction ; tout échec
ramène la base et les fichiers à l'archive « before-restore », le repère est retiré, le message dit ce qui s'est passé."""
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth import authenticate
from django.test import TransactionTestCase
from django.urls import reverse

from espaces.aides_tests import MDP, creer
from espaces.models import Compte, Espace
from referentiel.models import Utilisateur

from . import sauvegardes as SV
from . import sauvegardes_ailleurs as SA
from .aides_tests.autre_installation import archive_d_ailleurs, compte
from .aides_tests.hebergement import DossiersTemporaires

SQLITE = settings.DATABASES["default"]["ENGINE"].endswith("sqlite3")


class RetourAvant(DossiersTemporaires, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.ext = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.ext, True)
        Espace.objects.get_or_create(code="principal", defaults={"nom": "Principal", "etat": "actif"})
        self.inst = creer("inst@exemple.test", "admin")
        self.bob = creer("bob@exemple.test", "contributeur")  # seulement dans cet espace : quitterait le registre

    def etat(self):
        return (sorted(Utilisateur.objects.values_list("pk", "email", "role", "password")),
                sorted(Compte.objects.values_list("pk", "email", "password", "gestionnaire")))

    def restaurer(self, a):
        return SV.restaurer(a, par="essai", origine="outil", autre_installation=True,
                            restaurateur={"pk": self.inst.pk, "email": self.inst.email})

    def assert_revenu(self, avant, e):
        self.assertIsInstance(e, SV.ErreurApresRemplacement)
        self.assertIn("revenu à l'état d'avant", str(e))
        self.assertIn("jetons des assistants (MCP)", str(e))  # perdus au retour : le message le dit
        self.assertNotIn("Rien n'a changé", str(e))
        self.assertEqual(self.etat(), avant)
        self.assertIsNone(SV.restauration_en_cours())
        self.assertEqual(authenticate(None, username="bob@exemple.test", password=MDP).pk, self.bob.pk)
        self.assertEqual(authenticate(None, username="inst@exemple.test", password=MDP).pk, self.inst.pk)
        self.assertEqual(SV.historique_restaurations()[0]["origine"], "retour-automatique")
        # l'écran n'est pas bloqué : une sauvegarde de cette installation se restaure aussitôt
        SV.restaurer(SV.creer("manuelle", "json").chemin, exiger_signature=True, origine="outil")

    def test_echec_de_la_derniere_etape_registre_compris(self):
        a = archive_d_ailleurs(self.ext / "a.zip", [compte(self.bob.pk, "alice@exemple.test", "admin")])
        avant = self.etat()
        with mock.patch.object(SA, "assurer_restaurateur", side_effect=RuntimeError("panne simulée")):
            with self.assertRaises(SV.ErreurSauvegarde) as e:
                self.restaurer(a)
        self.assert_revenu(avant, e.exception)

    @unittest.skipUnless(SQLITE, "base SQLite seulement")
    def test_schema_inattendu_vu_apres_la_migration(self):
        """Archive d'une version « antérieure » (contrôle d'avant le remplacement sauté) au schéma forgé : vue juste après
        la migration, avant que le registre soit touché, puis retour à l'état d'avant."""
        a = archive_d_ailleurs(self.ext / "b.zip", [compte(self.bob.pk, "alice@exemple.test", "admin")], format_base="sqlite",
                               sql_en_plus=['ALTER TABLE "referentiel_utilisateur" DROP COLUMN first_name;'])
        avant = self.etat()
        with mock.patch.object(SV, "_migrations_de_la_copie", return_value=set()), \
                mock.patch.object(SA, "preparer_registre", wraps=SA.preparer_registre) as registre:
            with self.assertRaises(SV.ErreurSauvegarde) as e:
                self.restaurer(a)
        self.assertFalse(registre.called)  # registre jamais touché
        self.assertIn("first_name", str(e.exception))
        self.assert_revenu(avant, e.exception)

    def test_l_ecran_dit_la_verite(self):
        self.client.force_login(self.inst)
        f = archive_d_ailleurs(self.ext / "c.zip", [compte(900, "alice@exemple.test", "admin")])
        from django.core.files.uploadedfile import SimpleUploadedFile

        self.client.post(reverse("parametres:sauvegarde_deposer"),
                         {"fichier": SimpleUploadedFile("c.zip", f.read_bytes(), "application/zip")})
        a = next(SA.dossier().iterdir())
        url = reverse("parametres:sauvegarde_restaurer_ailleurs", args=[a.name])
        empreinte = self.client.get(url).context["empreinte"]
        with mock.patch.object(SA, "assurer_restaurateur", side_effect=RuntimeError("panne simulée")):
            rep = self.client.post(url, {"compris": "on", "origine_connue": "on", "confirmation": "RESTAURER",
                                         "empreinte": empreinte})
        self.assertContains(rep, "revenu à l&#x27;état d&#x27;avant la restauration")
        self.assertNotContains(rep, "Rien n&#x27;a changé")
        self.assertIsNone(SV.restauration_en_cours())

    def test_retour_qui_echoue_avant_son_repere_garde_le_repere(self):
        """Seconde relecture : le repère était retiré avant le retour ; un retour qui échouait avant d'écrire son propre
        repère (disque plein) ne laissait aucune trace alors que la base de l'archive était en place."""
        import errno

        a = archive_d_ailleurs(self.ext / "e.zip", [compte(900, "alice@exemple.test", "admin")])
        vrai = SV.restaurer

        def restaurer(*args, **kw):
            if kw.get("_retour"):
                raise OSError(errno.ENOSPC, "disque plein")
            return vrai(*args, **kw)
        with mock.patch.object(SA, "assurer_restaurateur", side_effect=RuntimeError("panne simulée")), \
                mock.patch.object(SV, "restaurer", side_effect=restaurer):
            with self.assertRaises(SV.ErreurApresRemplacement) as e:
                SV.restaurer(a, par="essai", origine="outil", autre_installation=True,
                             restaurateur={"pk": self.inst.pk, "email": self.inst.email})
        self.assertIn("n'a pas pu revenir", str(e.exception))
        self.assertEqual(SV.restauration_en_cours()["archive"], str(a.resolve()))  # signalé, repris au démarrage

    def test_sans_archive_d_avant_le_repere_reste_et_le_message_le_dit(self):
        a = archive_d_ailleurs(self.ext / "d.zip", [compte(900, "alice@exemple.test", "admin")])
        with mock.patch.object(SA, "assurer_restaurateur", side_effect=RuntimeError("panne simulée")):
            with self.assertRaises(SV.ErreurApresRemplacement) as e:
                SV.restaurer(a, sauvegarder_avant=False, autre_installation=True, origine="outil",
                             restaurateur={"pk": self.inst.pk, "email": self.inst.email})
        self.assertIn("n'a pas pu revenir", str(e.exception))
        self.assertIsNotNone(SV.restauration_en_cours())
