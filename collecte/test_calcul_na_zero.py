"""Règles du projet : ce qui change, et ce qui ne change pas.

1. CALC-01 : dans une somme, une source N/A compte comme 0 (case de la fiche KPI, migration referentiel/0016) ;
2. CALC-13 : un KPI facultatif du référentiel ne compte nulle part et n'est jamais relancé (la case reste saisissable) ;
3. CALC-09 : sous la granularité d'un paramètre hérité, une organisation sans ancêtre de ce niveau a sa propre case ;
4. un KPI cité dans une formule ne devient pas oui / non ou liste (« Ce KPI est utilisé dans la formule de … ») ;
5. P4-bis : les imports appliquent les mêmes contrôles de format que la fiche KPI ;
6. P9 : en-tête « Code KPI » du fichier du référentiel (l'ancien en-tête « id_… » reste lu), type « GHG » créé à la demande ;
7. une unité « nombre entier » (comptage) donne toujours 0 décimale au KPI."""
from decimal import Decimal
from importlib import import_module

from django.apps import apps as django_apps
from django.test import TestCase
from django.urls import reverse

from parametres.models import Unite
from parametres.referentiel import unite_depuis_symbole as U
from referentiel.formule import NA, additive
from referentiel.models import KPI, Niveau, TravailApresMiseAJour

from . import reglages as R
from . import saisie as S
from .calcul import Calculateur, recalculer
from .models import Campagne, Journal, Reponse
from .aides_tests.arbre_france import Arbre
from referentiel.models import Organisation

D = Decimal
FETCH = {"HTTP_X_REQUESTED_WITH": "fetch"}
MIGRATION = import_module("referentiel.migrations.0016_na_compte_zero_entiers")


# ---------------------------------------------------------------- 1. N/A compté comme 0 dans les sommes (CALC-01)
class NaCompteZeroTests(Arbre):
    """Le constat : S1 = [FIXE] + [MOBILE] + [FUG] ; E2 : 400 + 200 et FUG N/A. Avant : S1 E2 = N/A, S1 France = 160."""

    def setUp(self):
        super().setUp()
        for code in ("FIXE", "MOBILE", "FUG"):
            self.kpi(code)
        self.s1 = self.kpi("S1", "Calculé", "[FIXE] + [MOBILE] + [FUG]")
        for code, v in (("FIXE", 100), ("MOBILE", 50), ("FUG", 10)):
            self.saisir(code, self.e1, v)
        self.saisir("FIXE", self.e2, 400)
        self.saisir("MOBILE", self.e2, 200)
        self.saisir("FUG", self.e2, na=True)

    def test_case_cochee_d_office_pour_une_somme(self):
        self.assertTrue(self.s1.na_compte_zero)
        for formule, attendu in (("[A] - [B] + 10", True), ("-([A] + [B])", True), ("[A] / [B]", False), ("[A] * 2", False),
                                 ("([A] + [B]) / 2", False), ("12", False), ("[A] +", False)):
            self.assertEqual(additive(formule), attendu, formule)
        ratio = self.kpi("RATIO", "Calculé", "[FIXE] / [MOBILE]", agg="Formule")
        self.assertFalse(ratio.na_compte_zero)
        saisi = self.kpi("SAISI")
        self.assertFalse(saisi.na_compte_zero)
        choisi = KPI(code="CHOISI", type_saisie_id="Calculé", formule="[FIXE] + [FUG]", granularite_id=Niveau.ENTITY,
                     methode_agregation="Somme", na_compte_zero=False)
        choisi.na_compte_zero_choisi = True  # choix explicite (fiche, fichier importé) : gardé
        choisi.save()
        self.assertFalse(KPI.objects.get(code="CHOISI").na_compte_zero)

    def test_total_de_l_entite_et_du_pays(self):
        recalculer(self.c)
        e2 = self.cellule("S1", self.e2)
        self.assertEqual((e2.valeur, e2.non_applicable, e2.statut), (D(600), False, Reponse.Statut.CALCULE))
        self.assertEqual(e2.message_calcul, "FUG : N/A, compté comme 0")
        self.assertEqual(self.cellule("S1", self.e1).message_calcul, "")
        self.assertEqual(self.cellule("S1", self.fr).valeur, D(760))  # avant : 160, E2 disparaissait sans message
        self.assertEqual(self.cellule("S1", self.g).valeur, D(760))
        self.assertFalse(Journal.objects.filter(objet="Reponse").exists())  # pas de ligne de journal à chaque calcul

    def test_toutes_les_sources_na_donne_na(self):
        Reponse.objects.filter(kpi_id__in=["FIXE", "MOBILE"], organisation=self.e2).update(valeur=None, non_applicable=True)
        calc = Calculateur(self.c)
        self.assertIs(calc.valeur("S1", self.e2.id), NA)
        self.assertEqual(calc.message("S1", self.e2.id), "")
        self.assertEqual(calc.valeur("S1", self.fr.id), D(160))  # somme des enfants : N/A exclus

    def test_case_decochee_regle_d_avant(self):
        KPI.objects.filter(code="S1").update(na_compte_zero=False)
        calc = Calculateur(self.c)
        self.assertIs(calc.valeur("S1", self.e2.id), NA)
        self.assertEqual(calc.message("S1", self.e2.id), "Résultat N/A parce que FUG est N/A.")
        self.assertEqual(calc.valeur("S1", self.fr.id), D(160))

    def test_source_manquante_reste_incomplet(self):
        Reponse.objects.filter(kpi_id="MOBILE", organisation=self.e2).delete()
        calc = Calculateur(self.c)
        self.assertIsNone(calc.valeur("S1", self.e2.id))
        self.assertEqual(calc.message("S1", self.e2.id), "Source manquante : MOBILE")
        self.assertIsNone(calc.valeur("S1", self.fr.id))

    def test_ratio_coche_quotient_par_na_donne_na(self):
        r = self.kpi("PART", "Calculé", "[FUG] / [FIXE]", agg="Formule", na_compte_zero=True)
        q = self.kpi("PAR_FUG", "Calculé", "[FIXE] / [FUG]", agg="Formule", na_compte_zero=True)
        calc = Calculateur(self.c)
        self.assertEqual(calc.valeur(r.code, self.e2.id), D(0))  # 0 / 400
        self.assertEqual(calc.message(r.code, self.e2.id), "FUG : N/A, compté comme 0")
        self.assertIs(calc.valeur(q.code, self.e2.id), NA)  # division par une source N/A : N/A, pas une erreur
        self.assertEqual(calc.message(q.code, self.e2.id), "")

    def test_periode_citee_dans_le_message(self):
        self.kpi("VAR", "Calculé", "[FIXE] - [FIXE@N-1]")
        self.saisir("FIXE", self.e2, na=True, camp=self.c0)
        calc = Calculateur(self.c)
        self.assertEqual(calc.valeur("VAR", self.e2.id), D(400))
        self.assertEqual(calc.message("VAR", self.e2.id), "FIXE@N-1 : N/A, compté comme 0")

    def test_periode_cloturee_figee(self):
        for code, v in (("FIXE", 300), ("MOBILE", 100)):
            self.saisir(code, self.e2, v, camp=self.c0)
        self.saisir("FUG", self.e2, na=True, camp=self.c0)
        Reponse.objects.create(periode=self.c0.periode, kpi_id="S1", organisation=self.e2, non_applicable=True,
                               origine=Reponse.Origine.CALCUL, statut=Reponse.Statut.CALCULE)
        self.kpi("VAR_S1", "Calculé", "[S1] - [S1@N-1]")
        calc = Calculateur(self.c)
        self.assertIs(calc.valeur("S1", self.e2.id, self.c0.periode), NA)  # valeur enregistrée de 2025 : elle fait foi
        self.assertEqual(calc.valeur("VAR_S1", self.e2.id), D(600))  # 600 − N/A (compté comme 0)
        self.assertEqual(calc.message("VAR_S1", self.e2.id), "S1@N-1 : N/A, compté comme 0")


