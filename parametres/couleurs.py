"""Couleurs de l'installation : palettes proposées, gamme dérivée de 4 couleurs de base, contrastes WCAG.

Le CSS n'utilise que des variables (``--principale``, ``--accent-teinte``, ``--bord``…). Elles sont calculées ici à
partir de 4 couleurs choisies par le client : principale, accent, fond, texte. Une palette fournie peut préciser
toute sa gamme. Les palettes fournies sont neutres (aucune marque) ; chaque installation peut enregistrer les siennes
(``PaletteEnregistree``), avec au besoin une gamme fixée à l'identique (ex. la charte d'un client, erreur comprise).
"""
import re

from .libelles import libelle

BLANC, NOIR = "#FFFFFF", "#000000"
HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")

# Variables de marque : celles que le client fait varier (le reste du CSS est fixe)
VARIABLES = [
    "principale-vive", "principale-survol", "principale", "principale-claire", "principale-teinte", "principale-pale",
    "accent", "accent-claire", "accent-teinte", "accent-pale", "accent-texte",
    "texte", "texte-doux", "texte-leger", "fond", "surface", "entete-table", "bord", "bord-doux", "bord-fort", "neutre",
    "erreur", "erreur-texte", "erreur-teinte",
    # calculées pour la lisibilité (jamais réglées à la main) : voir _derivees
    "principale-texte", "principale-bord", "sur-principale", "contour",
    "bandeau", "sur-bandeau", "bandeau-filet", "bandeau-survol", "bandeau-actif", "sur-bandeau-actif",
]
ERREUR = {"erreur": "#D92D20", "erreur-texte": "#9B1C1C", "erreur-teinte": "#FDECEC"}

# Couleurs communes à toutes les installations (états, ombres, voile, cartes blanches, fond du logo) : celles de
# l'apparence claire ; l'apparence sombre les recalcule (``gamme_sombre``). Injectées avec la marque par ``css``.
FIXES = {
    "vert": "#0EC97E", "vert-pale": "#D7F3E6", "vert-texte": "#0B6644", "barre-valide": "#2E9E68",
    "jaune": "#FFEC32", "jaune-pale": "#FFF5C2", "jaune-texte": "#6A5A00", "barre-brouillon": "#E3B530",
    "orange": "#A86F00", "orange-pale": "#FFF1D6", "orange-bord": "#E8C98A", "orange-texte": "#7A4F00",
    "bleu3": "#E2E9FD", "bleu-texte": "#2B4596",
    "surface-vive": BLANC, "fond-logo": BLANC, "sur-erreur": BLANC,
    "ombre-flottante": "0 8px 24px rgba(20, 24, 32, .14)", "ombre-panneau": "-8px 0 24px rgba(0, 0, 0, .12)",
    "ombre-legere": "0 1px 2px rgba(20, 24, 32, .12)", "voile": "rgba(20, 24, 32, .32)",
}

PALETTES = {
    # palettes fournies (gammes Radix Colors et Tailwind, vérifiées avec Realtime Colors et les
    # contrôles de l'outil : tout est lisible en clair et en sombre, sans retouche automatique). Océan, la palette par
    # défaut, ne change pas. Une installation garde ses couleurs enregistrées : rien ne change sans l'admin.
    "ocean": {"nom": "Océan", "principale": "#1F5FAD", "accent": "#0F9D9A", "fond": "#F2F4F7", "texte": "#1E2A38"},
    "indigo": {"nom": "Indigo", "principale": "#3E63DD", "accent": "#0D9488", "fond": "#F7F8FC", "texte": "#1C2024"},
    "foret": {"nom": "Forêt", "principale": "#1D6B4F", "accent": "#D9822B", "fond": "#F5F7F4", "texte": "#1A221E"},
    "ardoise": {"nom": "Ardoise", "principale": "#334155", "accent": "#0284C7", "fond": "#F5F7FA", "texte": "#0F172A"},
    "terracotta": {"nom": "Terracotta", "principale": "#B5452A", "accent": "#2F7A78", "fond": "#FAF6F2", "texte": "#2A211C"},
    "prune": {"nom": "Prune", "principale": "#6E56CF", "accent": "#D6409F", "fond": "#F8F7FC", "texte": "#211F26"},
    "graphite": {"nom": "Graphite", "principale": "#27272A", "accent": "#E5484D", "fond": "#F7F7F8", "texte": "#18181B"},
}
PALETTE_PAR_DEFAUT = "ocean"


