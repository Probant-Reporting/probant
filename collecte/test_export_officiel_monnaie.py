"""Classeur officiel de l'EFRAG (norme VS) et monnaie de référence : la devise du rapport (D5)
est la monnaie de référence de l'espace ; un montant n'est écrit que si l'unité de son KPI est celle du modèle dans
cette monnaie. Sinon la cellule reste vide et le rapport le dit : jamais un chiffre dans une autre monnaie ou à une
autre échelle (aucune conversion). L'euro par défaut ne change rien."""
import datetime
import io
import warnings
from decimal import Decimal

import openpyxl
from django.test import TestCase

from parametres.models import Instance, Unite
from referentiel.bibliotheque.formats import vs_efrag as V
from referentiel.models import KPI, Organisation, Referentiel, Utilisateur

from . import export_officiel as X
from . import paquets as P
from .aides_tests.paquets import vider
from .models import Campagne, Periode, Reponse

MONTANTS = {"ECO-TOTAL-BILAN": 8000000, "ECO-CA": "12.5", "SOC-REMU-H-HOMMES": "21.5", "GOV-AMENDES": 1500, "GOV-CORRUPTION": 1}


def regler(code):
    i = Instance.courante()
    i.monnaie = code
    i.save()


class MonnaieTests(TestCase):
    def preparer(self, monnaie_installation="EUR"):
        vider()
        regler(monnaie_installation)
        a = P.analyser(P.fourni("vs_base.json").paquet, fourni=True)
        P.appliquer(None, a)
        self.admin = Utilisateur.objects.create_user("admin", "admin@exemple.test", "x", role=Utilisateur.Role.ADMIN)
        self.groupe = Organisation.objects.create(nom="Exemple SA", niveau_id="Group")
        self.periode = Periode.objects.create(type="annee", debut=datetime.date(2026, 1, 1), fin=datetime.date(2026, 12, 31), libelle="2026")
        for ref in Referentiel.objects.all():
            Campagne.objects.create(referentiel=ref, periode=self.periode, exercice=2026, statut=Campagne.Statut.CLOTUREE)
        for code, v in MONTANTS.items():
            Reponse.objects.create(periode=self.periode, kpi_id=code, organisation=self.groupe, valeur=Decimal(str(v)),
                                   statut=Reponse.Statut.VALIDE)

    def exporter(self):
        donnees, rapport = X.exporter(V.CODE, self.groupe, self.periode, "fr", self.admin)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            wb = openpyxl.load_workbook(io.BytesIO(donnees))
        return rapport, wb

    def test_euro_par_defaut(self):
        self.preparer()
        rapport, wb = self.exporter()
        gi, soc, gov = wb[V.GI], wb[V.SOC], wb[V.GOV]
        self.assertEqual((gi["D5"].value, gi["E278"].value, gi["E279"].value), ("EUR", 8000000, 12500000))
        self.assertEqual((soc["D144"].value, gov["H7"].value), (21.5, 1500))
        self.assertNotIn("montant non repris", " ".join(rapport.messages))

    def test_modele_installe_en_dollars(self):
        self.preparer("USD")
        self.assertEqual(KPI.objects.get(pk="ECO-CA").unite.symbole, "M$")
        rapport, wb = self.exporter()
        gi = wb[V.GI]
        self.assertEqual((gi["D5"].value, gi["E278"].value, gi["E279"].value), ("USD", 8000000, 12500000))
        self.assertEqual(wb[V.GOV]["H7"].value, 1500)

    def test_montants_en_euros_dans_un_rapport_en_dollars_non_ecrits(self):
        self.preparer()
        regler("USD")  # réglage changé après la saisie : les KPI restent en euros, rien n'est converti
        rapport, wb = self.exporter()
        gi, soc, gov = wb[V.GI], wb[V.SOC], wb[V.GOV]
        self.assertEqual(gi["D5"].value, "USD")
        self.assertEqual((gi["E278"].value, gi["E279"].value, soc["D144"].value, gov["H7"].value), (None, None, None, None))
        self.assertTrue(gov["H5"].value)  # « condamnation ou amende » : oui / non, sans montant, reste écrit
        messages = " ".join(rapport.messages)
        self.assertIn("ECO-CA : montant non repris. Son unité « M€ » n'est pas celle du modèle dans la monnaie du rapport (USD).",
                      messages)
        for code in ("ECO-TOTAL-BILAN", "SOC-REMU-H-HOMMES", "GOV-AMENDES"):
            self.assertIn(f"{code} : montant non repris", messages)

    def test_autre_echelle_non_ecrite(self):
        """Un KPI de montant passé en milliers par l'administrateur (« k€ » au lieu de « M€ ») : le classeur attend des
        unités, l'outil multipliait par un million ; la cellule reste vide plutôt qu'un chiffre mille fois trop petit."""
        self.preparer()
        k = KPI.objects.get(pk="ECO-CA")
        k.unite = Unite.objects.create(code="k€", symbole="k€", libelle="millier d'euros", famille="Monnaie")
        k.save()
        rapport, wb = self.exporter()
        self.assertIsNone(wb[V.GI]["E279"].value)
        self.assertEqual(wb[V.GI]["E278"].value, 8000000)
        self.assertIn("ECO-CA : montant non repris. Son unité « k€ »", " ".join(rapport.messages))
