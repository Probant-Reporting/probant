"""Visualisation v2 : moteur des visuels d'une vue (au-dessus de ``collecte.visualisation``, seule source de vérité).

Le serveur calcule, le navigateur dessine : les valeurs, totaux, parts, écarts, regroupements « Autres » et tris
arrivent en JSON, déjà limités au périmètre de la personne et déjà mis en forme (texte, unité, décimales). Le
navigateur (``static/js/visualisation.js``, Apache ECharts) ne refait aucun calcul de donnée.

- ``TYPES`` : les 9 formes (rendu, largeur et hauteur par défaut, nombre de KPI).
- ``Contexte`` : les filtres résolus (période automatique ou de « Je réponds à », comparaison N-1 ou période
  précédente, organisation et sommets du périmètre, référentiel et son plan, thèmes, brouillons, campagne du taux de
  remplissage) ; ``pour_visuel(v)`` applique les filtres propres d'un visuel.
- ``valider_vue`` : la définition propre d'une vue et ses erreurs ; ``compatibles``, ``par_defaut`` et
  ``suggestions`` : les règles des formes (§ 5.2 et 5.3 de la spécification).
- ``donnees`` : une seule ``Source`` pour tous les visuels d'une vue, puis un constructeur par forme. Chaque visuel
  porte son tableau de données (``tableau``, aussi utilisé par l'Excel) et sa phrase pour les lecteurs d'écran
  (``resume``).
- ``Perimetre``, ``publique``, ``est_masque``, ``garde``, ``fusionner`` : rien de hors du périmètre de la personne ne
  part vers le navigateur (ni code, ni nom, ni identifiant de KPI ou d'organisation) ; à l'enregistrement, ce que la
  page n'a pas reçu est gardé tel quel.

Tous les textes passent par ``parametres.libelles`` (fichiers ``libelles/visualisation.*.json``) ; les
contenus (noms des KPI, thèmes, unités, niveaux) restent traduits par leurs mécanismes habituels.
"""
# Paquet découpé en sous-modules ; tous les noms d'origine restent importables d'ici (noms privés compris),
# y compris les noms que l'ancien module importait lui-même.
import copy
import json
import logging
import re
import secrets
from collections import Counter
from decimal import ROUND_HALF_UP, Decimal, localcontext

from django.urls import reverse
from django.utils.crypto import salted_hmac

from parametres import libelles as LB
from referentiel.formule import NA
from referentiel.models import KPI, Referentiel, Theme
from referentiel.plans import Plan

from .. import periodes as P
from .. import saisie as S
from .. import visualisation as V
from ..models import Campagne, SelectionKPI

from .formes import (  # noqa: F401
    journal, TYPES, SPECIAUX, LARGEURS, HAUTEURS, AXES, SERIES, OPTIONS, FILTRES_DEFAUT, TAILLE_MAX,
    MAX_VISUELS, MAX_KPIS_GRAPHIQUE, MAX_KPIS_TABLEAU, MAX_PERIODES, MIN_PERIODES, MAX_CATEGORIES, MAX_SERIES,
    MAX_ORGS_COLONNES, MAX_BARRES_ORGS, MAX_SOMMETS_CHIFFRE, LIGNES_TABLEAU, ID_VISUEL, MOIS, lib, nouvel_id, arrondi,
    nombre, pourcent_texte, nombre_excel, formater, texte_point, etat_point, texte_lu, valeur_json, ecart, unite,
    meme_unite, additionnable, cellule,
)
from .filtres import (  # noqa: F401
    ID_MAX, _entier, filtres_depuis_adresse, nettoyer_filtres, _plan, _plan_de, codes_du_plan, codes_source,
    codes_source_fixes, libelle_source,
)
from .perimetre import (  # noqa: F401
    SOURCE, CASES, codes_visibles, Perimetre, _identifiant, filtres_publics, publique, est_masque, masques, projeter,
    _empreinte, garde, GARDE, lire_garde, non_recus, _completer, fusionner, fusionner_filtres, _filtres_visuel,
    _options, valider_visuel, plafond_visuels, valider_vue, lire_json,
)
from .contexte import (  # noqa: F401
    Contexte,
)
from .compatibilites import (  # noqa: F401
    _raison_dessous, compatibles, par_defaut, suggestions,
)
from .constructeurs import (  # noqa: F401
    cat_periode, cat_org, cat_kpi, serie, serie_brute, rogner, tableau_generique, _formats, _oc, _org_pour_comparer,
    _noter, _chiffre, _barres, _parts_cent, _barres_empilees, _courbe, _anneau, _tableau, _organisations,
    _comparaison_n1, remplissage_compteurs, _remplissage, CONSTRUCTEURS,
)
from .assemblage import (  # noqa: F401
    titre_auto, sous_titre, resume, sans_rien_a_dessiner, source_masquable, construire, erreur_visuel, donnees,
    donnees_et_contexte, _donnees, options_filtres,
)
