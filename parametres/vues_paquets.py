"""Administration › Référentiels › Gérer les référentiels : bibliothèque et échange (référentiels fournis, export d'un référentiel en
paquet, import d'un paquet avec aperçu et choix, modèle « système existant ») et composition « lego » (deux colonnes :
bibliothèque à gauche, référentiel en construction à droite, glisser un thème entier ou un KPI)."""
import logging
import os
import uuid

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.files.storage import default_storage
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.views.decorators.http import require_POST

from collecte import fichiers as X
from collecte import paquets as P
from collecte.models import Journal
from collecte.reponses_script import reponse_erreur
from collecte.saisie import campagne_courante

from .libelles import libelle
from .rangement import IMPORTS
from .views import exiger_admin_reglages
from espaces import contexte as ESP


CLE = "import_paquet"
MOTIFS_NIVEAU = {"même code": "referentiels.apercu.motif.meme_code", "même nom": "referentiels.apercu.motif.meme_nom",
                 "automatique": "referentiels.apercu.motif.auto", "choisi": "referentiels.apercu.motif.choisi",
                 "choisi : automatique": "referentiels.apercu.motif.choisi_auto"}  # motifs de collecte/paquets/ → libellés
journal = logging.getLogger("reporting.referentiels")
EXTENSIONS = (".xlsx", ".xlsm", ".json")


def _contexte(request, onglet, **autres):
    return {"page": "administration", "rubrique": "referentiels", "sous_rubrique": "referentiels", "onglet_ref": onglet,
            "campagne": campagne_courante(), **autres}


# ------------------------------------------------------------------------------------------- bibliothèque et échange
@login_required
def bibliotheque(request):
    """Ancienne page « Bibliothèque et échange » : la bibliothèque est dans « Ajouter un référentiel », l'export dans la page
    de chaque référentiel (Versions et partage)."""
    exiger_admin_reglages(request)
    return redirect("parametres:referentiel_nouveau")


@login_required
def paquet_exporter(request, code):
    from referentiel.models import Referentiel

    exiger_admin_reglages(request)
    ref = get_object_or_404(Referentiel, code=code)
    p = P.extraire(ref)
    Journal.ecrire(request.user, "export_paquet", ref, "fichier référentiel", "", f"version {ref.version}")
    if request.GET.get("format") == "json":
        rep = HttpResponse(P.vers_json(p), content_type="application/json; charset=utf-8")
        rep["Content-Disposition"] = f'attachment; filename="{P.nom_fichier(p)}.json"'
        return rep
    return P.reponse_excel(p)


@login_required
def paquet_fourni(request, nom_fichier):
    """Référentiel fourni en Excel, pour le lire ou l'adapter avant de l'importer."""
    exiger_admin_reglages(request)
    try:
        f = P.fourni(nom_fichier)
    except P.PaquetInvalide:
        return redirect("parametres:referentiel_nouveau")
    p = f.paquet
    if not p.niveaux:  # modèle sans niveaux : ceux de l'installation, pour les listes déroulantes (colonne Granularité vide)
        p.niveaux = P.niveaux_installation()
    return P.reponse_excel(p)


@login_required
def paquet_modele(request):
    exiger_admin_reglages(request)
    return P.modele_vierge()


# -------------------------------------------------------------------------------------------------- import d'un paquet
def _oublier(request):
    info = request.session.pop(CLE, None)
    if info and info.get("chemin") and default_storage.exists(info["chemin"]):
        default_storage.delete(info["chemin"])


def _paquet(info):
    """Paquet de la session : fichier déposé ou référentiel fourni ; (paquet, fourni)."""
    if info.get("bibliotheque"):
        return P.fourni(info["bibliotheque"]).paquet, True
    with default_storage.open(info["chemin"], "rb") as f:
        f.name = info["chemin"]
        return P.lire(f), False


INATTENDUES = (TypeError, ValueError, AttributeError, KeyError, IndexError, ArithmeticError)  # ArithmeticError : décimal illisible, nombre trop grand pour la base