class FicheKpiNaZeroTests(Arbre):
    """La case de la fiche KPI : proposée, journalisée, et elle refait les calculs de la campagne ouverte."""

    def setUp(self):
        super().setUp()
        for code in ("ELEC", "FROID"):
            self.kpi(code)
        self.total = self.kpi("TOTAL", "Calculé", "[ELEC] + [FROID]")
        self.saisir("ELEC", self.e1, 120)
        self.saisir("FROID", self.e1, na=True)
        recalculer(self.c)
        self.client.force_login(self.admin)

    def donnees(self, kpi, **changes):
        d = {c: getattr(kpi, f"{c}_id" if c in ("granularite", "type_saisie", "type_reponse", "unite") else c) for c in R.CHAMPS_FICHE}
        d.update(changes)
        return {c: v for c, v in d.items() if v not in (False, None)}

    def test_case_dans_la_fiche_et_journal(self):
        url = reverse("collecte:referentiel_kpi", args=["TOTAL"])
        html = self.client.get(url, **FETCH).json()["html"]
        self.assertIn('name="na_compte_zero" checked', html)
        self.assertIn("Une source N/A compte comme 0", html)
        self.assertEqual(self.cellule("TOTAL", self.e1).valeur, D(120))
        res = self.client.post(url, self.donnees(self.total, na_compte_zero=False), **FETCH).json()
        self.assertTrue(res["ok"], res["html"])
        self.total.refresh_from_db()
        self.assertFalse(self.total.na_compte_zero)
        self.assertTrue(Journal.objects.filter(action="reglage_kpi", objet_id="TOTAL", champ="na_compte_zero", avant="True",
                                               apres="False").exists())
        self.assertTrue(self.cellule("TOTAL", self.e1).non_applicable)  # campagne ouverte recalculée aussitôt
        self.client.post(url, self.donnees(self.total, na_compte_zero="on"), **FETCH)
        self.assertEqual(self.cellule("TOTAL", self.e1).valeur, D(120))

    def test_creation_garde_le_choix_de_l_admin(self):
        base = self.donnees(self.total, code="TOT2", nom__fr="Total 2", formule="[ELEC] + [FROID]")
        base.pop("na_compte_zero")
        res = self.client.post(reverse("collecte:referentiel_kpi_nouveau"), base, **FETCH).json()
        self.assertTrue(res["ok"], res["html"])
        self.assertFalse(KPI.objects.get(code="TOT2").na_compte_zero)  # décochée par l'admin : gardé
        html = self.client.get(reverse("collecte:referentiel_kpi_nouveau"), **FETCH).json()["html"]
        balise = html.split('name="na_compte_zero"')[1].split(">")[0]  # nouveau KPI : la page la propose d'après la formule
        self.assertNotIn("checked", balise)
        self.assertNotIn("data-touchee", balise)

    def test_tester_la_formule_suit_la_case(self):
        url = reverse("collecte:referentiel_kpi", args=["TOTAL"])
        avec = self.client.post(url, {**self.donnees(self.total), "action": "tester", "campagne_test": self.c.pk}, **FETCH).json()["html"]
        self.assertIn("FROID : N/A, compté comme 0", avec)
        sans = self.donnees(self.total, action="tester", campagne_test=self.c.pk)
        sans.pop("na_compte_zero")
        self.assertIn("Résultat N/A parce que FROID est N/A.", self.client.post(url, sans, **FETCH).json()["html"])

    def test_panneau_et_detail_de_l_agregat(self):
        html = self.client.get(reverse("collecte:cellule", args=[self.c.pk, "TOTAL", self.e1.pk]), **FETCH).json()["html"]
        self.assertIn("FROID : N/A, compté comme 0", html)  # sous le résultat
        self.assertIn("N/A, compté comme 0</strong>", html)  # composante du calcul
        html = self.client.get(reverse("collecte:cellule", args=[self.c.pk, "TOTAL", self.fr.pk]), **FETCH).json()["html"]
        self.assertIn('agregat-message">FROID : N/A, compté comme 0', html)  # détail de l'agrégat : la ligne de E1


