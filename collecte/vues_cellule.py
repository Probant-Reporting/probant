"""Panneau de saisie d'une case (cellule), preuves, forçage et points à vérifier (sections 4.1 et 4.4).

Sorti de ``collecte/views.py`` (rangement sans changement de comportement), comme ``vues_coherence.py`` : ce module
importe ses aides depuis ``.views``, jamais l'inverse. ``ligne_html`` reste dans ``views.py`` (utilisé par ``attribuer``).
"""
import os
import re
from contextlib import ExitStack
from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.html import format_html
from django.utils import timezone
from django.views.decorators.http import require_POST

from espaces import contexte as ESP
from parametres import ia as IA
from parametres import langues as L
from parametres import libelles as LB
from parametres import niveaux as N
from parametres.libelles import libelle
from parametres.models import CategorieDescription, Instance
from referentiel.models import KPI, Organisation
from referentiel.plans import Plan

from . import reglages as R
from . import saisie as S
from .calcul import Calculateur, kpis_lus_avant
from .garde_requetes import reponse_inerte
from .sensibles import alerte_sensible, caches_ia
from .models import Alerte, Campagne, Preuve, Reponse
from .reponses_script import reponse_erreur
from .templatetags.collecte import arrondi, formater, nombre, separateurs
from .views import ligne_html
from .vues_communes import est_identifiant, est_script, identifiant, memoriser_session


def _au_dessus_cellule(campagne, kpi, org, reponse):
    """Cellule au-dessus de la granularité d'un KPI saisissable aux niveaux supérieurs : total calculé à partir du détail
    (avec la cause s'il est incomplet), et si une valeur saisie ici le remplace."""
    from .calcul import Calculateur

    calc = Calculateur(campagne.periode)
    total = calc._agreger(kpi, org, campagne.periode)
    texte = formater(total, kpi) if total is not None else ""
    return {"au_dessus": True, "total_detail": texte, "total_message": calc.message(kpi.code, org.id) if total is None else "",
            "saisie_ici": bool(reponse and not reponse.est_calculee and (reponse.valeur is not None or reponse.texte or reponse.non_applicable))}


