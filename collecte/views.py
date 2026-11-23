"""Pages de l'outil : saisie par organisation, « Pour moi », tableau de bord, référentiel (sections 4.1, 4.4, 4.5).

Le panneau de saisie et la fiche KPI s'ouvrent par-dessus la page (requêtes ``fetch``) ; sans JavaScript,
les mêmes adresses affichent une page complète.
"""
import json
from itertools import groupby

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from parametres import libelles as LB
from parametres.libelles import libelle
from parametres.models import Instance
from referentiel.models import KPI, Attribution, Organisation, Referentiel, Utilisateur
from referentiel.plans import Plan

from . import relances as RL
from . import saisie as S
from .models import Campagne, Reponse
from .reponses_script import reponse_erreur
from .templatetags.collecte import arrondi, avatar_infos
from .vues_communes import campagne_affichee, corps_envoye, est_identifiant, est_script, exiger_admin, identifiant, memoriser_session


STATUTS_FILTRE = [Reponse.Statut.A_SAISIR, Reponse.Statut.BROUILLON, Reponse.Statut.VALIDE]  # libellés : choix.reponse.statut.*


def groupes_campagnes(utilisateur):
    """[(référentiel, [campagnes])] pour le sélecteur « Référentiel » puis « Période » : les référentiels de la personne,
    leurs campagnes de la plus récente à la plus ancienne."""
    return [(r, cs) for r in S.referentiels_de(utilisateur) if (cs := S.campagnes_proposees(utilisateur, r))]


def referentiel_choisi(request):
    """Référentiel choisi dans le sélecteur (paramètre « ref », sinon mémorisé dans la session) ; None = tous."""
    if "ref" in request.GET:
        request.session["referentiel"] = request.GET.get("ref", "")
    code = request.session.get("referentiel", "")
    r = Referentiel.objects.filter(pk=code, actif=True).first() if code else None
    if code and r is None:
        request.session["referentiel"] = ""
    if r is not None and "ref" in request.GET:
        memoriser_referentiel(request, r)
    return r


def memoriser_referentiel(request, r):
    """Même choix partout : un référentiel choisi dans une page d'administration devient celui des autres pages (la
    campagne affichée passe à sa campagne en cours si elle était d'un autre référentiel)."""
    request.session["referentiel"] = r.pk
    actuelle = Campagne.objects.filter(pk=request.session.get("campagne") or 0).first()
    if actuelle is None or actuelle.referentiel_id != r.pk:
        c = S.campagne_courante(r)
        if c is not None:
            request.session["campagne"] = c.pk


def plan_de(request):
    """Plan du référentiel choisi (ou de tous les référentiels actifs)."""
    return Plan(referentiel_choisi(request))


def _sections(lignes, niveau1, niveau2, tri):
    """[(titre, [(sous-titre, lignes)])] : sections repliables à deux niveaux."""
    lignes = sorted(lignes, key=tri)
    return [(t, [(st, list(g2)) for st, g2 in groupby(list(g1), key=niveau2)]) for t, g1 in groupby(lignes, key=niveau1)]


def _par_theme(lignes, plan):
    """Sections par thème du référentiel (sommet de l'arbre), sous-sections par thèmes en dessous, dans la langue
    de l'utilisateur et l'ordre du référentiel."""
    return _sections(lignes, lambda l: plan.titres(l.kpi.code)[0], lambda l: plan.titres(l.kpi.code)[1], S.ordre(plan))


def _par_organisation(lignes, plan):
    tri = S.ordre(plan)
    return _sections(lignes, lambda l: l.organisation.nom, lambda l: plan.titres(l.kpi.code)[0],
                     lambda l: (S.cle_arbre(l.organisation), tri(l)))


LIGNES_OUVERTES = 200  # Pour moi : au-delà, seules les premières sections sont ouvertes 


def _sections_ouvertes(groupes, limite=None):
    """Pour moi d'une longue liste (validateur : plus de 600 lignes dans un grand référentiel) : nombre de sections ouvertes de chaque
    groupe de sections (un par référentiel sur la vue « Tout ce qui m'est attribué »), dans l'ordre de la page, pour
    montrer environ ``limite`` lignes ; les suivantes sont repliées. La première section est toujours ouverte, une
    section qui dépasserait la limite reste repliée, et toutes celles d'après aussi. None : la liste tient, tout est ouvert."""
    limite = LIGNES_OUVERTES if limite is None else limite
    tailles = [[sum(len(lignes) for _, lignes in sous) for _, sous in g] for g in groupes]
    if sum(sum(t) for t in tailles) <= limite:
        return None
    ouvertes, montrees, plein = [], 0, False
    for t in tailles:
        n = 0
        for taille in t:
            if plein or (montrees and montrees + taille > limite):
                plein = True
                break
            montrees += taille
            n += 1
        ouvertes.append(n)
    return ouvertes


def comptes_json(request, validateurs=False):
    """Comptes proposés dans le sélecteur de SPOC (admin seulement) : liste écrite dans la page par json_script
    (échappée : un nom ne ferme jamais la balise). ``validateurs`` : choix Validateurs des Attributions, seulement les
    validateurs et administrateurs actifs."""
    if not request.user.est_admin:
        return []
    if validateurs:
        from .administration import personnes_validatrices

        comptes = personnes_validatrices().order_by("first_name", "last_name", "email")
    else:
        comptes = (Utilisateur.ecrivains().filter(is_active=True)
                   .order_by("first_name", "last_name", "email"))  # un lecteur ou un auditeur ne saisit rien : jamais SPOC
    return [{"id": u.id, "nom": str(u), "email": u.email, "role": LB.choix(u, "role"), **avatar_infos(u)} for u in comptes]


