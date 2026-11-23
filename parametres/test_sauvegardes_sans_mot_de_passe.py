"""Empreintes des mots de passe hors des archives d'un espace.

Avant : chaque copie d'un compte dans un espace gardait l'empreinte du registre commun (``espaces.comptes.COMMUNS``) ;
l'archive d'un espace la contenait donc (copie SQLite ou JSON), y compris celle du gestionnaire de l'installation, et un
administrateur de l'espace pouvait la télécharger pour tenter de casser les mots de passe hors ligne. Après : l'archive
porte ``MOT_DE_PASSE_RETIRE`` ; à la restauration, chaque compte reprend le mot de passe du registre ; un compte que le
registre ne connaît pas (archive restaurée ailleurs) est signalé, avec la marche à suivre."""
import io
import json
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path

from django.conf import settings
from django.contrib.auth import authenticate
from django.core.management import call_command
from django.test import TransactionTestCase
from django.urls import reverse

from espaces.models import Compte
from referentiel.models import Utilisateur

from . import sauvegardes as SV
from .aides_tests.hebergement import MDP, DossiersTemporaires

SQLITE = settings.DATABASES["default"]["ENGINE"].endswith("sqlite3")
AUTRE = "Autre-mot-de-passe-2026"


def octets_de_la_base(archive):
    with zipfile.ZipFile(archive.chemin) as z:
        return z.read(SV.BASE_SQLITE if SV.BASE_SQLITE in z.namelist() else SV.BASE_JSON)


def mots_de_passe_de_la_copie(archive):
    with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(archive.chemin) as z:
        z.extract(SV.BASE_SQLITE, tmp)
        c = sqlite3.connect(Path(tmp) / SV.BASE_SQLITE)
        try:
            return {r[0] for r in c.execute(f'SELECT password FROM "{Utilisateur._meta.db_table}"')}
        finally:
            c.close()


