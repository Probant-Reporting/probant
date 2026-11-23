"""Ajouter un référentiel : la page aux trois portes (installer depuis la bibliothèque, composer à partir de KPI
existants, importer un fichier) et l'installation d'un modèle de la bibliothèque en trois écrans : 1 choisir le modèle,
2 cocher les KPI, 3 résumé et installation. Les modèles n'ont pas de niveaux : l'outil rattache chaque KPI à l'arbre
(collecte/paquets/analyse_kpis.py, _niveaux_automatiques) et l'écran 3 dit la règle en une phrase. L'état circule dans la session
(``installer_modele``) ; s'il manque, on revient à l'écran 2 tout coché."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from collecte import fichiers as X
from collecte import paquets as P
from referentiel import formule as FO
from collecte.demande_depuis import choix as choix_depuis
from collecte.saisie import campagne_courante

from . import niveaux as N
from .libelles import libelle
from .views import exiger_admin_reglages

CLE = "installer_modele"
ETAPES = [1, 2, 3]  # Modèle, KPI, Installer (titres : referentiels.installer.etape.<n>)


def _contexte(**autres):
    return {"page": "administration", "rubrique": "referentiels", "sous_rubrique": "referentiels", "campagne": campagne_courante(),
            "etapes_installation_liste": [(n, libelle(f"referentiels.installer.etape.{n}")) for n in ETAPES], **autres}


def _monnaie(p):
    """Phrase des écrans 2 et 3 sur la monnaie des montants d'un modèle (monnaie de référence de l'espace), seulement
    s'il a des KPI de montant."""
    from . import monnaies as MO

    return {"montants": MO.a_des_montants(p), "monnaie_affichee": MO.affichee(getattr(p, "monnaie", None) or MO.reference())}


def fournis_decrits():
    """Modèles de la bibliothèque, avec leurs nombres (KPI, thèmes, calculés) et leur état dans l'installation."""
    from referentiel.models import ElementReferentiel

    ordres = P.ordre_modeles()  # ordre des définitions (norme VS, transparence, ESRS 2, E1 à E5, S1 à S4, G1)
    fournis = sorted(P.bibliotheque(), key=lambda f: (ordres.get(f.paquet.code, 10 ** 6), f.nom_fichier))
    for f in fournis:
        p = f.paquet
        f.code = p.code
        presents = set(ElementReferentiel.objects.filter(referentiel=f.installe).values_list("kpi_id", flat=True)) if f.installe else set()
        f.complet = bool(f.installe) and {k["code"] for k in p.kpis} <= presents  # rien à ajouter
        f.nb_kpi = len(p.kpis)
        f.nb_themes = len(p.themes)
        f.nb_calcules = sum(1 for k in p.kpis if k.get("type_saisie") == "Calculé")
        f.description_courte = p.description
    return fournis


def bibliotheque_par_thematique():
    """Page Référentiels : les modèles de la bibliothèque rangés par thématique, avec ce que l'installation
    possède déjà (« 10 KPI déjà chez vous » : codes du modèle présents dans le catalogue). [(thématique, [modèle])],
    dans l'ordre des thématiques puis des noms ; un modèle sans thématique va dans « Autres »."""
    from referentiel.models import KPI

    catalogue = set(KPI.objects.values_list("code", flat=True))
    groupes = {}
    for f in fournis_decrits():
        f.nb_deja = 0 if f.installe else sum(1 for k in f.paquet.kpis if k["code"] in catalogue)
        f.thematique = f.paquet.thematique or libelle("referentiels.bibliotheque.autres")
        # la recherche trouve aussi un ensemble par le nom d'un de ses KPI (« fioul », « effectif »)
        noms_kpi = [P.texte_affiche(k.get("libelle"), f.paquet.langue_reference) or "" for k in f.paquet.kpis]
        f.texte_recherche = " ".join([f.paquet.nom(), f.description_courte or "", f.thematique, *noms_kpi]).lower()
        groupes.setdefault(f.thematique, []).append(f)
    autres = libelle("referentiels.bibliotheque.autres")
    return [(t, sorted(fs, key=lambda f: (P.ordre_modeles().get(f.paquet.code, 10 ** 6), f.paquet.nom().lower()))) for t, fs in sorted(groupes.items(), key=lambda g: (g[0] == autres, g[0].lower()))]