# ---------------------------------------------------------------- calculs
def valide(h):
    return bool(h and HEX.match(h))


def rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def hexa(c):
    return "#" + "".join(f"{max(0, min(255, round(v))):02X}" for v in c)


def melange(a, b, part_a):
    """Couleur à ``part_a`` de a et (1 - part_a) de b."""
    ca, cb = rgb(a), rgb(b)
    return hexa(tuple(x * part_a + y * (1 - part_a) for x, y in zip(ca, cb)))


def luminance(h):
    def canal(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (canal(v) for v in rgb(h))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contraste(a, b):
    """Rapport de contraste WCAG entre deux couleurs (1 à 21)."""
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def lisible(couleur, fonds, seuil=4.6):
    """La couleur, rapprochée du noir (ou du blanc sur fond sombre) juste assez pour atteindre ``seuil`` sur chaque fond."""
    extreme = NOIR if luminance(fonds[0]) > 0.4 else BLANC
    c, part = couleur, 0.0
    while min(contraste(c, f) for f in fonds) < seuil and part < 1:
        part = round(part + 0.02, 2)
        c = melange(extreme, couleur, part)
    return c


def _lisibilite(g):
    """Texte secondaire et couleur de survol lisibles (WCAG AA) sur tous les fonds clairs où ils apparaissent."""
    g = dict(g)
    g["texte-doux"] = lisible(g["texte-doux"], [g["fond"], g["surface"], g["neutre"], g["entete-table"]])
    # survol des boutons (texte blanc) et des liens : la couleur vive de la marque, assombrie si besoin
    g["principale-survol"] = lisible(g["principale-vive"], [BLANC, g["surface"]])
    return g


def _derivees(g):
    """Couleurs calculées pour rester lisibles quelle que soit la palette : la couleur principale en texte, le texte posé
    sur elle (boutons), le bord des champs (3:1, WCAG 1.4.11) et le bandeau du haut. Le bandeau prend la couleur
    principale si le texte blanc y est lisible ; sinon il passe en clair (surface, filet de la couleur principale)."""
    g = {k: v for k, v in g.items() if k in VARIABLES}
    p = g["principale"]
    g["principale-texte"] = lisible(p, [g["fond"], g["surface"], BLANC])
    g["sur-principale"] = BLANC if contraste(BLANC, p) >= SEUIL_AA else (g["texte"] if contraste(g["texte"], p) >= SEUIL_AA else NOIR)
    g["contour"] = lisible(melange(g["texte"], g["fond"], .45), [g["fond"], g["surface"], BLANC], seuil=3.1)
    g["principale-bord"] = lisible(p, [g["fond"], g["surface"], BLANC], seuil=3.1)  # contours des éléments actifs
    if contraste(BLANC, p) >= SEUIL_AA:
        g.update({"bandeau": p, "sur-bandeau": BLANC, "bandeau-filet": p, "bandeau-survol": melange(NOIR, p, .18),
                  "bandeau-actif": BLANC, "sur-bandeau-actif": lisible(p, [BLANC])})
    else:
        g.update({"bandeau": g["surface"], "sur-bandeau": g["texte"], "bandeau-filet": p, "bandeau-survol": g["principale-pale"],
                  "bandeau-actif": g["principale-teinte"], "sur-bandeau-actif": lisible(p, [g["principale-teinte"], g["surface"]])})
    return g


def gamme(principale, accent, fond, texte, palette=None, gamme_fixe=None):
    """Toutes les variables de marque. ``gamme_fixe`` : gamme enregistrée d'une palette (reprise telle quelle)."""
    p = PALETTES.get(palette or "")
    if p and "gamme" in p and (principale, accent, fond, texte) == (p["principale"], p["accent"], p["fond"], p["texte"]):
        gamme_fixe = p["gamme"]
    if gamme_fixe:
        return {**_derivees(_lisibilite({**gamme_fixe})), **FIXES}
    return {**_derivees(_lisibilite({
        "principale-vive": melange(principale, BLANC, .82), "principale": principale,
        "principale-claire": melange(principale, BLANC, .42), "principale-teinte": melange(principale, BLANC, .11),
        "principale-pale": melange(principale, BLANC, .05),
        "accent": accent, "accent-claire": melange(accent, BLANC, .45), "accent-teinte": melange(accent, BLANC, .16),
        "accent-pale": melange(accent, BLANC, .07), "accent-texte": melange(accent, NOIR, .62),
        "texte": texte, "texte-doux": melange(texte, fond, .68), "texte-leger": melange(texte, fond, .35),
        "fond": fond, "surface": melange(fond, BLANC, .25), "entete-table": melange(fond, BLANC, .55),
        "bord": melange(texte, fond, .09), "bord-doux": melange(texte, fond, .06), "bord-fort": melange(texte, fond, .15),
        "neutre": melange(texte, fond, .07),
        **ERREUR,
    })), **FIXES}


def css(g):
    """Variables de la gamme ``g`` : la marque, puis les couleurs communes si ``g`` les porte."""
    return "".join(f"--{nom}: {g[nom]}; " for nom in VARIABLES + list(FIXES) if nom in g)


# ---------------------------------------------------------------- apparence sombre
# L'outil suit le réglage du système (prefers-color-scheme: dark) ; chacun peut forcer « Clair » ou « Sombre » dans Mon
# compte (cookie ``apparence`` : un choix de l'appareil, comme sur un téléphone, sans rien écrire dans la base). La gamme
# sombre est tirée de la gamme claire de l'installation (même marque, mêmes contrôles de contraste) : fonds sombres
# teintés du texte et de la couleur principale du client, texte clair, couleur principale éclaircie juste assez pour
# 4,5:1 (texte) et 3:1 (contours, icônes) sur les fonds sombres.
APPARENCES = ("systeme", "clair", "sombre")
COOKIE_APPARENCE = "apparence"
AUTO = ":root:not([data-apparence=clair])"  # système en sombre, sans choix « Clair » (sans guillemets : le gabarit les échapperait)
FORCE = ":root[data-apparence=sombre]"  # choix « Sombre » dans Mon compte


def _assombrir(couleur, cible=0.011):
    """Fond sombre tiré d'une couleur : rapprochée du noir jusqu'à une luminance très basse."""
    c, part = couleur, 0.0
    while luminance(c) > cible and part < 1:
        part = round(part + 0.02, 2)
        c = melange(NOIR, couleur, part)
    return c


ETATS_SOMBRES = {"vert": "#0EC97E", "jaune": "#E3B530", "orange": "#E8A23A", "bleu": "#6F8EF0"}  # teintes des états


def gamme_sombre(g):
    """Gamme de l'apparence sombre, tirée de la gamme claire ``g`` (palette fournie, réglée ou fixée)."""
    p, a = g["principale"], g["accent"]
    fond = melange(_assombrir(melange(g["texte"], p, .9)), "#15171B", .5)  # teinte de la marque, discrète
    surface, entete, neutre = melange(BLANC, fond, .05), melange(BLANC, fond, .09), melange(BLANC, fond, .12)
    vive = melange(BLANC, fond, .08)  # les cartes blanches de l'apparence claire (blocs de saisie, puces)
    texte = lisible(melange(g["fond"], fond, .9), [fond, surface], seuil=11)
    # états : mêmes teintes qu'en clair, fond foncé (des encarts entiers en sont couverts : liens et texte secondaire
    # restent lisibles dessus)
    etats = {nom: melange(base, surface, .18) for nom, base in ETATS_SOMBRES.items()}
    fonds = [fond, surface, entete, neutre, vive]
    s = {"fond": fond, "surface": surface, "entete-table": entete, "neutre": neutre, "texte": texte,
         "texte-leger": melange(texte, fond, .45),
         "bord": melange(BLANC, fond, .14), "bord-doux": melange(BLANC, fond, .1), "bord-fort": melange(BLANC, fond, .24)}
    s["texte-doux"] = lisible(melange(texte, fond, .7), fonds + list(etats.values()))
    # boutons : la couleur du client, éclaircie si elle se confond avec le fond ; texte blanc s'il y est lisible
    bouton = p
    while contraste(bouton, fond) < 2 and luminance(bouton) < .9:
        bouton = melange(BLANC, bouton, .06)
    s["principale"] = bouton
    s["sur-principale"] = BLANC if contraste(BLANC, bouton) >= SEUIL_AA else fond
    s["principale-survol"] = melange(NOIR if s["sur-principale"] == BLANC else BLANC, bouton, .16)
    s["principale-vive"] = lisible(g["principale-vive"], [fond], seuil=3.1)
    s["principale-claire"] = melange(p, fond, .55)
    s["principale-teinte"] = melange(p, fond, .3)
    s["principale-pale"] = melange(p, fond, .16)
    s["principale-texte"] = lisible(p, fonds + list(etats.values()) + [s["principale-teinte"], s["principale-pale"]])
    s["principale-bord"] = lisible(p, fonds, seuil=3.1)
    s["accent"] = lisible(a, [surface], seuil=3.1)
    s["accent-claire"] = melange(a, fond, .55)
    s["accent-teinte"] = melange(a, fond, .3)
    s["accent-pale"] = melange(a, fond, .14)
    s["accent-texte"] = lisible(a, [s["accent-teinte"], surface, fond])
    s["contour"] = lisible(melange(texte, fond, .4), fonds, seuil=3.1)
    s["erreur-teinte"] = melange(g["erreur"], surface, .24)
    s["erreur"] = lisible(g["erreur"], [surface, fond], seuil=3.1)
    s["erreur-texte"] = lisible(g["erreur"], [s["erreur-teinte"], surface, fond, vive])
    s["sur-erreur"] = BLANC if contraste(BLANC, s["erreur"]) >= SEUIL_AA else fond
    # bandeau du haut : sombre (la surface), filet de la couleur principale, onglet actif sur sa teinte
    s.update({"bandeau": surface, "sur-bandeau": texte, "bandeau-filet": s["principale-bord"], "bandeau-survol": s["principale-pale"],
              "bandeau-actif": s["principale-teinte"], "sur-bandeau-actif": lisible(texte, [s["principale-teinte"], surface], seuil=7)})
    for nom, pale in etats.items():
        s[f"{nom}-texte"] = lisible(ETATS_SOMBRES[nom], [pale, surface, fond, vive, entete])
        s["bleu3" if nom == "bleu" else f"{nom}-pale"] = pale
    s.update({"vert": "#0EC97E", "barre-valide": "#2E9E68", "jaune": "#FFEC32", "barre-brouillon": "#E3B530",
              "orange": lisible("#D98E04", [surface, fond], seuil=3.1), "orange-bord": melange("#E8A23A", surface, .5),
              "surface-vive": vive, "fond-logo": melange(BLANC, texte, .5),  # logo : carré clair, adouci
              "ombre-flottante": "0 8px 24px rgba(0, 0, 0, .5)", "ombre-panneau": "-8px 0 24px rgba(0, 0, 0, .45)",
              "ombre-legere": "0 1px 2px rgba(0, 0, 0, .5)", "voile": "rgba(0, 0, 0, .6)"})
    return s


def couleurs_niveau_sombre(couleur, fond):
    """(fond des étiquettes, texte des étiquettes, fond des cartes, trait à 3:1) d'une couleur de niveau, de type de
    saisie ou de référentiel, sur les fonds sombres."""
    if not valide(couleur):  # couleur absente ou abîmée (niveau créé sans couleur) : un gris neutre, jamais d'erreur
        couleur = "#8A8F98"
    etiquette = melange(couleur, fond, .28)
    return etiquette, lisible(couleur, [etiquette, fond]), melange(couleur, fond, .12), lisible(couleur, [fond], seuil=3.1)


def css_etiquettes(objets, regles, clair):
    """CSS des étiquettes colorées (niveaux, types de saisie, référentiels) dans l'apparence claire : ``regles(objet,
    fond, texte, pale, trait)`` donne [(sélecteur, déclarations)] ; ``clair(objet)`` donne ces quatre couleurs."""
    return "".join(f"{s}{{{d}}}" for o in objets for s, d in regles(o, *clair(o)))


def etiquettes_sombres(objets, regles, fond):
    """Mêmes règles que ``css_etiquettes`` pour l'apparence sombre [(sélecteur, déclarations)] : couleurs tirées de la
    couleur de chaque objet sur le fond sombre ``fond`` (``couleurs_niveau_sombre``)."""
    return [r for o in objets for r in regles(o, *couleurs_niveau_sombre(o.couleur, fond))]


def bloc_sombre(variables, regles=()):
    """CSS de l'apparence sombre : ``variables`` (« --x: …; ») sur la racine et ``regles`` [(sélecteur, déclarations)],
    deux fois : système en sombre (sauf choix « Clair ») et choix « Sombre ». Écran seulement : l'impression reste claire.
    Les règles gardent la spécificité des règles claires (:where) : celles des composants plus précises restent devant."""
    def corps(racine):
        return f"{racine}{{color-scheme: dark; {variables}}}" + "".join(f":where({racine}) {sel}{{{decl}}}" for sel, decl in regles)
    return f"@media screen and (prefers-color-scheme: dark){{{corps(AUTO)}}}@media screen{{{corps(FORCE)}}}"


CONTROLES = [  # (clé du libellé, couleur du texte ou du trait, couleur du fond, seuil) : ce que l'outil affiche réellement
    ("admin.identite.controle.boutons", lambda g: g["sur-principale"], lambda g: g["principale"], 4.5),
    ("admin.identite.controle.bandeau", lambda g: g["sur-bandeau"], lambda g: g["bandeau"], 4.5),
    ("admin.identite.controle.liens", lambda g: g["principale-texte"], lambda g: g["fond"], 4.5),
    ("admin.identite.controle.texte", lambda g: g["texte"], lambda g: g["fond"], 4.5),
    ("admin.identite.controle.secondaire", lambda g: g["texte-doux"], lambda g: g["surface"], 4.5),
    ("admin.identite.controle.etiquettes", lambda g: g["accent-texte"], lambda g: g["accent-teinte"], 4.5),
    ("admin.identite.controle.bords", lambda g: g["contour"], lambda g: g["surface"], 3),
]
SEUIL_AA = 4.5


def controles(g):
    """[(libellé, rapport arrondi, conforme, seuil)] pour l'aperçu et la page Identité."""
    sortie = []
    for cle, avant, arriere, seuil in CONTROLES:
        r = contraste(avant(g), arriere(g))
        sortie.append({"libelle": libelle(cle), "rapport": round(r, 1), "ok": r >= seuil, "seuil": seuil})
    return sortie


def adaptations(g):
    """Ce que l'outil ajuste de lui-même pour rester lisible avec ces couleurs (affiché sur la page Identité)."""
    sortie = []
    if g["bandeau"] != g["principale"]:
        sortie.append(libelle("admin.identite.adaptation.bandeau"))
    if g["principale-texte"] != g["principale"]:
        sortie.append(libelle("admin.identite.adaptation.texte"))
    return sortie


# ---------------------------------------------------------------- couleurs des graphiques (Visualisation)
# Palette fournie : celle de static/css/outil.css (--viz-1 à --viz-8, --viz-autres, --viz-pale), vérifiée pour les
# daltonismes, ordre fixe. L'admin peut la remplacer (Paramètres › Identité › « Couleurs des graphiques ») : ses couleurs
# sont alors injectées par ``couleurs_css`` ; sans réglage, rien n'est injecté et rien ne change à l'écran.
VIZ = ["#2A78D6", "#EB6834", "#1BAF7A", "#EDA100", "#E87BA4", "#008300", "#6250D6", "#E34948"]
VIZ_AUTRES = "#9AA0A6"
VIZ_PALE = "#86B6EF"  # valeur provisoire : la série 1, plus pâle
SEUIL_MARQUES = 3  # WCAG 1.4.11 : une barre, un trait ou une part se distingue de la surface à 3:1


def palette_graphiques(reglage):
    """(8 couleurs des séries, couleur « Autres », réglée par l'admin) ; un réglage incomplet ou abîmé compte comme
    aucun réglage (la palette fournie)."""
    r = reglage if isinstance(reglage, dict) else {}
    series, autres = r.get("series"), r.get("autres")
    if isinstance(series, list) and len(series) == len(VIZ) and all(valide(c) for c in series) and valide(autres):
        return [c.upper() for c in series], autres.upper(), True
    return list(VIZ), VIZ_AUTRES, False


def reglage_graphiques(series, autres):
    """Réglage à enregistrer : {} si ce sont les couleurs fournies (l'installation suit alors la palette fournie)."""
    series, autres = [c.upper() for c in series], autres.upper()
    return {} if (series, autres) == (VIZ, VIZ_AUTRES) else {"series": series, "autres": autres}


def pale(couleur):
    """La même teinte, plus pâle (valeur provisoire) : à moitié blanche."""
    return melange(couleur, BLANC, .55)


def viz_sombre(couleur, surface):
    """Couleur d'une série sur les cartes sombres : éclaircie juste assez pour 3:1 (WCAG 1.4.11)."""
    return lisible(couleur, [surface], seuil=SEUIL_MARQUES + .1)


def css_graphiques_sombre(reglage, surface):
    """Variables des couleurs des graphiques de l'apparence sombre (palette fournie ou réglée, éclaircie au besoin)."""
    series, autres, _ = palette_graphiques(reglage)
    series = [viz_sombre(c, surface) for c in series]
    return ("".join(f"--viz-{i}: {c}; " for i, c in enumerate(series, start=1))
            + f"--viz-autres: {viz_sombre(autres, surface)}; --viz-pale: {melange(series[0], surface, .55)}; ")


def css_graphiques(reglage):
    """Variables des couleurs des graphiques pour ``couleurs_css`` ; « » sans réglage (celles d'outil.css)."""
    series, autres, regle = palette_graphiques(reglage)
    if not regle:
        return ""
    return "".join(f"--viz-{i}: {c}; " for i, c in enumerate(series, start=1)) + f"--viz-autres: {autres}; --viz-pale: {pale(series[0])}; "


def claire(couleur, rang, surface):
    """Couleur choisie par l'admin à moins de 3:1 sur la surface. Une teinte de la palette fournie, à sa place (rang 0
    à 7 : les séries, 8 : « Autres »), n'est jamais « trop claire » : ses teintes claires sont déjà accompagnées de
    motifs et de valeurs écrites (légende chiffrée, tableau des données)."""
    return couleur.upper() != (VIZ + [VIZ_AUTRES])[rang] and contraste(couleur, surface) < SEUIL_MARQUES


def controles_graphiques(series, autres, surface):
    """[{numéro, couleur, rapport, claire}] : chaque couleur contre la surface des cartes (« claire » : voir ``claire``)."""
    sortie = []
    for i, c in enumerate(list(series) + [autres]):
        sortie.append({"numero": i + 1 if i < len(series) else 0, "couleur": c, "rapport": round(contraste(c, surface), 1),
                       "claire": claire(c, i, surface)})
    return sortie


def series_claires(reglage, surface):
    """Rangs des couleurs choisies par l'admin à moins de 3:1 sur la surface (0 à 7 : les séries, 8 : « Autres ») : les
    valeurs de ces séries sont toujours écrites sur les graphiques. Vide avec la palette fournie : l'affichage ne change
    pas."""
    series, autres, regle = palette_graphiques(reglage)
    return [i for i, c in enumerate(series + [autres]) if claire(c, i, surface)] if regle else []


# ---------------------------------------------------------------- niveaux de l'organisation
# couleurs proposées aux nouveaux niveaux (assistant, Paramètres › Niveaux) ; neutres, sans couleur de marque (les niveaux
# existants gardent la leur)
COULEURS_NIVEAUX = ["#6A4FB3", "#6482FA", "#A0527A", "#2BBFAE", "#E0A526", "#4C9A2A", "#D9577A", "#5A6B85"]


def couleurs_niveau(couleur):
    """(fond des étiquettes, texte des étiquettes, fond des cartes) pour une couleur de niveau."""
    fond = melange(couleur, BLANC, .16)
    texte, part = couleur, .7
    while contraste(texte, fond) < SEUIL_AA and part > .05:
        texte, part = melange(couleur, NOIR, part), part - .05
    return fond, texte, melange(couleur, BLANC, .07)
