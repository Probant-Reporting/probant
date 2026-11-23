"""Page « Valeurs forcées » (collecte/forcage.py) : demandes à accepter ou refuser (administrateur, validateur), demandes
de la personne, résultats calculés dont elle est responsable, valeurs forcées en place. Chaque ligne ouvre la case dans
le panneau de saisie, où se font la demande et la décision."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from parametres.libelles import libelle

from . import forcage as FO
from . import saisie as S
from .lots import par_lots
from .models import DemandeForcage, Reponse
from .templatetags.collecte import formater
from .vues_communes import identifiant


def _texte(valeur, na, kpi):
    return "N/A" if na else formater(valeur, kpi) if valeur is not None else "–"


@never_cache
@login_required
def forcages(request):
    from .views import groupes_campagnes
    from .vues_communes import campagne_affichee

    campagne = campagne_affichee(request)
    if campagne is None:
        return render(request, "collecte/aucune_campagne.html")
    u = request.user
    a_trancher = [(d, _texte(d.valeur, d.non_applicable, d.kpi)) for d in FO.demandes_a_traiter(u, [campagne])]
    miennes = [(d, _texte(d.valeur, d.non_applicable, d.kpi)) for d in DemandeForcage.objects.filter(periode=campagne.periode, demandeur=u)
               .select_related("kpi__unite", "kpi__type_reponse", "organisation", "traite_par")[:100]]
    cases = sorted(S.resultats_responsable(u, campagne), key=lambda p: (S.cle_arbre(p[1]), p[0].ordre, p[0].code))
    # seules les réponses des KPI dont la personne est responsable (et non tous les calculés de la période) sont lues
    valeurs = {(r.kpi_id, r.organisation_id): r for lot in par_lots(sorted({k.code for k, _ in cases}))
               for r in Reponse.objects.filter(periode=campagne.periode, kpi_id__in=lot).filter(kpi__type_saisie__comportement="calcul")}
    responsable = []
    for k, o in cases:
        r = valeurs.get((k.code, o.id))
        responsable.append((k, o, r, _texte(r.valeur if r else None, bool(r and r.non_applicable), k)))
    en_place = [(r, _texte(r.valeur, r.non_applicable, r.kpi))
                for r in (Reponse.objects.filter(periode=campagne.periode, origine=Reponse.Origine.FORCEE)
                          .select_related("kpi__unite", "kpi__type_reponse", "organisation", "saisi_par", "valide_par"))
                if S.voit_calcules(u, r.organisation) or r.saisi_par_id == u.pk]
    # chiffres importés tels quels sur des cases calculées (données d'avant la règle) : à forcer ou à retirer, par qui
    # peut forcer la case
    importees = [(r, _texte(r.valeur, r.non_applicable, r.kpi)) for r in FO.importees(campagne)
                 if FO.peut_trancher(u, campagne, r.kpi, r.organisation)]
    return render(request, "collecte/forcages.html", {
        "page": "forcages", "campagne": campagne, "a_trancher": a_trancher, "miennes": miennes, "responsable": responsable,
        "en_place": en_place, "importees": importees, "groupes_campagnes": groupes_campagnes(u),
    })


@login_required
@require_POST
def importee(request):
    """« Forcer » ou « Retirer » un chiffre importé sur une case calculée (section de la page Valeurs forcées)."""
    from referentiel.models import KPI, Organisation

    from .models import Campagne

    campagne = get_object_or_404(Campagne, pk=identifiant(request.POST.get("campagne")))
    kpi = get_object_or_404(KPI, code=request.POST.get("kpi", ""))
    org = get_object_or_404(Organisation, pk=identifiant(request.POST.get("organisation")))
    try:
        if request.POST.get("action") == "forcer":
            FO.forcer_importee(request.user, campagne, kpi, org)
            messages.success(request, libelle("saisie.forcage.msg.importee_forcee", kpi=kpi.code, organisation=org.nom))
        else:
            FO.retirer_importee(request.user, campagne, kpi, org)
            messages.success(request, libelle("saisie.forcage.msg.importee_retiree", kpi=kpi.code, organisation=org.nom))
    except PermissionDenied:
        raise
    except ValidationError as e:
        messages.error(request, " ".join(e.messages))
    return redirect(f"{reverse('collecte:forcages')}?campagne={campagne.pk}")
