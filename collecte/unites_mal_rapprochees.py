"""KPI rangés dans une mauvaise unité par l'ancien rapprochement des unités (avant la mise à jour) : à l'installation d'un
modèle de la bibliothèque ou à l'import d'un fichier, une unité était reconnue après une normalisation qui retirait les
symboles et la casse (« €/h » rangée en « h », « m » en « M€ », « MW » en « mW »). La règle juste est dans
``parametres.rapprochement_unites``.

Deux traitements, aucune valeur changée ni convertie (elles ont été saisies en pensant à la bonne unité) :

- correction (``corriger``, travail après la mise à jour posé par ``collecte/0044``) : seulement pour un KPI d'un
  référentiel installé depuis la bibliothèque, dans la version même du modèle livré avec l'outil (même définition), quand
  son unité diffère de celle de la définition ET que l'ancienne règle, rejouée, rapproche l'une de l'autre alors que la
  règle juste ne le fait pas : c'est une erreur de l'outil, pas un choix de l'administrateur. L'unité juste est reprise
  (ou créée, avec ses traductions), une ligne d'historique par KPI ; la règle « unité figée » ne s'applique pas à cette
  seule correction ;
- signalement (``douteux``, contrôle de ``check_data`` et ligne de « À traiter ») : tout autre KPI dont le code est celui
  d'un KPI d'un modèle de la bibliothèque et dont l'unité ressemble à un rapprochement fautif (même rejeu, ou, pour une
  unité dont l'administrateur a renommé le symbole depuis, le code de l'unité choisie : ``renommee``) ; rien n'est
  corrigé seul (fichier référentiel dont on n'a plus la source, classeur de configuration, autre version du modèle).
"""
from dataclasses import dataclass
from functools import lru_cache

from parametres import rapprochement_unites as RU

from . import fichiers as X

CHAMP_JOURNAL = "Unité corrigée"


@dataclass
class Cas:
    kpi: object
    actuelle: object  # Unite
    voulue: dict  # unité de la définition (dict du paquet)
    modele: str  # code du modèle de la bibliothèque
    langue: str  # langue de référence du paquet

    @property
    def symbole_voulu(self):
        s = self.voulue.get("symbole") or {}
        return s.get(self.langue) or next(iter(s.values()), "") or self.voulue["code"]


def _normalises(obj, *champs):
    sortie = set()
    for c in champs:
        sortie.add(X.normaliser(getattr(obj, c, "") or ""))
        for d in (obj.traductions or {}).values():
            if isinstance(d, dict) and d.get(c):
                sortie.add(X.normaliser(d[c]))
    sortie.discard("")
    return sortie


def ancienne_regle(voulue, unite, langue):
    """Vrai si l'ancien rapprochement (``collecte/paquets/analyse.py`` avant la mise à jour, rejoué tel quel) pouvait
    reconnaître l'unité ``unite`` de l'installation pour l'unité ``voulue`` d'un paquet."""
    textes = voulue.get("symbole") or {}
    symboles = {X.normaliser(t) for t in textes.values() if t} or {X.normaliser(voulue["code"])}
    if unite.code == voulue["code"] and symboles & (_normalises(unite, "symbole", "libelle") | {X.normaliser(unite.code)}):
        return True
    if textes.get(langue) and unite.symbole == textes[langue]:
        return True
    return bool(symboles & _normalises(unite, "symbole"))


def _autre_monnaie(voulue, unite):
    """Vrai si l'unité ``unite`` est l'unité en euros ``voulue`` du modèle écrite dans une autre monnaie (« $/h » pour
    « €/h ») : modèle installé avec une autre monnaie de référence (parametres/monnaies.py), pas un rapprochement fautif."""
    from parametres import monnaies as MO

    voulus = [v for v in [voulue["code"], *(voulue.get("symbole") or {}).values()] if v]
    return any(MO.variante(v, s) for v in voulus for s in (unite.symbole, unite.code) if s)


def mal_rapprochee(voulue, unite, langue):
    """Vrai si l'unité ``unite`` d'un KPI n'est pas celle de la définition (``voulue``) et ne peut venir que de l'ancien
    rapprochement fautif : la règle juste ne la reconnaît pas, l'ancienne oui."""
    if unite is None:
        return False  # l'ancienne règle donnait toujours une unité : un KPI sans unité est un choix
    if RU.rapprocher_unite((voulue.get("symbole") or {}).values(), [unite], code=voulue["code"]).unite is not None:
        return False  # même unité (symbole, code ou traduction), ou écart de casse sans risque
    if _autre_monnaie(voulue, unite):
        return False
    return ancienne_regle(voulue, unite, langue)


def renommee(voulue, unite):
    """Vrai si l'unité ``unite`` d'un KPI n'est pas celle de la définition, mais que son CODE est ce que l'ancienne
    règle aurait reconnu pour le symbole voulu : l'administrateur a renommé ensuite son
    symbole (« h » devenu « heure »), et le rejeu sur le symbole (``mal_rapprochee``) ne voit plus rien. Le code d'une
    unité ne change pas ; c'est celui de l'unité que l'ancienne règle choisissait. Seulement signalé (``douteux``),
    jamais corrigé seul : le renommage est un geste de l'administrateur."""
    if unite is None:
        return False
    if RU.rapprocher_unite((voulue.get("symbole") or {}).values(), [unite], code=voulue["code"]).unite is not None:
        return False
    if _autre_monnaie(voulue, unite):
        return False
    symboles = {X.normaliser(t) for t in (voulue.get("symbole") or {}).values() if t} or {X.normaliser(voulue["code"])}
    return X.normaliser(unite.code) in symboles


