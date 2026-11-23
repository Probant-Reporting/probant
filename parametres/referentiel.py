"""Référentiel réglable : unités, types de saisie et de réponse, catégories de description, champs personnalisés.

Valeurs d'installation, étiquettes colorées des types, usages (un élément utilisé ne se supprime pas), codes.
"""
import re
import unicodedata

from .models import CategorieDescription, Instance, Langue, TypeReponse, TypeSaisie, Unite

TYPES_SAISIE = [  # code, libellé, étiquette courte, couleur, fond, texte de l'étiquette, comportement
    # (couleurs par défaut d'une nouvelle installation, distinctes des couleurs d'état : jaune = brouillon, vert = validé)
    ("Saisi", "Saisi", "Saisie", "#5A6B85", "#E8ECF2", "#3D4A5C", "saisie"),
    ("Calculé", "Calculé", "Calcul", "#2B4596", "#E2E9FD", "#2B4596", "calcul"),
    ("FE", "Facteur d'émission", "FE", "#B04BC4", "#F5E4F7", "#8A2C9C", "herite"),
]
TYPES_EN = {"Saisi": "Input", "Calculé": "Calculated", "FE": "Emission factor"}  # traductions anglaises de départ
ABREGES_EN = {"Saisi": "Input", "Calculé": "Calc.", "FE": "EF"}  # étiquettes courtes en anglais (migration 0016)
TYPES_REPONSE = [("Numérique", "Numérique", "nombre"), ("Pourcentage", "Pourcentage", "pourcentage"),
                 ("TexteRedige", "Texte rédigé", "texte")]  # texte rédigé : (parametres/0020)
TYPES_REPONSE_EN = {"Numérique": "Number", "Pourcentage": "Percentage", "TexteRedige": "Written text"}  # traductions de départ
TYPES_REPONSE_ES = {"Numérique": "Número", "Pourcentage": "Porcentaje", "TexteRedige": "Texto redactado"}
TYPES_ES = {"Saisi": "Introducido", "Calculé": "Calculado", "FE": "Factor de emisión"}  # traductions espagnoles de départ
ABREGES_ES = {"Saisi": "Entrada", "Calculé": "Cálc.", "FE": "FE"}
LANGUES = [("fr", "Français"), ("en", "English")]  # langues d'installation (d'autres s'ajoutent dans Paramètres › Langues)
CATEGORIES = [("description", "Description"), ("a_inclure", "À inclure"), ("a_exclure", "À exclure"), ("source", "Source des données")]
CATEGORIES_TRAD = {  # traductions de départ des catégories (contenus en français, anglais et espagnol)
    "description": {"en": "Description", "es": "Descripción"},
    "a_inclure": {"en": "To include", "es": "Incluir"},
    "a_exclure": {"en": "To exclude", "es": "Excluir"},
    "source": {"en": "Data source", "es": "Fuente de los datos"},
}


def creer_par_defaut():
    """Langues, types et catégories d'installation, s'il n'en existe aucun (base neuve ou vidée)."""
    if not Langue.objects.exists():
        for i, (code, libelle) in enumerate(LANGUES, start=1):
            Langue.objects.create(code=code, libelle=libelle, ordre=i)
        i = Instance.courante()
        if not Langue.objects.filter(code=i.langue_reference).exists():
            Langue.objects.create(code=i.langue_reference, libelle=i.langue_reference, ordre=0)
    cree = False
    if not TypeSaisie.objects.exists():
        cree = True
        for i, (code, libelle, abrege, c, fond, texte, comportement) in enumerate(TYPES_SAISIE, start=1):
            TypeSaisie.objects.create(code=code, libelle=libelle, abrege=abrege, couleur=c, couleur_fond=fond, couleur_texte=texte,
                                      comportement=comportement, ordre=i, traductions={"en": {"libelle": TYPES_EN[code], "abrege": ABREGES_EN[code]},
                                                                        "es": {"libelle": TYPES_ES[code], "abrege": ABREGES_ES[code]}})
    if not TypeReponse.objects.exists():
        cree = True
        for i, (code, libelle, fmt) in enumerate(TYPES_REPONSE, start=1):
            traductions = {lg: {"libelle": t[code]} for lg, t in (("en", TYPES_REPONSE_EN), ("es", TYPES_REPONSE_ES)) if code in t}
            TypeReponse.objects.create(code=code, libelle=libelle, format=fmt, ordre=i, traductions=traductions)
    if not CategorieDescription.objects.exists():
        cree = True
        for i, (code, libelle) in enumerate(CATEGORIES, start=1):
            CategorieDescription.objects.create(code=code, libelle=libelle, ordre=i, traductions={
                lg: {"libelle": t} for lg, t in CATEGORIES_TRAD.get(code, {}).items()})
    if cree:
        from .traductions_depart import completer

        completer()  # allemand, italien, néerlandais, portugais des types et des catégories fournis (parametres/0036)


