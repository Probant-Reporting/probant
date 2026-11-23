"""KPI sensibles et leurs dérivés : une seule définition pour les deux portes de sortie vers un assistant (deux décisions) :

- assistants MCP (``serveur_mcp/outils.py``, réglage ``ReglageMCP.kpi_sensibles``, allumé par défaut) ;
- prise IA (``parametres/ia.py``, réglage ``Instance.ia_kpi_sensibles``, éteint par défaut ; docs/ai_socket.md).

Un KPI est sensible s'il est marqué « Restreint » ou « Confidentiel » sur sa fiche (``conservation.SENSIBLES``) ; ses
dérivés sont les KPI calculés dont une source, de proche en proche, est sensible. Une alerte est sensible si elle porte
sur un tel KPI : sa case, un KPI de sa règle (noté à la détection) ou un KPI cité aujourd'hui par les formules de sa
règle (une règle modifiée depuis la détection).
"""
from referentiel.models import KPI

from .conservation import SENSIBLES


def sensibles_et_derives(sensibles):
    """KPI sensibles et KPI calculés dont une source, de proche en proche, est sensible :
    ``[S] * 1``, ``[A] / [S]``, ``[S@N-1]``, une formule qui cite une telle formule. Un cumul dans le temps ou un total
    par organisation garde le code du KPI : déjà caché. Les formules sont relues (et non la table des sources, qu'une
    formule illisible laisse vide) ; une formule illisible ne cite rien."""
    from referentiel import formule as F

    if not sensibles:
        return frozenset()
    citants = {}
    for code, formule in KPI.objects.filter(type_saisie__comportement="calcul").values_list("code", "formule"):
        try:
            for ref in F.references(formule or ""):
                citants.setdefault(ref.kpi, set()).add(code)
        except F.FormuleInvalide:
            continue
    caches, pile = set(sensibles), list(sensibles)
    while pile:
        for c in citants.get(pile.pop(), ()):
            if c not in caches:
                caches.add(c)
                pile.append(c)
    return frozenset(caches)


def codes_sensibles():
    """Codes de tous les KPI sensibles de l'espace et de leurs dérivés (frozenset ; vide sans KPI sensible : une requête)."""
    return sensibles_et_derives(set(KPI.objects.filter(confidentialite__in=SENSIBLES).values_list("pk", flat=True)))


def caches_ia():
    """KPI dont rien ne part chez le fournisseur de la prise IA : vide quand le réglage de l'espace « Les KPI sensibles
    peuvent être envoyés à l'assistant IA » est allumé, sinon les sensibles et leurs dérivés."""
    from parametres.models import Instance

    if Instance.courante().ia_kpi_sensibles:
        return frozenset()
    return codes_sensibles()


def kpis_regle(regle):
    """Codes des KPI cités aujourd'hui par les deux côtés d'une règle (une formule illisible ne cite rien)."""
    from referentiel import formule as F

    codes = set()
    for cote in (regle.gauche, regle.droite):
        try:
            codes |= {r.kpi for r in F.references(cote or "")}
        except F.FormuleInvalide:
            continue
    return codes


def alerte_sensible(alerte, caches):
    """Vrai si l'alerte cite un KPI de ``caches`` : sa case, un KPI de sa règle noté à la détection ou cité aujourd'hui."""
    if not caches:
        return False
    if alerte.kpi_id in caches or any(k in caches for k in (alerte.kpis_concernes or "").split()):
        return True
    return bool(alerte.regle_id and kpis_regle(alerte.regle) & caches)
