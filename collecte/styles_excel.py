"""Styles Excel (police, alignement, remplissage, bordure, protection) créés une seule fois par jeu de réglages.

openpyxl range chaque style posé sur une cellule dans une liste du classeur, en le comparant à ceux déjà vus : un style
neuf pour chaque cellule coûte cher sur des milliers de lignes (rapport de revue, fichier à remplir). Ces fabriques
rendent le même objet pour les mêmes réglages. Un style déjà posé n'est jamais modifié dans l'outil (seules des
lectures, ex. ``cell.font.italic``) : le partager ne change rien au fichier produit.
"""
from functools import lru_cache

from openpyxl import styles as _styles
from openpyxl.utils.indexed_list import IndexedList

# Objets rendus par les fabriques ci-dessous, par identité : gardés à vie par le cache, jamais modifiés
PARTAGES = {}


def _partage(cls):
    @lru_cache(maxsize=None)
    def fabrique(*args, **kwargs):
        objet = cls(*args, **kwargs)
        PARTAGES[id(objet)] = objet
        return objet
    fabrique.__doc__ = cls.__doc__
    return fabrique


Alignment = _partage(_styles.Alignment)
Border = _partage(_styles.Border)
Font = _partage(_styles.Font)
PatternFill = _partage(_styles.PatternFill)
Protection = _partage(_styles.Protection)
Side = _partage(_styles.Side)


class ListeStyles(IndexedList):
    """Liste des polices (remplissages, alignements…) d'un classeur : un objet partagé (fabriques ci-dessus) retrouve son
    numéro par son identité, sans recalculer à chaque cellule l'empreinte de tous ses attributs (l'essentiel du temps
    d'écriture du rapport de revue et du fichier à remplir). Même numéro qu'openpyxl : le fichier ne change pas."""

    def __init__(self, iterable=None):
        super().__init__(iterable)
        self._rapide = {}

    def add(self, value):
        if PARTAGES.get(id(value)) is not value:
            return super().add(value)
        i = self._rapide.get(id(value))
        if i is None:
            i = self._rapide[id(value)] = super().add(value)
        return i


def accelerer(wb):
    """Listes de styles d'un classeur neuf remplacées par des ``ListeStyles`` (même contenu, même ordre)."""
    for nom in ("_fonts", "_fills", "_borders", "_alignments", "_protections"):
        setattr(wb, nom, ListeStyles(getattr(wb, nom)))
    return wb
