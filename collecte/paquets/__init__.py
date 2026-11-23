"""Paquet référentiel : un référentiel et tout ce qu'il faut pour le recréer dans une autre installation.

Contenu : métadonnées (code, nom, description, version, origine, fréquence…), arbre des thèmes, KPI avec leurs
traductions, descriptions et champs personnalisés, place de chaque KPI dans le référentiel, unités, types de saisie et de
réponse, catégories de description, champs personnalisés, niveaux de saisie et règles de cohérence. Les sources des
formules qui ne sont pas dans le référentiel voyagent avec lui (au catalogue, sans place dans le référentiel).

Deux formes : un classeur Excel (échange entre installations, modèle « système existant » à remplir) et un fichier JSON
(référentiels fournis dans la bibliothèque de l'outil). Les deux donnent le même ``Paquet``.

Import : ``analyser`` montre l'aperçu (référentiel nouveau ou mise à jour avec ses différences, niveaux et réglages
repris ou créés, KPI nouveaux, modifiés, en conflit, retirés, thèmes, règles), puis ``appliquer`` enregistre selon les
choix. Rien n'est jamais supprimé : une valeur vide du paquet ne retire rien, un KPI absent d'une nouvelle version reste
dans le référentiel sauf si l'on demande explicitement de l'en retirer (il reste alors au catalogue, avec ses valeurs).
Un KPI dont le code existe déjà se réutilise (même KPI, une seule valeur : catalogue unique), se renomme (nouveau KPI)
ou s'ignore.
"""
# Paquet découpé en sous-modules ; tous les noms d'origine restent importables d'ici (noms privés compris),
# y compris les noms que l'ancien module importait lui-même.
import copy
import datetime
import json
import re
from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db.models import Max
from django.utils import timezone
from openpyxl.styles import Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

from parametres import couleurs as CO
from parametres import langues as L
from parametres import libelles as LB
from parametres import niveaux as N
from parametres.models import (CategorieDescription, ChampPersonnalise, Instance, Langue, NiveauHierarchique, TypeReponse,
                               TypeSaisie, Unite, valider_code_langue)
from referentiel import formule as F
from referentiel.composition import code_referentiel
from referentiel.echange import enregistrer_descriptions, reconstruire_toutes_dependances
from referentiel.models import (KPI, ElementReferentiel, Frequence, KPIFormule, Referentiel, Theme, valider_code_kpi,
                                valider_code_referentiel, verifier_formule)

from .. import fichiers as X
from .. import reglages as R
from ..models import Journal, RegleCoherence
from espaces import contexte as ESP

from .modele import (  # noqa: F401
    _t, FORMAT, AUTO, VERSION_FORMAT, BIBLIOTHEQUE, NUMERIQUES, PaquetInvalide, Paquet, texte_affiche, texte_dans_langue,
    documents_affiches,
)
from .extraction import (  # noqa: F401
    _textes, _valeurs, themes_ordonnes, _sources, _kpi_vers_dict, extraire,
    _extraire, niveaux_installation,
)
from .bibliotheque_json import (  # noqa: F401
    vers_json, depuis_dict, LISTES_PAQUET, _controler_forme, TEXTES_LISTES, ENTIERS_LISTES, depuis_json, Fourni,
    bibliotheque, ordre_modeles, fourni, comparer_versions, documents_fournis,
)
from .excel_ecriture import (  # noqa: F401
    COL_THEMES, COL_KPI, ESSENTIELLES_KPI, COL_MODELE, COL_REGLES, COL_NIVEAUX, COL_UNITES, COL_TYPES_SAISIE,
    COL_TYPES_REPONSE, COL_CATEGORIES, COL_CHAMPS, COL_LANGUES, REGLAGES, CHAMPS_REFERENTIEL, CHAMPS_MODELE,
    AUTRES_LIGNES_REFERENTIEL, SUFFIXE, REFERENCES, _colonnes, noms_references, codes_references, _cellule, _onglet,
    _listes, A_LIRE, A_LIRE_MODELE, classeur, _feuille_referentiel, _classeur, _avancees, _modele, _kpi_specs,
    _specs_modele, _kpi_vers_ligne, modele_vierge, exemple_paquet, nom_fichier, reponse_excel,
)
from .analyse_outils import (  # noqa: F401
    LigneKpi, Reglage, Analyse, _norm_textes, _libelles_obj, _uuid, _differences_textes, _etiq, _affiche,
    _differences_referentiel, _niveau, _code_libre, _poser_textes, _poser_valeurs, _reglage, _objet_reglage,
)
from .excel_lecture import (  # noqa: F401
    _en_tetes, _code_langue, _lire_table, ALIAS, lire, _lire, _kpi_depuis_ligne,
)
from .analyse_kpis import (  # noqa: F401
    _analyser_themes, _valeur_champ, _analyser_kpis, _niveaux_automatiques, _controle_kpi, _cible,
    _type_saisie_par_defaut, _code_kpi_libre, _differences_kpi, _differences_element, _controler_formules,
    _analyser_regles, _niveau_regle,
)
from .analyse import (  # noqa: F401
    analyser, _analyser, _analyser_langues, _analyser_referentiel, _analyser_niveaux, _analyser_reglages,
)
from .application import (  # noqa: F401
    Resultat, appliquer, _appliquer, _appliquer_referentiel, _appliquer_themes, _appliquer_kpis, _appliquer_elements,
)
from .composition import (  # noqa: F401
    sous_paquet, composer_depuis_paquet, selection, analyser_installation, resume_niveaux,
)
