"""Formules cassées : ce qui empêche un KPI calculé de donner un résultat, pour le suivre et le corriger
(Administration › Référentiels › Formules à corriger, et une ligne dans « À traiter »).

Deux sortes :
- dans la formule elle-même (vue sans aucune donnée) : KPI calculé sans formule, formule illisible, KPI cité inconnu,
  KPI cité à réponse oui / non ou liste, boucle, KPI cité désactivé ;
- au calcul (vue dans les campagnes non clôturées) : cases en erreur, par exemple une division par zéro.
Une source simplement pas encore saisie n'est pas une formule cassée (la case est « incomplète »)."""
from django.core.exceptions import ValidationError

from parametres.libelles import libelle
from referentiel import formule as F
from referentiel.models import KPI, KPIFormule, verifier_formule

from .models import Campagne, Reponse

NUMERIQUES = ("nombre", "pourcentage")
EXEMPLES = 3


def dans_la_formule():
    """[{kpi, probleme, inactifs (codes des KPI cités désactivés, s'il y en a)}] des KPI calculés actifs dont la formule ne peut rien donner, quelles que soient les données."""
    tous = {k.code: k for k in KPI.objects.select_related("type_saisie", "type_reponse")}
    non_numeriques = {c for c, k in tous.items() if k.type_reponse_id and k.type_reponse.format not in NUMERIQUES}
    inactifs = {c for c, k in tous.items() if not k.actif}
    graphe = {}
    for c, s in KPIFormule.objects.filter(decalage="N").values_list("kpi_calcule_id", "kpi_source_id"):
        graphe.setdefault(c, set()).add(s)
    resultat = []
    for k in sorted(tous.values(), key=lambda k: k.code):
        if not k.actif or not k.est_calcule:
            continue
        texte = (k.formule or "").strip()
        if not texte:
            resultat.append({"kpi": k, "probleme": libelle("admin.formules.sans_formule")})
            continue
        try:
            verifier_formule(k.code, texte, set(tous), graphe, non_numeriques)
        except ValidationError as e:
            resultat.append({"kpi": k, "probleme": " ".join(e.messages)})
            continue
        cites = sorted({r.kpi for r in F.references(texte)} & inactifs)
        if cites:
            resultat.append({"kpi": k, "inactifs": cites,  # « inactifs » : un lien par KPI à réactiver
                             "probleme": libelle("admin.formules.sources_inactives", n=len(cites), codes=", ".join(cites))})
    return resultat


def au_calcul(campagnes=None):
    """[{kpi, n, message, exemples: [(organisation, campagne)]}] : cases en erreur dans les campagnes non clôturées
    (ou celles données), regroupées par KPI, les plus nombreuses d'abord."""
    if campagnes is None:
        campagnes = Campagne.objects.exclude(statut=Campagne.Statut.CLOTUREE)
    par_periode = {}
    for c in campagnes:
        par_periode.setdefault(c.periode_id, c)
    par_kpi = {}
    qs = (Reponse.objects.filter(periode_id__in=par_periode, statut=Reponse.Statut.ERREUR)
          .select_related("kpi", "organisation").order_by("kpi_id", "organisation__nom"))
    for r in qs:
        e = par_kpi.setdefault(r.kpi_id, {"kpi": r.kpi, "n": 0, "message": r.message_calcul, "exemples": []})
        e["n"] += 1
        if len(e["exemples"]) < EXEMPLES:
            e["exemples"].append((r.organisation, par_periode[r.periode_id]))
    for e in par_kpi.values():
        e["autres"] = e["n"] - len(e["exemples"])  # cases en erreur au-delà des exemples montrés
    return sorted(par_kpi.values(), key=lambda e: (-e["n"], e["kpi"].code))


def nombre():
    """Nombre de KPI à corriger (formule cassée, ou en erreur au calcul), pour « À traiter »."""
    return len({e["kpi"].code for e in dans_la_formule()} | {e["kpi"].code for e in au_calcul()})
