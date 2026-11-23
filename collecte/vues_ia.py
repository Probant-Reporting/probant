"""Prise IA côté collecte (docs/ai_socket.md) : expliquer une alerte de cohérence ; proposer les correspondances des
KPI dans l'assistant de reprise. Toute réponse est une proposition affichée, échappée, marquée « proposé par l'IA » :
rien n'est écrit sans un clic de la personne (le journal note seulement l'appel : parametres.ia.appeler).

Droits : l'explication est réservée aux rôles qui écrivent (administrateur, validateur, contributeur) et aux alertes
qu'ils voient (règle de la page Cohérence, coherence.peut_voir) ; lecteur et auditeur sont refusés avant la vue
(lecture_seule.py : une demande écrit une ligne au journal et compte dans un plafond payant). Les correspondances de
reprise sont réservées à l'administrateur, comme l'assistant.
"""
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.loader import render_to_string
from django.views.decorators.http import require_POST

from parametres import ia as IA
from parametres import ia_invites as INV
from parametres import langues as L
from parametres import libelles as LB
from parametres.ia_fournisseurs import ErreurIA
from parametres.libelles import libelle
from parametres.models import NiveauHierarchique

from . import coherence as CO
from . import saisie as S
from .calcul import NA
from .models import Alerte, Reponse
from .templatetags.collecte import formater
from .reponses_script import reponse_erreur
from .sensibles import alerte_sensible, caches_ia
from .vues_communes import est_script, exiger_admin


def peut_expliquer(utilisateur, alerte, cases=None):
    """Vrai si le bouton « Expliquer avec l'IA » s'affiche pour cette personne et cette alerte."""
    return (not utilisateur.lecture_seule and CO.explicable_par_ia(alerte) and IA.bouton_visible("expliquer_alerte")
            and CO.peut_voir(utilisateur, alerte, cases))


def donnees_alerte(a):
    """Ce qui part pour expliquer l'alerte ``a`` (docs/ai_socket.md, 6 a) : jamais le nom de l'organisation, ni les
    personnes, les commentaires, les explications ou les preuves."""
    k, p = a.kpi, a.campagne.periode
    niveau = NiveauHierarchique.objects.filter(code=a.organisation.niveau_id).first()
    # valeurs passées qui comptent (organisation ouverte, KPI demandé dans cette période : ``saisie.cases_comparables``)
    histo = [r for r in (Reponse.objects.filter(kpi=k, organisation=a.organisation, periode__type=p.type,
                                                periode__debut__lt=p.debut)
                         .select_related("periode").order_by("-periode__debut")[:INV.MAX_VALEURS_PASSEES * 2])
             if (r.kpi_id, r.organisation_id) in S.cases_comparables(r.periode, {(r.kpi_id, r.organisation_id)})
             ][:INV.MAX_VALEURS_PASSEES]
    d = {
        "answer_language": INV.nom_langue(L.interface()),
        "kpi": {"name": k.nom, "unit": getattr(k.unite, "symbole", "") or "", "format": getattr(k.type_reponse, "format", "")},
        "organisation_level": niveau.tr("nom") if niveau else "",
        "period": str(p),
        "check": LB.choix(a, "controle"),
        "severity": LB.choix(a, "gravite"),
        "finding": CO.constat_lisible(a),
        "value": CO.texte_alerte(a, "valeur"),
        "reference": CO.texte_alerte(a, "reference"),
        "previous_values": [{"period": str(r.periode), "value": formater(NA if r.non_applicable else r.valeur, k)} for r in histo],
    }
    if a.regle:
        from .vues_coherence import equation

        eq = equation(a)
        d["rule"] = {"name": a.regle.nom_affiche, "description": a.regle.description_affichee, "operator": a.regle.operateur}
        if eq:
            for cote in ("gauche", "droite"):
                d["rule"]["left" if cote == "gauche" else "right"] = [
                    {"kpi": (l["kpi"].nom if l["kpi"] else l["id"]), "value": l["valeur"], **({"period": l["annee"]} if l["annee"] else {})}
                    for l in eq[cote]["lignes"]]
    return d


def _fragment(request, ctx):
    return render_to_string("collecte/_ia_explication.html", ctx, request=request)


