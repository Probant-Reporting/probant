"""ESRS E3 Eau (ESRS révisées, règlement délégué (UE) 2026/1563) : premier modèle de la famille ESRS, construit comme
exemple pour les autres (méthode : note de conception de l'atelier, non publiée ; socle commun : _esrs_communs.py).

Inventaire : lignes « ESRS_E3 » de esrs_coverage.csv (11 points de la liste de l'EFRAG du 28/08/2026, plus GDR-M). Choix :

- politiques, actions et cibles : bloc commun des exigences générales de l'ESRS 2 (``bloc_gdr``), saisi une fois pour
  l'entreprise (niveau « haut ») ; le tableau des actions clés a une colonne de plus, « zones de stress hydrique »
  (E3-2 §13 : une réponse par action) ;
- indicateurs saisis par site et additionnés : prélèvement (KPI de la norme volontaire VS, même définition), rejet,
  eau recyclée et réutilisée, eau stockée (un stock : dernière valeur de la période) ; consommation calculée
  (prélèvement − rejet, E3 AR 4) ; consommation en zone de stress hydrique : KPI propre à l'ESRS (tous les rejets déduits,
  E3 AR 4), distinct de celui de la VS (B6 §37 : rejets des procédés seulement) ;
- EAU-CONSO du catalogue n'est pas repris (il accepte le prélèvement à la place de la consommation) ni EAU-REJET-PROCESS
  de la VS (rejet des seuls procédés) : revue des doublons de l'atelier.
"""
from referentiel.bibliotheque.outils import ZERO, ZERO_EN, kpi

from . import _esrs_communs as C
from . import _esrs_lot_e as L

SOURCE = C.SOURCE
COUVERTURE = C.COUVERTURE
UNITES = C.UNITES
TYPES_REPONSE = C.TYPES_REPONSE + [
    C.type_actions("EAU-TAB-ACTIONS", ("Actions clés sur l'eau", "Key actions on water"), [
        C.colonne("stress", "Liée aux zones de stress hydrique", "Related to areas with water stress", "liste", "ESRS-OUI-NON")]),
]

PREFIXE = "EAU"
SITES = ("Relevés de compteurs, factures d'eau, autorisations de prélèvement et de rejet.",
         "Meter readings, water bills, withdrawal and discharge permits.")


def _d(fr, en, zero=True):
    """Description (fr, en), avec la phrase « Saisir 0 s'il n'y en a pas » pour une donnée additionnée."""
    return (fr + (ZERO if zero else ""), en + (ZERO_EN if zero else ""))


KPIS = dict([
    *C.bloc_gdr(PREFIXE, ("l'eau", "water"), type_actions_sujet="EAU-TAB-ACTIONS"),
    # ------------------------------------------------------------------ E3-1 – politiques
    kpi("EAU-STRESS-HORS-POLITIQUE", "Sites en zone de stress hydrique non couverts par les politiques sur l'eau",
        "Sites in water-stress areas not covered by the water policies", "", "Décompte", reponse="OuiNon", niveau=C.HAUT,
        description=("L'entreprise a-t-elle des sites situés dans des zones de stress hydrique que ses politiques sur l'eau ne "
                     "couvrent pas ? Si oui, la norme demande de le dire (E3-1 §11). Zones de stress hydrique : indicateurs de "
                     "E3 AR 2, par exemple un stress hydrique de base « élevé » ou plus dans l'outil Aqueduct du WRI.",
                     "Does the company have sites in areas with water stress that its water policies do not cover? If yes, "
                     "the standard asks to say so (E3-1 §11). Areas with water stress: indicators of E3 AR 2, for example a "
                     "baseline water stress of ‘High’ or more in the WRI Aqueduct tool."),
        source=("Politiques sur l'eau, liste des sites, outil Aqueduct du WRI.", "Water policies, list of sites, WRI Aqueduct tool.")),
    # ------------------------------------------------------------------ E3-4 – indicateurs de l'eau (activités propres)
    kpi("EAU-REJET", "Total des rejets d'eau", "Total water discharge", "m³",
        description=_d("Effluents et autres eaux qui quittent le site vers les eaux de surface, les eaux souterraines ou des "
                       "tiers pendant la période, en mètres cubes (E3-4 §16(d)).",
                       "Effluents and other water leaving the site to surface water, groundwater or third parties during the "
                       "period, in cubic metres (E3-4 §16(d))."),
        source=SITES),
    kpi("EAU-CONSOMMATION", "Consommation totale d'eau", "Total water consumption", "m³", "Somme", "Calculé",
        formule="[EAU-PRELEVEMENT] - [EAU-REJET]",
        description=("Calculée par l'outil : eau prélevée moins eau rejetée (E3-4 §16(a), E3 AR 4). C'est l'eau qui entre sur le "
                     "site et n'en ressort ni vers l'environnement ni vers un tiers.",
                     "Calculated by the tool: water withdrawn minus water discharged (E3-4 §16(a), E3 AR 4). It is the water "
                     "that enters the site and does not leave it to the environment or to a third party.")),
    kpi("EAU-RECYCLEE", "Total de l'eau recyclée et réutilisée", "Total water recycled and reused", "m³",
        description=_d("Eau et eaux usées (traitées ou non) utilisées plus d'une fois avant de quitter l'entreprise : dans le "
                       "même procédé (recyclée), dans un autre procédé ou un autre site de l'entreprise (réutilisée), en "
                       "mètres cubes (E3-4 §16(e)).",
                       "Water and wastewater (treated or not) used more than once before it leaves the company: in the same "
                       "process (recycled), in another process or another site of the company (reused), in cubic metres "
                       "(E3-4 §16(e))."),
        source=("Compteurs des boucles de recyclage, bilans de la station de traitement.",
                "Meters of the recycling loops, reports of the treatment plant.")),
    kpi("EAU-STOCKEE", "Total de l'eau stockée", "Total water stored", "m³", temps="derniere",
        description=_d("Eau contenue dans les installations de stockage ou les réservoirs du site à la fin de la période, en "
                       "mètres cubes (E3-4 §16(f)).",
                       "Water held in the storage facilities or reservoirs of the site at the end of the period, in cubic "
                       "metres (E3-4 §16(f))."),
        source=("Relevés de niveau des réservoirs, capacité des cuves.", "Reservoir level readings, tank capacity.")),
    kpi("EAU-CONSO-STRESS", "Consommation d'eau en zone de stress hydrique (tous les rejets déduits)",
        "Water consumption in areas with water stress (all discharges deducted)", "m³",
        description=_d("Pour un site situé dans une zone de stress hydrique (indicateurs de E3 AR 2, par exemple un stress "
                       "hydrique de base « élevé » ou plus dans l'outil Aqueduct du WRI) : sa consommation d'eau de la période, "
                       "eau prélevée moins toute l'eau rejetée, comme la consommation totale (E3-4 §16(b), E3 AR 4), en mètres "
                       "cubes ; un site hors zone de stress hydrique saisit 0. La norme volontaire VS a son propre KPI, qui ne "
                       "déduit que les rejets des procédés de production (B6 §37).",
                       "For a site located in an area with water stress (indicators of E3 AR 2, for example a baseline water "
                       "stress of ‘High’ or more in the WRI Aqueduct tool): its water consumption of the period, water withdrawn "
                       "minus all water discharged, like the total consumption (E3-4 §16(b), E3 AR 4), in cubic metres; a site "
                       "outside areas with water stress enters 0. The Voluntary Standard VS has its own KPI, which deducts only "
                       "the discharge of production processes (B6 §37)."),
        source=("Relevés de compteurs, factures d'eau, outil Aqueduct du WRI.", "Meter readings, water bills, WRI Aqueduct tool.")),
])

