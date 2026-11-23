"""Corrections du moteur de calcul : recalculs après un changement d'organisation, de réglage ou de
statut, périodes figées lues telles qu'enregistrées, cellules calculées devenues sans objet, totaux sans détail."""
import datetime
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from referentiel.composition import composer
from referentiel.models import KPI, Niveau, Organisation, Referentiel, Utilisateur

from . import periodes as P
from .calcul import Calculateur, recalculer
from .models import Campagne, Reponse
from .aides_tests.arbre import Arbre

D = Decimal
FETCH = {"HTTP_X_REQUESTED_WITH": "fetch"}


class OrganisationModifieeTests(Arbre):
    """CALC-03 : désactiver ou rattacher ailleurs une organisation refait les calculs des campagnes en cours."""

    def setUp(self):
        super().setUp()
        self.kpi("EFF")
        self.saisir("EFF", self.e1, 10)
        self.saisir("EFF", self.e2, 20)
        self.saisir("EFF", self.e3, 5)
        recalculer(self.c)
        self.assertEqual(self.cellule("EFF", self.g).valeur, D(35))

    def test_desactiver_une_entite(self):
        res = self.post("admin_organisation", [self.e2.id], nom="E2", niveau=Niveau.ENTITY, parent=self.p.id, rang=0,
                        action="enregistrer")  # « Collectée » décochée
        self.assertTrue(res["ok"], res["html"])
        # fermée aujourd'hui, elle était ouverte pendant l'exercice en cours : sa valeur compte
        self.assertEqual(self.cellule("EFF", self.p).valeur, D(30))
        self.assertEqual(self.cellule("EFF", self.g).valeur, D(35))
        # sans valeur, une organisation fermée ne rend pas le total incomplet
        Reponse.objects.filter(kpi_id="EFF", organisation=self.e2).delete()
        recalculer(self.c)
        self.assertEqual(self.cellule("EFF", self.p).valeur, D(10))
        self.assertEqual(self.cellule("EFF", self.g).valeur, D(15))

    def test_rattacher_ailleurs(self):
        res = self.post("admin_organisation", [self.e2.id], nom="E2", niveau=Niveau.ENTITY, parent=self.p2.id, rang=0,
                        actif="on", action="enregistrer")
        self.assertTrue(res["ok"], res["html"])
        self.assertEqual(self.cellule("EFF", self.p).valeur, D(10))
        self.assertEqual(self.cellule("EFF", self.p2).valeur, D(25))
        self.assertEqual(self.cellule("EFF", self.g).valeur, D(35))

    def test_periode_cloturee_non_refaite(self):
        self.saisir("EFF", self.e1, 1, camp=self.c0)
        self.saisir("EFF", self.e2, 2, camp=self.c0)
        self.saisir("EFF", self.e3, 3, camp=self.c0)
        recalculer(self.c0)
        self.post("admin_organisation", [self.e2.id], nom="E2", niveau=Niveau.ENTITY, parent=self.p.id, rang=0,
                  action="enregistrer")
        self.assertEqual(self.cellule("EFF", self.g, self.c0).valeur, D(6))  # 2025 clôturé : figé


class ParentDesactiveTests(Arbre):
    """CALC-10 : une organisation qui a encore des organisations collectées rattachées ne se désactive pas."""

    def test_refus_dans_la_fiche(self):
        res = self.post("admin_organisation", [self.p2.id], nom="Pays 2", niveau=Niveau.COUNTRY, parent=self.g.id, rang=0,
                        action="enregistrer")
        self.assertFalse(res["ok"])
        self.assertRegex(res["html"], "rattachez-l(a|es) ailleurs")
        self.assertIn("statut-valide\">Active", res["html"])
        self.p2.refresh_from_db()
        self.assertTrue(self.p2.actif)
        self.e3.actif = False
        self.e3.save()
        res = self.post("admin_organisation", [self.p2.id], nom="Pays 2", niveau=Niveau.COUNTRY, parent=self.g.id, rang=0,
                        action="enregistrer")
        self.assertTrue(res["ok"], res["html"])
        self.p2.refresh_from_db()
        self.assertFalse(self.p2.actif)

    def test_refus_a_l_import_de_configuration(self):
        from collecte.outils_tests import xlsx

        from . import configuration as CF

        lignes = [["Nom", "Niveau", "Rattachée à", "Active"], ["Pays 2", "Pays", "Groupe", "Non"]]
        a = CF.analyser(xlsx({"Organisations": lignes}))
        ch = a.onglets["Organisations"][0]
        self.assertEqual(ch.action, "rejet")
        self.assertIn("E3", ch.motif)
        lignes.append(["E3", "Entité", "Pays 2", "Non"])
        a = CF.analyser(xlsx({"Organisations": lignes}))
        self.assertEqual([c.action for c in a.onglets["Organisations"]], ["modifier", "modifier"])


