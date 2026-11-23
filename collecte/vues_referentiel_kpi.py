"""Référentiel des KPI (administrateur) : liste, fiche KPI, ordre (section 4.5).

Sorti de ``collecte/views.py`` (rangement sans changement de comportement), comme ``vues_coherence.py`` : ce module
importe ses aides depuis ``.views``, jamais l'inverse.
"""
from itertools import groupby

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.forms import CheckboxInput
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.http import urlencode

from parametres import langues as L
from parametres import niveaux as N
from parametres import traductions as TR
from parametres.libelles import libelle
from parametres.models import CategorieDescription, TypeReponse, TypeSaisie
from referentiel.models import KPI, ElementReferentiel, KPIFormule, Referentiel
from referentiel.plans import Plan

from . import demande_depuis as DD
from . import reglages as R
from . import saisie as S
from .models import Campagne
from .views import memoriser_referentiel, referentiel_choisi
from .vues_communes import est_script, exiger_admin


# ---------------------------------------------------------------- référentiel (admin)
@login_required
def referentiel(request):
    """Administration › Référentiels › Catalogue des KPI : tous les KPI une fois chacun (rangés selon le premier référentiel qui
    les contient), ceux d'un référentiel (selon ses thèmes), ou ceux qui ne sont dans aucun ; fiche KPI en panneau. Ranger les
    KPI d'un référentiel se fait dans son contenu (Référentiels › le référentiel › Contenu)."""
    exiger_admin(request)
    hors = request.GET.get("hors") == "1"
    ref = None if hors else (Referentiel.objects.filter(pk=request.GET.get("ref"), actif=True).first() if request.GET.get("ref") else None)
    if ref is not None:
        memoriser_referentiel(request, ref)
    plan = Plan(ref)
    kpis = KPI.objects.prefetch_related("descriptions")
    actifs = request.GET.get("actifs", "1")
    if actifs == "1":
        kpis = kpis.filter(actif=True)
    if ref is not None:
        kpis = kpis.filter(elements__referentiel=ref)
    elif hors:
        kpis = kpis.filter(elements=None)
    nb_sources, nb_utilisations, sources_de, utilise_par = {}, {}, {}, {}
    noms = {k.code: k.nom for k in KPI.objects.all()}
    for c, s_ in KPIFormule.objects.values_list("kpi_calcule_id", "kpi_source_id").distinct():
        nb_sources[c] = nb_sources.get(c, 0) + 1
        nb_utilisations[s_] = nb_utilisations.get(s_, 0) + 1
        sources_de.setdefault(c, []).append(f"{s_} · {noms.get(s_, '?')}")
        utilise_par.setdefault(s_, []).append(f"{c} · {noms.get(c, '?')}")
    kpis = sorted(kpis, key=lambda k: plan.position(k.code, k.ordre))
    autres_langues = L.langues_a_traduire()
    categories = list(CategorieDescription.objects.values_list("code", flat=True))
    for k in kpis:
        k.a_traduire = TR.kpi_a_traduire(k, autres_langues, categories)
        k.nb_sources, k.nb_utilisations = nb_sources.get(k.code, 0), nb_utilisations.get(k.code, 0)
        k.liste_sources = "\n".join(sources_de.get(k.code, []))
        k.liste_utilisations = "\n".join(utilise_par.get(k.code, []))
        # menus « Calculé avec » et « Sert à calculer » : la liste se lit en un clic, chaque KPI ouvre sa fiche
        k.menu_sources = [t.split(" · ", 1) for t in sources_de.get(k.code, [])]
        k.menu_utilisations = [t.split(" · ", 1) for t in utilise_par.get(k.code, [])]
        k.element, k.refs = plan.element(k.code), plan.referentiels_de(k.code)
    # groupes : [(référentiel ou None, titre, nombre de KPI, [(rang du thème, thème, sous-sections)])]. « Tous les KPI » : un
    # groupe par référentiel (en-tête au-dessus de ses thèmes), puis les KPI hors référentiel ; sinon un seul groupe.
    if ref is not None:
        decoupe = [(ref, str(ref), _sections_arbre(plan, ref, kpis))]
    else:
        def referentiel_de(k):
            return k.element.referentiel if k.element else None

        def theme_de(k):
            chemin = plan.chemin(k.element.theme_id) if k.element else []
            return chemin[0].tr("nom") if chemin else (libelle("messages.plans.sans_theme") if k.element else plan.titres(k.code)[0])
        decoupe = [(r, str(r) if r else plan.titres(g[0].code)[0],
                    [(t, [(st, None, list(g2)) for st, g2 in groupby(list(g1), key=lambda k: plan.titres(k.code)[1])])
                     for t, g1 in groupby(g, key=theme_de)])
                   for r, g in ((r, list(g)) for r, g in groupby(kpis, key=referentiel_de))]
    groupes, rang = [], 0
    for r, titre, ss in decoupe:
        groupes.append((r, titre, sum(len(ks) for _, s in ss for _, _, ks in s), [(rang + i, t, s) for i, (t, s) in enumerate(ss)]))
        rang += len(ss)
    par_type = {}
    for k in kpis:
        if k.actif:
            par_type[k.type_saisie_id] = par_type.get(k.type_saisie_id, 0) + 1
    types = list(TypeSaisie.objects.all())
    for t in types:
        t.nb = par_type.get(t.code, 0)
    for k in kpis:  # « + » d'une ligne : ajouter un KPI au-dessus ou en dessous, dans le même thème du même référentiel
        k.url_ajout = (reverse("collecte:referentiel_kpi_nouveau") + "?" + urlencode({"dans": k.element.referentiel_id, "voisin": k.code})
                       if k.element and k.element.referentiel.actif else "")
    compteurs = {"actifs": sum(k.actif for k in kpis),
                 "inactifs": (KPI.objects.filter(elements__referentiel=ref) if ref else KPI.objects).filter(actif=False).count()}
    sommaire = [(r, titre, [(i, t, sum(len(ks) for _, _, ks in ss)) for i, t, ss in themes]) for r, titre, _, themes in groupes]
    return render(request, "collecte/referentiel.html", {
        "groupes": groupes, "entetes_groupes": ref is None and len(groupes) > 1, "nb": len(kpis), "actifs": actifs, "page": "administration", "rubrique": "referentiels", "sous_rubrique": "kpi", "compteurs": compteurs,
        "sommaire": sommaire, "types": types, "ouvrir": request.GET.get("kpi", ""), "ouvrir_traduire": bool(request.GET.get("traduire")), "ref": ref, "hors": hors,
        "nb_hors": KPI.objects.filter(elements=None).count(),
        "langues_a_traduire": [(l, sum(l in k.a_traduire for k in kpis)) for l in L.actives() if l.code in autres_langues],
    })


