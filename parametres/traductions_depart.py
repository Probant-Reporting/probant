"""Textes de départ dans les sept langues (niveaux, types de saisie et de réponse, catégories, unités fournies).

Les textes sont figés dans la migration ``parametres/0036_traductions_de_depart_sept_langues`` (une migration ne suit pas le
code) ; cette fonction rejoue la même complétion, additive, sur les éléments qu'une installation neuve ou vidée vient de créer
(``niveaux.creer_par_defaut``, ``referentiel.creer_par_defaut``). Une seule source : jamais deux listes à tenir à jour."""
import importlib

from django.apps import apps


def completer():
    """Ajoute les traductions manquantes aux éléments fournis (jamais un texte renommé ni une traduction déjà saisie)."""
    importlib.import_module("parametres.migrations.0036_traductions_de_depart_sept_langues").traduire(apps, None)