class MigrationNaZeroTests(Arbre):
    """referentiel/0016 : la case cochée pour les sommes seulement ; 0 décimale pour une unité entière ; recalcul posé."""

    def test_sommes_cochees_les_autres_non(self):
        for code, formule in (("SOMME", "[A] + [B] - 3"), ("RATIO", "[A] / [B]"), ("PRODUIT", "([A] + [B]) * 2"),
                              ("PAREN", "([A]) + (-[B])")):
            self.kpi(code, "Calculé", "", agg="Formule")
            KPI.objects.filter(code=code).update(formule=formule, na_compte_zero=False)  # comme une base d'avant la case
        self.kpi("A")
        self.kpi("B")
        MIGRATION.cocher_sommes(django_apps, None)
        self.assertEqual(dict(KPI.objects.filter(code__in=["SOMME", "RATIO", "PRODUIT", "PAREN"]).values_list("code", "na_compte_zero")),
                         {"SOMME": True, "RATIO": False, "PRODUIT": False, "PAREN": True})
        self.assertTrue(MIGRATION.est_somme("[K1] + [K2] + [K3]"))
        self.assertFalse(MIGRATION.est_somme("[A/B] / 2"))  # un « / » dans un code ne trompe pas, celui de la formule si
        self.assertTrue(MIGRATION.est_somme("[A/B] + 2"))
        self.assertFalse(MIGRATION.est_somme(""))

    def test_unites_entieres_et_travail_pose(self):
        k = self.kpi("EFF", unite=U("salariés"))
        KPI.objects.filter(pk=k.pk).update(decimales=2)
        MIGRATION.entiers_sans_decimale(django_apps, None)
        self.assertEqual(KPI.objects.get(pk="EFF").decimales, 0)
        MIGRATION.poser_recalcul(django_apps, None)
        self.assertTrue(TravailApresMiseAJour.objects.filter(code="recalcul").exists())


