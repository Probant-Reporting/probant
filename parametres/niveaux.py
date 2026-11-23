"""Niveaux de l'organisation : lecture groupée (une requête), CSS des étiquettes, création de codes."""
import re
import unicodedata

from .models import NiveauHierarchique

# Les 4 niveaux créés à l'installation (codes historiques conservés : les données existantes restent valides)
PAR_DEFAUT = [
    # code, rang, nom, pluriel, couleur, fond, texte, pâle (couleurs neutres, tirées de COULEURS_NIVEAUX)
    ("Group", 1, "Groupe", "Groupe", "#6A4FB3", "#E7E3F3", "#6A4FB3", "#F5F3FA"),
    ("Country", 2, "Pays", "Pays", "#6482FA", "#E2E9FD", "#2B4596", "#EEF2FE"),
    ("Entity", 3, "Entité", "Entités", "#A0527A", "#F0E3EA", "#703955", "#F8F3F6"),
    ("Site", 4, "Site", "Sites", "#2BBFAE", "#D9F5F1", "#0E6B60", "#E9F8F5"),
]

PLURIELS_EN = {"Group": "Group", "Country": "Countries", "Entity": "Entities", "Site": "Sites"}  # traductions anglaises de départ

# Modèles de niveaux de l'assistant de mise en place (étape « Organisation ») : (clé, codes des niveaux, du sommet vers le
# bas). Les codes usuels facilitent l'installation des modèles fournis. Les noms sont dans ``NOMS_MODELES``.
MODELES_NIVEAUX = [
    ("groupe-pays-entite-site", ["Group", "Country", "Entity", "Site"]),
    ("groupe-pays-site", ["Group", "Country", "Site"]),
    ("holding-filiale-site", ["Holding", "Filiale", "Site"]),
    ("holding-filiale", ["Holding", "Filiale"]),
]
# Noms des niveaux des modèles dans les sept langues de l'interface : code → {langue: (nom, pluriel)}. Un contenu que l'outil
# installe, pas un texte de l'interface (docs/translation.md, « What is not translated ») : le niveau créé prend le nom de la
# langue de l'installation, et les six autres en traduction. Group, Country, Entity, Site : mêmes textes que les niveaux de
# départ (``PAR_DEFAUT``, ``PLURIELS_EN``, ``parametres/0036``), pour qu'une installation neuve reconnaisse son modèle
# (contrôlé par parametres/test_modeles_niveaux_langues.py). À faire relire par des natifs, comme les autres langues.
NOMS_MODELES = {
    "Group": {"en": ("Group", "Group"), "fr": ("Groupe", "Groupe"), "es": ("Grupo", "Grupo"), "de": ("Konzern", "Konzern"),
              "it": ("Gruppo", "Gruppo"), "nl": ("Groep", "Groep"), "pt": ("Grupo", "Grupo")},
    "Country": {"en": ("Country", "Countries"), "fr": ("Pays", "Pays"), "es": ("País", "Países"), "de": ("Land", "Länder"),
                "it": ("Paese", "Paesi"), "nl": ("Land", "Landen"), "pt": ("País", "Países")},
    "Entity": {"en": ("Entity", "Entities"), "fr": ("Entité", "Entités"), "es": ("Entidad", "Entidades"),
               "de": ("Gesellschaft", "Gesellschaften"), "it": ("Entità", "Entità"), "nl": ("Entiteit", "Entiteiten"),
               "pt": ("Entidade", "Entidades")},
    "Site": {"en": ("Site", "Sites"), "fr": ("Site", "Sites"), "es": ("Centro", "Centros"), "de": ("Standort", "Standorte"),
             "it": ("Sede", "Sedi"), "nl": ("Locatie", "Locaties"), "pt": ("Local", "Locais")},
    "Holding": {"en": ("Holding", "Holding"), "fr": ("Holding", "Holding"), "es": ("Holding", "Holding"),
                "de": ("Holding", "Holding"), "it": ("Holding", "Holding"), "nl": ("Holding", "Holding"),
                "pt": ("Holding", "Holding")},
    "Filiale": {"en": ("Subsidiary", "Subsidiaries"), "fr": ("Filiale", "Filiales"), "es": ("Filial", "Filiales"),
                "de": ("Tochtergesellschaft", "Tochtergesellschaften"), "it": ("Controllata", "Controllate"),
                "nl": ("Dochteronderneming", "Dochterondernemingen"), "pt": ("Filial", "Filiais")},
}


def _langue_modeles(langue):
    """Langue d'un nom de modèle : elle-même, sa langue de base (« pt-BR » → « pt »), sinon l'anglais."""
    for x in (langue or "", (langue or "").split("-")[0]):
        if x in NOMS_MODELES["Site"]:
            return x
    return "en"