def _contexte_liste(request, campagne, lignes, etat, org=None):
    """Contexte commun de Saisie et Pour moi : compteurs des pastilles (lignes affichées) et ``etat``, ce qui reste à
    faire (``S.Reste`` : tout le périmètre sur Saisie, avec ``org`` l'organisation affichée ; la liste sur Pour moi),
    dont le bandeau tire sa phrase."""
    compteur = S.Compteur()
    for l in lignes:
        if l.attendue:
            compteur.ajouter(l)
    lecture = S.lecture_seule(request.user, campagne)
    return {
        "campagne": campagne, "groupes_campagnes": groupes_campagnes(request.user), "compteur": compteur, "etat": etat,
        "bandeau": _bandeau(etat, compteur, org, request.user.est_admin, lecture),
        "comparaison": S.libelle_comparaison(campagne),
        "nb_alertes": sum(1 for l in lignes if l.alertes and not l.calculee),
        "statuts": [(s, LB.choix_valeur(Reponse, "statut", s)) for s in STATUTS_FILTRE], "admin": request.user.est_admin, "comptes_json": comptes_json(request),
        "lecture_seule": lecture,
    }


def _n(cle, n):
    """Groupe nominal avec son nombre (« 3 valeurs », « 1 organisation ») : clé au pluriel de saisie.n.* ou saisie.alertes.*."""
    return libelle(cle, n=n)