def couleurs_types_par_defaut():
    """Démos : couleurs d'installation des types de saisie fournis (Saisi, Calculé, FE), distinctes des couleurs d'état
    (jaune = brouillon, vert = validé). Jamais appelé sur une installation réelle : elle garde ses couleurs réglées."""
    for code, _, _, c, fond, texte, _ in TYPES_SAISIE:
        TypeSaisie.objects.filter(code=code).update(couleur=c, couleur_fond=fond, couleur_texte=texte)


def classe_type(code):
    """Classe CSS d'un type de saisie (le code peut contenir des accents) : « ts-Calcul »."""
    base = unicodedata.normalize("NFKD", code).encode("ascii", "ignore").decode()
    return "ts-" + (re.sub(r"[^A-Za-z0-9_-]", "_", base) or "x")


def _regles_type(t, fond, texte, _pale, _trait):
    return [(f".{classe_type(t.code)}", f"background:{fond};color:{texte}")]


def css(types=None):
    """Étiquettes colorées des types de saisie."""
    from .couleurs import css_etiquettes

    return css_etiquettes(types if types is not None else TypeSaisie.objects.all(), _regles_type,
                          lambda t: (t.couleur_fond, t.couleur_texte, None, None))


def regles_sombres(fond, types=None):
    """Étiquettes des types de saisie dans l'apparence sombre [(sélecteur, déclarations)], tirées de leur couleur."""
    from .couleurs import etiquettes_sombres

    return etiquettes_sombres(types if types is not None else TypeSaisie.objects.all(), _regles_type, fond)


def nouveau_code(modele, texte, longueur=20):
    """Code stable tiré d'un libellé (« Oui / non » → « OuiNon »), unique pour le modèle."""
    base = unicodedata.normalize("NFKD", texte).encode("ascii", "ignore").decode()
    base = "".join(m[:1].upper() + m[1:] for m in re.findall(r"[A-Za-z0-9]+", base))[:longueur - 2] or "X"
    code, i = base, 2
    while modele.objects.filter(code=code).exists():
        code, i = f"{base}{i}", i + 1
    return code


def code_unite(symbole):
    """Une nouvelle unité garde son symbole comme code (ex. « kWh »), rendu unique si besoin."""
    code, i = symbole.strip()[:56] or "u", 2
    while Unite.objects.filter(code=code).exists():
        code, i = f"{symbole.strip()[:56]}~{i}", i + 1
    return code


def usages():
    """{section: {code: nombre d'usages}} : KPI pour les unités et types, textes pour les catégories, KPI renseignés pour les champs."""
    from django.db.models import Count

    from referentiel.models import KPI, Description

    u = {
        "unites": dict(KPI.objects.exclude(unite=None).values_list("unite").annotate(n=Count("pk")).values_list("unite", "n")),
        "types-saisie": dict(KPI.objects.values_list("type_saisie").annotate(n=Count("pk")).values_list("type_saisie", "n")),
        "types-reponse": dict(KPI.objects.values_list("type_reponse").annotate(n=Count("pk")).values_list("type_reponse", "n")),
        "categories": dict(Description.objects.values_list("categorie").annotate(n=Count("pk")).values_list("categorie", "n")),
        "champs": {},
    }
    # une liste de choix sert aussi aux colonnes des tableaux : comptée une fois par KPI du tableau (ni supprimable, ni
    # changée de format tant qu'un tableau y renvoie)
    for tableau in TypeReponse.objects.filter(format=TypeReponse.Format.TABLEAU):
        n = u["types-reponse"].get(tableau.code, 0) or 1
        for c in tableau.colonnes or []:
            if isinstance(c, dict) and c.get("liste"):
                u["types-reponse"][c["liste"]] = u["types-reponse"].get(c["liste"], 0) + n
    for champs in KPI.objects.exclude(champs={}).values_list("champs", flat=True):
        for code, v in champs.items():
            if v not in ("", None, False):
                u["champs"][code] = u["champs"].get(code, 0) + 1
    return u


