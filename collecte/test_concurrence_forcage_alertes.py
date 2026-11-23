"""Décisions concurrentes : deux personnes qui tranchent la même demande de valeur forcée ou la même alerte à partir
d'une page ouverte en même temps (objet lu avant la décision de l'autre). Le second reçoit « déjà traitée » ; rien de
contradictoire n'est écrit (journal, case forcée malgré le refus, mise à jour écrasée)."""
from decimal import Decimal
from unittest import mock

from django.core.exceptions import ValidationError

from referentiel.models import Attribution

from . import coherence as CO
from . import forcage as FO
from .models import Alerte, DemandeForcage, Journal, Reponse
from .test_coherence import CoherenceTests
from .aides_tests.saisie import Base

D = Decimal


class ForcageConcurrentTests(Base):
    def setUp(self):
        super().setUp()
        Attribution.objects.create(kpi=self.calc, organisation=self.e1, utilisateur=self.contrib)
        self.enregistrer("40")
        self.d = FO.demander(self.contrib, self.c, self.calc, self.e1, "75", False, "Correction")
        self.premiere, self.seconde = (DemandeForcage.objects.get(pk=self.d.pk) for _ in range(2))  # deux pages ouvertes

    def reponse(self):
        return Reponse.objects.get(periode=self.c.periode, kpi=self.calc, organisation=self.e1)

    def test_refus_puis_accord_perime(self):
        FO.refuser(self.admin, self.c, self.premiere, "Non justifié")
        with self.assertRaisesMessage(ValidationError, "déjà été traitée"):
            FO.accepter(self.valid, self.c, self.seconde)
        self.assertEqual((self.reponse().origine, self.reponse().valeur), (Reponse.Origine.CALCUL, D(80)))  # pas forcée
        self.d.refresh_from_db()
        self.assertEqual((self.d.statut, self.d.traite_par), (DemandeForcage.Statut.REFUSEE, self.admin))
        self.assertEqual(Journal.objects.filter(action__in=["forcage_accepte", "forcage_refuse"]).count(), 1)

    def test_accord_puis_refus_perime(self):
        FO.accepter(self.admin, self.c, self.premiere)
        with self.assertRaisesMessage(ValidationError, "déjà été traitée"):
            FO.refuser(self.valid, self.c, self.seconde, "Trop tard")
        self.d.refresh_from_db()
        self.assertEqual((self.d.statut, self.d.motif), (DemandeForcage.Statut.ACCEPTEE, ""))
        self.assertEqual(self.reponse().origine, Reponse.Origine.FORCEE)

    def test_retrait_perime(self):
        FO.accepter(self.admin, self.c, self.premiere)
        with self.assertRaisesMessage(ValidationError, "déjà été traitée"):
            FO.retirer(self.contrib, self.c, self.seconde)
        self.d.refresh_from_db()
        self.assertEqual(self.d.statut, DemandeForcage.Statut.ACCEPTEE)

    def test_prise_conditionnelle(self):
        """Même si la relecture était périmée (SQLite ignore le verrou), la mise à jour conditionnelle refuse."""
        DemandeForcage.objects.filter(pk=self.d.pk).update(statut=DemandeForcage.Statut.REFUSEE)
        with self.assertRaisesMessage(ValidationError, "déjà été traitée"):
            FO._prendre(self.admin, self.seconde, DemandeForcage.Statut.ACCEPTEE)

    def test_vue_du_second(self):
        FO.refuser(self.admin, self.c, self.premiere, "Non justifié")
        self.assertEqual(FO.en_attente(self.c.periode, self.calc, self.e1), None)


class AlerteConcurrenteTests(CoherenceTests):
    def setUp(self):
        super().setUp()
        self.saisir(self.eff, 150)
        a = self.alertes(controle="ecart_n1").get()
        CO.traiter(self.contrib, a, "justifier", "Ouverture d'un site")
        self.premiere, self.seconde = (Alerte.objects.get(pk=a.pk) for _ in range(2))

    def test_deux_decisions_de_l_admin(self):
        CO.traiter(self.admin, self.premiere, "accepter")
        with self.assertRaisesMessage(ValidationError, "déjà traité cette alerte"):
            CO.traiter(self.admin, self.seconde, "rejeter", "Pas convaincant")
        a = Alerte.objects.get(pk=self.premiere.pk)
        self.assertEqual(a.statut, Alerte.Statut.ACCEPTEE)
        self.assertNotIn("Pas convaincant", a.justification)
        self.assertEqual(Journal.objects.filter(action__in=["alerte_accepter", "alerte_rejeter"]).count(), 1)

    def test_decision_n_ecrase_pas_une_mise_a_jour_du_controle(self):
        """Seuls les champs de la décision sont écrits : un message mis à jour entre-temps reste."""
        Alerte.objects.filter(pk=self.premiere.pk).update(message="Message mis à jour par le contrôle")
        CO.traiter(self.admin, self.seconde, "accepter")
        a = Alerte.objects.get(pk=self.premiere.pk)
        self.assertEqual((a.statut, a.message), (Alerte.Statut.ACCEPTEE, "Message mis à jour par le contrôle"))
        self.assertEqual(self.seconde.statut, Alerte.Statut.ACCEPTEE)  # l'objet de l'appelant suit

    def test_mise_a_jour_conditionnelle(self):
        """Statut changé entre la relecture et l'écriture : refus, rien d'écrit."""
        perimee = self.seconde

        def relue_perimee():
            Alerte.objects.filter(pk=perimee.pk).update(statut=Alerte.Statut.REJETEE)  # l'autre décide à cet instant
            return mock.Mock(filter=lambda **k: mock.Mock(first=lambda: perimee))
        with mock.patch.object(Alerte.objects, "select_for_update", relue_perimee), \
                self.assertRaisesMessage(ValidationError, "déjà traité cette alerte"):
            CO.traiter(self.admin, self.seconde, "accepter")
        # (l'écriture simulée de l'autre, faite dans la même transaction, est annulée avec elle)
        self.assertNotEqual(Alerte.objects.get(pk=self.premiere.pk).statut, Alerte.Statut.ACCEPTEE)
        self.assertFalse(Journal.objects.filter(action="alerte_accepter").exists())