def _analyse(info, choix):
    """(paquet, fourni, analyse) du fichier de la session. Un fichier modifié à la main ou forgé dont une partie n'a pas
    la forme attendue (texte à la place d'une liste…) donne PaquetInvalide, jamais une erreur 500."""
    try:
        p, fourni = _paquet(info)
        return p, fourni, P.analyser(p, choix, source=info["nom"], fourni=fourni)
    except INATTENDUES as e:
        journal.warning("Framework file %s: unexpected content (%s: %s)", info.get("nom"), e.__class__.__name__, e)
        raise P.PaquetInvalide(libelle("referentiels.paquets.contenu_illisible"))


def _choix(post):
    """Choix de l'aperçu : mode et code du référentiel, niveaux, résolution de chaque KPI, retrait des absents."""
    choix = {c: v for c, v in post.items() if c.startswith(("kpi:", "code:", "niveau:")) and v}
    for c in ("mode", "code"):
        if post.get(c):
            choix[c] = post[c].strip()
    if post.get("retirer_absents") == "on":
        choix["retirer_absents"] = "on"
    return choix


@login_required
def paquet_importer(request):
    exiger_admin_reglages(request)
    if request.method != "POST":
        info = request.session.get(CLE)
        if not info:
            return redirect("parametres:referentiel_nouveau")
        return _apercu(request, info)
    action = request.POST.get("action")
    depuis_mep = _depuis_mise_en_place(request)
    if action == "annuler":
        _oublier(request)
        return redirect(_retour_mep() if depuis_mep else "parametres:referentiel_nouveau")
    if action == "verifier":
        _oublier(request)
        if request.POST.get("bibliotheque"):  # anciens formulaires : l'installation d'un modèle se fait en trois écrans
            try:
                f = P.fourni(request.POST["bibliotheque"])
            except P.PaquetInvalide as e:
                messages.error(request, str(e))
                return redirect("parametres:referentiel_nouveau")
            return redirect("parametres:installer_kpi", f.paquet.code)
        else:
            fichier = request.FILES.get("fichier")
            if not fichier:
                messages.error(request, libelle("referentiels.paquets.choisir_fichier"))
                return redirect("parametres:referentiel_nouveau")
            ext = os.path.splitext(fichier.name)[1].lower()
            if ext not in EXTENSIONS:
                messages.error(request, libelle("referentiels.paquets.formats"))
                return redirect("parametres:referentiel_nouveau")
            if fichier.size > X.TAILLE_MAX:
                messages.error(request, libelle("referentiels.paquets.trop_gros", taille=X.mo(X.TAILLE_MAX)))
                return redirect("parametres:referentiel_nouveau")
            chemin = default_storage.save(f"{IMPORTS}/{uuid.uuid4().hex}{ext}", fichier)
            request.session[CLE] = {"chemin": chemin, "nom": fichier.name, "choix": {},
                                    "depuis_mise_en_place": request.POST.get("depuis") == "mise_en_place"}
        return _apercu(request, request.session[CLE])
    info = request.session.get(CLE)
    if not info or (info.get("chemin") and not default_storage.exists(info["chemin"])):
        messages.error(request, libelle("referentiels.paquets.expire"))
        return redirect("parametres:referentiel_nouveau")
    info["choix"] = _choix(request.POST)
    info["depuis"] = request.POST.get("depuis", "")  # « demandé depuis » des KPI nouveaux (vide : la période en cours)
    request.session[CLE] = info
    if action == "confirmer":
        try:
            p, fourni, a = _analyse(info, info["choix"])
            a.depuis = info["depuis"]
            try:
                res = P.appliquer(request.user, a, info["nom"])  # tout ou rien (transaction)
            except INATTENDUES as e:
                journal.warning("Framework file %s: unexpected content (%s: %s)", info.get("nom"), e.__class__.__name__, e)
                raise P.PaquetInvalide(libelle("referentiels.paquets.contenu_illisible"))
        except P.PaquetInvalide as e:  # tout ou rien : le dire, comme pour le fichier de configuration
            messages.error(request, f"{e} {libelle('referentiels.paquets.rien_enregistre')}")
            return _apercu(request, info)
        _oublier(request)
        if depuis_mep:  # lancé depuis l'assistant : on y revient, avec le résultat en message 
            messages.success(request, libelle("referentiels.mep.import_fait", n=res.elements, referentiel=res.referentiel))
            return redirect(_retour_mep())
        return render(request, "parametres/paquet_apercu.html", _contexte(request, "bibliotheque", resultat=res, analyse=a, info=info))
    return _apercu(request, info)


