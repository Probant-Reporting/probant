"""Administration › Référentiels › Gérer les référentiels : les cadres de reporting (créer, renommer, réordonner, désactiver),
l'arbre des thèmes de chacun (ajouter, renommer, réordonner, déplacer) et les KPI du catalogue qui y figurent
(ajouter, déplacer, rendre facultatif, retirer). Un KPI retiré de tous les référentiels reste dans le catalogue."""
import datetime
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db.models import Count, Max, Q
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme

from collecte.models import Journal
from collecte.periodes import MOIS
from collecte.saisie import campagne_courante

from . import libelles as LB
from .libelles import libelle
from .views import exiger_admin_reglages
from espaces import contexte as ESP

LIMITE = 300  # KPI affichés à la fois (recherche pour aller plus loin)


def origine_texte(ref):
    """Origine d'un référentiel (créé, importé, fourni) dans la langue de l'interface."""
    return libelle(f"referentiels.origine.{ref.origine}")


def frequences_choix():
    """[(valeur, libellé)] des fréquences d'un référentiel, dans la langue de l'interface."""
    from referentiel.models import Referentiel

    return [(v, LB.choix_valeur(Referentiel, "frequence", v)) for v, _ in Referentiel._meta.get_field("frequence").choices]


def comparaisons_choix():
    """[(valeur, libellé)] des comparaisons (même période de l'exercice précédent, période précédente)."""
    from referentiel.models import Referentiel

    return [(v, LB.choix_valeur(Referentiel, "comparaison", v)) for v, _ in Referentiel.Comparaison.choices]


def mois_choix():
    """[(1, "janvier"), …] dans la langue de l'interface (français si elle n'a pas de noms de mois)."""
    return [(n + 1, m) for n, m in enumerate(MOIS.get(LB.langue_effective(), MOIS["fr"]))]


def _journal(request, obj, champ, avant, apres):
    Journal.ecrire(request.user, "reglage_referentiels", obj, champ, avant, apres)


def _arbre(ref):
    """[(thème, profondeur, chemin lisible)] dans l'ordre de l'arbre, avec le nombre de KPI et de sous-thèmes."""
    from referentiel.models import Theme

    themes = list(Theme.objects.filter(referentiel=ref).annotate(nb_kpi=Count("elements", distinct=True),
                                                                  nb_enfants=Count("enfants", distinct=True)))
    enfants = {}
    for t in themes:
        enfants.setdefault(t.parent_id, []).append(t)
    for liste in enfants.values():
        liste.sort(key=lambda t: (t.ordre, t.pk))
    sortie = []

    def parcourir(parent_id, prof, chemin):
        freres = enfants.get(parent_id, [])
        for i, t in enumerate(freres):
            t.premier, t.dernier = i == 0, i == len(freres) - 1
            t.chemin = " › ".join(chemin + [t.tr("nom")])
            sortie.append((t, prof))
            parcourir(t.pk, prof + 1, chemin + [t.tr("nom")])

    parcourir(None, 0, [])
    return sortie


def _descendants(theme):
    from referentiel.models import Theme

    ids, a_voir = set(), [theme.pk]
    while a_voir:
        a_voir = list(Theme.objects.filter(parent_id__in=a_voir).values_list("pk", flat=True))
        ids.update(a_voir)
    return ids


def referentiels_annotes():
    """Référentiels (par ordre) avec leurs nombres de KPI, de thèmes et de campagnes : trois comptages groupés (un
    seul COUNT DISTINCT sur trois jointures multiplierait les lignes : éléments × thèmes × campagnes)."""
    from collecte.models import Campagne
    from referentiel.models import ElementReferentiel, Referentiel, Theme

    def compte(modele):
        return dict(modele.objects.order_by().values_list("referentiel_id").annotate(n=Count("id")))

    kpis, themes, campagnes = compte(ElementReferentiel), compte(Theme), compte(Campagne)
    refs = list(Referentiel.objects.order_by("ordre", "code"))
    for r in refs:
        r.nb_kpi, r.nb_themes, r.nb_campagnes = kpis.get(r.pk, 0), themes.get(r.pk, 0), campagnes.get(r.pk, 0)
    return refs


def _retour(request, defaut=None):
    """Adresse où revenir après un formulaire : champ « retour » (chemin de l'outil), sinon ``defaut``."""
    r = request.POST.get("retour", "")
    # « /\\site » passait l'ancien contrôle (commence par « / », pas par « // ») : lu « //site » par les navigateurs
    ok = r.startswith("/") and url_has_allowed_host_and_scheme(r, {request.get_host()}, request.is_secure())
    return r if ok else defaut


@login_required
def referentiels(request):
    """Accueil : une carte par référentiel et le catalogue. Les formulaires des pages d'un référentiel envoient ici leurs
    actions (créer, enregistrer les réglages, réordonner, supprimer, thèmes et KPI en lot)."""
    from collecte import paquets as PQ
    from referentiel.models import KPI

    exiger_admin_reglages(request)
    tous = referentiels_annotes()
    ref = next((r for r in tous if r.code == (request.POST.get("ref") or request.GET.get("ref"))), None)
    if request.method == "POST":
        erreur = ""
        with ESP.atomic():
            try:
                from collecte.calcul import si_frequences_changent

                with si_frequences_changent():
                    cible = _action(request, ref)
            except ValidationError as e:
                erreur, cible = " ".join(e.messages), None
        if erreur:
            messages.error(request, erreur)
            return redirect(_retour(request) or (reverse("parametres:referentiel_contenu", args=[ref.code]) if ref else request.path))
        return redirect(_retour(request, cible) or cible or (reverse("parametres:referentiel_contenu", args=[ref.code]) if ref
                                                             else request.path))
    if ref is not None:  # anciens liens « ?ref=CODE » : la page du référentiel
        return redirect("parametres:referentiel_contenu", ref.code)
    maj = {f.installe.code: f for f in PQ.bibliotheque() if f.installe is not None and f.etat == "mise_a_jour"}
    from collecte.models import Campagne
    from .vues_installation import bibliotheque_par_thematique

    # état de chaque référentiel, en une étiquette : campagne ouverte, pas encore utilisé, mise à jour
    ouvertes = {}
    for c in Campagne.objects.filter(statut__in=[Campagne.Statut.OUVERTE, Campagne.Statut.REVUE]).select_related("periode").order_by("-periode__debut"):
        ouvertes.setdefault(c.referentiel_id, c)
    for r in tous:
        r.mise_a_jour = maj.get(r.code)
        r.origine_texte = origine_texte(r)
        r.campagne_ouverte = ouvertes.get(r.pk)
    return render(request, "parametres/referentiels_accueil.html", {"bibliotheque": bibliotheque_par_thematique(),
        "page": "administration", "rubrique": "referentiels", "sous_rubrique": "referentiels", "campagne": campagne_courante(),
        "referentiels": tous, "nb_catalogue": KPI.objects.count(), "nb_orphelins": KPI.objects.filter(elements=None).count(),
        "nb_inactifs": KPI.objects.filter(actif=False).count()})


