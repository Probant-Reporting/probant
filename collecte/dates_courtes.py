"""Date courte affichée à l'écran et dans les exports lisibles : la seule fonction, un format par langue.

Le format est dans les fichiers de la langue (clé « format.date_courte », modèle ``strftime``), comme les séparateurs de
nombres (« format.decimal ») : 01/03/2026 en français, espagnol, italien et portugais, 01.03.2026 en allemand, 01-03-2026 en
néerlandais, « 01 Mar 2026 » en anglais (jj/mm/aaaa y serait ambigu). Ajouter une langue ne demande aucun code ; langue sans
la clé : l'anglais.

Ne passent PAS par ici les formats d'échange : fichiers à réimporter (jj/mm/aaaa ou ISO, relus par les imports), noms de
fichiers, champs des paquets d'échange. Les dates SAISIES restent acceptées en jj/mm/aaaa et en aaaa-mm-jj
(``collecte/fichiers.py``) ; l'aide affichée dit le format attendu.
"""
import datetime

from django.utils import timezone

CLE = "format.date_courte"
HEURE = "%H:%M"


def modele(langue=None):
    """Modèle ``strftime`` de la langue (celle de l'interface par défaut)."""
    from parametres import langues as L
    from parametres import libelles as LB

    code = (langue or L.interface() or "fr").split("-")[0]
    for l in (code, LB.REPLI):
        t = LB.table(l).get(CLE)
        if t:
            return t
    return "%d/%m/%Y"


def _local(d):
    if isinstance(d, datetime.datetime) and timezone.is_aware(d):
        return timezone.localtime(d)
    return d


def date_courte(d, langue=None):
    """« 01/03/2026 » (selon la langue) ; vide si la date est vide. Un instant est lu à l'heure locale."""
    if not d:
        return ""
    return _local(d).strftime(modele(langue))


def date_heure_courte(d, langue=None):
    """Date courte suivie de l'heure (« 01/03/2026 14:05 ») ; l'heure est sur 24 heures dans toutes les langues."""
    if not d:
        return ""
    d = _local(d)
    return f"{d.strftime(modele(langue))} {d.strftime(HEURE)}"