def _depuis_mise_en_place(request):
    """Import lancé depuis l'étape 5 de l'assistant, encore en cours."""
    from . import mise_en_place as M

    info = request.session.get(CLE) or {}
    return bool(info.get("depuis_mise_en_place") or request.POST.get("depuis") == "mise_en_place") and bool(M.en_cours())


def _retour_mep():
    return reverse("parametres:mise_en_place_etape", args=[5])


def _options_depuis(a):
    """Choix « demandé depuis » des KPI nouveaux d'un référentiel existant (``demande_depuis.choix``) ; aucun pour un
    nouveau référentiel (sans campagne : rien à protéger)."""
    from collecte.demande_depuis import choix

    existant = getattr(a, "existant", None)
    return choix(existant) if existant is not None and getattr(existant, "pk", None) else []


def _apercu(request, info):
    try:
        p, fourni, a = _analyse(info, info.get("choix"))
    except P.PaquetInvalide as e:
        _oublier(request)
        messages.error(request, str(e))
        return redirect("parametres:referentiel_nouveau")
    ordre = {"conflit": 0, "rejet": 1, "modifie": 2, "nouveau": 3, "inchange": 4}
    lignes = sorted(a.kpis, key=lambda l: ordre[l.statut])
    genres = ["niveau", "unite", "type_saisie", "type_reponse", "categorie", "champ"]
    reglages = [(libelle(f"referentiels.apercu.genre.{g}"), [r for r in a.reglages if r.genre == g]) for g in genres[1:]]
    niveaux = [(n, local, motif, P.texte_affiche(n.get("nom"), p.langue_reference) or n["code"])
               for n, local, motif, utilise in a.niveaux if utilise]  # motif : « même code », « même nom », « automatique », « choisi », « choisi : automatique »
    return render(request, "parametres/paquet_apercu.html", _contexte(
        request, "bibliotheque", analyse=a, info=info, lignes=lignes, reglages=[(lib, rs) for lib, rs in reglages if rs],
        niveaux_utilises=[(n, local, libelle(MOTIFS_NIVEAU[motif]), nom) for n, local, motif, nom in niveaux], niveaux_auto=[nom for n, local, motif, nom in niveaux if not local],
        niveaux_repris=", ".join(nom for n, local, motif, nom in niveaux),
        langues_creees_texte=", ".join(lib for code, lib in a.langues_creees),
        themes_absents_texte=", ".join(str(t) for t in a.themes_absents),
        niveaux_choisis=any(motif.startswith("choisi") for _, _, motif, _ in niveaux),
        inchanges=[l for l in a.kpis if l.statut == "inchange"], nouveaux=[l for l in a.kpis if l.statut == "nouveau"],
        options_depuis=_options_depuis(a), depuis_choisi=info.get("depuis", ""),
        lignes_a_voir=[l for l in a.kpis if l.statut in ("conflit", "rejet", "modifie")]))


# -------------------------------------------------------------------------------------------------- composition « lego »
def _arbre_installe(ref, avec_kpi=True):
    """[(thème, profondeur, [éléments])] d'un référentiel installé, dans l'ordre de l'arbre ; éléments sans thème en tête."""
    from referentiel.models import ElementReferentiel

    themes = P.themes_ordonnes(ref)
    profondeur = {}
    for t in themes:
        profondeur[t.pk] = profondeur.get(t.parent_id, -1) + 1
    elements = {}
    if avec_kpi:
        for e in ElementReferentiel.objects.filter(referentiel=ref).select_related("kpi", "kpi__type_saisie").order_by("ordre", "kpi_id"):
            elements.setdefault(e.theme_id, []).append(e)
    return [(t, profondeur[t.pk], elements.get(t.pk, [])) for t in themes], elements.get(None, [])


