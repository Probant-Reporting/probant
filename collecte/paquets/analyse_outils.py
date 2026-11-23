"""Paquet référentiel : structures et outils communs de l'analyse (aperçu avant import)."""
from dataclasses import dataclass, field

from parametres import langues as L
from parametres import libelles as LB
from parametres import rapprochement_unites as RU
from parametres.models import TypeReponse, TypeSaisie, Unite
from referentiel.models import Referentiel

from .. import fichiers as X

from .modele import AUTO, Paquet, _t
from .excel_ecriture import CHAMPS_REFERENTIEL, _cellule


# ================================================================= analyse (aperçu)
@dataclass
class LigneKpi:
    code: str  # code dans le paquet
    nom: str
    statut: str = "nouveau"  # nouveau, inchange, modifie, conflit, rejet
    choix: str = "creer"  # creer, mettre_a_jour, garder, reutiliser, renommer, ignorer
    options: list = field(default_factory=list)  # [(valeur, libellé)]
    code_final: str = ""  # code dans l'installation après import
    nouveau_code: str = ""  # proposé pour « renommer »
    diff_kpi: list = field(default_factory=list)  # [(libellé, avant, après)] de la définition du KPI
    diff_place: list = field(default_factory=list)  # … de sa place dans le référentiel (mise à jour)
    motif: str = ""
    dans_referentiel: bool = True
    theme: str = ""  # chemin lisible dans le paquet
    aussi_dans: list = field(default_factory=list)  # autres référentiels de l'installation qui contiennent ce KPI
    local: object = None  # KPI existant
    donnees: dict = None  # ligne du paquet
    cible: object = None  # KPI à enregistrer (créé ou modifié), en mémoire
    descriptions: dict = field(default_factory=dict)  # {langue: {catégorie: texte}} à enregistrer
    element: dict = None  # place à enregistrer : {theme, ordre, libelle, obligatoire}
    element_local: object = None
    niveau_auto: bool = False  # niveau de saisie choisi par l'outil (le paquet n'en donnait pas)
    # modèle de la bibliothèque, KPI déjà installé à l'identique : nom qu'il ajoute dans la langue de référence, sans rien
    # remplacer ({"libelle": {langue: texte}}, ``textes_ajoutes``)
    ajouts: dict = field(default_factory=dict)

    @property
    def differences(self):
        return self.diff_kpi + self.diff_place

    @property
    def ecrit(self):
        """La définition du KPI est enregistrée (création, ou mise à jour d'un KPI qui diffère)."""
        return self.statut != "rejet" and (self.choix in ("creer", "renommer") or (self.choix == "mettre_a_jour" and bool(self.diff_kpi)))

    @property
    def place(self):
        """Le KPI prend (ou garde) sa place dans le référentiel."""
        return self.dans_referentiel and self.statut != "rejet" and self.choix != "ignorer"

    @property
    def ajoute(self):
        """Le KPI entre dans le référentiel (il n'y était pas)."""
        return self.place and self.element is not None and self.element_local is None


@dataclass
class Reglage:
    genre: str
    code: str  # dans le paquet
    libelle: str
    action: str  # repris, cree
    code_local: str
    libelle_local: str = ""
    motif: str = ""
    objet: object = None  # à créer
    ajouts: dict = field(default_factory=dict)  # modèle de la bibliothèque, réglage repris : textes ajoutés (``ajouts_type_reponse``)