def _bandeau(etat, compteur, org=None, admin=False, lecture_seule=False):
    """Phrase du bandeau « ce qui reste à faire » (Saisie, Pour moi) : un état parmi six, et le texte à annoncer.

    - ``ici`` (A) : il reste des valeurs dans l'organisation affichée (Saisie) ou dans la liste (Pour moi) ;
    - ``alertes_ici`` (B) : tout y est saisi, mais une alerte attend une justification ;
    - ``ailleurs`` (C) : fini ici, il reste des valeurs dans d'autres organisations (« Aller à … ») ;
    - ``alertes_ailleurs`` (D) : fini ici, il reste des alertes ailleurs ;
    - ``fini`` (E) : tout le périmètre de la personne est fini (valeurs et alertes) : seul cas de « Tout est fait » ;
    - ``fermee`` (F) : saisie fermée pour la personne (campagne en revue, clôturée, date de fin passée) ; les alertes
      restent à traiter (la justification reste possible), sans lien « Aller à ».
    ``org`` : organisation affichée (Saisie : ``etat`` est alors tout le périmètre) ; None sur Pour moi (``etat`` est la
    liste). L'administrateur : en saisie fermée, les chiffres de l'organisation affichée, le reste en « Ailleurs »."""
    perimetre = org is not None
    ici = etat.ici(org) if perimetre else etat
    ailleurs = etat.ailleurs(org) if perimetre else S.Reste()
    suivante = etat.suivante(sauf=org) if perimetre else None
    b = {"ici": ici, "ailleurs": ailleurs, "suivante": suivante, "perimetre": perimetre, "org": org}
    def avec_org(texte):
        """« Pays : » devant le texte quand le bandeau parle de l'organisation affichée."""
        return libelle("saisie.bandeau.org_texte", organisation=org.nom, texte=texte) if perimetre else texte

    def dans(element, n_orgs):
        return libelle("saisie.bandeau.dans", element=element, organisations=_n("saisie.n.organisations", n_orgs))

    def ligne_ailleurs(valeurs="saisie.n.valeurs"):
        if ailleurs.fini:
            return ""
        parts = []
        if ailleurs.valeurs:
            parts.append(dans(_n(valeurs, ailleurs.valeurs), ailleurs.nb_orgs_valeurs))
        if ailleurs.alertes:
            parts.append(dans(_n("saisie.alertes.a_traiter", ailleurs.alertes), ailleurs.nb_orgs_alertes))
        return libelle("saisie.bandeau.ailleurs", liste=", ".join(parts))

    def aller_a():
        return " " + libelle("saisie.bandeau.aller_a", organisation=suivante.nom) if suivante else ""

    if lecture_seule:
        if not etat.a_montrer:
            return {**b, "code": ""}
        fermees = ici if admin or not perimetre else etat
        b["fermees"] = fermees
        b["fermees_orgs"] = fermees.nb_orgs_valeurs if perimetre and not admin else 0
        b["prefixe_org"] = admin and perimetre  # admin : les chiffres de l'organisation affichée, qu'il faut nommer
        parts = []
        if fermees.valeurs:
            valeurs = _n("saisie.n.valeurs_non_validees", fermees.valeurs)
            parts.append(dans(valeurs, b["fermees_orgs"]) if b["fermees_orgs"] else valeurs)
        b["fermees_orgs_alertes"] = fermees.nb_orgs_alertes if perimetre and not admin else 0
        if fermees.alertes:
            alertes = _n("saisie.alertes.a_traiter", fermees.alertes)
            parts.append(dans(alertes, b["fermees_orgs_alertes"]) if b["fermees_orgs_alertes"] else alertes)
        if not parts:
            parts = [libelle("saisie.resume.toutes_validees" if fermees.total else "saisie.resume.rien_ici")]
        texte = (libelle("saisie.bandeau.fermee_org", organisation=org.nom, liste=", ".join(parts)) if b["prefixe_org"]
                 else libelle("saisie.bandeau.fermee", liste=", ".join(parts)))
        b["ligne_ailleurs"] = ligne_ailleurs("saisie.n.valeurs_non_validees") if b["prefixe_org"] else ""
        return {**b, "code": "fermee", "annonce": " ".join(x for x in (texte, b["ligne_ailleurs"]) if x)}
    if ici.valeurs:
        parts = [libelle("saisie.bandeau.a_saisir", n=compteur.a_saisir)] if compteur.a_saisir else []
        if compteur.brouillon:
            parts.append(_n("saisie.n.brouillons_a_valider", compteur.brouillon))
        if ici.alertes:
            parts.append(_n("saisie.alertes.a_traiter", ici.alertes))
        parts = parts or [_n("saisie.n.valeurs_a_faire", ici.valeurs)]
        b["ligne_ailleurs"] = ligne_ailleurs()
        return {**b, "code": "ici", "annonce": " ".join(x for x in (avec_org(", ".join(parts) + "."), b["ligne_ailleurs"]) if x)}
    if ici.alertes:
        b["ligne_ailleurs"] = ligne_ailleurs()
        texte = libelle("saisie.bandeau.alertes_coherence", n=ici.alertes)
        if ici.total:
            texte = libelle("saisie.bandeau.tout_saisi_min" if perimetre else "saisie.bandeau.tout_saisi_maj", texte=texte)
        return {**b, "code": "alertes_ici", "annonce": " ".join(x for x in (avec_org(texte), b["ligne_ailleurs"]) if x)}
    if not etat.a_montrer:
        return {**b, "code": ""}
    fait = avec_org(libelle("saisie.resume.plus_rien" if ici.total else "saisie.resume.rien_ici") + ".") if perimetre else ""
    if ailleurs.valeurs:
        texte = libelle("saisie.bandeau.il_reste", element=_n("saisie.n.valeurs", ailleurs.valeurs),
                        organisations=_n("saisie.n.organisations", ailleurs.nb_orgs_valeurs))
        if ailleurs.alertes:
            texte += " " + libelle("saisie.bandeau.et_element", element=_n("saisie.alertes.a_traiter", ailleurs.alertes),
                                   organisations=_n("saisie.n.organisations", ailleurs.nb_orgs_alertes))
        return {**b, "code": "ailleurs", "fait": fait, "annonce": f"{fait} {texte}.{aller_a()}", "texte": texte + "."}
    if ailleurs.alertes:
        texte = libelle("saisie.bandeau.il_reste", element=_n("saisie.alertes.a_traiter", ailleurs.alertes),
                        organisations=_n("saisie.n.organisations", ailleurs.nb_orgs_alertes))
        return {**b, "code": "alertes_ailleurs", "fait": fait, "annonce": f"{fait} {texte}.{aller_a()}", "texte": texte + "."}
    # Saisie : la phrase porte sur toutes les organisations du périmètre (les pastilles, sur l'organisation affichée)
    b["nb_orgs_fini"] = sum(1 for r in etat.par_org.values() if r.total) if perimetre else 0
    if b["nb_orgs_fini"] > 1:
        annonce = libelle("saisie.bandeau.fini_orgs", n=etat.valide, total=etat.total, organisations=_n("saisie.n.organisations", b["nb_orgs_fini"]))
    elif b["nb_orgs_fini"]:
        annonce = libelle("saisie.bandeau.fini_une_org", n=etat.valide, total=etat.total)
    else:
        annonce = libelle("saisie.bandeau.fini", n=etat.valide, total=etat.total)
    return {**b, "code": "fini", "annonce": annonce}


def _reste_campagne(utilisateur, campagne, lignes, personnel=False):
    """Ce qui reste à faire dans une campagne : les lignes (attendues) et les alertes à traiter de ce périmètre."""
    from .coherence import alertes_a_traiter

    cases = {(l.kpi.code, l.organisation.id) for l in lignes if not l.calculee and not l.au_dessus}
    return S.reste(lignes, alertes_a_traiter(utilisateur, campagne, cases=cases, personnel=personnel))


# ---------------------------------------------------------------- « Je réponds à » : référentiel et période
def _suivant(request, valeur):
    """Page où revenir après un choix : la même, sans les paramètres de campagne (sinon l'accueil)."""
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

    if not valeur or not url_has_allowed_host_and_scheme(valeur, {request.get_host()}, request.is_secure()):
        return reverse("collecte:accueil")
    u = urlsplit(valeur)
    requete = urlencode([(k, v) for k, v in parse_qsl(u.query) if k not in ("campagne", "ref")])
    chemin = "/" + u.path.replace("\\", "/").lstrip("/")  # « //site » ou « /\\site » : jamais un autre site
    return urlunsplit(("", "", chemin, requete, ""))


