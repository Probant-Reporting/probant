"""Comparaison avec N-1 quand l'organisation n'était pas ouverte dans la période comparée, ou que le KPI n'y était pas
demandé (``saisie.cases_comparables``). Constat du relecteur : un site avec 10 en 2025 reçoit
après coup une date d'ouverture au 01/01/2026 ; le calcul ignore 2025 (``Calculateur.lisible``), mais la saisie de 100
en 2026 était bloquée (« l'écart avec N-1 dépasse 20 % ») et une alerte « +900 % » était créée. Données inventées."""
import datetime
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from referentiel.composition import composer
from referentiel.models import KPI, ElementReferentiel, Frequence, Niveau, Organisation, Referentiel, Utilisateur

from . import calcul as C
from . import periodes as P
from . import saisie as S
from .coherence import controler
from .models import Alerte, Campagne, Reponse

D = Decimal


class CasesComparablesN1Tests(TestCase):
    def setUp(self):
        self.admin = Utilisateur.objects.create(username="admin", email="a@exemple.test", role=Utilisateur.Role.ADMIN)
        g = Organisation.objects.create(nom="G", niveau_id=Niveau.GROUP)
        p = Organisation.objects.create(nom="P", niveau_id=Niveau.COUNTRY, parent=g)
        self.e = Organisation.objects.create(nom="E", niveau_id=Niveau.ENTITY, parent=p)
        self.f = Organisation.objects.create(nom="F", niveau_id=Niveau.ENTITY, parent=p)
        self.x = KPI.objects.create(code="X", libelle="X", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY,
                                    methode_agregation="Somme")
        self.ref = Referentiel.objects.create(code="A", nom="A", ordre=1, frequence=Frequence.ANNEE)
        composer({"X": ["S"]}, self.ref)
        self.c25, _ = P.campagne(self.ref, datetime.date(2025, 1, 1), statut=Campagne.Statut.OUVERTE)
        for o in (self.e, self.f):
            Reponse.objects.create(periode=self.c25.periode, kpi_id="X", organisation=o, valeur=D(10), statut="valide")
        c26, _ = P.campagne(self.ref, datetime.date(2026, 1, 1), statut=Campagne.Statut.OUVERTE)
        Campagne.objects.filter(pk=c26.pk).update(seuil_ecart=D("0.2"))
        self.c26 = Campagne.objects.get(pk=c26.pk)

    def ouvrir_en_2026(self):
        Organisation.objects.filter(pk=self.e.pk).update(date_ouverture=datetime.date(2026, 1, 1))  # posée après coup
        self.e.refresh_from_db()

    def saisir(self, org=None, v="100"):
        S.enregistrer(self.admin, self.c26, self.x, org or self.e, v, False, "")
        return Reponse.objects.get(periode=self.c26.periode, kpi_id="X", organisation=org or self.e)

    def test_pas_ouverte_en_n_1_ni_blocage_ni_alerte(self):
        self.ouvrir_en_2026()
        r = self.saisir()
        self.assertEqual(S.controles_validation(r, self.c26), [])
        controler(self.c26)
        self.assertFalse(Alerte.objects.filter(organisation=self.e, controle=Alerte.Controle.ECART_N1).exists())
        self.assertIsNone(S.reponse_n1(self.c26, self.x, self.e))
        self.assertEqual(S.valeurs_n1(self.c26, {("X", self.e.id), ("X", self.f.id)}).keys(), {("X", self.f.id)})

    def test_temoin_ouverte_en_n_1_bloque_toujours(self):
        """Sans date d'ouverture, l'écart de +900 % bloque et crée l'alerte, comme avant."""
        r = self.saisir()
        self.assertTrue(S.controles_validation(r, self.c26))
        controler(self.c26)
        self.assertTrue(Alerte.objects.filter(organisation=self.e, controle=Alerte.Controle.ECART_N1).exists())

    def test_panneau_sans_comparaison(self):
        self.ouvrir_en_2026()
        self.saisir()
        self.client.force_login(self.admin)
        rep = self.client.get(reverse("collecte:cellule", args=[self.c26.pk, "X", self.e.pk]))
        self.assertEqual(rep.status_code, 200)
        self.assertIsNone(rep.context["n1"])
        self.assertIsNone(rep.context["ecart"])
        self.assertEqual(rep.context["controles"], [])

    def test_grille_sans_n1(self):
        self.ouvrir_en_2026()
        self.saisir()
        lignes = [l for l in S.lignes(self.admin, self.c26) if l.organisation.id == self.e.id and l.kpi.code == "X"]
        self.assertEqual(len(lignes), 1)
        self.assertIsNone(lignes[0].n1)
        self.assertIsNone(lignes[0].ecart)

    def test_kpi_hors_du_perimetre_note_en_n_1(self):
        """X hors du périmètre noté à la clôture de 2025 (aucune case offerte ni calculée) : pas de comparaison."""
        from .models import Periode

        Periode.objects.filter(pk=self.c25.periode_id).update(perimetre_fige=[])
        Campagne.objects.filter(pk=self.c25.pk).update(statut=Campagne.Statut.CLOTUREE)
        r = self.saisir()
        self.assertEqual(S.controles_validation(r, self.c26), [])
        self.assertIsNone(S.reponse_n1(self.c26, self.x, self.e))

    def test_demande_depuis_seul_garde_la_comparaison(self):
        """X demandé seulement depuis 2026 mais une valeur 2025 existe (reprise) : le calcul la lit par [X@N-1], la
        comparaison reste (comme ``test_texte_redige.test_reponse_n1_en_repere``) ; à trancher."""
        ElementReferentiel.objects.filter(referentiel=self.ref, kpi_id="X").update(demande_depuis=datetime.date(2026, 1, 1))
        self.assertIsNotNone(S.reponse_n1(self.c26, self.x, self.e))

    def test_arbre_de_l_epoque_pour_un_exercice_clos(self):
        """2025 clos avec son arbre noté (E ouverte à l'époque) : la date d'ouverture posée ensuite ne change pas 2025,
        la comparaison reste (comme le calcul, ``Calculateur.lisible``)."""
        from .administration import changer_statut

        C.recalculer(self.c25)
        changer_statut(self.admin, self.c25, "cloturer")
        self.ouvrir_en_2026()
        self.assertIsNotNone(S.reponse_n1(self.c26, self.x, self.e))
