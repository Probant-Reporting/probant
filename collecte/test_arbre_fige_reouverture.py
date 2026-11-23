"""Règle du projet : un exercice clos, puis rouvert en gardant les chiffres de l'époque, se calcule
toujours avec l'arbre des organisations tel qu'il était à sa clôture (``calcul.arbre_fige``) : mêmes parents, mêmes
organisations, pour les totaux, « incomplet », les paramètres hérités, ``ouverte`` et le recalcul ciblé. « Recalculer
avec l'organisation d'aujourd'hui » garde l'arbre d'aujourd'hui ; la clôture suivante note le nouvel arbre.

Données inventées uniquement."""
import datetime
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from referentiel.composition import composer
from referentiel.models import KPI, Frequence, Niveau, Organisation, Referentiel

from . import calcul as C
from . import periodes as P
from . import saisie as S
from .administration import changer_statut
from .models import Campagne, Periode, Reponse
from .test_changer_statut_reouverture import Reouverture

D = Decimal


class ArbreNoteTests(Reouverture):
    def test_note_a_la_cloture(self):
        fige = Periode.objects.get(pk=self.c.periode_id).arbre_fige
        self.assertEqual(fige["v"], 1)
        lignes = {o[0]: o for o in fige["o"]}
        self.assertEqual(lignes[self.e2.pk][1], self.p.pk)
        self.assertEqual(lignes[self.e2.pk][2], Niveau.ENTITY)
        self.assertEqual(len(lignes), Organisation.objects.count())

    def test_garder_ne_change_pas_l_arbre_recalculer_l_efface_et_la_cloture_le_renote(self):
        self.deplacer()
        changer_statut(self.admin, self.c, "rouvrir", garder=True)
        self.assertIsNotNone(Periode.objects.get(pk=self.c.periode_id).arbre_fige)
        changer_statut(self.admin, self.c, "cloturer")
        lignes = {o[0]: o for o in Periode.objects.get(pk=self.c.periode_id).arbre_fige["o"]}
        self.assertEqual(lignes[self.e2.pk][1], self.p.pk)  # arbre de la première clôture, gardé
        changer_statut(self.admin, self.c, "rouvrir", garder=False)
        self.assertIsNone(Periode.objects.get(pk=self.c.periode_id).arbre_fige)
        changer_statut(self.admin, self.c, "cloturer")
        lignes = {o[0]: o for o in Periode.objects.get(pk=self.c.periode_id).arbre_fige["o"]}
        self.assertEqual(lignes[self.e2.pk][1], self.p2.pk)  # nouvel arbre noté

    def test_mise_a_jour_note_l_arbre_du_jour_sans_rien_recalculer(self):
        Periode.objects.filter(pk=self.c.periode_id).update(arbre_fige=None)
        self.deplacer()
        avant = sorted(Reponse.objects.values_list("pk", "valeur", "statut"))
        self.assertEqual(C.noter_arbres_clos(), 1)
        self.assertEqual(sorted(Reponse.objects.values_list("pk", "valeur", "statut")), avant)
        lignes = {o[0]: o for o in Periode.objects.get(pk=self.c.periode_id).arbre_fige["o"]}
        self.assertEqual(lignes[self.e2.pk][1], self.p2.pk)  # arbre du jour de la mise à jour
        self.assertEqual(C.noter_arbres_clos(), 0)


