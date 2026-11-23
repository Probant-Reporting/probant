"""Monnaie de référence et KPI déjà dans l'installation (``analyse_kpis._analyser_kpis``) : à la mise à jour d'un modèle de
la bibliothèque, ou à la première installation d'un autre modèle qui partage des KPI monétaires, la monnaie d'un KPI déjà
présent n'est jamais réécrite (valeurs saisies, calculées ou aucune) ; seuls les KPI nouveaux prennent la monnaie de
référence. Aucune valeur n'est convertie."""
from decimal import Decimal

from django.test import TestCase

from parametres.models import Instance
from referentiel.models import KPI, Niveau, Organisation, Referentiel, Utilisateur

from . import paquets as P
from .models import Campagne, Reponse


def regler(code):
    i = Instance.courante()
    i.monnaie = code
    i.save()


def installer(fichier):
    p = P.fourni(fichier).paquet
    a = P.analyser(p, fourni=True)
    assert not a.erreur, a.erreur
    P.appliquer(None, a, sans_recalcul=True)
    return Referentiel.objects.get(identifiant=p.referentiel["identifiant"])


def symbole(code):
    return KPI.objects.get(pk=code).unite.symbole


class MiseAJourTests(TestCase):
    def test_kpi_calcule_et_source_sans_valeur_gardent_l_euro(self):
        admin = Utilisateur.objects.create_user("admin", "admin@exemple.test", "x", role=Utilisateur.Role.ADMIN)
        ref = installer("transparence_remunerations.json")
        org = Organisation.objects.create(nom="E1", niveau_id=Niveau.SITE)
        c = Campagne.objects.create(exercice=2025, statut=Campagne.Statut.OUVERTE)
        for code, valeur, origine in (("SOC-REMU-MOY-AN-F", 40000, Reponse.Origine.SAISIE), ("SOC-REMU-NB-F", 10, Reponse.Origine.SAISIE),
                                      ("SOC-REMU-TOT-AN-F", 400000, Reponse.Origine.CALCUL)):
            Reponse.objects.create(periode=c.periode, kpi_id=code, organisation=org, valeur=Decimal(valeur), origine=origine,
                                   statut=Reponse.Statut.VALIDE)
        regler("USD")
        f = P.fourni("transparence_remunerations.json")
        a, _ = P.analyser_installation(f.paquet, [k["code"] for k in f.paquet.kpis], existant=ref, nouvelle_version=True)
        self.assertEqual(a.compteurs["rejet"], 0)
        for code in ("SOC-REMU-MOY-AN-F", "SOC-REMU-TOT-AN-F", "SOC-REMU-MOY-AN-H", "SOC-REMU-TOT-AN-H"):
            self.assertIn(code, a.unites_gardees)
        P.appliquer(admin, a)
        for code in ("SOC-REMU-MOY-AN-F", "SOC-REMU-TOT-AN-F", "SOC-REMU-MOY-AN-H", "SOC-REMU-TOT-AN-H"):
            self.assertEqual(symbole(code), "€", code)
        self.assertEqual(Reponse.objects.get(kpi_id="SOC-REMU-MOY-AN-F").valeur, Decimal(40000))


class SecondModeleTests(TestCase):
    def test_kpi_partage_garde_son_unite_et_les_nouveaux_prennent_la_monnaie(self):
        installer("vs_base.json")
        regler("USD")
        a = P.analyser(P.fourni("esrs_g1.json").paquet, fourni=True)
        lignes = {l.code: l for l in a.kpis}
        self.assertEqual((lignes["GOV-AMENDES"].statut, a.compteurs["conflit"]), ("inchange", 0))
        self.assertEqual(a.unites_gardees, ["GOV-AMENDES"])
        P.appliquer(None, a, sans_recalcul=True)
        self.assertEqual(symbole("GOV-AMENDES"), "€")
        self.assertEqual(symbole("GOV-CONTRIBUTIONS-POLIT"), "$")