@login_required
def cellule(request, campagne_id, kpi_id, org_id):
    """Panneau de saisie d'une cellule : définition, valeur, N/A, commentaire, preuves, historique."""
    campagne = get_object_or_404(Campagne.objects.select_related("referentiel", "periode"), pk=campagne_id)
    memoriser_session(request, "campagne", campagne.pk)
    kpi = get_object_or_404(KPI, pk=kpi_id)
    org = get_object_or_404(Organisation, pk=org_id)
    reponse = S.reponse_de(campagne, kpi, org)
    d = S.droits(request.user, campagne, kpi, org, reponse)
    if not d.voir:
        raise PermissionDenied(d.motif)
    ici = reverse("collecte:cellule", args=[campagne.pk, kpi.pk, org.pk])
    saisi, erreurs, succes = None, [], ""
    enregistre = False  # la saisie envoyée est en base (même si la validation qui suivait a été refusée)
    justif = {}  # explication d'une alerte envoyée depuis le panneau : alerte, message de succès ou erreur, texte refusé
    avant = None  # alertes à justifier de la case avant l'envoi (``nouvelles_alertes`` : celles apparues après)
    erreur_preuve = []  # fichier de preuve refusé (motif sous la zone de dépôt)

    if request.method == "POST" and request.POST.get("auto") == "1" and request.POST.get("action") == "enregistrer" and est_script(request):
        return _brouillon_auto(request, campagne, kpi, org)
    if request.method == "POST":
        action = request.POST.get("action")
        avant = {a.pk for a in _alertes_case(campagne, kpi, org) if _a_justifier(a)}
        pile = ExitStack()
        if action != "justifier":  # le recalcul qui suit l'écriture lit le catalogue avant le verrou d'écriture
            pile.enter_context(kpis_lus_avant())
        try:
            if action == "justifier":
                justif = _justifier(request, campagne, kpi, org)
            elif action in ("enregistrer", "valider"):
                saisi = {"valeur": request.POST.get("valeur", ""), "non_applicable": request.POST.get("non_applicable") == "on",
                         "commentaire": request.POST.get("commentaire", "")}
                refus = None
                # une seule transaction : personne ne modifie la case entre l'enregistrement et la validation (la
                # personne valide ce qu'elle vient d'enregistrer) ; une validation refusée garde la saisie
                with ESP.atomic():
                    S.enregistrer(request.user, campagne, kpi, org, **saisi, version_vue=request.POST.get("version"))
                    enregistre = True
                    if action == "valider":
                        try:
                            S.valider(request.user, campagne, kpi, org)
                        except ValidationError as e:
                            refus = e
                if refus is not None:
                    raise refus
                if action == "valider":
                    succes = libelle("saisie.cellule.msg.validee")
                else:
                    succes = libelle("saisie.cellule.msg.brouillon_enregistre")
                saisi = None
            elif action == "revenir_total":
                S.enregistrer(request.user, campagne, kpi, org, "", False, "")
                succes = libelle("saisie.cellule.msg.valeur_effacee")
            elif action == "brouillon":
                S.repasser_brouillon(request.user, campagne, kpi, org)
                succes = libelle("saisie.cellule.msg.repassee_brouillon")
            elif action == "a_saisir":
                S.remettre_a_saisir(request.user, campagne, kpi, org, version_vue=request.POST.get("version"))
                succes = libelle("saisie.cellule.msg.remise_a_saisir")
            elif action == "preuve":
                fichier = request.FILES.get("fichier")
                if not fichier:
                    raise ValidationError(libelle("saisie.erreur.choisir_fichier"))
                try:
                    S.ajouter_preuve(request.user, campagne, kpi, org, fichier)
                except OSError as x:  # disque plein, dossier en lecture seule : rien n'est enregistré, l'IT est prévenue
                    import logging

                    logging.getLogger("reporting.fichiers").error("Evidence file not saved: %s", x)
                    raise ValidationError(libelle("saisie.erreur.preuve_non_enregistree")) from x
                succes = libelle("saisie.cellule.msg.preuve_deposee")
            elif action in ACTIONS_FORCAGE:
                succes = _forcage(request, campagne, kpi, org, action)
            elif action == "retirer_preuve":
                p = get_object_or_404(Preuve, pk=identifiant(request.POST.get("preuve")), reponse__periode=campagne.periode,
                                      reponse__kpi=kpi, reponse__organisation=org)
                S.retirer_preuve(request.user, p, campagne)
                succes = libelle("saisie.cellule.msg.preuve_retiree")
            else:
                raise ValidationError(libelle("saisie.erreur.action_inconnue"))
        except ValidationError as e:
            erreurs = e.messages
            if action not in ("enregistrer", "valider"):
                saisi = None
        finally:
            pile.close()
        # fichier de preuve refusé : le motif s'affiche sous la zone de dépôt, pas dans « À vérifier » (il ne bloque pas
        # la validation)
        erreur_preuve, erreurs = (erreurs, []) if action == "preuve" else ([], erreurs)
        if not est_script(request):
            for m in erreurs + erreur_preuve:
                messages.error(request, m)
            if succes or justif.get("succes") or justif.get("info"):
                messages.success(request, succes or justif.get("succes") or justif["info"])
            if (not erreurs or saisi is None) and not justif.get("erreur"):
                return redirect(ici)
        reponse = S.reponse_de(campagne, kpi, org)
        d = S.droits(request.user, campagne, kpi, org, reponse)

    n1 = S.reponse_n1(campagne, kpi, org)  # rien quand la case n'est pas comparable (``saisie.cases_comparables``)
    e = None
    if reponse and n1 and kpi.est_numerique and not reponse.non_applicable and not n1.non_applicable:
        e = S.ecart(reponse.valeur, n1.valeur)  # pas d'écart sur un décompte de réponses oui / non ou liste
    sources, utilisations = R.sources_et_utilisations(kpi)
    ctx = {
        "campagne": campagne, "kpi": kpi, "org": org, "reponse": reponse, "droits": d, "n1": n1, "ecart": e,
        "statut": S.statut_affiche(reponse), "calculee": S.est_calculee(kpi, org, reponse, campagne), "version": S.version(reponse),
        "peut_na": Instance.courante().peut_repondre_na(request.user),  # rôles réglés dans Paramètres › Seuils de suivi
        "comparaison": S.libelle_comparaison(campagne), "cumul": S.cumule(campagne, kpi) and kpi.se_saisit_a(org),
        "saisi": saisi or {"valeur": "" if reponse and reponse.est_calculee else S.valeur_pour_saisie(reponse, kpi), "non_applicable": bool(reponse and reponse.non_applicable),
                           "commentaire": reponse.commentaire if reponse and not reponse.est_calculee else ""},
        "preuves": reponse.preuves.all() if reponse else [],
        "historique": [r for r in S.historique(kpi, org) if r.periode_id != campagne.periode_id],
        # ce qui bloque la validation (en lecture seule, l'écart avec N-1 n'y figure pas : son alerte reste une alerte à
        # justifier dans le panneau, au lieu d'un motif « Bloque la validation » sans action possible)
        "controles": [m for m in S.controles_validation(reponse, campagne, n1.valeur if n1 and not n1.non_applicable else None)
                      if d.modifier or libelle("saisie.msg.ecart_fragment", comparaison=S.libelle_comparaison(campagne)) not in m]
        if reponse and reponse.statut == Reponse.Statut.BROUILLON and not erreurs else [],
        "est_pourcentage": kpi.est_pourcentage,
        "definition": [(c, t) for c in CategorieDescription.objects.filter(affichee=True) if (t := kpi.texte_description(c.code))],
        "places": Plan(kpis=[kpi.code]).places(kpi.code),
        "categorie_principale": CategorieDescription.objects.values_list("code", flat=True).first(),
        "sources": _sources_cellule(campagne, org, sources), "erreurs": erreurs, "succes": succes, "ici": ici,
        "erreur_preuve": erreur_preuve, "taille_max_preuve_octets": settings.PREUVE_TAILLE_MAX,
        "admin": request.user.est_admin,
        # saisie refusée par le serveur et absente de la base : le formulaire montre ce qui a été tapé, pas encore
        # enregistré (le panneau pose la question avant de fermer)
        "enregistre": enregistre, "non_enregistre": bool(erreurs) and saisi is not None and not enregistre,
        # lecteur d'écran : les motifs du refus (encadré « À vérifier ») sont lus avec le champ qui reçoit le focus, et la
        # valeur refusée est marquée invalide (pas pour un conflit de version : la valeur elle-même est correcte)
        "erreurs_saisie": bool(erreurs) and saisi is not None,
        # conflit de version : enregistrer à nouveau remplacerait la saisie de l'autre personne, la question le dit
        "conflit": any(m.startswith(S.debut_conflit()) for m in erreurs),
    }
    ctx["valeur_refusee"] = ctx["non_enregistre"] and not ctx["conflit"]
    # case qui ne compte pas dans cette période (organisation pas encore ouverte, KPI pas demandé) : un encadré le dit, à la
    # place du point « À vérifier » ; sans valeur enregistrée, pas de statut « À saisir » non plus (la case n'existe pas ici).
    # Compte en lecture seule ou exercice clos : le motif de ``droits`` est autre, la mention est lue ici (valeur gardée)
    hors = None
    if d.hors_periode:
        hors = {"motif": d.motif, "lien": d.lien, "lien_cle": d.lien_cle}
    elif d.voir and S.a_une_valeur(reponse) and not ctx["calculee"]:
        motif, lien = S.organisation_pas_ouverte(request.user, campagne, org, valeur=True)
        if motif:
            hors = {"motif": motif, "lien": lien, "lien_cle": "saisie.msg.modifier_ouverture"}
    ctx["hors_periode"] = hors
    ctx["sans_statut"] = bool(d.hors_periode and ctx["statut"] == Reponse.Statut.A_SAISIR)
    if kpi.est_texte:  # réponse rédigée : limite de longueur, dite sous la zone de texte
        from . import markdown as MD

        ctx["texte_max"], ctx["texte_max_affiche"] = MD.TEXTE_MAX, nombre(MD.TEXTE_MAX, 0)
    if kpi.est_tableau:  # tableau : colonnes, options des listes et lignes saisies, dans la langue de la personne
        ctx["tableau"] = tableau_saisie(kpi, (ctx.get("saisi") or {}).get("valeur") or "")
    if ctx["cumul"]:
        ctx["cumul_detail"] = _cumul_cellule(campagne, kpi, org)
    if org.niveau_id != kpi.granularite_id and not ctx["cumul"] and N.rangs().get(org.niveau_id, 0) < N.rangs().get(kpi.granularite_id, 0):
        ctx["detail_agregat"] = _detail_agregat(campagne, kpi, org)
    if S.au_dessus(kpi, org) and not ctx["calculee"]:
        ctx.update(_au_dessus_cellule(campagne, kpi, org, reponse))
    if kpi.est_calcule:
        ctx["forcage"] = _forcage_contexte(request.user, campagne, kpi, org, reponse)
    alertes = _alertes_case(campagne, kpi, org)
    vals = [abs(r.valeur) for r in ctx["historique"] if r.valeur is not None and not r.non_applicable]
    plus = max(vals + [abs(reponse.valeur)] if reponse and reponse.valeur is not None else vals, default=0)
    ctx["n1_saisie"] = S.valeur_pour_saisie(n1, kpi) if n1 and not n1.non_applicable and n1.valeur is not None else ""
    ctx["historique_barres"] = [(r, int(abs(r.valeur) / plus * 100) if plus and r.valeur is not None and not r.non_applicable else 0)
                                for r in ctx["historique"]]
    # compte en lecture seule (lecteur, auditeur) : l'encadré de la page le dit déjà, « À vérifier » ne le répète pas
    ctx["points"] = _points_a_verifier(erreurs or ctx["controles"], bool(erreurs), alertes,
                                       "" if ctx["calculee"] or request.user.lecture_seule or d.hors_periode else d.motif, ctx["comparaison"], ctx["non_enregistre"],
                                       utilisateur=request.user, droits=d, reponse=reponse, justif=justif, ecart_case=e)
    ctx["justifiables"] = any(p.get("justifiable") for p in ctx["points"])
    # « Expliquer avec l'IA » (docs/ai_socket.md) : prise et usage allumés, rôles qui écrivent ; sur une alerte dont la
    # personne peut ouvrir la fiche (``fiche`` du point), jamais un bouton qui mènerait à « Accès refusé »
    ctx["ia_alertes"] = (not request.user.lecture_seule and any(p.get("ia") for p in ctx["points"])
                         and IA.bouton_visible("expliquer_alerte"))
    if ctx["ia_alertes"]:  # KPI sensibles et dérivés, réglage éteint : pas de bouton sur une alerte qui en cite un
        caches = caches_ia()
        for p in ctx["points"]:
            p["ia"] = p.get("ia") and not alerte_sensible(p["alerte"], caches)
        ctx["ia_alertes"] = any(p.get("ia") for p in ctx["points"])
    ctx["info_justif"] = justif.get("info", "")  # explication envoyée pour une alerte corrigée entre-temps
    if est_script(request):
        html = render_to_string("collecte/_panneau.html", ctx, request=request)
        if request.method == "POST":
            cle, ligne = ligne_html(request, campagne, kpi, org)
            # alertes apparues avec cet envoi (nouvelle alerte, ou alerte rouverte) : « Valider et suivant » s'arrête (E6)
            nouvelles = sorted({a.pk for a in alertes if _a_justifier(a)} - (avant or set()))
            # explication d'une alerte corrigée entre-temps : rien d'enregistré, le panneau reste ouvert sur le message
            ok = not erreurs and not erreur_preuve and not justif.get("erreur") and not justif.get("info")
            return JsonResponse({"html": html, "lignes": {cle: ligne}, "ok": ok, "enregistre": enregistre, "nouvelles_alertes": nouvelles})
        return JsonResponse({"html": html})
    return render(request, "collecte/cellule.html", ctx)