class TravauxApresMiseAJourTests(Arbre):
    """Le recalcul posé par la migration est fait une fois, avec le code installé : campagnes ouvertes seulement."""

    def setUp(self):
        super().setUp()
        for code in ("ELEC", "FROID"):
            self.kpi(code)
        self.kpi("TOTAL", "Calculé", "[ELEC] + [FROID]")
        for camp in (self.c0, self.c):
            self.saisir("ELEC", self.e1, 120, camp=camp)
            self.saisir("FROID", self.e1, na=True, camp=camp)
            Reponse.objects.create(periode=camp.periode, kpi_id="TOTAL", organisation=self.e1, non_applicable=True,
                                   origine=Reponse.Origine.CALCUL, statut=Reponse.Statut.CALCULE)  # calculé avant la mise à jour

    def test_recalcul_une_fois_campagnes_ouvertes(self):
        from .mise_a_jour import faire_les_travaux

        TravailApresMiseAJour.objects.create(code="recalcul", motif="Essai.")
        TravailApresMiseAJour.objects.create(code="plus_tard", motif="Travail d'une version plus récente.")
        self.assertEqual(faire_les_travaux(), ["recalcul"])
        self.assertEqual(self.cellule("TOTAL", self.e1).valeur, D(120))
        self.assertTrue(self.cellule("TOTAL", self.e1, self.c0).non_applicable)  # 2025 clôturé : figé
        self.assertEqual(list(TravailApresMiseAJour.objects.values_list("code", flat=True)), ["plus_tard"])
        self.assertEqual(faire_les_travaux(), [])  # rien à refaire

    def test_echec_garde_le_travail(self):
        from unittest import mock

        from . import mise_a_jour as M

        TravailApresMiseAJour.objects.create(code="recalcul")
        with mock.patch.dict(M.TRAVAUX, {"recalcul": mock.Mock(side_effect=RuntimeError("panne"))}), \
                self.assertLogs("reporting.mise_a_jour", "ERROR"):
            self.assertEqual(M.faire_les_travaux(), [])
        self.assertTrue(TravailApresMiseAJour.objects.filter(code="recalcul").exists())  # refait au prochain démarrage

    def test_migrate_fait_le_travail(self):
        from io import StringIO

        from django.core.management import call_command

        TravailApresMiseAJour.objects.create(code="recalcul", motif="Essai.")
        sortie = StringIO()
        call_command("migrate", verbosity=1, stdout=sortie)  # base déjà à jour : seulement les travaux posés
        self.assertIn("After the update: Essai.", sortie.getvalue())
        self.assertFalse(TravailApresMiseAJour.objects.exists())
        self.assertEqual(self.cellule("TOTAL", self.e1).valeur, D(120))

    def test_installation_neuve_sans_message(self):
        from io import StringIO

        from django.core.management import call_command

        Campagne.objects.all().delete()  # aucune campagne : rien à refaire, rien à annoncer
        TravailApresMiseAJour.objects.create(code="recalcul", motif="Essai.")
        sortie = StringIO()
        call_command("migrate", verbosity=1, stdout=sortie)
        self.assertNotIn("After the update", sortie.getvalue())
        self.assertFalse(TravailApresMiseAJour.objects.exists())


# ---------------------------------------------------------------- 7. unité entière : 0 décimale
class UniteEntiereTests(Arbre):
    def setUp(self):
        super().setUp()
        self.salaries = U("salariés")
        self.assertTrue(self.salaries.entier)
        self.kwh = Unite.objects.create(code="kWh_t", symbole="kWh", decimales=1)
        self.eff = self.kpi("EFF", unite=self.kwh, decimales=1)
        self.client.force_login(self.admin)

    def donnees(self, **changes):
        d = {c: getattr(self.eff, f"{c}_id" if c in ("granularite", "type_saisie", "type_reponse", "unite") else c)
             for c in R.CHAMPS_FICHE}
        d.update(changes)
        return {c: v for c, v in d.items() if v not in (False, None)}

    def test_fiche_verrouille_et_journalise(self):
        url = reverse("collecte:referentiel_kpi", args=["EFF"])
        html = self.client.get(url, **FETCH).json()["html"]
        self.assertIn(f'value="{self.salaries.code}" data-decimales="0" data-entier="1"', html)
        self.assertNotIn("readonly", html.split('name="decimales"')[1].split(">")[0])
        res = self.client.post(url, self.donnees(unite=self.salaries.code, decimales="3"), **FETCH).json()
        self.assertTrue(res["ok"], res["html"])
        self.eff.refresh_from_db()
        self.assertEqual(self.eff.decimales, 0)
        self.assertTrue(Journal.objects.filter(objet_id="EFF", champ="decimales", avant="1", apres="0").exists())
        html = self.client.get(url, **FETCH).json()["html"]
        self.assertIn("readonly", html.split('name="decimales"')[1].split(">")[0])  # verrouillé à 0
        self.assertIn('id="aide-decimales-entier">', html)

    def test_creation_et_import_de_configuration(self):
        from . import configuration as C

        k = KPI.objects.create(code="NB", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY, unite=self.salaries, decimales=2)
        self.assertEqual(k.decimales, 0)
        _, lignes = C.lignes_kpi([KPI.objects.get(code="NB")], [], [])
        self.assertIn(0, lignes[0])

    def test_affichage(self):
        from .templatetags import collecte as T

        k = KPI.objects.create(code="NB", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY, unite=self.salaries)
        self.assertEqual(T.valeur(Reponse(valeur=D(12)), k), "12 salariés")
        self.assertEqual(S.valeur_pour_saisie(Reponse(valeur=D(12)), k), "12")