def modeles_proposes(langue_ecran, langue_reference):
    """[(clé, libellé « A › B › C » dans la langue de l'écran, [(code, nom, pluriel, traductions)])] : les niveaux qu'un
    modèle crée, nommés dans la langue de référence de l'installation, avec la traduction des six autres langues
    ({langue: {"nom", "nom_pluriel"}})."""
    ecran, ref = _langue_modeles(langue_ecran), _langue_modeles(langue_reference)
    sortie = []
    for cle, codes in MODELES_NIVEAUX:
        defs = []
        for code in codes:
            noms = NOMS_MODELES[code]
            nom, pluriel = noms[ref]
            traductions = {lg: {"nom": n, "nom_pluriel": p} for lg, (n, p) in noms.items() if lg != ref}
            defs.append((code, nom, pluriel, traductions))
        sortie.append((cle, " › ".join(NOMS_MODELES[c][ecran][0] for c in codes), defs))
    return sortie


def creer_par_defaut():
    """Crée les 4 niveaux standard si aucun niveau n'existe (installation neuve, base vidée)."""
    if NiveauHierarchique.objects.exists():
        return
    for code, rang, nom, pluriel, c, fond, texte, pale in PAR_DEFAUT:
        NiveauHierarchique.objects.create(code=code, rang=rang, nom=nom, nom_pluriel=pluriel, couleur=c,
                                          couleur_fond=fond, couleur_texte=texte, couleur_pale=pale,
                                          traductions={"en": {"nom": code, "nom_pluriel": PLURIELS_EN.get(code, code)}})
    from .traductions_depart import completer

    completer()  # espagnol, allemand, italien, néerlandais, portugais (parametres/0036)


def tous():
    return list(NiveauHierarchique.objects.all())


def par_code():
    return {n.code: n for n in NiveauHierarchique.objects.all()}


def rangs():
    """{code: rang} — rang 1 = sommet ; un rang plus grand est plus bas dans l'arbre."""
    return dict(NiveauHierarchique.objects.values_list("code", "rang"))


def le_plus_bas():
    return NiveauHierarchique.objects.order_by("-rang").first()


def _regles(n, fond, texte, pale, trait):
    return [(f".niveau-{n.code}", f"background:{fond};color:{texte}"),
            (f".carte-{n.code}", f"--teinte:{pale};--teinte-forte:{trait};--teinte-texte:{texte}"),
            (f".niv-{n.code}", f"--c-niv:{trait};--p-niv:{pale}")]


def css(niveaux=None):
    """Couleurs propres à chaque niveau : étiquettes (.niveau-CODE), cartes (.carte-CODE), traits et fonds (.niv-CODE : --c-niv, --p-niv)."""
    from .couleurs import css_etiquettes

    return css_etiquettes(niveaux if niveaux is not None else tous(), _regles,
                          lambda n: (n.couleur_fond, n.couleur_texte, n.couleur_pale, n.couleur))


def regles_sombres(fond, niveaux=None):
    """Mêmes classes que ``css`` pour l'apparence sombre [(sélecteur, déclarations)] : couleurs tirées de la couleur du
    niveau sur le fond sombre (``fond`` : la surface de la gamme sombre)."""
    from .couleurs import etiquettes_sombres

    return etiquettes_sombres(niveaux if niveaux is not None else tous(), _regles, fond)


def nouveau_code(nom):
    """Code stable et sûr pour le CSS, tiré du nom (« Business unit » → « BusinessUnit »), unique."""
    base = unicodedata.normalize("NFKD", nom).encode("ascii", "ignore").decode()
    base = "".join(m.capitalize() for m in re.findall(r"[A-Za-z0-9]+", base))[:16] or "Niveau"
    if base[0].isdecimal():
        base = "N" + base
    code, i = base, 2
    while NiveauHierarchique.objects.filter(code=code).exists():
        code, i = f"{base[:14]}{i}", i + 1
    return code


def tous_sous(niveau):
    """Niveaux situés sous ``niveau`` (du plus proche au plus bas)."""
    return list(NiveauHierarchique.objects.filter(rang__gt=niveau.rang))


def codes():
    return list(NiveauHierarchique.objects.values_list("code", flat=True))


CODE_VALIDE = re.compile(r"^[A-Za-z][A-Za-z0-9]{0,19}$")


def utilises():
    """Codes des niveaux qui portent des organisations, des KPI ou des règles (non supprimables)."""
    from collecte.models import RegleCoherence
    from referentiel.models import KPI, Organisation

    return (set(Organisation.objects.values_list("niveau_id", flat=True)) | set(KPI.objects.values_list("granularite_id", flat=True))
            | set(RegleCoherence.objects.values_list("niveau_id", flat=True)))