def tableau_saisie(kpi, texte):
    """Colonnes (libellé, type, options affichées des listes) et lignes [[{col, v}]] d'une réponse en tableau, les valeurs
    de liste traduites dans la langue courante (le serveur relit une valeur écrite dans n'importe quelle langue)."""
    from parametres.models import TypeReponse

    from . import tableaux as T

    cols = T.colonnes(kpi.type_reponse)
    listes = {t.code: t for t in TypeReponse.objects.filter(code__in={c.liste for c in cols if c.liste})}
    affichage = {c.code: dict(listes[c.liste].choix_traduits()) if c.liste in listes else {} for c in cols}
    colonnes = [{"code": c.code, "libelle": c.libelle(), "type": c.type, "options": list(affichage[c.code].values())} for c in cols]
    decimale = separateurs()[1]  # nombres affichés avec la virgule de la langue (relus dans n'importe quelle écriture)
    lignes = []
    for brute in T.lignes_brutes(texte):
        brute = (brute + [""] * len(cols))[:len(cols)]
        lignes.append([{"col": col, "v": v.replace(".", decimale) if c.type == "nombre" else affichage[c.code].get(v, v)}
                       for c, col, v in zip(cols, colonnes, brute)])
    return {"colonnes": colonnes, "lignes": lignes, "vide": [{"col": col, "v": ""} for col in colonnes]}


