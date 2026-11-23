"""Affichage des valeurs : pourcentages stockés en fraction, arrondi d'affichage du KPI, format français,
réponses oui / non et liste en texte, étiquettes des niveaux et des types de saisie."""
import json
import re
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from django import template
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from parametres.libelles import libelle as _lib

from ..nombres import arrondi, chiffres, sans_milliers  # noqa: F401  règle unique d'arrondi (pages, Visualisation, fichiers)

register = template.Library()


@register.simple_tag
def jeton_csp():
    """Jeton (nonce) de la politique de sécurité des contenus pour ``<script nonce="…">`` et ``<style nonce="…">``
    (collecte/politique_contenus.py) : un script ou un style intégré sans ce jeton ne s'exécute pas."""
    from ..politique_contenus import jeton_courant

    return jeton_courant()


def nombre(v, decimales=2, langue=None, milliers=True):
    """Nombre arrondi écrit avec les séparateurs de la langue ; ``milliers=False`` : sans séparateur de milliers (année,
    ``nombres.sans_milliers``)."""
    texte = chiffres(v, decimales, milliers)
    milliers, decimale = separateurs(langue)
    return texte.replace(",", "\x00").replace(".", decimale).replace("\x00", milliers)


# Séparateurs des nombres affichés, selon la langue de l'interface : (milliers, décimale).
# Réglés par la langue elle-même, dans ses fichiers (clés « format.milliers » et « format.decimal » de la zone
# Visualisation) : français 1 234,5 (espace fine insécable) ; anglais 1,234.5 ; espagnol et allemand 1.234,5. Ajouter une
# langue ne demande aucun code. Langue sans ces clés : l'anglais.
def reglage_format(cle, langue=None):
    from parametres import langues as L
    from parametres import libelles as LB

    code = (langue or L.interface() or "fr").split("-")[0]
    for l in (code, LB.REPLI):
        t = LB.table(l).get(cle)
        if t is not None:
            return t
    return ""


def separateurs(langue=None):
    return reglage_format("format.milliers", langue), reglage_format("format.decimal", langue)


def code_langue(langue=None):
    from parametres import langues as L

    return (langue or L.interface() or "fr").split("-")[0]


# Signe « % » selon la langue (format par langue), modèle « format.pourcent » de la langue :
# collé en anglais (« 12.5% »), précédé d'une espace fine insécable en français et en espagnol (« 12,5 % ») : jamais de
# retour à la ligne avant « % ».
def avec_pourcent(texte, langue=None):
    return reglage_format("format.pourcent", langue).replace("{valeur}", str(texte))


@register.filter
def pct(v):
    """Nombre déjà sur 100 (taux du tableau de bord…) écrit avec les séparateurs et le signe % de la langue."""
    if v is None or v == "":
        return ""
    return avec_pourcent(nombre(v, 0 if isinstance(v, int) else 1))


EXEMPLE_UNITE = 1234.5678  # valeur d'exemple de l'aperçu des unités (Paramètres › Référentiel)


@register.filter
def exemple_unite(u):
    """Aperçu d'une réponse avec cette unité : « 1 234,6 kWh » (entier : « 1 235 salariés »)."""
    return f"{nombre(EXEMPLE_UNITE, 0 if u.entier else u.decimales)} {u.tr('symbole')}".strip()


@register.simple_tag
def valeur(reponse, kpi, avec_unite=True):
    """Valeur d'une réponse (avec son unité par défaut) ; « N/A » ; « – » si vide."""
    if reponse is None:
        return "–"
    if reponse.non_applicable:
        return "N/A"
    if kpi.est_tableau:  # tableau : son nombre de lignes (le tableau entier se lit dans le panneau)
        from collecte.tableaux import resume

        n = resume(reponse.texte)
        return _lib("saisie.tableau.lignes", n=n) if n else "–"
    if kpi.est_texte:  # texte rédigé : son début, en texte brut (le texte entier se lit dans le panneau)
        from collecte.markdown import extrait

        return extrait(reponse.texte) or "–"
    if not kpi.est_numerique:  # oui / non, liste ; sur un agrégat : le décompte des réponses (dans la langue courante)
        return kpi.reponse_affichee(reponse.texte) or "–"
    if reponse.valeur is None:
        return "–"
    if kpi.est_pourcentage:
        texte = nombre(reponse.valeur * 100, kpi.decimales)
        return avec_pourcent(texte) if avec_unite else texte
    texte = nombre(reponse.valeur, kpi.decimales, milliers=not sans_milliers(kpi))
    return f"{texte} {kpi.symbole}".strip() if avec_unite else texte