def _sections_arbre(plan, ref, kpis):
    """Sections d'un référentiel d'après l'arbre de ses thèmes, thèmes vides compris (cibles du glisser-déposer) :
    [(thème du sommet, [(sous-titre, id du thème, KPI)])] ; « Sans thème » en tête s'il y a des KPI sans thème."""
    par_theme = {}
    for k in kpis:
        par_theme.setdefault(k.element.theme_id if k.element else None, []).append(k)
    sections = []
    if par_theme.get(None):
        sections.append((libelle("saisie.panneau.sans_theme"), [("", "", par_theme[None])]))
    for t, prof in plan.arbre(ref):
        chemin = plan.chemin(t.id)
        if prof == 0:
            sections.append((t.tr("nom"), []))
        sections[-1][1].append((" › ".join(x.tr("nom") for x in chemin[1:]), t.id, par_theme.get(t.id, [])))
    return sections


AGREGATIONS = [  # méthode (code stocké), réponses concernées (numérique / texte / toutes) ; libellé et aide : saisie.agregation.<code en minuscules>
    ("Somme", "numerique"), ("Formule", "numerique"), ("Décompte", "texte"), ("Aucune", "toutes"),
]
AGREGATIONS_TEMPS = ["somme", "moyenne", "derniere", "aucune"]  # agrégation dans le temps ; libellé et aide : saisie.agregation_temps.<code>


def agregations():
    """[(méthode, libellé, aide, réponses concernées)] dans la langue de la personne."""
    sans_accent = {"Décompte": "decompte"}
    return [(code, libelle(f"saisie.agregation.{sans_accent.get(code, code.lower())}"),
             libelle(f"saisie.agregation.{sans_accent.get(code, code.lower())}_aide"), pour) for code, pour in AGREGATIONS]