class ArchivesSansEmpreinte(DossiersTemporaires, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.admin = Utilisateur.objects.create_user("admin", email="admin@exemple.test", password=MDP,
                                                     role=Utilisateur.Role.ADMIN)
        self.u = Utilisateur.objects.create_user("marie", email="marie@exemple.test", password=MDP,
                                                 role=Utilisateur.Role.CONTRIBUTEUR)
        # empreintes d'avant restées dans l'espace libre de la base : compte supprimé, mot de passe changé
        parti = Utilisateur.objects.create_user("parti", email="parti@exemple.test", password=AUTRE)
        self.empreintes = {Compte.objects.get(pk=parti.pk).password}
        parti.delete()
        self.empreintes.add(Utilisateur.objects.get(pk=self.u.pk).password)
        self.u.set_password(AUTRE)
        self.u.save()
        self.u.set_password(MDP)
        self.u.save()
        self.empreintes |= set(Compte.objects.values_list("password", flat=True))
        self.assertTrue(all(len(e) > 20 for e in self.empreintes))

    def assert_sans_empreinte(self, archive):
        brut = octets_de_la_base(archive)
        for e in self.empreintes:
            self.assertFalse(e.encode() in brut, e)
            self.assertFalse(e.split("$")[-1].encode() in brut, e)  # ni même la fin de l'empreinte

    @unittest.skipUnless(SQLITE, "copie SQLite : base SQLite seulement")
    def test_copie_sqlite_sans_empreinte(self):
        a = SV.creer("essai", "sqlite")
        self.assertEqual(mots_de_passe_de_la_copie(a), {SV.MOT_DE_PASSE_RETIRE})
        self.assert_sans_empreinte(a)
        # la base vivante, elle, n'a pas changé : la personne se connecte toujours
        self.assertEqual(authenticate(None, username="marie@exemple.test", password=MDP), self.u)

    def test_archive_json_sans_empreinte(self):
        a = SV.creer("essai", "json")
        comptes = [o for o in json.loads(octets_de_la_base(a)) if o["model"] == "referentiel.utilisateur"]
        self.assertEqual({o["fields"]["password"] for o in comptes}, {SV.MOT_DE_PASSE_RETIRE})
        self.assert_sans_empreinte(a)

    def restaurer_et_se_connecter(self, format_base):
        a = SV.creer("essai", format_base)
        self.u.set_password(AUTRE)  # changé après la sauvegarde : le registre fait foi
        self.u.save()
        d = SV.restaurer(a.chemin, sauvegarder_avant=False)
        self.assertEqual(d["comptes_sans_mot_de_passe"], 0)
        self.assertEqual(authenticate(None, username="marie@exemple.test", password=AUTRE), self.u)
        self.assertIsNone(authenticate(None, username="marie@exemple.test", password=MDP))
        # chaque copie a repris l'empreinte du registre : plus aucune marque dans la base de l'espace
        self.assertFalse(Utilisateur.objects.filter(password=SV.MOT_DE_PASSE_RETIRE).exists())
        self.assertEqual(Utilisateur.objects.get(pk=self.u.pk).password, Compte.objects.get(pk=self.u.pk).password)

    @unittest.skipUnless(SQLITE, "copie SQLite : base SQLite seulement")
    def test_restauration_sqlite_mot_de_passe_du_registre(self):
        self.restaurer_et_se_connecter("sqlite")

    def test_restauration_json_mot_de_passe_du_registre(self):
        self.restaurer_et_se_connecter("json")

    def test_restauration_sans_le_registre_message_et_remede(self):
        """Archive restaurée sur un serveur dont le registre ne connaît pas le compte (ici : retiré du registre) : le
        compte n'a plus de mot de passe utilisable, la commande le dit avec les deux remèdes ; un nouveau mot de passe
        donné par l'IT (``changepassword``) suffit pour se connecter de nouveau."""
        a = SV.creer("essai", "json")
        Compte.objects.filter(pk=self.u.pk).delete()
        sortie = io.StringIO()
        call_command("restore", a.nom, "--yes", "--no-backup-before", stdout=sortie)
        self.assertIn("1 account(s) of this space have no password on this server", sortie.getvalue())
        self.assertIn("restore --shared", sortie.getvalue())
        self.assertIn("changepassword", sortie.getvalue())
        self.assertEqual(SV.comptes_sans_mot_de_passe(), 1)
        self.assertEqual(Compte.objects.get(pk=self.u.pk).password, SV.MOT_DE_PASSE_RETIRE)
        self.assertIsNone(authenticate(None, username="marie@exemple.test", password=MDP))
        self.assertEqual(authenticate(None, username="admin@exemple.test", password=MDP), self.admin)
        u = Utilisateur.objects.get(pk=self.u.pk)
        u.set_password(AUTRE)  # ce que fait « manage.py changepassword »
        u.save()
        self.assertEqual(authenticate(None, username="marie@exemple.test", password=AUTRE), u)
        self.assertEqual(SV.comptes_sans_mot_de_passe(), 0)

    def test_la_commande_garde_ses_messages_postgresql(self):
        """Le message ajouté à la commande ne doit pas avaler la méthode qui le suit (constaté sous PostgreSQL : la
        méthode des archives d'une autre structure était devenue une fonction locale, « restore » échouait)."""
        from .management.commands.restauration import Command

        self.assertTrue(callable(getattr(Command, "_structure_differente", None)))

    def test_restauration_depuis_l_outil_signale_les_comptes_sans_mot_de_passe(self):
        a = SV.creer("manuelle")
        Compte.objects.filter(pk=self.u.pk).delete()
        self.client.force_login(self.admin)
        rep = self.client.post(reverse("parametres:sauvegarde_restaurer", args=[a.nom]),
                               {"compris": "on", "confirmation": "RESTAURER"}, follow=True)
        self.assertContains(rep, "1 compte de cette sauvegarde n&#x27;a pas de mot de passe dans cette installation")

    def test_le_registre_garde_les_empreintes_hors_de_portee_de_l_outil(self):
        """L'archive du registre commun (``backups/shared``, IT seulement) garde les empreintes : sans elles, une
        restauration complète ne rendrait aucun mot de passe. Aucune page de l'outil ne la liste ni ne la donne."""
        chemin = SV.creer_registre("essai")
        with zipfile.ZipFile(chemin) as z:
            registre = json.loads(z.read("registry.json"))
        self.assertIn(Compte.objects.get(pk=self.u.pk).password,
                      {o["fields"]["password"] for o in registre if o["model"] == "espaces.compte"})
        self.assertNotIn(chemin.name, [x.nom for x in SV.archives()])
        with self.assertRaises(SV.ErreurSauvegarde):
            SV.archive(chemin.name)
        self.client.force_login(self.admin)
        for nom in (chemin.name, f"shared/{chemin.name}", f"../{chemin.name}"):
            try:
                url = reverse("parametres:sauvegarde_telecharger", args=[nom])
            except Exception:  # noqa: BLE001 - adresse refusée par le motif de l'URL
                continue
            self.assertEqual(self.client.get(url).status_code, 404, nom)
