"""Langues des contenus : langue courante (celle de l'utilisateur, ou celle choisie pour un export), textes traduits
avec repli, valeurs de listes, thèmes, complétude des traductions. Langue de l'interface (menus, boutons, messages :
fichiers de langue de ``parametres.libelles``), choisie par la personne dans la barre du haut ou dans Mon compte.

Repli d'un texte absent : langue demandée → langue par défaut → langue de référence → première langue où il existe.
Hors requête (commandes, tests), la langue courante est la langue par défaut : tout s'affiche comme avant.

Une seule préférence par personne (``Utilisateur.langue``, ou ``request.session["langue"]`` pour un visiteur et pour le
choix fait dans la barre du haut) règle les deux : l'interface si la langue a des fichiers de langue (français, anglais,
espagnol…), les contenus si c'est une langue active des contenus (Paramètres › Langues) ; sinon, chacune se replie sur la
langue par défaut de l'installation, puis sur le français.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from django.conf import settings

_etat = ContextVar("etat_langues", default=None)
_courante = ContextVar("langue_courante", default=None)
_interface = ContextVar("langue_interface", default=None)
_requete = ContextVar("requete_langues", default=None)  # requête en cours : langue du formulaire envoyé (``saisie``)
CLE_SESSION = "langue"  # choix fait dans la barre du haut (visiteur ou personne connectée)
CHAMP_SAISIE = "langue_saisie"  # champ caché des formulaires de saisie : langue de l'interface à leur affichage


@dataclass
class Etat:
    reference: str
    defaut: str
    langues: list  # toutes les langues (objets Langue), dans l'ordre

    @property
    def actives(self):
        return [l for l in self.langues if l.active or l.code in (self.reference, self.defaut)]

    @property
    def codes_actifs(self):
        return [l.code for l in self.actives]

    @property
    def ordre(self):
        return [l.code for l in self.langues]

    def libelle(self, code):
        return next((l.libelle for l in self.langues if l.code == code), code)


def calculer():
    from .models import Instance, Langue

    i = Instance.courante()
    return Etat(reference=i.langue_reference or "fr", defaut=i.langue or i.langue_reference or settings.LANGUE_PAR_DEFAUT, langues=list(Langue.objects.all()))


def etat():
    """État des langues : figé pour la durée d'une requête (middleware), relu sinon."""
    return _etat.get() or calculer()


@contextmanager
def session():
    """Lit l'état des langues une fois pour un traitement long (export, commande)."""
    if _etat.get() is not None:
        yield _etat.get()
        return
    jeton = _etat.set(calculer())
    try:
        yield _etat.get()
    finally:
        _etat.reset(jeton)


def courante():
    return _courante.get() or etat().defaut


@contextmanager
def activer(code):
    """Affiche les contenus dans ``code`` le temps du bloc (export dans une langue choisie) ; l'interface suit
    (``interface_de(code)``) quand une langue est donnée, sinon elle ne change pas."""
    jeton = _courante.set(code or None)
    jeton_i = _interface.set(interface_de(code)) if code else None
    try:
        yield
    finally:
        if jeton_i is not None:
            _interface.reset(jeton_i)
        _courante.reset(jeton)


def reference():
    return etat().reference


def defaut():
    return etat().defaut


def actives():
    return etat().actives


def codes_actifs():
    return etat().codes_actifs


def langues_a_traduire():
    """Codes des langues actives hors langue de référence."""
    ref = reference()
    return [c for c in codes_actifs() if c != ref]


def libelle(code):
    return etat().libelle(code)


def champs_reference():
    """Pour un écran de réglages dont les champs de saisie portent la langue de référence : ``{"reference": nom de cette
    langue, "ecran": nom de la langue des noms affichés, "different": True si les deux ne sont pas la même langue}``.
    Quand elles diffèrent, l'écran dit sur quoi porte chaque champ et montre la traduction à côté."""
    e = etat()
    ecran = courante()
    return {"reference": e.libelle(e.reference), "ecran": e.libelle(ecran), "different": ecran != e.reference}