@login_required
def choisir_campagne(request, pk):
    """Choix du panneau « Je réponds à » : mémorisé pour toutes les pages, puis retour à la page d'où il a été fait."""
    campagne = get_object_or_404(Campagne, pk=pk)
    if campagne.referentiel not in S.referentiels_de(request.user):
        raise PermissionDenied(libelle("saisie.erreur.referentiel_hors_perimetre"))
    request.session["campagne"] = campagne.pk
    request.session["referentiel"] = campagne.referentiel_id
    return redirect(_suivant(request, request.GET.get("suivant")))


@login_required
def choix_reponse(request):
    """Contenu du panneau « Je réponds à » (chargé à l'ouverture) : pour chaque référentiel de la personne, les
    campagnes en cours avec ce qu'il lui reste à faire, puis les autres périodes."""
    actuelle = request.session.get("campagne")
    suivant = request.GET.get("suivant", "")
    blocs = []
    for r in S.referentiels_de(request.user):
        en_cours, autres = [], []
        for c in S.campagnes_proposees(request.user, r):
            if c.statut in (Campagne.Statut.OUVERTE, Campagne.Statut.REVUE):  # même calcul que Pour moi et Saisie
                en_cours.append((c, _reste_campagne(request.user, c, S.lignes(request.user, c)), S.lecture_seule(request.user, c)))
            else:
                autres.append(c)
        blocs.append({"ref": r, "en_cours": en_cours, "recentes": autres[:3], "anciennes": autres[3:]})
    # au-delà de 6 périodes ouvertes, une recherche en tête du panneau 
    nb_en_cours = sum(len(b["en_cours"]) for b in blocs)
    ctx = {"blocs": blocs, "actuelle": actuelle, "suivant": suivant, "recherche": nb_en_cours > 6}
    if not est_script(request):  # adresse ouverte directement : une page complète, pas le fragment du panneau
        return render(request, "collecte/choix_reponse.html", {**ctx, "page": "saisie"})
    return render(request, "collecte/_choix_reponse.html", ctx)


# ---------------------------------------------------------------- pages
VUE_ORGANISATION, VUE_FLUX = "organisation", "flux"


def vue_saisie(utilisateur, session):
    """Vue de l'onglet Saisie : « une organisation à la fois » (page saisie) ou « tout ce qui m'est attribué » (page
    pour_moi, le flux des organisations). La dernière vue ouverte, sinon celle du rôle : l'administrateur parcourt les
    organisations, le contributeur et le validateur suivent leur flux. L'auditeur (lecture seule) n'a que la première."""
    if utilisateur.lecture_seule:
        return VUE_ORGANISATION
    vue = session.get("vue_saisie") if session is not None else None
    if vue in (VUE_ORGANISATION, VUE_FLUX):
        return vue
    return VUE_ORGANISATION if utilisateur.est_admin else VUE_FLUX


@login_required
def accueil(request):
    u = request.user
    if u.est_lecteur:
        return redirect("collecte:visu")
    return redirect("collecte:pour_moi" if vue_saisie(u, request.session) == VUE_FLUX else "collecte:saisie")


@never_cache  # retour arrière du navigateur : la page est relue (statuts à jour), pas reprise du cache
@login_required
def saisie(request):
    """Onglet Saisie, vue « Une organisation à la fois » : une organisation, choisie dans le sélecteur ; KPI du référentiel de la campagne, rangés par thème."""
    campagne = campagne_affichee(request)
    if campagne is None:
        return render(request, "collecte/aucune_campagne.html")
    if not request.user.lecture_seule:
        memoriser_session(request, "vue_saisie", VUE_ORGANISATION)  # l'onglet Saisie rouvre cette vue
    orgs = S.organisations_visibles(request.user, campagne)
    if not orgs:
        return render(request, "collecte/saisie.html", {"campagne": campagne, "groupes_campagnes": groupes_campagnes(request.user), "orgs": [], "page": "saisie"})
    etat = S.reste_par_org(orgs)  # tout le périmètre de la personne dans la campagne
    ids = {o.id: o for o, *_ in orgs}
    # choix demandé (mémorisé pour toutes les campagnes), sinon celui de cette campagne, sinon le dernier choix demandé ;
    # sans choix, la première organisation où il reste quelque chose : des valeurs, sinon des alertes, mémorisée
    # pour cette campagne seulement (le bandeau relu garde l'organisation ; une autre campagne refait le choix)
    par_campagne = request.session.get("org_par_campagne") or {}
    demande = request.GET.get("org")
    # « org_choisie » et non l'ancienne clé « org », que l'outil écrivait à chaque visite, même sans choix : une session
    # ouverte avant la mise à jour ne fige pas l'organisation
    choix = next((c for c in (demande, par_campagne.get(str(campagne.pk)), request.session.get("org_choisie"))
                  if est_identifiant(c) and int(c) in ids), None)
    org = ids[int(choix)] if choix is not None else (etat.suivante() or orgs[0][0])
    if demande is not None and est_identifiant(demande) and int(demande) in ids:
        request.session["org_choisie"] = org.id
    memoriser_session(request, "org_par_campagne", {**par_campagne, str(campagne.pk): org.id})
    voit_calc = S.voit_calcules(request.user, org)
    calculees = voit_calc and request.GET.get("calc", request.session.get("calc", "0")) == "1"
    memoriser_session(request, "calc", "1" if calculees else "0")
    plan = Plan(campagne.referentiel)
    lignes = S.lignes(request.user, campagne, org=org, calculees=calculees, plan=plan)
    return render(request, "collecte/saisie.html", {
        **_contexte_liste(request, campagne, lignes, etat, org), "orgs": orgs, "org": org, "sections": _par_theme(lignes, plan),
        "voit_calc": voit_calc, "calculees": calculees, "page": "saisie",
    })