class FichiersNaZeroEtEntiersTests(TestCase):
    """La case « N/A compté comme 0 » et les décimales d'une unité entière passent par le fichier référentiel (paquet) et le
    classeur de configuration : un choix explicite est gardé, un ancien fichier sans la case suit la formule."""

    def setUp(self):
        from .aides_tests.paquets import Base

        Base.setUpTestData.__func__(type(self))  # référentiel R1 : C = A + B (somme), D = A × FE1 (produit)
        self.r1, self.admin = type(self).r1, type(self).admin

    def test_fichier_referentiel(self):
        from . import paquets as P
        from .aides_tests.paquets import fichier, kp, vider

        self.assertEqual(dict(KPI.objects.filter(code__in=["C", "D"]).values_list("code", "na_compte_zero")), {"C": True, "D": False})
        KPI.objects.filter(code="C").update(na_compte_zero=False)  # choix de l'admin sur une somme
        p = P.extraire(self.r1)
        self.assertEqual((kp(p, "C")["na_compte_zero"], kp(p, "D")["na_compte_zero"]), (False, False))
        relu = P.lire(fichier(p))
        self.assertIs(kp(relu, "C")["na_compte_zero"], False)
        self.assertTrue(P.analyser(relu).aucune_difference)
        ancien = P.lire(fichier(p))
        for k in ancien.kpis:  # fichier d'avant la case : la case de l'installation est gardée
            k["na_compte_zero"] = None
        self.assertTrue(P.analyser(ancien).aucune_difference)
        kp(relu, "C")["na_compte_zero"] = True
        ligne = next(l for l in P.analyser(relu).kpis if l.code == "C")
        self.assertIn(("Source N/A comptée comme 0", "Non", "Oui"), ligne.diff_kpi)
        vider()  # autre installation : sans la case dans le fichier, d'après la formule ; sinon, celle du fichier
        P.appliquer(self.admin, P.analyser(ancien))
        self.assertTrue(KPI.objects.get(code="C").na_compte_zero)
        vider()
        P.appliquer(self.admin, P.analyser(P.lire(fichier(p))))
        self.assertFalse(KPI.objects.get(code="C").na_compte_zero)

    def test_classeur_de_configuration(self):
        import io

        from django.core.files.uploadedfile import SimpleUploadedFile
        from openpyxl import load_workbook

        from . import configuration as C

        U("salariés")
        wb = load_workbook(io.BytesIO(C.exporter().content))
        ws = wb["KPI"]
        tete = [c.value for c in ws[1]]
        col = tete.index("Source N/A comptée comme 0") + 1
        ligne_c = next(r for r in range(2, ws.max_row + 1) if ws.cell(r, 1).value == "C")
        self.assertEqual(ws.cell(ligne_c, col).value, "Oui")
        ws.cell(ligne_c, col, "Non")
        ws.cell(ligne_c, tete.index("Unité") + 1, "salariés")  # unité de comptage : 0 décimale
        flux = io.BytesIO()
        wb.save(flux)
        a = C.analyser(SimpleUploadedFile("conf.xlsx", flux.getvalue()))
        ch = next(c for c in a.onglets["KPI"] if c.cle == "C")
        self.assertIn(("Source N/A comptée comme 0", "Oui", "Non"), ch.champs)
        self.assertIn(("Décimales", 2, 0), ch.champs)
        C.appliquer(self.admin, SimpleUploadedFile("conf.xlsx", flux.getvalue()))
        c = KPI.objects.get(code="C")
        self.assertEqual((c.na_compte_zero, c.decimales), (False, 0))


