from decimal import Decimal
from pathlib import Path

from django.test import TestCase

from referentiel.formule import NA
from referentiel.models import KPI, Niveau, Organisation

from .calcul import Calculateur, recalculer
from .models import Campagne, Reponse

D = Decimal


class MoteurTests(TestCase):
    """Arbre : Groupe > Pays > 2 entités > 1 site chacune."""

    def setUp(self):
        self.g = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        self.p = Organisation.objects.create(nom="Pays", niveau_id=Niveau.COUNTRY, parent=self.g)
        self.e1 = Organisation.objects.create(nom="E1", niveau_id=Niveau.ENTITY, parent=self.p)
        self.e2 = Organisation.objects.create(nom="E2", niveau_id=Niveau.ENTITY, parent=self.p)
        self.s1 = Organisation.objects.create(nom="S1", niveau_id=Niveau.SITE, parent=self.e1)
        self.s2 = Organisation.objects.create(nom="S2", niveau_id=Niveau.SITE, parent=self.e2)
        self.c = Campagne.objects.create(exercice=2026, statut=Campagne.Statut.OUVERTE)
        self.c0 = Campagne.objects.create(exercice=2025, statut=Campagne.Statut.CLOTUREE)

    def kpi(self, i, t="Saisi", f="", gran=Niveau.ENTITY, agg="Somme"):
        return KPI.objects.create(code=i, type_saisie_id=t, formule=f, granularite_id=gran, methode_agregation=agg)

    def saisir(self, kpi, org, v, camp=None, na=False, origine=Reponse.Origine.IMPORT):
        return Reponse.objects.create(periode=(camp or self.c).periode, kpi_id=kpi, organisation=org, valeur=None if na else D(v),
                                      non_applicable=na, origine=origine)

    def test_somme_et_na(self):
        self.kpi("EFF")
        self.saisir("EFF", self.e1, 10)
        self.saisir("EFF", self.e2, 0, na=True)
        calc = Calculateur(self.c)
        self.assertEqual(calc.valeur("EFF", self.p.id), D(10))
        self.assertEqual(calc.valeur("EFF", self.g.id), D(10))

    def test_tous_na_donne_na(self):
        self.kpi("EFF")
        self.saisir("EFF", self.e1, 0, na=True)
        self.saisir("EFF", self.e2, 0, na=True)
        self.assertIs(Calculateur(self.c).valeur("EFF", self.p.id), NA)

    def test_enfant_manquant_rend_incomplet(self):
        self.kpi("EFF")
        self.saisir("EFF", self.e1, 10)
        calc = Calculateur(self.c)
        self.assertIsNone(calc.valeur("EFF", self.p.id))
        self.assertIn("E2", calc.message("EFF", self.p.id))

    def test_ratio_recalcule_au_niveau_superieur(self):
        self.kpi("F")
        self.kpi("T")
        self.kpi("PART", "Calculé", "[F] / [T]", agg="Formule")
        self.saisir("F", self.e1, 1)
        self.saisir("T", self.e1, 4)
        self.saisir("F", self.e2, 3)
        self.saisir("T", self.e2, 4)
        calc = Calculateur(self.c)
        self.assertEqual(calc.valeur("PART", self.e1.id), D("0.25"))
        self.assertEqual(calc.valeur("PART", self.p.id), D("0.5"))  # 4 / 8, pas la moyenne des ratios

    def test_facteur_herite_et_emissions_sommees(self):
        self.kpi("CONSO", gran=Niveau.SITE)
        self.kpi("FE1", "FE", gran=Niveau.ENTITY, agg="Aucune")
        self.kpi("EMI", "Calculé", "[CONSO] * [FE1]", gran=Niveau.SITE, agg="Somme")
        self.saisir("CONSO", self.s1, 100)
        self.saisir("CONSO", self.s2, 10)
        self.saisir("FE1", self.e1, 2)
        self.saisir("FE1", self.e2, 3)
        calc = Calculateur(self.c)
        self.assertEqual(calc.valeur("EMI", self.s1.id), D(200))
        self.assertEqual(calc.valeur("EMI", self.p.id), D(230))

    def test_reference_n_moins_1(self):
        self.kpi("CA", gran=Niveau.GROUP, agg="Aucune")
        self.kpi("CROISS", "Calculé", "([CA] - [CA@N-1]) / [CA@N-1]", gran=Niveau.GROUP, agg="Aucune")
        self.saisir("CA", self.g, 110)
        self.saisir("CA", self.g, 100, camp=self.c0)
        self.assertEqual(Calculateur(self.c).valeur("CROISS", self.g.id), D("0.1"))

    def test_division_par_zero_en_erreur(self):
        self.kpi("A")
        self.kpi("B")
        self.kpi("R", "Calculé", "[A] / [B]", agg="Formule")
        self.saisir("A", self.e1, 1)
        self.saisir("B", self.e1, 0)
        recalculer(self.c)
        r = Reponse.objects.get(kpi_id="R", organisation=self.e1)
        self.assertEqual(r.statut, Reponse.Statut.ERREUR)

    def test_recalcul_automatique_apres_saisie(self):
        self.kpi("A")
        self.kpi("DOUBLE", "Calculé", "[A] * 2")
        self.saisir("A", self.e2, 5)
        self.saisir("A", self.e1, 1, origine=Reponse.Origine.SAISIE)  # déclenche le recalcul
        self.assertEqual(Reponse.objects.get(kpi_id="DOUBLE", organisation=self.p).valeur, D(12))
        r = Reponse.objects.get(kpi_id="A", organisation=self.e1)
        r.valeur = D(10)
        r.save()
        self.assertEqual(Reponse.objects.get(kpi_id="DOUBLE", organisation=self.p).valeur, D(30))
        self.assertEqual(Reponse.objects.get(kpi_id="A", organisation=self.g).valeur, D(15))  # agrégation du saisi

    def test_valeur_importee_non_ecrasee(self):
        self.kpi("A")
        self.kpi("C", "Calculé", "[A] * 2")
        self.saisir("C", self.e1, 99, camp=self.c0)  # historique importé d'un KPI calculé
        recalculer(self.c0)
        self.assertEqual(Reponse.objects.get(kpi_id="C", organisation=self.e1, periode=self.c0.periode).valeur, D(99))
        self.assertEqual(Calculateur(self.c0).valeur("C", self.e1.id), D(99))

    def test_organisation_inactive_exclue(self):
        self.kpi("A")
        self.e2.actif = False
        self.e2.save()
        self.saisir("A", self.e1, 7)
        self.assertEqual(Calculateur(self.c).valeur("A", self.p.id), D(7))