class GarderAvecLArbreDeLEpoqueTests(Reouverture):
    def test_organisation_deplacee_puis_corrigee(self):
        """Le défaut de la relecture (Werk Leipzig) : la correction d'une organisation déplacée depuis la clôture ne la
        fait plus compter deux fois."""
        self.deplacer()
        changer_statut(self.admin, self.c, "rouvrir", garder=True)
        self.corriger(self.e2, 21)
        self.assertEqual(self.total(self.p), (D(31), Reponse.Statut.CALCULE))  # 10 + 21 : son parent de l'époque
        self.assertEqual(self.total(self.p2), (D(5), Reponse.Statut.CALCULE))
        self.assertEqual(self.total(self.g), (D(36), Reponse.Statut.CALCULE))  # 35 + 1

    def test_correction_sous_l_ancien_parent(self):
        self.deplacer()
        changer_statut(self.admin, self.c, "rouvrir", garder=True)
        self.corriger(self.e1, 12)
        self.assertEqual(self.total(self.p), (D(32), Reponse.Statut.CALCULE))  # 12 + 20 : E2 y est encore
        self.assertEqual(self.total(self.g), (D(37), Reponse.Statut.CALCULE))

    def test_organisation_creee_depuis(self):
        e4 = Organisation.objects.create(nom="E4", niveau_id=Niveau.ENTITY, parent=self.p)
        changer_statut(self.admin, self.c, "rouvrir", garder=True)
        self.corriger(self.e1, 12)
        self.assertEqual(self.total(self.p), (D(32), Reponse.Statut.CALCULE))  # E4 n'existait pas : rien ne manque
        self.assertNotIn(e4.pk, {o.id for _, o in S.cellules(self.admin, campagne=self.c)})  # aucune case
        motif, _ = S.organisation_pas_ouverte(self.admin, Campagne.objects.get(pk=self.c.pk), e4)
        self.assertIn("E4", motif)
        self.assertFalse(S.droits(self.admin, Campagne.objects.get(pk=self.c.pk), self.eff, e4).modifier)

    def test_organisation_fermee_depuis(self):
        Organisation.objects.filter(pk=self.e1.pk).update(actif=False, date_desactivation=datetime.date(2024, 6, 30))
        changer_statut(self.admin, self.c, "rouvrir", garder=True)
        self.corriger(self.e2, 21)
        self.assertEqual(self.total(self.p), (D(31), Reponse.Statut.CALCULE))  # E1 ouverte à l'époque : comptée

    def test_organisation_supprimee_depuis(self):
        changer_statut(self.admin, self.c, "rouvrir", garder=True)
        Organisation.objects.filter(pk=self.e1.pk).delete()  # ses réponses partent avec elle
        self.corriger(self.e2, 21)
        self.assertEqual(self.total(self.p), (D(21), Reponse.Statut.CALCULE))  # E1 n'existe plus : ni valeur ni manque

    def test_parent_supprime_depuis_ses_enfants_remontent(self):
        Organisation.objects.filter(pk__in=[self.e1.pk, self.e2.pk]).update(parent=self.p2)
        Organisation.objects.filter(pk=self.p.pk).delete()
        changer_statut(self.admin, self.c, "rouvrir", garder=True)
        self.corriger(self.e1, 12)
        self.assertEqual(self.total(self.g), (D(37), Reponse.Statut.CALCULE))  # 12 + 20 (sous le Groupe) + 5
        self.assertEqual(self.total(self.p2), (D(5), Reponse.Statut.CALCULE))

    def test_deux_reouvertures_successives(self):
        self.deplacer()
        changer_statut(self.admin, self.c, "rouvrir", garder=True)
        changer_statut(self.admin, self.c, "cloturer")
        changer_statut(self.admin, self.c, "rouvrir", garder=True)
        self.corriger(self.e2, 21)
        self.assertEqual(self.total(self.g), (D(36), Reponse.Statut.CALCULE))
        changer_statut(self.admin, self.c, "cloturer")
        changer_statut(self.admin, self.c, "rouvrir", garder=False)  # arbre d'aujourd'hui : E2 sous Pays 2
        self.assertEqual(self.total(self.p), (D(10), Reponse.Statut.CALCULE))
        self.assertEqual(self.total(self.p2), (D(26), Reponse.Statut.CALCULE))
        changer_statut(self.admin, self.c, "cloturer")  # nouvel arbre noté
        Organisation.objects.filter(pk=self.e2.pk).update(parent=self.p)  # puis E2 revient sous Pays
        changer_statut(self.admin, self.c, "rouvrir", garder=True)
        self.corriger(self.e1, 11)
        self.assertEqual(self.total(self.p), (D(11), Reponse.Statut.CALCULE))  # E2 était sous Pays 2 à cette clôture
        self.assertEqual(self.total(self.g), (D(37), Reponse.Statut.CALCULE))

    def test_recalculer_suit_l_arbre_d_aujourd_hui(self):
        self.deplacer()
        changer_statut(self.admin, self.c, "rouvrir", garder=False)
        self.corriger(self.e2, 21)
        self.assertEqual(self.total(self.p2), (D(26), Reponse.Statut.CALCULE))
        self.assertEqual(self.total(self.g), (D(36), Reponse.Statut.CALCULE))

    def test_detail_d_un_total_avec_l_arbre_de_l_epoque(self):
        from .vues_cellule import _detail_agregat

        self.deplacer()
        changer_statut(self.admin, self.c, "rouvrir", garder=True)
        c = Campagne.objects.get(pk=self.c.pk)
        self.assertEqual(sorted(n["org"].nom for n in _detail_agregat(c, self.eff, self.p)), ["E1", "E2"])
        self.assertEqual([n["org"].nom for n in _detail_agregat(c, self.eff, self.p2)], ["E3"])


