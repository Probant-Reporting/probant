"""Page Cohérence : à l'ouverture, les détections se calculent sans verrou ; le verrou et la transaction d'écriture ne
sont pris que s'il y a quelque chose à écrire, et la comparaison est alors refaite sous verrou
(``coherence.controler_a_l_ouverture``). Résultat identique à ``coherence.controler``."""
from decimal import Decimal
from unittest import mock

from django.db import connections, transaction
from django.db.models.query import QuerySet
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from espaces import contexte as ESP

from . import coherence as CO
from .models import Alerte, Reponse
from .test_coherence import CoherenceTests

D = Decimal
ECRITURES = ("INSERT", "UPDATE", "DELETE", "SAVEPOINT", "RELEASE", "BEGIN")
CHAMPS = ("kpi_id", "organisation_id", "controle", "regle_id", "gravite", "message", "valeur", "reference", "empreinte",
          "statut", "textes", "kpis_concernes")


class CoherenceSansVerrouTests(CoherenceTests):
    def etat(self):
        return sorted(map(repr, Alerte.objects.filter(campagne=self.c).values_list(*CHAMPS)))

    def perimer(self):
        """Valeurs changées sans passer par la saisie (aucun contrôle) : les alertes enregistrées sont dépassées."""
        Reponse.objects.filter(periode=self.c.periode, kpi=self.eff, organisation=self.e1).update(valeur=D(300))
        if not Reponse.objects.filter(periode=self.c.periode, kpi=self.form, organisation=self.e1).update(valeur=D(-4)):
            Reponse.objects.bulk_create([Reponse(periode=self.c.periode, kpi=self.form, organisation=self.e1, valeur=D(-4),
                                                 origine=Reponse.Origine.SAISIE)])

    def compter_verrous(self):
        return mock.patch.object(QuerySet, "select_for_update", autospec=True, side_effect=QuerySet.select_for_update)

    def test_ouverture_sans_changement_ni_ecriture_ni_verrou(self):
        self.saisir(self.eff, 150)  # écart N-1 : alerte créée par la saisie, déjà à jour
        self.saisir(self.fe, D("9.5"))
        self.assertTrue(Alerte.objects.filter(campagne=self.c).exists())
        avant = self.etat()
        with CaptureQueriesContext(connections[ESP.alias_courant()]) as requetes, self.compter_verrous() as verrous, \
                mock.patch.object(CO, "_controler", side_effect=AssertionError("verrou pris sans raison")):
            CO.controler_a_l_ouverture(self.c)
        ecritures = [q["sql"] for q in requetes.captured_queries if q["sql"].lstrip().upper().startswith(ECRITURES)]
        self.assertEqual(ecritures, [])
        self.assertEqual(verrous.call_count, 0)
        self.assertEqual(self.etat(), avant)

    def test_page_ouverte_sans_changement_ne_verrouille_pas(self):
        self.saisir(self.eff, 150)
        self.client.force_login(self.admin)
        with self.compter_verrous() as verrous, mock.patch.object(CO, "_controler", side_effect=AssertionError("verrou")):
            r = self.client.get(reverse("collecte:coherence"), secure=True)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(verrous.call_count, 0)

    def test_ouverture_avec_changement_memes_alertes_que_controler(self):
        self.saisir(self.eff, 150)
        self.saisir(self.form, 40)
        self.perimer()
        avant = self.etat()
        point = transaction.savepoint()
        with self.compter_verrous() as verrous:
            CO.controler_a_l_ouverture(self.c)
        self.assertEqual(verrous.call_count, 1)  # une différence : verrou pris, une fois
        ouverture = self.etat()
        transaction.savepoint_rollback(point)
        self.assertEqual(self.etat(), avant)
        CO.controler(self.c)  # référence : le contrôle de toujours
        self.assertEqual(ouverture, self.etat())
        self.assertNotEqual(ouverture, avant)
        self.assertTrue(Alerte.objects.filter(campagne=self.c, controle="format", statut=Alerte.Statut.OUVERTE).exists())

    def test_alerte_levee_a_l_ouverture(self):
        self.saisir(self.eff, 150)
        Reponse.objects.filter(periode=self.c.periode, kpi=self.eff, organisation=self.e1).update(valeur=D(100))
        CO.controler_a_l_ouverture(self.c)
        self.assertEqual(Alerte.objects.get(campagne=self.c, controle="ecart_n1").statut, Alerte.Statut.CORRIGEE)

    def test_course_l_etat_change_entre_la_detection_et_le_verrou(self):
        """Les valeurs changent après la détection sans verrou, avant le verrou : rien n'est écrit d'après la lecture
        dépassée ; l'état final est celui du contrôle fait sur les valeurs finales."""
        self.saisir(self.eff, 150)
        self.perimer()
        original = CO.controler

        def entre_temps():  # une saisie arrive entre les deux (FORM corrigé, EFF revenu à 100)
            Reponse.objects.filter(periode=self.c.periode, kpi=self.form, organisation=self.e1).update(valeur=D(40))
            Reponse.objects.filter(periode=self.c.periode, kpi=self.eff, organisation=self.e1).update(valeur=D(100))

        def controler_apres_course(campagne, kpi_ids=None):
            entre_temps()
            return original(campagne, kpi_ids)

        point = transaction.savepoint()
        with mock.patch.object(CO, "controler", side_effect=controler_apres_course):
            CO.controler_a_l_ouverture(self.c)
        course = self.etat()
        transaction.savepoint_rollback(point)
        entre_temps()
        original(self.c)
        self.assertEqual(course, self.etat())
        self.assertFalse(Alerte.objects.filter(campagne=self.c, controle="format").exists())  # jamais créée
        self.assertEqual(Alerte.objects.get(campagne=self.c, controle="ecart_n1").statut, Alerte.Statut.CORRIGEE)