@register.filter
def markdown(texte, niveau_titre=4):
    """HTML sûr d'une réponse rédigée (collecte.markdown : tout HTML écrit est échappé, liens http(s) et mailto seulement)."""
    from collecte.markdown import rendu

    return rendu(texte, int(niveau_titre))


def formater(v, kpi, avec_unite=True):
    """Valeur brute (Decimal, NA ou None) au format du KPI : décimales, pourcentage, unité."""
    from referentiel.formule import NA

    if v is None:
        return _lib("saisie.format.manquant")
    if v is NA:
        return "N/A"
    if kpi.est_tableau and isinstance(v, str):  # tableau : son nombre de lignes
        from collecte.tableaux import resume

        return _lib("saisie.tableau.lignes", n=resume(v))
    if kpi.est_texte and isinstance(v, str):  # texte rédigé : son début, en texte brut
        from collecte.markdown import extrait

        return extrait(v)
    if not isinstance(v, Decimal):  # réponse oui / non ou liste, ou décompte
        return kpi.reponse_affichee(v.texte(kpi.choix) if hasattr(v, "texte") else str(v))
    if kpi.est_pourcentage:
        return avec_pourcent(nombre(v * 100, kpi.decimales))
    return f"{nombre(v, kpi.decimales, milliers=not sans_milliers(kpi))} {kpi.symbole if avec_unite else ''}".strip()


def _bulles():
    """Couleurs des bulles, assombries juste assez pour des initiales blanches lisibles (WCAG AA). Teintes neutres,
    propres à aucune marque (l'outil se pose dans n'importe quelle charte)."""
    from parametres.couleurs import BLANC, lisible

    return [lisible(c, [BLANC]) for c in ("#3E6A9E", "#2F7F72", "#7A5A9E", "#A8573C", "#4D7A3A", "#5A6B85", "#9C5476", "#8A6A2E")]


PALETTE = _bulles()


def avatar_infos(u):
    """Initiales et couleur (fixe pour une personne) de la bulle d'un compte."""
    if u.first_name or u.last_name:
        initiales = (u.first_name[:1] + u.last_name[:1]).upper()
    else:
        initiales = (u.email or u.username)[:2].upper()
    return {"initiales": initiales or "?", "couleur": PALETTE[u.pk % len(PALETTE)]}


@register.simple_tag
def avatar(u, cache=False):
    """Bulle aux initiales ; cache=True la retire de l'arbre d'accessibilité (bouton qui porte déjà le nom en clair)."""
    i = avatar_infos(u)
    if cache:
        return format_html('<span class="avatar" style="background:{}" title="{} – {}" aria-hidden="true">{}</span>', i["couleur"], u,
                           u.email, i["initiales"])
    return format_html('<span class="avatar" style="background:{}" title="{} – {}">{}</span>', i["couleur"], u, u.email, i["initiales"])


@register.filter
def cause_echec(erreur):
    """Cause d'un échec d'envoi de relance, en clair (infobulle de l'historique)."""
    from collecte.relances import cause_echec as cause

    return cause(erreur)


@register.filter
def prenom_initiale(u):
    """« Camille C. » : nom court pour les étiquettes de la grille des attributions."""
    if u.first_name:
        return f"{u.first_name} {u.last_name[:1]}.".strip(" .") + ("." if u.last_name else "")
    return u.email.split("@")[0]


@register.filter
def statut_libelle(statut):
    from collecte.models import Reponse
    from parametres.libelles import choix_valeur

    return choix_valeur(Reponse, "statut", statut)


@register.filter
def choix(objet, champ):
    """Valeur d'un champ à choix dans la langue de l'interface : {{ user|choix:"role" }}, {{ campagne|choix:"statut" }}
    (à la place de get_role_display ; clés « choix.<modèle>.<champ>.<valeur> » de libelles/cadre.*.json)."""
    from parametres.libelles import choix as _choix

    return _choix(objet, champ) if objet is not None else ""


@register.filter
def choix_phrase(objet, champ):
    """Comme ``choix``, au milieu d'une phrase ou entre parenthèses : {{ campagne|choix_phrase:"statut" }} (la casse vient du
    libellé de chaque langue, clés « choix.phrase.* » de libelles/cadre.*.json ; jamais ``|lower``)."""
    from parametres.libelles import choix_phrase as _choix

    return _choix(objet, champ) if objet is not None else ""


@register.filter
def largeur(compteur, attribut):
    """Pourcentage d'un compteur pour une barre empilée."""
    return compteur.pct(getattr(compteur, attribut))


