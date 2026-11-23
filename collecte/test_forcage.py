"""Valeurs forcées des KPI calculés : demande du responsable du résultat, accord de l'administrateur ou d'un validateur."""
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse

from referentiel.models import Attribution

from . import forcage as FO
from . import relances as RL
from . import saisie as S
from .models import Campagne, DemandeForcage, Journal, Reponse
from .aides_tests.saisie import Base
from .aides_tests import saisie as TS
from referentiel.models import Utilisateur

D = Decimal


class ForcageTests(Base):
    def setUp(self):
        super().setUp()
        # responsable du résultat du KPI calculé DBL (= EFF × 2) dans E1
        Attribution.objects.create(kpi=self.calc, organisation=self.e1, utilisateur=self.contrib)
        self.enregistrer("40")
        self.enregistrer("50", org=self.e2, user=self.admin)

    def reponse(self, org, kpi=None):
        return Reponse.objects.get(periode=self.c.periode, kpi=kpi or self.calc, organisation=org)

    def test_attribution_sur_kpi_calcule_hors_de_la_saisie(self):
        Attribution(kpi=self.calc, organisation=self.e2, utilisateur=self.autre).clean()  # acceptée
        self.assertEqual({(k.code, o.nom) for k, o in S.cellules(self.contrib)}, {("EFF", "E1"), ("TX", "E1")})
        self.assertEqual([(k.code, o.nom) for k, o in S.resultats_responsable(self.contrib, self.c)], [("DBL", "E1")])
        a_relancer = [(l.kpi.code, l.organisation.nom) for p in RL.a_faire([self.c]) for _, ls in p.campagnes for l in ls]
        self.assertNotIn(("DBL", "E1"), a_relancer)
        self.assertTrue(S.droits(self.contrib, self.c, self.calc, self.e1).voir)  # il voit le résultat
        self.assertFalse(S.droits(self.contrib, self.c, self.calc, self.e2).voir)

    def test_demande_du_responsable_puis_accord_du_validateur(self):
        self.assertEqual(self.reponse(self.e1).valeur, D(80))
        d = FO.demander(self.contrib, self.c, self.calc, self.e1, "75", False, "Correction du prestataire")
        self.assertEqual((d.statut, d.valeur, d.valeur_calculee), (DemandeForcage.Statut.EN_ATTENTE, D(75), D(80)))
        self.assertEqual(self.reponse(self.e1).valeur, D(80))  # rien ne change avant l'accord
        self.assertEqual(FO.demandes_a_traiter(self.valid, [self.c]), [d])
        self.assertEqual(FO.demandes_a_traiter(self.autre, [self.c]), [])
        with self.assertRaises(PermissionDenied):
            FO.accepter(self.contrib, self.c, d)  # le responsable ne tranche pas sa propre demande
        FO.accepter(self.valid, self.c, d)
        r = self.reponse(self.e1)
        self.assertEqual((r.origine, r.valeur, r.statut, r.valide_par, r.saisi_par, r.commentaire),
                         (Reponse.Origine.FORCEE, D(75), Reponse.Statut.VALIDE, self.valid, self.contrib, "Correction du prestataire"))
        self.assertEqual(self.reponse(self.p).valeur, D(175))  # la valeur forcée remonte : 75 + 50 × 2
        self.enregistrer("45")  # une nouvelle saisie de la source ne remplace pas la valeur forcée
        self.assertEqual(self.reponse(self.e1).valeur, D(75))
        self.assertEqual(self.reponse(self.p).valeur, D(175))
        self.assertEqual(set(Journal.objects.filter(action__startswith="forcage_").values_list("action", flat=True)),
                         {"forcage_demande", "forcage_accepte"})

    def test_refus_avec_motif(self):
        d = FO.demander(self.contrib, self.c, self.calc, self.e1, "75", False, "Correction")
        with self.assertRaises(ValidationError):
            FO.refuser(self.admin, self.c, d, " ")
        FO.refuser(self.admin, self.c, d, "Chiffre non justifié")
        d.refresh_from_db()
        self.assertEqual((d.statut, d.traite_par, d.motif), (DemandeForcage.Statut.REFUSEE, self.admin, "Chiffre non justifié"))
        self.assertEqual((self.reponse(self.e1).valeur, self.reponse(self.e1).origine), (D(80), Reponse.Origine.CALCUL))
        with self.assertRaises(ValidationError):
            FO.accepter(self.admin, self.c, d)  # déjà traitée

    def test_admin_force_un_total_puis_revient_au_calcul(self):
        d = FO.demander(self.admin, self.c, self.calc, self.p, "300", False, "Total consolidé publié")
        self.assertEqual(d.statut, DemandeForcage.Statut.ACCEPTEE)  # faite par l'administrateur : appliquée aussitôt
        self.assertEqual((self.reponse(self.p).valeur, self.reponse(self.p).origine), (D(300), Reponse.Origine.FORCEE))
        self.assertEqual(self.reponse(self.g).valeur, D(300))
        FO.revenir_au_calcul(self.admin, self.c, self.calc, self.p, "Détail complet")
        self.assertEqual((self.reponse(self.p).valeur, self.reponse(self.p).origine), (D(180), Reponse.Origine.AGREGATION))
        d.refresh_from_db()
        self.assertEqual((d.statut, d.motif), (DemandeForcage.Statut.LEVEE, "Détail complet"))

    def test_non_applicable(self):
        FO.demander(self.admin, self.c, self.calc, self.e1, "", True, "Sans objet cette année")
        r = self.reponse(self.e1)
        self.assertTrue(r.non_applicable and r.origine == Reponse.Origine.FORCEE)
        self.assertEqual(self.reponse(self.p).valeur, D(100))  # N/A exclu de la somme

    def test_refus_et_retrait(self):
        with self.assertRaises(PermissionDenied):
            FO.demander(self.autre, self.c, self.calc, self.e1, "75", False, "Pas responsable")
        with self.assertRaises(ValidationError):
            FO.demander(self.contrib, self.c, self.calc, self.e1, "75", False, "")  # justification obligatoire
        with self.assertRaises(PermissionDenied):
            FO.demander(self.admin, self.c, self.eff, self.e1, "75", False, "KPI saisi")  # seulement un KPI calculé
        d = FO.demander(self.contrib, self.c, self.calc, self.e1, "75", False, "Première")
        d2 = FO.demander(self.contrib, self.c, self.calc, self.e1, "76", False, "Seconde")  # remplace la première
        d.refresh_from_db()
        self.assertEqual(d.statut, DemandeForcage.Statut.RETIREE)
        with self.assertRaises(PermissionDenied):
            FO.retirer(self.autre, self.c, d2)
        FO.retirer(self.contrib, self.c, d2)
        self.assertEqual(DemandeForcage.objects.filter(statut=DemandeForcage.Statut.EN_ATTENTE).count(), 0)
        self.c.statut = Campagne.Statut.CLOTUREE
        self.c.save()
        with self.assertRaises(PermissionDenied):
            FO.demander(self.admin, self.c, self.calc, self.e1, "75", False, "Campagne clôturée")

    def test_panneau_et_page(self):
        url = reverse("collecte:cellule", args=[self.c.pk, "DBL", self.e1.pk])
        entete = {"HTTP_X_REQUESTED_WITH": "fetch"}
        self.client.force_login(self.contrib)
        self.assertIn('value="forcer"', self.client.get(url, **entete).json()["html"])
        r = self.client.post(url, {"action": "forcer", "valeur_forcee": "75", "justification": "Correction"}, **entete)
        self.assertTrue(r.json()["ok"])
        d = DemandeForcage.objects.get()
        r = self.client.get(reverse("collecte:forcages") + f"?campagne={self.c.pk}")
        self.assertContains(r, "DBL")
        self.client.force_login(self.valid)
        self.assertIn('value="accepter_forcage"', self.client.get(url, **entete).json()["html"])
        self.client.post(url, {"action": "accepter_forcage", "demande": d.pk}, **entete)
        self.assertEqual(self.reponse(self.e1).valeur, D(75))
        self.assertIn('value="revenir_calcul"', self.client.get(url, **entete).json()["html"])
        self.client.force_login(self.admin)
        r = self.client.get(reverse("collecte:admin_journal"))
        self.assertEqual(r.status_code, 200)