def _brouillon_auto(request, campagne, kpi, org):
    """Enregistrement automatique du brouillon tapé dans le panneau : le même chemin que
    « Enregistrer le brouillon » (droits, lecture de la valeur, version, journal : une ligne par champ changé, jamais réécrite), jamais une validation, sans redessiner
    le panneau. Refusé, et dit, pour une valeur validée (elle ne change que sur « Enregistrer la modification ») et pour un
    séparateur ambigu (« 1,234 » : la personne choisit en enregistrant). Réponse : ``ok``, la nouvelle ``version``, le
    statut, l'heure, la ligne de la liste ; ou ``motif`` (et ``conflit``)."""
    from .templatetags.collecte import statut_libelle

    valeur = request.POST.get("valeur", "")
    na = request.POST.get("non_applicable") == "on"
    refusee = False  # la valeur elle-même est refusée (marquée invalide), pas l'envoi
    try:
        reponse = S.reponse_de(campagne, kpi, org)
        S.exiger(S.droits(request.user, campagne, kpi, org, reponse), "modifier")  # lecture seule, saisie fermée : refus 403
        if not na:
            try:
                S.lire_reponse(valeur, kpi)
            except ValidationError:
                refusee = True
                raise
        if kpi.est_numerique and not na and S.separateur_ambigu(valeur) \
                and valeur.strip() != S.valeur_pour_saisie(reponse, kpi, L.saisie()):  # affichée dans la langue du formulaire
            raise ValidationError(libelle("saisie.auto.ambigu", saisie=valeur.strip()))
        with kpis_lus_avant(), ESP.atomic():
            reponse = S.enregistrer(request.user, campagne, kpi, org, valeur, na, request.POST.get("commentaire", ""),
                                    version_vue=request.POST.get("version"), auto=True)
    except ValidationError as e:
        conflit = any(m.startswith(S.debut_conflit()) for m in e.messages)
        motif = " ".join(e.messages)
        if conflit:  # le message complet est long : le repère dit qui et à quelle heure ; l'enregistrement explicite dit le reste
            r = S.reponse_de(campagne, kpi, org)
            quand = timezone.localtime(r.date_maj) if r else timezone.localtime()
            motif = libelle("saisie.auto.conflit", qui=(r and r.saisi_par) or libelle("saisie.msg.autre_personne"), heure=f"{quand:%H:%M}")
        # refus de l'enregistrement automatique : statut 200, le panneau lit « motif » et garde la saisie à l'écran
        return reponse_erreur(motif, status=200, motif=motif, conflit=conflit, valeur_refusee=refusee)
    cle, ligne = ligne_html(request, campagne, kpi, org)
    statut = S.statut_affiche(reponse)
    return JsonResponse({"ok": True, "version": S.version(reponse), "statut": statut, "statut_libelle": str(statut_libelle(statut)),
                         "heure": f"{timezone.localtime():%H:%M}", "lignes": {cle: ligne}})


@login_required
@require_POST
def apercu_texte(request):
    """Aperçu d'une réponse rédigée (bouton « Aperçu » de la saisie) : le HTML du rendu Markdown sûr, le même que
    l'affichage (collecte.markdown : tout HTML écrit est échappé). Rien n'est enregistré."""
    from . import markdown as MD

    texte = request.POST.get("texte", "")[:MD.TEXTE_MAX]
    html = MD.rendu(texte, 4) or format_html('<p class="discret">{}</p>', libelle("saisie.md.vide"))
    return JsonResponse({"html": str(html)})