@login_required
@require_POST
def alerte_ia(request, pk):
    """Explication d'une alerte proposée par l'IA : fragment HTML (proposition, ou refus / erreur qui reste à l'écran)."""
    a = get_object_or_404(Alerte.objects.select_related("campagne__referentiel", "campagne__periode", "kpi__unite",
                                                        "kpi__type_reponse", "organisation", "regle"), pk=pk)
    if request.user.lecture_seule or not CO.peut_voir(request.user, a):
        raise PermissionDenied(libelle("saisie.coherence.erreur.hors_perimetre"))
    if not CO.explicable_par_ia(a, frozenset()):  # calcul impossible : rien n'est envoyé (son message cite des organisations)
        raise PermissionDenied(libelle("saisie.ia.refus.calcul"))
    if alerte_sensible(a, caches_ia()):  # KPI sensible ou dérivé, réglage éteint : rien n'est envoyé
        raise PermissionDenied(libelle("saisie.ia.refus.sensible"))
    if not est_script(request):
        return redirect("collecte:alerte", pk=a.pk)
    cible = request.POST.get("cible", "")
    cible = cible if cible in ("texte-just", f"justif-{a.pk}") else ""  # seulement le champ d'explication de cette alerte
    ctx = {"a": a, "cible": cible, "justifiable": CO.peut_justifier(request.user, a),
           "fournisseur": getattr(IA.fournisseur(), "nom", "")}
    try:
        ctx["proposition"] = IA.appeler(request.user, INV.expliquer_alerte(donnees_alerte(a)), a)
    except (IA.Refus, ErreurIA) as e:
        ctx["erreur"] = IA.message_erreur(e)
    return JsonResponse({"html": _fragment(request, ctx), "ok": "proposition" in ctx})


# ---------------------------------------------------------------- reprise : correspondances des KPI
@login_required
@require_POST
def reprise_ia(request):
    """Correspondances proposées par l'IA pour les libellés de KPI pas encore reliés de l'étape « Relier » : JSON
    {propositions: [{libelle, code, affiche, raison}]} ; rien n'est mémorisé ici."""
    from referentiel.models import KPI

    from . import reprise as R
    from .vues_reprise import CLE, lire_fichier

    exiger_admin(request)
    if not IA.disponible("reprise"):
        return reponse_erreur(libelle("admin.ia.refus.eteinte"))
    etat = dict(request.session.get(CLE) or {})
    onglets = lire_fichier(etat) if etat.get("chemin") else {}
    if not onglets:
        return reponse_erreur(libelle("admin.ia.reprise.rien"))
    r = R.Reglages.depuis(etat.get("reglages"))
    lignes = onglets.get(r.onglet) or next(iter(onglets.values()))
    props = [p for p in R.proposer_kpis(R.extraire(lignes, r), R.Contexte(r.source)) if not p.sur and not p.ignorer]
    if not props:
        return JsonResponse({"propositions": [], "message": libelle("admin.ia.reprise.tout_relie")})
    props = props[:INV.MAX_LIBELLES_REPRISE]
    # KPI sensibles et dérivés, réglage éteint : retirés de la liste envoyée (l'IA ne les propose jamais ; l'administrateur
    # les relie à la main, comme avant)
    kpis = list(KPI.objects.filter(actif=True).exclude(pk__in=caches_ia()).select_related("unite").order_by("ordre", "code"))
    invite = INV.reprise([(n, p.libelle, p.exemple) for n, p in enumerate(props, start=1)],
                         [(k.code, k.nom, getattr(k.unite, "symbole", "") or "") for k in kpis], L.interface())
    try:
        reponse = IA.appeler(request.user, invite, IA.instance())
    except (IA.Refus, ErreurIA) as e:
        return reponse_erreur(IA.message_erreur(e), status=400 if isinstance(e, IA.Refus) else 502)
    par_code = {k.code: k for k in kpis}
    sortie = []
    for n, p in enumerate(props, start=1):
        code, raison = reponse.get(n, ("", ""))
        k = par_code.get(code)
        sortie.append({"libelle": p.libelle, "code": code if k else "", "affiche": f"{k.code} – {k.nom[:90]}" if k else "",
                       "raison": raison})
    return JsonResponse({"propositions": sortie, "fournisseur": getattr(IA.fournisseur(), "nom", "")})