def contexte_referentiel(request, ref, onglet, **autres):
    """Contexte commun des pages d'un référentiel (en-tête, onglets Contenu, Réglages, Versions et partage)."""
    r = next(x for x in referentiels_annotes() if x.code == ref.code)
    r.origine_texte = origine_texte(r)
    r.mois_libelle = dict(mois_choix())[r.mois_debut]
    from collecte import paquets as PQ

    return {"page": "administration", "rubrique": "referentiels", "sous_rubrique": "referentiels", "campagne": campagne_courante(),
            "ref": r, "onglet_ref": onglet, "frequences": frequences_choix(),
            # documents sources du modèle de la bibliothèque dont il vient (par l'identifiant ; rien en base)
            "documents_source": PQ.documents_fournis(r.identifiant) if r.origine == "fourni" else [],
            "comparaisons": comparaisons_choix(), "mois": mois_choix(), **autres}


def _ref_ou_404(code):
    from django.shortcuts import get_object_or_404

    from referentiel.models import Referentiel

    return get_object_or_404(Referentiel, code=code)


CLE_RETOUR_MEP = "referentiel_compose_depuis_mise_en_place"  # code du référentiel composé depuis l'assistant (étape 5)


@login_required
def nouveau(request):
    """Ajouter un référentiel : trois portes (installer depuis la bibliothèque, composer à partir de KPI existants,
    importer un fichier). Le formulaire de la porte 2 crée le référentiel (vide, ou avec le tiroir « Ajouter depuis… »)."""

    from .vues_installation import contexte_portes

    exiger_admin_reglages(request)
    if request.method == "POST":
        try:
            with ESP.atomic():
                cible = ajouter_referentiel(request)
        except ValidationError as e:
            messages.error(request, " ".join(e.messages))
        else:
            from . import mise_en_place as M

            if request.POST.get("depuis") == "mise_en_place" and M.en_cours():  # retour à l'assistant proposé dans le contenu
                request.session[CLE_RETOUR_MEP] = cible.rstrip("/").rsplit("/", 1)[-1]
            if request.POST.get("composer") and request.POST.get("depuis") != "mise_en_place":
                return redirect(cible.rstrip("/") + "/choisir/")  # « Créer et choisir les KPI » : la page à cocher
            return redirect(cible + ("?ajouter=1" if request.POST.get("composer") else ""))  # assistant : le contenu, avec le retour
    return render(request, "parametres/referentiel_nouveau.html", {
        "page": "administration", "rubrique": "referentiels", "sous_rubrique": "referentiels", "campagne": campagne_courante(),
        **contexte_portes(), "post": request.POST})


HORS = "_hors"  # source « KPI hors de tout référentiel » de la page « Choisir les KPI »


@login_required
def choisir(request, code):
    """Choisir les KPI d'un référentiel à soi : les KPI d'un autre référentiel (ou ceux du catalogue qui ne
    sont dans aucun), à cocher par thème, dans l'allure du catalogue. Les KPI cochés sont ajoutés sous des thèmes de
    même nom ; aucun KPI n'est recopié (une valeur saisie sert dans tous les référentiels)."""
    from referentiel import formule as FO
    from referentiel.composition import chemin_noms, placer, theme_par_chemin
    from referentiel.models import KPI, ElementReferentiel, Referentiel, Theme

    from collecte.demande_depuis import choix as choix_depuis

    from .referentiel import classe_type

    exiger_admin_reglages(request)
    cible = _ref_ou_404(code)
    presents = set(ElementReferentiel.objects.filter(referentiel=cible).values_list("kpi_id", flat=True))
    comptes = dict(ElementReferentiel.objects.order_by().values_list("referentiel_id").annotate(n=Count("id")))
    sources = [(r.code, str(r), comptes.get(r.pk, 0)) for r in Referentiel.objects.exclude(pk=cible.pk).order_by("ordre", "code")
               if comptes.get(r.pk)]
    nb_hors = KPI.objects.filter(elements=None).count()
    if nb_hors:
        sources.append((HORS, libelle("referentiels.choisir.source_hors"), nb_hors))
    demande = request.POST.get("source") or request.GET.get("source") or ""
    source_code = demande if demande in {c for c, _, _ in sources} else (sources[0][0] if sources else "")
    if source_code == HORS:
        elements = [ElementReferentiel(kpi=k) for k in KPI.objects.filter(elements=None).select_related("type_saisie", "unite", "type_reponse").order_by("ordre", "code")]
        themes = []
    else:
        elements = list(ElementReferentiel.objects.filter(referentiel_id=source_code or None)
                        .select_related("kpi", "kpi__type_saisie", "kpi__unite", "kpi__type_reponse", "theme").order_by("ordre", "kpi_id"))
        themes = list(Theme.objects.filter(referentiel_id=source_code or None).order_by("ordre", "pk"))
    if request.method == "POST":
        coches = set(request.POST.getlist("kpi")) - presents
        cache, n = {}, 0
        with ESP.atomic():
            for e in elements:
                if e.kpi_id not in coches:
                    continue
                theme = theme_par_chemin(cible, chemin_noms(e), cache) if e.theme_id else None
                _, cree = placer(e.kpi, cible, theme, obligatoire=e.obligatoire)
                n += cree
            if n:
                origine = libelle("referentiels.choisir.source_hors") if source_code == HORS else source_code
                Journal.ecrire(request.user, "reglage_referentiels", cible, "composition", "", f"{n} KPI repris de {origine}")
            if n and request.POST.get("depuis"):  # « Les ajouter aussi aux exercices précédents ? »
                from collecte.demande_depuis import changer, lire_choix

                try:
                    changer(request.user, cible, sorted(coches), lire_choix(cible, request.POST["depuis"]))
                except ValidationError as e:
                    messages.error(request, " ".join(e.messages))
        if n:
            messages.success(request, libelle("referentiels.choisir.ajoutes", n=n, referentiel=str(cible)))
            return redirect(reverse("parametres:referentiel_contenu", args=[cible.code]) + "?choisis=1")
        messages.error(request, libelle("referentiels.choisir.cocher_un"))
        return redirect(f"{request.path}?source={source_code}")
    noms = {k.code: k.nom for k in KPI.objects.all()}
    precedent, periode = libelle("referentiels.calcul.exercice_precedent"), libelle("referentiels.calcul.periode_precedente")

    def ligne(e):
        k = e.kpi
        t = k.type_saisie
        return {"code": k.code, "nom": k.nom, "sources": [], "unite": k.symbole if k.est_numerique else str(k.type_reponse or ""),
                "definition": "", "type": t.tr("abrege") if t else "", "type_titre": t.tr("libelle") if t else "",
                "classe_type": classe_type(t.code) if t else "", "coche": k.code in presents, "present": k.code in presents,
                "existant": False, "sans_etat": True, "texte_present": libelle("referentiels.choisir.deja_dedans"),
                "calcul": FO.en_clair(k.formule, noms, precedent, periode) if k.est_calcule else ""}

    par_theme = {}
    for e in elements:
        par_theme.setdefault(e.theme_id, []).append(ligne(e))
    enfants = {}
    for t in themes:
        enfants.setdefault(t.parent_id, []).append(t)

    def noeud(t, prof):
        n = {"code": f"{t.pk}", "nom": str(t), "prof": prof, "kpis": par_theme.get(t.pk, []),
             "enfants": [noeud(x, prof + 1) for x in enfants.get(t.pk, [])]}
        n["nb"] = len(n["kpis"]) + sum(x["nb"] for x in n["enfants"])
        n["nb_coches"] = sum(1 for l in n["kpis"] if l["coche"]) + sum(x["nb_coches"] for x in n["enfants"])
        return n

    racines = [x for x in (noeud(t, 0) for t in enfants.get(None, [])) if x["nb"]]
    return render(request, "parametres/referentiel_choisir.html", {
        "page": "administration", "rubrique": "referentiels", "sous_rubrique": "referentiels", "campagne": campagne_courante(),
        "ref": cible, "sources": sources, "source_code": source_code, "racines": racines, "sans_theme": par_theme.get(None, []),
        "nb": len(elements), "nb_presents": len(presents), "nb_presents_source": sum(1 for e in elements if e.kpi_id in presents),
        "options_depuis": choix_depuis(cible)})


