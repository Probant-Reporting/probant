"""Formules très imbriquées ou très longues : erreur de formule claire (« Formule trop complexe »), jamais une erreur 500
(RecursionError), dans la fiche KPI comme dans les règles de Cohérence."""
from django.test import SimpleTestCase
from django.urls import reverse

from collecte.models import RegleCoherence
from parametres.aides_tests.referentiel import Base, FETCH
from referentiel import formule as F
from referentiel.models import KPI, Niveau


def imbriquee(n, coeur="1"):
    return "(" * n + coeur + ")" * n


class AnalyseurTests(SimpleTestCase):
    def test_formules_trop_complexes_refusees(self):
        for texte in (imbriquee(400), "-" * 1500 + "1", "+".join(["1"] * 2000), imbriquee(60, "[EFF]")):
            with self.subTest(texte=texte[:20]), self.assertRaisesMessage(F.FormuleInvalide, "Formule trop complexe"):
                F.analyser(texte)

    def test_formules_raisonnables_acceptees(self):
        self.assertEqual(F.evaluer(F.analyser(imbriquee(40, "[EFF] * 2")), lambda r: 3), 6)
        self.assertEqual(F.evaluer(F.analyser(" + ".join(["[EFF]"] * 150)), lambda r: 1), 150)


class FormulesImbriqueesPagesTests(Base):
    def test_fiche_kpi(self):
        calc = KPI(code="ZZ400", libelle="Test", type_saisie_id="Calculé", granularite_id=Niveau.ENTITY, methode_agregation="Somme")
        res = self.enregistrer_fiche(calc, code="ZZ400", formule=imbriquee(400, "[EFF]"))
        self.assertFalse(res["ok"])
        self.assertIn("Formule trop complexe", res["html"])
        self.assertFalse(KPI.objects.filter(code="ZZ400").exists())

    def test_regle_de_coherence(self):
        self.client.force_login(self.admin)
        donnees = {"nom": "Prof", "gauche": imbriquee(400), "operateur": "<=", "droite": "[EFF]", "tolerance": "0",
                   "niveau": "Entity", "bloquante": "on", "actif": "on"}
        for action in ("tester", "enregistrer"):
            rep = self.client.post(reverse("collecte:regle_nouvelle"), {**donnees, "action": action}, **FETCH)
            self.assertEqual(rep.status_code, 200)
            self.assertIn("Formule trop complexe", rep.json()["html"])
        self.assertFalse(RegleCoherence.objects.exists())