@never_cache  # retour arrière du navigateur : la page est relue (statuts à jour), pas reprise du cache
@login_required
def pour_moi(request):
    """Onglet Saisie, vue « Tout ce qui m'est attribué » (ancienne page Pour moi, même adresse) : le flux des
    organisations, tout ce qui est attribué à la personne ; un onglet par campagne en cours de ses référentiels, ou « Tous mes
    référentiels » (une liste par référentiel ; un KPI commun à deux référentiels de même période n'y figure qu'une fois)."""
    if "tous" in request.GET:
        request.session["pour_moi_tous"] = request.GET["tous"] == "1"
    elif request.GET.get("campagne") or request.GET.get("ref"):
        request.session["pour_moi_tous"] = False
    campagne = campagne_affichee(request)
    if campagne is None:
        return render(request, "collecte/aucune_campagne.html")
    memoriser_session(request, "vue_saisie", VUE_FLUX)  # l'onglet Saisie rouvre cette vue
    groupe = request.GET.get("groupe", "organisation")
    plans = {}  # un plan par référentiel, lu une fois pour la page
    onglets = _onglets_pour_moi(request, campagne, plans)
    tous = bool(request.session.get("pour_moi_tous")) and len(onglets) > 1
    # vue d'ensemble : chaque case une seule fois ; d'une campagne dont la saisie est fermée, seules ses alertes (encore à
    # justifier) comptent, sauf si toutes sont fermées (la vue d'ensemble dit alors « saisie fermée »)
    tous_fermes = all(o["lecture_seule"] for o in onglets)
    reste_tous = sum((o["reste"] if tous_fermes or not o["lecture_seule"] else S.Reste(alertes=o["reste"].alertes)
                      for o in onglets), S.Reste())
    from . import forcage as FO
    from . import imports_arriere_plan as AP

    ctx = {"groupe": groupe, "page": "pour_moi", "onglets": onglets, "tous": tous, "reste_tous": reste_tous,
           "tous_fermes": tous_fermes,
           # valeurs forcées : résultats calculés dont la personne est responsable, demandes qu'elle peut accepter
           "forcage_responsable": len(S.resultats_responsable(request.user, campagne)),
           "forcage_a_trancher": len(FO.demandes_a_traiter(request.user, [campagne])),
           "imports_fond": AP.a_signaler(request.user)}  # gros imports en arrière-plan : en cours, ou finis et pas vus
    if tous:
        blocs, toutes = [], []
        for o in onglets:
            c, plan = o["campagne"], plans.get(o["campagne"].referentiel_id) or Plan(o["campagne"].referentiel)
            ls = o["lignes"]
            if ls:
                blocs.append({"campagne": c, "comparaison": S.libelle_comparaison(c), "reste": o["reste"],
                              "sections": _par_theme(ls, plan) if groupe == "theme" else _par_organisation(ls, plan),
                              "lecture_seule": o["lecture_seule"]})
            toutes += ls
        ouvertes = _ouvertes_demandees(request, len(blocs)) or _sections_ouvertes([b["sections"] for b in blocs])
        for i, b in enumerate(blocs):
            b["nb_ouvertes"] = None if ouvertes is None else ouvertes[i]
            b["prefixe"] = f"{i}-"
        ctx.update(_contexte_liste(request, campagne, toutes, reste_tous), blocs=blocs, lecture_seule=False,
                   sections_repliees=ouvertes is not None)
    else:
        plan = plans.get(campagne.referentiel_id) or Plan(campagne.referentiel)
        onglet = next((o for o in onglets if o["campagne"] == campagne), None)
        if onglet is not None:
            lignes, etat = onglet["lignes_completes"], onglet["etat"]
        else:
            lignes = S.lignes(request.user, campagne, personnel=True, plan=plan)
            etat = _reste_campagne(request.user, campagne, lignes, personnel=True)
        sections = _par_theme(lignes, plan) if groupe == "theme" else _par_organisation(lignes, plan)
        ouvertes = _ouvertes_demandees(request, 1) or _sections_ouvertes([sections])
        ctx.update(_contexte_liste(request, campagne, lignes, etat), sections=sections, prefixe_section="0-",
                   nb_ouvertes=None if ouvertes is None else ouvertes[0], sections_repliees=ouvertes is not None)
    # longue liste (échelle, P-A9) : les sections repliées partent sans leurs lignes ; le script les demande aussitôt la
    # page affichée (?reste=1, avec le nombre de sections ouvertes de la page), « ?complet=1 » : tout d'un coup (sans script)
    if request.GET.get("reste") == "1":
        return render(request, "collecte/_pour_moi_reste.html", ctx)
    if ouvertes is not None and request.GET.get("complet") != "1":
        params = request.GET.copy()
        params.pop("reste", None)
        params["complet"] = "1"
        ctx["url_complet"] = "?" + params.urlencode()
        params.pop("complet")
        params["reste"], params["ouvertes"] = "1", ",".join(str(n) for n in ouvertes)
        ctx.update(sections_a_charger=True, url_reste="?" + params.urlencode())
    # sélecteur d'organisation commun aux deux vues : ici, « Tout ce qui m'est attribué » est choisi
    ctx["orgs"] = S.organisations_visibles(request.user, campagne)
    return render(request, "collecte/pour_moi.html", ctx)