@dataclass
class Analyse:
    paquet: Paquet
    source: str = ""
    fourni: bool = False
    erreur: str = ""
    mode: str = "nouveau"  # nouveau, mise_a_jour
    existant: object = None  # référentiel mis à jour
    candidat: object = None  # référentiel de l'installation qui pourrait être mis à jour (même identifiant ou même code)
    reconnu: bool = False  # même identifiant : c'est une autre version du même référentiel
    code: str = ""  # code du référentiel après import
    code_propose: str = ""
    comparaison_version: int = 0
    referentiel_differences: list = field(default_factory=list)
    niveaux: list = field(default_factory=list)  # [(niveau du paquet, code local, motif, utilisé)]
    options_niveaux: list = field(default_factory=list)
    reglages: list = field(default_factory=list)  # [Reglage]
    langues_creees: list = field(default_factory=list)
    kpis: list = field(default_factory=list)  # [LigneKpi]
    retires: list = field(default_factory=list)  # [ElementReferentiel] absents du paquet (mise à jour)
    retirer_absents: bool = False
    themes: list = field(default_factory=list)  # [{code, nom, statut, differences, objet, parent}]
    themes_absents: list = field(default_factory=list)
    regles: list = field(default_factory=list)  # [{nom, nom_final, statut, differences, motif, objet}]
    avertissements: list = field(default_factory=list)
    renommages: dict = field(default_factory=dict)  # code du paquet → code dans l'installation
    # KPI d'un modèle de la bibliothèque déjà dans l'installation, qui gardent leur unité monétaire (le modèle est écrit
    # dans une autre monnaie de référence : parametres/monnaies.py)
    unites_gardees: list = field(default_factory=list)

    def kpis_statut(self, statut):
        return [l for l in self.kpis if l.statut == statut]

    @property
    def compteurs(self):
        c = {s: 0 for s in ("nouveau", "modifie", "conflit", "inchange", "rejet")}
        for l in self.kpis:
            c[l.statut] += 1
        c["retire"] = len(self.retires)
        c["ajoute"] = sum(1 for l in self.kpis if l.ajoute)
        return c

    @property
    def nb_dans_referentiel(self):
        return sum(1 for l in self.kpis if l.place)

    @property
    def reglages_crees(self):
        return [r for r in self.reglages if r.action == "cree"]

    @property
    def themes_a_ecrire(self):
        return [t for t in self.themes if t["statut"] in ("nouveau", "modifie")]

    @property
    def regles_a_ecrire(self):
        return [r for r in self.regles if r["statut"] in ("nouveau", "modifie", "renomme")]

    @property
    def aucune_difference(self):
        """Réimportation à l'identique : rien ne serait écrit."""
        return (self.mode == "mise_a_jour" and not self.referentiel_differences and not self.reglages_crees
                and not self.langues_creees and all(l.statut == "inchange" and not l.ajoute for l in self.kpis) and not self.retires
                and not self.themes_a_ecrire and not self.regles_a_ecrire)


def _norm_textes(textes):
    return {X.normaliser(t) for t in (textes or {}).values() if t}


def _libelles_obj(obj, *champs):
    """Textes normalisés d'un objet de l'installation (référence et traductions)."""
    sortie = set()
    for c in champs:
        sortie.add(X.normaliser(getattr(obj, c, "") or ""))
        for d in (obj.traductions or {}).values():
            if (d or {}).get(c):
                sortie.add(X.normaliser(d[c]))
    sortie.discard("")
    return sortie


def _uuid(texte):
    import uuid

    try:
        return uuid.UUID(str(texte))
    except (ValueError, TypeError, AttributeError):
        return None


def _differences_textes(obj, champ, textes, libelle, ref, fourni=False):
    """[(libellé, avant, après)] des textes non vides du paquet qui diffèrent de ceux de l'objet. ``fourni`` : un modèle de la
    bibliothèque qui apporte une traduction que l'objet n'a pas encore (langues de ``bibliotheque.traductions``) n'a pas de
    différence à signaler : c'est un ajout, pas un désaccord (un KPI repris d'un autre modèle ne devient pas un conflit)."""
    from referentiel.bibliotheque.traductions import LANGUES

    sortie = []
    for lg, t in (textes or {}).items():
        if fourni and lg in LANGUES and lg != ref and not ((getattr(obj, "traductions", None) or {}).get(lg) or {}).get(champ):
            continue
        if fourni and lg == ref and _porte_autre_langue(obj, champ, textes, ref):
            continue  # le champ n'a pas de texte propre dans la langue de référence : le texte du modèle est un ajout
        if t and t != L.texte(obj, champ, lg, ref):
            sortie.append((f"{libelle} {L.suffixe(lg)}", X.court(L.texte(obj, champ, lg, ref), 70), X.court(t, 70)))
    return sortie


