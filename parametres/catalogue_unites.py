"""Catalogue d'unités proposées, rangées par thématique (Paramètres › Référentiel › Unités).

Rien n'est installé d'office : l'admin coche les unités utiles et les ajoute ; tout reste modifiable ensuite.
Chaque unité : (symbole, libellé, comptage entier, décimales par défaut).
"""

THEMES = [
    # thématique, explication, unités
    ("Énergie", "Consommations d'électricité, de gaz, de chaleur ; production d'énergie renouvelable.", [
        ("Wh", "wattheure", False, 0), ("kWh", "kilowattheure", False, 0), ("MWh", "mégawattheure", False, 1),
        ("GWh", "gigawattheure", False, 2), ("TWh", "térawattheure", False, 3), ("kWh PCI", "kilowattheure PCI", False, 0),
        ("kWh PCS", "kilowattheure PCS", False, 0), ("MJ", "mégajoule", False, 0), ("GJ", "gigajoule", False, 1),
        ("TJ", "térajoule", False, 2), ("tep", "tonne équivalent pétrole", False, 2), ("kW", "kilowatt (puissance)", False, 0),
        ("MW", "mégawatt (puissance)", False, 2), ("kWc", "kilowatt-crête (photovoltaïque)", False, 0),
    ]),
    ("Émissions", "Gaz à effet de serre en équivalent CO₂, polluants atmosphériques.", [
        ("gCO2eq", "gramme équivalent CO₂", False, 0), ("kgCO2eq", "kilogramme équivalent CO₂", False, 0),
        ("tCO2eq", "tonne équivalent CO₂", False, 1), ("ktCO2eq", "kilotonne équivalent CO₂", False, 2),
        ("MtCO2eq", "mégatonne équivalent CO₂", False, 3), ("kg NOx", "kilogramme d'oxydes d'azote", False, 1),
        ("kg SO2", "kilogramme de dioxyde de soufre", False, 1), ("kg PM10", "kilogramme de particules fines", False, 1),
        ("kg CFC-11 eq", "kilogramme équivalent CFC-11 (couche d'ozone)", False, 2),
    ]),
    ("Masse", "Déchets, emballages, matières premières, produits.", [
        ("mg", "milligramme", False, 0), ("g", "gramme", False, 0), ("kg", "kilogramme", False, 0), ("t", "tonne", False, 1),
        ("kt", "kilotonne", False, 2),
    ]),
    ("Volume", "Eau prélevée ou rejetée, carburants, liquides.", [
        ("mL", "millilitre", False, 0), ("L", "litre", False, 0), ("hL", "hectolitre", False, 1), ("m³", "mètre cube", False, 0),
        ("ML", "mégalitre (1 000 m³)", False, 2),
    ]),
    ("Surface", "Bâtiments, terrains, espaces verts, sols artificialisés.", [
        ("m²", "mètre carré", False, 0), ("ha", "hectare", False, 2), ("km²", "kilomètre carré", False, 2),
    ]),
    ("Distance", "Déplacements professionnels, trajets domicile-travail, transport de marchandises.", [
        ("m", "mètre", False, 0), ("km", "kilomètre", False, 0), ("p.km", "passager-kilomètre", False, 0),
        ("t.km", "tonne-kilomètre", False, 0), ("véh.km", "véhicule-kilomètre", False, 0),
    ]),
    ("Durée", "Temps de formation, absentéisme, heures travaillées, ancienneté.", [
        ("min", "minute", False, 0), ("h", "heure", False, 0), ("jours", "jours", False, 0), ("semaines", "semaines", False, 1),
        ("mois", "mois", False, 1), ("années", "années", False, 1),
    ]),
    ("Effectif", "Personnes : salariés, équivalents temps plein, stagiaires, intérimaires.", [
        ("salariés", "salariés", True, 0), ("ETP", "équivalent temps plein", False, 1), ("personnes", "personnes", True, 0),
        ("collaborateurs", "collaborateurs", True, 0), ("intérimaires", "intérimaires (en ETP)", False, 1),
        ("stagiaires", "stagiaires", True, 0), ("alternants", "alternants", True, 0), ("managers", "managers", True, 0),
    ]),
    ("Monnaie", "Chiffre d'affaires, dépenses, investissements, dons.", [
        ("€", "euro", False, 0), ("k€", "millier d'euros", False, 0), ("M€", "million d'euros", False, 1),
        ("Md€", "milliard d'euros", False, 2), ("$", "dollar américain", False, 0), ("£", "livre sterling", False, 0),
        ("CHF", "franc suisse", False, 0),
    ]),
    ("Pourcentage et ratios", "Parts, taux, écarts. Un pourcentage se saisit de préférence avec le type de réponse « Pourcentage ».", [
        ("%", "pour cent", False, 1), ("‰", "pour mille", False, 1), ("pts", "points (écart de pourcentage)", False, 1),
        ("ratio", "ratio (sans unité)", False, 2),
    ]),
    ("Intensités", "Une quantité rapportée à une autre : par salarié, par m², par chiffre d'affaires, par colis…", [
        ("kWh/m²", "kilowattheure par mètre carré", False, 0), ("kWh/salarié", "kilowattheure par salarié", False, 0),
        ("tCO2eq/M€", "tonne équivalent CO₂ par million d'euros", False, 1),
        ("kgCO2eq/salarié", "kilogramme équivalent CO₂ par salarié", False, 0),
        ("gCO2eq/km", "gramme équivalent CO₂ par kilomètre", False, 0), ("kgCO2eq/kWh", "facteur d'émission de l'énergie", False, 3),
        ("kgCO2eq/€", "facteur d'émission monétaire", False, 3), ("m³/salarié", "mètre cube d'eau par salarié", False, 1),
        ("kg/salarié", "kilogramme par salarié", False, 1), ("L/100 km", "litres aux 100 kilomètres", False, 1),
        ("h/salarié", "heures par salarié (formation…)", False, 1), ("€/salarié", "euro par salarié", False, 0),
    ]),
    ("Santé et sécurité", "Indicateurs normalisés des accidents du travail.", [
        ("TF", "taux de fréquence (accidents par million d'heures travaillées)", False, 2),
        ("TG", "taux de gravité (jours perdus par millier d'heures travaillées)", False, 2),
        ("accidents", "accidents", True, 0), ("jours d'arrêt", "jours d'arrêt", True, 0),
    ]),
    ("Comptages", "Des objets ou des événements que l'on compte un par un : toujours des nombres entiers.", [
        ("nombre", "nombre", True, 0), ("sites", "sites", True, 0), ("bâtiments", "bâtiments", True, 0),
        ("fournisseurs", "fournisseurs", True, 0), ("audits", "audits", True, 0), ("formations", "formations", True, 0),
        ("incidents", "incidents", True, 0), ("plaintes", "plaintes", True, 0), ("véhicules", "véhicules", True, 0),
        ("produits", "produits", True, 0), ("commandes", "commandes", True, 0), ("colis", "colis", True, 0),
        ("pays", "pays", True, 0), ("certifications", "certifications", True, 0),
    ]),
    ("Note", "Scores, évaluations, notes sur une échelle.", [
        ("/5", "note sur 5", False, 1), ("/10", "note sur 10", False, 1), ("/20", "note sur 20", False, 1),
        ("/100", "note sur 100", False, 0),
    ]),
]