@register.filter
def pluriel(n, suffixe="s"):
    """Pluriel à la française : 0 et 1 au singulier (« 0 valeur validée », « 2 valeurs validées »)."""
    try:
        return suffixe if abs(int(n)) >= 2 else ""
    except (TypeError, ValueError):
        return suffixe if hasattr(n, "__len__") and len(n) >= 2 else ""


@register.filter
def ecart(e):
    """Écart relatif (fraction) en pourcentage signé."""
    if e is None:
        return "–"
    signe = "+" if e > 0 else ""
    return avec_pourcent(f"{signe}{nombre(Decimal(e) * 100, 1)}")


@register.filter
def constat(alerte):
    """Constat d'une alerte de cohérence en clair (coherence.constat_lisible : réécrit aussi les anciens messages)."""
    from ..coherence import constat_lisible

    return constat_lisible(alerte)


@register.filter
def texte_alerte(alerte, champ):
    """« valeur » ou « reference » d'une alerte de cohérence dans la langue de la personne qui lit (coherence.texte_alerte)."""
    from ..coherence import texte_alerte as texte

    return texte(alerte, champ)


@register.filter
def constats_joints(alertes):
    """Constats de plusieurs alertes, sans leur point final, séparés comme dans la langue (étiquette d'une ligne de la grille)."""
    return _lib("saisie.ligne.separateur_constats").join(sans_point_final(constat(a)) for a in alertes)


@register.filter
def guillemets_liste(elements):
    """« A », « B » : noms entre guillemets (ceux de la langue), séparés par une virgule."""
    return ", ".join(_lib("saisie.guillemets", texte=e) for e in elements)


@register.filter
def sans_point_final(texte):
    """Texte sans son point final, pour le suivre d'une autre ponctuation (« … précédents) : ouvrir (Entrée) »)."""
    return str(texte).rstrip().removesuffix(".")


@register.simple_tag
def unite(kpi):
    return kpi.symbole


@register.filter
def pourcent(f):
    """Fraction en pourcentage, sans signe."""
    return "" if f is None else avec_pourcent(nombre(Decimal(f) * 100, 0))


@register.simple_tag
def ecart_fleche(e, seuil=None):
    """Écart avec N-1 : flèche ▲/▼, en rose au-delà du seuil de la campagne."""
    if e is None:
        return "–"
    from ..saisie import depasse_seuil  # (saisie importe ce module : pas en tête)

    fort = depasse_seuil(e, seuil)
    fleche = "▲" if e > 0 else "▼" if e < 0 else "="
    return format_html('<span class="{}" title="{}"><span class="ecart-fleche">{}</span>{}</span>',
                       "ecart-fort" if fort else "", _lib("saisie.ecart.seuil" if fort else "saisie.ecart.avec_n1"),
                       fleche, ecart(e))


@register.simple_tag
def ecart_sous(e, seuil=None, comparaison="N-1"):
    """Écart au-delà du seuil, répété sous la valeur pour les écrans où sa colonne est masquée (E13 : tablette et
    téléphone, outil.css .ecart-sous) ; rien en deçà du seuil ni sans seuil. Le texte lu ne dit pas « commentaire
    obligatoire » : la valeur peut être déjà expliquée, calculée ou validée (la règle reste celle de saisie.py)."""
    from ..saisie import depasse_seuil  # (saisie importe ce module : pas en tête)

    if not depasse_seuil(e, seuil):
        return ""
    fleche = "▲" if e > 0 else "▼" if e < 0 else "="
    comparaison = comparaison or "N-1"
    return format_html('<div class="ecart-sous"><span class="visuellement-cache">{} </span><span class="ecart-fort">'
                       '<span class="ecart-fleche" aria-hidden="true">{}</span>{}</span> <span class="discret" aria-hidden="true">{}</span></div>',
                       _lib("saisie.ecart.sous_lecteur", comparaison=comparaison), fleche, ecart(e),
                       _lib("saisie.ecart.sous_vs", comparaison=comparaison))


@register.filter
def chemin(org):
    """Organisations parentes : « Exemplia Groupe › France »."""
    return " › ".join(reversed([a.nom for a in org.ancetres()]))


# ---------------------------------------------------------------- niveaux de l'arbre (Paramètres › Niveaux)
def _niveaux(context):
    """{code: niveau} : fourni par le processeur de contexte, sinon lu une fois par rendu."""
    d = context.get("niveaux_par_code")
    if d is None:
        d = context.render_context.get("niveaux_par_code")
        if d is None:
            from parametres import niveaux as N

            d = context.render_context["niveaux_par_code"] = N.par_code()
    return d