class ParametreHeriteTests(TestCase):
    """Facteur hérité du pays : un site déplacé depuis la clôture reprend le facteur de son pays de l'époque."""

    def setUp(self):
        from referentiel.models import Utilisateur

        self.admin = Utilisateur.objects.create(username="admin", email="admin@exemple.test", role=Utilisateur.Role.ADMIN)
        self.g = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        self.p = Organisation.objects.create(nom="Pays", niveau_id=Niveau.COUNTRY, parent=self.g)
        self.p2 = Organisation.objects.create(nom="Pays 2", niveau_id=Niveau.COUNTRY, parent=self.g)
        self.e = Organisation.objects.create(nom="E", niveau_id=Niveau.ENTITY, parent=self.p)
        KPI.objects.create(code="EFF", libelle="Effectif", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY,
                           methode_agregation="Somme")
        KPI.objects.create(code="FE", libelle="Facteur", type_saisie_id="FE", granularite_id=Niveau.COUNTRY,
                           methode_agregation="Aucune")
        KPI.objects.create(code="CO2", libelle="CO2", type_saisie_id="Calculé", granularite_id=Niveau.ENTITY,
                           methode_agregation="Somme", formule="[EFF]*[FE]")
        ref = Referentiel.objects.create(code="RAP", nom="Rapport", ordre=1)
        composer({"EFF": ["Social"], "FE": ["Social"], "CO2": ["Social"]}, ref)
        self.c, _ = P.campagne(ref, datetime.date(2025, 1, 1), statut=Campagne.Statut.OUVERTE,
                               date_fin_saisie=timezone.localdate() + datetime.timedelta(days=30))
        for kpi, org, v in (("EFF", self.e, 10), ("FE", self.p, 2), ("FE", self.p2, 3)):
            Reponse.objects.create(periode=self.c.periode, kpi_id=kpi, organisation=org, valeur=D(v),
                                   statut=Reponse.Statut.VALIDE, origine=Reponse.Origine.SAISIE)
        C.recalculer(self.c)
        changer_statut(self.admin, self.c, "cloturer")

    def test_facteur_du_pays_de_l_epoque(self):
        Organisation.objects.filter(pk=self.e.pk).update(parent=self.p2)
        changer_statut(self.admin, self.c, "rouvrir", garder=True)
        S.enregistrer(self.admin, Campagne.objects.get(pk=self.c.pk), KPI.objects.get(code="EFF"),
                      Organisation.objects.get(pk=self.e.pk), "11", False, "Correction")
        co2 = Reponse.objects.get(periode=self.c.periode, kpi_id="CO2", organisation=self.e)
        self.assertEqual(co2.valeur, D(22))  # 11 × 2 (Pays à la clôture), pas 11 × 3
        self.assertEqual(Reponse.objects.get(periode=self.c.periode, kpi_id="CO2", organisation=self.p).valeur, D(22))


class PeriodesTests(Reouverture):
    def test_n_moins_1_entre_une_annee_figee_et_une_annee_courante(self):
        """Chaque période lue suit son arbre : 2025 (close) l'arbre de sa clôture, 2026 (ouverte) celui d'aujourd'hui."""
        self.deplacer()
        c26, _ = P.campagne(self.ref, datetime.date(2026, 1, 1), statut=Campagne.Statut.OUVERTE,
                            date_fin_saisie=timezone.localdate() + datetime.timedelta(days=30))
        for org, v in ((self.e1, 1), (self.e2, 2), (self.e3, 3)):
            Reponse.objects.create(periode=c26.periode, kpi=self.eff, organisation=org, valeur=D(v),
                                   statut=Reponse.Statut.VALIDE, origine=Reponse.Origine.SAISIE)
        Reponse.objects.filter(periode=self.c.periode, organisation__in=[self.p, self.p2]).delete()  # lues au calcul
        calc = C.Calculateur(c26)
        self.assertEqual(calc.valeur("EFF", self.p.pk, self.c.periode), D(30))  # 2025 : E1 + E2 (arbre de l'époque)
        self.assertEqual(calc.valeur("EFF", self.p2.pk, self.c.periode), D(5))
        self.assertEqual(calc.valeur("EFF", self.p.pk), D(1))  # 2026 : E1 seule (arbre d'aujourd'hui)
        self.assertEqual(calc.valeur("EFF", self.p2.pk), D(5))  # 2 + 3

    def test_mois(self):
        mensuel = Referentiel.objects.create(code="MOIS", nom="Mensuel", ordre=2, frequence=Frequence.MOIS)
        composer({"EFF": ["Social"]}, mensuel)
        cm, _ = P.campagne(mensuel, datetime.date(2025, 3, 1), statut=Campagne.Statut.OUVERTE,
                           date_fin_saisie=timezone.localdate() + datetime.timedelta(days=30))
        for org, v in ((self.e1, 1), (self.e2, 2), (self.e3, 3)):
            Reponse.objects.create(periode=cm.periode, kpi=self.eff, organisation=org, valeur=D(v),
                                   statut=Reponse.Statut.VALIDE, origine=Reponse.Origine.SAISIE)
        C.recalculer(cm)
        changer_statut(self.admin, cm, "cloturer")
        self.deplacer()
        changer_statut(self.admin, cm, "rouvrir", garder=True)
        S.enregistrer(self.admin, Campagne.objects.get(pk=cm.pk), self.eff, self.e2, "4", False, "Correction")

        def total(org):
            return Reponse.objects.get(periode=cm.periode, kpi=self.eff, organisation=org).valeur

        self.assertEqual((total(self.p), total(self.p2), total(self.g)), (D(5), D(3), D(8)))  # 1 + 4 ; 3 ; 6 + 2


