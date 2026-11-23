"""Validation d'une saisie (``saisie.valider``, ``repasser_brouillon``) × exercice rouvert « garder les chiffres de
l'époque » qui contient la période de la saisie.

Troisième passe du calcul (``qa/calculation_fuzz.py --v3``, graine 4264) : la validation ne change que le
statut de la case, mais le signal de la saisie lançait le recalcul ciblé ; l'exercice gardé qui contient le mois était
refait pour l'organisation, et son chiffre publié (le cumul des mois tel qu'à la clôture) prenait les valeurs des mois
saisies depuis : un chiffre publié bougeait sans aucune correction (README, « Keep the figures of the time » : seule une
organisation corrigée est recalculée). Une écriture qui ne touche que le statut, l'auteur ou les dates ne recalcule
rien (aucun calcul ne lit le statut). Données inventées."""
import datetime
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from referentiel.composition import composer
from referentiel.models import KPI, Frequence, Niveau, Organisation, Referentiel, Utilisateur

from . import calcul as C
from . import periodes as P
from . import saisie as S
from .administration import changer_statut
from .models import Campagne, Reponse

FIN = timezone.localdate() + datetime.timedelta(days=30)


class ValiderExerciceGardeTests(TestCase):
    def setUp(self):
        self.admin = Utilisateur.objects.create(username="admin", email="a@exemple.test", role=Utilisateur.Role.ADMIN)
        self.g = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        self.p = Organisation.objects.create(nom="Pays", niveau_id=Niveau.COUNTRY, parent=self.g)
        self.e1 = Organisation.objects.create(nom="E1", niveau_id=Niveau.ENTITY, parent=self.p)
        KPI.objects.create(code="X", libelle="X", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY,
                           methode_agregation="Somme")
        mens = Referentiel.objects.create(code="M", nom="Mensuel", ordre=1, frequence=Frequence.MOIS)
        composer({"X": ["S"]}, mens)
        an = Referentiel.objects.create(code="A", nom="Annuel", ordre=2, frequence=Frequence.ANNEE)
        composer({"X": ["S"]}, an)
        self.ca, _ = P.campagne(an, datetime.date(2025, 1, 1), statut=Campagne.Statut.OUVERTE, date_fin_saisie=FIN)
        self.mois = []
        for m in range(1, 13):
            cm, _ = P.campagne(mens, datetime.date(2025, m, 1), statut=Campagne.Statut.OUVERTE, date_fin_saisie=FIN)
            self.mois.append(cm)
            Reponse.objects.create(periode=cm.periode, kpi_id="X", organisation=self.e1, valeur=Decimal(1),
                                   statut=Reponse.Statut.BROUILLON, origine=Reponse.Origine.SAISIE)
            C.recalculer(cm)
        changer_statut(self.admin, self.ca, "cloturer")  # 2025 publié : 12
        # pendant la clôture de l'année, mars change (sa campagne reste ouverte) : l'année close ne bouge pas
        r = Reponse.objects.get(periode=self.mois[2].periode, kpi_id="X", organisation=self.e1)
        r.valeur = Decimal(5)
        r.save()
        changer_statut(self.admin, self.ca, "rouvrir", garder=True)

    def annee(self, org):
        return Reponse.objects.get(periode=self.ca.periode, kpi_id="X", organisation=org).valeur

    def test_valider_le_mois_ne_change_pas_le_chiffre_garde(self):
        self.assertEqual(self.annee(self.p), Decimal(12))
        S.valider(self.admin, self.mois[2], KPI.objects.get(code="X"), self.e1)
        self.assertEqual(Reponse.objects.get(periode=self.mois[2].periode, kpi_id="X", organisation=self.e1).statut,
                         Reponse.Statut.VALIDE)
        self.assertEqual((self.annee(self.e1), self.annee(self.p)), (Decimal(12), Decimal(12)))  # avant : 16, 16
        S.repasser_brouillon(self.admin, self.mois[2], KPI.objects.get(code="X"), self.e1)
        self.assertEqual(self.annee(self.p), Decimal(12))

    def test_corriger_le_mois_refait_le_chiffre_garde(self):
        # une vraie correction du mois (règle du README) refait l'organisation et ses totaux de l'époque
        S.enregistrer(self.admin, self.mois[2], KPI.objects.get(code="X"), self.e1, "6", False, "")
        self.assertEqual((self.annee(self.e1), self.annee(self.p)), (Decimal(17), Decimal(17)))
