"""Provenance d'un référentiel importé d'un fichier (``paquets.appliquer``) : écrite dans la langue de l'interface de la
personne qui importe, avec la date courte de cette langue (``collecte/dates_courtes.py``). Avant : toujours en français,
avec une date jj/mm/aaaa écrite en dur (« Fichier « paquet.xlsx », importé »), montrée telle quelle dans
la page Partager d'un référentiel en anglais ou en allemand."""
import datetime
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile

from parametres import langues as L

from . import paquets as P
from .aides_tests.paquets import Base, fichier, vider


class ProvenanceDansLaLangue(Base):
    def importer(self, langue):
        brut = fichier(P.extraire(self.r1)).getvalue()
        vider()
        a = P.analyser(P.lire(SimpleUploadedFile("paquet.xlsx", brut)), source="paquet.xlsx")
        with L.activer_interface(langue), mock.patch("django.utils.timezone.localdate", return_value=datetime.date(2026, 3, 1)):
            return P.appliquer(self.admin, a, "paquet.xlsx").referentiel.provenance

    def test_anglais(self):
        provenance = self.importer("en")
        self.assertIn("paquet.xlsx", provenance)
        self.assertIn("01 Mar 2026", provenance)
        self.assertNotIn("importé", provenance)

    def test_allemand(self):
        provenance = self.importer("de")
        self.assertIn("01.03.2026", provenance)
        self.assertNotIn("importé", provenance)

    def test_francais_inchange(self):
        self.assertEqual(self.importer("fr"), "Fichier « paquet.xlsx » de « Ma structure », importé le 01/03/2026")