# ---------------------------------------------------------------- 4 et 5. format d'un KPI cité dans une formule, imports (P4-bis)
class FormatEtFormulesTests(Arbre):
    """EFF (nombre, une réponse) et SRC (nombre, sans réponse) sont cités par DBL = [EFF] * 2 et DBL2 = [SRC] + 1 ; POL
    est oui / non. Avant : la fiche refusait seulement le format d'un KPI qui a des réponses, les imports pas du tout."""

    def setUp(self):
        super().setUp()
        from parametres.models import TypeReponse

        self.oui_non = TypeReponse.objects.create(code="OuiNon", libelle="Oui / non", format="oui_non", ordre=10)
        self.eff, self.src, self.lib = self.kpi("EFF"), self.kpi("SRC"), self.kpi("LIB")
        self.pol = self.kpi("POL", agg="Décompte", type_reponse=self.oui_non)
        self.kpi("DBL", "Calculé", "[EFF] * 2")
        self.kpi("DBL2", "Calculé", "[SRC@N-1] + 1")
        self.saisir("EFF", self.e1, 10)

    def test_motifs(self):
        self.assertEqual(R.motif_cite_en_formule("nombre", {"DBL"}), "")
        self.assertEqual(R.motif_cite_en_formule("oui_non", set()), "")
        self.assertTrue(R.motif_cite_en_formule("liste", {"DBL"}).startswith("Ce KPI est utilisé dans la formule de DBL : "))
        self.assertTrue(R.motif_cite_en_formule("oui_non", {"B", "A"}).startswith("Ce KPI est utilisé dans les formules de A, B : "))
        self.assertEqual(R.citations()["SRC"], {"DBL2"})  # toutes périodes : [SRC@N-1] compte
        self.assertEqual(R.citations({"DBL2": "[LIB] + 1"}).get("SRC"), None)  # formule du fichier, à la place de la sienne
        self.assertTrue(R.motif_format_fige("EFF", self.eff.type_reponse, self.oui_non).startswith("Ce KPI a déjà 1 réponse (nombre)"))
        self.assertEqual(R.motif_format_fige("SRC", self.src.type_reponse, self.oui_non), "")

    def historique(self, dossier, changes):
        """Le référentiel exporté au format historique (ancien format technique), avec ``changes`` : {code : {colonne : valeur}}."""
        from openpyxl import load_workbook

        from referentiel.echange import exporter_kpi

        chemin = f"{dossier}/referentiel.xlsx"
        exporter_kpi(chemin)
        wb = load_workbook(chemin)
        ws = wb["KPI"]
        tete = [c.value for c in ws[1]]
        for r in range(2, ws.max_row + 1):
            for colonne, valeur in changes.get(ws.cell(r, 1).value, {}).items():
                ws.cell(r, tete.index(colonne) + 1, valeur)
        wb.save(chemin)
        return chemin

    def test_import_du_referentiel_historique(self):
        import tempfile

        from referentiel.echange import importer_kpi

        oui_non = {"type_reponse": "OuiNon", "methode_agregation": "Décompte"}
        with tempfile.TemporaryDirectory() as d:
            r = importer_kpi(self.historique(d, {"EFF": oui_non, "SRC": oui_non}))
            erreurs = {i: m for _, i, m in r.erreurs}
            self.assertEqual(set(erreurs), {"EFF", "SRC"})
            self.assertIn("Ce KPI a déjà 1 réponse (nombre)", erreurs["EFF"])  # même contrôle que la fiche KPI (P4-bis)
            self.assertIn("Ce KPI est utilisé dans la formule de DBL :", erreurs["EFF"])
            self.assertTrue(erreurs["SRC"].startswith("Ce KPI est utilisé dans la formule de DBL2 :"))
            self.assertEqual(KPI.objects.get(code="SRC").format, "nombre")  # import annulé
            r = importer_kpi(self.historique(d, {"DBL": {"formule": "[POL] * 2"}}))  # réciproque : avant, acceptée
            self.assertEqual([(i, m) for _, i, m in r.erreurs],
                             [("DBL", "Réponse oui / non, liste ou texte rédigé, pas un nombre : POL ne peut pas entrer dans une formule.")])
            r = importer_kpi(self.historique(d, {"LIB": oui_non, "DBL2": {"formule": "[EFF] + 1"}, "SRC": oui_non}))
            self.assertEqual(r.erreurs, [])  # SRC n'est plus cité après l'import : il peut devenir oui / non
        self.assertEqual((KPI.objects.get(code="LIB").format, KPI.objects.get(code="SRC").format), ("oui_non", "oui_non"))

    def test_classeur_de_configuration(self):
        import io

        from django.core.files.uploadedfile import SimpleUploadedFile
        from openpyxl import load_workbook

        from . import configuration as C

        wb = load_workbook(io.BytesIO(C.exporter().content))
        ws = wb["KPI"]
        tete = [c.value for c in ws[1]]
        for r in range(2, ws.max_row + 1):
            if ws.cell(r, 1).value in ("EFF", "SRC", "LIB"):
                ws.cell(r, tete.index("Type de réponse") + 1, "Oui / non")
                ws.cell(r, tete.index("Agrégation") + 1, "Décompte")
        flux = io.BytesIO()
        wb.save(flux)
        a = C.analyser(SimpleUploadedFile("conf.xlsx", flux.getvalue()))
        lignes = {c.cle: c for c in a.onglets["KPI"]}
        self.assertEqual((lignes["EFF"].action, lignes["SRC"].action, lignes["LIB"].action), ("rejet", "rejet", "modifier"))
        self.assertTrue(lignes["EFF"].motif.startswith("Ce KPI a déjà 1 réponse (nombre)"))
        self.assertTrue(lignes["SRC"].motif.startswith("Ce KPI est utilisé dans la formule de DBL2 :"))
        self.assertNotEqual(lignes["DBL2"].action, "rejet")  # sa source reste un nombre : la formule se calcule
        C.appliquer(self.admin, SimpleUploadedFile("conf.xlsx", flux.getvalue()))  # tout ou rien : rien
        self.assertEqual([KPI.objects.get(code=c).format for c in ("EFF", "SRC", "LIB")], ["nombre", "nombre", "nombre"])
        for r in range(2, ws.max_row + 1):  # les lignes refusées remises comme avant : le reste passe
            if ws.cell(r, 1).value in ("EFF", "SRC"):
                ws.cell(r, tete.index("Type de réponse") + 1, "Numérique")
                ws.cell(r, tete.index("Agrégation") + 1, "Somme")
        flux = io.BytesIO()
        wb.save(flux)
        C.appliquer(self.admin, SimpleUploadedFile("conf.xlsx", flux.getvalue()))
        self.assertEqual([KPI.objects.get(code=c).format for c in ("EFF", "SRC", "LIB")], ["nombre", "nombre", "oui_non"])