@login_required
def nouveau_ancien(request):
    """Ancienne adresse « Nouveau référentiel » : la page « Ajouter un référentiel »."""
    exiger_admin_reglages(request)
    return redirect("parametres:referentiel_nouveau")


@login_required
def reglages(request, code):
    """Réglages d'un référentiel : nom, couleur, description, fréquence, exercice, comparaison, version, actif, position."""
    exiger_admin_reglages(request)
    ref = _ref_ou_404(code)
    tous = list(type(ref).objects.order_by("ordre", "code"))
    return render(request, "parametres/referentiel_reglages.html", contexte_referentiel(
        request, ref, "reglages", position=[r.code for r in tous].index(ref.code) + 1, nb_refs=len(tous)))


@login_required
def partage(request, code):
    """Versions et partage : exporter le référentiel en fichier, importer une nouvelle version, mise à jour de la
    bibliothèque, historique des réglages."""
    from collecte import paquets as PQ

    exiger_admin_reglages(request)
    ref = _ref_ou_404(code)
    fourni = next((f for f in PQ.bibliotheque() if f.installe is not None and f.installe.code == ref.code), None)
    historique = list(Journal.objects.filter(Q(objet="Referentiel", objet_id=ref.code) | Q(action="export_paquet", objet_id=ref.code))
                      .order_by("-date")[:15])
    return render(request, "parametres/referentiel_partage.html", contexte_referentiel(
        request, ref, "partage", fourni=fourni, historique=historique))


def _action(request, ref):
    """Exécute le bouton envoyé ; renvoie l'adresse où revenir (ou None : la page du référentiel)."""
    P = request.POST
    action = P.get("action", "")
    for cle in ("monter", "descendre", "supprimer", "monter_theme", "descendre_theme", "supprimer_theme"):
        if cle in P:
            action = cle
    if action == "ajouter":
        return ajouter_referentiel(request)
    if action == "enregistrer":
        return _enregistrer_referentiels(request)
    if action in ("monter", "descendre", "supprimer"):
        return _ligne_referentiel(request, action, P.get(action, ""))
    if action in ("desactiver", "reactiver"):
        return _basculer_actif(request, P.get("code", ""), actif=action == "reactiver")
    if ref is None:
        raise ValidationError(libelle("referentiels.vues.aucun_referentiel"))
    if action == "ajouter_theme":
        _ajouter_theme(request, ref)
    elif action == "enregistrer_themes":
        _enregistrer_themes(request, ref)
    elif action in ("monter_theme", "descendre_theme", "supprimer_theme"):
        _ligne_theme(request, ref, action, P.get(action, ""))
    elif action == "ajouter_kpi":
        _ajouter_kpi(request, ref)
    elif action in ("deplacer", "obligatoire", "facultatif", "retirer"):
        _elements(request, ref, action)
        retour = {"ref": ref.code, **{c: P.get(c) for c in ("q", "theme") if P.get(c)}}
        return reverse("parametres:referentiels") + "?" + urlencode(retour) + "#kpi"
    else:
        raise ValidationError(libelle("referentiels.vues.action_inconnue"))
    return None


# ------------------------------------------------------------------------------------------------- référentiels
def ajouter_referentiel(request):
    from referentiel.composition import code_referentiel
    from referentiel.models import Referentiel, valider_code_referentiel

    from .models import valider_couleur

    P = request.POST
    nom = P.get("nom", "").strip()[:150]
    if not nom:
        raise ValidationError(libelle("referentiels.vues.nom_obligatoire"))
    code = P.get("code", "").strip() or code_referentiel(nom)
    valider_code_referentiel(code)
    if Referentiel.objects.filter(code__iexact=code).exists():
        raise ValidationError(libelle("referentiels.vues.code_existe", code=code))
    couleur = (P.get("couleur", "").strip() or "#1F5FAD").upper()
    valider_couleur(couleur)
    ordre = (Referentiel.objects.aggregate(m=Max("ordre"))["m"] or 0) + 1
    frequence = P.get("frequence") if P.get("frequence") in dict(Referentiel._meta.get_field("frequence").choices) else "annee"
    mois_debut = int(P.get("mois_debut")) if str(P.get("mois_debut", "")).isdecimal() and 1 <= int(P.get("mois_debut")) <= 12 else 1
    r = Referentiel.objects.create(code=code, nom=nom, couleur=couleur, description=P.get("description", "").strip(), ordre=ordre,
                                   frequence=frequence, mois_debut=mois_debut,
                                   comparaison="P-1" if P.get("comparaison") == "P-1" else "N-1")
    _journal(request, r, "référentiel", "", f"{nom} ({code}) créé")
    messages.success(request, libelle("referentiels.vues.cree", nom=nom))
    return reverse("parametres:referentiel_contenu", args=[code])