def agregations_temps():
    """[(code, libellé, aide)] de l'agrégation dans le temps, dans la langue de la personne."""
    return [(code, libelle(f"saisie.agregation_temps.{code}"), libelle(f"saisie.agregation_temps.{code}_aide")) for code in AGREGATIONS_TEMPS]


def _fiche_a_jour(request, kpi, form):
    """Vrai si personne n'a modifié la fiche depuis son ouverture ; sinon, message sur le formulaire (rien n'est écrasé)."""
    if kpi.date_maj is None or request.POST.get("version") is None:  # nouveau KPI : rien à écraser
        return True
    actuel = KPI.objects.filter(pk=kpi.pk).first()
    if actuel is None or request.POST["version"] == R.version_kpi(actuel):
        return True
    form.add_error(None, R.message_conflit_kpi(actuel))
    return False


def _voisin(request):
    """Nouveau KPI demandé au-dessus ou en dessous d'un KPI d'un référentiel (« + » d'une ligne du catalogue) :
    {element du voisin, position « avant » ou « apres », kpi voisin}, ou None."""
    d = request.POST if request.method == "POST" else request.GET
    code, dans = d.get("voisin"), d.get("dans")
    if not code or not dans:
        return None
    e = ElementReferentiel.objects.filter(kpi_id=code, referentiel_id=dans, referentiel__actif=True).select_related("kpi", "referentiel").first()
    return {"element": e, "kpi": e.kpi, "position": "avant" if d.get("position") == "avant" else "apres"} if e else None


def _langues_a_traduire(kpi):
    """Langues actives (hors langue de référence) où des textes du KPI manquent : [Langue]."""
    autres = L.langues_a_traduire()
    manquent = TR.kpi_a_traduire(kpi, autres, list(CategorieDescription.objects.values_list("code", flat=True)))
    return [l for l in L.actives() if l.code in manquent]


def _choix_depuis(form, kpi):
    """Nouveau KPI : « L'ajouter aussi aux exercices précédents ? » pour chaque référentiel où il peut être créé et qui a
    des périodes passées : [(code, [(valeur, libellé)], valeur envoyée, visible)] ; seul celui du référentiel choisi est
    visible (les autres s'affichent quand on change de référentiel)."""
    if kpi.pk or "ajout_place" not in form.fields:
        return []
    codes = list(dict.fromkeys(v.split("|", 1)[0] for v, _ in form.fields["ajout_place"].choices if "|" in v))
    choisi = str(form["ajout_place"].value() or "").split("|", 1)[0]
    sortie = []
    for ref in Referentiel.objects.filter(code__in=codes).order_by("ordre", "code"):
        options = DD.choix(ref)
        if len(options) > 1:
            sortie.append((ref.code, options, form.data.get(f"ajout_depuis__{ref.code}", ""), ref.code == choisi))
    return sortie


