"""Assistant « Mise en place » : premier lancement d'une installation vide, en 8 étapes (compte administrateur, structure,
langues, organisation, référentiels, fiche indicateur, équipe, première campagne).

Chaque étape réutilise les réglages de l'outil (identité, langues, niveaux, bibliothèque et échange de référentiels,
comptes, campagnes) : tout reste modifiable ensuite dans Administration. L'état est gardé dans l'installation
(``Instance.mise_en_place_etape`` et ``mise_en_place_terminee``) : on reprend à l'étape en cours. Une installation
existante (des comptes avant cette version) est marquée terminée par la migration et ne voit jamais l'assistant.

Sans aucun compte, toutes les pages mènent à l'étape 1 ; ensuite, l'administrateur qui revient à l'accueil est ramené
à l'étape en cours et un bandeau propose de reprendre depuis les autres pages.
"""
import copy
import datetime
import re
from dataclasses import dataclass

from django import forms
from django.contrib import messages
from django.contrib.auth import login, password_validation
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count, Max
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone, translation
from django.utils.functional import lazy

from collecte import fichiers as X
from collecte.models import Journal

from . import couleurs as CO
from . import langues as L
from . import libelles as LB
from . import niveaux as N
from .libelles import libelle
from .models import CategorieDescription, ChampPersonnalise, Instance, Langue, NiveauHierarchique, TypeReponse, TypeSaisie, Unite
from espaces import contexte as ESP

_l = lazy(libelle, str)  # libellé évalué à l'affichage (champs de formulaire définis à l'import)


@dataclass(frozen=True)
class Etape:
    """Une étape de l'assistant ; titre, résumé et « où la modifier ensuite » sont dans libelles/referentiels.*.json."""
    numero: int
    code: str
    passer: bool = True  # une valeur par défaut existe : « Passer » possible

    @property
    def titre(self):
        return libelle(f"referentiels.mep.etape.{self.code}.titre")

    @property
    def resume(self):
        return libelle(f"referentiels.mep.etape.{self.code}.resume")

    @property
    def ensuite(self):  # où la modifier après la mise en place
        return libelle(f"referentiels.mep.etape.{self.code}.ensuite")


ETAPES = [Etape(1, "compte", False), Etape(2, "structure"), Etape(3, "langues"), Etape(4, "organisation"), Etape(5, "referentiels"),
          Etape(6, "fiche"), Etape(7, "equipe"), Etape(8, "campagne")]
DERNIERE = len(ETAPES)


# ================================================================= état, redirection, bandeau
def sans_compte():
    """Installation sans aucun compte (registre commun vide) : l'étape 1 crée l'administrateur. Jamais lu dans un espace :
    un espace neuf, sans copie, n'offre pas l'étape 1 à un visiteur non connecté."""
    from espaces.models import Compte

    return not Compte.objects.exists()


def en_cours(instance=None):
    """Étape en cours (1 à 8) si une mise en place est commencée et pas terminée, sinon None."""
    i = instance or Instance.courante()
    return i.mise_en_place_etape if i.mise_en_place_etape and not i.mise_en_place_terminee else None


def avancer(instance, etape):
    """Après l'étape ``etape`` : on passe à la suivante (on ne recule jamais l'étape mémorisée)."""
    if etape >= DERNIERE:
        instance.mise_en_place_terminee = True
    instance.mise_en_place_etape = max(instance.mise_en_place_etape, min(etape + 1, DERNIERE))
    instance.save(update_fields=["mise_en_place_etape", "mise_en_place_terminee"])


class MiseEnPlaceMiddleware:
    """Installation sans compte : toute page mène à l'assistant (à la place de la connexion). Mise en place commencée et
    pas terminée : l'administrateur qui arrive à l'accueil (après la connexion) reprend à l'étape en cours."""

    LIBRES = ("/static/", "/media/", "/mise-en-place/", "/identite/logo/", "/sante/", "/langue/")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        chemin = request.path_info  # sans le préfixe /espace/<code>/
        if not chemin.startswith(self.LIBRES):
            u = getattr(request, "user", None)
            if u is None or not u.is_authenticated:
                if sans_compte():
                    return redirect("parametres:mise_en_place")
            elif chemin == "/" and u.est_admin and en_cours():
                return redirect("parametres:mise_en_place")
        return self.get_response(request)


def contexte(request):
    """Bandeau « Mise en place en cours » (administrateurs, hors de l'assistant)."""
    u = getattr(request, "user", None)
    if u is None or not u.is_authenticated or not u.est_admin:
        return {}
    etape = en_cours()
    if not etape:
        return {}
    return {"mise_en_place": {"etape": etape, "total": DERNIERE, "titre": ETAPES[etape - 1].titre,
                              "url": reverse("parametres:mise_en_place_etape", args=[etape])}}