class SaisieAuDessusEtMoisTests(TestCase):
    """CALC-07 : le pays saisi chaque mois (détail des entités indisponible) donne le total annuel du pays et du groupe."""

    def setUp(self):
        self.g = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        self.p = Organisation.objects.create(nom="Pays", niveau_id=Niveau.COUNTRY, parent=self.g)
        self.e1 = Organisation.objects.create(nom="E1", niveau_id=Niveau.ENTITY, parent=self.p)
        self.e2 = Organisation.objects.create(nom="E2", niveau_id=Niveau.ENTITY, parent=self.p)
        self.elec = KPI.objects.create(code="ELEC", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY, methode_agregation="Somme",
                                       saisie_au_dessus=True)
        rse = Referentiel.objects.create(code="RSE", nom="RSE", ordre=1)
        nrg = Referentiel.objects.create(code="NRG", nom="Énergie", ordre=2, frequence="mois")
        composer({"ELEC": ["Env"]}, rse)
        composer({"ELEC": ["Conso"]}, nrg)
        self.annee, _ = P.campagne(rse, datetime.date(2026, 1, 1), statut=Campagne.Statut.OUVERTE)
        self.mois = {m: P.campagne(nrg, datetime.date(2026, m, 1), statut=Campagne.Statut.OUVERTE)[0] for m in range(1, 13)}

    def test_cumul_des_mois_saisis_au_pays(self):
        for m in range(1, 13):
            Reponse.objects.create(periode=self.mois[m].periode, kpi=self.elec, organisation=self.p, valeur=D(100),
                                   origine=Reponse.Origine.IMPORT)
        calc = Calculateur(self.annee)
        self.assertEqual(calc.valeur("ELEC", self.p.id), D(1200))
        self.assertEqual(calc.message("ELEC", self.p.id), "")
        self.assertEqual(calc.valeur("ELEC", self.g.id), D(1200))
        recalculer(self.annee)
        r = Reponse.objects.get(periode=self.annee.periode, kpi=self.elec, organisation=self.g)
        self.assertEqual((r.valeur, r.statut), (D(1200), Reponse.Statut.CALCULE))

    def test_mois_manquant_au_pays_reste_incomplet(self):
        for m in range(1, 12):
            Reponse.objects.create(periode=self.mois[m].periode, kpi=self.elec, organisation=self.p, valeur=D(100),
                                   origine=Reponse.Origine.IMPORT)
        calc = Calculateur(self.annee)
        self.assertIsNone(calc.valeur("ELEC", self.p.id))
        self.assertTrue(calc.message("ELEC", self.p.id).startswith("Incomplet"))


class OrganisationSansDetailTests(Arbre):
    """CALC-08 : une organisation sans aucune organisation du niveau du KPI en dessous ne bloque pas le total."""

    def test_pays_avec_seulement_un_site(self):
        self.kpi("EFF")
        be = Organisation.objects.create(nom="Belgique", niveau_id=Niveau.COUNTRY, parent=self.g)
        Organisation.objects.create(nom="Site Bruxelles", niveau_id=Niveau.SITE, parent=be)  # rattachement souple
        nouveau = Organisation.objects.create(nom="Pays tout neuf", niveau_id=Niveau.COUNTRY, parent=self.g)
        self.saisir("EFF", self.e1, 10)
        self.saisir("EFF", self.e2, 20)
        self.saisir("EFF", self.e3, 5)
        calc = Calculateur(self.c)
        self.assertIsNone(calc.valeur("EFF", be.id))
        self.assertIsNone(calc.valeur("EFF", nouveau.id))
        self.assertEqual(calc.valeur("EFF", self.g.id), D(35))
        self.assertEqual(calc.message("EFF", self.g.id), "")

    def test_entite_manquante_toujours_bloquante(self):
        self.kpi("EFF")
        self.saisir("EFF", self.e1, 10)
        self.saisir("EFF", self.e2, 20)
        calc = Calculateur(self.c)
        self.assertIsNone(calc.valeur("EFF", self.g.id))
        self.assertEqual(calc.message("EFF", self.g.id), "Incomplet : Pays 2")

    def test_valeur_saisie_au_dessus_sans_detail_compte(self):
        self.kpi("ELEC", saisie_au_dessus=True)
        be = Organisation.objects.create(nom="Belgique", niveau_id=Niveau.COUNTRY, parent=self.g)
        self.saisir("ELEC", self.e1, 1)
        self.saisir("ELEC", self.e2, 2)
        self.saisir("ELEC", self.e3, 3)
        self.saisir("ELEC", be, 100)
        self.assertEqual(Calculateur(self.c).valeur("ELEC", self.g.id), D(106))