def _porte_autre_langue(obj, champ, textes, ref):
    """Le champ de l'objet (langue de référence ``ref`` de l'installation) porte le texte d'une autre langue du modèle :
    objet installé par un modèle qui n'avait pas de texte dans cette langue (le champ a reçu le texte de la langue du
    paquet). Un texte saisi ou modifié dans l'installation n'est jamais pris pour le texte d'une autre langue."""
    actuel = getattr(obj, champ, "") or ""
    return any(t and t == actuel for lg, t in (textes or {}).items() if lg != ref) and actuel != ((textes or {}).get(ref) or actuel)


def textes_ajoutes(obj, champ, textes, ref):
    """{langue de référence: texte} qu'un modèle de la bibliothèque ajoute à un objet déjà installé dont le champ porte le
    texte d'une autre langue (``_porte_autre_langue``) : le cas que ``_differences_textes(…, fourni=True)`` laisse passer
    dans la langue de référence. Une autre langue que l'objet n'a pas encore n'est ni un conflit ni écrite : l'objet repris
    reste tel quel."""
    t = (textes or {}).get(ref)
    return {ref: t} if t and _porte_autre_langue(obj, champ, textes, ref) else {}


def poser_ajouts(obj, champ, ajouts, textes, ref):
    """Écrit sur ``obj`` (en mémoire) les ``ajouts`` de ``textes_ajoutes`` : le texte que le champ portait reste dans les
    traductions de sa langue, puis le champ prend celui de la langue de référence."""
    if not ajouts.get(ref):
        return
    actuel = getattr(obj, champ, "") or ""
    for autre, texte in (textes or {}).items():
        if autre != ref and texte == actuel and not L.texte(obj, champ, autre, ref):
            L.definir(obj, champ, autre, actuel)
    setattr(obj, champ, ajouts[ref])


def ajouts_type_reponse(local, t, ref_paquet):
    """Textes qu'un modèle de la bibliothèque ajoute à un type de réponse repris sous le même code (installé par un autre
    modèle), dans la langue de référence de l'installation seulement, quand il n'y en a pas : son nom (``textes_ajoutes``),
    les valeurs de sa liste, les libellés des colonnes de son tableau. Rien de ce qu'il a n'est remplacé."""
    ref = L.reference()
    ajouts = {}
    libelle = textes_ajoutes(local, "libelle", t.get("libelle"), ref)
    if libelle:
        ajouts["libelle"] = libelle
    nb = len(L.cles_valeurs(local) or [])
    liste = (t.get("valeurs") or {}).get(ref)
    if ref != ref_paquet and nb and len(liste or []) == nb and not ((local.traductions or {}).get(ref) or {}).get("valeurs"):
        ajouts["valeurs"] = {ref: liste}
    du_paquet = {str(c.get("code")): c.get("libelle") for c in (t.get("colonnes") or []) if isinstance(c, dict)}
    colonnes, change = [dict(c) if isinstance(c, dict) else c for c in (local.colonnes or [])], False
    for c in colonnes:
        lib, autre = (c.get("libelle"), du_paquet.get(str(c.get("code")))) if isinstance(c, dict) else (None, None)
        if isinstance(lib, dict) and isinstance(autre, dict) and autre.get(ref) and not lib.get(ref):
            c["libelle"], change = {**lib, ref: autre[ref]}, True
    if change:
        ajouts["colonnes"] = colonnes
    return ajouts