# ================================================================= vue
def mise_en_place(request, etape=None):
    i = Instance.courante()
    if sans_compte():
        if etape not in (None, 1):
            return redirect("parametres:mise_en_place")
        etape = 1
    else:
        if not request.user.is_authenticated:
            return redirect(f"{reverse('login')}?next={request.path}")
        if not request.user.est_admin:
            raise PermissionDenied(libelle("referentiels.mep.reserve_admin"))
        if i.mise_en_place_terminee:  # l'assistant sert au premier lancement ; ensuite tout est dans Administration
            messages.info(request, libelle("referentiels.mep.deja_terminee"))
            return redirect("collecte:admin_accueil")
        if etape is None:
            return redirect("parametres:mise_en_place_etape", en_cours(i) or 2)
        if not 2 <= etape <= DERNIERE:  # le compte administrateur existe : l'étape 1 est faite
            return redirect("parametres:mise_en_place_etape", 2)
    e = ETAPES[etape - 1]
    traiter, preparer = VUES[e.code]
    ctx = {}
    if request.method == "POST":
        action = request.POST.get("action", "suivant")
        if action == "passer" and e.passer:
            if e.code == "organisation" and not niveaux_confirmes(request):
                messages.error(request, libelle("referentiels.mep.niveaux.a_confirmer"))
                return redirect("parametres:mise_en_place_etape", etape)
            avancer(i, etape)
            return _suivante(request, i, etape, libelle("referentiels.mep.etape_passee"))
        with ESP.atomic():
            resultat = traiter(request, i)
        if resultat is True:  # étape enregistrée
            avancer(i, etape)
            return _suivante(request, i, etape)
        if isinstance(resultat, str):  # rester sur l'étape (action intermédiaire), avec un message
            if resultat:
                messages.success(request, resultat)
            return redirect("parametres:mise_en_place_etape", etape)
        ctx = resultat or {}  # dict : formulaire refusé, à réafficher
    if i.mise_en_place_etape < etape and etape > 1:  # ouverte directement : elle devient l'étape en cours
        i.mise_en_place_etape = etape
        i.save(update_fields=["mise_en_place_etape"])
    return render(request, f"parametres/mise_en_place/{e.code}.html", {
        "page": "mise_en_place", "etape": e, "etapes": ETAPES, "atteinte": max(i.mise_en_place_etape, etape),
        "terminee": i.mise_en_place_terminee, "depart_sauvegarde": depart_sauvegarde_permis(request),
        **preparer(request, i), **ctx})


def depart_sauvegarde_permis(request):
    """« Partir d'une sauvegarde » (version 1.1.1) : proposé à la personne connectée, gestionnaire des espaces
    (le compte créé à l'étape 1 l'est), tant que l'installation est vide (``sauvegardes_ailleurs.installation_vide``).
    Jamais à un visiteur non connecté : l'étape 1 crée d'abord le compte, la porte reste celle d'aujourd'hui."""
    from espaces.comptes import est_gestionnaire

    from .sauvegardes_ailleurs import installation_vide

    return bool(request.user.is_authenticated and est_gestionnaire(request.user) and installation_vide())


def _suivante(request, i, etape, message=""):
    if message:
        messages.info(request, message)
    if etape >= DERNIERE:
        Journal.ecrire(request.user, "reglage_identite", i, "mise en place", "", "terminée")
        messages.success(request, libelle("referentiels.mep.terminee"))
        return redirect("collecte:tableau_de_bord")
    return redirect("parametres:mise_en_place_etape", etape + 1)


# ================================================================= 1. compte administrateur
class CompteAdminForm(forms.Form):
    prenom = forms.CharField(label=_l("referentiels.mep.compte.form.prenom"), max_length=150)
    nom = forms.CharField(label=_l("referentiels.mep.compte.form.nom"), max_length=150)
    email = forms.EmailField(label=_l("referentiels.mep.compte.form.email"),
                             error_messages={"invalid": _l("referentiels.mep.compte.form.email_invalide")})
    mot_de_passe = forms.CharField(label=_l("referentiels.mep.compte.form.mot_de_passe"), strip=False,
                                   widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
    confirmation = forms.CharField(label=_l("referentiels.mep.compte.form.confirmation"), strip=False,
                                   widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))

    def clean(self):
        d = super().clean()
        if d.get("mot_de_passe") and d.get("mot_de_passe") != d.get("confirmation"):
            self.add_error("confirmation", libelle("referentiels.mep.compte.form.mdp_differents"))
        elif d.get("mot_de_passe"):
            try:
                with translation.override(L.interface()):  # messages de Django dans la langue de l'interface
                    password_validation.validate_password(d["mot_de_passe"])
            except ValidationError as e:
                with translation.override(L.interface()):
                    self.add_error("mot_de_passe", list(e.messages))
        return d