@login_required
def referentiel_kpi(request, kpi_id=None):
    """Fiche KPI : définition, saisie et calcul (type, formule, granularité, agrégation), interactions, test de formule."""
    exiger_admin(request)
    kpi = get_object_or_404(KPI, pk=kpi_id) if kpi_id else KPI()
    defaut = referentiel_choisi(request) or Referentiel.objects.filter(actif=True).first()  # nouveau KPI : rangé ici
    voisin = _voisin(request) if kpi_id is None else None  # nouveau KPI demandé au-dessus ou en dessous d'un autre
    place = f"{voisin['element'].referentiel_id}|{voisin['element'].theme_id or ''}" if voisin else request.GET.get("place")
    form, test, erreur_test, succes = R.KPIForm(instance=kpi, referentiel_defaut=defaut, place=place), None, "", ""
    proposer_traduction = []
    if request.method == "POST":
        form = R.KPIForm(request.POST, instance=kpi, referentiel_defaut=defaut)
        if request.POST.get("action") == "tester":
            campagne = get_object_or_404(Campagne.objects.select_related("referentiel", "periode"), pk=request.POST.get("campagne_test"))
            essai = KPI(code=kpi.pk or "__essai__",
                        granularite_id=request.POST.get("granularite") or kpi.granularite_id or N.codes()[0],
                        type_reponse_id=request.POST.get("type_reponse") or kpi.type_reponse_id or TypeReponse.objects.first().pk,
                        unite_id=request.POST.get("unite") or None if "unite" in request.POST else kpi.unite_id,
                        decimales=int(request.POST.get("decimales") or kpi.decimales or 0),
                        # la case telle qu'elle est dans la fiche (même lecture qu'une case à cocher de formulaire)
                        na_compte_zero=CheckboxInput().value_from_datadict(request.POST, None, "na_compte_zero"))
            try:
                test = (campagne, R.tester_formule(essai, request.POST.get("formule", ""), campagne))
            except ValidationError as e:
                erreur_test = " ".join(e.messages)
        elif form.is_valid() and _fiche_a_jour(request, kpi, form):
            nouveau = kpi_id is None  # (la validation a déjà posé le code sur l'instance)
            try:
                kpi, recalculs = R.enregistrer_kpi(request.user, form)
            except ValidationError as e:  # unité relue sous verrou : une valeur est arrivée entre-temps (rien n'est enregistré)
                form.add_error(None, e)
                kpi = KPI.objects.get(pk=kpi.pk)
            else:
                if nouveau and voisin:
                    R.inserer_pres(request.user, kpi, voisin["element"], voisin["position"])
                if nouveau:  # textes absents des autres langues actives : proposer de les saisir (rien n'est traduit tout seul)
                    proposer_traduction = _langues_a_traduire(kpi)
                succes = libelle("saisie.referentiel.kpi_enregistre") + (
                    " " + libelle("saisie.referentiel.recalculs", liste=", ".join(recalculs)) if recalculs else "")
                form = R.KPIForm(instance=kpi, referentiel_defaut=defaut)
                if not est_script(request):
                    messages.success(request, succes)
                    return redirect(reverse("collecte:referentiel") + f"?kpi={kpi.pk}" + ("&traduire=1" if proposer_traduction else ""))
    elif kpi.pk and request.GET.get("traduire"):
        proposer_traduction = _langues_a_traduire(kpi)
    if kpi_id is None and not succes:
        kpi = KPI()  # création refusée (ou pas encore envoyée) : la fiche reste celle d'un nouveau KPI, pas d'un KPI au code posé par la validation
    sources, utilisations = R.sources_et_utilisations(kpi) if kpi.pk else ([], [])
    choix_depuis = _choix_depuis(form, kpi)
    for e in form.elements:  # « Demandé depuis » de chaque place (modifiable dans le contenu du référentiel)
        e.depuis_texte = DD.libelle_depuis(e.referentiel, e.demande_depuis)
    ctx = {
        "kpi": kpi, "form": form, "sources": sources, "utilisations": utilisations, "test": test, "erreur_test": erreur_test,
        "succes": succes, "campagnes": Campagne.objects.select_related("referentiel", "periode"),
        "version_kpi": R.version_kpi(KPI.objects.filter(pk=kpi.pk).first() or kpi) if kpi.pk else "",
        "campagne_test": request.POST.get("campagne_test") or str(getattr(S.campagne_courante(), "pk", "")),
        "references": R.references_lisibles(kpi.formule) if kpi.formule else [],
        "types_saisie": TypeSaisie.objects.all(), "agregations": agregations(), "agregations_temps": agregations_temps(),
        "nb_reponses": R.reponses_ouvertes(kpi) if kpi.pk else 0,
        "voisin": None if succes else voisin, "proposer_traduction": proposer_traduction,
        "url_types": reverse("parametres:referentiel") + "?section=types-saisie",
        "choix_depuis": choix_depuis,
    }
    if est_script(request):
        return JsonResponse({"html": render_to_string("collecte/_kpi_fiche.html", ctx, request=request), "ok": bool(succes)})
    return render(request, "collecte/kpi_fiche.html", ctx)


@login_required
def referentiel_kpis_json(request):
    """KPI proposés dans le constructeur de formule (recherche par nom ou ID)."""
    exiger_admin(request)
    return JsonResponse({"kpis": [{"id": k.code, "nom": k.nom, "unite": k.symbole, "type": k.type_saisie.tr("abrege"), "actif": k.actif,
                                   "numerique": k.est_numerique, "niveau": k.granularite_id} for k in KPI.objects.order_by("ordre", "code")]})

