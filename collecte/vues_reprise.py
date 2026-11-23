"""Assistant de reprise d'un ancien système (administrateur) : fichier, colonnes, correspondances, unités, aperçu, import.

L'état de l'assistant (fichier déposé, réglages) est gardé en session ; le fichier est relu à chaque étape. Les
correspondances sont mémorisées en base dès l'étape 3 ; un profil garde le reste pour les fichiers suivants."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.files.storage import default_storage
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from parametres import ia as IA
from parametres.libelles import libelle
from referentiel.models import KPI, Organisation

from . import fichiers as X
from .garde_requetes import nombre_envoye
from . import imports as I
from . import reprise as R
from . import saisie as S
from .models import Journal, ProfilReprise
from .vues_communes import exiger_admin, identifiant
from .vues_echanges import deposer_fichier, oublier_fichier, ouvrir_fichier, garder_lecture, lecture_gardee

CLE = "reprise"
ETAPES = [("fichier", "admin.reprise.etape.fichier"), ("colonnes", "admin.reprise.etape.colonnes"),
          ("correspondances", "admin.reprise.etape.correspondances"), ("unites", "admin.reprise.etape.unites"),
          ("apercu", "admin.reprise.etape.apercu")]  # (code, clé du libellé)


def _url(etape):
    return f"{reverse('collecte:admin_reprise')}?etape={etape}"


def lire_fichier(etat):
    """{onglet: lignes} du fichier déposé ; {} s'il a disparu."""
    if not etat.get("chemin") or not default_storage.exists(etat["chemin"]):
        return {}
    onglets = lecture_gardee(etat["chemin"])  # relire un gros classeur prend plusieurs secondes : lu une seule fois
    if onglets is not None:
        return onglets
    with ouvrir_fichier(etat["chemin"]) as f:
        f.name = etat["nom"]
        try:
            onglets = X.lire(f)
        except X.FichierInvalide:
            return {}
    garder_lecture(etat["chemin"], onglets)
    return onglets


def _annees_demandees(texte):
    """« 2023, 2024 » ou « 2022-2024 » → [2022, 2023, 2024] ; sans rien de lisible : les trois derniers exercices clos."""
    import datetime
    import re

    annees = set()
    for debut, fin in re.findall(r"((?:19|20)\d\d)\s*[-–à]\s*((?:19|20)\d\d)", texte or ""):
        annees.update(range(int(debut), min(int(fin), int(debut) + 30) + 1))
    annees.update(int(a) for a in re.findall(r"(?<!\d)((?:19|20)\d\d)(?!\d)", texte or ""))
    if not annees:
        cette_annee = datetime.date.today().year
        annees = {cette_annee - 3, cette_annee - 2, cette_annee - 1}
    return sorted(annees)[:15]


def _completer_lecture(lignes, r):
    """Après une proposition de colonnes : les colonnes qui ne sont pas des valeurs sont écartées d'office, et l'année
    vient du nom de l'onglet quand aucune colonne ne la donne (« 2025 Data »)."""
    r.exclues = R.colonnes_a_ecarter(lignes, r, R.Contexte(r.source))
    if r.forme != "annees" and "periode" not in r.colonnes and not r.fixes.get("periode"):
        annee = R.annee_de_l_onglet(r.onglet)
        if annee:
            r.fixes = {**r.fixes, "periode": annee}


def _sauver(request, etat, r=None, etape=None):
    if r is not None:
        etat["reglages"] = r.en_dict()
    if etape:
        etat["etape"] = etape
    request.session[CLE] = etat
    request.session.modified = True