# valeurs d'origine du modèle (parametres/models.py, en français) ; les valeurs par défaut des sept langues sont dans
# libelles/referentiels.<langue>.json (« referentiels.mep.defaut.* »)
DEFAUTS_FR = {"nom": "Ma structure", "contact": "l'administrateur de l'outil"}
LANGUES_FOURNIES = ("en", "fr", "es", "de", "it", "nl", "pt")


def defaut_dans_la_langue(instance, champ, langue=None):
    """Valeur de ``champ`` (« nom » ou « contact ») de l'identité à afficher dans ``langue`` (celle de l'interface par
    défaut) : la valeur par défaut de cette langue si la valeur enregistrée est encore une valeur par défaut (d'une des
    sept langues), sinon la valeur enregistrée. N'écrit rien."""
    valeur = getattr(instance, champ)
    connus = {DEFAUTS_FR[champ]} | {libelle(f"referentiels.mep.defaut.{champ}", langue=lg) for lg in LANGUES_FOURNIES}
    return libelle(f"referentiels.mep.defaut.{champ}", langue=langue or L.interface()) if valeur in connus else valeur


def localiser_defauts(instance, langue):
    """Met le nom de la structure et le contact par défaut dans ``langue`` (celle de la personne qui installe, ou la langue
    par défaut choisie à l'étape des langues). Seule une valeur encore égale à une valeur par défaut (d'une des sept
    langues) change : un texte choisi par l'administrateur n'est jamais touché. Vrai si quelque chose a changé."""
    maj = []
    for champ in DEFAUTS_FR:
        nouveau = defaut_dans_la_langue(instance, champ, langue)
        if nouveau != getattr(instance, champ):
            setattr(instance, champ, nouveau)
            maj.append(champ)
    if maj:
        instance.save(update_fields=maj)
    return bool(maj)


def _traiter_compte(request, i):
    from referentiel.models import Utilisateur

    form = CompteAdminForm(request.POST)
    if not form.is_valid():
        return {"form": form}
    d = form.cleaned_data
    email = d["email"].strip().lower()
    u = Utilisateur(username=email, email=email, first_name=d["prenom"].strip(), last_name=d["nom"].strip(),
                    role=Utilisateur.Role.ADMIN, is_staff=True, is_superuser=True)
    u.set_password(d["mot_de_passe"])
    u.save()
    Journal.ecrire(u, "creation_compte", u, "rôle", "", "administrateur (mise en place)")
    login(request, u, backend="referentiel.auth.EmailOuIdentifiant")
    localiser_defauts(i, L.interface())  # valeurs par défaut dans la langue de la personne qui installe
    return True


def _preparer_compte(request, i):
    # nom par défaut, encore celui de la création de l'installation (en français), affiché dans la langue de l'interface
    # (aperçu de la connexion, titre de la page) ; il n'est enregistré dans cette langue qu'à la création du compte
    # (localiser_defauts) : copie en mémoire, jamais enregistrée
    affichee = copy.copy(i)
    affichee.nom = defaut_dans_la_langue(i, "nom")
    return {"form": CompteAdminForm(), "instance": affichee}


# ================================================================= 2. structure
def _traiter_structure(request, i):
    from .views import IdentiteForm, enregistrer_identite

    form = IdentiteForm(request.POST, request.FILES, instance=i)
    if not form.is_valid():
        return {"form": form}
    enregistrer_identite(request.user, form)
    return True


def _preparer_structure(request, i):
    from .views import IdentiteForm, contexte_identite

    ctx = contexte_identite(IdentiteForm(instance=Instance.courante()))
    return ctx


# ================================================================= 3. langues
SUGGESTIONS_LANGUES = [("en", "English"), ("es", "Español"), ("de", "Deutsch"), ("it", "Italiano"), ("pt", "Português"),
                       ("nl", "Nederlands")]


def _traiter_langues(request, i):
    from .vues_langues import action_langues

    action = request.POST.get("action")
    if action == "ajouter":
        if request.POST.get("code_libre", "").strip():
            request.POST = request.POST.copy()
            request.POST["code"] = request.POST["code_libre"].strip()
        erreur = action_langues(request)
        if erreur:
            messages.error(request, erreur)
        return ""
    request.POST = request.POST.copy()
    request.POST["action"] = "enregistrer"
    avant = Instance.courante().langue
    erreur = action_langues(request)
    if erreur:
        messages.error(request, erreur)
        return ""
    apres = Instance.courante()
    if apres.langue != avant:  # nouvelle langue par défaut : les valeurs par défaut de l'identité la suivent
        localiser_defauts(apres, apres.langue)
    return True


def _preparer_langues(request, i):
    existantes = {l.code for l in Langue.objects.all()}
    langues = Langue.objects.all()
    return {"langues": langues, "reference": L.libelle(L.reference()), "code_reference": L.reference(),
            "defaut": L.defaut(), "defaut_libelle": next((lg.libelle for lg in langues if lg.code == L.defaut()), ""), "suggestions": [(c, lib) for c, lib in SUGGESTIONS_LANGUES if c not in existantes]}