def ligne_traduction(obj, *champs):
    """Traduction d'un élément dans la langue de l'écran, en une ligne (« Español : Grupo · Grupos ») : les textes de
    ``champs`` tels qu'enregistrés dans cette langue, sans repli, pour ne jamais prendre la langue de référence pour une
    traduction. Lecture seule : on la modifie dans Paramètres › Langues."""
    from .libelles import libelle

    e = etat()
    ecran = courante()
    textes = [texte(obj, c, ecran, e.reference) for c in champs]
    morceau = " · ".join(t for t in textes if t) or libelle("admin.reference.traduction_manquante")
    return libelle("admin.reference.traduction", nom_langue=e.libelle(ecran), texte=morceau)


def suffixe(code):
    """Suffixe d'en-tête de colonne : « (FR) », « (PT-BR) »."""
    return f"({code.upper()})"


# ---------------------------------------------------------------- textes
def texte(obj, champ, langue, ref=None):
    """Texte tel qu'enregistré dans une langue (vide s'il n'y est pas), sans repli."""
    if langue == (ref or reference()):
        return getattr(obj, champ, "") or ""
    return ((obj.traductions or {}).get(langue) or {}).get(champ, "") or ""


def langues_candidates(langue, e=None):
    e = e or etat()
    vus = []
    for l in (langue or courante(), e.defaut, e.reference, *e.ordre):
        if l and l not in vus:
            vus.append(l)
    return vus


def traduire(obj, champ, langue=None):
    """Texte dans la langue demandée (par défaut la langue courante), avec repli."""
    e = etat()
    for l in langues_candidates(langue, e):
        t = texte(obj, champ, l, e.reference)
        if t:
            return t
    for l, d in (obj.traductions or {}).items():  # langue supprimée de la liste, texte conservé
        if (d or {}).get(champ):
            return d[champ]
    return ""


def definir(obj, champ, langue, valeur):
    """Écrit le texte d'une langue (sans enregistrer l'objet) : le champ lui-même pour la langue de référence."""
    valeur = (valeur or "").strip()
    if langue == reference():
        setattr(obj, champ, valeur)
        return
    trad = dict(obj.traductions or {})
    d = dict(trad.get(langue) or {})
    if valeur:
        d[champ] = valeur
    else:
        d.pop(champ, None)
    if d:
        trad[langue] = d
    else:
        trad.pop(langue, None)
    obj.traductions = trad


def a_traduire(obj, champ, langue):
    """Le texte existe dans une langue mais pas dans celle-ci."""
    return not texte(obj, champ, langue) and bool(traduire(obj, champ, reference()))


# ---------------------------------------------------------------- valeurs de listes (traduites par position)
def valeurs_langue(obj, langue):
    return list(((obj.traductions or {}).get(langue) or {}).get("valeurs") or [])


def valeurs(obj, cles, langue=None):
    """[(clé stockée, texte affiché)] : la réponse garde sa clé, l'affichage suit la langue."""
    e = etat()
    candidates = langues_candidates(langue, e)
    sortie = []
    for i, cle in enumerate(cles):
        texte_ = ""
        for l in candidates:
            tl = valeurs_langue(obj, l)
            texte_ = (tl[i] if i < len(tl) else "") or (cle if l == e.reference else "")
            if texte_:
                break
        sortie.append((cle, texte_ or cle))
    return sortie


def valeur(obj, cles, cle, langue=None):
    """Texte affiché d'une réponse de liste (la clé si elle n'est plus dans la liste)."""
    return dict(valeurs(obj, cles, langue)).get(cle, cle)