def _ouvertes_demandees(request, nb_blocs):
    """Nombre de sections ouvertes de chaque bloc, donné par la page qui demande ses sections repliées (?reste=1&ouvertes=3
    ou 3,0,0) : les mêmes sections que celles que la page a laissées vides, même si la liste a changé entre-temps. None
    hors de cette demande, ou si la valeur ne convient pas (la page refait alors son propre calcul)."""
    if request.GET.get("reste") != "1":
        return None
    morceaux = request.GET.get("ouvertes", "").split(",")
    if len(morceaux) != nb_blocs or not all(m.isdecimal() and len(m) < 7 for m in morceaux):
        return None
    return [int(m) for m in morceaux]


def _onglets_pour_moi(request, campagne, plans=None):
    """Campagnes en cours des référentiels de la personne (et la campagne affichée), avec ses lignes et ce qu'il lui reste
    à faire : [{campagne, lignes (sans les cases déjà vues dans un référentiel précédent de même période),
    lignes_completes, etat (Reste de la campagne : onglet et bandeau), reste (Reste sans ce qui est déjà compté dans
    un onglet précédent : vue d'ensemble), lecture_seule}]. Une valeur commune à deux référentiels de même période
    compte une fois dans la vue d'ensemble, et son alerte aussi, même si chaque campagne a la sienne ; elle va
    d'abord à une campagne dont la saisie est ouverte. ``plans`` : {référentiel : Plan}, complété ici (lu une fois)."""
    from .coherence import alertes_a_traiter

    plans = {} if plans is None else plans

    refs = S.referentiels_de(request.user)
    campagnes = [c for c in S.campagnes_en_cours() if c.referentiel in refs]
    if campagne not in campagnes:
        campagnes.insert(0, campagne)
    fermees = {c: S.lecture_seule(request.user, c) for c in campagnes}
    onglets, vues, vues_alertes = {}, set(), set()
    for c in sorted(campagnes, key=lambda c: fermees[c]):  # une case commune revient d'abord à une campagne ouverte
        if c.referentiel_id not in plans:
            plans[c.referentiel_id] = Plan(c.referentiel)
        completes = S.lignes(request.user, c, personnel=True, plan=plans[c.referentiel_id])
        alertes = alertes_a_traiter(request.user, c, cases={(l.kpi.code, l.organisation.id) for l in completes}, personnel=True)
        lignes = [l for l in completes if (c.periode_id, l.kpi.code, l.organisation.id) not in vues]
        vues.update((c.periode_id, l.kpi.code, l.organisation.id) for l in completes)
        cle = lambda a: (c.periode_id, a.kpi_id, a.organisation_id, a.controle, a.regle_id)  # noqa: E731
        propres = [a for a in alertes if cle(a) not in vues_alertes]
        vues_alertes.update(cle(a) for a in alertes)
        onglets[c] = {"campagne": c, "lignes": lignes, "lignes_completes": completes, "etat": S.reste(completes, alertes),
                      "reste": S.reste(lignes, propres), "lecture_seule": fermees[c]}
    return [onglets[c] for c in campagnes]


def _rythme(campagne):
    """Part du temps de saisie déjà écoulée (0 à 1) d'une campagne ouverte, ou None sans dates d'ouverture et de fin."""
    debut, fin = campagne.date_ouverture, campagne.date_fin_saisie
    if campagne.statut != Campagne.Statut.OUVERTE or not (debut and fin) or fin <= debut:
        return None
    return min(max((timezone.localdate() - debut).days / (fin - debut).days, 0), 1)


def tolerance_retard():
    """Points de taux sous le rythme attendu avant de signaler un retard (Paramètres › Seuils de suivi)."""
    from parametres.models import Instance

    return Instance.courante().tolerance_retard


def suivi(campagne, tdb):
    """Rythme attendu (en %, None sans dates), organisations en retard (identifiants) et compteur des cellules sans SPOC
    qui restent à faire (None s'il n'y en a pas), d'après le tableau de bord ``tdb`` d'une campagne.
    chaque organisation est jugée sur ses propres cases (``par_org_propre``) ; un parent n'est en retard que sur
    ses propres KPI, et ``retards_dessous`` compte les organisations en retard qui lui sont rattachées."""
    rythme = _rythme(campagne)
    attendu = int(arrondi(100 * rythme)) if rythme is not None else None
    retards = set()
    if attendu is not None:
        seuil = attendu - tolerance_retard()
        retards = {o.pk for o, c in tdb["par_org_propre"].items() if c.total and c.taux < seuil}
    sans_spoc = next((c for u, c in tdb["par_spoc"] if u is None and c.a_saisir + c.brouillon), None)
    return attendu, retards, sans_spoc


def retards_dessous(tdb, retards):
    """{identifiant d'une organisation : nombre des organisations en retard qui lui sont rattachées, à tout niveau}
    (« dont N en retard » sur la ligne d'un parent)."""
    dessous = {}
    for o in tdb["par_org_propre"]:
        if o.pk in retards:
            p = o.parent
            while p is not None:
                dessous[p.pk] = dessous.get(p.pk, 0) + 1
                p = p.parent
    return dessous