class PagesTests(Reouverture):
    """À l'écran, une période close ou rouverte en gardant les chiffres montre les rattachements de l'époque : le total
    affiché est la somme du détail affiché."""

    def setUp(self):
        super().setUp()
        self.deplacer()
        changer_statut(self.admin, self.c, "rouvrir", garder=True)
        self.periode = Periode.objects.get(pk=self.c.periode_id)

    def test_consolidation(self):
        from . import consolidation as CO

        t = CO.tableau(self.admin, self.periode, [self.eff])
        lignes = {l.org.nom: l for l in t.lignes}
        self.assertEqual(lignes["E2"].parent_id, self.p.pk)  # sous Pays, comme à la clôture
        self.assertEqual(lignes["Pays"].cases[0].point.valeur, D(30))  # = E1 (10) + E2 (20), montrées dessous

    def test_visualisation(self):
        from . import visualisation as V

        s = V.Source(self.admin, ["EFF"])
        self.assertEqual(sorted(o.nom for o in s.enfants(self.p, self.periode)), ["E1", "E2"])
        self.assertEqual([o.nom for o in s.enfants(self.p2, self.periode)], ["E3"])
        parts, total = s.repartition("EFF", self.p, self.periode)
        self.assertEqual((total, sum(v for _, v, _, _ in parts)), (D(30), D(30)))
        e4 = Organisation.objects.create(nom="E4", niveau_id=Niveau.ENTITY, parent=self.p)
        s = V.Source(self.admin, ["EFF"])
        self.assertIsNone(s.point("EFF", e4, self.periode))  # créée depuis : aucun point dans cet exercice

    def test_export(self):
        from . import exports as E

        p = E.Parametres(niveaux=[Niveau.GROUP, Niveau.COUNTRY, Niveau.ENTITY], exercices=["2025"])
        lignes = [l for l in E.collecter(self.admin, p) if l.kpi.code == "EFF"]
        e2 = next(l for l in lignes if l.org.nom == "E2")
        self.assertEqual(e2.org.parent_id, self.p.pk)


class OuvertureVisualisationTests(Reouverture):
    """La Visualisation et la Consolidation appliquent ``calcul.ouverte`` : une organisation pas encore ouverte pendant
    la période n'y montre pas d'anciennes valeurs."""

    def test_pas_encore_ouverte(self):
        from . import consolidation as CO
        from . import visualisation as V

        Organisation.objects.filter(pk=self.e1.pk).update(date_ouverture=datetime.date(2026, 3, 1))
        periode = Periode.objects.get(pk=self.c.periode_id)
        Periode.objects.filter(pk=periode.pk).update(arbre_fige=None)  # arbre d'aujourd'hui (date posée depuis)
        s = V.Source(self.admin, ["EFF"])
        self.assertIsNone(s.point("EFF", Organisation.objects.get(pk=self.e1.pk), periode))
        self.assertNotIn("E1", {l.org.nom for l in CO.tableau(self.admin, periode, [self.eff]).lignes})


class EcranTests(Reouverture):
    def test_aide_de_la_reouverture(self):
        from django.urls import reverse

        self.client.force_login(self.admin)
        page = self.client.get(reverse("collecte:admin_campagne", args=[self.c.pk])).content.decode()
        self.assertIn("garde l'arbre des organisations de sa clôture", page)
        self.assertIn("avant que l'arbre soit gardé à chaque clôture", page)
        self.assertNotIn("ne garde pas l'arbre du passé", page)
