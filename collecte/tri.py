"""Tri des listes par le serveur, comme les tableaux triables de la page (_app/13_tableaux.js) : colonne lue dans l'adresse
(``?tri-<tableau>=col`` croissant, ``-col`` décroissant), valeurs vides toujours en dernier, textes sans tenir compte des
majuscules ni des accents. Sert quand la page ne montre qu'une partie des lignes (Cohérence au-delà de 500 alertes,
Historique) : le tri se fait avant de couper."""
import unicodedata


def demande(request, tableau, colonnes):
    """(colonne, décroissant) demandés dans l'adresse pour ce tableau, ou ("", False) si la colonne n'est pas permise."""
    v = request.GET.get(f"tri-{tableau}", "")
    col = v[1:] if v.startswith("-") else v
    return (col, v.startswith("-")) if col in colonnes else ("", False)


def texte(v):
    """Clé de tri d'un texte : sans accents ni majuscules (« Éco » avec « eco »)."""
    t = unicodedata.normalize("NFKD", str(v or ""))
    return "".join(c for c in t if not unicodedata.combining(c)).casefold().strip()


def trier(objets, cle, decroissant=False):
    """Objets triés selon ``cle(objet)`` (None ou "" : en dernier, dans l'ordre d'arrivée) ; tri stable."""
    pleins, vides = [], []
    for o in objets:
        (vides if cle(o) in (None, "") else pleins).append(o)
    return sorted(pleins, key=cle, reverse=decroissant) + vides