class FormatFichierReferentielTests(TestCase):
    """Fichier référentiel (paquet) : A, source de C = A + B et de D = A × FE1, ne devient pas oui / non."""

    def setUp(self):
        from .aides_tests.paquets import Base

        Base.setUpTestData.__func__(type(self))
        self.r1, self.admin = type(self).r1, type(self).admin

    def test_kpi_cite_ne_devient_pas_oui_non(self):
        from . import paquets as P
        from .aides_tests.paquets import fichier, kp

        p = P.extraire(self.r1)
        kp(p, "A").update(type_reponse="OuiNon", methode_agregation="Décompte")
        kp(p, "B").update(type_reponse="OuiNon", methode_agregation="Décompte")
        kp(p, "C").update(formule="[A] * 2")  # B n'est plus cité après l'import : il peut changer
        a = P.analyser(P.lire(fichier(p)), {"kpi:A": "mettre_a_jour", "kpi:B": "mettre_a_jour", "kpi:C": "mettre_a_jour"})
        lignes = {l.code: l for l in a.kpis}
        self.assertEqual(lignes["A"].statut, "rejet")
        self.assertTrue(lignes["A"].motif.startswith("Ce KPI est utilisé dans les formules de C, D :"), lignes["A"].motif)
        self.assertNotEqual(lignes["B"].statut, "rejet")
        self.assertNotEqual(lignes["C"].statut, "rejet")


class ComptagesTests(TestCase):
    """(21) une décimale est refusée pour un comptage (unité « nombre entier »), à la saisie, à l'import, et une unité ne
    devient pas entière (ni un KPI) quand des valeurs décimales existent."""

    def test_import_refuse_une_decimale(self):
        from django.core.exceptions import ValidationError

        from parametres.models import Unite
        from referentiel.models import KPI, Niveau

        from . import saisie as S

        from parametres import niveaux as N
        N.creer_par_defaut()
        u = Unite.objects.create(code="pers", symbole="pers.", entier=True, decimales=0)
        k = KPI.objects.create(code="EFF", libelle="Effectif", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY, unite=u)
        with self.assertRaises(ValidationError):
            S.lire_nombre("12,5", k)
        self.assertEqual(S.lire_nombre("12", k), 12)


class MigrationComptagesTests(TestCase):
    """Migration collecte/0027 : un KPI qui a déjà des réponses décimales avec une unité entière passe sur une copie non
    entière de son unité ; les autres KPI de l'unité, et toutes les valeurs, ne changent pas."""

    def test_copie_non_entiere_de_l_unite(self):
        import datetime
        from decimal import Decimal
        from importlib import import_module

        from django.apps import apps as django_apps

        from parametres import niveaux as N
        from parametres.models import Unite
        from referentiel.models import KPI, Niveau, Organisation

        from .models import Journal, Periode, Reponse

        N.creer_par_defaut()
        emp = Unite.objects.create(code="employees", symbole="employees", libelle="salariés", entier=True, decimales=0,
                                   traductions={"en": {"libelle": "employees"}})
        moyen = KPI.objects.create(code="MOY", libelle="Effectif moyen", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY,
                                   unite=emp, decimales=0)
        fin = KPI.objects.create(code="FIN", libelle="Effectif fin", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY,
                                 unite=emp, decimales=0)
        o = Organisation.objects.create(nom="E1", niveau_id=Niveau.ENTITY)
        p = Periode.objects.create(type="annee", debut=datetime.date(2025, 1, 1), fin=datetime.date(2025, 12, 31), libelle="2025")
        Reponse.objects.create(periode=p, kpi=moyen, organisation=o, valeur=Decimal("12.5"), origine="saisie")
        Reponse.objects.create(periode=p, kpi=fin, organisation=o, valeur=Decimal("13"), origine="saisie")
        import_module("collecte.migrations.0027_comptages_decimaux").copier_unites(django_apps, None)
        moyen.refresh_from_db()
        fin.refresh_from_db()
        self.assertEqual(fin.unite_id, "employees")
        copie = moyen.unite
        self.assertEqual((copie.code, copie.symbole, copie.entier, copie.libelle), ("employees_decimal", "employees", False,
                                                                                  "salariés (décimal)"))
        self.assertEqual(copie.traductions["en"]["libelle"], "employees (decimal)")
        self.assertEqual(moyen.decimales, 1)
        self.assertEqual(Reponse.objects.get(kpi_id="MOY").valeur, Decimal("12.5"))
        self.assertTrue(Journal.objects.filter(objet_id="MOY", champ="unite").exists())
        # la saisie d'une décimale reste possible pour ce KPI
        from . import saisie as S

        self.assertEqual(S.lire_nombre("11,5", moyen), Decimal("11.5"))


