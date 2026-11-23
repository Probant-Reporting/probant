"""Modèles de la bibliothèque, un fichier Python par modèle (VSME, index d'égalité, décret tertiaire…).

Chaque fichier ``<nom>.py`` de ce dossier (sauf ceux qui commencent par « _ ») est un modèle. ``python3 manage.py
bibliotheque`` le contrôle (referentiel/bibliotheque/controle.py), puis écrit son paquet JSON et sa partie de
docs/library.md. Un fichier ``<nom>_coverage.csv`` à côté liste les exigences de la norme et ce que le modèle en fait
(KPI, texte rédigé, hors périmètre…) : le contrôle vérifie qu'aucune n'est oubliée.

Contenu d'un fichier de modèle :

- ``SOURCE`` : la norme d'origine {"titre", "editeur", "version", "url", "consulte_le", "licence"} ;
- ``SOCLE`` : code, fichier JSON, couleur, version, thématique, nom, description, arbre des thèmes, règles ;
- ``KPIS`` : les KPI nouveaux dans la bibliothèque, écrits avec ``outils.kpi`` (un KPI déjà défini ailleurs se réutilise
  par son code, sans le redéfinir) ;
- facultatifs : ``UNITES``, ``TYPES_REPONSE`` (listes de choix), ``REGLES`` (contrôles de cohérence).
"""
import importlib
import pkgutil
from pathlib import Path

DOSSIER = Path(__file__).resolve().parent


def charger(paquet=__name__, dossier=DOSSIER):
    """Modules des modèles du dossier, rangés par ``SOCLE["ordre"]`` puis par nom de fichier."""
    modules = []
    for info in sorted(pkgutil.iter_modules([str(dossier)]), key=lambda i: i.name):
        if info.name.startswith("_") or info.ispkg:
            continue
        m = importlib.import_module(f"{paquet}.{info.name}")
        if not hasattr(m, "SOCLE"):
            raise ImportError(f"{info.name}.py : pas de SOCLE (voir referentiel/bibliotheque/definitions/__init__.py)")
        modules.append(m)
    return sorted(modules, key=lambda m: (m.SOCLE.get("ordre", 100), m.__name__))


def couverture(module, dossier=DOSSIER):
    """Chemin du fichier de couverture d'un modèle (``<nom>_coverage.csv``), qu'il existe ou non. Un modèle d'une famille
    qui partage un inventaire maître (ESRS : ``esrs_coverage.csv``, colonne ``template``) le déclare dans ``COUVERTURE`` ;
    le contrôle n'en lit alors que ses lignes (controle._controler_couverture)."""
    return dossier / getattr(module, "COUVERTURE", f"{module.__name__.rsplit('.', 1)[-1]}_coverage.csv")
