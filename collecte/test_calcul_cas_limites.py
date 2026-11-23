"""Contrôle qualité du moteur de calcul : cas limites (division par zéro, N/A dans un ratio ou une somme,
négatifs, très grands nombres, pourcentages, [ID@N-1] la première année, organisation inactive, réouverture d'une
campagne clôturée avec des chiffres repris tels quels d'un fichier historique, arrondi comme Excel)."""
from decimal import Decimal

from referentiel.models import Niveau

from .calcul import recalculer
from .models import Campagne, Reponse
from .templatetags.collecte import arrondi, nombre
from .aides_tests.arbre import Arbre

D = Decimal


class CasLimitesTests(Arbre):
    def test_division_par_zero_erreur(self):
        self.kpi("A")
        self.kpi("B")
        self.kpi("R", t="Calculé", f="[A] / [B]", agg="Formule")
        self.saisir("A", self.e1, 10)
        self.saisir("B", self.e1, 0)
        recalculer(self.c)
        r = self.cellule("R", self.e1)
        self.assertIsNone(r.valeur)
        self.assertEqual(r.statut, Reponse.Statut.ERREUR)

    def test_na_dans_un_ratio_reste_na(self):
        self.kpi("A")
        self.kpi("B")
        self.kpi("R", t="Calculé", f="[A] / [B]", agg="Formule")
        self.saisir("A", self.e1, na=True)
        self.saisir("B", self.e1, 4)
        recalculer(self.c)
        self.assertTrue(self.cellule("R", self.e1).non_applicable)

    def test_na_dans_une_somme_compte_zero(self):
        self.kpi("A")
        self.kpi("B")
        k = self.kpi("S", t="Calculé", f="[A] + [B]")
        self.assertTrue(k.na_compte_zero)  # proposé coché pour une somme
        self.saisir("A", self.e1, na=True)
        self.saisir("B", self.e1, 4)
        recalculer(self.c)
        self.assertEqual(self.cellule("S", self.e1).valeur, D(4))

    def test_somme_toutes_sources_na(self):
        self.kpi("A")
        self.kpi("B")
        self.kpi("S", t="Calculé", f="[A] + [B]")
        self.saisir("A", self.e1, na=True)
        self.saisir("B", self.e1, na=True)
        recalculer(self.c)
        self.assertTrue(self.cellule("S", self.e1).non_applicable)

    def test_negatifs_et_grands_nombres(self):
        self.kpi("A")
        self.kpi("B")
        self.kpi("S", t="Calculé", f="[A] - [B]")
        self.saisir("A", self.e1, "123456789012.5")
        self.saisir("B", self.e1, "123456789013.75")
        self.saisir("A", self.e2, "-5")
        self.saisir("B", self.e2, "-7.25")
        recalculer(self.c)
        self.assertEqual(self.cellule("S", self.e1).valeur, D("-1.25"))
        self.assertEqual(self.cellule("S", self.e2).valeur, D("2.25"))
        self.assertEqual(self.cellule("S", self.p).valeur, D("1.00"))

    def test_resultat_trop_grand_erreur_nommee(self):
        self.kpi("A")
        self.kpi("P", t="Calculé", f="[A] * [A]", agg="Formule")
        self.saisir("A", self.e1, "100000000000")
        recalculer(self.c)
        r = self.cellule("P", self.e1)
        self.assertIsNone(r.valeur)
        self.assertEqual(r.statut, Reponse.Statut.ERREUR)

    def test_n_moins_1_la_premiere_annee(self):
        self.kpi("A")
        self.kpi("V", t="Calculé", f="([A] - [A@N-1]) / [A@N-1]", agg="Formule")
        c = Campagne.objects.create(exercice=2021, statut=Campagne.Statut.OUVERTE)
        self.saisir("A", self.e1, 10, camp=c)
        recalculer(c)
        r = self.cellule("V", self.e1, camp=c)
        self.assertIsNone(r.valeur)
        self.assertEqual(r.statut, Reponse.Statut.INCOMPLET)
        self.assertIn("2020", r.message_calcul)

    def test_organisation_inactive_hors_des_totaux(self):
        self.kpi("A")
        self.kpi("B")
        self.kpi("R", t="Calculé", f="[A] / [B]", agg="Formule")
        for o, a, b in ((self.e1, 10, 100), (self.e2, 30, 100)):
            self.saisir("A", o, a)
            self.saisir("B", o, b)
        self.e2.actif = False
        self.e2.save()
        recalculer(self.c)
        self.assertEqual(self.cellule("A", self.p).valeur, D(10))
        self.assertEqual(self.cellule("R", self.p).valeur, D("0.1"))

    def test_organisation_fermee_comptee_quand_elle_etait_ouverte(self):
        """Un site fermé compte dans les totaux des périodes où il était ouvert (désactivé
        après le début de la période), plus ensuite ; sans date de désactivation, il ne compte pas."""
        import datetime

        self.kpi("A")
        for camp in (self.c0, self.c):
            self.saisir("A", self.e1, 10, camp=camp)
            self.saisir("A", self.e2, 30, camp=camp)
        self.c0.statut = Campagne.Statut.OUVERTE
        self.c0.save()
        self.e2.actif = False
        self.e2.date_desactivation = datetime.date(2025, 12, 31)  # fermé fin 2025
        self.e2.save()
        recalculer(self.c0)
        recalculer(self.c)
        self.assertEqual(self.cellule("A", self.p, self.c0).valeur, D(40))  # 2025 : encore ouvert
        self.assertEqual(self.cellule("A", self.p).valeur, D(10))  # 2026 : fermé
        self.e2.date_desactivation = None
        self.e2.save()
        recalculer(self.c0)
        self.assertEqual(self.cellule("A", self.p, self.c0).valeur, D(10))

    def test_ratio_au_dessus_sur_les_sources_agregees(self):
        """Formule au niveau du pays : ratio des sommes (pas somme ni moyenne des ratios)."""
        self.kpi("A")
        self.kpi("B")
        self.kpi("R", t="Calculé", f="[A] / [B]", agg="Formule")
        for o, a, b in ((self.e1, 1, 4), (self.e2, 3, 4)):
            self.saisir("A", o, a)
            self.saisir("B", o, b)
        recalculer(self.c)
        self.assertEqual(self.cellule("R", self.p).valeur, D("0.5"))

    def test_arrondi_comme_excel(self):
        self.assertEqual(arrondi(D("2.5")), D(3))
        self.assertEqual(arrondi(D("-2.5")), D(-3))
        self.assertEqual(arrondi(0.125, 2), D("0.13"))
        self.assertEqual(nombre(D("-0.001"), 2, "en"), "0.00")