# ---------------------------------------------------------------- unités créées depuis un texte (imports)
COMPTAGES = {"employees", "accidents", "deaths", "complaints", "incidents", "members", "hires", "departures", "cases",
             "reports", "warehouses", "units", "breaches", "requests", "actions", "suppliers", "countries", "brands",
             "products", "sales", "parcels", "professions", "applications", "virtual machines", "meals", "nights",
             "salariés", "personnes", "sites", "nombre"}


MOTS_DUREE = {"hours", "days", "years", "months", "weeks", "nights"}

# Unités écrites en anglais dans un référentiel importé (par exemple « employees », « members »…) : symbole en français,
# anglais et espagnol (règle du projet : des fichiers en français affichaient des unités en anglais).
# Le code de l'unité, clé dans les fichiers, ne change pas.
SYMBOLES_ANGLAIS = {
    "accidents": ("accidents", "accidentes"), "agreements": ("accords", "acuerdos"),
    "applications": ("applications", "aplicaciones"), "apprentices": ("apprentis", "aprendices"),
    "associations": ("associations", "asociaciones"), "beneficiaries": ("bénéficiaires", "beneficiarios"),
    "brands": ("marques", "marcas"), "breaches": ("violations", "violaciones"), "cases": ("cas", "casos"),
    "complaints": ("plaintes", "quejas"), "convictions": ("condamnations", "condenas"), "countries": ("pays", "países"),
    "days": ("jours", "días"), "deaths": ("décès", "fallecimientos"), "departures": ("départs", "salidas"),
    "emails": ("e-mails", "correos"), "employees": ("salariés", "empleados"), "FTE": ("ETP", "ETC"),
    "hires": ("embauches", "contrataciones"), "hours": ("heures", "horas"), "incidents": ("incidents", "incidentes"),
    "initiatives": ("initiatives", "iniciativas"), "interns": ("stagiaires", "becarios"), "meals": ("repas", "comidas"),
    "meetings": ("réunions", "reuniones"), "members": ("membres", "miembros"),
    "nationalities": ("nationalités", "nacionalidades"), "nights": ("nuitées", "noches"), "parcels": ("colis", "paquetes"),
    "participations": ("participations", "participaciones"), "people": ("personnes", "personas"),
    "proceedings": ("procédures", "procedimientos"), "products": ("produits", "productos"),
    "professions": ("métiers", "profesiones"), "reams": ("ramettes", "resmas"), "reports": ("signalements", "denuncias"),
    "requests": ("demandes", "solicitudes"), "sales": ("ventes", "ventas"), "sanctions": ("sanctions", "sanciones"),
    "snacks": ("en-cas", "tentempiés"), "suppliers": ("fournisseurs", "proveedores"), "units": ("unités", "unidades"),
    "virtual machines": ("machines virtuelles", "máquinas virtuales"), "warehouses": ("entrepôts", "almacenes"),
    "websites": ("sites web", "sitios web"), "workers": ("intérimaires", "trabajadores temporales"),
    "years": ("ans", "años"),
    "hours/employee": ("heures/salarié", "horas/empleado"), "kg/employee": ("kg/salarié", "kg/empleado"),
    "kg/parcel": ("kg/colis", "kg/paquete"), "kgCO2 éq / package": ("kgCO2 éq / colis", "kgCO2 eq / paquete"),
    "kgCO2eq/employee": ("kgCO2eq/salarié", "kgCO2eq/empleado"), "kgCO2eq/meal": ("kgCO2eq/repas", "kgCO2eq/comida"),
    "kgCO2eq/parcel": ("kgCO2eq/colis", "kgCO2eq/paquete"),
    "kgCO2eq/passenger-km": ("kgCO2eq/passager-km", "kgCO2eq/pasajero-km"),
    "kgCO2eq/ream": ("kgCO2eq/ramette", "kgCO2eq/resma"), "kgCO2eq/snack": ("kgCO2eq/en-cas", "kgCO2eq/tentempié"),
    "parcels/day": ("colis/jour", "paquetes/día"), "parcels/order": ("colis/commande", "paquetes/pedido"),
    "visitors/day": ("visiteurs/jour", "visitantes/día"), "tCO2eq/M parcels": ("tCO2eq/M colis", "tCO2eq/M paquetes"),
    "days per thousand hours worked": ("jours par millier d'heures travaillées", "días por mil horas trabajadas"),
    "per million hours worked": ("par million d'heures travaillées", "por millón de horas trabajadas"),
}


