"""Routage des bases, garde contre les fuites entre espaces, préfixe des adresses, déclaration des alias."""
import tempfile
import threading

from django.conf import settings
from django.db import connections, transaction
from django.test import SimpleTestCase, override_settings
from django.urls import reverse

from referentiel.models import Organisation, Utilisateur

from . import contexte as E
from .essais import EspacesTestCase
from .models import Compte, Espace, MarqueEspace
from .routeur import Routeur
from .aides_tests import oublier_alias


class RouteurTests(EspacesTestCase):
    def test_registre_dans_commun_le_reste_dans_l_espace_courant(self):
        r = Routeur()
        self.assertEqual(r.db_for_read(Compte), "commun")
        self.assertEqual(r.db_for_write(Espace), "commun")
        self.assertEqual(r.db_for_read(Utilisateur), "default")
        self.assertEqual(r.db_for_read(MarqueEspace), "default")
        with E.activer("essai"):
            self.assertEqual(r.db_for_read(Utilisateur), "espace_essai")
            self.assertEqual(r.db_for_read(MarqueEspace), "espace_essai")
            self.assertEqual(r.db_for_read(Compte), "commun")

    def test_migrations(self):
        r = Routeur()
        self.assertTrue(r.allow_migrate("commun", "espaces", "compte"))
        self.assertTrue(r.allow_migrate("commun", "sessions", "session"))
        self.assertFalse(r.allow_migrate("default", "espaces", "compte"))
        self.assertFalse(r.allow_migrate("default", "sessions", "session"))
        self.assertTrue(r.allow_migrate("default", "espaces", "marqueespace"))
        self.assertFalse(r.allow_migrate("commun", "espaces", "marqueespace"))
        self.assertFalse(r.allow_migrate("commun", "collecte"))  # migrations de données : jamais dans le registre
        self.assertTrue(r.allow_migrate("espace_essai", "collecte"))

    def test_un_objet_reste_dans_sa_base(self):
        with E.activer("essai"):
            n = Organisation.objects.count()
        self.assertEqual(Organisation.objects.using("espace_essai").count(), n)
        o = Organisation.objects.using("default").first()
        if o is not None:
            with E.activer("essai"), self.assertRaises(E.FuiteEspace):
                o.save()  # lu dans le principal : enregistré dans le principal, donc refusé pendant l'espace « essai »

    def test_relation_entre_deux_bases_refusee(self):
        from parametres.models import NiveauHierarchique

        n_principal = NiveauHierarchique.objects.using("default").first()
        with E.activer("essai"):
            o = Organisation.objects.using("espace_essai").first() or Organisation(nom="X")
        o._state.db = "espace_essai"
        if n_principal is not None:
            with self.assertRaises(ValueError):
                o.niveau = n_principal


class GardeTests(EspacesTestCase):
    def test_requete_vers_un_autre_espace_refusee(self):
        with E.activer("essai"):
            Utilisateur.objects.count()  # base de l'espace : permis
            Compte.objects.count()  # registre : permis
            with self.assertRaises(E.FuiteEspace):
                Utilisateur.objects.using("default").count()
            with E.toutes_les_bases():
                Utilisateur.objects.using("default").count()
        with self.assertRaises(E.FuiteEspace):
            with E.activer("principal"):
                Utilisateur.objects.using("espace_essai").count()

    def test_atomic_sans_base_detecte(self):
        with E.activer("essai"), self.assertRaises(E.FuiteEspace):
            with transaction.atomic():  # sur « default » : point de sauvegarde refusé par la garde
                pass
        with E.activer("essai"):
            with E.atomic():
                Organisation.objects.count()
            self.assertEqual(E.connexion().alias, "espace_essai")

    def test_curseur_nu_detecte(self):
        from django.db import connection

        with E.activer("essai"), self.assertRaises(E.FuiteEspace):
            with connection.cursor() as c:
                c.execute("SELECT 1")

    def test_garde_retiree_a_la_sortie_meme_apres_erreur(self):
        with self.assertRaises(RuntimeError):
            with E.activer("essai"):
                raise RuntimeError
        self.assertEqual(E.alias_courant(), "default")
        Utilisateur.objects.using("default").count()

    def test_atomic_decorateur_choisit_la_base_a_l_appel(self):
        @E.atomic
        def base():
            return transaction.get_connection(E.alias_courant()).in_atomic_block, E.alias_courant()

        with E.activer("essai"):
            self.assertEqual(base(), (True, "espace_essai"))
        self.assertEqual(base(), (True, "default"))


class AdressesTests(EspacesTestCase):
    def test_prefixe_des_liens(self):
        self.assertEqual(reverse("collecte:accueil"), "/")
        with E.activer("essai"):
            self.assertEqual(reverse("collecte:accueil"), "/espace/essai/")
            with E.activer("principal"):
                self.assertEqual(reverse("collecte:accueil"), "/")
            self.assertEqual(E.url_espace("principal"), "/")
            self.assertEqual(reverse("collecte:accueil"), "/espace/essai/")
        self.assertEqual(E.url_espace("essai"), "/espace/essai/")
        self.assertEqual(reverse("collecte:accueil"), "/")


class DeclarationTests(SimpleTestCase):
    def test_statiques_absolus(self):
        self.assertTrue(settings.STATIC_URL.startswith("/"))
        self.assertTrue(settings.MEDIA_URL.startswith("/"))

    def test_codes(self):
        for bon in ("achats", "rh2", "ab"):
            self.assertTrue(E.CODE.match(bon))
        for mauvais in ("a", "Achats", "ach-ats", "../x", "1abc", "a" * 21, "ach ats", ""):
            self.assertFalse(E.CODE.match(mauvais), mauvais)
        with self.assertRaises(ValueError):
            E.declarer("../x")

    def test_deux_fils_declarent_en_meme_temps(self):
        with tempfile.TemporaryDirectory() as d, override_settings(ESPACES_DOSSIER=d):
            codes = [f"fil{i}" for i in range(8)]
            erreurs = []

            def declarer(code):
                try:
                    for _ in range(20):
                        E.declarer(code)
                        list(connections)  # un autre fil parcourt les connexions pendant ce temps
                except Exception as e:  # pragma: no cover
                    erreurs.append(e)

            fils = [threading.Thread(target=declarer, args=(c,)) for c in codes]
            for f in fils:
                f.start()
            for f in fils:
                f.join()
            try:
                self.assertEqual(erreurs, [])
                for c in codes:
                    self.assertIn(f"espace_{c}", connections.settings)
                    self.assertTrue(str(connections.settings[f"espace_{c}"]["NAME"]).startswith(d)
                                    or connections.settings[f"espace_{c}"]["ENGINE"].endswith("postgresql"))
            finally:
                for c in codes:
                    oublier_alias(f"espace_{c}")