# ================================================================= 4. organisation
def modeles_niveaux():
    """Modèles de niveaux proposés (``niveaux.modeles_proposes``) : libellés dans la langue de l'écran, niveaux créés dans
    la langue de référence de l'installation, traduits dans les six autres langues de l'interface (avant la mise à jour :
    en français partout, sans traduction)."""
    return N.modeles_proposes(L.interface(), L.reference())


def niveaux_utilises():
    from collecte.models import RegleCoherence
    from referentiel.models import KPI, Organisation

    return Organisation.objects.exists() or KPI.objects.exists() or RegleCoherence.objects.exists()


def remplacer_niveaux(utilisateur, definitions):
    """Remplace les niveaux de l'arbre (installation où aucun n'est encore utilisé) : [(code ou "", nom, pluriel)], ou
    [(code, nom, pluriel, traductions)] pour un modèle proposé (noms des autres langues de l'interface)."""
    if not 1 <= len(definitions) <= NiveauHierarchique.MAXIMUM:
        raise ValidationError(libelle("referentiels.mep.niveaux.nombre", maximum=NiveauHierarchique.MAXIMUM))
    definitions = [tuple(d) + ({},) * (4 - len(d)) for d in definitions]
    noms = [X.normaliser(d[1]) for d in definitions]
    if len(set(noms)) != len(noms) or not all(noms):
        raise ValidationError(libelle("referentiels.mep.niveaux.noms"))
    if [(n.nom, n.nom_pluriel) for n in N.tous()] == [(nom, pl) for _, nom, pl, _ in definitions]:
        return False
    if niveaux_utilises():
        raise ValidationError(libelle("referentiels.mep.niveaux.utilises"))
    NiveauHierarchique.objects.all().delete()
    for rang, (code, nom, pluriel, traductions) in enumerate(definitions, start=1):
        n = NiveauHierarchique(code=code or N.nouveau_code(nom), rang=rang, nom=nom[:60], nom_pluriel=(pluriel or nom)[:60],
                               couleur=CO.COULEURS_NIVEAUX[(rang - 1) % len(CO.COULEURS_NIVEAUX)],
                               traductions=traductions or {})
        n.deriver_couleurs()
        n.save()
    Journal.ecrire(utilisateur, "reglage_niveaux", Instance.courante(), "niveaux", "", " › ".join(d[1] for d in definitions))
    return True


def _pluriel(nom):
    return nom if nom[-1:].lower() in "sxz" else nom + "s"


def definitions_niveaux(post):
    """Niveaux demandés : un modèle proposé, ou une liste libre (un niveau par ligne, du sommet vers le bas ; « Nom ; Pluriel »)."""
    choix = post.get("modele", "")
    for cle, _, defs in modeles_niveaux():
        if choix == cle:
            return defs
    lignes = [l.strip() for l in post.get("niveaux_libres", "").splitlines() if l.strip()]
    sortie = []
    for l in lignes:
        nom, _, pluriel = (x.strip() for x in l.partition(";"))
        sortie.append(("", nom, pluriel or _pluriel(nom)))
    return sortie


@dataclass
class Noeud:
    nom: str
    niveau: object
    parent: str = ""
    ligne: int = 0
    existe: bool = False
    prof: int = 0  # profondeur dans l'arbre (aperçu)
    ouverture: object = None  # date d'ouverture (« Lyon [2026-03-01] »), ou None
    # (date, nom) : ancêtre ouvert plus tard que l'organisation (ou qu'elle, sans date) : elle ne compte qu'à partir de
    # cette date (une organisation n'est pas ouverte avant son parent, ``calcul.ouverte``), dit dans l'aperçu
    ouverture_parent: object = None


# Coller des organisations (assistant, étape organisation ; Administration › Organisations › « + Plusieurs
# organisations ») : au plus tant de lignes à la fois. Au-delà, l'aperçu devient long à lire
# et à vérifier : mieux vaut découper la liste, ou passer par le fichier de configuration.
MAX_ORGANISATIONS_COLLEES = 500

EXPLICITE = re.compile(r"^(?P<nom>.*?)\s*\[(?P<niveau>[^\]]+)\]\s*$")
# date d'ouverture entre les crochets, seule ou avec le niveau : « Lyon [2026-03-01] », « Lyon [Site, 01/03/2026] »
DATE_CROCHETS = re.compile(r"(?P<date>\d{4}-\d{1,2}-\d{1,2}|\d{1,2}/\d{1,2}/\d{4})")