def _enregistrer_referentiels(request):
    from referentiel.models import Referentiel

    from .models import valider_couleur

    P = request.POST
    n = 0
    frequences = dict(Referentiel._meta.get_field("frequence").choices)
    for r in Referentiel.objects.all():
        if f"nom__{r.code}" not in P:
            continue
        avant = {"nom": r.nom, "description": r.description, "couleur": r.couleur, "actif": r.actif, "frequence": r.frequence,
                 "mois_debut": r.mois_debut, "comparaison": r.comparaison, "version": r.version,
                 "date_version": r.date_version}
        frequence, mois = P.get(f"frequence__{r.code}", r.frequence), P.get(f"mois_debut__{r.code}", str(r.mois_debut))
        if frequence in frequences and mois.isdecimal() and 1 <= int(mois) <= 12 and (frequence, int(mois)) != (r.frequence, r.mois_debut):
            if r.campagnes.exists():
                raise ValidationError(libelle("referentiels.vues.a_des_campagnes_frequence", referentiel=str(r)))
            r.frequence, r.mois_debut = frequence, int(mois)
        if P.get(f"comparaison__{r.code}") in ("N-1", "P-1"):
            r.comparaison = P[f"comparaison__{r.code}"]
        r.nom = P.get(f"nom__{r.code}", "").strip()[:150] or r.nom
        r.description = P.get(f"description__{r.code}", "").strip()
        r.couleur = (P.get(f"couleur__{r.code}", "").strip() or r.couleur).upper()
        try:
            valider_couleur(r.couleur)
        except ValidationError:
            raise ValidationError(libelle("referentiels.vues.couleur_format", nom=avant["nom"]))
        r.actif = f"actif__{r.code}" in P
        r.version = P.get(f"version__{r.code}", "").strip()[:20] or r.version
        if f"date_version__{r.code}" in P:  # date de la version : celle choisie, sinon aujourd'hui si la version change
            texte = P[f"date_version__{r.code}"].strip()
            try:
                date = datetime.date.fromisoformat(texte) if texte else None
            except ValueError:
                date = avant["date_version"]
            if date == avant["date_version"] and r.version != avant["version"]:
                date = timezone.localdate()
            r.date_version = date
        changes = [(c, a, getattr(r, c)) for c, a in avant.items() if a != getattr(r, c)]
        if changes:
            r.save()
            n += 1
            for c, a, b in changes:
                _journal(request, r, c, a, b)
    messages.success(request, libelle("referentiels.vues.enregistres") if n else libelle("referentiels.vues.aucune_modification"))
    return reverse("parametres:referentiels") + (f"?ref={request.GET.get('ref')}" if request.GET.get("ref") else "")


def _basculer_actif(request, code, actif):
    """Rendre un référentiel inactif (ou le réactiver) en un clic : il disparaît des filtres et ne déclenche plus de
    collecte ; ses campagnes, ses valeurs et son contenu sont gardés."""
    from referentiel.models import Referentiel

    r = Referentiel.objects.filter(code=code).first()
    if r is None:
        raise ValidationError(libelle("referentiels.vues.inconnu"))
    if r.actif != actif:
        r.actif = actif
        r.save(update_fields=["actif"])
        _journal(request, r, "actif", not actif, actif)
    messages.success(request, libelle("referentiels.vues.reactive" if actif else "referentiels.vues.desactive", nom=str(r)))
    return _retour(request, reverse("parametres:referentiels"))


def copier_referentiel(user, ref, nom, code=None, desactiver_original=False, campagnes_des=None):
    """Copie d'un référentiel : réglages (fréquence, exercice, comparaison, couleur, description, traductions),
    arbre des thèmes, KPI avec leur thème, leur libellé, leur ordre et leur caractère obligatoire. Les KPI sont ceux du
    catalogue (aucune valeur dupliquée : une valeur saisie compte dans les deux) ; les campagnes ne sont pas copiées.
    ``desactiver_original`` : l'original devient inactif (nouvelle version d'un référentiel).
    ``campagnes_des`` (exercice, ex. 2026) : les campagnes de l'original à partir de cet exercice passent à la copie
    (référentiel historique jusqu'à 2025, nouvelle version à partir de 2026) ; les valeurs, rangées par période, ne
    bougent pas. Renvoie la copie (``copie.campagnes_passees`` : nombre de campagnes passées)."""
    from referentiel.composition import code_referentiel
    from referentiel.models import ElementReferentiel, Referentiel, Theme, valider_code_referentiel

    nom = (nom or "").strip()[:150]
    if not nom:
        raise ValidationError(libelle("referentiels.vues.nom_obligatoire"))
    code = (code or "").strip() or code_referentiel(nom)
    valider_code_referentiel(code)
    if Referentiel.objects.filter(code__iexact=code).exists():
        raise ValidationError(libelle("referentiels.vues.code_existe", code=code))
    traductions = {lg: {k: v for k, v in champs.items() if k != "nom"} for lg, champs in (ref.traductions or {}).items()}
    copie = Referentiel.objects.create(
        code=code, nom=nom, description=ref.description, couleur=ref.couleur, frequence=ref.frequence,
        mois_debut=ref.mois_debut, comparaison=ref.comparaison, version=ref.version, date_version=ref.date_version,
        ordre=(Referentiel.objects.aggregate(m=Max("ordre"))["m"] or 0) + 1,
        traductions={lg: c for lg, c in traductions.items() if c},
        provenance=libelle("referentiels.copie.provenance", nom=ref.nom, code=ref.code)[:200])
    correspondance = {}
    themes = list(ref.themes.all())
    restants = themes[:]
    while restants:  # parents d'abord
        suivants = []
        for t in restants:
            if t.parent_id is None or t.parent_id in correspondance:
                correspondance[t.pk] = Theme.objects.create(referentiel=copie, code=t.code, nom=t.nom, ordre=t.ordre,
                                                            traductions=t.traductions, parent=correspondance.get(t.parent_id))
            else:
                suivants.append(t)
        if len(suivants) == len(restants):  # parent hors du référentiel (ne devrait pas arriver) : rattachés à la racine
            for t in suivants:
                correspondance[t.pk] = Theme.objects.create(referentiel=copie, code=t.code, nom=t.nom, ordre=t.ordre,
                                                            traductions=t.traductions)
            break
        restants = suivants
    # bulk_create ne passe pas par save() : chaque champ est recopié ici, « demandé depuis » compris
    ElementReferentiel.objects.bulk_create([
        ElementReferentiel(referentiel=copie, kpi_id=e.kpi_id, theme=correspondance.get(e.theme_id), ordre=e.ordre,
                           libelle=e.libelle, obligatoire=e.obligatoire, traductions=e.traductions,
                           demande_depuis=e.demande_depuis)
        for e in ref.elements.all()])
    Journal.ecrire(user, "reglage_referentiels", copie, "référentiel", "", f"{copie.nom} ({copie.code}) créé par copie de {ref.nom} ({ref.code})")
    copie.campagnes_passees = 0
    if campagnes_des:
        from collecte.calcul import recalculer
        from collecte.models import Campagne

        for c in Campagne.objects.filter(referentiel=ref, exercice__gte=campagnes_des).select_related("periode"):
            c.referentiel = copie
            c.save(update_fields=["referentiel"])
            Journal.ecrire(user, "reglage_campagne", c, "référentiel", f"{ref.nom} ({ref.code})", f"{copie.nom} ({copie.code})")
            if c.statut != Campagne.Statut.CLOTUREE:
                recalculer(c)  # périmètre du nouveau référentiel (alertes, cumuls, formules)
            copie.campagnes_passees += 1
    if desactiver_original and ref.actif:
        ref.actif = False
        ref.save(update_fields=["actif"])
        Journal.ecrire(user, "reglage_referentiels", ref, "actif", True, False)
    return copie