ACTIONS_FORCAGE = ("forcer", "accepter_forcage", "refuser_forcage", "retirer_forcage", "revenir_calcul")


def _forcage(request, campagne, kpi, org, action):
    """Actions du panneau sur la valeur forcée d'un KPI calculé ; renvoie le message de succès."""
    from . import forcage as FO

    if action == "forcer":
        d = FO.demander(request.user, campagne, kpi, org, request.POST.get("valeur_forcee", ""),
                        request.POST.get("na_forcee") == "on", request.POST.get("justification", ""))
        return libelle("saisie.forcage.msg.appliquee" if d.statut == d.Statut.ACCEPTEE else "saisie.forcage.msg.demandee")
    if action == "revenir_calcul":
        FO.revenir_au_calcul(request.user, campagne, kpi, org, request.POST.get("motif", ""))
        return libelle("saisie.forcage.msg.revenue")
    demande = FO.en_attente(campagne.periode, kpi, org)
    if demande is None or str(demande.pk) != request.POST.get("demande"):
        raise ValidationError(libelle("saisie.forcage.msg.deja_traitee"))
    if action == "accepter_forcage":
        FO.accepter(request.user, campagne, demande)
        return libelle("saisie.forcage.msg.acceptee")
    if action == "refuser_forcage":
        FO.refuser(request.user, campagne, demande, request.POST.get("motif", ""))
        return libelle("saisie.forcage.msg.refusee")
    FO.retirer(request.user, campagne, demande)
    return libelle("saisie.forcage.msg.retiree")


def _forcage_contexte(utilisateur, campagne, kpi, org, reponse):
    """Ce que le panneau montre d'une case de KPI calculé : valeur forcée en place, demande en attente, ce que la
    personne peut faire."""
    from . import forcage as FO

    appliquee = FO.appliquee(campagne.periode, kpi, org) if reponse is not None and reponse.origine == Reponse.Origine.FORCEE else None
    attente = FO.en_attente(campagne.periode, kpi, org)
    trancher = FO.peut_trancher(utilisateur, campagne, kpi, org)

    def texte(d, calculee=False):
        if d is None:
            return ""
        if calculee:
            return formater(d.valeur_calculee, kpi) if d.valeur_calculee is not None else ""
        return "N/A" if d.non_applicable else formater(d.valeur, kpi)

    return {"forcee": reponse is not None and reponse.origine == Reponse.Origine.FORCEE, "appliquee": appliquee,
            "appliquee_valeur": texte(appliquee), "appliquee_calcul": texte(appliquee, True),
            "attente": attente, "attente_valeur": texte(attente), "attente_calcul": texte(attente, True),
            "trancher": trancher, "demander": FO.peut_demander(utilisateur, campagne, kpi, org),
            "demandeur": attente is not None and attente.demandeur_id == utilisateur.pk,
            "pourcentage": kpi.est_pourcentage}


def _alertes_case(campagne, kpi, org):
    """Alertes d'une case, hors corrigées : les siennes, et celles des règles entre KPI qui citent son KPI dans la même
    organisation."""
    return [a for a in Alerte.objects.filter(Q(kpi=kpi) | Q(controle=Alerte.Controle.REGLE), campagne=campagne, organisation=org)
            .exclude(statut=Alerte.Statut.CORRIGEE).select_related("regle", "campagne", "justifie_par")
            if a.kpi_id == kpi.pk or kpi.pk in a.kpis_concernes.split()]


def _a_justifier(alerte):
    from .coherence import a_justifier

    return a_justifier(alerte)


def _justifier(request, campagne, kpi, org):
    """« Expliquer pourquoi la valeur est juste » : justification d'une alerte de la case depuis le panneau, comme sur la page
    Cohérence (statut « justifiée », Journal). Droits : la règle de la page Cohérence ; une alerte d'une autre case :
    404. Une erreur (texte vide, statut qui ne le permet plus) reste sous le champ, avec le texte tapé."""
    from . import coherence as CO

    pk = request.POST.get("alerte", "")
    if not est_identifiant(pk):
        raise Http404(libelle("saisie.erreur.alerte_inconnue"))
    a = get_object_or_404(Alerte.objects.select_related("campagne", "regle"), Q(kpi=kpi) | Q(controle=Alerte.Controle.REGLE),
                          pk=pk, campagne=campagne, organisation=org)
    if a.kpi_id != kpi.pk and kpi.pk not in a.kpis_concernes.split():
        raise Http404(libelle("saisie.erreur.alerte_autre_case"))
    if not CO.peut_voir(request.user, a):
        raise PermissionDenied(libelle("saisie.erreur.justifier_interdit"))
    refus = CO.motif_justification_refusee(request.user, a)  # calcul impossible, campagne clôturée : même règle et
    if refus:  # même explication que la fiche et l'outil MCP
        raise PermissionDenied(refus)
    if a.statut == Alerte.Statut.CORRIGEE:  # la valeur a changé entre-temps : l'alerte n'est plus affichée, on le dit
        return {"alerte": a.pk, "info": libelle("saisie.justif.alerte_corrigee")}
    texte = request.POST.get("justification", "")
    try:
        CO.traiter(request.user, a, "justifier", texte)
    except ValidationError as e:
        return {"alerte": a.pk, "erreur": " ".join(e.messages), "texte": texte}
    return {"alerte": a.pk, "succes": libelle("saisie.justif.enregistree")}