@lru_cache(maxsize=1)
def _definitions():
    """{code d'un KPI : [(code du modèle, identifiant, version, langue, unité voulue)]} des modèles de la bibliothèque, et
    des socles retirés (``socles_retires.py``) : leurs KPI restent dans les installations qui les avaient."""
    from referentiel.bibliotheque import socles as S
    from referentiel.bibliotheque.socles_retires import SOCLES_RETIRES

    from .paquets import BIBLIOTHEQUE, depuis_json

    sortie = {}
    paquets = [depuis_json(chemin.read_text(encoding="utf-8")) for chemin in sorted(BIBLIOTHEQUE.glob("*.json"))]
    fournis = {p.code for p in paquets}
    paquets += [S.paquet(s) for s in SOCLES_RETIRES if s["code"] not in fournis]
    for p in paquets:
        unites = {u["code"]: u for u in p.unites}
        ref = p.referentiel
        for k in p.kpis:
            u = unites.get(k.get("unite") or "")
            if u is not None:
                sortie.setdefault(k["code"], []).append((ref.get("code") or "", str(ref.get("identifiant") or ""),
                                                         str(ref.get("version") or ""), p.langue_reference, u))
    return sortie


def _cas(seulement_corrigeables):
    from referentiel.models import KPI, ElementReferentiel, Referentiel

    from .paquets import comparer_versions

    definitions = _definitions()
    refs = {str(r.identifiant): r for r in Referentiel.objects.all()}
    places = {}
    for ref_id, kpi_id in ElementReferentiel.objects.filter(kpi_id__in=list(definitions)).values_list("referentiel_id", "kpi_id"):
        places.setdefault(kpi_id, set()).add(ref_id)
    sortie = []
    for kpi in KPI.objects.filter(code__in=list(definitions)).select_related("unite").order_by("code"):
        for modele, identifiant, version, langue, voulue in definitions[kpi.code]:
            if not mal_rapprochee(voulue, kpi.unite, langue):
                if not seulement_corrigeables and renommee(voulue, kpi.unite):  # symbole renommé depuis : signalé
                    sortie.append(Cas(kpi, kpi.unite, voulue, modele, langue))
                    break
                continue
            ref = refs.get(identifiant)
            corrigeable = (ref is not None and ref.code in places.get(kpi.code, ())
                           and comparer_versions(ref.version, version) == 0)
            if corrigeable or not seulement_corrigeables:
                sortie.append(Cas(kpi, kpi.unite, voulue, modele, langue))
                break
    return sortie


def a_corriger():
    """KPI à corriger seuls (modèle installé dans la version livrée, rejeu de l'ancienne règle), du plus petit code."""
    return _cas(True)


def douteux():
    """KPI dont l'unité ressemble à un rapprochement fautif (code d'un KPI d'un modèle de la bibliothèque), corrigeables
    ou non : pour ``check_data`` et « À traiter »."""
    return _cas(False)


def _unite_voulue(cas):
    """Unité de l'installation pour l'unité de la définition : reprise par la règle juste, sinon créée avec ses
    traductions (comme à l'installation d'un modèle)."""
    from parametres.models import Unite

    from .paquets.analyse_outils import unite_du_paquet

    u = cas.voulue
    trouvee = RU.rapprocher_unite((u.get("symbole") or {}).values(), Unite.objects.all(), code=u["code"])
    if trouvee.unite is not None and not trouvee.casse:
        return trouvee.unite
    obj = unite_du_paquet(u, cas.langue, Unite.objects.count() + 1)
    obj.save()
    return obj


def corriger():
    """Corrige l'unité des KPI de ``a_corriger`` (relus sous verrou), une ligne d'historique par KPI. Aucune valeur
    changée. Renvoie le nombre de KPI corrigés."""
    from espaces import contexte as ESP
    from parametres import langues as L
    from referentiel.models import KPI

    from .models import Journal

    n = 0
    with L.session():
        for cas in a_corriger():
            with ESP.atomic():
                kpi = KPI.objects.select_for_update().select_related("unite").get(pk=cas.kpi.pk)  # relu sous verrou
                if kpi.unite_id != cas.actuelle.pk or not mal_rapprochee(cas.voulue, kpi.unite, cas.langue):
                    continue
                unite = _unite_voulue(cas)
                avant = kpi.unite.symbole
                kpi.unite = unite
                kpi.save(update_fields=["unite"])  # la règle « unité figée » (écrans, imports) ne s'applique pas ici
                Journal.ecrire(None, "reglage_kpi", kpi, CHAMP_JOURNAL, avant,
                               f"{unite.symbole} (erreur de rapprochement à l'installation du modèle {cas.modele})")
                n += 1
    return n