@login_required
def copier(request, code):
    """Page « Dupliquer » d'un référentiel : nom et code de la copie, et, au choix, l'original rendu inactif."""
    exiger_admin_reglages(request)
    ref = _ref_ou_404(code)
    nom = libelle("referentiels.copie.nom_defaut", nom=ref.nom)[:150]
    erreur, exercice = "", ""
    if request.method == "POST":
        nom = request.POST.get("nom", "").strip()
        exercice = request.POST.get("campagnes_des", "").strip()
        try:
            if exercice and not (exercice.isdecimal() and 1900 <= int(exercice) <= 3000):
                raise ValidationError(libelle("referentiels.copie.exercice_invalide"))
            with ESP.atomic():
                copie = copier_referentiel(request.user, ref, nom, request.POST.get("code", ""),
                                           desactiver_original="desactiver" in request.POST,
                                           campagnes_des=int(exercice) if exercice else None)
        except ValidationError as e:
            erreur = " ".join(e.messages)
        else:
            messages.success(request, libelle("referentiels.copie.faite", nom=copie.nom, original=ref.nom)
                             + (" " + libelle("referentiels.copie.campagnes_passees", n=copie.campagnes_passees, nom=copie.nom,
                                              exercice=exercice) if exercice else "")
                             + (" " + libelle("referentiels.copie.original_inactif", original=ref.nom)
                                if "desactiver" in request.POST else ""))
            return redirect("parametres:referentiel_contenu", copie.code)
    exercices = sorted(set(ref.campagnes.values_list("exercice", flat=True)))
    return render(request, "parametres/referentiel_copier.html", contexte_referentiel(
        request, ref, "copier", nom_copie=nom, erreur=erreur, exercice=exercice, exercices=exercices))


def lire_codes(texte):
    """Codes KPI collés (colonne copiée d'Excel, ou séparés par des espaces, virgules ou points-virgules), sans doublon."""
    import re

    return list(dict.fromkeys(c.strip() for c in re.split(r"[\s,;]+", texte or "") if c.strip()))


def retirer_par_liste(user, ref, codes, garder=False, appliquer=False):
    """KPI à retirer d'un référentiel d'après une liste de codes : ceux de la liste (``garder=False``) ou tous les autres
    (``garder=True``). Renvoie (à retirer, codes de la liste absents du référentiel, nombre restant) ; ``appliquer`` :
    retire vraiment (les KPI restent au catalogue avec leurs valeurs) et le note au journal."""
    from referentiel.models import ElementReferentiel

    elements = list(ElementReferentiel.objects.filter(referentiel=ref).select_related("kpi").order_by("ordre", "kpi_id"))
    presents = {e.kpi_id for e in elements}
    liste = set(codes)
    absents = [c for c in codes if c not in presents]
    a_retirer = [e for e in elements if (e.kpi_id not in liste) == garder]
    if appliquer and a_retirer:
        for e in a_retirer:
            _j(user, e.kpi, "Référentiel", f"{ref}", "(retiré)")
        ElementReferentiel.objects.filter(pk__in=[e.pk for e in a_retirer]).delete()
    return a_retirer, absents, len(elements) - len(a_retirer)


@login_required
def liste(request, code):
    """Page « Retirer par liste » : coller des codes KPI, retirer ceux-là ou garder seulement ceux-là ; aperçu puis
    confirmation."""
    exiger_admin_reglages(request)
    ref = _ref_ou_404(code)
    texte, mode, erreur, apercu = "", "retirer", "", None
    if request.method == "POST":
        texte, mode = request.POST.get("codes", ""), request.POST.get("mode", "retirer")
        codes = lire_codes(texte)
        if not codes:
            erreur = libelle("referentiels.liste.vide")
        else:
            confirmer = request.POST.get("action") == "confirmer"
            with ESP.atomic():
                a_retirer, absents, restent = retirer_par_liste(request.user, ref, codes, garder=mode == "garder",
                                                                appliquer=confirmer)
            if confirmer:
                messages.success(request, libelle("referentiels.vues.kpi_retires", n=len(a_retirer), referentiel=str(ref)))
                return redirect("parametres:referentiel_contenu", ref.code)
            apercu = {"a_retirer": a_retirer, "absents": absents, "restent": restent, "n_liste": len(codes)}
    return render(request, "parametres/referentiel_liste.html", contexte_referentiel(
        request, ref, "liste", texte=texte, mode=mode, erreur=erreur, apercu=apercu))


def _ligne_referentiel(request, action, code):
    from referentiel.models import Referentiel

    tous = list(Referentiel.objects.all())
    r = next((x for x in tous if x.code == code), None)
    if r is None:
        raise ValidationError(libelle("referentiels.vues.inconnu"))
    if action == "supprimer":
        if r.elements.exists():
            raise ValidationError(libelle("referentiels.vues.contient_kpi", referentiel=str(r)))
        if r.campagnes.exists():
            raise ValidationError(libelle("referentiels.vues.a_des_campagnes", referentiel=str(r)))
        _journal(request, r, "référentiel", f"{r.nom} ({r.code})", "supprimé")
        r.delete()
        messages.success(request, libelle("referentiels.vues.supprime", nom=r.nom))
        return reverse("parametres:referentiels")
    i = tous.index(r)
    j = i - 1 if action == "monter" else i + 1
    if 0 <= j < len(tous):
        tous[i], tous[j] = tous[j], tous[i]
        for n, x in enumerate(tous, start=1):
            if x.ordre != n:
                Referentiel.objects.filter(pk=x.pk).update(ordre=n)
        _journal(request, r, "ordre", i + 1, j + 1)
    return reverse("parametres:referentiels") + f"?ref={request.GET.get('ref') or code}"