class TotalAvecSourceNATests(TestCase):
    """P1 (CALC-01) : dans un total (formule qui n'est qu'une somme), une composante N/A compte
    comme 0 et le détail du calcul le dit ; le total n'est N/A que si toutes ses composantes le sont. Case de la fiche
    KPI décochée : la composante N/A rend le total N/A, et le panneau dit laquelle."""

    def setUp(self):
        self.g = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        self.e1 = Organisation.objects.create(nom="E1", niveau_id=Niveau.ENTITY, parent=self.g)
        self.c = Campagne.objects.create(exercice=2026, statut=Campagne.Statut.OUVERTE)
        for code in ("ELEC", "FROID"):
            KPI.objects.create(code=code, type_saisie_id="Saisi", granularite_id=Niveau.ENTITY, methode_agregation="Somme")
        KPI.objects.create(code="TOTAL", type_saisie_id="Calculé", formule="[ELEC] + [FROID]", granularite_id=Niveau.ENTITY,
                           methode_agregation="Somme")

    def saisir(self, kpi, v=None, na=False):
        Reponse.objects.create(periode=self.c.periode, kpi_id=kpi, organisation=self.e1, valeur=None if na else D(v),
                               non_applicable=na, origine=Reponse.Origine.SAISIE, statut=Reponse.Statut.VALIDE)

    def test_total_compte_na_comme_zero(self):
        self.saisir("ELEC", 120000)
        self.saisir("FROID", na=True)
        calc = Calculateur(self.c)
        self.assertEqual(calc.valeur("TOTAL", self.e1.id), D(120000))
        self.assertEqual(calc.message("TOTAL", self.e1.id), "FROID : N/A, compté comme 0")
        recalculer(self.c.periode)
        r = Reponse.objects.get(periode=self.c.periode, kpi_id="TOTAL", organisation=self.e1)
        self.assertEqual((r.valeur, r.non_applicable, r.statut), (D(120000), False, Reponse.Statut.CALCULE))
        self.assertEqual(r.message_calcul, "FROID : N/A, compté comme 0")
        g = Reponse.objects.get(periode=self.c.periode, kpi_id="TOTAL", organisation=self.g)
        self.assertEqual(g.valeur, D(120000))  # le total remonte

    def test_case_decochee_total_na_explique_sans_conseil(self):
        KPI.objects.filter(code="TOTAL").update(na_compte_zero=False)
        self.saisir("ELEC", 120000)
        self.saisir("FROID", na=True)
        calc = Calculateur(self.c)
        self.assertIs(calc.valeur("TOTAL", self.e1.id), NA)
        self.assertEqual(calc.message("TOTAL", self.e1.id), "Résultat N/A parce que FROID est N/A.")

    def test_toutes_sources_na_sans_message(self):
        self.saisir("ELEC", na=True)
        self.saisir("FROID", na=True)
        calc = Calculateur(self.c)
        self.assertIs(calc.valeur("TOTAL", self.e1.id), NA)
        self.assertEqual(calc.message("TOTAL", self.e1.id), "")  # vraiment non applicable : rien à expliquer

    def test_formule_du_socle_energie(self):
        from referentiel import formule as F
        from referentiel.bibliotheque.socles import KPIS

        formule = KPIS["NRJ-TOTAL"]["formule"]
        refs = {r.kpi for r in F.refs_additives(F.analyser(formule))}
        self.assertIn("NRJ-FROID", refs)
        self.assertNotIn("CONV-FIOUL", refs)  # facteur d'un produit : son N/A n'appelle pas « saisir 0 »

    def test_na_dans_un_quotient_sans_conseil(self):
        KPI.objects.create(code="RATIO", type_saisie_id="Calculé", formule="[ELEC] / [FROID]", granularite_id=Niveau.ENTITY,
                           methode_agregation="Formule")
        self.saisir("ELEC", 120000)
        self.saisir("FROID", na=True)
        calc = Calculateur(self.c)
        self.assertIs(calc.valeur("RATIO", self.e1.id), NA)
        self.assertEqual(calc.message("RATIO", self.e1.id), "")

    def test_zero_au_lieu_de_na(self):
        self.saisir("ELEC", 120000)
        self.saisir("FROID", 0)
        calc = Calculateur(self.c)
        self.assertEqual(calc.valeur("TOTAL", self.e1.id), D(120000))
        self.assertEqual(calc.message("TOTAL", self.e1.id), "")
