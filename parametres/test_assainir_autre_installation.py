"""Contenu d'une sauvegarde d'une autre installation assaini avant d'être chargé (``assainir_json``, ``assainir_copie``,
``preparer``), dans les deux formats, et lu UNE fois : la page de confirmation annonce ce qui sera chargé.

Avant :
- une archive forgée donnait ``is_staff`` et des permissions (lecture des valeurs, du journal) à un contributeur : il
  entrait dans le mode expert (``/admin/``) et lisait toutes les valeurs, KPI sensibles compris, sans être annoncé ;
- un compte écrit « referentiel.UTILISATEUR » dans le JSON n'était pas lu par la page de confirmation mais chargé par
  ``loaddata`` : caché, il devenait administrateur avec le mot de passe d'une personne existante ;
- la lecture du JSON coûtait un temps quadratique et une mémoire égale au fichier pour un objet démesuré."""
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from django.conf import settings
from django.contrib.auth import authenticate
from django.test import TransactionTestCase

from espaces.aides_tests import MDP, creer
from espaces.models import Compte, Espace
from referentiel.models import Utilisateur

from . import sauvegardes as SV
from . import sauvegardes_ailleurs as SA
from .aides_tests.autre_installation import archive_d_ailleurs, compte
from .aides_tests.hebergement import DossiersTemporaires
from .models import Instance

SQLITE = settings.DATABASES["default"]["ENGINE"].endswith("sqlite3")
PERMISSIONS = [["view_reponse", "collecte", "reponse"], ["view_journal", "collecte", "journal"]]