@never_cache  # retour arrière du navigateur : la page est relue (statuts à jour), pas reprise du cache
@login_required
def tableau_de_bord(request):
    """Taux de remplissage de la campagne par organisation, par thème et par SPOC, sur le périmètre de la personne ;
    avancement de toutes les campagnes en cours (taux par référentiel et période). Pour l'administrateur et le validateur,
    la liste « À relancer » vient en tête ; une organisation est « en retard » quand le taux de ses propres cases
    est nettement sous la part du temps de saisie écoulée, ce que le contributeur ne voit pas ; tri
    possible par taux (?tri=taux)."""
    campagne = campagne_affichee(request)
    if campagne is None:
        return render(request, "collecte/aucune_campagne.html")
    plan = Plan(campagne.referentiel)
    # lignes légères : la page ne fait que compter (saisie.lignes_legeres, mêmes chiffres)
    lignes = {campagne: S.lignes(request.user, campagne, plan=plan, legere=True)}
    tdb = S.tableau_de_bord(lignes[campagne], plan)
    refs = S.referentiels_de(request.user)
    en_cours = [c for c in S.campagnes_en_cours() if c.referentiel in refs]
    if campagne not in en_cours:
        en_cours.insert(0, campagne)
    avancement = []
    for c in en_cours:
        p = plan if c.pk == campagne.pk else Plan(c.referentiel)
        if c.pk == campagne.pk:  # mêmes cases que le taux en tête de page : déjà comptées
            avancement.append((c, tdb["total"]))
            continue
        if c not in lignes:
            lignes[c] = S.lignes(request.user, c, plan=p, legere=True)
        compteur = S.Compteur()
        for l in lignes[c]:
            if l.attendue:  # KPI facultatifs exclus, comme dans le taux en tête de page
                compteur.ajouter(l)
        avancement.append((c, compteur))
    attendu, retards, sans_spoc = suivi(campagne, tdb)
    voit_retards = RL.peut_relancer(request.user)  # le contributeur ne relance personne
    if not voit_retards:
        retards = set()
    dessous = retards_dessous(tdb, retards)
    tri = "taux" if request.GET.get("tri") == "taux" else "arbre"
    if tri == "taux":  # le plus bas d'abord ; « Sans SPOC » reste en tête
        def par_taux(x):
            return x[1].taux, -(x[1].a_saisir + x[1].brouillon), str(x[0] or "")

        tdb["par_org"] = sorted(tdb["par_org"], key=par_taux)
        tdb["par_theme"] = sorted(tdb["par_theme"], key=par_taux)
        tdb["par_spoc"] = sorted(tdb["par_spoc"], key=lambda x: (x[0] is not None, *par_taux(x)))
    # lignes de l'arbre : un parent (des cases rattachées) nomme ses deux chiffres, l'ensemble et ses propres KPI
    arbre = []
    ids = {o.pk for o, _ in tdb["par_org"]}
    avec_enfants = {o.parent_id for o, _ in tdb["par_org"] if o.parent_id in ids}
    base = min((o.prof for o, _ in tdb["par_org"]), default=0)
    for o, c in tdb["par_org"]:
        propre = tdb["par_org_propre"].get(o)
        # parent_id, enfants, prof : l'arbre se replie dans la page (ordre de l'arbre seulement), comme la Consolidation
        arbre.append((o, c, {"parent": c.total > (propre.total if propre else 0), "propre": propre,
                             "retard": o.pk in retards, "dessous": dessous.get(o.pk, 0),
                             "parent_id": o.parent_id if o.parent_id in ids and tri == "arbre" else None,
                             "enfants": o.pk in avec_enfants and tri == "arbre", "prof": o.prof - base}))
    ouverte = campagne.statut == Campagne.Statut.OUVERTE
    peut_relancer = voit_retards and ouverte
    # « À relancer » retiré du tableau de bord : la page Relances donne la liste par personne
    jours = (campagne.date_fin_saisie - timezone.localdate()).days if ouverte and campagne.date_fin_saisie else None
    verdict = _verdict(tdb["total"], attendu, tolerance_retard()) if voit_retards and ouverte else None
    return render(request, "collecte/tableau_de_bord.html", {
        "verdict": verdict, "a_faire": _a_faire_tdb(request.user, campagne, attendu, retards, sans_spoc, peut_relancer),
        "lien_saisie": None if request.user.est_lecteur else reverse(
            "collecte:saisie" if request.user.est_admin or request.user.lecture_seule else "collecte:pour_moi"),
        # chiffres cliquables : vers la Saisie filtrée sur ce statut, ou vers les organisations en retard
        "tuiles": [("a_saisir", tdb["total"].a_saisir), ("brouillon", tdb["total"].brouillon)]
                  + ([("retards", len(retards))] if voit_retards and attendu is not None else []),
        "campagne": campagne, "groupes_campagnes": groupes_campagnes(request.user), "page": "tableau_de_bord", **tdb,
        "peut_relancer": peut_relancer, "smtp": RL.envoi_actif(), "arbre": arbre, "voit_retards": voit_retards,
        "avancement": avancement, "attendu": attendu,
        # verdict : taux validé au pour cent près, comme le rythme attendu auquel il est comparé (« 26 % » et « 26 % »)
        "taux_verdict": int(arrondi(tdb["total"].taux)), "retards": retards, "tri": tri, "sans_spoc": sans_spoc,
        "tolerance": tolerance_retard(), "jours": jours, "jours_depasses": -jours if jours is not None and jours < 0 else 0,
    })