def _code(objet):
    """Code du niveau d'une organisation, d'un KPI (granularité), d'une règle, ou code donné tel quel."""
    for attribut in ("niveau_id", "granularite_id", "code"):
        if hasattr(objet, attribut):
            return getattr(objet, attribut)
    return objet


@register.simple_tag(takes_context=True)
def nom_niveau(context, objet, pluriel=False):
    n = _niveaux(context).get(_code(objet))
    if n is None:
        return _code(objet) or ""
    return n.tr("nom_pluriel") if pluriel else n.tr("nom")


@register.simple_tag(takes_context=True)
def etiquette_niveau(context, objet, texte=None):
    """Pastille colorée du niveau ; ``texte`` remplace le nom du niveau (ex. le nom de l'organisation)."""
    code = _code(objet)
    return format_html('<span class="niveau niveau-{}">{}</span>', code, texte if texte is not None else nom_niveau(context, code))


@register.simple_tag
def etiquette_type(objet):
    """Pastille du type de saisie d'un KPI (ou d'un type) : « Saisie », « Calcul », « FE »… couleur réglée dans
    Référentiels › Unités et formats."""
    from parametres.referentiel import classe_type

    t = getattr(objet, "type_saisie", objet)
    return format_html('<span class="type {}" title="{}">{}</span>', classe_type(t.code), t.tr("libelle"), t.tr("abrege"))


@register.filter
def classe_referentiel(code):
    from referentiel.plans import classe_referentiel as classe

    return classe(code)


@register.simple_tag
def etiquette_referentiel(r):
    """Pastille d'un référentiel, à sa couleur (Référentiels › Gérer les référentiels)."""
    from referentiel.plans import classe_referentiel

    return format_html('<span class="ref-chip {}" title="{}">{}</span>', classe_referentiel(r.code), r.tr("description") or r, r)


@register.simple_tag
def choix_periodes(groupes, campagne):
    """Sélecteurs « Référentiel » et « Période » : {refs, periodes} ; la campagne affichée y figure toujours."""
    refs = [r for r, _ in groupes]
    periodes = next((cs for r, cs in groupes if campagne is not None and r.pk == campagne.referentiel_id), None)
    if campagne is not None and periodes is None:
        refs.append(campagne.referentiel)
        periodes = [campagne]
    return {"refs": refs, "periodes": periodes or []}


@register.simple_tag
def classe_ref(r):
    """Classe CSS d'un référentiel (sa couleur dans --c-ref)."""
    from referentiel.plans import classe_referentiel

    return classe_referentiel(r.code) if getattr(r, "code", None) else ""  # campagne absente : r vaut ""


# ---------------------------------------------------------------- langues des contenus (Paramètres › Langues)
@register.filter
def tr(objet, champ):
    """Texte traduisible d'un élément dans la langue courante : {{ unite|tr:"libelle" }}."""
    return objet.tr(champ) if objet is not None and hasattr(objet, "tr") else ""



@register.simple_tag
def ligne_traduction(objet, *champs):
    """Traduction d'un élément dans la langue de l'écran, sur une ligne : {% ligne_traduction niveau "nom" "nom_pluriel" %}."""
    from parametres.langues import ligne_traduction as _ligne

    return _ligne(objet, *champs)


@register.simple_tag
def etiquette_reference(texte, langues):
    """Libellé d'un champ saisi dans la langue de référence : « Nom (langue de référence : français) » quand l'écran est dans
    une autre langue (``langues`` : ``parametres.langues.champs_reference()``), le libellé seul sinon."""
    from parametres.libelles import libelle

    return libelle("admin.reference.etiquette", champ=texte, nom_langue=langues["reference"]) if langues["different"] else texte


@register.filter
def attribut(objet, nom):
    """Valeur d'un attribut nommé (gabarits génériques : Référentiels › Unités et formats)."""
    v = getattr(objet, nom, "")
    return "\n".join(v) if isinstance(v, list) else v


@register.filter
def champ_kpi(kpi, code):
    """Valeur d'un champ personnalisé d'un KPI."""
    return kpi.champs.get(code, "") if kpi else ""


@register.filter
def description_kpi(kpi, code):
    return kpi.texte_description(code) if kpi else ""


@register.filter
def get_item(d, cle):
    return d.get(cle, "") if hasattr(d, "get") else ""


