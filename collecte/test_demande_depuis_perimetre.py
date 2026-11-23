"""« Demandé depuis » (règle du projet) : à partir de quelle période un référentiel demande un KPI.
Une seule règle (``demande_depuis.filtre_demande``, lue par ``saisie.codes_perimetre``) pour la saisie, le taux de
remplissage ET le calcul ; un exercice clos ne bouge pas tant qu'il est clos ; une date avancée explicitement fait entrer
le KPI à la réouverture (deux modes), puis au périmètre noté à la clôture suivante ; défaut à la création : l'exercice
en cours ; reculer : refusé avec des valeurs ou sur un exercice clos, confirmé sur des cases vides.

Données inventées uniquement."""
import datetime
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from referentiel.composition import composer, placer
from referentiel.models import KPI, ElementReferentiel, Niveau, Organisation, Referentiel, Utilisateur

from . import calcul as C
from . import demande_depuis as DD
from . import periodes as P
from . import saisie as S
from .administration import changer_statut
from .models import Campagne, Journal, Reponse

D = Decimal
J25, J26 = datetime.date(2025, 1, 1), datetime.date(2026, 1, 1)


class Base(TestCase):
    """Groupe > E1, E2 ; EFF (somme) dans RAP ; 2024 et 2025 clôturés (par l'écran), 2026 ouvert."""

    def setUp(self):
        self.g = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        self.e1 = Organisation.objects.create(nom="E1", niveau_id=Niveau.ENTITY, parent=self.g)
        self.e2 = Organisation.objects.create(nom="E2", niveau_id=Niveau.ENTITY, parent=self.g)
        self.admin = Utilisateur.objects.create(username="admin", email="admin@exemple.test", role=Utilisateur.Role.ADMIN)
        KPI.objects.create(code="EFF", libelle="Effectif", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY,
                           methode_agregation="Somme")
        self.ref = Referentiel.objects.create(code="RAP", nom="Rapport", ordre=1)
        composer({"EFF": ["Social"]}, self.ref)
        self.c = {}
        for an in (2024, 2025, 2026):
            self.c[an] = P.campagne(self.ref, datetime.date(an, 1, 1), statut=Campagne.Statut.OUVERTE)[0]
            for org, v in ((self.e1, 10), (self.e2, 20)):
                Reponse.objects.create(periode=self.c[an].periode, kpi_id="EFF", organisation=org, valeur=D(v),
                                       statut=Reponse.Statut.VALIDE, origine=Reponse.Origine.SAISIE)
            C.recalculer(self.c[an])
        for an in (2024, 2025):
            changer_statut(self.admin, self.c[an], "cloturer")

    def camp(self, an):
        return Campagne.objects.select_related("periode", "referentiel").get(pk=self.c[an].pk)

    def nouveau(self, code="NEW", **kw):
        KPI.objects.create(code=code, libelle=code, type_saisie_id=kw.pop("type_saisie_id", "Saisi"),
                           granularite_id=Niveau.ENTITY, methode_agregation=kw.pop("methode_agregation", "Somme"), **kw)

    def offerts(self, an):
        return {k.code for k, o in S.cellules(self.admin, campagne=self.camp(an))}

    def attendues(self, an):
        return {l.kpi.code for l in S.lignes(self.admin, self.camp(an)) if l.attendue}

    def element(self, code="NEW"):
        return ElementReferentiel.objects.get(referentiel=self.ref, kpi_id=code)


class DefautALaCreationTests(Base):
    def test_defaut_l_exercice_en_cours(self):
        self.assertEqual(DD.depuis_par_defaut(self.ref.pk), J26)
        self.nouveau()
        placer(KPI.objects.get(pk="NEW"), self.ref, None)  # n'importe quelle porte
        self.assertEqual(self.element().demande_depuis, J26)
        self.assertIn("NEW", self.offerts(2026))
        self.assertNotIn("NEW", self.offerts(2025))

    def test_exercice_rouvert_n_est_pas_l_exercice_en_cours(self):
        changer_statut(self.admin, self.camp(2025), "rouvrir", garder=False)
        self.assertEqual(DD.depuis_par_defaut(self.ref.pk), J26)
        self.nouveau()
        placer(KPI.objects.get(pk="NEW"), self.ref, None)
        self.assertNotIn("NEW", self.offerts(2025))  # remplace l'exception implicite d'avant (ajout pendant la réouverture)
        self.assertNotIn("NEW", C.perimetre_calcul(self.camp(2025).periode))

    def test_tout_clos_la_periode_suivante_sans_campagne_vide(self):
        changer_statut(self.admin, self.camp(2026), "cloturer")
        self.assertEqual(DD.depuis_par_defaut(self.ref.pk), datetime.date(2027, 1, 1))
        vide = Referentiel.objects.create(code="NEU", nom="Neuf", ordre=2)
        self.assertIsNone(DD.depuis_par_defaut(vide.pk))

    def test_choix_explicite_vide_garde_depuis_le_debut(self):
        self.nouveau()
        e = ElementReferentiel(referentiel=self.ref, kpi_id="NEW", ordre=9)
        e.depuis_choisi = True
        e.save()
        self.assertIsNone(self.element().demande_depuis)