def _constat_ecart(a, comparaison, e=None):
    """Écart avec la période de comparaison en clair, à partir de la valeur et de la référence de l'alerte (« 160
    salariés, contre 100 salariés en 2025 : +60,0 % »), quel que soit le texte de son message (ancien ou nouveau), arrondi
    comme la colonne « Écart » de la liste et la comparaison du panneau (une décimale, séparateur de milliers). ``e`` :
    écart actuel de la case (fraction), s'il est connu."""
    from . import coherence as CO
    from .templatetags.collecte import ecart as ecart_lisible

    ref, valeur = CO.texte_alerte(a, "reference"), CO.texte_alerte(a, "valeur")
    morceaux = re.split(r"\s*:\s+", ref, maxsplit=1)  # « 2025 : 100 salariés » (« 2025: 100 salariés » dans une autre langue)
    if len(morceaux) == 2:
        ref = libelle("saisie.pav.reference_en", valeur=morceaux[1], periode=morceaux[0])
    if e is not None:
        return libelle("saisie.pav.constat_ecart_valeur", valeur=valeur, reference=ref or comparaison, ecart=ecart_lisible(e))
    return libelle("saisie.pav.constat_ecart", valeur=valeur, reference=ref or comparaison)


def _points_a_verifier(motifs, sont_erreurs, alertes, motif_lecture, comparaison="N-1", non_enregistre=False,
                       utilisateur=None, droits=None, reponse=None, justif=None, ecart_case=None):
    """Un seul encadré : ce qui bloque la validation, puis les alertes de cohérence, sans doublon. ``non_enregistre`` :
    la saisie envoyée a été refusée et rien n'est en base, l'étiquette le dit (« Non enregistré »).

    Chaque point issu d'un motif (``motif``) ne porte que du texte (il est lu avec la valeur refusée). Une alerte à
    justifier que la personne voit (règle de la page Cohérence) propose « Expliquer pourquoi la valeur est juste »
    (``justifiable``, jamais pour un calcul impossible), prérempli avec sa justification rejetée (sans la décision de
    l'admin) ou, sinon, avec le commentaire de la saisie (proposé, un clic l'enregistre) ; un écart avec N-1 renvoie
    au commentaire quand la personne peut modifier la saisie (``vers_commentaire``). ``ecart_case`` : écart actuel
    de la case avec la période de comparaison (fraction), ajouté au constat d'un écart avec N-1."""
    from . import coherence as CO

    justif = justif or {}
    points, restantes = [], list(alertes)
    ecart = libelle("saisie.msg.ecart_fragment", comparaison=comparaison)
    for m in motifs:
        liee = next((a for a in restantes if (a.controle == Alerte.Controle.ECART_N1 and ecart in m)
                     or (a.regle and libelle("saisie.guillemets", texte=a.regle.nom_affiche) in m)), None)
        if liee:
            restantes.remove(liee)
        a_completer = not (ecart in m or (liee and liee.regle))
        titre = (libelle("saisie.pav.titre_ecart", comparaison=comparaison) if ecart in m
                 else libelle("saisie.pav.titre_regle", regle=liee.regle.nom_affiche) if liee and liee.regle else libelle("saisie.pav.a_completer"))
        if a_completer:
            detail = m
        elif ecart in m:
            detail = (_constat_ecart(liee, comparaison, ecart_case) + " · " if liee else "") + m.replace(
                libelle("saisie.msg.ecart_debut", comparaison=comparaison), libelle("saisie.msg.ecart_au_dela"))
        else:
            detail = liee.regle.description_affichee or m
        if m.startswith(S.debut_conflit()):  # saisie simultanée : rien n'a été écrasé
            titre, etiquette = libelle("saisie.pav.modifiee_entre_temps"), libelle("saisie.pav.non_enregistre")
        else:
            etiquette = libelle("saisie.pav.non_enregistre" if non_enregistre else "saisie.pav.bloque_validation")
        points.append({"niveau": "bloque", "etiquette": etiquette, "titre": titre, "detail": detail, "alerte": liee, "motif": True})
    for a in restantes:
        detail = _constat_ecart(a, comparaison, ecart_case) + "." if a.controle == Alerte.Controle.ECART_N1 and a.valeur else CO.constat_lisible(a)
        points.append({"niveau": "alerte" if a.a_traiter else "info", "etiquette": LB.choix(a, "statut"),
                       "titre": LB.choix(a, "controle"), "detail": detail, "alerte": a, "motif": False})
    if utilisateur is not None:
        modifier = bool(droits and droits.modifier)
        cases = None  # cases du périmètre de la personne, lues une seule fois (règle de la page Cohérence)
        # seulement les KPI des alertes affichées : même réponse, sans lire tout le catalogue à chaque ouverture
        cites = {k for p in points if p["alerte"] is not None
                 for k in [p["alerte"].kpi_id, *p["alerte"].kpis_concernes.split()] if k}
        for p in points:
            a = p["alerte"]
            if a is None:
                continue
            if cases is None and not (utilisateur.voit_tout and utilisateur.orgs_permises() is None):
                cases = {(k.pk, o.pk) for k, o in S.cellules(utilisateur, campagne=a.campagne, kpi_ids=cites)}
            voit = CO.peut_voir(utilisateur, a, cases)
            p["fiche"] = voit  # jamais de lien vers une fiche refusée (« Accès refusé »)
            # « Expliquer avec l'IA » : jamais sur un calcul impossible ; KPI sensibles : relus dans la vue, seulement
            # quand la prise est visible (aucune requête de plus sinon)
            p["ia"] = voit and CO.explicable_par_ia(a, frozenset())
            p["seule_rse"] = not voit and CO.a_justifier(a)
            ecart_n1 = a.controle == Alerte.Controle.ECART_N1
            p["vers_commentaire"] = ecart_n1 and modifier and a.a_traiter
            refus = CO.motif_justification_refusee(utilisateur, a)  # calcul impossible, campagne clôturée
            p["justifiable"] = (not p["motif"] and voit and CO.a_justifier(a) and not p["vers_commentaire"] and not refus
                                and a.statut in CO.TRANSITIONS["justifier"][0] and not utilisateur.lecture_seule)
            # alerte encore à traiter qui ne se justifie pas : la même explication que la fiche et l'outil MCP
            p["non_justifiable"] = refus if voit and a.a_traiter and not p["motif"] else ""
            if a.statut == Alerte.Statut.JUSTIFIEE and a.justification:
                p["justification"] = a.justification
            admin = a.justification.split("\n" + libelle("saisie.coherence.admin_ajout", L.defaut(), texte=""), 1)
            if a.statut == Alerte.Statut.REJETEE and len(admin) == 2:
                p["motif_rejet"] = admin[1]
            if justif.get("alerte") == a.pk and justif.get("erreur"):
                p["erreur"] = justif["erreur"]  # sous le champ (ou seule, si l'alerte ne se justifie plus)
            if p["justifiable"]:
                # la même case à justifier dans un autre référentiel de la même période ; une explication ne
                # vaut que pour sa campagne, on le signale
                p["aussi"] = sorted({str(x.campagne.referentiel) for x in Alerte.objects.filter(
                    CO.A_JUSTIFIER, kpi_id=a.kpi_id, organisation_id=a.organisation_id, controle=a.controle, regle_id=a.regle_id,
                    campagne__periode_id=a.campagne.periode_id).exclude(campagne_id=a.campagne_id)
                    .select_related("campagne__referentiel")})
                if justif.get("alerte") == a.pk and "texte" in justif:
                    p["texte"] = justif["texte"]
                elif a.statut == Alerte.Statut.REJETEE and a.justification:  # reprise sans la décision de l'admin
                    p["texte"], p["reprise"] = admin[0].strip(), True
                # (une alerte rouverte parce que la valeur a changé garde son ancienne justification en base, qui ne vaut
                # plus : on propose le commentaire, comme pour une nouvelle alerte)
                elif reponse is not None and reponse.commentaire.strip() and not reponse.est_calculee:
                    p["texte"], p["proposition"] = reponse.commentaire.strip(), True
            if justif.get("alerte") == a.pk and justif.get("succes"):
                p["succes"] = justif["succes"]
    if motif_lecture:
        points.insert(0, {"niveau": "info", "etiquette": libelle("saisie.pav.lecture_seule"), "titre": "", "detail": motif_lecture, "alerte": None,
                          "motif": True})
    return points