class PeriodeFigeeTests(Arbre):
    """CALC-02 : une période figée (toutes ses campagnes clôturées) se lit telle qu'enregistrée, sans être recalculée
    avec les réglages d'aujourd'hui (organisations désactivées, formule changée, valeur calculée importée)."""

    def setUp(self):
        super().setUp()
        self.lecteur = Utilisateur.objects.create(username="lect", email="lect@exemple.test", role=Utilisateur.Role.LECTEUR)

    def cloturer_2025_puis_desactiver_e2(self):
        self.c0.statut = Campagne.Statut.OUVERTE
        self.c0.save()
        for camp in (self.c0, self.c):
            for o in (self.e1, self.e2, self.e3):
                Reponse.objects.create(periode=camp.periode, kpi_id="DEC", organisation=o, valeur=D(300 if o == self.e2 else 100),
                                       statut=Reponse.Statut.VALIDE, origine=Reponse.Origine.IMPORT)
        recalculer(self.c0)
        self.c0.statut = Campagne.Statut.CLOTUREE
        self.c0.save()
        self.e2.actif = False
        self.e2.save()
        recalculer(self.c)

    def test_visualisation_d_une_annee_cloturee_apres_desactivation(self):
        from . import visualisation as V

        self.kpi("DEC")
        self.cloturer_2025_puis_desactiver_e2()
        self.assertEqual(self.cellule("DEC", self.g, self.c0).valeur, D(500))
        for brouillons in (False, True):
            src = V.Source(self.lecteur, ["DEC"], brouillons=brouillons)
            point = src.point("DEC", self.g, self.c0.periode)
            self.assertEqual((point.valeur, point.provisoire), (D(500), False))
            self.assertEqual(src.point("DEC", self.g, self.c.periode).valeur, D(200))  # 2026 ouvert : calcul d'aujourd'hui

    def test_formule_n_1_lit_l_annee_cloturee_enregistree(self):
        self.kpi("DEC")
        self.kpi("EVOL", "Calculé", "([DEC] - [DEC@N-1]) / [DEC@N-1]", agg="Formule", type_reponse_id="Pourcentage")
        self.cloturer_2025_puis_desactiver_e2()
        self.assertEqual(self.cellule("EVOL", self.g).valeur, D("-0.6"))  # 200 contre 500 enregistré en 2025

    def test_formule_changee_ne_refait_pas_l_historique(self):
        from . import visualisation as V
        from .reglages import apres_reglage

        for code in ("GES", "CA", "CAHT"):
            self.kpi(code, gran=Niveau.GROUP, agg="Aucune")
        k = self.kpi("INT", "Calculé", "[GES] / [CA]", gran=Niveau.GROUP, agg="Aucune")
        self.c0.statut = Campagne.Statut.OUVERTE
        self.c0.save()
        for code, v in (("GES", 1000), ("CA", 50), ("CAHT", 40)):
            Reponse.objects.create(periode=self.c0.periode, kpi_id=code, organisation=self.g, valeur=D(v),
                                   statut=Reponse.Statut.VALIDE, origine=Reponse.Origine.IMPORT)
        recalculer(self.c0)
        self.c0.statut = Campagne.Statut.CLOTUREE
        self.c0.save()
        k.formule = "[GES] / [CAHT]"
        k.save()
        apres_reglage(k, {"formule"})
        self.assertEqual(self.cellule("INT", self.g, self.c0).valeur, D(20))
        self.assertEqual(V.Source(self.admin, ["INT"]).point("INT", self.g, self.c0.periode).valeur, D(20))

    def test_valeur_calculee_importee_de_l_ancien_outil(self):
        from . import visualisation as V

        self.kpi("F", gran=Niveau.GROUP, agg="Aucune")
        self.kpi("T", gran=Niveau.GROUP, agg="Aucune")
        self.kpi("PART", "Calculé", "[F] / [T]", gran=Niveau.GROUP, agg="Aucune", type_reponse_id="Pourcentage")
        for code, v in (("F", 41), ("T", 100), ("PART", "0.43")):
            Reponse.objects.create(periode=self.c0.periode, kpi_id=code, organisation=self.g, valeur=D(v),
                                   statut=Reponse.Statut.VALIDE, origine=Reponse.Origine.IMPORT)
        for brouillons in (False, True):
            point = V.Source(self.admin, ["PART"], brouillons=brouillons).point("PART", self.g, self.c0.periode)
            self.assertEqual((point.valeur, point.provisoire), (D("0.43"), False))

    def test_decompte_enregistre_relu(self):
        from parametres.models import TypeReponse

        from . import visualisation as V

        ouinon = TypeReponse.objects.create(code="OuiNon", libelle="Oui / non", format="oui_non")
        self.kpi("POL", agg="Décompte", type_reponse=ouinon)
        self.c0.statut = Campagne.Statut.OUVERTE
        self.c0.save()
        for o, t in ((self.e1, "Oui"), (self.e2, "Non"), (self.e3, "Oui")):
            Reponse.objects.create(periode=self.c0.periode, kpi_id="POL", organisation=o, texte=t,
                                   statut=Reponse.Statut.VALIDE, origine=Reponse.Origine.IMPORT)
        recalculer(self.c0)
        self.c0.statut = Campagne.Statut.CLOTUREE
        self.c0.save()
        self.e2.actif = False
        self.e2.save()
        calc = Calculateur(self.c)
        self.assertEqual(calc.valeur("POL", self.g.id, self.c0.periode), {"Oui": 2, "Non": 1})
        point = V.Source(self.admin, ["POL"]).point("POL", self.g, self.c0.periode)
        self.assertEqual(V.decompte(point.valeur), {"Oui": 2, "Non": 1})