def contexte_portes():
    """Ce qu'il faut aux trois portes (page « Ajouter un référentiel », état vide de Référentiels, assistant)."""
    from referentiel.models import Referentiel

    from . import couleurs as CO
    from .vues_referentiels import comparaisons_choix, frequences_choix, mois_choix

    n = Referentiel.objects.count()
    return {"fournis": fournis_decrits(), "frequences": frequences_choix(),
            "mois": mois_choix(), "comparaisons": comparaisons_choix(),
            "existants": n, "couleur_suivante": CO.COULEURS_NIVEAUX[n % len(CO.COULEURS_NIVEAUX)], "post": {}}


def modele_fourni(code):
    for f in P.bibliotheque():
        if f.paquet.code == code:
            f.code = code
            return f
    raise Http404(libelle("referentiels.installer.modele_introuvable"))


def _etat(request, code):
    etat = request.session.get(CLE) or {}
    return etat if etat.get("code") == code else None


def _depuis_mise_en_place(request):
    from . import mise_en_place as M

    return request.GET.get("depuis") == "mise_en_place" and bool(M.en_cours())


def _reprise_mise_en_place(request):
    """Parcours commencé depuis l'assistant, qui n'est pas terminé entre-temps."""
    from . import mise_en_place as M

    return bool((request.session.get(CLE) or {}).get("depuis_mise_en_place")) and bool(M.en_cours())


def _destination(ref, depuis_mep):
    """Après l'installation : l'étape 5 de l'assistant, sinon le contenu du référentiel (régler les niveaux)."""
    from . import mise_en_place as M

    if depuis_mep and M.en_cours():
        return reverse("parametres:mise_en_place_etape", args=[5])
    return reverse("parametres:referentiel_contenu", args=[ref.code]) + "?installe=1#regler-niveaux"


# ------------------------------------------------------------------------------------------------------- écran 1
@login_required
def modeles(request):
    exiger_admin_reglages(request)
    depuis = _depuis_mise_en_place(request) or _reprise_mise_en_place(request)
    request.session[CLE] = {"depuis_mise_en_place": depuis}  # nouveau parcours : choix précédents oubliés
    return render(request, "parametres/installer_modeles.html", _contexte(
        fournis=fournis_decrits(), etape_installation=1, depuis_mep=(request.session.get(CLE) or {}).get("depuis_mise_en_place")))