class ImportsHistoriquesTests(TestCase):
    """Fichiers historiques : libellé du fichier historique repris en alias, onglet des valeurs trouvé tout seul."""

    def classeur(self, onglets, dossier):
        from openpyxl import Workbook
        wb = Workbook()
        wb.remove(wb.active)
        for nom, lignes in onglets.items():
            ws = wb.create_sheet(nom)
            for l in lignes:
                ws.append(l)
        chemin = Path(dossier) / "f.xlsx"
        wb.save(chemin)
        return chemin

    def test_alias_et_onglet_des_valeurs(self):
        import tempfile

        from referentiel.echange import importer_organisations
        from referentiel.models import OrgAlias

        from .echange import importer_valeurs
        with tempfile.TemporaryDirectory() as d:
            r = importer_organisations(self.classeur({"Organizational structure": [
                ["Level", "Country", "Entity", "Site", "Unit (display)", "Status", "Original tool label"],
                ["Group", "", "", "", "Groupe", "", ""], ["Country", "FR", "", "", "France", "", ""],
                ["Entity", "FR", "E1", "", "Entité 1", "", "FR – E1 (ancien)"]]}, d))
            self.assertEqual(r.erreurs, [])
            self.assertEqual(list(OrgAlias.objects.values_list("source", "libelle")), [("Ancien outil", "FR – E1 (ancien)")])
            KPI.objects.create(code="EFF", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY)
            r = importer_valeurs(self.classeur({"Notes": [["Rien"]], "Valeurs": [
                ["ID KPI", "Result", "Organisation", "Year"], ["EFF", 12, "FR – E1 (ancien)", 2024]]}, d))
        self.assertEqual(r.crees, 1)
        self.assertEqual(Reponse.objects.get().valeur, 12)