class ElementSansDateTests(Base):
    """Installations existantes : élément sans date = comportement d'avant (le périmètre noté décide)."""

    def test_sans_date_rien_ne_change(self):
        self.nouveau()
        e = ElementReferentiel(referentiel=self.ref, kpi_id="NEW", ordre=9)
        e.depuis_choisi = True
        e.save()
        self.assertIn("NEW", self.offerts(2026))
        self.assertNotIn("NEW", self.offerts(2025))
        changer_statut(self.admin, self.camp(2025), "rouvrir", garder=False)
        self.assertNotIn("NEW", self.offerts(2025))


class AvancerTests(Base):
    def setUp(self):
        super().setUp()
        self.nouveau()
        placer(KPI.objects.get(pk="NEW"), self.ref, None)

    def test_exercice_clos_rien_ne_bouge_puis_entre_a_la_reouverture(self):
        p = DD.Prevision(self.ref, ["NEW"], J25)
        self.assertEqual([(c.periode.debut, effet, cases) for c, etat, effet, codes, cases in p.lignes],
                         [(J25, "reouverture", 2)])
        DD.changer(self.admin, self.ref, ["NEW"], J25)
        self.assertEqual(self.element().demande_depuis, J25)
        # clos : ni case, ni taux de remplissage, ni calcul (périmètre noté inchangé)
        self.assertNotIn("NEW", self.offerts(2025))
        self.assertNotIn("NEW", self.attendues(2025))
        self.assertNotIn("NEW", C.perimetre_gele(self.camp(2025).periode))
        self.assertFalse(Reponse.objects.filter(periode=self.camp(2025).periode, kpi_id="NEW").exists())
        self.assertNotIn("NEW", self.offerts(2024))  # avant la date : jamais
        p = DD.Prevision(self.ref, ["NEW"], datetime.date(2024, 1, 1))  # 2025 déjà couvert : seul 2024 est annoncé
        self.assertEqual([c.periode.debut.year for c, *_ in p.lignes], [2024])
        self.assertTrue(Journal.objects.filter(action="reglage_kpi", objet_id="NEW", champ="Demandé depuis (RAP)",
                                               apres="2025").exists())
        for garder in (True, False):
            with self.subTest(garder=garder):
                changer_statut(self.admin, self.camp(2025), "rouvrir", garder=garder)
                self.assertIn("NEW", self.offerts(2025))
                self.assertIn("NEW", self.attendues(2025))
                self.assertIn("NEW", C.perimetre_calcul(self.camp(2025).periode))
                S.enregistrer(self.admin, self.camp(2025), KPI.objects.get(pk="NEW"), self.e1, "3", False, "")
                self.assertTrue(Reponse.objects.filter(periode=self.camp(2025).periode, kpi_id="NEW",
                                                       organisation=self.g).exists())  # total au-dessus
                changer_statut(self.admin, self.camp(2025), "cloturer")
                self.assertIn("NEW", self.camp(2025).periode.perimetre_fige)  # noté à la reclôture
                self.assertIn("NEW", self.offerts(2025))

    def test_choisir_l_exercice_rouvert_y_entre_aussitot(self):
        changer_statut(self.admin, self.camp(2025), "rouvrir", garder=False)
        p = DD.changer(self.admin, self.ref, ["NEW"], J25)
        self.assertEqual([(c.periode.debut, etat, effet) for c, etat, effet, _, _ in p.lignes], [(J25, "rouvert", "entre")])
        self.assertIn("NEW", self.offerts(2025))
        j = Journal.objects.get(action="perimetre_periode", apres="NEW")
        self.assertEqual(j.objet_id, str(self.c[2025].pk))

    def test_campagne_en_cours_plus_ancienne(self):
        autre = Referentiel.objects.create(code="MOI", nom="Mensuel", ordre=2, frequence="mois")
        composer({"EFF": ["T"]}, autre)
        mois = {m: P.campagne(autre, datetime.date(2026, m, 1), statut=Campagne.Statut.OUVERTE)[0] for m in (1, 2, 3, 4)}
        self.nouveau("MEN")
        e = ElementReferentiel(referentiel=autre, kpi_id="MEN", ordre=2)
        e.save()
        self.assertEqual(e.demande_depuis, datetime.date(2026, 1, 1))  # le plus ancien mois en cours
        DD.changer(self.admin, autre, ["MEN"], datetime.date(2026, 3, 1), confirmer=True)
        for m, attendu in ((1, False), (2, False), (3, True), (4, True)):
            c = Campagne.objects.select_related("periode", "referentiel").get(pk=mois[m].pk)
            self.assertEqual("MEN" in S.codes_campagne(c)[1], attendu, m)
            self.assertEqual("MEN" in C.perimetre_calcul(c.periode), attendu, m)
        self.assertIn("MEN", C.perimetre_calcul(self.camp(2026).periode))  # l'année cumule les mois qui le demandent