# ------------------------------------------------------------------------------------------------------- écran 2
def _arbre_a_cocher(p, coches, presents, existants):
    """[nœud] : {code, nom, kpis: [ligne], enfants: [nœud], nb, nb_coches} ; une ligne par KPI du modèle."""
    from parametres.models import TypeSaisie

    lg = p.langue_reference
    types_p = {t["code"]: t for t in p.types_saisie}
    locaux = {}
    for t in TypeSaisie.objects.order_by("ordre", "code"):
        locaux.setdefault(t.comportement, t)
    from .referentiel import classe_type

    unites = {u["code"]: P.texte_affiche(u.get("symbole"), lg) or u["code"] for u in p.unites}
    formats = {t["code"]: t.get("format") for t in p.types_reponse}
    noms = {k["code"]: P.texte_affiche(k.get("libelle"), lg) or k["code"] for k in p.kpis}
    utilise_par = {}
    lignes = {}
    for k in p.kpis:
        code = k["code"]
        comportement = (types_p.get(k.get("type_saisie")) or {}).get("comportement") or ("calcul" if k.get("formule") else "saisie")
        local = locaux.get(comportement)
        sources = sorted(c for c in FO.codes_cites(k.get("formule")) if c in noms and c != code) if comportement == "calcul" else []
        for s in sources:
            utilise_par.setdefault(s, []).append(code)
        fmt = formats.get(k.get("type_reponse"))
        unite = ("%" if fmt == "pourcentage" else libelle("referentiels.installer.unite_oui_non") if fmt == "oui_non"
                 else libelle("referentiels.installer.unite_liste") if fmt == "liste" else unites.get(k.get("unite"), ""))
        desc = P.texte_affiche({c: (d or {}).get("description", "") for c, d in (k.get("descriptions") or {}).items()}, lg)
        lignes[code] = {"code": code, "nom": noms[code], "sources": sources, "unite": unite, "definition": desc,
                        "type": (local.tr("abrege") if local else comportement), "type_titre": local.tr("libelle") if local else "",
                        "classe_type": classe_type(local.code) if local else "", "coche": code in coches or code in presents,
                        "present": code in presents, "existant": code in existants and code not in presents,
                        "calcule": comportement == "calcul",
                        # le calcul écrit avec les noms des KPI du modèle, plutôt qu'une liste de codes
                        "calcul": FO.en_clair(k.get("formule"), noms, libelle("referentiels.calcul.exercice_precedent"),
                                              libelle("referentiels.calcul.periode_precedente")) if comportement == "calcul" else ""}
    par_theme = {}
    for k in p.kpis:
        e = k.get("element") or {}
        par_theme.setdefault(X.texte(e.get("theme")), []).append((e.get("ordre") or 0, k["code"]))
    enfants = {}
    for t in sorted(p.themes, key=lambda t: t.get("ordre") or 0):
        enfants.setdefault(X.texte(t.get("parent")), []).append(t)

    def noeud(t, prof):
        n = {"code": t["code"], "nom": P.texte_affiche(t.get("nom"), lg) or t["code"], "prof": prof,
             "kpis": [lignes[c] for _, c in sorted(par_theme.get(t["code"], []))],
             "enfants": [noeud(x, prof + 1) for x in enfants.get(t["code"], [])]}
        n["nb"] = len(n["kpis"]) + sum(e["nb"] for e in n["enfants"])
        n["nb_coches"] = sum(1 for l in n["kpis"] if l["coche"]) + sum(e["nb_coches"] for e in n["enfants"])
        return n
    racines = [noeud(t, 0) for t in enfants.get("", [])]
    sans_theme = [lignes[c] for _, c in sorted(par_theme.get("", []))]
    for code, l in lignes.items():
        l["utilise_par"] = utilise_par.get(code, [])
    return racines, sans_theme, lignes


@login_required
def modele_kpi(request, code):
    from referentiel.models import KPI, ElementReferentiel

    exiger_admin_reglages(request)
    f = modele_fourni(code)
    p = f.paquet
    existant = f.installe
    etat = _etat(request, code)
    depuis_mep = _depuis_mise_en_place(request) or _reprise_mise_en_place(request)
    nouvelle_version = request.GET["version"] == "1" if "version" in request.GET else bool(etat and etat.get("nouvelle_version"))
    presents = set(ElementReferentiel.objects.filter(referentiel=existant).values_list("kpi_id", flat=True)) if existant else set()
    tous = [k["code"] for k in p.kpis]
    if request.method == "POST":
        action = request.POST.get("action", "continuer")
        coches = [c for c in request.POST.getlist("kpi") if c in tous]
        if action in ("tout", "rien"):  # sans JavaScript : « Tout cocher », « Tout décocher »
            coches = tous if action == "tout" else []
        elif not set(coches) - presents and not (nouvelle_version and existant is not None):
            messages.error(request, libelle("referentiels.installer.cocher_un_msg") if not existant else libelle("referentiels.installer.cocher_un_ajouter_msg"))
        else:
            request.session[CLE] = {**(etat or {}), "code": code, "codes": coches, "depuis_mise_en_place": depuis_mep,
                                    "nouvelle_version": nouvelle_version and existant is not None}
            return redirect("parametres:installer_resume", code)
    elif etat and etat.get("codes"):
        coches = [c for c in etat["codes"] if c in tous]
    else:
        coches = [] if existant else tous
    coches = set(coches) - presents
    existants = set(KPI.objects.filter(code__in=tous).values_list("code", flat=True))
    racines, sans_theme, lignes = _arbre_a_cocher(p, coches, presents, existants)
    request.session[CLE] = {**(etat or {}), "code": code, "depuis_mise_en_place": depuis_mep,
                            "nouvelle_version": nouvelle_version and existant is not None}
    nb_coches = len(coches | presents)
    return render(request, "parametres/installer_kpi.html", _contexte(
        f=f, p=p, existant=existant, racines=racines, sans_theme=sans_theme, nb=len(tous), nb_coches=nb_coches,
        nb_existants=len((coches | presents) & existants - presents), nb_presents=len(presents),
        nouvelle_version=nouvelle_version and existant is not None, etape_installation=2, depuis_mep=depuis_mep,
        retour=reverse("parametres:installer_modeles"), **_monnaie(p)))