# Icônes : bibliothèque Lucide (licence ISC, collecte/icones/, voir docs/third_party_libraries.md).
# Noms de l'outil → nom Lucide ; tout autre nom Lucide s'emploie aussi tel quel : {% icone "calendar" %}.
ICONES = {
    "une-organisation": "building-2", "flux": "rows-3",  # vues de la Saisie
    "fermer": "x", "coche": "check", "alerte": "triangle-alert", "trombone": "paperclip", "telecharger": "download",
    "envoyer": "send", "cadenas": "lock", "crayon": "pencil", "chevron-bas": "chevron-down", "chevron-haut": "chevron-up",
    "chevron-gauche": "chevron-left", "chevron-droite": "chevron-right", "poignee": "grip-vertical", "supprimer": "trash-2",
    "externe": "external-link", "rechercher": "search", "importer": "upload",
    # Visualisation : formes des visuels (toujours accompagnées de leur nom) et actions des visuels
    "forme-chiffre": "square-sigma", "forme-barres": "chart-column", "forme-barres_empilees": "chart-column-stacked",
    "forme-courbe": "chart-line", "forme-anneau": "chart-pie", "forme-tableau": "table",
    "forme-organisations": "chart-bar-decreasing", "forme-comparaison_n1": "chart-column-big",
    "forme-remplissage": "circle-gauge", "plus-actions": "ellipsis", "plein-ecran": "maximize", "image": "image",
    "filtre": "funnel", "langue": "globe",
    "liste-puces": "list", "liste-numeros": "list-ordered", "lien": "link",  # barre d'outils d'une réponse rédigée
    # barre du haut
    "menu-saisie": "pencil-line", "menu-tableau-de-bord": "chart-no-axes-column", "menu-visualisation": "chart-spline",
    "menu-coherence": "triangle-alert", "menu-historique": "history", "menu-echanges": "arrow-down-up",
    "menu-parametres": "settings", "deconnexion": "log-out",
}
# trait, couleur et épaisseur viennent de la feuille de style (.icone-svg, barre du haut…) : retirés des tracés
_ATTRIBUTS_TRAIT = re.compile(r' (?:fill="none"|stroke="currentColor"|stroke-linecap="round"|stroke-linejoin="round"|stroke-width="2")')


@lru_cache(maxsize=None)
def _lucide():
    d = json.loads((Path(__file__).resolve().parent.parent / "icones" / "lucide.json").read_text(encoding="utf-8"))
    return d["icons"], d.get("aliases", {})


@lru_cache(maxsize=None)
def trace_icone(nom):
    """Tracé SVG (24 × 24) d'une icône : nom de l'outil (``ICONES``) ou nom Lucide ; KeyError si inconnu."""
    icones, alias = _lucide()
    n = ICONES.get(nom, nom)
    while n not in icones:
        n = alias[n]["parent"]
    return _ATTRIBUTS_TRAIT.sub("", icones[n]["body"])


@register.simple_tag
def icone(nom, classe="icone-svg"):
    """Icône dessinée (SVG), à la couleur du texte ; décorative : le libellé est porté par le texte ou l'aria-label."""
    attr = format_html(' class="{}"', classe) if classe else ""
    return mark_safe(f'<svg{attr} viewBox="0 0 24 24" aria-hidden="true" focusable="false">{trace_icone(nom)}</svg>')


# ---------------------------------------------------------------- encart (message dans la page) : un composant, quatre teintes
TEINTES_ENCART = ("info", "avertissement", "erreur", "succes")
_BLOC_ENCART = re.compile(r"<(p|ol|ul|div|table|form|details|pre|h[1-6])\b", re.I)
_FIN_PHRASE = re.compile(r"[.!?…](?=\s|$)")
_BALISE_OUVRANTE = re.compile(r"<(?!/|br\b|input\b|img\b|hr\b|path\b|circle\b|line\b|rect\b)[a-zA-Z][^>]*(?<!/)>")
_BALISE_FERMANTE = re.compile(r"</[a-zA-Z][^>]*>")


def gras_premiere_phrase(html):
    """Première phrase d'un texte (HTML déjà sûr) en gras : « <strong class="encart-titre">Phrase.</strong> suite ».
    La phrase finit au premier « . », « ! », « ? » ou « … » suivi d'un blanc, hors d'une balise ; un texte d'une seule
    phrase passe en gras en entier. Rien n'est changé si le texte commence déjà par du gras."""
    html = html.strip()
    if not html or "encart-titre" in html or re.match(r"<(strong|b)\b", html):
        return html
    coupe = len(html)
    for m in _FIN_PHRASE.finditer(html):
        debut = html[:m.end()]
        if debut.count("<") != debut.count(">"):  # dans une balise (attribut) : pas une fin de phrase
            continue
        if len(_BALISE_OUVRANTE.findall(debut)) != len(_BALISE_FERMANTE.findall(debut)):  # dans un lien, un <span>…
            continue
        coupe = m.end()
        break
    return f'<strong class="encart-titre">{html[:coupe]}</strong>{html[coupe:]}'