class PropagationTests(TestCase):
    """CALC-04 : année de référence [ID@AAAA], N-1 d'une année cumulée, réouverture d'une campagne."""

    def setUp(self):
        self.g = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        self.e1 = Organisation.objects.create(nom="E1", niveau_id=Niveau.ENTITY, parent=self.g)
        self.admin = Utilisateur.objects.create(username="admin", email="admin@exemple.test", role=Utilisateur.Role.ADMIN)

    def valeur(self, kpi, org, periode):
        return Reponse.objects.get(periode=periode, kpi_id=kpi, organisation=org).valeur

    def test_annee_de_reference_corrigee(self):
        KPI.objects.create(code="CA", type_saisie_id="Saisi", granularite_id=Niveau.GROUP, methode_agregation="Aucune")
        KPI.objects.create(code="IDX", type_saisie_id="Calculé", formule="[CA] / [CA@2021]", granularite_id=Niveau.GROUP,
                           methode_agregation="Aucune")
        c21 = Campagne.objects.create(exercice=2021, statut=Campagne.Statut.CLOTUREE)
        c26 = Campagne.objects.create(exercice=2026, statut=Campagne.Statut.OUVERTE)
        r = Reponse.objects.create(periode=c21.periode, kpi_id="CA", organisation=self.g, valeur=D(100), origine=Reponse.Origine.IMPORT)
        Reponse.objects.create(periode=c26.periode, kpi_id="CA", organisation=self.g, valeur=D(150), origine=Reponse.Origine.IMPORT)
        recalculer(c26)
        self.assertEqual(self.valeur("IDX", self.g, c26.periode), D("1.5"))
        r.valeur = D(120)  # correction importée dans la campagne clôturée de 2021
        r.save()
        recalculer(c21, ["CA"])
        self.assertEqual(self.valeur("IDX", self.g, c26.periode), D("1.25"))

    def mensuel(self, statut_annees=Campagne.Statut.OUVERTE):
        KPI.objects.create(code="ELEC", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY, methode_agregation="Somme")
        rse = Referentiel.objects.create(code="RSE", nom="RSE", ordre=1)
        nrg = Referentiel.objects.create(code="NRG", nom="Énergie", ordre=2, frequence="mois")
        composer({"ELEC": ["Env"]}, rse)
        composer({"ELEC": ["Conso"]}, nrg)
        self.annees, self.mois = {}, {}
        for an, v in ((2025, 10), (2026, 12)):
            self.annees[an] = P.campagne(rse, datetime.date(an, 1, 1), statut=statut_annees)[0]
            for m in range(1, 13):
                self.mois[an, m] = P.campagne(nrg, datetime.date(an, m, 1), statut=Campagne.Statut.OUVERTE)[0]
                Reponse.objects.create(periode=self.mois[an, m].periode, kpi_id="ELEC", organisation=self.e1, valeur=D(v),
                                       origine=Reponse.Origine.IMPORT)

    def test_n_1_d_une_annee_cumulee(self):
        self.mensuel()
        KPI.objects.create(code="VAR", type_saisie_id="Calculé", formule="([ELEC] - [ELEC@N-1]) / [ELEC@N-1]",
                           granularite_id=Niveau.ENTITY, methode_agregation="Formule", type_reponse_id="Pourcentage")
        recalculer(self.annees[2025])
        recalculer(self.annees[2026])
        self.assertEqual(self.valeur("VAR", self.e1, self.annees[2026].periode), D("0.2"))
        Reponse.objects.filter(periode=self.mois[2025, 3].periode, kpi_id="ELEC").update(valeur=D(70))
        recalculer(self.mois[2025, 3], ["ELEC"])
        self.assertEqual(self.valeur("ELEC", self.e1, self.annees[2025].periode), D(180))
        self.assertEqual(self.valeur("VAR", self.e1, self.annees[2026].periode), D("-0.2"))

    def test_reouverture_refait_les_calculs(self):
        from .administration import changer_statut

        self.mensuel(statut_annees=Campagne.Statut.CLOTUREE)
        for an in (2025, 2026):
            recalculer(self.annees[an], propager=False)
        self.assertEqual(self.valeur("ELEC", self.e1, self.annees[2026].periode), D(144))
        Reponse.objects.filter(periode=self.mois[2026, 12].periode, kpi_id="ELEC").update(valeur=D(70))
        recalculer(self.mois[2026, 12], ["ELEC"])
        self.assertEqual(self.valeur("ELEC", self.e1, self.annees[2026].periode), D(144))  # figée
        changer_statut(self.admin, self.annees[2026], "rouvrir")
        self.assertEqual(self.valeur("ELEC", self.e1, self.annees[2026].periode), D(202))