def definir_valeurs(obj, langue, textes, nb):
    """Traductions des valeurs d'une liste dans une langue (hors référence), alignées sur les ``nb`` clés."""
    textes = [(t or "").strip() for t in list(textes)[:nb]]
    textes += [""] * (nb - len(textes))
    trad = dict(obj.traductions or {})
    d = dict(trad.get(langue) or {})
    if any(textes):
        d["valeurs"] = textes
    else:
        d.pop("valeurs", None)
    if d:
        trad[langue] = d
    else:
        trad.pop(langue, None)
    obj.traductions = trad


def cle_valeur(obj, cles, saisi):
    """Clé d'une réponse écrite dans n'importe quelle langue (import, saisie), sans tenir compte de la casse ; None sinon."""
    s = (saisi or "").strip().lower()
    if not s:
        return None
    for i, cle in enumerate(cles):
        if cle.strip().lower() == s:
            return cle
    for d in (obj.traductions or {}).values():
        tl = (d or {}).get("valeurs") or []
        for i, t in enumerate(tl[:len(cles)]):
            if t and t.strip().lower() == s:
                return cles[i]
    return None


# ---------------------------------------------------------------- éléments traduisibles
def modeles():
    """(clé, titre, modèle) des éléments traduisibles hors KPI et thèmes, dans l'ordre de la page « Traductions »."""
    from referentiel.models import ElementReferentiel, Referentiel

    from . import libelles as LB
    from .models import CategorieDescription, ChampPersonnalise, NiveauHierarchique, TypeReponse, TypeSaisie, Unite

    return [("referentiels", LB.libelle("cadre.langues.modele.referentiels"), Referentiel), ("elements", LB.libelle("cadre.langues.modele.elements"), ElementReferentiel),
            ("niveaux", LB.libelle("cadre.langues.modele.niveaux"), NiveauHierarchique), ("unites", LB.libelle("cadre.langues.modele.unites"), Unite),
            ("types-saisie", LB.libelle("cadre.langues.modele.types_saisie"), TypeSaisie), ("types-reponse", LB.libelle("cadre.langues.modele.types_reponse"), TypeReponse),
            ("categories", LB.libelle("cadre.langues.modele.categories"), CategorieDescription), ("champs", LB.libelle("cadre.langues.modele.champs"), ChampPersonnalise)]


def cles_valeurs(obj):
    """Clés des valeurs d'une liste (types de réponse oui / non ou liste, champs personnalisés liste), sinon []."""
    if hasattr(obj, "choix") and not callable(obj.choix):
        return obj.choix
    if getattr(obj, "type", None) == "liste":
        return list(obj.valeurs)
    return []


def langues_utilisees():
    """Codes de langue présents dans des traductions, des descriptions ou les préférences des comptes."""
    from referentiel.models import KPI, Description, Theme, Utilisateur

    codes = set(Description.objects.values_list("langue", flat=True).distinct())
    codes |= set(Utilisateur.objects.exclude(langue="").values_list("langue", flat=True).distinct())
    for _, _, modele in modeles() + [("kpi", "", KPI), ("themes", "", Theme)]:
        for t in modele.objects.exclude(traductions={}).values_list("traductions", flat=True):
            codes |= set((t or {}).keys())
    return codes


# ---------------------------------------------------------------- langue de l'interface
def langues_interface():
    """Codes des langues de l'interface (celles qui ont des fichiers de langue), langue de base d'abord : ["en", "es", "fr"]."""
    from . import libelles as LB

    codes = LB.langues_disponibles()
    return sorted(codes, key=lambda c: (c != LB.REPLI, c))


def interface_de(choisie, e=None):
    """Langue de l'interface pour une préférence (« es », « pt-BR », « » …) : elle-même, sa langue de base, la langue par
    défaut de l'installation, puis l'anglais (langue de base)."""
    from . import libelles as LB

    dispo = langues_interface()
    try:
        defaut_ = (e or etat()).defaut
    except Exception:  # noqa: BLE001 - base pas encore prête (migrations) : langue par défaut des installations
        defaut_ = settings.LANGUE_PAR_DEFAUT
    for l in (choisie, (choisie or "").split("-")[0], defaut_, (defaut_ or "").split("-")[0]):
        if l and l in dispo:
            return l
    return LB.REPLI