NOMS = [t for t, _, _ in THEMES]


def par_symbole():
    """{symbole en minuscules : (thématique, libellé, entier, décimales)}."""
    return {s.lower(): (t, l, e, d) for t, _, unites in THEMES for s, l, e, d in unites}


# ---------------------------------------------------------------- textes affichés dans la langue de l'interface
# Le catalogue est écrit en français (ci-dessus) ; ses traductions sont dans les fichiers de langue de la zone
# « admin » (``admin.catalogue_unites.*``), une clé par texte, tirée du texte français. Ce qui est enregistré (thématique
# d'une unité, nom de l'unité ajoutée) reste le texte français du catalogue.
PREFIXE = "admin.catalogue_unites"


def cle(texte):
    """Morceau de clé tiré d'un texte français : « Pourcentage et ratios » → « pourcentage_et_ratios »."""
    import re
    import unicodedata

    t = unicodedata.normalize("NFKD", texte).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", t).strip("_")[:80]


# Symboles qui sont des mots français (ou en contiennent un) : « semaines », « salariés », « kWh/salarié »… Leur traduction est
# dans les mêmes fichiers de langue (``admin.catalogue_unites.symbole.*``) ; les autres symboles (kWh, t, %, m²…) sont les
# mêmes dans toutes les langues et ne sont pas listés.
SYMBOLES_TRADUITS = (
    "jours", "semaines", "mois", "années", "salariés", "ETP", "personnes", "collaborateurs", "intérimaires", "stagiaires",
    "alternants", "accidents", "jours d'arrêt", "nombre", "sites", "bâtiments", "fournisseurs", "audits", "formations",
    "incidents", "plaintes", "véhicules", "produits", "commandes", "colis", "pays", "certifications", "ratio", "pts", "tep",
    "véh.km", "kWh/salarié", "kgCO2eq/salarié", "m³/salarié", "kg/salarié", "h/salarié", "€/salarié",
)