class ReglageChangeTests(Arbre):
    """CALC-05 et CALC-06 : après un changement de réglage, les cellules suivent le nouveau calcul."""

    def test_saisi_devenu_calcule(self):
        from .models import Journal
        from .reglages import apres_reglage

        tot = self.kpi("TOT")
        self.kpi("A")
        self.kpi("B")
        for o, v in ((self.e1, 999), (self.e2, 7), (self.e3, 1)):
            Reponse.objects.create(periode=self.c.periode, kpi_id="TOT", organisation=o, valeur=D(v), commentaire="note",
                                   statut=Reponse.Statut.VALIDE, origine=Reponse.Origine.SAISIE)
        for o in (self.e1, self.e2, self.e3):
            self.saisir("A", o, 1)
            self.saisir("B", o, 2)
        recalculer(self.c)
        tot.type_saisie_id, tot.formule = "Calculé", "[A] + [B]"
        tot.save()
        apres_reglage(tot, {"type_saisie", "formule"})
        r = self.cellule("TOT", self.e1)
        self.assertEqual((r.valeur, r.origine, r.statut, r.commentaire), (D(3), Reponse.Origine.CALCUL, Reponse.Statut.CALCULE, "note"))
        self.assertEqual(self.cellule("TOT", self.p).valeur, D(6))
        self.assertEqual(self.cellule("TOT", self.g).valeur, D(9))
        j = Journal.objects.filter(action="valeur_recalculee", objet_id=str(r.pk)).get()
        self.assertEqual((j.avant, j.apres), ("999", "3"))

    def test_saisi_devenu_calcule_formule_incomplete(self):
        from .reglages import apres_reglage

        tot = self.kpi("TOT")
        self.kpi("A")
        Reponse.objects.create(periode=self.c.periode, kpi_id="TOT", organisation=self.e1, valeur=D(999),
                               statut=Reponse.Statut.VALIDE, origine=Reponse.Origine.SAISIE)
        tot.type_saisie_id, tot.formule = "Calculé", "[A] * 2"
        tot.save()
        apres_reglage(tot, {"type_saisie", "formule"})
        r = self.cellule("TOT", self.e1)
        self.assertEqual((r.valeur, r.statut, r.message_calcul), (None, Reponse.Statut.INCOMPLET, "Source manquante : A"))

    def test_import_d_un_kpi_calcule_jamais_ecrase(self):
        self.kpi("A")
        self.kpi("DBL", "Calculé", "[A] * 2")
        self.saisir("A", self.e1, 1)
        self.saisir("DBL", self.e1, 5)  # importée (historique)
        recalculer(self.c)
        self.assertEqual(self.cellule("DBL", self.e1).valeur, D(5))

    def test_somme_vers_aucune_vide_les_totaux(self):
        from .reglages import apres_reglage

        eff = self.kpi("EFF")
        self.saisir("EFF", self.e1, 10)
        self.saisir("EFF", self.e2, 20)
        self.saisir("EFF", self.e3, 5)
        recalculer(self.c)
        Reponse.objects.filter(kpi_id="EFF", organisation=self.p).update(commentaire="garder")
        eff.methode_agregation = "Aucune"
        eff.save()
        apres_reglage(eff, {"methode_agregation"})
        self.assertFalse(Reponse.objects.filter(kpi_id="EFF", organisation__in=[self.g, self.p2]).exists())
        r = self.cellule("EFF", self.p)  # commentaire gardé : la cellule reste, vide
        self.assertEqual((r.valeur, r.origine, r.statut, r.commentaire), (None, Reponse.Origine.SAISIE, Reponse.Statut.A_SAISIR, "garder"))
        self.assertEqual(self.cellule("EFF", self.e1).valeur, D(10))

    def test_cumul_devenu_saisissable(self):
        from . import saisie as S
        from .reglages import apres_reglage

        elec = KPI.objects.create(code="ELEC", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY, methode_agregation="Somme")
        rse = Referentiel.objects.create(code="ANN", nom="Annuel", ordre=1)
        nrg = Referentiel.objects.create(code="NRG", nom="Énergie", ordre=2, frequence="mois")
        composer({"ELEC": ["Env"]}, rse)
        composer({"ELEC": ["Conso"]}, nrg)
        annee, _ = P.campagne(rse, datetime.date(2027, 1, 1), statut=Campagne.Statut.OUVERTE)
        for m in range(1, 13):
            mois, _ = P.campagne(nrg, datetime.date(2027, m, 1), statut=Campagne.Statut.OUVERTE)
            Reponse.objects.create(periode=mois.periode, kpi=elec, organisation=self.e1, valeur=D(10), origine=Reponse.Origine.IMPORT)
        recalculer(annee)
        r = Reponse.objects.get(periode=annee.periode, kpi=elec, organisation=self.e1)
        self.assertEqual((r.valeur, r.origine), (D(120), Reponse.Origine.CUMUL))
        elec.agregation_temps = KPI.AgregationTemps.AUCUNE
        elec.save()
        apres_reglage(elec, {"agregation_temps"})
        self.assertFalse(Reponse.objects.filter(periode=annee.periode, kpi=elec, organisation=self.e1).exists())
        self.assertFalse(S.est_calculee(elec, self.e1, None, annee))

    def test_referentiel_mensuel_desactive(self):
        elec = KPI.objects.create(code="ELEC", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY, methode_agregation="Somme")
        rse = Referentiel.objects.create(code="ANN", nom="Annuel", ordre=1)
        nrg = Referentiel.objects.create(code="NRG", nom="Énergie", ordre=2, frequence="mois")
        composer({"ELEC": ["Env"]}, rse)
        composer({"ELEC": ["Conso"]}, nrg)
        annee, _ = P.campagne(rse, datetime.date(2027, 1, 1), statut=Campagne.Statut.OUVERTE)
        for m in range(1, 13):
            mois, _ = P.campagne(nrg, datetime.date(2027, m, 1), statut=Campagne.Statut.CLOTUREE)
            Reponse.objects.create(periode=mois.periode, kpi=elec, organisation=self.e1, valeur=D(10), origine=Reponse.Origine.IMPORT)
        recalculer(annee)
        self.assertTrue(Reponse.objects.filter(periode=annee.periode, kpi=elec, organisation=self.e1).exists())
        self.client.force_login(self.admin)
        self.client.post(reverse("parametres:referentiels"), {"action": "enregistrer", "nom__NRG": "Énergie"})
        nrg.refresh_from_db()
        self.assertFalse(nrg.actif)
        self.assertFalse(Reponse.objects.filter(periode=annee.periode, kpi=elec, organisation=self.e1).exists())