@login_required
def reprise(request):
    exiger_admin(request)
    if request.GET.get("modele"):  # modèle d'adaptation : au bon format, déjà rempli avec les KPI et les organisations
        return R.modele_adaptation(_annees_demandees(request.GET.get("annees", "")))
    etat = dict(request.session.get(CLE) or {})
    onglets = lire_fichier(etat) if etat.get("chemin") else {}
    etape = request.GET.get("etape") or etat.get("etape") or "fichier"
    if etape not in dict(ETAPES) and etape != "resultat" or (etape != "fichier" and not onglets):
        etape = "fichier"
    r = R.Reglages.depuis(etat.get("reglages"))
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "recommencer":
            oublier_fichier(request, CLE)
            return redirect(_url("fichier"))
        if action == "supprimer_profil":
            p = get_object_or_404(ProfilReprise, pk=identifiant(request.POST.get("profil")))
            messages.success(request, libelle("admin.reprise.profil_supprime", nom=str(p)))
            p.delete()
            return redirect(_url("fichier"))
        traiter = {"fichier": _poster_fichier, "colonnes": _poster_colonnes, "correspondances": _poster_correspondances,
                   "unites": _poster_unites, "apercu": _poster_apercu}.get(etape)
        if traiter is not None:
            reponse = traiter(request, etat, r, onglets)
            if reponse is not None:
                return reponse
            etat = dict(request.session.get(CLE) or {})
            r = R.Reglages.depuis(etat.get("reglages"))
            onglets = lire_fichier(etat) if etat.get("chemin") else {}
    ctx = {"page": "administration", "rubrique": "fichiers", "etapes": [(c, libelle(cle)) for c, cle in ETAPES], "etape": etape, "etat": etat, "r": r,
           "rang": [e for e, _ in ETAPES].index(etape) if etape in dict(ETAPES) else len(ETAPES)}
    if etape == "fichier":
        ctx["annees_proposees"] = ", ".join(str(a) for a in _annees_demandees(""))
        ctx.update(profils=list(ProfilReprise.objects.all()), sources=sorted(set(ProfilReprise.objects.values_list("source", flat=True))
                   | set(R.CorrespondanceReprise.objects.values_list("source", flat=True)) or {R.SOURCE_PAR_DEFAUT}))
    else:
        lignes = onglets.get(r.onglet) or next(iter(onglets.values()))
        ctx.update(_contexte_etape(request, etape, lignes, r, onglets, etat))
        # « Télécharger les lignes rejetées » (même rapport que l'import de valeurs) : préparé à la demande seulement,
        # il coûte plusieurs secondes sur un gros fichier 
        if etape == "apercu" and request.GET.get("rejets"):
            return I.fichier_rejets(request.user, I.lignes_rejetees(ctx["analyse"], request.user), etat.get("nom", ""), "xlsx")
    return render(request, "collecte/administration/reprise.html", ctx)


# ---------------------------------------------------------------- étape 1 : fichier
def _poster_fichier(request, etat, r, onglets):
    profil = ProfilReprise.objects.filter(pk=request.POST.get("profil") or 0).first() if str(request.POST.get("profil", "")).isdecimal() else None
    chemin, erreur = deposer_fichier(request, CLE)
    if erreur:
        messages.error(request, erreur)
        return redirect(_url("fichier"))
    etat = dict(request.session[CLE])
    onglets = lire_fichier(etat)
    if not any(onglets.values()):
        messages.error(request, libelle("admin.reprise.fichier_vide"))
        oublier_fichier(request, CLE)
        return redirect(_url("fichier"))
    r = R.Reglages.depuis(profil.reglages) if profil else R.Reglages()
    r.source = (request.POST.get("source") or (profil.source if profil else "") or R.SOURCE_PAR_DEFAUT).strip()[:100]
    if r.onglet not in onglets:
        r.onglet = next((n for n, l in onglets.items() if any(any(X.texte(v) for v in x) for x in l)), next(iter(onglets)))
    _detecter(onglets[r.onglet], r, garder=profil is not None)
    etat["profil"] = profil.pk if profil else None
    _sauver(request, etat, r, "colonnes")
    forme = dict((f, nom) for f, nom, _ in R.formes())[r.forme]
    messages.success(request, libelle("admin.reprise.fichier_lu_profil", ligne=r.entete + 1, forme=forme, profil=str(profil)) if profil
                     else libelle("admin.reprise.fichier_lu", ligne=r.entete + 1, forme=forme))
    return redirect(_url("colonnes"))


def _detecter(lignes, r, garder=False, forme=None):
    """Ligne d'en-têtes, forme et colonnes proposées. ``garder`` : un profil donne déjà la forme et les colonnes ; elles
    sont gardées si leurs en-têtes existent dans ce fichier."""
    ctx = R.Contexte(r.source)
    if garder and r.colonnes:  # la ligne qui contient les en-têtes du profil
        voulus = set(r.colonnes.values())
        meilleure = max(range(min(20, len(lignes))), key=lambda i: len(voulus & set(R.entetes(lignes, i))), default=0)
        if voulus & set(R.entetes(lignes, meilleure)):
            r.entete = meilleure
            if voulus <= set(R.entetes(lignes, r.entete)):
                return
    else:
        r.entete = R.detecter_entete(lignes)
    proposee, colonnes = R.detecter(lignes, r.entete, ctx)
    r.forme = forme or proposee
    r.colonnes = colonnes if r.forme == proposee else R.proposer_colonnes(lignes, r.entete, r.forme, ctx)
    _completer_lecture(lignes, r)
    r.dates = R.proposer_dates(lignes, r)