# ------------------------------------------------------------------------------------------------------- thèmes
def theme_du_referentiel(ref, pk):
    from referentiel.models import Theme

    t = Theme.objects.filter(pk=pk, referentiel=ref).first() if str(pk).isdecimal() else None
    if t is None:
        raise ValidationError(libelle("referentiels.vues.theme_inconnu"))
    return t


def _ajouter_theme(request, ref):
    from referentiel.composition import code_theme
    from referentiel.models import Theme

    P = request.POST
    nom = P.get("nom_theme", "").strip()[:150]
    if not nom:
        raise ValidationError(libelle("referentiels.vues.theme_nom_obligatoire"))
    parent = theme_du_referentiel(ref, P["parent"]) if P.get("parent") else None
    code = P.get("code_theme", "").strip()[:40]
    if code and Theme.objects.filter(referentiel=ref, code=code).exists():
        raise ValidationError(libelle("referentiels.vues.theme_code_existe", code=code))
    ordre = (Theme.objects.filter(referentiel=ref, parent=parent).aggregate(m=Max("ordre"))["m"] or 0) + 1
    t = Theme.objects.create(referentiel=ref, parent=parent, nom=nom, code=code or code_theme(ref, nom), ordre=ordre)
    _journal(request, t, "thème", "", f"{ref.code} › {nom} ajouté" + (f" sous « {parent} »" if parent else ""))
    messages.success(request, libelle("referentiels.vues.theme_ajoute", nom=nom))


def _enregistrer_themes(request, ref):
    from referentiel.models import Theme

    P = request.POST
    themes = {t.pk: t for t in Theme.objects.filter(referentiel=ref)}
    n = 0
    for t in themes.values():
        if f"theme_nom__{t.pk}" not in P:
            continue
        avant = (t.nom, t.parent_id)
        t.nom = P.get(f"theme_nom__{t.pk}", "").strip()[:150] or t.nom
        parent = P.get(f"theme_parent__{t.pk}", "")
        nouveau_parent = int(parent) if parent.isdecimal() and int(parent) in themes else None
        if nouveau_parent != t.parent_id:
            if nouveau_parent == t.pk or nouveau_parent in _descendants(t):
                raise ValidationError(libelle("referentiels.vues.theme_sous_lui_meme", nom=avant[0]))
            t.parent_id = nouveau_parent
            t.ordre = (Theme.objects.filter(referentiel=ref, parent_id=nouveau_parent).aggregate(m=Max("ordre"))["m"] or 0) + 1
        if (t.nom, t.parent_id) != avant:
            t.save()
            n += 1
            if t.nom != avant[0]:
                _journal(request, t, "nom", avant[0], t.nom)
            if t.parent_id != avant[1]:
                _journal(request, t, "parent", themes[avant[1]] if avant[1] else "(racine)",
                         themes[t.parent_id] if t.parent_id else "(racine)")
    messages.success(request, libelle("referentiels.vues.themes_enregistres") if n else libelle("referentiels.vues.aucune_modification"))


def _ligne_theme(request, ref, action, pk):
    from referentiel.models import Theme

    t = theme_du_referentiel(ref, pk)
    if action == "supprimer_theme":
        if t.enfants.exists() or t.elements.exists():
            raise ValidationError(libelle("referentiels.vues.theme_pas_vide", theme=str(t)))
        _journal(request, t, "thème", f"{ref.code} › {t.nom}", "supprimé")
        t.delete()
        messages.success(request, libelle("referentiels.vues.theme_supprime", nom=t.nom))
        return
    freres = list(Theme.objects.filter(referentiel=ref, parent=t.parent).order_by("ordre", "id"))
    i = freres.index(t)
    j = i - 1 if action == "monter_theme" else i + 1
    if 0 <= j < len(freres):
        freres[i], freres[j] = freres[j], freres[i]
        for n, x in enumerate(freres, start=1):
            if x.ordre != n:
                Theme.objects.filter(pk=x.pk).update(ordre=n)
        _journal(request, t, "ordre", i + 1, j + 1)


# ---------------------------------------------------------------------------------------------- KPI du référentiel
def _codes(request, cle):
    """Codes KPI cochés (cases) et tapés (zone de texte, séparés par des espaces, virgules ou retours à la ligne)."""
    import re

    codes = list(request.POST.getlist(cle))
    codes += [c for c in re.split(r"[\s,;]+", request.POST.get(f"{cle}_texte", "")) if c]
    return list(dict.fromkeys(codes))


def _ajouter_kpi(request, ref):
    from referentiel.composition import ordre_suivant
    from referentiel.models import KPI, ElementReferentiel

    P = request.POST
    theme = theme_du_referentiel(ref, P["theme_cible"]) if P.get("theme_cible") else None
    codes = _codes(request, "kpi")
    if not codes:
        raise ValidationError(libelle("referentiels.vues.cocher_catalogue"))
    kpis = KPI.objects.in_bulk(codes)
    inconnus = [c for c in codes if c not in kpis]
    if inconnus:
        raise ValidationError(libelle("referentiels.vues.absents_catalogue", liste=", ".join(inconnus[:10]) + (" …" if len(inconnus) > 10 else "")))
    deja = set(ElementReferentiel.objects.filter(referentiel=ref, kpi_id__in=codes).values_list("kpi_id", flat=True))
    ordre = ordre_suivant(ref, theme)
    ajoutes = 0
    for c in codes:
        if c in deja:
            continue
        ElementReferentiel.objects.create(referentiel=ref, kpi=kpis[c], theme=theme, ordre=ordre)
        _journal(request, kpis[c], "Référentiel", "", f"{ref}" + (f" › {theme}" if theme else ""))
        ordre, ajoutes = ordre + 1, ajoutes + 1
    from collecte.demande_depuis import changer, lire_choix

    # « L'ajouter aussi aux exercices précédents ? » : vide = l'exercice en cours (déjà posé)
    if P.get("depuis") and ajoutes:
        changer(request.user, ref, [c for c in codes if c not in deja], lire_choix(ref, P["depuis"]))
    messages.success(request, libelle("referentiels.vues.kpi_ajoutes", n=ajoutes, referentiel=str(ref),
                                      deja=(" " + libelle("referentiels.vues.kpi_deja", n=len(deja))) if deja else ""))