@register.filter(name="premiere_phrase_gras")
def premiere_phrase_gras(texte):
    """Message d'une phrase ou plus (texte simple, échappé ici), sa première phrase en gras : messages du haut de page."""
    from django.utils.html import conditional_escape

    return mark_safe(gras_premiere_phrase(str(conditional_escape(texte))))


class NoeudEncart(template.Node):
    def __init__(self, teinte, attributs, contenu):
        self.teinte, self.attributs, self.contenu = teinte, attributs, contenu

    def render(self, context):
        teinte = self.teinte.resolve(context)
        if teinte not in TEINTES_ENCART:
            raise template.TemplateSyntaxError(f"encart : teinte inconnue « {teinte} » ({', '.join(TEINTES_ENCART)}).")
        html = self.contenu.render(context).strip()
        if not html:
            return ""
        attributs = {nom: valeur.resolve(context) for nom, valeur in self.attributs.items()}
        bloc = bool(_BLOC_ENCART.search(html))
        balise = attributs.pop("balise", None) or ("div" if bloc else "p")
        classes = f"encart encart-{teinte}"
        if attributs.pop("compact", False):
            classes += " compact"
        if attributs.get("classe"):
            classes += f" {attributs['classe']}"
        attributs.pop("classe", None)
        if bloc:  # contenu en paragraphes : la première phrase du premier paragraphe
            m = re.match(r"<p>(.*?)</p>", html, re.S)
            if m and "encart-titre" not in html:
                html = f"<p>{gras_premiere_phrase(m.group(1))}</p>{html[m.end():]}"
        else:
            html = gras_premiere_phrase(html)
        suite = ""
        for nom, valeur in attributs.items():
            if valeur is True:
                suite += f" {nom.replace('_', '-')}"
            elif valeur not in (False, None, ""):
                suite += format_html(' {}="{}"', nom.replace("_", "-"), valeur)
        return f'<{balise} class="{classes}"{suite}>{html}</{balise}>'


@register.tag(name="encart")
def encart(parser, token):
    """Encart dans la page (DESIGN.md, « Callouts ») : {% encart "avertissement" role="status" %}…{% endencart %}.
    Teintes : info (bleu), avertissement (orange), erreur (rouge), succes (vert). L'icône vient de la feuille de style ;
    la première phrase passe en gras. Options : balise="li", classe="mt-0", compact=True, et tout attribut HTML
    (id, role, hidden=condition, data_x=True : les « _ » deviennent des « - »). Un contenu vide n'affiche rien."""
    from django.template.base import token_kwargs

    morceaux = token.split_contents()[1:]
    if not morceaux:
        raise template.TemplateSyntaxError("encart : la teinte manque (info, avertissement, erreur, succes).")
    teinte = parser.compile_filter(morceaux[0])
    reste = morceaux[1:]
    attributs = token_kwargs(reste, parser)
    if reste:
        raise template.TemplateSyntaxError(f"encart : option illisible « {reste[0]} ».")
    contenu = parser.parse(("endencart",))
    parser.delete_first_token()
    return NoeudEncart(teinte, attributs, contenu)


@register.filter
def jours_restants(jour):
    """Nombre de jours d'ici à une date (0 le jour même, négatif si elle est passée), ou None sans date."""
    from django.utils import timezone

    return (jour - timezone.localdate()).days if jour else None


@register.filter
def liste(valeurs, separateur=", "):
    """Éléments joints en texte simple, pour un paramètre de {% libelle %} : celui-ci échappe ses paramètres, alors que
    le filtre join renverrait un texte déjà échappé (une apostrophe s'afficherait « &#x27; »)."""
    return separateur.join(str(v) for v in valeurs or ())


@register.filter
def nom_porte_niveau(org):
    """Vrai si le nom de l'organisation finit déjà par son niveau (« Exemplia (Groupe) ») : ne pas le répéter dans une
    liste (« Exemplia (Groupe) (groupe) »)."""
    return org.nom.lower().endswith(f"({str(org.niveau).lower()})")


@register.filter
def mo(octets):
    """Taille d'un fichier en mégaoctets, au format de la langue : 1572864 → « 1,5 » (FR), « 1.5 » (EN)."""
    from collecte.fichiers import mo as en_mo

    return en_mo(octets or 0)