# ---------------------------------------------------------------- étape 2 : colonnes
def _poster_colonnes(request, etat, r, onglets):
    P = request.POST
    etat["reglages_ouverts"] = True  # la personne règle la lecture : « Corriger la lecture » reste déplié
    onglet = P.get("onglet") if P.get("onglet") in onglets else r.onglet
    try:
        entete = max(0, min(int(P.get("entete") or r.entete + 1), 10_000) - 1)
    except ValueError:
        entete = r.entete
    forme = P.get("forme") if P.get("forme") in R.ROLES_PAR_FORME else r.forme
    lignes = onglets[onglet]
    if (onglet, entete, forme) != (r.onglet, r.entete, r.forme):  # autre onglet, autre ligne ou autre forme : on repropose
        r.onglet = onglet
        if onglet != etat.get("reglages", {}).get("onglet"):
            _detecter(lignes, r, forme=forme if forme != r.forme else None)
        else:
            r.entete, r.forme = entete, forme
            r.colonnes = R.proposer_colonnes(lignes, entete, forme, R.Contexte(r.source))
            _completer_lecture(lignes, r)
            r.dates = R.proposer_dates(lignes, r)
        _sauver(request, etat, r)
        return redirect(_url("colonnes"))
    tetes = R.entetes(lignes, r.entete)
    r.colonnes = {role: P[f"role_{role}"] for role in R.ROLES_PAR_FORME[r.forme] if P.get(f"role_{role}") in tetes}
    valeurs = R.colonnes_de_valeurs(lignes, R.Reglages.depuis({**r.en_dict(), "exclues": []}))
    gardees = set(P.getlist("valeurs"))
    r.exclues = [t for t in valeurs if t not in gardees]
    r.fixes = {}
    if P.get("org_fixe", "").isdecimal():
        r.fixes["organisation"] = int(P["org_fixe"])
    if P.get("periode_fixe", "").strip():
        r.fixes["periode"] = P["periode_fixe"].strip()[:20]
    r.dates = "mois" if P.get("dates") == "mois" else "exercice"
    _sauver(request, etat, r)
    if P.get("action") != "suivant":
        return redirect(_url("colonnes"))
    manque = _manques(r, lignes)
    if manque:
        for m in manque:
            messages.error(request, m)
        return redirect(_url("colonnes"))
    suite = _etape_utile(lignes, r, "correspondances")
    _sauver(request, etat, r, suite)
    return redirect(_url(suite))


def _etape_utile(lignes, r, depuis):
    """Première étape, à partir de ``depuis``, où la personne a quelque chose à faire : les correspondances s'il reste
    des libellés à relier, les unités s'il y a une conversion ou un pourcentage à confirmer, sinon l'aperçu."""
    ctx = R.Contexte(r.source)
    elements = R.extraire(lignes, r)
    if depuis == "correspondances":
        if R.verifier(lignes, r, ctx).reste_a_relier:
            return "correspondances"
    unites, pourcents = R.conversions_a_regler(elements, ctx, r)  # déjà réglés (réglages enregistrés) : rien à confirmer
    a_regler = any(cle not in r.conversions for cle, *_ in unites) or any(k.code not in r.pourcentages for k, *_ in pourcents)
    return "unites" if a_regler else "apercu"


