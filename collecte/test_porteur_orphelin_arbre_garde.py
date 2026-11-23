"""Paramètre hérité porté par une organisation sans ancêtre du bon niveau (``Calculateur.porteur``, CALC-09) × arbre
gardé à la clôture × [X@N-1] × recalcul ciblé (soupçon de la, vérifié : pas de défaut).

S, rattachée directement au groupe en 2024, porte son propre facteur ; après la clôture de 2024, S passe sous Pays.
2024 rouvert « garder » suit l'arbre de sa clôture (S porte toujours son facteur) ; 2025 suit l'arbre d'aujourd'hui (S
reprend celui de Pays), et [FE@N-1] lit le facteur de S en 2024. Données inventées."""
import datetime
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from referentiel.composition import composer
from referentiel.models import KPI, Niveau, Organisation, Referentiel, Utilisateur

from . import calcul as C
from . import periodes as P
from . import saisie as S
from .administration import changer_statut
from .models import Campagne, Reponse

D = Decimal
FIN = timezone.localdate() + datetime.timedelta(days=30)


class PorteurOrphelinArbreGardeTests(TestCase):
    def test_correction_du_facteur_porte_par_l_orpheline(self):
        admin = Utilisateur.objects.create(username="admin", email="a@exemple.test", role=Utilisateur.Role.ADMIN)
        g = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        pays = Organisation.objects.create(nom="Pays", niveau_id=Niveau.COUNTRY, parent=g)
        e1 = Organisation.objects.create(nom="E1", niveau_id=Niveau.ENTITY, parent=pays)
        s = Organisation.objects.create(nom="S", niveau_id=Niveau.ENTITY, parent=g)  # sans pays : porte son facteur
        KPI.objects.create(code="EFF", libelle="Eff", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY, methode_agregation="Somme")
        KPI.objects.create(code="FE", libelle="FE", type_saisie_id="FE", granularite_id=Niveau.COUNTRY, methode_agregation="Aucune")
        KPI.objects.create(code="CO2", libelle="CO2", type_saisie_id="Calculé", granularite_id=Niveau.ENTITY,
                           methode_agregation="Somme", formule="[EFF]*[FE]")
        KPI.objects.create(code="CO2N", libelle="CO2N", type_saisie_id="Calculé", granularite_id=Niveau.ENTITY,
                           methode_agregation="Somme", formule="[EFF]*[FE@N-1]")
        ref = Referentiel.objects.create(code="RAP", nom="Rapport", ordre=1)
        composer({"EFF": ["S"], "FE": ["S"], "CO2": ["S"], "CO2N": ["S"]}, ref)
        c24, _ = P.campagne(ref, datetime.date(2024, 1, 1), statut=Campagne.Statut.OUVERTE, date_fin_saisie=FIN)
        c25, _ = P.campagne(ref, datetime.date(2025, 1, 1), statut=Campagne.Statut.OUVERTE, date_fin_saisie=FIN)
        for c, kpi, o, v in ((c24, "EFF", e1, 1), (c24, "EFF", s, 1), (c24, "FE", pays, 2), (c24, "FE", s, 5),
                             (c25, "EFF", e1, 10), (c25, "EFF", s, 10), (c25, "FE", pays, 3)):
            Reponse.objects.create(periode=c.periode, kpi_id=kpi, organisation=o, valeur=v, statut=Reponse.Statut.VALIDE)
        C.recalculer(c24)
        C.recalculer(c25)
        changer_statut(admin, c24, "cloturer")
        Organisation.objects.filter(pk=s.pk).update(parent=pays)
        C.recalculer_en_cours()
        changer_statut(admin, Campagne.objects.get(pk=c24.pk), "rouvrir", garder=True)
        c24 = Campagne.objects.get(pk=c24.pk)

        def lue(c, kpi, o):
            return Reponse.objects.get(periode=c.periode, kpi_id=kpi, organisation=o).valeur

        self.assertEqual(lue(c25, "CO2", s), 30)  # 2025 : facteur de Pays (arbre d'aujourd'hui)
        self.assertEqual(lue(c25, "CO2N", s), 50)  # facteur de S en 2024 (arbre de l'époque)
        S.enregistrer(admin, c24, KPI.objects.get(code="FE"), s, "6", False, "correction")
        self.assertEqual(lue(c24, "CO2", s), 6)
        self.assertEqual(lue(c24, "CO2", g), 2 + 6)
        self.assertEqual(lue(c25, "CO2N", s), 60)
        self.assertEqual(lue(c25, "CO2N", pays), 10 * 2 + 60)
        calc = C.Calculateur(c25)
        for o in (e1, s, pays, g):
            for kpi in ("CO2", "CO2N"):
                self.assertEqual(lue(c25, kpi, o), calc.valeur(kpi, o.pk), f"{kpi} {o.nom}")