def _elements(request, ref, action):
    from referentiel.composition import ordre_suivant
    from referentiel.models import ElementReferentiel

    codes = _codes(request, "element")
    elements = list(ElementReferentiel.objects.filter(referentiel=ref, kpi_id__in=codes).select_related("kpi", "theme"))
    if not elements:
        raise ValidationError(libelle("referentiels.vues.cocher_referentiel"))
    if action == "retirer":
        for e in elements:
            _journal(request, e.kpi, "Référentiel", f"{ref}", "(retiré)")
        ElementReferentiel.objects.filter(pk__in=[e.pk for e in elements]).delete()
        messages.success(request, libelle("referentiels.vues.kpi_retires", n=len(elements), referentiel=str(ref)))
        return
    if action == "deplacer":
        theme = theme_du_referentiel(ref, request.POST["theme_destination"]) if request.POST.get("theme_destination") else None
        ordre = ordre_suivant(ref, theme)
        n = 0
        for e in elements:
            if e.theme_id != (theme.pk if theme else None):
                _journal(request, e.kpi, f"Thème ({ref.code})", e.theme or "Sans thème", theme or "Sans thème")
                e.theme, e.ordre, ordre, n = theme, ordre, ordre + 1, n + 1
                e.save(update_fields=["theme", "ordre"])
        messages.success(request, libelle("referentiels.vues.kpi_deplaces", n=n, theme=str(theme) if theme else libelle("referentiels.contenu.lot.sans_theme")))
        return
    obligatoire = action == "obligatoire"
    n = 0
    for e in elements:
        if e.obligatoire != obligatoire:
            _journal(request, e.kpi, f"Obligatoire ({ref.code})", "non" if obligatoire else "oui", "oui" if obligatoire else "non")
            e.obligatoire, n = obligatoire, n + 1
            e.save(update_fields=["obligatoire"])
    messages.success(request, libelle("referentiels.vues.kpi_obligatoires" if obligatoire else "referentiels.vues.kpi_facultatifs", n=n, referentiel=str(ref)))


# ------------------------------------------------------------------------------- éditeur « Contenu » (actions JSON)
def _j(user, obj, champ, avant, apres):
    Journal.ecrire(user, "reglage_referentiels", obj, champ, avant, apres)


def _exiger_theme(t):
    if t is None:
        raise ValidationError(libelle("referentiels.vues.theme_inconnu"))
    return t


def _renumeroter(freres):
    from referentiel.models import Theme

    for n, x in enumerate(freres, start=1):
        if x.ordre != n:
            Theme.objects.filter(pk=x.pk).update(ordre=n)
            x.ordre = n


def ajouter_theme(user, ref, nom, parent=None):
    from referentiel.composition import code_theme, ordre_theme_suivant
    from referentiel.models import Theme

    nom = (nom or "").strip()[:150]
    if not nom:
        raise ValidationError(libelle("referentiels.vues.theme_nom_obligatoire"))
    t = Theme.objects.create(referentiel=ref, parent=parent, nom=nom, code=code_theme(ref, nom), ordre=ordre_theme_suivant(ref, parent))
    _j(user, t, "thème", "", f"{ref.code} › {nom} ajouté" + (f" dans « {parent} »" if parent else ""))
    return libelle("referentiels.vues.theme_ajoute_dans", nom=nom, parent=str(parent)) if parent else libelle("referentiels.vues.theme_ajoute", nom=nom)


def renommer_theme(user, t, nom):
    _exiger_theme(t)
    nom = (nom or "").strip()[:150]
    if not nom:
        raise ValidationError(libelle("referentiels.vues.theme_nom_obligatoire"))
    if nom == t.nom:
        return libelle("referentiels.vues.nom_inchange")
    _j(user, t, "nom", t.nom, nom)
    t.nom = nom
    t.save(update_fields=["nom"])
    return libelle("referentiels.vues.theme_renomme", nom=nom)


def deplacer_theme(user, t, parent=None, avant=None):
    """Range ``t`` dans ``parent`` (None : premier niveau), juste avant le thème ``avant`` (sinon à la fin)."""
    from referentiel.models import Theme

    _exiger_theme(t)
    if avant is not None:
        parent = avant.parent
    if parent is not None and (parent.pk == t.pk or parent.pk in _descendants(t)):
        raise ValidationError(libelle("referentiels.vues.theme_dans_lui_meme", theme=str(t)))
    if avant is not None and avant.pk == t.pk:
        return libelle("referentiels.vues.theme_inchange")
    ancien = t.parent
    freres = [x for x in Theme.objects.filter(referentiel=t.referentiel, parent=parent).order_by("ordre", "pk") if x.pk != t.pk]
    i = next((n for n, x in enumerate(freres) if avant is not None and x.pk == avant.pk), len(freres))
    if t.parent_id != (parent.pk if parent else None):
        t.parent = parent
        t.save(update_fields=["parent"])
        _j(user, t, "parent", ancien or "(premier niveau)", parent or "(premier niveau)")
    _renumeroter(freres[:i] + [t] + freres[i:])
    return libelle("referentiels.vues.theme_range_dans", theme=str(t), parent=str(parent)) if parent else libelle("referentiels.vues.theme_range_premier", theme=str(t))


def decaler_theme(user, t, sens):
    from referentiel.models import Theme

    _exiger_theme(t)
    freres = list(Theme.objects.filter(referentiel=t.referentiel, parent=t.parent).order_by("ordre", "pk"))
    i = [x.pk for x in freres].index(t.pk)
    j = i + sens
    if not 0 <= j < len(freres):
        return libelle("referentiels.vues.deja_premier") if sens < 0 else libelle("referentiels.vues.deja_dernier")
    freres[i], freres[j] = freres[j], freres[i]
    _renumeroter(freres)
    _j(user, t, "ordre", i + 1, j + 1)
    return libelle("referentiels.vues.theme_monte" if sens < 0 else "referentiels.vues.theme_descendu", theme=str(t))


def supprimer_theme(user, t):
    _exiger_theme(t)
    if t.enfants.exists() or t.elements.exists():
        raise ValidationError(libelle("referentiels.vues.theme_pas_vide_retirer", theme=str(t)))
    _j(user, t, "thème", f"{t.referentiel_id} › {t.nom}", "supprimé")
    t.delete()
    return libelle("referentiels.vues.theme_supprime", nom=t.nom)


class Confirmation(Exception):
    """L'action demande une confirmation (message à reposer) avant d'être appliquée."""