# Entrée progressive de l'ESRS 1 §126(a) (toutes les normes thématiques avant 2027 pour les petites entreprises de la
# première vague) : même phrase que dans G1, ajoutée à chaque KPI propre au modèle ; les KPI repris de la norme VS ou
# du catalogue ne la portent pas (une seule définition, qui se lirait aussi dans une installation VS seule).
KPIS = dict(L.avec_phase_in(KPIS.items(), L.PHASE_IN_G1))

# Règle portée par le KPI propre à l'ESRS : EAU-CONSO-STRESS et EAU-CONSOMMATION déduisent tous les deux
# tous les rejets (E3 AR 4), au même site. Elle ne porte jamais sur EAU-STRESS, KPI de la
# norme VS (B6 §37 : rejets des procédés seulement), qui donnait une fausse alerte (prélèvement 1 000, rejets des procédés
# 200 et sanitaires 300 : 800 > 500).
REGLES = {
    "Consommation en zone de stress hydrique ≤ consommation totale": (
        "[EAU-CONSO-STRESS]", "<=", "[EAU-CONSOMMATION]",
        ("La consommation d'eau d'un site en zone de stress hydrique fait partie de sa consommation totale (mêmes rejets "
         "déduits).",
         "The water consumption of a site in an area with water stress is part of its total consumption (same discharges "
         "deducted)."),
        "Consumption in water-stress areas ≤ total consumption"),
}


def _actions():
    """Partie « actions » du bloc GDR ; le tableau des actions répond aussi à E3-2 §13 (zones de stress hydrique)."""
    return [(code, ref + " ; E3-2 · 13" if code == "EAU-ACT-TAB" else ref) for code, ref in C.arbre_gdr(PREFIXE, "E3-2", "A")]


SOCLE = C.socle("ESRS_E3", "1.1", "2026-11-19", [
    ("E3_1", "E3-1 – Politiques relatives à l'eau", "E3-1 – Policies related to water", [
        *C.arbre_gdr(PREFIXE, "E3-1", "P"), ("EAU-STRESS-HORS-POLITIQUE", "E3-1 · 11")]),
    ("E3_2", "E3-2 – Actions et ressources relatives à l'eau", "E3-2 – Actions and resources related to water", _actions()),
    ("E3_3", "E3-3 – Cibles relatives à l'eau", "E3-3 – Targets related to water", C.arbre_gdr(PREFIXE, "E3-3", "T")),
    ("E3_4", "E3-4 – Indicateurs de l'eau", "E3-4 – Water metrics", [
        ("EAU-CONSOMMATION", "E3-4 · 16(a)"), ("EAU-CONSO-STRESS", "E3-4 · 16(b)"), ("EAU-PRELEVEMENT", "E3-4 · 16(c)"),
        ("EAU-REJET", "E3-4 · 16(d)"), ("EAU-RECYCLEE", "E3-4 · 16(e)"), ("EAU-STOCKEE", "E3-4 · 16(f)"),
        *C.arbre_gdr(PREFIXE, "E3-4", "M")]),
], regles=list(REGLES))