def cles_catalogue():
    """{clé du fichier de langue : texte français} de tout le catalogue (thématiques, explications, noms et symboles des unités)."""
    sortie = {}
    for nom, aide, unites in THEMES:
        sortie[f"{PREFIXE}.theme.{cle(nom)}"] = nom
        sortie[f"{PREFIXE}.aide.{cle(nom)}"] = aide
        for symbole, libelle_unite, _, _ in unites:
            sortie[f"{PREFIXE}.unite.{cle(libelle_unite)}"] = libelle_unite
            if symbole in SYMBOLES_TRADUITS:
                sortie[f"{PREFIXE}.symbole.{cle(symbole)}"] = symbole
    return sortie


def _traduit(genre, texte_fr, langue=None, cle_texte=None):
    from .libelles import table, libelle

    c = f"{PREFIXE}.{genre}.{cle(cle_texte or texte_fr)}"
    return libelle(c, langue) if c in table("fr") and table("fr")[c] == texte_fr else texte_fr


# Thématiques que les modèles fournis ont écrites sur leurs unités avant d'être alignés sur le catalogue : une installation
# existante les garde enregistrées telles quelles ; à l'écran, elles se rangent dans la thématique du catalogue qui leur
# correspond (donc se traduisent). Aucune donnée n'est changée.
THEMES_HISTORIQUES = {"facteur d'émission": "Intensités", "conversion": "Intensités", "comptage": "Comptages"}


def theme_du_catalogue(nom):
    """Nom de la thématique du catalogue que désigne ``nom`` (le sien ou une thématique historique), sinon ``None``."""
    cle = (nom or "").strip().lower()
    return next((t for t, _, _ in THEMES if t.lower() == cle), None) or THEMES_HISTORIQUES.get(cle)


def nom_theme(nom, langue=None):
    """Nom affiché d'une thématique : traduit si c'est une thématique du catalogue (« Durée » → « Duration »), sinon tel
    quel (thématique propre à l'installation)."""
    officiel = theme_du_catalogue(nom)
    return _traduit("theme", officiel, langue) if officiel else nom


def aide_theme(nom, aide, langue=None):
    return _traduit("aide", aide, langue, nom)


def nom_unite(libelle_unite, langue=None):
    return _traduit("unite", libelle_unite, langue)


def nom_symbole(symbole, langue=None):
    """Symbole affiché d'une unité du catalogue : traduit quand c'est un mot (« semaines » → « weeks », « Wochen »)."""
    return _traduit("symbole", symbole, langue) if symbole in SYMBOLES_TRADUITS else symbole


def traductions_installation(symbole, libelle_unite, langue_reference):
    """Traductions d'une unité installée depuis le catalogue ({langue: {"libelle", "symbole"}}), dans toutes les langues
    de l'interface sauf la langue de référence, qui garde le texte du catalogue. Un symbole qui n'est pas un mot (kWh) n'a
    pas de traduction de symbole. Même forme que les traductions de départ des unités fournies."""
    from .libelles import langues_disponibles

    sortie = {}
    for lg in langues_disponibles():
        if lg == langue_reference:
            continue
        textes = {"libelle": nom_unite(libelle_unite, lg)}
        if symbole in SYMBOLES_TRADUITS:
            textes["symbole"] = nom_symbole(symbole, lg)
        sortie[lg] = textes
    return sortie