def _date_crochets(texte):
    """(date, reste) : date d'ouverture écrite entre les crochets (AAAA-MM-JJ ou JJ/MM/AAAA) et ce qui reste (le niveau,
    sans les séparateurs) ; (None, texte) sans date ; ValueError pour une date impossible (31/02/2026)."""
    import datetime

    m = DATE_CROCHETS.search(texte)
    if not m:
        return None, texte
    brute = m.group("date")
    if "-" in brute:
        a, mo, j = (int(x) for x in brute.split("-"))
    else:
        j, mo, a = (int(x) for x in brute.split("/"))
    date = datetime.date(a, mo, j)
    return date, (texte[:m.start()] + texte[m.end():]).strip(" ,;")


def lire_arbre(texte, niveaux):
    """Arbre décrit par saisie rapide ou collé depuis Excel ; (nœuds dans l'ordre, erreurs).

    - Saisie rapide : une organisation par ligne, décalée (espaces, tabulation en début de ligne, ou puces « - ») sous
      celle dont elle dépend ; le décalage donne le niveau. « Nom [Site] » force le niveau (rattachement à un niveau
      supérieur quelconque, ex. un site directement sous la holding). « Groupe > France > Lyon » décrit un chemin.
    - Collage Excel : une colonne par niveau (du sommet vers le bas) ; une cellule vide reprend la valeur du dessus ;
      une ligne d'en-têtes avec les noms des niveaux est ignorée."""
    from referentiel.models import Organisation

    niveaux = list(niveaux)
    par_nom = {}
    for n in niveaux:
        for t in (n.nom, n.nom_pluriel, n.code):
            par_nom[X.normaliser(t)] = n
    existantes = {o.nom: o for o in Organisation.objects.select_related("niveau", "parent")}
    noeuds, erreurs, index = [], [], {}
    chemin = []  # chemin[profondeur] = (nom, niveau)
    pile = []  # largeurs de décalage (saisie rapide)

    def ajouter(num, profondeur, nom, niveau=None):
        nom = nom.strip()[:150]
        if not nom:
            return
        m = EXPLICITE.match(nom)
        ouverture = None
        if m:
            nom = m.group("nom").strip()
            try:
                ouverture, reste = _date_crochets(m.group("niveau"))
            except ValueError:
                erreurs.append(libelle("referentiels.mep.arbre.date_invalide", ligne=num, nom=nom))
                return
            niveau = par_nom.get(X.normaliser(reste)) if reste else niveau
            if reste and niveau is None:
                erreurs.append(libelle("referentiels.mep.arbre.niveau_inconnu", ligne=num, niveau=m.group("niveau"), niveaux=", ".join(n.nom for n in niveaux)))
                return
        parent = None
        while len(chemin) > profondeur:
            chemin.pop()
        if profondeur > len(chemin):
            erreurs.append(libelle("referentiels.mep.arbre.decale", ligne=num, nom=nom))
            return
        if chemin:
            parent = chemin[-1]
        if niveau is None:
            rang = (parent[1].rang + 1) if parent else 1
            niveau = next((n for n in niveaux if n.rang == rang), None)
            if niveau is None:
                erreurs.append(libelle("referentiels.mep.arbre.trop_bas", ligne=num, nom=nom, n=len(niveaux)))
                return
        if parent and parent[1].rang >= niveau.rang:
            erreurs.append(libelle("referentiels.mep.arbre.niveau_plus_bas", ligne=num, nom=nom, niveau=niveau.nom, parent=parent[0], niveau_parent=parent[1].nom))
            return
        if not parent and niveau.rang != 1:
            erreurs.append(libelle("referentiels.mep.arbre.rattacher", ligne=num, nom=nom, niveau=niveau.nom))
            return
        parent_nom = parent[0] if parent else ""
        if nom in index:
            deja = index[nom]
            if (deja.niveau.code, deja.parent) != (niveau.code, parent_nom):
                erreurs.append(libelle("referentiels.mep.arbre.deux_fois", ligne=num, nom=nom))
                return
        else:
            o = existantes.get(nom)
            if o is not None and (o.niveau_id != niveau.code or (o.parent.nom if o.parent_id else "") != parent_nom):
                erreurs.append(libelle("referentiels.mep.arbre.existe_ailleurs", ligne=num, nom=nom, niveau=o.niveau.nom))
                return
            index[nom] = Noeud(nom, niveau, parent_nom, num, existe=o is not None, prof=len(chemin), ouverture=ouverture)
            noeuds.append(index[nom])
        chemin.append((nom, niveau))

    lignes = [l for l in (texte or "").replace("\r", "").split("\n")]
    colle = sum("\t" in l.strip("\t ") for l in lignes if l.strip()) > 0
    utiles = [l for l in lignes if l.strip()]
    if colle and utiles and all(not c.strip() or X.normaliser(c.strip()) in par_nom for c in utiles[0].split("\t")):
        utiles = utiles[1:]  # ligne d'en-têtes : pas une organisation
    if len(utiles) > MAX_ORGANISATIONS_COLLEES:  # tout refusé : rien n'est lu ni créé
        return [], [libelle("referentiels.mep.arbre.trop_de_lignes", maximum=MAX_ORGANISATIONS_COLLEES, n=len(utiles))]
    precedente = []
    for num, brute in enumerate(lignes, start=1):
        if not brute.strip():
            continue
        if colle:  # une colonne par niveau
            cellules = [c.strip() for c in brute.split("\t")]
            if num == next(k for k, l in enumerate(lignes, start=1) if l.strip()) and all(
                    not c or X.normaliser(c) in par_nom for c in cellules):
                continue  # en-têtes
            # cellules vides avant la première remplie : valeurs de la ligne précédente
            premiere = next((j for j, c in enumerate(cellules) if c), len(cellules))
            remplies = (precedente[:premiere] + [""] * premiere)[:premiere] + cellules[premiere:]
            precedente = remplies
            chemin.clear()
            profondeur = 0
            for j, c in enumerate(remplies):
                if not c:
                    continue
                niveau = niveaux[j] if j < len(niveaux) else None
                if niveau is None:
                    erreurs.append(libelle("referentiels.mep.arbre.trop_colonnes", ligne=num, n=len(niveaux)))
                    break
                ajouter(num, profondeur, c, niveau)
                if len(chemin) > profondeur:  # ajoutée (le nom lu peut différer de la cellule : « Lyon [2026-03-01] »)
                    profondeur += 1
            continue
        if ">" in brute or "›" in brute:  # chemin « Groupe > France > Lyon »
            chemin.clear()
            pile.clear()
            for profondeur, morceau in enumerate(re.split(r"\s*[>›]\s*", brute.strip())):
                ajouter(num, profondeur, morceau)
            continue
        decalage = len(brute.expandtabs(4)) - len(brute.expandtabs(4).lstrip(" "))
        nom = brute.strip().lstrip("-*•·").strip()
        while pile and pile[-1] >= decalage:
            pile.pop()
        profondeur = len(pile)
        pile.append(decalage)
        ajouter(num, profondeur, nom)
    for x in noeuds:  # date d'ouverture d'un ancêtre plus tardive (collé ou existant) : elle vaut pour l'organisation
        if x.existe:
            continue
        date, nom_parent, p, vus = x.ouverture, None, x.parent, set()
        while p and p not in vus:
            vus.add(p)
            n, o = index.get(p), existantes.get(p)
            d = n.ouverture if n is not None and not n.existe else (o.date_ouverture if o is not None else None)
            if d and (date is None or d > date):
                date, nom_parent = d, p
            p = n.parent if n is not None else (o.parent.nom if o is not None and o.parent_id else "")
        if nom_parent:
            x.ouverture_parent = (date, nom_parent)
    return noeuds, erreurs