def _arbre_fourni(p):
    """Même forme pour un référentiel fourni (paquet) : [(thème (dict), profondeur, [KPI (dict)])]."""
    lg = p.langue_reference
    profondeur, sortie = {}, []
    par_theme = {}
    for k in p.kpis:
        if k.get("element") is not None:
            par_theme.setdefault(k["element"]["theme"], []).append(k)
    for t in p.themes:
        profondeur[t["code"]] = profondeur.get(t["parent"], -1) + 1
        kpis = [{"code": k["code"], "nom": P.texte_affiche(k["libelle"], lg),
                 "calcule": k["type_saisie"] == "Calculé"} for k in sorted(par_theme.get(t["code"], []), key=lambda k: k["element"]["ordre"] or 0)]
        sortie.append(({"code": t["code"], "nom": P.texte_affiche(t["nom"], lg)}, profondeur[t["code"]], kpis))
    return sortie


def _cible(request, code):
    from referentiel.models import Referentiel

    return Referentiel.objects.filter(code=code).first() if code else None


@login_required
def composer(request):
    """Ancienne page « Composer » : la composition se fait dans le contenu de chaque référentiel."""
    exiger_admin_reglages(request)
    code = request.GET.get("ref")
    if code and _cible(request, code):
        return redirect(reverse("parametres:referentiel_contenu", args=[code]) + "?ajouter=1")
    return redirect("parametres:referentiels")


def _bibliotheque_compo(cible):
    """Sources du tiroir « Ajouter depuis… » : autres référentiels, modèles fournis, KPI du catalogue hors référentiel."""
    from referentiel.models import KPI, Referentiel

    sources = []
    for r in Referentiel.objects.exclude(code=cible.code).order_by("ordre", "code"):
        themes, sans = _arbre_installe(r)
        sources.append((r, themes, sans))
    fournis = [(f, _arbre_fourni(f.paquet)) for f in P.bibliotheque()]
    hors = list(KPI.objects.filter(elements=None).order_by("ordre", "code"))
    return {"sources": sources, "fournis": fournis, "hors": hors}


def _ranger_avant(cible, theme, code, avant):
    """Place le KPI ``code`` juste avant ``avant`` dans ce thème du référentiel (à la fin si ``avant`` n'y est pas)."""
    from referentiel.composition import ordonner_elements
    from referentiel.models import ElementReferentiel

    codes = list(ElementReferentiel.objects.filter(referentiel=cible, theme=theme).exclude(kpi_id=code)
                 .order_by("ordre", "kpi_id").values_list("kpi_id", flat=True))
    i = codes.index(avant) if avant in codes else len(codes)
    ordonner_elements(cible, theme, codes[:i] + [code] + codes[i:])