def _verdict(total, attendu, tolerance):
    """Phrase d'en-tête du tableau de bord : « dans les temps » ou « en retard de N points » sur le rythme attendu
    (même tolérance que les organisations en retard) ; None sans rythme attendu (pas de dates) ou sans case."""
    if attendu is None or not total.total:
        return None
    ecart = round(attendu - total.taux)
    if total.taux < attendu - tolerance:
        return {"code": "retard", "points": ecart}
    return {"code": "a_temps", "points": max(-ecart, 0)}


def _a_faire_tdb(utilisateur, campagne, attendu, retards, sans_spoc, peut_relancer):
    """« À traiter » du tableau de bord : seulement ce qui demande une action, chaque ligne avec son lien. Mêmes sujets,
    mêmes mots que l'Administration › Vue d'ensemble (collecte/a_traiter.py) ; rien pour le lecteur et l'auditeur (ils
    n'agissent sur rien). Les liens « Attribuer » et « Hébergement » sont réservés à l'administrateur."""
    from . import a_traiter as AT

    if utilisateur.lecture_seule:
        return []
    sortie = []
    n_sans_spoc = (sans_spoc.a_saisir + sans_spoc.brouillon) if sans_spoc else 0
    if n_sans_spoc:
        sortie.append(AT.sans_spoc(n_sans_spoc, utilisateur.est_admin))
    if retards:  # « Voir et relancer » : montre les organisations en retard dans la page (liste « Seulement en retard »)
        sortie.append(AT.retards(len(retards), campagne, attendu, "#detail-tdb", sur_place=True))
    if peut_relancer and not RL.envoi_actif():
        sortie.append(AT.emails(Instance.courante().relance_auto, utilisateur.est_admin))
    return sortie


# ---------------------------------------------------------------- panneau de saisie
def ligne_html(request, campagne, kpi, org):
    """Ligne relue après une saisie : même HTML que dans la liste (``rendu_ligne``)."""
    from . import rendu_ligne as RL

    l = S.ligne(request.user, campagne, kpi, org)
    return l.cle, RL.ligne(l, RL.Constantes(request.user.est_admin, request.user, campagne, S.libelle_comparaison(campagne),
                                            request.headers.get("x-page") == "pour_moi"))


# ---------------------------------------------------------------- attributions (SPOC)
@login_required
@require_POST
def attribuer(request):
    """Attribue ou retire un SPOC sur une ou plusieurs cellules. Corps JSON : {cles, utilisateur, retirer, campagne}."""
    exiger_admin(request)
    corps = corps_envoye(request)  # None : formulaire au lieu de JSON
    try:
        donnees = None if corps is None else json.loads(corps or "{}")
    except (ValueError, RecursionError):  # RecursionError : imbrication démesurée ([[[[…]]]])
        donnees = None
    if not isinstance(donnees, dict) or not isinstance(donnees.get("cles", []), list):
        return reponse_erreur(libelle("saisie.erreur.action_inconnue"))
    # campagne de la page (lignes de la Saisie à redessiner), lue sans rien mémoriser : une attribution ne change jamais
    # le référentiel ni la campagne mémorisés (seconde recette, B1 : le filtre Référentiel des Attributions changeait seul)
    cle = donnees.get("campagne")
    campagne = None if donnees.get("format") == "cellule" else (
        Campagne.objects.select_related("referentiel", "periode").filter(pk=cle).first() if est_identifiant(cle) else None) \
        or campagne_affichee(request)
    role = donnees.get("role") or Attribution.Role.CONTRIBUTEUR  # « validateur » : choix Validateurs de la grille
    if role not in Attribution.Role.values:
        return reponse_erreur(libelle("saisie.erreur.action_inconnue"))
    u = get_object_or_404(Utilisateur, pk=identifiant(donnees.get("utilisateur")), is_active=True)
    paires = []
    for cle in donnees.get("cles", []):
        kpi_id, _, org_id = str(cle).rpartition("|")
        paires.append((get_object_or_404(KPI, pk=kpi_id), get_object_or_404(Organisation, pk=identifiant(org_id))))
    try:
        n = S.attribuer(request.user, paires, u, retirer=bool(donnees.get("retirer")), role=role)
    except ValidationError as e:
        return reponse_erreur(" ".join(e.messages))
    if donnees.get("format") == "cellule":  # grille Administration › Attributions
        from .administration import cellule_html

        lignes = {f"{k.pk}|{o.pk}": cellule_html(request, k, o, role) for k, o in paires}
    else:
        lignes = dict(ligne_html(request, campagne, k, o) for k, o in paires)
    retirer = bool(donnees.get("retirer"))
    if role == Attribution.Role.VALIDATEUR:
        message = libelle("saisie.attribuer.validateur_retire" if retirer else "saisie.attribuer.validateur_attribue", n=n, utilisateur=u)
    else:
        message = libelle("saisie.attribuer.retire" if retirer else "saisie.attribuer.attribue", n=n, utilisateur=u)
    if n < len(paires):
        message += " " + libelle("saisie.attribuer.inchange_retire" if retirer else "saisie.attribuer.inchange_attribue", n=len(paires) - n)
    return JsonResponse({"ok": True, "lignes": lignes, "message": message})