def symboles_unite(anglais):
    """{langue: symbole} d'une unité écrite en anglais (SYMBOLES_ANGLAIS), ou {} si elle n'y est pas."""
    t = SYMBOLES_ANGLAIS.get((anglais or "").strip())
    return {"en": anglais.strip(), "fr": t[0], "es": t[1]} if t else {}


def traduire_unite(u, reference):
    """Symbole d'une unité écrite en anglais dans les trois langues : celui de la langue de référence dans le champ, les
    autres dans ``traductions`` (une traduction déjà saisie n'est jamais remplacée). Renvoie True si l'unité a changé."""
    mots = symboles_unite(u.symbole)
    if not mots:
        return False
    trad = {l: dict(d or {}) for l, d in (u.traductions or {}).items()}
    for langue, mot in mots.items():
        if langue != reference and not trad.get(langue, {}).get("symbole"):
            trad.setdefault(langue, {})["symbole"] = mot
    if reference in mots:
        u.symbole = mots[reference]
    u.traductions = {l: d for l, d in trad.items() if d}
    return True


def famille(symbole):
    """Thématique devinée d'après le symbole (catalogue, puis mots courants en français et en anglais), sinon ""."""
    from .catalogue_unites import par_symbole

    s = symbole.lower().strip()
    if s in par_symbole():
        return par_symbole()[s][0]
    if "per million hours" in s or "per thousand hours" in s:
        return "Santé et sécurité"
    if "/" in s and not s.startswith("/") or " per " in s:
        return "Intensités"
    if s in MOTS_DUREE:
        return "Durée"
    if s in COMPTAGES:
        return "Comptages"
    if "co2" in s or "co₂" in s:
        return "Émissions"
    familles = {"Énergie": ("kwh", "mwh", "gwh", "wh"), "Masse": ("t", "kg", "g", "tonne(s)", "tonnes"), "Monnaie": ("€", "k€", "m€"),
                "Volume": ("m³", "m3", "l"), "Durée": ("hours", "days", "years", "h", "jours"),
                "Effectif": ("employees", "fte", "people", "members", "employés", "salariés"), "Pourcentage et ratios": ("%",)}
    for nom, symboles in familles.items():
        if s in symboles:
            return nom
    return "Note" if s.startswith("/") else ""


def nouvelle_unite(symbole, code, ordre, decimales=2):
    """Unité à créer (non enregistrée) pour un symbole libre cité par un fichier (référentiel, configuration, fichier
    référentiel) : nombre entier pour un comptage, thématique devinée, symbole anglais traduit (« employees » :
    « salariés » dans un outil en français). ``code`` : celui que chaque chemin calcule."""
    from . import langues

    entier = symbole.lower() in COMPTAGES
    u = Unite(code=code, symbole=symbole[:60], entier=entier, famille=famille(symbole), decimales=0 if entier else decimales,
              ordre=ordre)
    traduire_unite(u, langues.reference())
    return u


def unite_depuis_symbole(symbole, decimales=2):
    """Unité d'un texte libre (fichier importé) : retrouvée par son code ou son symbole, sinon créée."""
    symbole = symbole.strip()[:60]
    u = Unite.objects.filter(code=symbole).first() or Unite.objects.filter(symbole=symbole).first()
    if u is None:
        u = nouvelle_unite(symbole, code_unite(symbole), Unite.objects.count() + 1, decimales)
        u.save()
    return u