def creer_arbre(utilisateur, noeuds):
    """Crée les organisations nouvelles de l'arbre lu (les existantes sont gardées) ; renvoie le nombre créé."""
    from referentiel.models import Organisation

    orgs = {o.nom: o for o in Organisation.objects.all()}
    rangs, n = {}, 0
    for x in noeuds:
        if x.nom in orgs:
            continue
        parent = orgs.get(x.parent) if x.parent else None
        rangs[x.parent] = rangs.get(x.parent, (Organisation.objects.filter(parent=parent).aggregate(m=Max("rang"))["m"] or 0)) + 1
        o = Organisation.objects.create(nom=x.nom, niveau=x.niveau, parent=parent, rang=rangs[x.parent],
                                        date_ouverture=x.ouverture)
        Journal.ecrire(utilisateur, "creation_organisation", o, "niveau", "", x.niveau.nom)
        if x.ouverture:
            Journal.ecrire(utilisateur, "creation_organisation", o, "date_ouverture", "", x.ouverture)
        orgs[x.nom] = o
        n += 1
    return n


CLE_NIVEAUX_CONFIRMES = "mise_en_place_niveaux_confirmes"


def niveaux_confirmes(request):
    """Les niveaux de l'arbre sont confirmés : bouton « Confirmer ces niveaux » de l'étape 4, ou
    niveaux déjà utilisés par des organisations ou des KPI (plus modifiables ici). Sans cela, ni « Créer ces
    organisations », ni « Enregistrer et continuer », ni « Passer »."""
    return bool(request.session.get(CLE_NIVEAUX_CONFIRMES)) or niveaux_utilises()


