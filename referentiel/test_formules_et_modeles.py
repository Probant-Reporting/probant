from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from . import formule as F
from .models import KPI, KPIFormule, Niveau, Organisation, verifier_formule


class FormuleTests(TestCase):
    def test_references_et_decalages(self):
        refs = F.references("([123456] - [123456@N-1]) / [123456@N-1] + [A@2021]")
        self.assertEqual(refs, [F.Ref("123456"), F.Ref("123456", "N-1"), F.Ref("A", "2021")])

    def test_codes_cites(self):
        texte = "([X] - [Y@N-1]) / [Z@2021] + [X@N-1]"
        self.assertEqual(F.codes_cites(texte), {"X", "Y", "Z"})  # toutes périodes
        self.assertEqual(F.codes_cites(texte, "N"), {"X"})  # même période seulement
        for illisible in ("", None, "[A] +"):
            self.assertEqual(F.codes_cites(illisible), set())

    def test_priorite_des_operateurs(self):
        arbre = F.analyser("[A] + [B] * 2 - -1")
        v = F.evaluer(arbre, lambda r: {"A": Decimal(1), "B": Decimal(3)}[r.kpi])
        self.assertEqual(v, Decimal(8))

    def test_division_par_zero(self):
        with self.assertRaises(F.ErreurCalcul):
            F.evaluer(F.analyser("[A] / [B]"), lambda r: Decimal(5) if r.kpi == "A" else Decimal(0))
        # 0 / 0 : 0 (rien à rapporter, convention du produit)
        self.assertEqual(F.evaluer(F.analyser("[A] / [B]"), lambda r: Decimal(0)), 0)

    def test_na_se_propage(self):
        self.assertIs(F.evaluer(F.analyser("[A] * [B]"), lambda r: F.NA if r.kpi == "A" else Decimal(2)), F.NA)

    def test_source_manquante(self):
        with self.assertRaises(F.ValeurManquante):
            F.evaluer(F.analyser("[A] + 1"), lambda r: None)

    def test_formules_invalides(self):
        for texte in ["", "[A] +", "([A]", "[A] [B]", "import os", "[A] ^ 2"]:
            with self.subTest(texte=texte), self.assertRaises(F.FormuleInvalide):
                F.analyser(texte)


def kpi(i, type_saisie="Saisi", formule="", gran=Niveau.ENTITY, agg="Somme", **kw):
    return KPI.objects.create(code=i, type_saisie_id=type_saisie, formule=formule, granularite_id=gran, methode_agregation=agg, **kw)


class KPITests(TestCase):
    def test_dependances_reconstruites(self):
        kpi("A")
        kpi("B")
        c = kpi("C", "Calculé", "[A] / [B@N-1]", agg="Formule")
        self.assertEqual(set(c.sources.values_list("kpi_source_id", "decalage")), {("A", "N"), ("B", "N-1")})
        c.formule = "[A]"
        c.save()
        self.assertEqual(KPIFormule.objects.filter(kpi_calcule=c).count(), 1)

    def test_reference_inconnue(self):
        with self.assertRaises(ValidationError):
            verifier_formule("X", "[INCONNU] + 1")

    def test_boucle_detectee(self):
        kpi("A")
        kpi("B", "Calculé", "[A] + 1")
        kpi("C", "Calculé", "[B] * 2")
        b = KPI.objects.get(pk="B")
        b.formule = "[C] + 1"
        with self.assertRaises(ValidationError):
            b.full_clean()

    def test_reference_a_n_moins_1_de_soi_meme_autorisee(self):
        kpi("A")
        c = KPI(code="C", type_saisie_id="Calculé", formule="[A] - [C@N-1]", granularite_id=Niveau.ENTITY, methode_agregation="Somme")
        c.full_clean()

    def test_regles_de_configuration(self):
        fe = KPI(code="FE1", type_saisie_id="FE", granularite_id=Niveau.SITE, methode_agregation="Somme")
        self.assertIn("methode_agregation", fe.erreurs_regles())
        saisi = KPI(code="S1", type_saisie_id="Saisi", granularite_id=Niveau.SITE, methode_agregation="Formule")
        self.assertIn("methode_agregation", saisi.erreurs_regles())
        calc = KPI(code="C1", type_saisie_id="Calculé", granularite_id=Niveau.SITE, methode_agregation="Somme")
        self.assertIn("formule", calc.erreurs_regles())


class OrganisationTests(TestCase):
    def test_rattachement_souple(self):
        """Le parent est à n'importe quel niveau supérieur ; le sommet n'a pas de parent."""
        g = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        site = Organisation.objects.create(nom="Site", niveau_id=Niveau.SITE, parent=g)
        site.full_clean()  # un site directement sous le groupe : permis
        for o in (Organisation(nom="G2", niveau_id=Niveau.GROUP, parent=g),  # sommet rattaché
                  Organisation(nom="Sans parent", niveau_id=Niveau.ENTITY),  # sous le sommet sans rattachement
                  Organisation(nom="E sous site", niveau_id=Niveau.ENTITY, parent=site),  # parent plus bas
                  Organisation(nom="S sous site", niveau_id=Niveau.SITE, parent=site)):  # parent du même niveau
            with self.assertRaises(ValidationError, msg=o.nom):
                o.full_clean()
        site.niveau_id = Niveau.GROUP  # passer au niveau du parent : refusé
        with self.assertRaises(ValidationError):
            site.full_clean()
