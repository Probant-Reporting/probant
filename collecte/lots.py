"""Lectures et suppressions par lots : SQLite refuse une requête de plus de 32 766 paramètres (« too many SQL variables »)."""
from itertools import islice

TAILLE_LOT = 500


def par_lots(valeurs, taille=TAILLE_LOT):
    """Découpe ``valeurs`` (toute séquence ou itérable) en listes d'au plus ``taille`` éléments."""
    it = iter(valeurs)
    while lot := list(islice(it, taille)):
        yield lot


def supprimer_par_pk(modele, pks, taille=TAILLE_LOT):
    """Supprime les lignes de ``modele`` dont la clé est dans ``pks``, par lots (sans liste de paramètres démesurée)."""
    for lot in par_lots(pks, taille):
        modele.objects.filter(pk__in=lot).delete()
