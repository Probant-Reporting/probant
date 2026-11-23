"""Onglet Visualisation (v2) : une page faite de vues (``collecte/vues_visu.py`` pour la page et les points d'accès
JSON, ``collecte/visuels/`` pour les données).

- ``/visualisation/`` ouvre la vue par défaut de la personne : sa vue par défaut, sinon la vue d'accueil de son rôle
  (choisie par l'administrateur), sinon la première vue de ses onglets, sinon la « Vue de départ » (proposée, non enregistrée).
- Vues automatiques, non enregistrées (adresses conservées) : ``/visualisation/kpi/<code>/`` (chiffre clé, courbe,
  comparaison des organisations et anneau, seulement les formes compatibles, puis la définition et le mode de calcul) et
  ``/visualisation/theme/<id>/`` (4 chiffres clés, puis le tableau du thème).
- Anciennes adresses des tableaux (convertis en vues par la migration 0023) : redirigées vers leur vue.
"""
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.decorators.http import require_GET

from referentiel.models import KPI, Theme
from referentiel.plans import Plan

from . import visualisation as V
from . import visuels as VS
from . import vues_visu as VV
from .models import AccueilVisu, TableauVisu, VueVisu


def vue_ouverte(utilisateur):
    """Vue ouverte sur /visualisation/ : vue par défaut de la personne, vue d'accueil de son rôle (choisie par l'administrateur), première de ses onglets ; None : la Vue de départ."""
    pref = VV.preference(utilisateur)
    visibles = VueVisu.visibles(utilisateur)
    if pref and pref.vue_defaut_id:
        v = visibles.filter(pk=pref.vue_defaut_id).first()
        if v is not None:
            return v
    v = AccueilVisu.vue_de(utilisateur)
    if v is not None:
        return v
    vues = VV.vues_ordonnees(utilisateur, pref)
    return vues[0] if vues else None


@login_required
@require_GET
def accueil(request):
    vue = vue_ouverte(request.user)
    if vue is not None:
        return VV.rendre_page(request, vue)
    return VV.rendre_page(request, auto=VV.vue_de_depart(request.user, VV.campagne_choisie(request)))


def _visuel(id_, forme, kpis=(), largeur=None, **autres):
    return {"id": id_, "type": forme, "titre": "", "kpis": list(kpis), "source": "", "axe": "", "series": "",
            "largeur": largeur or VS.TYPES[forme]["largeur"], "hauteur": "m", "filtres": {}, "options": {}, **autres}


@login_required
@require_GET
def kpi(request, code):
    k = get_object_or_404(KPI.objects.select_related("granularite"), pk=code, actif=True)
    source = V.Source(request.user, [k.code])
    if not any(source.voit(k.code, o.id) for o in source.organisations()):
        raise Http404("KPI hors de votre périmètre.")
    formes = ["chiffre", "courbe", "organisations", "anneau"] if k.est_numerique else ["chiffre"] if k.est_texte \
        else ["chiffre", "anneau", "organisations"]  # réponse rédigée : une carte qui dit qu'elle n'a pas de graphique
    visuels = [_visuel(f"k{i + 1}", f, [k.code], largeur=3 if f == "chiffre" else (9 if f == "courbe" else 6))
               for i, f in enumerate(formes)]
    from parametres.models import CategorieDescription

    categories = CategorieDescription.objects.all() if request.user.voit_tout else CategorieDescription.objects.filter(affichee=True)
    definition = [(c, t) for c in categories if (t := k.texte_description(c.code))]
    plan = Plan()
    return VV.rendre_page(request, auto={"nom": k.nom, "genre": "kpi", "filtres": {}, "visuels": visuels, "filtrer": True,
                                         "description": " › ".join(x for x in plan.titres(k.code) if x)},
                          extra={"kpi_defini": k, "definition": definition})


@login_required
@require_GET
def theme(request, pk):
    t = get_object_or_404(Theme.objects.select_related("referentiel"), pk=pk, referentiel__actif=True)
    codes = VS.codes_du_plan(Plan(t.referentiel), [t])
    visibles = VS.codes_visibles(request.user)
    kpis = {x.code: x for x in KPI.objects.filter(code__in=[c for c in codes if c in visibles])}
    chiffres = [c for c in codes if c in kpis and kpis[c].est_numerique][:4]
    visuels = [_visuel(f"c{i + 1}", "chiffre", [c]) for i, c in enumerate(chiffres)]
    visuels.append(_visuel("t", "tableau", source=f"theme:{t.pk}"))
    return VV.rendre_page(request, auto={"nom": t.tr("nom"), "genre": "theme", "filtres": {"referentiel": t.referentiel_id},
                                         "visuels": visuels, "description": str(t.referentiel)})


# ---------------------------------------------------------------- anciennes adresses des tableaux
def _vue_du_tableau(request, pk):
    get_object_or_404(TableauVisu.visibles(request.user), pk=pk)  # un tableau inconnu ou non visible : 404, comme avant
    return get_object_or_404(VueVisu.visibles(request.user), ancien_tableau=pk)


def _avec_filtres(request, url, **ajouts):
    q = request.GET.copy()
    for cle, valeur in ajouts.items():
        q[cle] = valeur
    return f"{url}?{q.urlencode()}" if q else url


@login_required
def tableau(request, pk):
    return redirect(_avec_filtres(request, reverse("collecte:visu_vue", args=[_vue_du_tableau(request, pk).pk])))


@login_required
def tableau_modifier(request, pk):
    return redirect(_avec_filtres(request, reverse("collecte:visu_vue", args=[_vue_du_tableau(request, pk).pk]), modifier="1"))


@login_required
def tableau_nouveau(request):
    theme_id = request.GET.get("theme", "")
    if theme_id.isdecimal() and Theme.objects.filter(pk=theme_id, referentiel__actif=True).exists():
        return redirect(reverse("collecte:visu_theme", args=[int(theme_id)]) + "?modifier=1")
    return redirect("collecte:visu_vue_nouvelle")