def lot_niveau(user, ref, elements, niveau, confirmer=False):
    """Niveau de saisie de plusieurs KPI : confirmation s'ils ont des réponses dans une campagne en cours, journal, un seul
    recalcul ; avertissement (sans bloquer) si un KPI calculé se retrouve sous le niveau d'une source non héritée."""
    from collecte import reglages as RG
    from collecte.calcul import recalculer
    from collecte.models import Campagne
    from referentiel.models import KPI, KPIFormule

    from . import niveaux as N

    niveaux = N.par_code()
    cible = niveaux.get(niveau or "")
    if cible is None:
        raise ValidationError(libelle("referentiels.vues.choisir_niveau"))
    a_changer = [e.kpi for e in elements if e.kpi.granularite_id != cible.code]
    n = len(elements)
    if not a_changer:
        return libelle("referentiels.vues.niveau_deja", n=n, niveau=cible.nom)
    en_cours = list(Campagne.objects.filter(statut__in=[Campagne.Statut.OUVERTE, Campagne.Statut.REVUE]).select_related("periode", "referentiel"))
    if not confirmer and en_cours:
        nb = sum(RG.reponses_ouvertes(k) for k in a_changer)
        if nb:
            noms = ", ".join(sorted({f"« {c.nom_complet} »" for c in en_cours}))
            raise Confirmation(libelle("referentiels.vues.niveau_confirmer", n=nb, campagnes=noms))
    for k in a_changer:
        Journal.ecrire(user, "reglage_kpi", k, "Granularité", str(niveaux.get(k.granularite_id) or k.granularite_id), cible.nom)
        k.granularite_id = cible.code
        k.save(update_fields=["granularite", "date_maj"])
    codes = [k.code for k in a_changer]
    faites = set()
    for c in en_cours:
        if c.periode_id not in faites:
            recalculer(c, codes)
            faites.add(c.periode_id)
    # un calculé placé sous le niveau d'une source non héritée n'a pas de valeur (le moteur ne descend pas)
    liens = KPIFormule.objects.filter(Q(kpi_calcule_id__in=codes) | Q(kpi_source_id__in=codes)).values_list("kpi_calcule_id", "kpi_source_id")
    concernes = {x for l in liens for x in l}
    kpis = {k.code: k for k in KPI.objects.filter(code__in=concernes).select_related("type_saisie")}
    avertissements = []
    for calc, src in sorted(set(liens)):
        kc, ks = kpis.get(calc), kpis.get(src)
        if not kc or not ks or ks.est_herite or kc.granularite_id not in niveaux or ks.granularite_id not in niveaux:
            continue
        if niveaux[kc.granularite_id].rang > niveaux[ks.granularite_id].rang:
            avertissements.append(libelle("referentiels.vues.niveau_avertissement", calcule=calc, niveau_calcule=niveaux[kc.granularite_id].nom,
                                          source=src, niveau_source=niveaux[ks.granularite_id].nom))
    m = len(a_changer)
    message = libelle("referentiels.vues.niveau_change", n=m, niveau=cible.nom)
    if avertissements:
        reste = libelle("referentiels.vues.niveau_et_autres", n=len(avertissements) - 3) if len(avertissements) > 3 else ""
        message += " " + libelle("referentiels.vues.niveau_attention", avertissements=" ".join(avertissements[:3]) + reste)
    return message


def lot_depuis(user, ref, elements, valeur, confirmer=False):
    """« Demandé depuis » de plusieurs KPI (``collecte.demande_depuis``) : aperçu d'abord (périodes
    touchées, cases créées, avertissements des sources), enregistré une fois confirmé ; refus avec un message."""
    from collecte import demande_depuis as DD

    nouveau = DD.lire_choix(ref, valeur)
    texte = DD.libelle_depuis(ref, nouveau)
    codes = [e.kpi_id for e in elements]
    p = DD.Prevision(ref, codes, nouveau)
    if not p.changes:
        return libelle("referentiels.depuis.deja", depuis=DD.phrase_depuis(ref, nouveau))
    if p.refus:
        raise ValidationError(" ".join(p.refus[:5]) + (" …" if len(p.refus) > 5 else ""))
    if not confirmer and (p.lignes or p.avertissements):
        raise Confirmation(libelle("referentiels.depuis.apercu", depuis=texte, effet=" ".join([p.resume()] + p.avertissements)))
    p = DD.changer(user, ref, codes, nouveau, confirmer=True)
    return libelle("referentiels.depuis.change", n=len(p.changes), depuis=texte, effet=" ".join([p.resume()] + p.avertissements))


def lot(user, ref, operation, codes, theme=None, niveau=None, confirmer=False, depuis=None):
    """Action sur plusieurs KPI cochés du référentiel : deplacer (vers ``theme`` ou sans thème), obligatoire, facultatif,
    retirer, niveau (de saisie), depuis (« demandé depuis »)."""
    from referentiel.composition import ordre_suivant
    from referentiel.models import ElementReferentiel

    elements = list(ElementReferentiel.objects.filter(referentiel=ref, kpi_id__in=codes).select_related("kpi", "theme"))
    if not elements:
        raise ValidationError(libelle("referentiels.vues.cocher_un"))
    n = len(elements)
    if operation == "retirer":
        for e in elements:
            _j(user, e.kpi, "Référentiel", f"{ref}", "(retiré)")
        ElementReferentiel.objects.filter(pk__in=[e.pk for e in elements]).delete()
        return libelle("referentiels.vues.kpi_retires", n=n, referentiel=str(ref))
    if operation == "deplacer":
        ordre = ordre_suivant(ref, theme)
        for e in elements:
            if e.theme_id != (theme.pk if theme else None):
                _j(user, e.kpi, f"Thème ({ref.code})", e.theme or "Sans thème", theme or "Sans thème")
                e.theme, e.ordre, ordre = theme, ordre, ordre + 1
                e.save(update_fields=["theme", "ordre"])
        return libelle("referentiels.vues.kpi_ranges", n=n, theme=str(theme) if theme else libelle("referentiels.contenu.lot.sans_theme"))
    if operation in ("obligatoire", "facultatif"):
        obligatoire = operation == "obligatoire"
        for e in elements:
            if e.obligatoire != obligatoire:
                _j(user, e.kpi, f"Obligatoire ({ref.code})", "non" if obligatoire else "oui", "oui" if obligatoire else "non")
                e.obligatoire = obligatoire
                e.save(update_fields=["obligatoire"])
        return libelle("referentiels.vues.lot_obligatoires" if obligatoire else "referentiels.vues.lot_facultatifs", n=n)
    if operation == "niveau":
        return lot_niveau(user, ref, elements, niveau, confirmer)
    if operation == "depuis":
        return lot_depuis(user, ref, elements, depuis, confirmer)
    raise ValidationError(libelle("referentiels.vues.action_inconnue"))