@register.filter
def ko(octets):
    """Taille d'un fichier de moins de 1 Mo en kilooctets, arrondie au-dessus (17 408 → 17 ; 300 → 1, jamais 0 pour un
    fichier non vide)."""
    return -(-(octets or 0) // 1024)


# Paramètres entiers de {% libelle %} qui ne sont pas des comptes : jamais groupés par milliers (« Exercice 2026 »)
PARAMETRES_SANS_MILLIERS = {"exercice", "annee", "an", "version", "numero", "ligne", "rang", "code", "id", "heure", "mois", "port"}


@register.filter
def entier(v):
    """Nombre entier (un compte) avec le séparateur de milliers de la langue : 1767 → « 1 767 » (FR), « 1,767 » (EN),
    « 1.767 » (ES). Autre chose qu'un entier : rendu tel quel."""
    if v is None or v == "":
        return ""
    if isinstance(v, (int, float, Decimal)) and not isinstance(v, bool):  # pas pour une année : un nombre brut
        return nombre(v, 0)
    return v


@register.filter
def joindre(valeurs, separateur=", "):
    """Liste en texte brut, NON échappé, pour un paramètre de {% libelle %} qui l'échappe une fois (``join`` échappe déjà
    chaque élément : « &lt; » devenait « &amp;lt; ») ; affiché seul, le texte est échappé comme toute variable."""
    return str(separateur).join(str(v) for v in valeurs or [])


@register.simple_tag
def libelle(cle, n=None, **valeurs):
    """Libellé de l'interface dans la langue de la personne (``parametres.libelles``) : {% libelle "visu.vue.renommer" %},
    {% libelle "visu.deplace" titre=t position=2 total=6 %}, {% libelle "visu.kpi.nb" n=3 %},
    {% libelle "cadre.deconnexion" as texte %} (pour un attribut, ou pour le réutiliser). Échappé à l'affichage, paramètres compris."""
    return libelle_echappe(cle, n, valeurs, html=False)


def libelle_echappe(cle, n, valeurs, html):
    """Texte du fichier échappé (sauf l'apostrophe, et sauf les balises permises pour ``libelle_html``) et paramètres
    échappés : sûr dans le texte comme dans un attribut entre guillemets doubles (règle des gabarits de l'outil)."""
    from django.utils.html import escape

    from parametres.libelles import gabarit, remplacer

    texte = gabarit(cle, n=n)
    if not html:
        texte = texte.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    def lisible(v, nom=""):  # un nombre s'écrit avec la décimale de la langue (« 40,9 », « 40.9 »), pas comme en Python
        if isinstance(v, (float, Decimal)) and not isinstance(v, bool):
            return str(v).replace(".", separateurs()[1])
        if isinstance(v, int) and not isinstance(v, bool) and nom not in PARAMETRES_SANS_MILLIERS:
            return entier(v)  # un compte groupé par milliers (« 1 767 », « 1,767 ») ; une année reste « 2026 »
        return v

    valeurs = {k: escape(lisible(v, k)) for k, v in valeurs.items()}  # toujours échappés, même un texte « sûr » du gabarit
    if n is not None:
        valeurs.setdefault("n", escape(lisible(n)))
    return mark_safe(remplacer(texte, valeurs))


@register.simple_tag
def langue_page():
    """Code de la langue de l'interface (attribut lang) : aussi sans contexte, sur les pages d'erreur."""
    from parametres import langues as L

    return L.interface()


@register.simple_tag
def libelle_html(cle, n=None, **valeurs):
    """Libellé qui contient une mise en forme simple écrite dans le fichier de langue (<strong>, <b>, <em>, <code>,
    <br>) : {% libelle_html "cadre.connexion.aide" contact=instance.contact %}. Les paramètres sont échappés ; le texte
    du fichier est sûr (écrit par nous, balises vérifiées par parametres/test_traduction.py)."""
    return libelle_echappe(cle, n, valeurs, html=True)


@register.simple_tag
def libelles_js():
    """Libellés des scripts des pages (clés « commun.* » et « <zone>.js.* » de toutes les zones), dans la langue de
    l'interface : <script type="application/json" id="libelles-js">, lus par la fonction ``lib()`` de _app/01_socle.js."""
    from django.utils.html import json_script

    from parametres.libelles import libelles as _libelles
    from parametres.zones_langue import ZONES

    d = _libelles("commun.")
    d.update(_libelles("format."))  # séparateurs, signe %, pluriel de la langue
    for _, prefixes, _ in ZONES.values():
        for p in prefixes:
            d.update(_libelles(p + "js."))
    return json_script(d, "libelles-js")


@register.simple_tag(takes_context=True)
def annulation_proposee(context):
    """Offre « Supprimé : X. Annuler » gardée pour cette page après une suppression (collecte.corbeille), une seule fois."""
    from collecte.corbeille import offre_en_attente

    request = context.get("request")
    return offre_en_attente(request) if request is not None else None


@register.filter
def retrait(n):
    """Retrait d'une organisation dans une liste déroulante (espaces insécables, selon sa profondeur)."""
    try:
        return "   " * max(int(n), 0)
    except (TypeError, ValueError):
        return ""


@register.filter
def date_longue(d):
    """Date en toutes lettres dans la langue de l'interface (« 29 octobre 2026 », « 29 October 2026 », « 29 de octubre
    de 2026 ») : le filtre ``date:"j F Y"`` de Django écrirait le mois en français dans toutes les langues."""
    from collecte.periodes import MOIS
    from parametres import langues as L

    if not d:
        return ""
    mois = MOIS.get(L.interface(), MOIS["fr"])[d.month - 1]
    return _lib("saisie.date_longue", jour=d.day, mois=mois, annee=d.year)


@register.filter
def date_courte(d):
    """Date courte dans la langue de l'interface (01/03/2026, 01.03.2026…) : ``collecte/dates_courtes.py``."""
    from collecte import dates_courtes

    return dates_courtes.date_courte(d)


@register.filter
def date_heure_courte(d):
    """Date courte et heure (24 h) dans la langue de l'interface."""
    from collecte import dates_courtes

    return dates_courtes.date_heure_courte(d)


@register.filter
def depuis(d):
    """Durée écoulée (« 3 heures ») dans la langue de l'interface (``timesince`` de Django, traduit par Django)."""
    from django.utils import translation
    from django.utils.timesince import timesince

    from parametres import langues as L

    if not d:
        return ""
    with translation.override(L.interface()):
        return timesince(d)


@register.simple_tag
def valeur_point(point, kpi):
    """Valeur d'un point de la Visualisation ou de la Consolidation, au format du KPI, sans l'unité (portée par l'en-tête
    de colonne ; un pourcentage garde son « % »)."""
    return formater(point.valeur, kpi, avec_unite=False)


@register.simple_tag
def valeur_point_brut(valeur, kpi):
    """Nombre au format du KPI, sans l'unité (total partiel de la Consolidation)."""
    return formater(valeur, kpi, avec_unite=False)


ICONES_DONNEES = {"compte": "user-round", "mot_de_passe": "key-round", "valeurs": "pencil", "historique": "history",
                  "preuves": "paperclip", "corbeille": "trash-2", "relances": "mail", "connexion": "shield-alert",
                  "sessions": "cookie", "sauvegardes": "hard-drive-download", "controle": "shield-check"}


@register.simple_tag
def icone_donnee(cle):
    """Icône d'une donnée de la page Données et confidentialité (une icône neutre pour une donnée ajoutée plus tard)."""
    return icone(ICONES_DONNEES.get(cle, "file-text"))


@register.filter
def date_etat(alerte):
    """Date du dernier changement d'état d'une alerte (coherence.date_etat)."""
    from collecte.coherence import date_etat as d

    return d(alerte)


@register.simple_tag(takes_context=True)
def calcul_clair(context, kpi):
    """Calcul d'un KPI écrit pour être lu : « Scope 1 + Scope 2 + Scope 3 », avec les noms des KPI à la
    place des codes. Vide pour un KPI saisi ou une formule illisible. Les noms sont lus une fois par page."""
    formule = getattr(kpi, "formule", "") or ""
    if not formule.strip() or not getattr(kpi, "est_calcule", True):
        return ""
    from referentiel import formule as F
    from referentiel.models import KPI

    porteur = context.get("request") or context.render_context
    noms = getattr(porteur, "_noms_kpi", None)
    if noms is None:
        noms = {k.code: k.nom for k in KPI.objects.all()}
        try:
            porteur._noms_kpi = noms
        except AttributeError:
            pass
    return F.en_clair(formule, noms, libelle("referentiels.calcul.exercice_precedent"), libelle("referentiels.calcul.periode_precedente"))



@register.simple_tag(takes_context=True)
def ligne_grille(context, l):
    """Ligne de la grille de saisie (``collecte/rendu_ligne.py`` : le HTML de l'ancien gabarit ``_ligne.html``)."""
    from ..rendu_ligne import constantes, ligne

    return mark_safe(ligne(l, constantes(context)))
