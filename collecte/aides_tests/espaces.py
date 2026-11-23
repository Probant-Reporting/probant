"""Aides des tests des espaces qui touchent aux données de collecte : une organisation, un KPI, une campagne et une valeur."""
from decimal import Decimal


from collecte.models import Campagne, Reponse
from espaces import contexte as E
from referentiel.models import KPI, Niveau, Organisation


def jeu(espace, nom_org, code_kpi):
    """Une organisation, un KPI, une campagne ouverte et une valeur, dans l'espace ``espace``."""
    with E.activer(espace):
        g = Organisation.objects.create(nom=nom_org, niveau_id=Niveau.GROUP)
        KPI.objects.create(code=code_kpi, type_saisie_id="Saisi", granularite_id=Niveau.GROUP,
                           methode_agregation="Somme")
        c = Campagne.objects.create(exercice=2026, statut=Campagne.Statut.OUVERTE)
        r = Reponse.objects.create(periode=c.periode, kpi_id=code_kpi, organisation=g, valeur=Decimal(42),
                                   origine=Reponse.Origine.SAISIE, statut=Reponse.Statut.VALIDE)
        return g, c, r
