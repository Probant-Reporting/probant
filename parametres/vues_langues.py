"""Administration › Paramètres › Langues : langues des contenus (ajouter, activer, réordonner, langue par défaut,
supprimer si inutilisée) et page « Traductions » (ce qui reste à traduire dans une langue, à remplir sur place)."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse

from collecte.models import Journal
from collecte.saisie import campagne_courante

from . import ia as IA
from . import langues as L
from . import traductions as TR
from . import traductions_fichier as TF
from .libelles import libelle
from .models import Instance, Langue, valider_code_langue
from .views import exiger_admin_reglages
from espaces import contexte as ESP

LIMITE = 150  # éléments affichés à la fois dans la page Traductions


def _journal(request, obj, champ, avant, apres):
    Journal.ecrire(request.user, "reglage_langues", obj, champ, avant, apres)


@login_required
def langues(request):
    exiger_admin_reglages(request)
    erreur = ""
    if request.method == "POST":
        with ESP.atomic():
            erreur = action_langues(request)
        if not erreur:
            return redirect("parametres:langues")
    ref, defaut = L.reference(), L.defaut()
    utilisees = L.langues_utilisees()
    from referentiel.models import Utilisateur

    preferences = {}
    for code in Utilisateur.objects.exclude(langue="").values_list("langue", flat=True):
        preferences[code] = preferences.get(code, 0) + 1
    lignes = []
    for lg in Langue.objects.all():
        sections, (faits, total) = TR.completude(lg.code) if lg.code != ref else ({}, (0, 0))
        lignes.append({"langue": lg, "reference": lg.code == ref, "defaut": lg.code == defaut, "comptes": preferences.get(lg.code, 0),
                       "faits": faits, "total": total, "reste": total - faits, "pct": int(100 * faits / total) if total else 100,
                       "supprimable": lg.code not in (ref, defaut) and lg.code not in utilisees})
    return render(request, "parametres/langues.html", {
        "page": "administration", "rubrique": "parametres", "sous_rubrique": "langues", "campagne": campagne_courante(),
        "lignes": lignes, "reference": L.libelle(ref), "a_traduire": [L.libelle(c) for c in L.langues_a_traduire()], "erreur": erreur, "post": request.POST if erreur else {},
    })


def action_langues(request):
    P = request.POST
    action = P.get("action", "")
    for cle in ("monter", "descendre", "supprimer"):
        if cle in P:
            action = cle
    ref = L.reference()
    toutes = list(Langue.objects.all())
    if action == "ajouter":
        code, nom_langue = P.get("code", "").strip(), P.get("libelle", "").strip()[:40]
        try:
            valider_code_langue(code)
        except ValidationError as e:
            return " ".join(e.messages)
        if Langue.objects.filter(code__iexact=code).exists():
            return libelle("admin.langues.erreur.existe", code=code)
        lg = Langue.objects.create(code=code, libelle=nom_langue or code, ordre=len(toutes) + 1, active=True)
        _journal(request, lg, "langue", "", f"{lg.libelle} ({code}) ajoutée")
        messages.success(request, libelle("admin.langues.ajoutee", nom=lg.libelle))
        return ""
    if action == "enregistrer":
        defaut = P.get("defaut", L.defaut())
        par_code = {lg.code: lg for lg in toutes}
        for lg in toutes:
            avant = (lg.libelle, lg.active)
            lg.libelle = (P.get(f"libelle__{lg.code}", lg.libelle) or lg.code).strip()[:40]
            lg.active = f"active__{lg.code}" in P or lg.code in (ref, defaut)
            if (lg.libelle, lg.active) != avant:
                lg.save()
                if lg.libelle != avant[0]:
                    _journal(request, lg, "libellé", avant[0], lg.libelle)
                if lg.active != avant[1]:
                    _journal(request, lg, "active", "oui" if avant[1] else "non", "oui" if lg.active else "non")
        if defaut in par_code and defaut != L.defaut():
            i = Instance.courante()
            _journal(request, i, "langue par défaut", L.libelle(i.langue), par_code[defaut].libelle)
            i.langue = defaut
            i.save(update_fields=["langue"])
        messages.success(request, libelle("admin.langues.enregistrees"))
        return ""
    code = P.get(action, "")
    i = next((n for n, lg in enumerate(toutes) if lg.code == code), None)
    if i is None:
        return ""
    if action == "supprimer":
        if code in (ref, L.defaut()) or code in L.langues_utilisees():
            return libelle("admin.langues.erreur.utilisee", nom=toutes[i].libelle)
        _journal(request, toutes[i], "langue", toutes[i].libelle, "(supprimée)")
        toutes[i].delete()
        messages.success(request, libelle("admin.langues.supprimee", nom=toutes[i].libelle))
        return ""
    j = i - 1 if action == "monter" else i + 1
    if 0 <= j < len(toutes):
        toutes[i], toutes[j] = toutes[j], toutes[i]
        for rang, lg in enumerate(toutes, start=1):
            if lg.ordre != rang:
                Langue.objects.filter(pk=lg.pk).update(ordre=rang)
    return ""


@login_required
def traductions(request, code):
    """Ce qui reste à traduire dans une langue, section par section, à remplir sur place (par lots)."""
    exiger_admin_reglages(request)
    lg = Langue.objects.filter(code=code).first()
    if lg is None:
        raise Http404
    if code == L.reference():
        messages.info(request, libelle("admin.traductions.reference"))
        return redirect("parametres:langues")
    section = request.GET.get("section") if request.GET.get("section") in dict(TR.SECTIONS) else None
    tout = request.GET.get("tout") == "1"
    if request.method == "POST":
        donnees = {k: v for k, v in request.POST.items() if "|" in k}
        with ESP.atomic():
            n = TR.enregistrer(code, donnees)
            if n:
                Journal.ecrire(request.user, "traduction", lg, dict(TR.SECTIONS).get(section, "traductions"), "", f"{n} texte(s) en {lg.libelle}")
        messages.success(request, libelle("admin.traductions.enregistrees", n=n) if n else libelle("admin.traductions.aucun_changement"))
        return redirect(reverse("parametres:traductions", args=[code]) + f"?section={section or ''}{'&tout=1' if tout else ''}")
    comptes, (faits, total) = TR.completude(code)
    if section is None:  # première section où il reste quelque chose à traduire
        section = next((s for s, _ in TR.SECTIONS if comptes.get(s, (0, 0))[0] < comptes.get(s, (0, 0))[1]), TR.SECTIONS[0][0])
    elements = TR.elements(code, section, tout)
    return render(request, "parametres/traductions.html", {
        "page": "administration", "rubrique": "parametres", "sous_rubrique": "langues", "campagne": campagne_courante(),
        "langue": lg, "section": section, "tout": tout, "elements": elements[:LIMITE], "nb": len(elements), "limite": LIMITE,
        "sections": [(s, titre, comptes.get(s, (0, 0))) for s, titre in TR.titres_sections()], "faits": faits, "total": total,
        "reference": L.libelle(L.reference()), "reste": total - faits,
        "langues_traduction": [x for x in Langue.objects.all() if x.code != L.reference()],
        "ia_traductions": IA.bouton_visible("traduction") and any(not e.actuel and not e.facultatif for e in elements[:LIMITE]),
    })



def _codes(code):
    """Langues visées : une langue (page Traductions) ou toutes les langues à traduire (« toutes », page Langues)."""
    if code == "toutes":
        codes = L.langues_a_traduire()
    elif Langue.objects.filter(code=code).exists() and code != L.reference():
        codes = [code]
    else:
        raise Http404
    if not codes:
        raise Http404
    return codes


def _retour(code):
    return redirect("parametres:langues") if code == "toutes" else redirect("parametres:traductions", code=code)


@login_required
def traductions_export(request, code):
    """Fichier des textes à traduire (ou de tous), pour une langue ou toutes : Excel ou CSV."""
    exiger_admin_reglages(request)
    return TF.exporter(_codes(code), tout=request.GET.get("tout") == "1", format="csv" if request.GET.get("format") == "csv" else "xlsx")


@login_required
def traductions_import(request, code):
    """Import d'un fichier de traductions : aperçu des changements par langue, puis enregistrement après confirmation."""
    exiger_admin_reglages(request)
    codes = _codes(code)
    if request.method != "POST":
        raise Http404
    cle_session = f"traductions_import_{code}"
    if request.POST.get("action") == "appliquer":
        en_attente = request.session.pop(cle_session, None)
        if not en_attente:
            messages.error(request, libelle("admin.traductions.apercu_expire"))
            return _retour(code)
        bilan = []
        with ESP.atomic():
            for lg_code, donnees in en_attente.items():
                n = TR.enregistrer(lg_code, donnees)
                if n:
                    lg = Langue.objects.get(code=lg_code)
                    Journal.ecrire(request.user, "traduction", lg, "import de fichier", "", f"{n} texte(s) en {lg.libelle}")
                    bilan.append(libelle("admin.traductions.bilan_langue", n=n, nom_langue=lg.libelle))
        messages.success(request, libelle("admin.traductions.importees", bilan=", ".join(bilan)) if bilan else libelle("admin.traductions.aucun_changement"))
        return _retour(code)
    fichier = request.FILES.get("fichier")
    if fichier is None:
        messages.error(request, libelle("admin.traductions.choisir_fichier"))
        return _retour(code)
    analyses, erreur = TF.analyser(fichier, codes, seule=codes[0] if code != "toutes" else None)
    if erreur:
        messages.error(request, erreur)
        return _retour(code)
    request.session[cle_session] = {a.code: a.donnees for a in analyses if a.changements}
    total = sum(len(a.changements) for a in analyses)
    return render(request, "parametres/traductions_import.html", {
        "page": "administration", "rubrique": "parametres", "sous_rubrique": "langues", "campagne": campagne_courante(),
        "code": code, "analyses": analyses, "total": total, "nom_fichier": fichier.name, "limite": LIMITE,
        "langue": Langue.objects.get(code=code) if code != "toutes" else None,
    })