def _manques(r, lignes):
    roles = r.colonnes
    m = []
    if r.forme != "kpis" and not ({"kpi_code", "kpi_nom"} & set(roles)):
        m.append(libelle("admin.reprise.manque.kpi"))
    if r.forme != "organisations" and "organisation" not in roles and not r.fixes.get("organisation"):
        m.append(libelle("admin.reprise.manque.organisation"))
    if r.forme != "annees" and "periode" not in roles and not r.fixes.get("periode"):
        m.append(libelle("admin.reprise.manque.periode"))
    elif r.fixes.get("periode") and "periode" not in roles and r.forme != "annees" and R.P.lire(r.fixes["periode"]) is None:
        m.append(libelle("admin.reprise.manque.periode_illisible", periode=r.fixes["periode"]))
    if r.forme == "longue" and "valeur" not in roles:
        m.append(libelle("admin.reprise.manque.valeur"))
    if r.forme != "longue" and not R.colonnes_de_valeurs(lignes, r):
        m.append(libelle("admin.reprise.manque.colonnes_valeurs", sens=R.sens_colonnes(r.forme)))
    return m


# ---------------------------------------------------------------- étape 3 : correspondances
def _poster_correspondances(request, etat, r, onglets):
    P = request.POST
    erreurs, choix_kpi, choix_org = [], {}, {}
    codes = {c.lower(): c for c in KPI.objects.values_list("code", flat=True)}
    for i in range(nombre_envoye(P, "nb_kpi")):
        lib = P.get(f"lib_kpi_{i}", "")
        brut = P.get(f"kpi_{i}", "").strip()
        code = codes.get(brut.split(" – ")[0].strip().lower(), "") if brut else ""
        if brut and not code:
            erreurs.append(libelle("admin.reprise.erreur.kpi_inconnu", valeur=brut, ligne=lib))
        choix_kpi[lib] = (code, P.get(f"ignorer_kpi_{i}") == "on")
    orgs = set(Organisation.objects.values_list("id", flat=True))
    for i in range(nombre_envoye(P, "nb_org")):
        lib = P.get(f"lib_org_{i}", "")
        cible = int(P[f"org_{i}"]) if P.get(f"org_{i}", "").isdecimal() and int(P[f"org_{i}"]) in orgs else ""
        choix_org[lib] = (cible, P.get(f"ignorer_org_{i}") == "on")
    R.memoriser(r.source, "kpi", choix_kpi)
    R.memoriser(r.source, "org", choix_org)
    for e in erreurs:
        messages.error(request, e)
    if erreurs or P.get("action") != "suivant":
        return redirect(_url("correspondances"))
    reste = sum(1 for c, ig in list(choix_kpi.values()) + list(choix_org.values()) if not c and not ig)
    if reste:
        messages.warning(request, libelle("admin.reprise.non_relies", n=reste))
    suite = _etape_utile(onglets.get(r.onglet) or next(iter(onglets.values())), r, "unites")
    _sauver(request, etat, r, suite)
    return redirect(_url(suite))


# ---------------------------------------------------------------- étape 4 : unités
def _poster_unites(request, etat, r, onglets):
    P = request.POST
    for i in range(nombre_envoye(P, "nb_unites")):
        cle, f = P.get(f"cle_unite_{i}", ""), P.get(f"facteur_{i}", "").strip()
        if not cle:
            continue
        if f and R.decimal_lu(f) is None:
            messages.error(request, libelle("admin.reprise.erreur.facteur", valeur=f))
            return redirect(_url("unites"))
        r.conversions[cle] = f.replace(",", ".") if f else "1"
    for cle, v in P.items():
        if cle.startswith("pct_") and v in ("fraction", "cent"):
            r.pourcentages[cle[4:]] = v
    _sauver(request, etat, r, "apercu" if P.get("action") == "suivant" else None)
    return redirect(_url("apercu" if P.get("action") == "suivant" else "unites"))


# ---------------------------------------------------------------- étape 5 : aperçu et import
def _transformation(lignes, r):
    ctx = R.Contexte(r.source)
    return R.transformer(R.extraire(lignes, r), r, ctx)


