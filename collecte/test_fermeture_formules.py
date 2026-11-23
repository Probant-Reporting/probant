"""Date de fermeture d'une organisation (fiche organisation) et formules à corriger."""
import datetime
from decimal import Decimal as D

from django.urls import reverse
from django.utils import timezone

from referentiel.models import KPI, Niveau

from . import formules as FM
from .calcul import recalculer
from .models import Reponse
from .aides_tests.arbre import Arbre


class DateDeFermetureTests(Arbre):
    def setUp(self):
        super().setUp()
        self.kpi("EFF")
        self.saisir("EFF", self.e1, 10)
        self.saisir("EFF", self.e2, 20)
        recalculer(self.c)

    def enregistrer(self, **autres):
        return self.post("admin_organisation", [self.e2.id], nom="E2", niveau=Niveau.ENTITY, parent=self.p.id, rang=0,
                         action="enregistrer", **autres)

    def test_date_choisie(self):
        res = self.enregistrer(date_desactivation="2025-06-30")  # « Collectée » décochée, fermée en 2025
        self.assertTrue(res["ok"], res["html"])
        self.e2.refresh_from_db()
        self.assertEqual((self.e2.actif, self.e2.date_desactivation), (False, datetime.date(2025, 6, 30)))
        self.assertEqual(self.cellule("EFF", self.p).valeur, D(10))  # 2026 : fermée avant, ne compte plus
        self.assertIn("Date de fermeture", res["html"])
        self.assertIn("les périodes commencées avant cette date la comptent", res["html"])

    def test_date_vide_aujourd_hui_et_reactivation(self):
        self.enregistrer()
        self.e2.refresh_from_db()
        self.assertEqual(self.e2.date_desactivation, timezone.localdate())
        self.assertEqual(self.cellule("EFF", self.p).valeur, D(30))  # ouverte pendant l'exercice en cours
        self.enregistrer(actif="on", date_desactivation="2025-06-30")
        self.e2.refresh_from_db()
        self.assertEqual((self.e2.actif, self.e2.date_desactivation), (True, None))

    def test_jamais_de_date_pour_une_organisation_active(self):
        """La date de fermeture n'existe que pour une organisation désactivée : envoyée avec « Collectée » cochée, elle
        est ignorée ; une organisation réactivée la perd ; le champ est caché tant que l'organisation est collectée."""
        self.enregistrer(actif="on", date_desactivation="2025-06-30")
        self.e2.refresh_from_db()
        self.assertEqual((self.e2.actif, self.e2.date_desactivation), (True, None))
        self.e2.date_desactivation = datetime.date(2025, 6, 30)
        self.e2.save()  # même hors de la fiche (import, commande)
        self.e2.refresh_from_db()
        self.assertIsNone(self.e2.date_desactivation)
        self.client.force_login(self.admin)
        html = self.client.get(reverse("collecte:admin_organisation", args=[self.e2.id])).content.decode()
        self.assertIn('data-si-fermee hidden', html)
        self.enregistrer(date_desactivation="2025-06-30")
        html = self.client.get(reverse("collecte:admin_organisation", args=[self.e2.id])).content.decode()
        self.assertNotIn('data-si-fermee hidden', html)

    def test_fermee_avec_d_autres_valeurs_rend_le_total_incomplet(self):
        """Une organisation fermée pendant la période qui y a saisi d'autres KPI : une valeur manquante rend le total
        incomplet (rien ne disparaît en silence) ; sans aucune valeur sur la période, elle est écartée."""
        self.kpi("AUTRE")
        Reponse.objects.filter(kpi_id="EFF", organisation=self.e2).delete()
        self.saisir("AUTRE", self.e2, 1)
        self.e2.actif = False
        self.e2.date_desactivation = timezone.localdate()
        self.e2.save()
        recalculer(self.c)
        self.assertEqual(self.cellule("EFF", self.p).statut, Reponse.Statut.INCOMPLET)
        Reponse.objects.filter(kpi_id="AUTRE", organisation=self.e2).delete()
        recalculer(self.c)
        self.assertEqual(self.cellule("EFF", self.p).valeur, D(10))

    def test_date_future_refusee(self):
        demain = timezone.localdate() + datetime.timedelta(days=1)
        res = self.enregistrer(date_desactivation=demain.isoformat())
        self.assertFalse(res["ok"])
        self.e2.refresh_from_db()
        self.assertTrue(self.e2.actif)


class FormulesACorrigerTests(Arbre):
    def test_formules_cassees(self):
        self.kpi("A")
        self.kpi("B")
        ok = self.kpi("OK", t="Calculé", f="[A] + [B]", agg="Formule")
        self.kpi("VIDE", t="Calculé", f="", agg="Formule")
        KPI.objects.filter(code="B").update(actif=False)
        codes = {e["kpi"].code: e["probleme"] for e in FM.dans_la_formule()}
        self.assertIn("VIDE", codes)
        self.assertIn("B", codes["OK"])  # cite un KPI désactivé
        self.assertNotIn("A", codes)
        self.assertTrue(ok.est_calcule)

    def test_division_par_zero_en_erreur_et_a_traiter(self):
        self.kpi("A")
        self.kpi("B")
        self.kpi("R", t="Calculé", f="[A] / [B]", agg="Formule")
        self.saisir("A", self.e1, 10)
        self.saisir("B", self.e1, 0)
        recalculer(self.c)
        r = self.cellule("R", self.e1)
        self.assertEqual(r.statut, Reponse.Statut.ERREUR)
        erreurs = FM.au_calcul()
        self.assertEqual([(e["kpi"].code, e["n"]) for e in erreurs][:1], [("R", 1)])
        self.client.force_login(self.admin)
        page = self.client.get(reverse("collecte:admin_formules"))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Formules à corriger")
        self.assertContains(page, reverse("collecte:referentiel_kpi", args=["R"]))
        accueil = self.client.get(reverse("collecte:admin_accueil"))
        self.assertContains(accueil, reverse("collecte:admin_formules"))

    def test_statut_erreur_dans_une_autre_langue(self):
        """Le statut « erreur » ne dépend plus du texte du message (qui suit la langue)."""
        from django.utils import translation

        self.kpi("A")
        self.kpi("B")
        self.kpi("R", t="Calculé", f="[A] / [B]", agg="Formule")
        self.saisir("A", self.e1, 1)
        self.saisir("B", self.e1, 0)
        with translation.override("en"):
            recalculer(self.c)
        self.assertEqual(self.cellule("R", self.e1).statut, Reponse.Statut.ERREUR)

    def test_page_reservee_a_l_administrateur(self):
        from referentiel.models import Utilisateur

        u = Utilisateur.objects.create_user("contrib", email="c@exemple.test", password="x", role=Utilisateur.Role.CONTRIBUTEUR)
        self.client.force_login(u)
        self.assertIn(self.client.get(reverse("collecte:admin_formules")).status_code, (302, 403, 404))