def _deposer(user, cible, theme, src, avant=None):
    """Dépose dans ``cible`` (sous ``theme``, ou au premier niveau) un thème ou un KPI d'un autre référentiel, d'un modèle de
    la bibliothèque ou du catalogue, ou y range un de ses KPI (avant ``avant``). Renvoie le message."""
    from referentiel.composition import copier_theme, placer
    from referentiel.models import KPI, ElementReferentiel, Theme

    genre = src.get("type")
    if genre == "retirer":
        e = ElementReferentiel.objects.filter(referentiel=cible, kpi_id=src.get("code")).first()
        if e is None:
            raise ValidationError(libelle("referentiels.paquets.kpi_absent"))
        Journal.ecrire(user, "reglage_kpi", e.kpi, "Référentiel", f"{cible}", "(retiré)")
        e.delete()
        return libelle("referentiels.paquets.kpi_retire", code=src["code"], referentiel=str(cible))
    if src.get("bib"):
        f = P.fourni(src["bib"])
        ajoutes, presents, crees, rejets = P.composer_depuis_paquet(
            user, f.paquet, cible, theme, code_theme=src.get("id") if genre == "theme" else None,
            code_kpi=src.get("code") if genre == "kpi" else None)
        if genre == "kpi" and avant is not None:  # KPI d'un modèle déposé à un endroit précis
            _ranger_avant(cible, theme, src.get("code"), avant)
        return (libelle("referentiels.paquets.depuis_modele", n=ajoutes, modele=f.paquet.nom())
                + (", " + libelle("referentiels.paquets.crees_catalogue", n=crees) if crees else "")
                + (", " + libelle("referentiels.paquets.deja_presents", n=presents) if presents else "")
                + (". " + libelle("referentiels.paquets.rejetes", liste=" ; ".join(rejets)) if rejets else "") + ".")
    if genre == "theme":
        source = get_object_or_404(Theme, pk=src.get("id"), referentiel_id=src.get("ref"))
        try:
            nouveau, ajoutes, presents = copier_theme(source, cible, theme)
        except ValueError as e:
            raise ValidationError(str(e))
        Journal.ecrire(user, "reglage_referentiels", cible, "composition", "", f"thème « {source} » repris de {source.referentiel_id}")
        return (libelle("referentiels.paquets.theme_ajoute", theme=str(nouveau), n=ajoutes)
                + (", " + libelle("referentiels.paquets.deja_presents", n=presents) if presents else "")
                + ". " + libelle("referentiels.paquets.pas_recopies"))
    if genre in ("kpi", "element"):
        kpi = get_object_or_404(KPI, pk=src.get("code"))
        e, cree = placer(kpi, cible, theme)
        if cree:
            Journal.ecrire(user, "reglage_kpi", kpi, "Référentiel", "", f"{cible}" + (f" › {theme}" if theme else ""))
        if avant is not None:
            _ranger_avant(cible, theme, kpi.code, avant)
        place = str(theme) if theme else libelle("referentiels.contenu.lot.sans_theme")
        return libelle("referentiels.paquets.kpi_ajoute_dans" if cree else "referentiels.paquets.kpi_range_dans", code=kpi.code, theme=place)
    raise ValidationError(libelle("referentiels.paquets.glisser"))


# -------------------------------------------------------------------------------------------------- éditeur « Contenu »
def _noeuds(ref):
    """Arbre du référentiel pour l'éditeur : ([nœuds du premier niveau], [éléments sans thème]) ; nœud :
    {theme, prof, elements, enfants, nb (KPI du thème et de ses sous-thèmes)}."""
    from referentiel.models import ElementReferentiel

    from collecte.demande_depuis import choix_refuses, libelle_depuis, phrase_depuis
    from collecte.models import Campagne

    themes = P.themes_ordonnes(ref)
    elements = {}
    periodes = {c.periode.debut: c.periode for c in Campagne.objects.filter(referentiel=ref).select_related("periode")}
    for e in (ElementReferentiel.objects.filter(referentiel=ref)
              .select_related("kpi", "kpi__type_saisie", "kpi__unite", "kpi__type_reponse", "kpi__granularite")
              .order_by("ordre", "kpi_id")):
        e.depuis_texte = libelle_depuis(ref, e.demande_depuis, periodes)  # colonne « Demandé depuis »
        e.depuis_phrase = phrase_depuis(ref, e.demande_depuis, periodes)
        elements.setdefault(e.theme_id, []).append(e)
    tous = [e for liste in elements.values() for e in liste]
    refus = choix_refuses(ref, tous)
    for e in tous:
        e.depuis_refus = " ".join(v or "_" for v in refus[e.kpi_id]) or "-"  # choix impossibles : grisés dans la barre d'actions
    noeuds = {t.pk: {"theme": t, "elements": elements.get(t.pk, []), "enfants": []} for t in themes}
    racine = []
    for t in themes:
        (noeuds[t.parent_id]["enfants"] if t.parent_id in noeuds else racine).append(noeuds[t.pk])

    def compter(n, prof):
        n["prof"] = prof
        n["nb"] = len(n["elements"]) + sum(compter(x, prof + 1) for x in n["enfants"])
        return n["nb"]

    for n in racine:
        compter(n, 0)
    return racine, elements.get(None, [])


