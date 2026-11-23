"""« Revenir au calcul » sur une valeur forcée (``forcage.revenir_au_calcul``) : seuls l'administrateur (campagne non
clôturée) et un validateur de l'organisation (saisie ouverte) peuvent remettre la case au résultat du calcul. Le
contributeur responsable du résultat demande une valeur forcée, mais ne la lève pas lui-même."""
import datetime
from decimal import Decimal

from django.core.exceptions import PermissionDenied
from django.utils import timezone

from referentiel.models import Attribution, Utilisateur

from . import forcage as FO
from .models import Campagne, Reponse
from .aides_tests.saisie import Base

D = Decimal


class RevenirAuCalculDroitsTests(Base):
    def setUp(self):
        super().setUp()
        Attribution.objects.create(kpi=self.calc, organisation=self.e1, utilisateur=self.contrib)  # responsable du résultat
        self.enregistrer("40")  # DBL = EFF × 2 = 80 dans E1
        self.lecteur = Utilisateur.objects.create(username="lect", email="lect@exemple.test", role=Utilisateur.Role.LECTEUR)
        self.auditeur = Utilisateur.objects.create(username="aud", email="aud@exemple.test", role=Utilisateur.Role.AUDITEUR)
        self.forcer()

    def case(self):
        return Reponse.objects.get(periode=self.c.periode, kpi=self.calc, organisation=self.e1)

    def forcer(self):
        FO.demander(self.admin, self.c, self.calc, self.e1, "75", False, "Chiffre publié")
        self.assertEqual((self.case().origine, self.case().valeur), (Reponse.Origine.FORCEE, D(75)))

    def test_refuse_a_tout_autre_role(self):
        for u in (self.contrib, self.autre, self.lecteur, self.auditeur):
            self.assertFalse(FO.peut_trancher(u, self.c, self.calc, self.e1), u.username)
            with self.assertRaises(PermissionDenied, msg=u.username):
                FO.revenir_au_calcul(u, self.c, self.calc, self.e1, "Essai")
            self.assertEqual((self.case().origine, self.case().valeur), (Reponse.Origine.FORCEE, D(75)), u.username)

    def test_validateur_et_administrateur_reviennent_au_calcul(self):
        for u in (self.valid, self.admin):
            self.assertTrue(FO.peut_trancher(u, self.c, self.calc, self.e1), u.username)
            FO.revenir_au_calcul(u, self.c, self.calc, self.e1, "Détail complet")
            self.assertEqual((self.case().origine, self.case().valeur), (Reponse.Origine.CALCUL, D(80)), u.username)
            self.forcer()

    def test_validateur_refuse_apres_la_fin_de_la_saisie(self):
        Campagne.objects.filter(pk=self.c.pk).update(date_fin_saisie=timezone.localdate() - datetime.timedelta(days=1))
        c = Campagne.objects.get(pk=self.c.pk)
        with self.assertRaises(PermissionDenied):
            FO.revenir_au_calcul(self.valid, c, self.calc, self.e1)
        self.assertEqual(self.case().origine, Reponse.Origine.FORCEE)
        FO.revenir_au_calcul(self.admin, c, self.calc, self.e1)  # l'administrateur, tant que la campagne n'est pas clôturée
        self.assertEqual(self.case().origine, Reponse.Origine.CALCUL)