# ------------------------------------------------------------------------------------------------------- écran 3
def _analyse(f, etat, post=None):
    from referentiel.composition import code_referentiel
    from referentiel.models import Referentiel

    p = f.paquet
    post = post or {}
    nom_defaut = p.nom()
    nom = (post.get("nom") or etat.get("nom") or nom_defaut).strip()[:150]
    frequence = post.get("frequence") or etat.get("frequence") or p.frequence
    mois = post.get("mois_debut") or etat.get("mois_debut") or p.referentiel.get("mois_debut") or 1
    code_defaut = p.code if not Referentiel.objects.filter(code__iexact=p.code).exists() else code_referentiel(nom_defaut)
    code = (post.get("code") or etat.get("code_referentiel") or code_defaut).strip()
    existant = f.installe  # modèle déjà installé : complément (ou nouvelle version) de ce référentiel
    choix_kpi = {c: v for c, v in post.items() if c.startswith(("kpi:", "code:")) and v}
    a, ajoutes = P.analyser_installation(p, etat["codes"], nom=nom, frequence=frequence, mois_debut=int(mois) if str(mois).isdecimal() else 1,
                                         code=code if existant is None else "", existant=existant,
                                         nouvelle_version=bool(etat.get("nouvelle_version")), choix=choix_kpi)
    valeurs = {"nom": nom, "frequence": frequence, "mois_debut": int(mois) if str(mois).isdecimal() else 1, "code": code}
    return a, ajoutes, valeurs, existant


def _liste_et(parts):
    """« A », « A et B », « A, B et C » : parties déjà prêtes (texte sûr), jointes dans la langue de l'interface."""
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return libelle("referentiels.liste_et.deux", a=parts[0], b=parts[1])
    return libelle("referentiels.liste_et.trois", a=parts[0], b=parts[1], c=parts[2])


def _phrases_niveaux(a, niveaux):
    """(phrase, détail) du rattachement dans l'arbre, avec les vrais noms des niveaux ; ("", "") si l'outil n'a choisi aucun
    niveau. La phrase contient du gras (<b>) : texte sûr, noms de niveaux échappés."""
    from collecte.templatetags.collecte import libelle_echappe

    resume = P.resume_niveaux(a)
    if not resume or not niveaux:
        return "", ""
    haut, bas = niveaux[0], niveaux[-1]
    if haut == bas:
        return libelle_echappe("referentiels.installer.resume.un_niveau", None, {"niveau": str(bas)}, html=True), ""
    morceaux = []
    if "saisis" in resume:
        places = [n for n, _ in resume["saisis"]]
        if places == [bas]:
            morceaux.append(libelle_echappe("referentiels.installer.resume.niveau_saisis", None, {"niveau": str(bas)}, html=True))
        else:  # niveaux conseillés par le modèle (« haut », « entite ») : les vrais niveaux, pas « le plus bas »
            noms = _liste_et([format_html("<b>{}</b>", str(n)) for n in places[:3]])
            morceaux.append(libelle("referentiels.installer.resume.niveau_saisis_conseilles", niveaux=noms))
    if "parametres" in resume:
        morceaux.append(libelle_echappe("referentiels.installer.resume.niveau_parametres", None, {"niveau": str(haut)}, html=True))
    if "calcules" in resume:
        morceaux.append(libelle("referentiels.installer.resume.niveau_calcules"))
    phrase = libelle("referentiels.installer.resume.rattachement", liste=_liste_et(morceaux))
    detail = " · ".join(libelle("referentiels.installer.resume.detail_famille", famille=libelle(f"referentiels.installer.famille.{f}"),
                                liste=", ".join(f"{n} ({nb})" for n, nb in resume[f]))
                        for f in ("saisis", "parametres", "calcules") if f in resume)
    return mark_safe(phrase), detail