class RevueEtCouvertesTests(Arbre):
    """CALC-11 : rapport de revue et « Cases restant à saisir » comptent les mêmes cases que le tableau de bord."""

    def test_saisie_au_dessus(self):
        from . import exports as E
        from . import saisie as S

        self.e3.actif = False  # un seul pays collecté
        self.e3.save()
        self.p2.actif = False
        self.p2.save()
        elec = self.kpi("ELEC", saisie_au_dessus=True)
        eff = self.kpi("EFF")
        S.enregistrer(self.admin, self.c, elec, self.p, "5000", False, "détail par entité indisponible")
        S.valider(self.admin, self.c, elec, self.p)
        for e in (self.e1, self.e2):
            S.enregistrer(self.admin, self.c, eff, e, "10", False, "")
            S.valider(self.admin, self.c, eff, e)
        tdb = S.tableau_de_bord(S.lignes(self.admin, self.c))
        self.assertEqual((tdb["total"].valide, tdb["total"].total), (2, 2))
        p_revue = E.Parametres.depuis(E.PRESETS["revue"][2])
        p_revue.exercices = ["2026"]
        lignes = E.collecter(self.admin, p_revue)
        self.assertIn(("ELEC", "Pays"), [(l.kpi.code, l.org.nom) for l in lignes])  # la valeur saisie au pays reste listée
        av = E._avancement(lignes)
        self.assertEqual([sum(x[i] for x in av.values()) for i in range(3)], [2, 2, 0])
        p_manq = E.Parametres.depuis(E.PRESETS["manquantes"][2])
        p_manq.exercices = ["2026"]
        self.assertEqual([(l.kpi.code, l.org.nom) for l in E.collecter(self.admin, p_manq)], [])