class ReouvertureTests(Arbre):
    """Chiffres repris tels quels (origine import) dans une campagne clôturée : jamais écrasés à la réouverture."""

    def test_reouverture_garde_les_chiffres_repris(self):
        self.kpi("A")
        self.kpi("S", t="Calculé", f="[A] * 2")
        self.saisir("A", self.e1, 10, camp=self.c0)
        self.saisir("A", self.e2, 20, camp=self.c0)
        recalculer(self.c0)
        # total du pays et chiffre calculé de E1 publiés par un fichier historique, différents du calcul
        for kid, o, v in (("A", self.p, 31), ("S", self.e1, 21)):
            r = self.cellule(kid, o, camp=self.c0)
            r.valeur, r.origine = D(v), Reponse.Origine.IMPORT
            r.save()
        self.c0.statut = Campagne.Statut.REVUE
        self.c0.save()
        recalculer(self.c0)
        self.assertEqual(self.cellule("A", self.p, camp=self.c0).valeur, D(31))
        self.assertEqual(self.cellule("S", self.e1, camp=self.c0).valeur, D(21))
        self.assertEqual(self.cellule("S", self.e2, camp=self.c0).valeur, D(40))


class NiveauxTests(Arbre):
    def test_kpi_d_entite_cite_au_niveau_pays(self):
        """Formule au pays qui cite un KPI saisi par entité : la somme des entités du pays."""
        self.kpi("A")
        self.kpi("B", gran=Niveau.COUNTRY)
        self.kpi("T", t="Calculé", f="[A] + [B]", gran=Niveau.COUNTRY)
        self.saisir("A", self.e1, 1)
        self.saisir("A", self.e2, 2)
        self.saisir("B", self.p, 10)
        recalculer(self.c)
        self.assertEqual(self.cellule("T", self.p).valeur, D(13))



