"""Isolation des espaces : ce qui est créé dans un espace est invisible dans l'autre (pages, exports, preuves, session,
rôles), les sauvegardes d'un espace n'emportent ni le registre ni les fichiers des autres, une restauration croisée est
refusée, la réconciliation suit une restauration."""
import datetime
import json
import shutil
import sqlite3
import tempfile
import zipfile
from pathlib import Path

from django.contrib.sessions.backends.db import SessionStore
from django.core.files.base import ContentFile
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from collecte.models import Preuve, Reponse
from parametres import sauvegardes as SV
from referentiel.models import Organisation, Utilisateur

from . import contexte as E
from .essais import EspacesTestCase
from .models import Compte, Espace, Installation, MarqueEspace
from .session import SessionEspace
from .aides_tests import creer
from collecte.aides_tests.espaces import jeu

PAGES = ["/saisie/", "/tableau-de-bord/", "/visualisation/", "/coherence/", "/administration/organisations/",
         "/administration/comptes/", "/administration/journal/", "/administration/campagnes/", "/referentiel/",
         "/import-export/", "/tableau-de-bord/relances/", "/attributions/"]


class DonneesTests(EspacesTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.admin = creer("admin@exemple.example", "admin")
        creer("admin@exemple.example", "admin", "essai")
        cls.org_rse, cls.c_rse, cls.r_rse = jeu("principal", "Siège RSE", "KPI-RSE")
        cls.org_ach, cls.c_ach, cls.r_ach = jeu("essai", "Usine Achats", "KPI-ACH")

    def setUp(self):
        self.client.force_login(Utilisateur.objects.get(pk=self.admin.pk))

    def test_pages(self):
        for page in PAGES:
            ici = self.client.get(page)
            la = self.client.get("/espace/essai" + page)
            self.assertEqual(ici.status_code, la.status_code, page)
            for r, absent in ((ici, "Usine Achats"), (ici, "KPI-ACH"), (la, "Siège RSE"), (la, "KPI-RSE")):
                self.assertNotIn(absent, r.content.decode(), page)

    def test_objet_d_un_autre_espace_par_son_numero(self):
        org_seule = self.org_ach.pk if not Organisation.objects.filter(pk=self.org_ach.pk).exists() else None
        if org_seule:
            r = self.client.get(f"/administration/organisations/{org_seule}/")
            self.assertEqual(r.status_code, 404)
        with E.activer("essai"):
            self.assertFalse(Reponse.objects.filter(kpi_id="KPI-RSE").exists())
        self.assertFalse(Reponse.objects.filter(kpi_id="KPI-ACH").exists())

    def test_export_excel(self):
        r = self.client.get("/espace/essai/import-export/exporter/", {"format": "xlsx"})
        self.assertIn(r.status_code, (200, 302, 400, 405))

    def test_gros_export_d_un_autre_espace(self):
        """Gros export en arrière-plan (collecte/exports_arriere_plan.py) : sa tâche et son fichier restent dans leur
        espace ; par l'adresse de l'autre espace, rien (404), même avec le même numéro."""
        from django.core.files.storage import default_storage

        from collecte import exports_arriere_plan as EAP
        from collecte.models import TacheExport

        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        with override_settings(MEDIA_ROOT=f"{tmp}/files", ESPACES_DOSSIER=f"{tmp}/espaces-donnees"):
            with E.activer("essai"):
                u = Utilisateur.objects.get(email="admin@exemple.example")
                chemin = default_storage.save("exports/achats.csv", ContentFile(b"Usine Achats"))
                t = TacheExport.objects.create(utilisateur=u, titre="Export Achats", statut=TacheExport.Statut.PRET, chemin=chemin,
                                               nom_fichier="achats.csv", empreinte=EAP.empreinte(u),
                                               expire_le=timezone.now() + datetime.timedelta(days=1))
            self.assertFalse(TacheExport.objects.filter(pk=t.pk).exists())
            for suffixe in ("fichier", "etat"):
                self.assertEqual(self.client.get(f"/import-export/exports/{t.pk}/{suffixe}/").status_code, 404, suffixe)
            self.assertNotContains(self.client.get("/import-export/"), "Export Achats")
            self.assertContains(self.client.get("/espace/essai/import-export/"), "Export Achats")
            rep = self.client.get(f"/espace/essai/import-export/exports/{t.pk}/fichier/")
            self.assertEqual(b"".join(rep.streaming_content), b"Usine Achats")

    def test_journal_separe(self):
        from collecte.models import Journal

        with E.activer("essai"):
            Journal.ecrire(Utilisateur.objects.get(pk=self.admin.pk), "reglage_identite", self.org_ach, "nom", "", "Achats")
            n = Journal.objects.count()
        self.assertEqual(Journal.objects.filter(objet_id=str(self.org_ach.pk), apres="Achats").count(), 0)
        self.assertGreaterEqual(n, 1)


class SessionTests(EspacesTestCase):
    def test_cles_de_l_outil_propres_a_chaque_espace(self):
        s = SessionStore()
        s["campagne"] = 1
        v = SessionEspace(s, "essai")
        self.assertNotIn("campagne", v)
        v["campagne"] = 7
        v["_messages"] = "commun"
        self.assertEqual((s["campagne"], s["espace:essai:campagne"], v["campagne"]), (1, 7, 7))
        self.assertEqual(s["_messages"], "commun")
        self.assertEqual(sorted(v.keys()), ["_messages", "campagne"])


class RolesParEspaceTests(EspacesTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        creer("premier@exemple.example", "admin")
        cls.u = creer("lecteur@exemple.example", "lecteur")
        creer("lecteur@exemple.example", "auditeur", "essai")

    def test_lecteur_ici_auditeur_la(self):
        self.client.force_login(Utilisateur.objects.get(pk=self.u.pk))
        self.assertEqual(self.client.get("/historique/").status_code, 403)
        self.assertEqual(self.client.get("/espace/essai/historique/").status_code, 200)
        self.assertEqual(self.client.post("/espace/essai/administration/organisations/nouvelle/", {"nom": "X"}).status_code, 403)


class PreuvesTests(EspacesTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.admin = creer("admin@exemple.example", "admin")
        creer("admin@exemple.example", "admin", "essai")
        cls.org, cls.c, cls.r = jeu("essai", "Usine Achats", "KPI-ACH")

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        reglages = override_settings(MEDIA_ROOT=self.tmp / "files", ESPACES_DOSSIER=self.tmp / "espaces-donnees")
        reglages.enable()
        self.addCleanup(reglages.disable)
        self.client.force_login(Utilisateur.objects.get(pk=self.admin.pk))

    def test_preuve_rangee_dans_son_espace(self):
        with E.activer("essai"):
            p = Preuve.objects.create(reponse=self.r, fichier=ContentFile(b"%PDF-1.4 achats", name="facture.pdf"))
        chemin = self.tmp / "espaces-donnees" / "essai" / "files" / p.fichier.name
        self.assertTrue(chemin.is_file())
        self.assertFalse((self.tmp / "files").exists() and any((self.tmp / "files").rglob("*.pdf")))
        r = self.client.get(f"/espace/essai/preuve/{p.pk}/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(b"".join(r.streaming_content), b"%PDF-1.4 achats")
        self.assertEqual(self.client.get(f"/preuve/{p.pk}/").status_code, 404)  # jamais par l'adresse du principal

    def test_dossiers_des_espaces_hors_des_fichiers_du_principal(self):
        principal = E.dossier_medias("principal").resolve()
        autre = E.dossier_medias("essai").resolve()
        self.assertNotIn(principal, autre.parents)


@override_settings()
class SauvegardesTests(TransactionTestCase):
    databases = {"default", "commun", "espace_essai"}

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        reglages = override_settings(MEDIA_ROOT=self.tmp / "media", SAUVEGARDES_DIR=self.tmp / "sauvegardes",
                                     ESPACES_DOSSIER=self.tmp / "espaces-donnees")
        reglages.enable()
        self.addCleanup(reglages.disable)
        from parametres import niveaux as N
        from parametres import referentiel as PR

        for code in ("principal", "essai"):  # réglages des migrations, effacés par le test précédent
            with E.activer(code):
                N.creer_par_defaut()
                PR.creer_par_defaut()
        Installation.objects.create(identifiant="installation-essai")
        Espace.objects.create(code="principal", nom="RSE", etat="actif")
        Espace.objects.create(code="essai", nom="Achats", etat="actif")
        MarqueEspace.objects.create(code="principal", installation="installation-essai")
        MarqueEspace.objects.using("espace_essai").create(code="essai", installation="installation-essai")
        self.u = creer("admin@exemple.example", "admin", "essai")
        creer("rse@exemple.example", "admin")
        self.org, self.c, self.r = jeu("essai", "Usine Achats", "KPI-ACH")
        jeu("principal", "Siège RSE", "KPI-RSE")
        with E.activer("principal"):
            Preuve.objects.create(reponse=Reponse.objects.get(kpi_id="KPI-RSE"), fichier=ContentFile(b"rse", name="rse.pdf"))
        with E.activer("essai"):
            Preuve.objects.create(reponse=self.r, fichier=ContentFile(b"achats", name="achats.pdf"))

    def archive(self, format_base=None):
        with E.activer("essai"):
            return SV.creer("essai", format_base)

    def test_archive_d_un_espace_seulement(self):
        a = self.archive()
        self.assertTrue(str(a.chemin).startswith(str(self.tmp / "sauvegardes" / "spaces" / "essai")))
        with zipfile.ZipFile(a.chemin) as z:
            noms = z.namelist()
            d = json.loads(z.read("backup.json"))
            z.extract("database.sqlite3", self.tmp) if "database.sqlite3" in noms else None
            base_json = z.read("database.json").decode() if "database.json" in noms else ""
        self.assertEqual((d["espace"], d["identifiant_installation"]), ("essai", "installation-essai"))
        fichiers = [n for n in noms if n.startswith("files/")]
        self.assertTrue(fichiers and all("achats" in n for n in fichiers), fichiers)
        if base_json:
            self.assertNotIn("espaces.compte", base_json)
            self.assertNotIn("Siège RSE", base_json)
        else:
            tables = {t for (t,) in sqlite3.connect(self.tmp / "database.sqlite3").execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertNotIn("espaces_compte", tables)
            self.assertNotIn("django_session", tables)
        self.assertEqual(SV.archives(), [])  # rien dans les sauvegardes du principal

    def test_archive_json_sans_le_registre(self):
        a = self.archive("json")
        with zipfile.ZipFile(a.chemin) as z:
            base = z.read("database.json").decode()
        self.assertNotIn('"espaces.compte"', base)
        self.assertNotIn('"sessions.session"', base)
        self.assertNotIn("Siège RSE", base)
        self.assertIn("Usine Achats", base)

    def test_restauration_croisee_refusee(self):
        a = self.archive()
        with self.assertRaisesMessage(SV.ErreurSauvegarde, "espace « essai »"):
            SV.restaurer(a.chemin)  # dans l'espace principal
        Installation.objects.update(identifiant="autre-installation")
        with E.activer("essai"), self.assertRaisesMessage(SV.ErreurSauvegarde, "autre installation"):
            SV.restaurer(a.chemin)

    def test_archive_ancienne_seulement_dans_le_principal(self):
        a = self.archive()
        ancienne = self.tmp / "ancienne.zip"
        with zipfile.ZipFile(a.chemin) as z, zipfile.ZipFile(ancienne, "w") as w:
            for n in z.namelist():
                contenu = z.read(n)
                if n == "backup.json":
                    d = json.loads(contenu)
                    d.pop("espace"), d.pop("identifiant_installation")
                    contenu = json.dumps(d)
                w.writestr(n, contenu)
        with E.activer("essai"), self.assertRaises(SV.ErreurSauvegarde):
            SV.restaurer(ancienne)

    def test_restauration_puis_reconciliation(self):
        a = self.archive()
        with E.activer("essai"):
            u = Utilisateur.objects.get(pk=self.u.pk)
            u.set_password("Change-apres-2026")
            u.save()
            Organisation.objects.filter(pk=self.org.pk).update(nom="Renommée")
            SV.restaurer(a.chemin, sauvegarder_avant=False)
            self.assertEqual(Organisation.objects.get(pk=self.org.pk).nom, "Usine Achats")
            self.assertTrue(Utilisateur.objects.get(pk=self.u.pk).check_password("Change-apres-2026"))  # registre
            self.assertEqual(Preuve.objects.get().fichier.read(), b"achats")
        self.assertTrue(Compte.objects.filter(pk=self.u.pk).exists())
        self.assertEqual(Organisation.objects.filter(nom="Siège RSE").count(), 1)  # le principal n'a pas bougé
        self.assertTrue((self.tmp / "media" / Preuve.objects.get().fichier.name).is_file())

    def test_registre(self):
        chemin = SV.creer_registre("essai")
        Compte.objects.filter(pk=self.u.pk).update(first_name="Changé")
        SV.restaurer_registre(chemin)
        self.assertEqual(Compte.objects.get(pk=self.u.pk).first_name, "Prénom")
        self.assertEqual(Espace.objects.count(), 2)


class DossiersImbriquesTests(EspacesTestCase):
    """L'IT a placé le dossier des espaces et celui des sauvegardes sous le dossier des fichiers de l'espace principal :
    la sauvegarde du principal ne les emporte pas ; sa restauration ne les efface pas et n'y écrit rien, même avec une
    archive piégée."""

    def test_sauvegarde_et_restauration_du_principal(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        media = tmp / "media"
        reglages = override_settings(DOSSIER_DONNEES=tmp, MEDIA_ROOT=media, ESPACES_DOSSIER=media / "espaces",
                                     SAUVEGARDES_DIR=media / "sauvegardes")
        reglages.enable()
        self.addCleanup(reglages.disable)
        (media / "preuves").mkdir(parents=True)
        (media / "preuves" / "p.pdf").write_bytes(b"%PDF preuve")
        (media / "espaces" / "achats").mkdir(parents=True)
        (media / "espaces" / "achats" / "base.sqlite3").write_bytes(b"base achats")
        a = SV.creer("essai", format_base="json")
        with zipfile.ZipFile(a.chemin) as z:
            noms = z.namelist()
        self.assertIn("files/preuves/p.pdf", noms)
        self.assertEqual([n for n in noms if n.startswith(("files/espaces", "files/sauvegardes"))], [])
        piege = tmp / "piege.zip"
        with zipfile.ZipFile(a.chemin) as z, zipfile.ZipFile(piege, "w") as w:
            for info in z.infolist():
                w.writestr(info, z.read(info))
            w.writestr("files/espaces/achats/base.sqlite3", b"ecrasee")
        with zipfile.ZipFile(piege) as z:
            SV._restaurer_fichiers(z)
        self.assertEqual((media / "espaces" / "achats" / "base.sqlite3").read_bytes(), b"base achats")
        self.assertTrue(a.chemin.exists())
        self.assertEqual((media / "preuves" / "p.pdf").read_bytes(), b"%PDF preuve")