class ReglesSurPourcentagesTests(Arbre):
    """CALC-12 : une règle sur un pourcentage affiche ses valeurs en pourcentage, pas en fraction arrondie."""

    def setUp(self):
        super().setUp()
        from .models import RegleCoherence

        self.txf = self.kpi("TXF", type_reponse_id="Pourcentage", agg="Aucune")
        self.txa = self.kpi("TXA", type_reponse_id="Pourcentage", agg="Aucune")
        self.r1 = RegleCoherence.objects.create(nom="Femmes cadres ≤ 30 %", gauche="[TXF]", operateur="<=", droite="0.3",
                                                niveau_id=Niveau.ENTITY, bloquante=True)
        self.r2 = RegleCoherence.objects.create(nom="Accidents ≤ 0,3 %", gauche="[TXA]", operateur="<=", droite="0.003",
                                                niveau_id=Niveau.ENTITY)
        self.saisir("TXF", self.e1, "0.35")
        self.saisir("TXA", self.e1, "0.004")

    def test_alertes_et_motif_bloquant(self):
        from . import coherence as CO
        from .templatetags.collecte import formater

        d = {x["regle"].pk: x for x in CO.controles_regles(self.c, orgs=[self.e1])}
        self.assertEqual((d[self.r1.pk]["valeur"], d[self.r1.pk]["reference"]),
                         (formater(D("0.35"), self.txf), "≤ " + formater(D("0.3"), self.txf)))
        self.assertEqual((d[self.r2.pk]["valeur"], d[self.r2.pk]["reference"]),
                         (formater(D("0.004"), self.txa), "≤ " + formater(D("0.003"), self.txa)))
        self.assertIn("%", d[self.r2.pk]["valeur"])
        self.assertNotEqual(d[self.r2.pk]["valeur"], d[self.r2.pk]["reference"].split(" ", 1)[1])
        motif = CO.regles_bloquantes_en_echec(self.c, self.txf, self.e1)[0]
        self.assertIn("%", motif)

    def test_regle_ecrite_en_pourcentage_refusee(self):
        from .vues_coherence import RegleForm

        form = RegleForm({"nom": "Femmes cadres", "gauche": "[TXF]", "operateur": "<=", "droite": "30", "tolerance": "0",
                          "niveau": Niveau.ENTITY, "actif": "on"})
        self.assertFalse(form.is_valid())
        self.assertIn("0.3", str(form.errors))
        form = RegleForm({"nom": "Femmes cadres", "gauche": "[TXF]", "operateur": "<=", "droite": "0.3", "tolerance": "0",
                          "niveau": Niveau.ENTITY, "actif": "on"})
        self.assertTrue(form.is_valid(), form.errors)


class SommeDePourcentagesTests(TestCase):
    """CALC-14 : un pourcentage ne s'additionne pas."""

    def test_somme_refusee(self):
        for t in ("Saisi", "Calculé"):
            k = KPI(code="TXR", type_saisie_id=t, formule="[A] / [B]" if t == "Calculé" else "", granularite_id=Niveau.ENTITY,
                    methode_agregation="Somme", type_reponse_id="Pourcentage")
            self.assertIn("ne s'additionne pas", str(k.erreurs_regles().get("methode_agregation")))
        k = KPI(code="TXR", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY, methode_agregation="Aucune",
                type_reponse_id="Pourcentage")
        self.assertNotIn("methode_agregation", k.erreurs_regles())