def _sources_cellule(campagne, org, sources):
    """Sources d'un KPI calculé avec leur valeur pour l'organisation (vue « résultat et composantes ») : [(KPI, décalage,
    réponse, organisation où elle se lit)]. Sous sa granularité, un paramètre hérité (facteur d'émission) se lit dans
    l'organisation qui le porte : l'ancêtre de son niveau, ou l'organisation elle-même faute d'un tel ancêtre (CALC-09)."""
    if not sources:
        return []
    from referentiel.models import porteur_herite

    from .periodes import Calendrier

    cal = Calendrier()
    periodes = {d: cal.resoudre(campagne.periode, d) for _, d in sources}
    rangs, arbres, ou = N.rangs(), {}, {}
    for k, decalage in sources:
        if k.est_herite and rangs.get(org.niveau_id, 0) > rangs.get(k.granularite_id, 0):
            # arbre de la période de la source (celui de sa clôture pour un exercice clos ou rouvert « garder » ; celui
            # du jour où la source a été figée par une campagne clôturée de la période)
            q = periodes[decalage] or campagne.periode
            if (q.pk, k.code) not in arbres:
                arbres[(q.pk, k.code)] = S.arbre_organisations(q, k.code)
            arbre = arbres[(q.pk, k.code)]
            if org.id in arbre:
                ou[k.code] = porteur_herite(arbre[org.id], k.granularite_id, rangs, arbre)
    cles = {(k.code, ou.get(k.code, org).id) for k, _ in sources}
    reponses = {(r.kpi_id, r.organisation_id, r.periode_id): r for r in Reponse.objects.filter(
        organisation_id__in={o for _, o in cles}, kpi_id__in=[k.code for k, _ in sources], periode__in=[p for p in periodes.values() if p])
        if (r.kpi_id, r.organisation_id) in cles}
    sortie = []
    for k, decalage in sources:
        o = ou.get(k.code, org)
        sortie.append((k, decalage, reponses.get((k.code, o.id, periodes[decalage].pk)) if periodes[decalage] else None, o))
    return sortie