def poser_ajouts_type_reponse(local, ajouts, t):
    """Écrit les ``ajouts`` de ``ajouts_type_reponse`` sur le type de réponse (en mémoire)."""
    if ajouts.get("libelle"):
        poser_ajouts(local, "libelle", ajouts["libelle"], t.get("libelle"), L.reference())
    nb = len(L.cles_valeurs(local) or [])
    for lg, liste in (ajouts.get("valeurs") or {}).items():
        L.definir_valeurs(local, lg, liste, nb)
    if ajouts.get("colonnes"):
        local.colonnes = ajouts["colonnes"]


def _etiq(cle):
    """Libellé affiché d'un champ de l'onglet Référentiel (aperçu d'un import) ; les libellés du fichier restent en français."""
    return _t(f"referentiels.paquets.champ.{cle}")


def _affiche(r, cle, genre):
    """Valeur d'un champ du référentiel pour l'aperçu : fréquence et comparaison dans la langue de l'interface."""
    if cle in ("frequence", "comparaison") and r.get(cle) not in (None, ""):
        return LB.choix_valeur(Referentiel, cle, r[cle])
    return _cellule(r, cle, None, genre)


def _differences_referentiel(a, ref):
    r, lg_ref = a.paquet.referentiel, L.reference()
    # nouvelle version d'un modèle de la bibliothèque : le nom choisi dans l'outil reste 
    sortie = ([] if a.fourni else _differences_textes(ref, "nom", r.get("nom"), _etiq("nom"), lg_ref)) + _differences_textes(
        ref, "description", r.get("description"), _etiq("description"), lg_ref)
    for cle, _libelle, genre in CHAMPS_REFERENTIEL:
        libelle = _etiq(cle)
        if cle in ("code", "identifiant", "nom", "description", "origine"):
            continue
        v = r.get(cle)
        if v in (None, "") or str(v).upper() == str(getattr(ref, cle)).upper():
            continue
        if cle in ("frequence", "mois_debut") and ref.campagnes.exists():
            a.avertissements.append(_t("referentiels.paquets.campagnes_gardee", champ=libelle, valeur=_affiche(r, cle, genre), referentiel=str(ref)))
            continue
        sortie.append((libelle, _affiche({cle: getattr(ref, cle)}, cle, genre), _affiche(r, cle, genre)))
    return sortie


def _niveau(a, code):
    """Niveau de l'installation relié au niveau ``code`` du paquet ; AUTO s'il est rattaché automatiquement."""
    for n, local, _, _ in a.niveaux:
        if n["code"] == code:
            return local or AUTO
    return None


def _code_libre(modele, code, longueur):
    """Le code du paquet s'il est libre dans l'installation, sinon « code~2 », « code~3 »…"""
    base = (code or "X")[:longueur - 3]
    pris = {c.lower() for c in modele.objects.values_list("code", flat=True)}
    c, i = code[:longueur] if code else base, 2
    while c.lower() in pris:
        c, i = f"{base}~{i}", i + 1
    return c


def unite_du_paquet(u, lg, ordre):
    """Unité à créer (non enregistrée) pour l'unité ``u`` d'un paquet (langue de référence ``lg``), avec ses traductions :
    installation d'un modèle, import d'un fichier référentiel, réparation des unités mal rapprochées."""
    from .modele import texte_dans_langue

    obj = Unite(code=_code_libre(Unite, u["code"], 60), symbole=texte_dans_langue(u.get("symbole"), lg, lg) or u["code"],
                libelle=texte_dans_langue(u.get("libelle"), lg, lg), entier=bool(u.get("entier")),
                decimales=int(u.get("decimales") or 0), famille=X.texte(u.get("famille")), ordre=ordre)
    _poser_textes(obj, "symbole", u.get("symbole"), lg)
    _poser_textes(obj, "libelle", u.get("libelle"), lg)
    return obj