def interface():
    """Langue de l'interface en cours (celle de la personne pendant une requête, sinon celle de l'installation)."""
    return _interface.get() or interface_de("")


@contextmanager
def activer_interface(code):
    """Libellés de l'interface dans ``code`` le temps du bloc (e-mail à une personne, export dans une langue choisie)."""
    jeton = _interface.set(interface_de(code) if code else None)
    try:
        yield
    finally:
        _interface.reset(jeton)


@contextmanager
def formulaire(request):
    """Le bloc traite la requête ``request`` : ``saisie`` y lit la langue du formulaire envoyé."""
    jeton = _requete.set(request)
    try:
        yield
    finally:
        _requete.reset(jeton)


def saisie():
    """Langue dans laquelle les nombres tapés ont été affichés : celle du formulaire envoyé (champ caché ``CHAMP_SAISIE``,
    posé à l'affichage), si c'est une langue de l'interface ; sinon la langue de l'interface en cours. La langue de la
    session peut avoir changé depuis l'affichage (autre onglet, Mon compte) : « 2,125 » affiché en français reste 2,125,
    jamais 2125 lu en anglais. Lu seulement d'un envoi (POST), au moment de lire le nombre (après la lecture du formulaire
    par la vue)."""
    r = _requete.get()
    if r is not None and r.method == "POST":
        try:
            code = r.POST.get(CHAMP_SAISIE, "")
        except Exception:  # noqa: BLE001 - corps illisible ou déjà lu en flux : langue en cours
            code = ""
        if code and code in langues_interface():
            return code
    return interface()


def preference(utilisateur):
    """Langue choisie par une personne (« » : celle de l'installation)."""
    return getattr(utilisateur, "langue", "") or ""


@contextmanager
def pour(utilisateur):
    """Interface et contenus dans la langue d'une personne (e-mail de relance, message qui lui est destiné)."""
    choisie = preference(utilisateur)
    with activer(choisie if choisie in codes_actifs() else None), activer_interface(choisie or None):
        yield


def choix_requete(request):
    """Préférence de langue pour une requête : le choix de la barre du haut (session), sinon celui du compte."""
    session = getattr(request, "session", None)
    choisie = session.get(CLE_SESSION, "") if session is not None else ""
    if not choisie:
        u = getattr(request, "user", None)
        choisie = preference(u) if u is not None and u.is_authenticated else ""
    return choisie


class LangueMiddleware:
    """Fige l'état des langues pour la requête et choisit la langue des contenus (celle de la personne si elle est
    active, sinon la langue par défaut de l'installation) et celle de l'interface (voir ``interface_de``)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # supervision : sans langue, ni base (base illisible : 503, pas 500) ; la page « Santé » de l'Administration, elle,
        # suit la langue de la personne
        if request.path_info.endswith("/sante/") and not request.path_info.startswith("/administration/"):
            return self.get_response(request)
        e = calculer()
        j1 = _etat.set(e)
        choisie = choix_requete(request)
        j2 = _courante.set(choisie if choisie in e.codes_actifs else None)
        j3 = _interface.set(interface_de(choisie, e))
        j4 = _requete.set(request)
        try:
            if request.path_info.startswith("/admin/"):  # mode expert : en français, comme ses libellés
                return self.get_response(request)
            # format des nombres et des dates de Django dans la langue de l'interface
            # (« 1 234,5 » en français, « 1,234.5 » en anglais, « 1.234,5 » en espagnol), messages de Django compris
            from django.utils import translation

            with translation.override(_interface.get()):
                return self.get_response(request)
        finally:
            _requete.reset(j4)
            _interface.reset(j3)
            _courante.reset(j2)
            _etat.reset(j1)
