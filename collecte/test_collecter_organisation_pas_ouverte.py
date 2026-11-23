"""Exports d'un exercice : une organisation qui n'y est pas encore ouverte (date d'ouverture, la sienne ou celle d'un
ancêtre, postérieure ; valeurs anciennes gardées après « Je confirme ») n'y figure plus, comme sur les écrans et dans les
totaux (même fonction ``calcul.ouverte``). Ses valeurs restent en base et dans
l'historique de la case.

Données inventées uniquement."""
import datetime

from referentiel.models import Organisation

from . import exports as E
from .aides_tests.echanges import Base
from .models import Reponse


class ExportOrganisationPasOuverteTests(Base):
    def lignes(self, preset):
        p = E.Parametres.depuis(E.PRESETS[preset][2])
        return {(l.periode.libelle, l.kpi.code, l.org.nom) for l in E.collecter(self.admin, p)}

    def test_absente_de_l_exercice_ou_elle_n_est_pas_ouverte(self):
        avant = self.lignes("powerbi")
        self.assertIn(("2025", "EFF", "E1"), avant)  # valeur importée de 2025
        Organisation.objects.filter(pk=self.e1.pk).update(date_ouverture=datetime.date(2026, 1, 1))
        apres = self.lignes("powerbi")
        self.assertNotIn(("2025", "EFF", "E1"), apres)
        self.assertIn(("2026", "EFF", "E1"), apres)  # ouverte en 2026 : exportée
        self.assertTrue(Reponse.objects.filter(periode=self.c0.periode, kpi=self.eff, organisation=self.e1).exists())

    def test_parent_ouvert_plus_tard(self):
        Organisation.objects.filter(pk=self.p.pk).update(date_ouverture=datetime.date(2027, 1, 1))
        self.assertFalse({l for l in self.lignes("powerbi") if l[2] in ("E1", "E2", "Pays")})