def _traiter_organisation(request, i):
    action = request.POST.get("action")
    if action == "niveaux":
        try:
            change = remplacer_niveaux(request.user, definitions_niveaux(request.POST))
        except ValidationError as e:
            messages.error(request, " ".join(e.messages))
            return ""
        request.session[CLE_NIVEAUX_CONFIRMES] = True
        return libelle("referentiels.mep.niveaux.enregistres") if change else libelle("referentiels.mep.niveaux.inchanges")
    texte = request.POST.get("arbre", "")
    if action != "apercu" and not niveaux_confirmes(request):
        messages.error(request, libelle("referentiels.mep.niveaux.a_confirmer"))
        return {"texte_arbre": texte}
    noeuds, erreurs = lire_arbre(texte, N.tous())
    if action == "apercu" or erreurs:
        return {"texte_arbre": texte, "noeuds_lus": noeuds, "erreurs_arbre": erreurs}
    n = creer_arbre(request.user, noeuds)
    if action == "creer":
        return libelle("referentiels.mep.organisations_creees", n=n)
    if n:
        messages.success(request, libelle("referentiels.mep.organisations_creees", n=n))
    from referentiel.models import Organisation

    if not Organisation.objects.exists():
        messages.error(request, libelle("referentiels.mep.organisation_requise"))
        return ""
    return True


def _preparer_organisation(request, i):
    from collecte import saisie as S

    niveaux = N.tous()
    actuel = [(n.code, n.nom, n.nom_pluriel) for n in niveaux]
    modeles = modeles_niveaux()
    modele = next((cle for cle, _, defs in modeles if [d[1:3] for d in defs] == [a[1:] for a in actuel]), "")
    orgs = sorted(S.arbre_organisations().values(), key=S.cle_arbre)
    return {"niveaux": niveaux, "modeles_niveaux": modeles, "modele_actuel": modele, "niveaux_figes": niveaux_utilises(),
            "niveaux_confirmes": niveaux_confirmes(request),
            "niveaux_chaine": " › ".join(n.nom for n in niveaux), "niveaux_liste": ", ".join(n.nom for n in niveaux),
            "niveaux_libres": "\n".join(f"{n.nom} ; {n.nom_pluriel}" for n in niveaux), "orgs": orgs,
            "exemple_arbre": exemple_arbre(niveaux), "limite_arbre": MAX_ORGANISATIONS_COLLEES}


def exemple_arbre(niveaux):
    lignes = [("  " * (n.rang - 1)) + (libelle(f"referentiels.mep.organisation.exemple.{n.rang}") if n.rang <= 4 else f"{n.nom} 1")
              for n in niveaux[:4]]
    return "\n".join(lignes)


# ================================================================= 5. référentiels
def _traiter_referentiels(request, i):
    from referentiel.models import Referentiel

    from .vues_referentiels import ajouter_referentiel

    action = request.POST.get("action")
    if action == "zero":
        try:
            ajouter_referentiel(request)
        except ValidationError as e:
            messages.error(request, " ".join(e.messages))
        return ""
    n = 0
    for r in Referentiel.objects.annotate(nb=Count("campagnes")):
        f, m = request.POST.get(f"frequence__{r.code}"), request.POST.get(f"mois_debut__{r.code}", "")
        if r.nb or f not in dict(Referentiel._meta.get_field("frequence").choices) or not m.isdecimal() or not 1 <= int(m) <= 12:
            continue
        if (f, int(m)) != (r.frequence, r.mois_debut):
            Journal.ecrire(request.user, "reglage_referentiels", r, "fréquence", f"{r.frequence} ({r.mois_debut})", f"{f} ({m})")
            r.frequence, r.mois_debut = f, int(m)
            r.save(update_fields=["frequence", "mois_debut"])
            n += 1
    if not Referentiel.objects.filter(actif=True).exists():
        messages.error(request, libelle("referentiels.mep.referentiel_requis"))
        return ""
    return True


def _preparer_referentiels(request, i):
    from collecte import paquets as P

    from .vues_referentiels import referentiels_annotes, frequences_choix, mois_choix, origine_texte

    refs = referentiels_annotes()  # nombres de KPI et de campagnes sans jointures multipliées
    for r in refs:
        r.origine_texte = origine_texte(r)
    apercu = None
    if refs:
        apercu = (refs[0], P.themes_ordonnes(refs[0])[:12])
    from .vues_installation import contexte_portes

    return {**contexte_portes(), "referentiels": refs, "frequences": frequences_choix(),
            "mois": mois_choix(), "apercu_ref": apercu}


# ================================================================= 6. fiche indicateur
def _traiter_fiche(request, i):
    for c in CategorieDescription.objects.all():
        affichee, obligatoire = f"affichee__{c.code}" in request.POST, f"obligatoire__{c.code}" in request.POST
        if (affichee, obligatoire) != (c.affichee, c.obligatoire):
            Journal.ecrire(request.user, "reglage_referentiel", c, "affichée / obligatoire", f"{c.affichee} / {c.obligatoire}",
                           f"{affichee} / {obligatoire}")
            c.affichee, c.obligatoire = affichee, obligatoire
            c.save(update_fields=["affichee", "obligatoire"])
    return True