class Assainir(DossiersTemporaires, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.ext = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.ext, True)
        Espace.objects.get_or_create(code="principal", defaults={"nom": "Principal", "etat": "actif"})
        self.inst = creer("inst@exemple.test", "admin")
        self.restaurateur = {"pk": self.inst.pk, "email": self.inst.email}

    def restaurer(self, a):
        return SV.restaurer(a, autre_installation=True, origine="outil", restaurateur=self.restaurateur)

    def apercu(self, a):
        return SA.apercu(a, SV.lire_descriptif(a), self.restaurateur)

    def assert_sans_droit_glisse(self):
        for u in Utilisateur.objects.exclude(email="inst@exemple.test"):
            self.assertEqual((u.is_staff, u.is_superuser), (u.role == "admin", u.role == "admin"), u.email)
            self.assertFalse(u.user_permissions.exists() or u.groups.exists(), u.email)
        carla = Utilisateur.objects.get(email="carla@exemple.test")
        self.assertFalse(carla.has_perm("collecte.view_reponse"))
        carla.set_password("Carla-essai-2026")
        carla.save()
        self.client.login(username="carla@exemple.test", password="Carla-essai-2026")
        self.assertNotEqual(self.client.get("/admin/collecte/reponse/").status_code, 200)  # pas de mode expert
        i = Instance.courante()
        self.assertFalse(i.ia_active or i.ia_kpi_sensibles)

    def test_droits_glisses_json(self):
        def trafiquer(objets):
            for o in objets:
                if o["model"] == "referentiel.utilisateur" and o["fields"]["email"] == "carla@exemple.test":
                    o["fields"].update(is_staff=True, user_permissions=PERMISSIONS)
                if o["model"] == "referentiel.utilisateur" and o["fields"]["email"] == "dan@exemple.test":
                    o["fields"].update(is_superuser=True, is_staff=True)  # super-utilisateur sans le rôle
                if o["model"] == "parametres.instance":
                    o["fields"].update(ia_active=True, ia_kpi_sensibles=True)
        a = archive_d_ailleurs(self.ext / "a.zip", [compte(900, "carla@exemple.test"), compte(901, "dan@exemple.test")],
                               modifier_objets=trafiquer)
        plan, refus = self.apercu(a)
        self.assertEqual((plan.admins, refus), ([], ""))  # annoncé : aucun administrateur, ce qui est vrai après
        self.restaurer(a)
        self.assert_sans_droit_glisse()

    @unittest.skipUnless(SQLITE, "copie SQLite : base SQLite seulement")
    def test_droits_glisses_sqlite(self):
        sql = ["UPDATE referentiel_utilisateur SET is_staff = 1 WHERE email = 'carla@exemple.test';",
               "UPDATE referentiel_utilisateur SET is_staff = 1, is_superuser = 1 WHERE email = 'dan@exemple.test';",
               "INSERT INTO referentiel_utilisateur_user_permissions (utilisateur_id, permission_id) SELECT 900, id "
               "FROM auth_permission WHERE codename IN ('view_reponse', 'view_journal');",
               "UPDATE parametres_instance SET ia_active = 1, ia_kpi_sensibles = 1;"]
        a = archive_d_ailleurs(self.ext / "b.zip", [compte(900, "carla@exemple.test"), compte(901, "dan@exemple.test")],
                               format_base="sqlite", sql_en_plus=sql)
        plan, refus = self.apercu(a)
        self.assertEqual((plan.admins, refus), ([], ""))
        self.restaurer(a)
        self.assert_sans_droit_glisse()

    def test_nom_de_modele_dans_une_autre_casse_refuse(self):
        """Compte caché sous « referentiel.UTILISATEUR » avec l'e-mail d'une personne existante : refusé, la page le dit."""
        creer("existante@exemple.test", "contributeur")
        cache = {"model": "referentiel.UTILISATEUR", "pk": 950, "fields": {}}

        def cacher(objets):
            gabarit = next(o for o in objets if o["model"] == "referentiel.utilisateur")
            cache["fields"] = {**gabarit["fields"], "email": "existante@exemple.test", "username": "x", "role": "admin",
                               "is_superuser": True, "is_staff": True}
            objets.append(cache)
        a = archive_d_ailleurs(self.ext / "c.zip", [compte(900, "alice@exemple.test")], modifier_objets=cacher)
        plan, refus = self.apercu(a)
        self.assertIsNone(plan)
        self.assertIn("referentiel.UTILISATEUR", refus)
        avant = sorted(Compte.objects.values_list("pk", "email"))
        with self.assertRaises(SV.ErreurSauvegarde):
            self.restaurer(a)
        self.assertEqual(sorted(Compte.objects.values_list("pk", "email")), avant)
        self.assertEqual(authenticate(None, username="existante@exemple.test", password=MDP).role, "contributeur")

    def test_modele_hors_liste_ou_en_double_refuse(self):
        for nom, objet in {"registre": {"model": "espaces.accesespace", "pk": 1, "fields": {}},
                           "permission": {"model": "auth.permission", "pk": 1, "fields": {}},
                           "inconnu": {"model": "pirate.table", "pk": 1, "fields": {}}}.items():
            with self.subTest(nom):
                a = archive_d_ailleurs(self.ext / f"{nom}.zip", [compte(900, "alice@exemple.test")], objets_en_plus=[objet])
                self.assertIsNone(self.apercu(a)[0])
        double = archive_d_ailleurs(self.ext / "double.zip", [compte(900, "alice@exemple.test"),
                                                               compte(900, "bob@exemple.test", "admin")])
        plan, refus = self.apercu(double)
        self.assertIsNone(plan)
        self.assertIn("referentiel.utilisateur 900", refus)

    def test_relances_automatiques_et_taches_en_attente_eteintes(self):
        """Seconde relecture : une archive forgée pouvait garder les relances automatiques allumées et faire partir, depuis
        le serveur d'e-mails d'ici, un message de son choix ; des imports ou exports en attente se lançaient tout seuls."""
        Instance.courante()  # ligne de l'installation présente dans l'archive
        allumees = []

        def allumer(objets):
            for o in objets:
                if o["model"] == "parametres.instance":
                    o["fields"]["relance_auto"] = True
                    allumees.append(o["pk"])
        self.restaurer(archive_d_ailleurs(self.ext / "r.zip", [compte(900, "alice@exemple.test")], modifier_objets=allumer))
        self.assertEqual(allumees, [1])
        self.assertFalse(Instance.courante().relance_auto)
        sortie = Path(tempfile.mkdtemp()) / "x.json"
        self.addCleanup(shutil.rmtree, sortie.parent, True)
        flux = io.BytesIO(json.dumps([{"model": "collecte.tacheexport", "pk": 1, "fields": {"statut": "attente"}},
                                      {"model": "collecte.tacheimport", "pk": 1, "fields": {"statut": "en_cours"}}]).encode())
        SA.assainir_json(flux, sortie)
        self.assertEqual([o["fields"]["statut"] for o in json.loads(sortie.read_text())], ["interrompue", "interrompue"])

    @unittest.skipUnless(SQLITE, "copie SQLite : base SQLite seulement")
    def test_relances_automatiques_eteintes_sqlite(self):
        Instance.courante()  # ligne de l'installation présente dans la base copiée
        a = archive_d_ailleurs(self.ext / "rs.zip", [compte(900, "alice@exemple.test")], format_base="sqlite",
                               sql_en_plus=["UPDATE parametres_instance SET relance_auto = 1;"])
        import sqlite3
        import zipfile

        with zipfile.ZipFile(a) as z, tempfile.TemporaryDirectory() as tmp:
            z.extract(SV.BASE_SQLITE, tmp)
            c = sqlite3.connect(Path(tmp) / SV.BASE_SQLITE)
            try:  # l'archive porte bien les relances allumées
                self.assertEqual(c.execute("SELECT relance_auto FROM parametres_instance").fetchone()[0], 1)
            finally:
                c.close()
        self.restaurer(a)
        self.assertFalse(Instance.courante().relance_auto)

    def test_json_imbrique_sans_fin_refus_propre(self):
        """Seconde relecture : un « database.json » imbriqué très profondément levait RecursionError (erreur 500 sur la page
        de confirmation)."""
        import zipfile

        a = archive_d_ailleurs(self.ext / "p.zip", [compte(900, "alice@exemple.test")])
        profond = self.ext / "profond.zip"
        with zipfile.ZipFile(a) as src, zipfile.ZipFile(profond, "w") as z:
            for n in src.namelist():
                donnees = src.read(n)
                if n == SV.BASE_JSON:
                    donnees = b'[{"model": "parametres.instance", "pk": 1, "fields": {"nom": ' + b"[" * 200000 + b"]" * 200000 + b"}}]"
                z.writestr(n, donnees)
        plan, refus = self.apercu(profond)
        self.assertIsNone(plan)
        self.assertTrue(refus)
        with self.assertRaises(SV.ErreurSauvegarde):
            self.restaurer(profond)

    def test_lecture_json_bornee(self):
        lourd = b'[{"model": "a", "pk": 1, "fields": {"t": "' + b"x" * 5000 + b'"}}]'
        with self.assertRaises(ValueError):
            list(SA._objets_json(io.BytesIO(lourd), max_objet=1000))
        self.assertEqual(len(list(SA._objets_json(io.BytesIO(lourd), max_objet=10000))), 1)
        with self.assertRaises(ValueError):  # objet jamais fermé : refusé dès la borne, sans tout lire en mémoire
            list(SA._objets_json(io.BytesIO(b'[{"t": "' + b"y" * 50000), max_objet=1000))
