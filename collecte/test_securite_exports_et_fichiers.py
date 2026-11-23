"""Sécurité (avant la première installation) : tabulation et retour chariot neutralisés dans les
exports, classeur piégé (plage démesurée) refusé sans saturer le serveur, preuve servie selon le fichier rangé,
en-tête X-Forwarded-For lu seulement derrière un proxy HTTPS, archive piégée refusée à la restauration."""
import io
import shutil
import tempfile
import time
import zipfile
from collections import namedtuple
from pathlib import Path
from unittest import mock

from django.core.cache import cache, caches
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from openpyxl import Workbook

from parametres import sauvegardes as SV

from . import fichiers as X
from .models import Preuve, Reponse
from .aides_tests.echanges import Base


def classeur_plage(ref, cellules):
    """Classeur de quelques Ko dont la balise « dimension » annonce la plage ``ref`` (ex. A1:XFD1048576)."""
    wb = Workbook()
    for coord, v in cellules:
        wb.active[coord] = v
    f = io.BytesIO()
    wb.save(f)
    src = zipfile.ZipFile(io.BytesIO(f.getvalue()))
    sortie = io.BytesIO()
    with zipfile.ZipFile(sortie, "w", zipfile.ZIP_DEFLATED) as z:
        for n in src.namelist():
            d = src.read(n)
            if n == "xl/worksheets/sheet1.xml":
                debut = d.index(b"<dimension ")
                d = d[:debut] + f'<dimension ref="{ref}"/>'.encode() + d[d.index(b"/>", debut) + 2:]
            z.writestr(n, d)
    return SimpleUploadedFile("piege.xlsx", sortie.getvalue())


class ExportsTabulationTests(TestCase):
    def test_tabulation_et_retour_chariot(self):
        for v in ("\t=1+1", "\r=1+1", "=1+1", "@SUM(A1)"):
            self.assertTrue(X.valeur_csv(v, "fr").startswith("'"), repr(v))
        self.assertEqual(X.valeur_csv("Texte\tavec tabulation", "fr"), "Texte\tavec tabulation")
        self.assertEqual(X.texte("'\t=1+1"), "\t=1+1")  # relu tel qu'il a été écrit


class ClasseurPiegeTests(TestCase):
    def test_plage_demesuree_lue_sans_la_croire(self):
        """5 Ko qui annoncent 16 384 colonnes × 2 000 lignes : avant, 33 millions de cellules en mémoire (300 Mo, 5 s) ;
        un million de lignes saturait le serveur."""
        f = classeur_plage("A1:XFD1048576", [("A1", "ID KPI"), ("B1", "Valeur"), ("A2", "EFF"), ("B2", 3), ("XFD1048576", None)])
        t = time.monotonic()
        lignes = X.lire(f)["Sheet"]
        self.assertLess(time.monotonic() - t, 60)  # avant la correction : des minutes ; large marge pour une machine chargée
        self.assertEqual(lignes[:2], [["ID KPI", "Valeur"], ["EFF", 3]])
        self.assertTrue(all(len(l) <= 2 for l in lignes))

    def test_trop_de_cellules(self):
        f = classeur_plage("A1:C3", [("A1", 1), ("C3", 2)])
        self.assertEqual(X.lire(f)["Sheet"], [[1, None, None], [None, None, None], [None, None, 2]])  # plage normale : inchangé
        with mock.patch.object(X, "CELLULES_MAX", 5):
            with self.assertRaisesMessage(X.FichierInvalide, "Ce fichier a trop de cellules une fois ouvert"):
                X.lire(classeur_plage("A1:C3", [("A1", 1), ("C3", 2)]))


class PreuveServieTests(Base):
    def test_type_selon_le_fichier_range(self):
        r = Reponse.objects.get(kpi=self.eff, organisation=self.e1, periode=self.c.periode)
        p = Preuve.objects.create(reponse=r, fichier=ContentFile(b"%PDF-1.4 <script>alert(1)</script>", name="f.pdf"),
                                  nom_fichier="facture.html")  # nom affiché trompeur (base restaurée, par exemple)
        self.client.force_login(self.contrib)
        rep = self.client.get(reverse("collecte:preuve", args=[p.pk]))
        self.assertEqual(rep["Content-Type"], "application/pdf")
        self.assertEqual(rep["X-Content-Type-Options"], "nosniff")
        ancien = Path(p.fichier.path)
        ancien.rename(ancien.with_suffix(".html"))
        Preuve.objects.filter(pk=p.pk).update(fichier=p.fichier.name.replace(".pdf", ".html"))
        rep = self.client.get(reverse("collecte:preuve", args=[p.pk]))
        self.assertEqual(rep["Content-Type"], "application/octet-stream")
        self.assertTrue(rep["Content-Disposition"].startswith("attachment"))


class AdresseForgeeTests(Base):
    def setUp(self):
        super().setUp()
        cache.clear()
        caches["connexion"].clear()  # compteur des essais de connexion (cache dédié)
        self.contrib.set_password("bon-mot-de-passe-2026")
        self.contrib.save()

    def essai(self, mdp, xff):
        return self.client.post(reverse("login"), {"username": "contrib@exemple.test", "password": mdp},
                                REMOTE_ADDR="10.1.2.3", HTTP_X_FORWARDED_FOR=xff)

    def test_sans_proxy_l_en_tete_ne_compte_pas(self):
        """Outil sans proxy sur le réseau de l'entreprise : changer X-Forwarded-For à chaque essai ne lève plus le blocage."""
        for i in range(5):
            self.essai("faux", f"203.0.113.{i}")
        self.assertContains(self.essai("bon-mot-de-passe-2026", "203.0.113.99"), "Trop d'essais")

    @override_settings(HTTPS=True)
    def test_derriere_un_proxy_https(self):
        for i in range(5):
            self.essai("faux", "203.0.113.7")
        self.assertContains(self.essai("bon-mot-de-passe-2026", "203.0.113.7"), "Trop d'essais")
        self.assertEqual(self.essai("bon-mot-de-passe-2026", "198.51.100.4").status_code, 302)


class ArchivePiegeeTests(TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.reglages = override_settings(MEDIA_ROOT=self.tmp / "media", SAUVEGARDES_DIR=self.tmp / "sauvegardes")
        self.reglages.enable()

    def tearDown(self):
        self.reglages.disable()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_trop_grosse_pour_le_disque(self):
        chemin = self.tmp / "piege.zip"
        with zipfile.ZipFile(chemin, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("files/zeros.bin", b"\0" * (20 * 1024 * 1024))  # 20 Mo de zéros : quelques Ko compressés
        self.assertLess(chemin.stat().st_size, 100_000)
        Usage = namedtuple("Usage", "total used free")
        with mock.patch.object(SV.shutil, "disk_usage", return_value=Usage(0, 0, 110 * 1024 * 1024)):
            with self.assertRaisesMessage(SV.ErreurSauvegarde, "trop volumineuse"):
                SV.controler_place(chemin)
        SV.controler_place(chemin)  # place réelle suffisante : accepté