def _poster_apercu(request, etat, r, onglets):
    P = request.POST
    lignes = onglets.get(r.onglet) or next(iter(onglets.values()))
    if P.get("action") == "profil":
        nom = P.get("nom_profil", "").strip()[:100]
        profil = ProfilReprise.objects.filter(pk=etat.get("profil") or 0).first()
        if P.get("mettre_a_jour") == "on" and profil is not None:
            profil.reglages, profil.source = r.en_dict(), r.source
            profil.nom = nom or profil.nom
            profil.save()
        elif not nom:
            messages.error(request, libelle("admin.reprise.erreur.nom_profil"))
            return redirect(_url("apercu"))
        else:
            profil = ProfilReprise.objects.create(nom=nom, source=r.source, reglages=r.en_dict(), proprietaire=request.user)
        etat["profil"] = profil.pk
        _sauver(request, etat)
        messages.success(request, libelle("admin.reprise.profil_enregistre", nom=str(profil), source=r.source))
        return redirect(_url("apercu"))
    if P.get("action") != "importer":
        return None
    t = _transformation(lignes, r)
    nom = f"Reprise {r.source} – {etat.get('nom', '')}"
    # fichier d'un autre système : ses nombres écrits en texte se lisent dans la langue de l'écran (S.langue_ecran)
    analyse, n, avertissements = I.appliquer(request.user, None, nom, creer_campagnes=True, onglets=t.onglets,
                                             transformer=lambda a: R.retoucher_motifs(a, t), langue_nombres=I.S.langue_ecran())
    Journal.ecrire(request.user, "reprise", request.user, "fichier", "",
                   f"{r.source} · {etat.get('nom', '')} : {n} valeur(s), {len(analyse.campagnes_a_creer)} campagne(s) créée(s)")
    request.session["rejets_import"] = {"nom": etat.get("nom", ""), "lignes": I.lignes_rejetees(analyse, request.user)}
    etat["resultat"] = {"ecrites": n, "avertissements": avertissements[:100], "campagnes": analyse.campagnes_a_creer,
                        "rejets": len(request.session["rejets_import"]["lignes"]), "ignorees": t.ignorees}
    _sauver(request, etat, etape="resultat")
    return redirect(_url("resultat"))


# ---------------------------------------------------------------- contexte des étapes
def _contexte_etape(request, etape, lignes, r, onglets, etat):
    tetes = R.entetes(lignes, r.entete)
    ctx = {"onglets": list(onglets), "nb_lignes": len(lignes)}
    if etape == "colonnes":
        complet = R.Reglages.depuis({**r.en_dict(), "exclues": []})
        ctx.update(apercu=R.apercu_lignes(lignes, r.entete), tetes=tetes, formes=R.formes(),
                   roles=[(role, R.nom_role(role), r.colonnes.get(role, "")) for role in R.ROLES_PAR_FORME[r.forme]],
                   valeurs=[(t, t not in r.exclues) for t in R.colonnes_de_valeurs(lignes, complet)],
                   sens_valeurs=R.sens_colonnes(r.forme),
                   orgs=sorted(S.arbre_organisations().values(), key=S.cle_arbre),
                   a_des_dates=any(isinstance(v, R.datetime.date) for l in lignes[r.entete + 1:r.entete + 200] for v in l),
                   verification=R.verifier(lignes, r, R.Contexte(r.source), _manques(r, lignes)),
                   ouvrir_reglages=bool(etat.get("reglages_ouverts")))
        return ctx
    elements = R.extraire(lignes, r)
    contexte = R.Contexte(r.source)
    ctx["nb_elements"] = len(elements)
    if etape == "correspondances":
        kpis = R.proposer_kpis(elements, contexte)
        for p in kpis:
            k = contexte.kpis.get(p.cible)
            p.affiche = f"{k.code} – {k.nom}" if k else ""
        ctx.update(kpis=kpis, orgs_prop=R.proposer_orgs(elements, contexte),
                   ia_reprise=IA.bouton_visible("reprise") and any(not p.sur and not p.ignorer for p in kpis),
                   tous_kpis=sorted(contexte.kpis.values(), key=lambda k: k.code),
                   orgs=sorted(S.arbre_organisations().values(), key=S.cle_arbre))
    elif etape == "unites":
        unites, pourcents = R.conversions_a_regler(elements, contexte, r)
        ctx.update(unites=[(cle, k, u, str(f).replace(".", ",")) for cle, k, u, f in unites], pourcents=pourcents)
    elif etape == "apercu":
        t = R.transformer(elements, r, contexte)
        analyse = I.analyser(request.user, None, creer_campagnes=True, onglets=t.onglets, langue_nombres=I.S.langue_ecran())
        R.retoucher_motifs(analyse, t)
        ctx.update(analyse=analyse, transformation=t, profil=ProfilReprise.objects.filter(pk=etat.get("profil") or 0).first(),
                   nb_rejets=sum(1 for l in analyse.lignes if l.action == "rejet"))
    elif etape == "resultat":
        ctx["resultat"] = etat.get("resultat") or {}
    return ctx
