"""Valeur enregistrée (``models.valeur_enregistree``) : une valeur tapée, importée (import actuel ou ancien import) ou
calculée est réduite aux 10 décimales que la base garde avec la même règle, la moitié en s'éloignant de zéro, et non
au pair : la même valeur ne diffère jamais à la 10e décimale selon son chemin."""
import io
from decimal import Decimal as D

from django.test import SimpleTestCase
from openpyxl import Workbook

from . import echange as E
from . import imports as I
from . import saisie as S
from .models import Reponse, valeur_enregistree
from .aides_tests.echanges import Base
from .outils_tests import xlsx

ENTETES = ["ID KPI", "Organisation", "Exercice", "Valeur"]


class RegleTests(SimpleTestCase):
    def test_moitie_en_s_eloignant_de_zero(self):
        self.assertEqual(valeur_enregistree(D("0.00000000025")), D("3E-10"))  # au pair : 2E-10
        self.assertEqual(valeur_enregistree(D("-0.00000000025")), D("-3E-10"))
        self.assertEqual(valeur_enregistree(D("12.5")), D("12.5"))
        self.assertEqual(str(valeur_enregistree(D("-0.00000000001"))), "0E-10")  # pas de « -0 »


class MemeValeurPartoutTests(Base):
    """« 0,000000025 % » = 2,5E-10 en fraction : 3E-10 enregistré, tapé ou importé."""

    def test_saisie(self):
        self.assertEqual(S.lire_nombre("0,000000025", self.taux), D("3E-10"))

    def test_import(self):
        a = I.analyser(self.admin, xlsx([ENTETES, ["TX", "E1", 2026, "0,000000025"]]), campagne_defaut=self.c.pk)
        self.assertEqual(a.lignes[0].valeur, D("3E-10"))

    def test_ancien_import(self):
        wb = Workbook()
        ws = wb.active
        ws.append(["ID KPI", "Organisation", "Year", "Result"])
        ws.append(["TX", "E1", 2024, "0.000000025"])
        flux = io.BytesIO()
        wb.save(flux)
        flux.seek(0)
        E.importer_valeurs(flux)
        self.assertEqual(Reponse.objects.get(kpi=self.taux, organisation=self.e1, periode__debut__year=2024).valeur, D("3E-10"))