class ReculerTests(Base):
    def setUp(self):
        super().setUp()
        self.nouveau()
        e = ElementReferentiel(referentiel=self.ref, kpi_id="NEW", ordre=9, demande_depuis=J25)
        e.save()
        changer_statut(self.admin, self.camp(2025), "rouvrir", garder=False)

    def test_refuse_sur_un_exercice_clos(self):
        changer_statut(self.admin, self.camp(2025), "cloturer")
        self.assertIn("NEW", self.offerts(2025))
        with self.assertRaises(ValidationError):
            DD.changer(self.admin, self.ref, ["NEW"], J26, confirmer=True)
        self.assertEqual(self.element().demande_depuis, J25)

    def test_refuse_avec_une_valeur(self):
        S.enregistrer(self.admin, self.camp(2025), KPI.objects.get(pk="NEW"), self.e1, "3", False, "")
        with self.assertRaises(ValidationError):
            DD.changer(self.admin, self.ref, ["NEW"], J26, confirmer=True)
        self.assertEqual(self.element().demande_depuis, J25)

    def test_relu_sous_verrou_au_moment_d_enregistrer(self):
        p = DD.Prevision(self.ref, ["NEW"], J26)  # aperçu : cases vides, à confirmer
        self.assertEqual((p.refus, p.a_confirmer), ([], True))
        S.enregistrer(self.admin, self.camp(2025), KPI.objects.get(pk="NEW"), self.e1, "3", False, "")  # entre-temps
        with self.assertRaises(ValidationError):
            DD.changer(self.admin, self.ref, ["NEW"], J26, confirmer=True)
        self.assertEqual(self.element().demande_depuis, J25)

    def test_cases_vides_confirmation(self):
        with self.assertRaises(DD.Confirmation):
            DD.changer(self.admin, self.ref, ["NEW"], J26)
        self.assertEqual(self.element().demande_depuis, J25)
        DD.changer(self.admin, self.ref, ["NEW"], J26, confirmer=True)
        self.assertEqual(self.element().demande_depuis, J26)
        self.assertNotIn("NEW", self.offerts(2025))


class SourcesEtPartageTests(Base):
    def test_avertissement_source_demandee_plus_tard(self):
        self.nouveau("SRC")
        self.nouveau("CAL", type_saisie_id="Calculé", formule="[EFF] + [SRC]", methode_agregation="Formule")
        placer(KPI.objects.get(pk="SRC"), self.ref, None)  # 2026
        e = ElementReferentiel(referentiel=self.ref, kpi_id="CAL", ordre=9)
        e.save()
        changer_statut(self.admin, self.camp(2025), "rouvrir", garder=False)
        p = DD.Prevision(self.ref, ["CAL"], J25)
        self.assertEqual(len(p.avertissements), 1)
        self.assertIn("SRC", p.avertissements[0])
        DD.changer(self.admin, self.ref, ["CAL"], J25)
        self.assertIn("SRC", S.codes_campagne(self.camp(2025))[1])  # la source le sert

    def test_kpi_commun_deux_referentiels(self):
        autre = Referentiel.objects.create(code="AUT", nom="Autre", ordre=2)
        c26 = P.campagne(autre, J26, statut=Campagne.Statut.OUVERTE)[0]
        self.nouveau()
        e = ElementReferentiel(referentiel=autre, kpi_id="NEW", ordre=1)
        e.depuis_choisi = True
        e.save()
        placer(KPI.objects.get(pk="NEW"), self.ref, None)
        self.assertIsNone(e.demande_depuis)
        self.assertEqual(self.element().demande_depuis, J26)
        self.assertIn("NEW", S.codes_campagne(Campagne.objects.get(pk=c26.pk))[1])

    def test_facultatif_suit_la_meme_regle(self):
        self.nouveau()
        placer(KPI.objects.get(pk="NEW"), self.ref, None, obligatoire=False)
        self.assertNotIn("NEW", self.offerts(2025))
        self.assertIn("NEW", self.offerts(2026))


class ExerciceDecaleTests(TestCase):
    def test_exercice_juillet(self):
        Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        KPI.objects.create(code="A", libelle="A", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY, methode_agregation="Somme")
        ref = Referentiel.objects.create(code="DEC", nom="Décalé", ordre=1, mois_debut=7)
        c24 = P.campagne(ref, datetime.date(2024, 7, 1), statut=Campagne.Statut.OUVERTE)[0]
        c25 = P.campagne(ref, datetime.date(2025, 7, 1), statut=Campagne.Statut.OUVERTE)[0]
        e = ElementReferentiel(referentiel=ref, kpi_id="A", ordre=1)
        e.save()
        self.assertEqual(e.demande_depuis, datetime.date(2024, 7, 1))
        ElementReferentiel.objects.filter(pk=e.pk).update(demande_depuis=datetime.date(2025, 7, 1))
        self.assertNotIn("A", S.codes_campagne(Campagne.objects.get(pk=c24.pk))[1])
        self.assertIn("A", S.codes_campagne(Campagne.objects.get(pk=c25.pk))[1])
