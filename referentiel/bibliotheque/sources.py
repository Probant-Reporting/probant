"""Documents sur lesquels s'appuie un modèle de la bibliothèque (rubrique « Source documents »).

``SOURCE`` d'un fichier de ``definitions/`` est une LISTE de documents, un dictionnaire par document :

- ``titre``, ``editeur``, ``version`` : tels que le document les donne (et que le registre de l'atelier les note) ;
- ``date`` : date du document, ``AAAA-MM-JJ`` ou l'année seule (``AAAA``) quand le document n'écrit pas de date exacte ;
  jamais une date supposée ;
- ``url`` : adresse publique de l'éditeur ;
- ``consulte_le`` : jour où le document a été lu, ``AAAA-MM-JJ`` ;
- ``licence`` : ce que la licence permet, en une phrase (texte publiable : rien qui parle de l'atelier).

L'ancienne forme (un seul dictionnaire ``titre / editeur / version / url / consulte_le / licence``, sans ``date``) reste
lue : ``documents`` la range en une liste d'un document. Le paquet JSON d'un modèle porte cette liste (champ ``documents``) :
c'est par lui que l'outil l'affiche, sans rien ajouter en base. Dans l'atelier seulement, un test compare chaque document au
registre des références.
"""
import datetime
import re

CLES = ("titre", "editeur", "version", "date", "url", "consulte_le", "licence")
OBLIGATOIRES = ("titre", "editeur", "version", "url", "consulte_le", "licence")  # « date » : voir ci-dessous
ANNEE = re.compile(r"^\d{4}$")
INTERDIT = "refer" + r"ences/|atelier|workshop"  # un texte publié ne cite ni dossier de travail ni atelier


def documents(source):
    """Liste de documents ``[{clé: texte}]`` d'un ``SOURCE`` (liste, ancien dictionnaire seul, ou vide)."""
    if not source:
        return []
    if isinstance(source, dict):
        source = [source]
    return [{c: str(d.get(c, "")).strip() for c in CLES} for d in source]


def _jour(texte):
    try:
        return datetime.date.fromisoformat(texte) if len(texte) == 10 else None
    except ValueError:
        return None


def erreurs(source, strict=True):
    """Erreurs d'un ``SOURCE`` (liste de textes). ``strict`` : la date du document est aussi obligatoire (forme en liste)."""
    if not source:
        return ["SOURCE absente : au moins un document"] if strict else []
    if isinstance(source, dict):
        liste, forme_liste = [source], False
    elif isinstance(source, (list, tuple)) and all(isinstance(d, dict) for d in source):
        liste, forme_liste = list(source), True
    else:
        return ["SOURCE : une liste de documents (dictionnaires)"]
    sortie = []
    for i, d in enumerate(liste, start=1):
        nom = f"SOURCE, document {i}" if len(liste) > 1 else "SOURCE"
        manquants = [c for c in OBLIGATOIRES + (("date",) if forme_liste else ()) if not str(d.get(c, "")).strip()]
        if manquants:
            sortie.append(f"{nom} incomplète : " + ", ".join(manquants))
        inconnues = sorted(set(d) - set(CLES))
        if inconnues:
            sortie.append(f"{nom} : clés inconnues : " + ", ".join(inconnues))
        date, consulte = str(d.get("date", "")).strip(), str(d.get("consulte_le", "")).strip()
        if date and not (ANNEE.match(date) or _jour(date)):
            sortie.append(f"{nom} : date du document invalide « {date} » (AAAA-MM-JJ, ou l'année seule AAAA)")
        if consulte and not _jour(consulte):
            sortie.append(f"{nom} : date de consultation invalide « {consulte} » (AAAA-MM-JJ)")
        elif consulte and _jour(consulte) > datetime.date.today():
            sortie.append(f"{nom} : date de consultation dans le futur ({consulte})")
        if _jour(date) and _jour(date) > datetime.date.today():
            sortie.append(f"{nom} : date du document dans le futur ({date})")
        url = str(d.get("url", "")).strip()
        if forme_liste and url and not re.match(r"^https?://[^\s]+$", url):
            sortie.append(f"{nom} : adresse invalide « {url} » (une adresse http ou https, sans texte autour)")
        for c in ("titre", "editeur", "version", "licence") if forme_liste else ():
            if re.search(INTERDIT, str(d.get(c, "")), re.I):
                sortie.append(f"{nom} : « {c} » parle de l'atelier ou d'un dossier de travail (texte publié : rien de tel)")
    return sortie
