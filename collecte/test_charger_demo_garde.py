"""Commande de démo (charger_demo / load_demo) : elle ne touche une base que si elle est vide ou porte le marqueur de
démo posé par la commande elle-même (ou, pour les bases de démo d'avant le marqueur, le compte admin@exemple.test avec le
mot de passe public encore valide). Sur une vraie base (même appelée « Exemplia », avec une campagne 2026), elle refuse :
jamais de compte « admin » superutilisateur au mot de passe public, jamais un vrai compte homonyme écrasé."""
from io import StringIO

from django.core.management import CommandError, call_command
from django.test import TestCase

from parametres.models import Instance
from referentiel.models import Utilisateur

from .management.commands import charger_demo as CD
from .models import Campagne, Journal

VRAI_MDP = "Vrai-mot-de-passe-2026!"


class VraieBaseTests(TestCase):
    def setUp(self):
        Instance.courante()
        Instance.objects.filter(pk=1).update(nom="Exemplia")
        Campagne.objects.create(exercice=2026, statut=Campagne.Statut.OUVERTE)
        self.admin = Utilisateur.objects.create_user("admin", email="direction@client.example", password=VRAI_MDP,
                                                     role=Utilisateur.Role.ADMIN)

    def test_refus_sur_une_vraie_base(self):
        with self.assertRaisesMessage(CommandError, "not a demo database"):
            call_command("load_demo", "--language", "fr", stdout=StringIO())
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.check_password(VRAI_MDP))  # le vrai compte n'est pas écrasé
        self.assertEqual(self.admin.email, "direction@client.example")
        self.assertFalse(Utilisateur.objects.filter(username="validateur").exists())
        self.assertFalse(Journal.objects.filter(action=CD.MARQUEUR).exists())

    def test_refus_espaces(self):
        with self.assertRaisesMessage(CommandError, "not a demo database"):
            call_command("load_demo", "--language", "fr", "--spaces", stdout=StringIO())

    def test_option_explicite(self):
        call_command("load_demo", "--language", "fr", "--force-on-existing-data", stdout=StringIO())
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.check_password(CD.MOT_DE_PASSE))  # demandé en connaissance de cause
        self.assertTrue(Journal.objects.filter(action=CD.MARQUEUR).exists())

    def test_ancien_admin_de_demo_dont_le_mot_de_passe_a_change(self):
        self.admin.email = "admin@exemple.test"
        self.admin.save()
        self.assertFalse(CD.base_de_demo())


class BaseSansDonneesAvecComptesTests(TestCase):
    def test_compte_cree_par_l_it_sans_rien_d_autre(self):
        """Installation vierge où l'IT a créé le compte administrateur : refusée (sinon « admin » serait écrasé)."""
        Utilisateur.objects.create_user("admin", email="it@client.example", password=VRAI_MDP, role=Utilisateur.Role.ADMIN)
        with self.assertRaisesMessage(CommandError, "not a demo database"):
            call_command("load_demo", "--language", "fr", stdout=StringIO())
        self.assertTrue(Utilisateur.objects.get(username="admin").check_password(VRAI_MDP))


class BaseDeDemoTests(TestCase):
    def test_base_vide_puis_rechargement(self):
        self.assertTrue(CD.base_vide())
        call_command("load_demo", "--language", "fr", stdout=StringIO())
        self.assertEqual(Journal.objects.filter(action=CD.MARQUEUR).count(), 1)
        sortie = StringIO()
        call_command("load_demo", "--language", "fr", stdout=sortie)  # rechargement : comptes remis en état
        self.assertIn("already present", sortie.getvalue())
        self.assertEqual(Journal.objects.filter(action=CD.MARQUEUR).count(), 1)

    def test_ancienne_base_de_demo_reconnue(self):
        """Base de démo d'avant le marqueur (Codespace) : reconnue par le compte admin@exemple.test au mot de passe
        public, puis marquée."""
        call_command("load_demo", "--language", "fr", stdout=StringIO())
        Journal.objects.filter(action=CD.MARQUEUR).delete()
        self.assertTrue(CD.base_de_demo())
        sortie = StringIO()
        call_command("load_demo", "--language", "fr", stdout=sortie)
        self.assertIn("already present", sortie.getvalue())
        self.assertTrue(Journal.objects.filter(action=CD.MARQUEUR).exists())
        # mot de passe changé et plus de marqueur : plus reconnue
        Journal.objects.filter(action=CD.MARQUEUR).delete()
        admin = Utilisateur.objects.get(username="admin")
        admin.set_password(VRAI_MDP)
        admin.save()
        with self.assertRaisesMessage(CommandError, "not a demo database"):
            call_command("load_demo", "--language", "fr", stdout=StringIO())