def _detail_agregat(campagne, kpi, org):
    """Arbre des valeurs qui composent un agrégat : [(organisation, réponse, sous-arbre)], des enfants directs jusqu'au
    niveau de saisie (une valeur saisie au-dessus de la granularité arrête la descente)."""
    if kpi.methode_agregation not in (KPI.Agregation.SOMME, KPI.Agregation.DECOMPTE):
        return []
    rangs = N.rangs()
    rang_k = rangs.get(kpi.granularite_id, 0)
    reponses = {r.organisation_id: r for r in Reponse.objects.filter(periode=campagne.periode, kpi=kpi)}
    # organisations ouvertes pendant la période (une organisation fermée compte pour les périodes où elle était ouverte,
    #) ; sans valeur, une organisation active est listée avec une valeur vide, même sans rien à
    # saisir dessous ; une organisation fermée n'est listée que si la somme la compte (quelque
    # chose à saisir sous elle et au moins une valeur sur la période)
    calc = Calculateur(campagne.periode)
    p = calc.periode
    detail = calc._avec_detail(rang_k, p, kpi.code)  # arbre que suit le KPI (figé par une campagne clôturée : le sien)

    def a_valeur(r):
        return r is not None and (r.non_applicable or r.valeur is not None or bool(r.texte))

    def compte(e):
        # même règle que la somme (``Calculateur.compte_sans_valeur``), plus toute organisation active
        return a_valeur(reponses.get(e.id)) or e.actif or calc.compte_sans_valeur(kpi, e, p, detail)


    def part(r, total):
        if r is None or r.valeur is None or r.non_applicable or not total or kpi.methode_agregation != KPI.Agregation.SOMME:
            return None
        return max(0, min(100, int(arrondi(float(r.valeur / total) * 100))))

    def niveau(parent):
        """Enfants d'une organisation ; la part de chacun se rapporte à la somme des valeurs connues du niveau."""
        liste = sorted((e for e in calc.enfants(parent.id, p, kpi.code) if rangs.get(e.niveau_id, 0) <= rang_k and compte(e)),
                       key=lambda x: (x.rang, x.nom))
        total = sum((reponses[e.id].valeur for e in liste if e.id in reponses and reponses[e.id].valeur is not None
                     and not reponses[e.id].non_applicable), Decimal(0))
        return [noeud(e, total) for e in liste]

    def noeud(o, total):
        r = reponses.get(o.id)
        bas = rangs.get(o.niveau_id, 0) >= rang_k or (r is not None and not r.est_calculee)
        return {"org": o, "r": r, "sous": [] if bas else niveau(o), "part": part(r, total),
                "saisi_ici": r is not None and not r.est_calculee and rangs.get(o.niveau_id, 0) < rang_k}

    return niveau(org)


detail_agregat = _detail_agregat  # même détail pour les contrôles hors du module (qa/calculation_fuzz.py --pages)


def _cumul_cellule(campagne, kpi, org):
    """Périodes courtes qui composent la valeur cumulée (ex. les 12 mois d'une année) : [(libellé, réponse)]."""
    from .periodes import Calendrier, libelle

    f = S.frequences(campagne).get(kpi.code)
    cal = Calendrier()
    debuts = cal.contenues(campagne.periode, f)
    periodes = [(d, cal.trouver(f, d)) for d in debuts]
    reponses = {r.periode_id: r for r in Reponse.objects.filter(kpi=kpi, organisation=org, periode__in=[p for _, p in periodes if p])}
    return [(str(p) if p else libelle(f, d), reponses.get(p.pk) if p else None) for d, p in periodes]


@login_required
def preuve(request, pk):
    p = get_object_or_404(Preuve.objects.select_related("reponse__periode", "reponse__kpi", "reponse__organisation"), pk=pk)
    r = p.reponse
    campagne = S.campagne_de(r)
    if campagne is None or not S.droits(request.user, campagne, r.kpi, r.organisation, r).voir:
        raise PermissionDenied(libelle("saisie.erreur.preuve_hors_perimetre"))
    # type d'après le fichier rangé (extension vérifiée au dépôt, contenu compris), jamais d'après le nom affiché : un nom
    # en « .html » (base restaurée, nom modifié) ne fait pas ouvrir une page dans l'outil ; autre type : téléchargé
    types = {"pdf": "application/pdf", "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png"}
    type_ = types.get(os.path.splitext(p.fichier.name)[1].lower().lstrip("."))
    reponse = FileResponse(p.fichier.open("rb"), as_attachment=type_ is None, filename=p.nom_fichier,
                           content_type=type_ or "application/octet-stream")
    reponse["Cache-Control"] = "private, no-store"  # document confidentiel : ni proxy partagé, ni copie sur le disque du poste
    return reponse_inerte(reponse)  # contenu actif déguisé sans effet ; PDF sans « sandbox » : s'ouvre dans tout navigateur