def _contexte_contenu(ref):
    from collecte.reglages import options_themes

    racine, sans = _noeuds(ref)
    presents = " ".join(ref.elements.values_list("kpi_id", flat=True))
    from . import niveaux as N

    from collecte.demande_depuis import choix

    return {"cible": ref, "noeuds": racine, "sans_theme": sans, "presents": presents,
            "options_themes": options_themes(P.themes_ordonnes(ref)), "options_niveaux": sorted(N.tous(), key=lambda n: n.rang),
            "options_depuis": choix(ref, tous=True)}


def _html_contenu(request, ref):
    return render_to_string("parametres/_contenu_arbre.html", _contexte_contenu(ref), request=request)


@login_required
def contenu(request, code):
    """Contenu d'un référentiel : ses thèmes et ses KPI (renommer, ranger, ajouter, retirer, actions en lot) et le tiroir
    « Ajouter depuis… » (autres référentiels, modèles de la bibliothèque, catalogue)."""
    from referentiel.models import Referentiel

    from .vues_referentiels import contexte_referentiel

    exiger_admin_reglages(request)
    cible = get_object_or_404(Referentiel, code=code)
    from . import mise_en_place as M
    from .vues_referentiels import CLE_RETOUR_MEP

    retour_mep = (reverse("parametres:mise_en_place_etape", args=[5])
                  if request.session.get(CLE_RETOUR_MEP) == cible.code and M.en_cours() else "")
    ctx = contexte_referentiel(request, cible, "contenu", **_bibliotheque_compo(cible), **_contexte_contenu(cible),
                        tiroir_ouvert=request.GET.get("ajouter") == "1", retour_mep=retour_mep)
    return render(request, "parametres/referentiel_contenu.html", ctx)


@login_required
@require_POST
def contenu_action(request, code):
    """Actions de l'éditeur (JSON) : deposer, theme_ajouter, theme_renommer, theme_deplacer, theme_monter, theme_descendre,
    theme_supprimer, lot (deplacer, obligatoire, facultatif, retirer). Renvoie {ok, message, html}."""
    from referentiel.models import Referentiel

    from . import vues_referentiels as VR

    exiger_admin_reglages(request)
    cible = get_object_or_404(Referentiel, code=code)
    from collecte.vues_communes import corps_json

    d = corps_json(request)
    action = d.get("action")

    def theme_de(cle):
        v = d.get(cle)
        return VR.theme_du_referentiel(cible, v) if str(v or "").isdecimal() else None

    from collecte.calcul import si_frequences_changent

    try:
        with ESP.atomic(), si_frequences_changent():
            if action == "deposer":
                message = _deposer(request.user, cible, theme_de("theme"), d.get("source") or {}, d.get("avant"))
            elif action == "theme_ajouter":
                message = VR.ajouter_theme(request.user, cible, d.get("nom", ""), theme_de("parent"))
            elif action == "theme_renommer":
                message = VR.renommer_theme(request.user, theme_de("id"), d.get("nom", ""))
            elif action == "theme_deplacer":
                message = VR.deplacer_theme(request.user, theme_de("id"), theme_de("parent"), theme_de("avant"))
            elif action in ("theme_monter", "theme_descendre"):
                message = VR.decaler_theme(request.user, theme_de("id"), -1 if action == "theme_monter" else 1)
            elif action == "theme_supprimer":
                message = VR.supprimer_theme(request.user, theme_de("id"))
            elif action == "lot":
                message = VR.lot(request.user, cible, d.get("operation"), d.get("codes") or [], theme_de("theme"), niveau=d.get("niveau"),
                                 confirmer=bool(d.get("confirmer")), depuis=d.get("depuis"))
            else:
                raise ValidationError(libelle("referentiels.vues.action_inconnue"))
    except VR.Confirmation as e:  # rien n'est écrit : la question est reposée, puis l'action renvoyée avec « confirmer »
        return JsonResponse({"ok": False, "confirmer": str(e)})
    except (ValidationError, P.PaquetInvalide) as e:
        return reponse_erreur(" ".join(getattr(e, "messages", [str(e)])))
    return JsonResponse({"ok": True, "message": message, "html": _html_contenu(request, cible)})