def _preparer_fiche(request, i):
    return {"categories": CategorieDescription.objects.all(), "unites": Unite.objects.all(), "types_saisie": TypeSaisie.objects.all(),
            "types_reponse": TypeReponse.objects.all(), "champs": ChampPersonnalise.objects.all()}


# ================================================================= 7. équipe
NB_LIGNES_EQUIPE = 5


def creer_comptes(request, nb_lignes):
    """Comptes des lignes remplies du formulaire (prénom, nom, e-mail, rôle) : (créés [(compte, mot de passe)], erreurs).
    Sert à l'étape « Équipe » et à Administration › Comptes › Plusieurs comptes."""
    from collecte.administration import CompteForm, donner_mot_de_passe, rattache

    crees, erreurs = [], []
    for k in range(nb_lignes):
        valeurs = {c: request.POST.get(f"{c}_{k}", "").strip() for c in ("first_name", "last_name", "email", "role")}
        if not any(valeurs[c] for c in ("first_name", "last_name", "email")):
            continue
        form = CompteForm({**valeurs, "is_active": "on", "equipe": ""}, moi=request.user)
        if not form.is_valid():
            erreurs.append(libelle("referentiels.mep.equipe.erreur_ligne", ligne=k + 1, qui=valeurs["email"] or valeurs["first_name"],
                                   erreurs=" ".join(m for ms in form.errors.values() for m in ms)))
            continue
        u = form.save()
        Journal.ecrire(request.user, "creation_compte", u, "rôle", "", u.get_role_display())
        crees.append((u, None if rattache(u) else donner_mot_de_passe(u)))
    return crees, erreurs


def _traiter_equipe(request, i):
    crees, erreurs = creer_comptes(request, NB_LIGNES_EQUIPE)
    if erreurs or crees:
        return {"crees": crees, "erreurs_equipe": erreurs, "post": request.POST if erreurs else {}}
    return True


def _preparer_equipe(request, i):
    from collecte.administration import ROLES_EXPLIQUES
    from referentiel.models import Utilisateur

    comptes = Utilisateur.objects.order_by("first_name", "last_name")
    return {"comptes": comptes, "comptes_texte": ", ".join(str(u) for u in comptes), "roles": ROLES_EXPLIQUES,
            "lignes": range(NB_LIGNES_EQUIPE), "adresse": request.build_absolute_uri(reverse("collecte:accueil"))}


# ================================================================= 8. première campagne
def _traiter_campagne(request, i):
    from collecte.administration import CampagneForm, changer_statut
    from collecte.calcul import recalculer

    form = CampagneForm(request.POST, instance=_campagne_vide())
    if not form.is_valid():
        return {"form": form}
    creees = form.creer()
    if not creees:
        form.add_error(None, libelle("referentiels.mep.campagne.existe_deja"))
        return {"form": form}
    for c in creees:
        Journal.ecrire(request.user, "creation_campagne", c, "statut", "", "en préparation")
        recalculer(c)
        if request.POST.get("ouvrir") == "on":
            changer_statut(request.user, c, "ouvrir")
    return True


def _campagne_vide():
    from collecte.models import Campagne

    return Campagne()


def proposition_campagne(referentiel=None):
    """Période en cours du référentiel ; saisie ouverte dès aujourd'hui pour deux mois."""
    from collecte.administration import suggestion_campagne

    d = suggestion_campagne(referentiel)
    aujourdhui = timezone.localdate()
    if d:
        d.update(date_ouverture=aujourdhui, date_fin_saisie=aujourdhui + datetime.timedelta(days=60), seuil_pct=20)
    return d


def _preparer_campagne(request, i):
    from collecte.administration import CampagneForm, rangs_par_frequence
    from referentiel.models import Referentiel

    ref = Referentiel.objects.filter(actif=True).order_by("ordre", "code").first()
    form = CampagneForm(instance=_campagne_vide(), initial=proposition_campagne(ref))
    from collecte.models import Campagne

    campagnes = Campagne.objects.select_related("referentiel", "periode")
    return {"form": form, "ref_propose": ref, "rangs": rangs_par_frequence(), "frequences": {r.pk: r.frequence for r in Referentiel.objects.all()},
            "sans_referentiel": ref is None,
            "campagnes_texte": ", ".join(f"{c.nom_complet} ({LB.choix_phrase(c, 'statut')})" for c in campagnes)}


VUES = {
    "compte": (_traiter_compte, _preparer_compte), "structure": (_traiter_structure, _preparer_structure),
    "langues": (_traiter_langues, _preparer_langues), "organisation": (_traiter_organisation, _preparer_organisation),
    "referentiels": (_traiter_referentiels, _preparer_referentiels), "fiche": (_traiter_fiche, _preparer_fiche),
    "equipe": (_traiter_equipe, _preparer_equipe), "campagne": (_traiter_campagne, _preparer_campagne),
}