class DecompteSansEcartTests(Arbre):
    """CALC-15 : pas d'écart avec N-1 pour une réponse oui / non ou liste, même agrégée en décompte."""

    def test_pas_d_ecart(self):
        from parametres.models import TypeReponse

        from . import exports as E
        from . import saisie as S

        ouinon = TypeReponse.objects.create(code="OuiNon", libelle="Oui / non", format="oui_non")
        self.kpi("POL", agg="Décompte", type_reponse=ouinon)
        self.c0.statut = Campagne.Statut.OUVERTE
        self.c0.save()
        for camp, reps in ((self.c0, ("Oui", None, "Oui")), (self.c, ("Oui", "Oui", "Oui"))):
            for o, t in zip((self.e1, self.e2, self.e3), reps):
                self.saisir("POL", o, camp=camp, texte=t or "", na=t is None)
            recalculer(camp)
        self.assertEqual(self.cellule("POL", self.p, self.c0).valeur, D(1))
        self.assertEqual(self.cellule("POL", self.p).valeur, D(2))
        lignes = [l for l in S.lignes(self.admin, self.c, org=self.p, calculees=True) if l.kpi.code == "POL"]
        self.assertTrue(lignes)
        self.assertTrue(all(l.ecart is None for l in lignes))
        p = E.Parametres.depuis(E.PRESETS["tableau"][2])
        p.exercices = ["2026"]
        self.assertTrue(all(E._ecart(l) is None for l in E.collecter(self.admin, p) if l.kpi.code == "POL"))
        self.client.force_login(self.admin)
        html = self.client.get(reverse("collecte:cellule", args=[self.c.pk, "POL", self.p.id]), **FETCH).json()["html"]
        self.assertNotIn("+100", html)


class ComparaisonMensuelleTests(Arbre):
    """CALC-16 : la base de données dit avec quelle période la « Valeur N-1 » se compare."""

    def test_colonne_periode_de_comparaison(self):
        from . import exports as E
        from . import saisie as S

        nrg = Referentiel.objects.create(code="NRG", nom="Énergie", ordre=1, frequence="mois", comparaison="P-1")
        k = self.kpi("ELEC")
        composer({"ELEC": ["Conso"]}, nrg)
        fev, _ = P.campagne(nrg, datetime.date(2026, 2, 1), statut=Campagne.Statut.OUVERTE)
        mars, _ = P.campagne(nrg, datetime.date(2026, 3, 1), statut=Campagne.Statut.OUVERTE)
        S.enregistrer(self.admin, fev, k, self.e1, "100", False, "")
        S.enregistrer(self.admin, mars, k, self.e1, "110", False, "")
        p = E.Parametres(exercices=["2026"], n1=True, periodes=["mois"], referentiel="NRG")
        entetes = E.entetes_base(p)
        self.assertIn("Valeur N-1", entetes)  # colonne gardée telle quelle (requêtes Power BI existantes)
        ligne = [E.ligne_base(l, p) for l in E.collecter(self.admin, p) if l.periode == mars.periode and l.org == self.e1][0]
        self.assertEqual(ligne[entetes.index("Valeur N-1")], 100)
        self.assertEqual(ligne[entetes.index("Période de comparaison")], str(fev.periode))
        self.assertNotIn("Période de comparaison", E.entetes_base(E.Parametres(exercices=["2026"], periodes=["mois"])))
        csv = E.lignes_tableau_csv(E.collecter(self.admin, E.Parametres(exercices=["2026"], n1=True, periodes=["mois"],
                                                                         presentation="tableau", referentiel="NRG")), p)
        self.assertIn("E1 (période de comparaison)", csv[0])


class UniteEntiereTests(Arbre):
    """CALC-17 : une unité passée en « Nombre entier » passe ses KPI à 0 décimale."""

    def test_kpi_suivent_l_unite(self):
        from parametres.models import Unite

        from .models import Journal
        from .templatetags.collecte import valeur as tag_valeur

        u = Unite.objects.create(code="sal", symbole="salariés", libelle="salariés", entier=False, decimales=2)
        k = self.kpi("EFF", unite=u, decimales=2)
        r = self.saisir("EFF", self.e1, 1234)
        unites = list(Unite.objects.all())
        i = [x.pk for x in unites].index("sal")
        donnees = {"action": "enregistrer", "nb": len(unites), **{f"code__{j}": x.pk for j, x in enumerate(unites)},
                   **{f"{c}__{j}": getattr(x, c) for j, x in enumerate(unites) for c in ("symbole", "libelle", "famille", "decimales")},
                   **{f"entier__{j}": "on" for j, x in enumerate(unites) if x.entier}, f"entier__{i}": "on"}
        self.client.force_login(self.admin)
        self.client.post("/administration/parametres/referentiel/?section=unites", donnees)
        u.refresh_from_db()
        k.refresh_from_db()
        self.assertEqual((u.entier, u.decimales, k.decimales), (True, 0, 0))
        self.assertEqual(tag_valeur(r, k), "1\u202f234 salariés")
        self.assertTrue(Journal.objects.filter(action="reglage_kpi", objet_id="EFF", champ="decimales", avant="2", apres="0").exists())