def _poser_textes(obj, champ, textes, ref_paquet):
    """Textes du paquet sur un objet : la langue de référence de l'installation dans le champ (sinon celle du paquet),
    les autres dans les traductions. Un texte vide ne retire rien."""
    ref = L.reference()
    textes = {lg: t for lg, t in (textes or {}).items() if t}
    if not textes:
        return
    base = textes.get(ref) or textes.get(ref_paquet) or next(iter(textes.values()))
    if base and base != getattr(obj, champ, ""):
        setattr(obj, champ, base)
    for lg, t in textes.items():
        if lg != ref:
            L.definir(obj, champ, lg, t)


def _poser_valeurs(obj, valeurs, ref_paquet):
    """Traductions par position des valeurs d'une liste (les clés sont les valeurs de la langue de référence du paquet)."""
    nb = len(L.cles_valeurs(obj) or obj.valeurs or [])
    for lg, liste in (valeurs or {}).items():
        if lg != ref_paquet and liste and nb:
            L.definir_valeurs(obj, lg, liste, nb)


def _reglage(a, genre, valeur):
    """Code dans l'installation d'une unité, d'un type… cité par un KPI (code ou libellé du paquet, ou réglage de
    l'installation) ; None si inconnu."""
    v = X.texte(valeur)
    if not v:
        return None
    for r in a.reglages:
        if r.genre == genre and r.code == v:
            return r.code_local
    if genre == "unite":
        return _reglage_unite(a, v)
    n = X.normaliser(v)
    for r in a.reglages:
        if r.genre == genre and n in (X.normaliser(r.libelle), X.normaliser(r.code)):
            return r.code_local
    modele = {"unite": Unite, "type_saisie": TypeSaisie, "type_reponse": TypeReponse}[genre]
    for o in modele.objects.all():
        if o.code == v or n in _libelles_obj(o, "symbole", "libelle", "abrege") or n == X.normaliser(o.code):
            return o.code
    return None


def _avertir(a, texte):
    if texte not in a.avertissements:
        a.avertissements.append(texte)


def _reglage_unite(a, v):
    """Code dans l'installation d'une unité citée par un KPI : unité du paquet (symbole exact, code ou traduction), sinon
    unité de l'installation ou déjà prévue (même règle, écart de casse sans risque rapproché avec un avertissement),
    sinon créée (règle unique ``rapprochement_unites``)."""
    du_paquet = RU.rapprocher_unite([v], a.paquet.unites, casse=False).unite
    if du_paquet:
        for r in a.reglages:
            if r.genre == "unite" and r.code == du_paquet["code"]:
                return r.code_local
    prevues = [r.objet for r in a.reglages if r.genre == "unite" and r.objet is not None]
    r = RU.rapprocher_unite([v], [*prevues, *Unite.objects.all()])
    if r.unite:
        if r.casse:
            _avertir(a, _t("referentiels.paquets.unite_casse_reprise", texte=r.texte, symbole=r.casse))
        return r.unite.code
    if r.ecartee:
        _avertir(a, _t("referentiels.paquets.unite_casse_creee", texte=r.texte, symbole=r.ecartee))
    from parametres import referentiel as PR  # unité citée seulement dans l'onglet KPI : créée

    obj = PR.nouvelle_unite(v, _code_libre(Unite, v, 60), Unite.objects.count() + len(a.reglages_crees) + 1)
    a.reglages.append(Reglage("unite", v, v, "cree", obj.code, obj.symbole, objet=obj, motif=_t("referentiels.paquets.citee_onglet_kpi")))
    return obj.code


def _objet_reglage(a, genre, code_local):
    """Objet (existant ou à créer) d'un réglage."""
    for r in a.reglages:
        if r.genre == genre and r.code_local == code_local and r.objet is not None:
            return r.objet
    modele = {"unite": Unite, "type_saisie": TypeSaisie, "type_reponse": TypeReponse}[genre]
    return modele.objects.filter(code=code_local).first()