class ForcageDeuxFoisTests(TS.Base):
    """Une case déjà forcée, forcée une seconde fois : la valeur calculée gardée est celle du calcul (pas la première
    valeur forcée), la première demande est levée, et le retour au calcul redonne le calcul."""

    def setUp(self):
        super().setUp()
        Attribution.objects.create(kpi=self.calc, organisation=self.e1, utilisateur=self.contrib)
        self.enregistrer("40")  # DBL = EFF × 2 : 80 dans E1, 100 dans E2
        self.enregistrer("50", org=self.e2, user=self.admin)

    def reponse(self, org):
        return Reponse.objects.get(periode=self.c.periode, kpi=self.calc, organisation=org)

    def test_forcer_deux_fois_puis_revenir_au_calcul(self):
        d1 = FO.demander(self.admin, self.c, self.calc, self.e1, "75", False, "Premier chiffre")
        d2 = FO.demander(self.admin, self.c, self.calc, self.e1, "70", False, "Chiffre corrigé")
        self.assertEqual((d2.valeur, d2.valeur_calculee), (D(70), D(80)))  # et non 75, la première valeur forcée
        d1.refresh_from_db()
        self.assertEqual(d1.statut, DemandeForcage.Statut.LEVEE)
        self.assertEqual(self.reponse(self.e1).valeur, D(70))
        self.assertEqual(self.reponse(self.p).valeur, D(170))
        FO.revenir_au_calcul(self.admin, self.c, self.calc, self.e1)
        self.assertEqual((self.reponse(self.e1).valeur, self.reponse(self.e1).origine), (D(80), Reponse.Origine.CALCUL))
        self.assertEqual(self.reponse(self.p).valeur, D(180))
        with self.assertRaises(ValidationError):  # plus forcée : rien à lever
            FO.revenir_au_calcul(self.admin, self.c, self.calc, self.e1)

    def test_lecteur_ne_tranche_rien(self):
        FO.demander(self.contrib, self.c, self.calc, self.e1, "75", False, "Correction")
        lecteur = Utilisateur.objects.create(username="lect", email="lect@exemple.test", role=Utilisateur.Role.LECTEUR)
        self.assertEqual(FO.demandes_a_traiter(lecteur), [])
        with self.assertRaises(ValidationError):  # ni valeur ni N/A
            FO.demander(self.admin, self.c, self.calc, self.e1, "", False, "Sans valeur")