class TotalRepriseTests(Arbre):
    """Total d'un KPI saisi publié par un fichier historique et repris tel quel (détail incomplet) : il vaut dans les formules
    et les totaux du dessus, comme un chiffre calculé repris tel quel ; il ne remplace jamais un total calculable."""

    def setUp(self):
        super().setUp()
        self.kpi("A")
        self.kpi("T", t="Calculé", f="[A] * 2", gran=Niveau.COUNTRY)
        self.saisir("A", self.e1, 10, camp=self.c0)  # E2 sans valeur : total du pays incomplet
        self.saisir("A", self.e3, 5, camp=self.c0)
        self.saisir("A", self.p, 25, camp=self.c0)  # total publié par un fichier historique, repris tel quel

    def test_total_repris_cite_par_une_formule(self):
        recalculer(self.c0)
        self.assertEqual(self.cellule("T", self.p, camp=self.c0).valeur, D(50))
        self.assertEqual(self.cellule("A", self.g, camp=self.c0).valeur, D(30))
        self.assertEqual(self.cellule("A", self.p, camp=self.c0).valeur, D(25))  # jamais écrasé

    def test_total_calculable_prioritaire(self):
        """Campagne en cours : un total calculable remplace le chiffre importé dans ce qui le cite."""
        self.c0.statut = Campagne.Statut.OUVERTE
        self.c0.save()
        self.saisir("A", self.e2, 20, camp=self.c0)
        recalculer(self.c0)
        self.assertEqual(self.cellule("T", self.p, camp=self.c0).valeur, D(60))  # 10 + 20, pas le 25 publié
        self.assertEqual(self.cellule("A", self.g, camp=self.c0).valeur, D(35))

    def test_periode_cloturee_chiffre_importe_officiel(self):
        """Dans une période clôturée, le chiffre importé (publié) est le chiffre officiel, celui
        qu'utilisent les formules et les totaux qui le citent, même si le détail permettrait de le recalculer."""
        self.saisir("A", self.e2, 20, camp=self.c0)
        recalculer(self.c0)
        self.assertEqual(self.cellule("T", self.p, camp=self.c0).valeur, D(50))  # 25 publié × 2
        self.assertEqual(self.cellule("A", self.g, camp=self.c0).valeur, D(30))  # 25 + 5


class DivisionParZeroEtNATests(Arbre):
    """Une vraie division par zéro reste une erreur, quel que soit l'ordre des termes et même si une autre source est
    N/A ; une division par une source N/A donne N/A."""

    def setUp(self):
        super().setUp()
        for k in "ABC":
            self.kpi(k)
        self.saisir("A", self.e1, na=True)
        self.saisir("B", self.e1, 5)
        self.saisir("C", self.e1, 0)

    def statut(self, formule, na_zero):
        self.kpi("R", t="Calculé", f=formule, agg="Formule", na_compte_zero=na_zero)
        recalculer(self.c)
        return self.cellule("R", self.e1)

    def test_vrai_zero_apres_un_na(self):
        self.assertEqual(self.statut("[A] + [B] / [C]", False).statut, Reponse.Statut.ERREUR)

    def test_vrai_zero_avant_un_na(self):
        self.assertEqual(self.statut("[B] / [C] + [A]", False).statut, Reponse.Statut.ERREUR)

    def test_vrai_zero_case_na_comme_zero(self):
        self.assertEqual(self.statut("[A] + [B] / [C]", True).statut, Reponse.Statut.ERREUR)

    def test_diviseur_na(self):
        self.assertTrue(self.statut("[B] / [A]", False).non_applicable)

    def test_diviseur_na_case_na_comme_zero(self):
        self.assertTrue(self.statut("[B] / [A]", True).non_applicable)


class BoucleTests(Arbre):
    def test_boucle_forcee_ne_plante_pas(self):
        """Formules en boucle (passées outre la vérification) : résultat incomplet, sans erreur ni récursion infinie."""
        self.kpi("X", t="Calculé", f="[Y] + 1", agg="Formule")
        self.kpi("Y", t="Calculé", f="[X] + 1", agg="Formule")
        recalculer(self.c)
        self.assertIsNone(self.cellule("X", self.e1).valeur)
        self.assertIsNone(self.cellule("Y", self.e1).valeur)