@login_required
def modele_installer(request, code):
    exiger_admin_reglages(request)
    f = modele_fourni(code)
    etat = _etat(request, code)
    fait = request.session.get(CLE + "_fait") or {}
    if not etat and fait.get("code") == code and f.installe is not None:
        # second clic sur « Installer », retour arrière sur le résumé : c'est déjà fait, on ne réinstalle rien
        return redirect(_destination(f.installe, fait.get("depuis_mise_en_place")))
    if not etat or "codes" not in etat or not (etat["codes"] or etat.get("nouvelle_version")):
        messages.info(request, libelle("referentiels.installer.choisir_d_abord"))
        return redirect("parametres:installer_kpi", code)
    post = request.POST if request.method == "POST" else None
    a, ajoutes, valeurs, existant = _analyse(f, etat, post)
    if request.method == "POST" and request.POST.get("action") == "installer" and not a.erreur:
        if not valeurs["nom"]:
            messages.error(request, libelle("referentiels.vues.nom_obligatoire"))
        else:
            a.depuis = request.POST.get("depuis", "")  # « demandé depuis » des KPI ajoutés (vide : la période en cours)
            try:
                res = P.appliquer(request.user, a, f.paquet.nom())
            except P.PaquetInvalide as e:
                messages.error(request, str(e))
                return redirect("parametres:installer_resume", code)
            ref = res.referentiel
            request.session.pop(CLE, None)
            request.session[CLE + "_fait"] = {"code": code, "depuis_mise_en_place": bool(etat.get("depuis_mise_en_place"))}
            nb = sum(1 for l in a.kpis if l.ajoute)
            if existant is None:
                message = libelle("referentiels.installer.installe", referentiel=str(ref), n=nb)
            else:
                message = libelle("referentiels.installer.complete", referentiel=str(ref), n=nb)
            messages.success(request, message)
            return redirect(_destination(ref, etat.get("depuis_mise_en_place")))
    if request.method == "POST" and request.POST.get("action") == "retour":
        return redirect("parametres:installer_kpi", code)
    if request.method == "POST":  # mémoriser les champs (retour aux choix, nouvel essai)
        etat.update(nom=valeurs["nom"], frequence=valeurs["frequence"], mois_debut=valeurs["mois_debut"], code_referentiel=valeurs["code"])
        request.session[CLE] = etat
    niveaux = sorted(N.tous(), key=lambda n: n.rang)
    from . import mise_en_place as M

    arbre_libre = not M.niveaux_utilises()  # aucune organisation ni aucun KPI : les niveaux se remplacent encore d'un clic
    lignes_place = [l for l in a.kpis if l.place]
    a_voir = [l for l in a.kpis if l.statut in ("conflit", "rejet")]
    phrase_niveaux, detail_niveaux = _phrases_niveaux(a, niveaux)
    from .vues_referentiels import frequences_choix, mois_choix
    return render(request, "parametres/installer_resume.html", _contexte(
        f=f, p=f.paquet, analyse=a, ajoutes=ajoutes, valeurs=valeurs, existant=existant, etape_installation=3,
        nouvelle_version=bool(etat.get("nouvelle_version")) and existant is not None,
        depuis_mep=etat.get("depuis_mise_en_place"), nb_installes=sum(1 for l in a.kpis if l.ajoute), nb_dans=len(lignes_place),
        nb_themes=len(a.themes),
        reutilises=[l for l in a.kpis if l.ajoute and l.local is not None], a_voir=a_voir, phrase_niveaux=phrase_niveaux,
        detail_niveaux=detail_niveaux, niveaux=niveaux, niveaux_chaine=" › ".join(str(n) for n in niveaux), arbre_libre=arbre_libre,
        url_niveaux=reverse("parametres:mise_en_place_etape", args=[4]) if M.en_cours() else reverse("parametres:niveaux"),
        frequences=frequences_choix(), mois=mois_choix(),
        reglages_crees=a.reglages_crees, regles=[r for r in a.regles if r["statut"] != "inchange"],
        options_depuis=choix_depuis(existant) if existant is not None else [], depuis_choisi=(post or {}).get("depuis", ""),
        **_monnaie(f.paquet)))
