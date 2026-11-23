"""Fichiers d'échange (Excel et CSV) : lecture tolérante des en-têtes, nombres « à la française », mise en forme commune."""
import codecs
import contextvars
import csv
import datetime
import io
import re
import unicodedata
import warnings
import zipfile
from decimal import Decimal, InvalidOperation
from functools import lru_cache

from django.conf import settings
from django.http import HttpResponse
from django.utils import timezone
from openpyxl import Workbook, load_workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles.cell_style import StyleArray
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo
from openpyxl.worksheet.worksheet import Worksheet

from parametres.libelles import libelle, langues_disponibles, table as table_libelles

from .styles_excel import Alignment, Font, PatternFill  # créés une fois par réglage (pas un objet par cellule)

# Couleurs des fichiers Excel : reprises de l'identité de l'installation (et des niveaux) à chaque export (voir
# couleurs_marque), propres au fil qui fait l'export (ContextVar) : deux exports simultanés de deux espaces dans le même
# processus (gunicorn, plusieurs fils) ne mélangent pas leurs couleurs. Lues par ``X.MAGENTA``, ``X.NIVEAU_COULEURS``…
# (``__getattr__`` du module) ou ``palette()["MAGENTA"]`` dans ce module.
# Par défaut (avant ``couleurs_marque``) : la palette par défaut de l'outil (Océan, ``parametres.couleurs``).
PALETTE_DEFAUT = {
    "MAGENTA": "1F5FAD", "ROSE": "E6EDF6", "ROSE_PALE": "F4F7FB", "VIOLET": "09615F", "VIOLET_PALE": "D9EFEF",
    "GRIS": "F2F4F7", "GRIS_TEXTE": "5C656E",
    "NIVEAU_COULEURS": {},  # {code du niveau: (fond, texte)}, repris de Paramètres › Niveaux
}
_PALETTE = contextvars.ContextVar("palette_excel", default=None)


def palette():
    """Couleurs du fil courant (celles de l'installation après ``couleurs_marque``, sinon celles par défaut)."""
    return _PALETTE.get() or PALETTE_DEFAUT


def __getattr__(nom):
    if nom in PALETTE_DEFAUT:
        return palette()[nom]
    raise AttributeError(f"module {__name__!r} has no attribute {nom!r}")


TAILLE_MAX = settings.IMPORT_TAILLE_MAX  # TAILLE_MAX_IMPORT_MO (10 par défaut)


def sans_fin_vide(liste):
    """Copie de la liste sans ses éléments vides de fin (traductions de valeurs d'une liste de choix)."""
    liste = list(liste)
    while liste and not liste[-1]:
        liste.pop()
    return liste


def court(t, n=60):
    """Texte sur une ligne, coupé à ``n`` caractères (« … ») : aperçu des changements avant import."""
    t = str(t or "").replace("\n", " ")
    return t if len(t) <= n else t[:n - 1] + "…"


def _compte(n):
    """32767 → « 32 767 » (FR), « 32,767 » (EN), « 32.767 » (ES) : séparateur de milliers de la langue."""
    from .templatetags.collecte import entier

    return entier(n)


def mo(octets):
    """5242880 → « 5 » ; 1572864 → « 1,5 » (tailles maximales affichées)."""
    from .templatetags.collecte import separateurs

    return f"{octets / 1024 / 1024:.1f}".rstrip("0").rstrip(".").replace(".", separateurs()[1])
DANGEREUX = ("=", "+", "-", "@", "\t", "\r")  # début de formule dans un tableur (tabulation et retour chariot compris, que
# certains tableurs sautent avant de lire une formule) : neutralisé dans les cellules de texte
# Classeur déposé : nombre de cellules au plus, une fois ouvert (un .xlsx est compressé : 5 Ko peuvent annoncer des
# milliards de cellules). Gardées : cellules rendues (vides de fin de ligne retirées) ; lues : toutes celles parcourues.
CELLULES_MAX = 5_000_000
CELLULES_LUES_MAX = 20_000_000
# Avant d'ouvrir un classeur (controler_classeur) : taille totale décompressée (MAX_XLSX_UNCOMPRESSED_MB, par défaut
# 20 fois la taille d'import, soit 200 Mo ; un classeur réel de 10 Mo en fait 100 à 170), taux de compression d'une entrée (une dizaine pour un vrai
# classeur, près de 1 000 pour une bombe) et longueur d'un texte de cellule (limite d'Excel)
DECOMPRESSE_MAX = settings.XLSX_DECOMPRESSE_MAX
TAUX_MAX, TAUX_A_PARTIR_DE = 100, 1024 * 1024
TEXTE_CELLULE_MAX = 32_767
# un texte de cellule s'écrit en XML sans « < » ; un caractère y prend au plus 6 octets (« &quot; »)
SANS_BALISE_MAX = TEXTE_CELLULE_MAX * 6


CONTROLE = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]")  # caractères de contrôle (sauf tabulation et retours à la ligne) :
# invisibles, refusés par Excel (une seule de ces cellules faisait échouer tout un export) ; de même les caractères
# interdits en XML (U+FFFE, U+FFFF, moitiés de paire isolées), que openpyxl laisse passer


def sans_controle(v):
    """Texte sans caractère de contrôle (venu d'un CSV, d'un copier-coller) ; le reste est rendu tel quel."""
    return CONTROLE.sub("", v) if isinstance(v, str) and CONTROLE.search(v) else v


class FichierInvalide(Exception):
    pass


# ---------------------------------------------------------------- lecture
def normaliser(texte):
    """« Valeur N-1 » → « valeurn1 » : comparaison d'en-têtes sans accents, casse ni ponctuation."""
    texte = unicodedata.normalize("NFKD", str(texte or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", texte.lower())


class PourcentExcel(float):
    """Nombre d'une cellule Excel au format pourcentage (« 12,5 % » tapé est rangé 0,125) : la valeur reste celle de la
    cellule ; l'import des valeurs la lit sur 100 pour un KPI pourcentage (voir ``imports.analyser``)."""

    __slots__ = ()


def format_pourcentage(fmt):
    """Vrai si le format de nombre Excel affiche la valeur × 100 (« 0% », « 0.0 % ») ; un « % » entre guillemets ou
    précédé de « \\ » n'est que du texte (« #,##0.00" %" » des exports : valeur déjà sur 100)."""
    if not fmt or "%" not in fmt:
        return False
    return "%" in re.sub(r'"[^"]*"|\\.|\[[^\]]*\]', "", fmt)


def _cellule(c):
    v = c.value
    if isinstance(v, str) and len(v) > TEXTE_CELLULE_MAX:
        raise FichierInvalide(libelle("suivi.fichier.erreur.texte_trop_long", n=_compte(TEXTE_CELLULE_MAX)))
    if isinstance(v, (int, float)) and not isinstance(v, bool) and format_pourcentage(getattr(c, "number_format", "")):
        return PourcentExcel(v)
    return v


def _onglet(ws, compte):
    """Lignes d'un onglet (format de chaque cellule gardé pour les pourcentages Excel : PourcentExcel), dans la limite de
    CELLULES_MAX cellules pour tout le classeur. Une plage déclarée démesurée (balise « dimension » forgée, mise en forme
    jusqu'à la dernière colonne) n'est pas crue : chaque ligne s'arrête à sa dernière cellule remplie."""
    rognees = (ws.max_row or 0) * (ws.max_column or 0) > CELLULES_MAX
    if rognees:
        ws.reset_dimensions()
    lignes = []
    for r in ws.iter_rows():
        compte["lues"] += len(r) + 1
        if compte["lues"] > CELLULES_LUES_MAX:
            raise FichierInvalide(libelle("suivi.fichier.erreur.trop_de_cellules", n=_compte(CELLULES_MAX)))
        ligne = [_cellule(c) for c in r]
        while rognees and ligne and ligne[-1] is None:
            ligne.pop()
        compte["gardees"] += len(ligne) + 1
        if compte["gardees"] > CELLULES_MAX:
            raise FichierInvalide(libelle("suivi.fichier.erreur.trop_de_cellules", n=_compte(CELLULES_MAX)))
        lignes.append(ligne)
    return lignes


def controler_classeur(fichier):
    """Refuse un classeur Excel piégé AVANT de l'ouvrir avec openpyxl (qui chargerait tout le texte en mémoire) :
    taille totale décompressée au-delà de DECOMPRESSE_MAX, entrée au taux de compression aberrant, ou texte de cellule
    plus long que la limite d'Excel (lu au fil de l'eau, par morceaux : jamais tout en mémoire). Les tailles annoncées
    par le zip bornent ce que zipfile décompresse vraiment. ``fichier`` : chemin ou fichier déposé (remis au début).
    Un fichier qui n'est pas un zip est laissé à openpyxl (message « illisible »)."""
    try:
        position = fichier.tell() if hasattr(fichier, "seek") else None
    except (OSError, ValueError):
        position = None
    try:
        try:
            z = zipfile.ZipFile(fichier)
        except (zipfile.BadZipFile, OSError, ValueError):
            return
        with z:
            entrees = z.infolist()
            if sum(i.file_size for i in entrees) > DECOMPRESSE_MAX:
                raise FichierInvalide(libelle("suivi.fichier.erreur.trop_gros_ouvert", mo=mo(DECOMPRESSE_MAX)))
            for i in entrees:
                if i.file_size >= TAUX_A_PARTIR_DE and i.file_size > TAUX_MAX * max(i.compress_size, 1):
                    raise FichierInvalide(libelle("suivi.fichier.erreur.excel_illisible"))
            for i in entrees:  # quel que soit son nom : openpyxl trouve les feuilles par les relations du classeur
                if i.file_size > SANS_BALISE_MAX and not _media(z, i):
                    _controler_textes(z, i)
    finally:
        if position is not None:
            fichier.seek(position)


# Débuts de fichier des médias connus d'un classeur (images, objets incorporés) : de longues suites d'octets sans « < »
# y sont normales. Reconnus par leur contenu et non par leur nom, qu'un classeur forgé choisit librement.
SIGNATURES_MEDIAS = (b"\x89PNG", b"\xff\xd8\xff", b"GIF8", b"BM", b"II*\x00", b"MM\x00*", b"\xd7\xcd\xc6\x9a",
                     b"\x01\x00\x00\x00", b"\xd0\xcf\x11\xe0", b"RIFF", b"PK\x03\x04", b"%PDF")


def _media(z, entree):
    """Vrai si l'entrée est un média connu (``SIGNATURES_MEDIAS``) : jamais lue comme XML par openpyxl."""
    try:
        with z.open(entree) as f:
            return f.read(8).startswith(SIGNATURES_MEDIAS)
    except (zipfile.BadZipFile, OSError, EOFError, RuntimeError, NotImplementedError):
        raise FichierInvalide(libelle("suivi.fichier.erreur.excel_illisible"))


def _controler_textes(z, entree):
    """Plus longue suite d'octets sans « < » d'une entrée XML, lue par morceaux : au-delà de SANS_BALISE_MAX, un texte
    dépasse la limite d'Excel."""
    suite = 0
    try:
        with z.open(entree) as f:
            while morceau := f.read(1024 * 1024):
                debut = morceau.find(b"<")
                if debut < 0:
                    suite += len(morceau)
                else:
                    suite += debut
                    if suite > SANS_BALISE_MAX:
                        break
                    fin = morceau.rfind(b"<")
                    plus_longue = max((len(x) for x in morceau[debut:fin].split(b"<")), default=0)
                    if plus_longue > SANS_BALISE_MAX:
                        suite = plus_longue
                        break
                    suite = len(morceau) - fin - 1
                if suite > SANS_BALISE_MAX:
                    break
    except (zipfile.BadZipFile, OSError, EOFError, RuntimeError, NotImplementedError):
        raise FichierInvalide(libelle("suivi.fichier.erreur.excel_illisible"))
    if suite > SANS_BALISE_MAX:
        raise FichierInvalide(libelle("suivi.fichier.erreur.texte_trop_long", n=_compte(TEXTE_CELLULE_MAX)))


class OngletsCSV(dict):
    """Onglet d'un CSV déposé, avec son séparateur de colonnes (« ; », « , » ou tabulation) : il dit la décimale de ses
    nombres écrits en texte (``imports.langue_des_nombres``)."""

    def __init__(self, onglets, separateur):
        super().__init__(onglets)
        self.separateur = separateur


def lire(fichier):
    """Onglets d'un fichier déposé : {nom: [lignes]}. Un CSV donne un seul onglet « CSV »."""
    nom = (getattr(fichier, "name", "") or "").lower()
    if getattr(fichier, "size", 0) and fichier.size > TAILLE_MAX:
        raise FichierInvalide(libelle("suivi.fichier.erreur.trop_gros", mo=mo(TAILLE_MAX)))
    if nom.endswith((".csv", ".txt")):
        texte_ = decoder_csv(fichier.read())
        premiere = texte_.split("\n", 1)[0]
        sep = max(";,\t", key=premiere.count)
        try:
            return OngletsCSV({"CSV": [ligne for ligne in csv.reader(io.StringIO(texte_, newline=""), delimiter=sep)]}, sep)
        except csv.Error:  # guillemets ou cellule démesurés (plus de 10 Mo) : refusé avec un message, jamais une erreur
            raise FichierInvalide(libelle("suivi.fichier.erreur.csv_illisible"))
    if nom.endswith((".xlsx", ".xlsm")):
        controler_classeur(fichier)  # classeur piégé : refusé avant d'être ouvert
        try:
            wb = load_workbook(fichier, read_only=True, data_only=True)
        except Exception:
            raise FichierInvalide(libelle("suivi.fichier.erreur.excel_illisible"))
        try:
            compte = {"gardees": 0, "lues": 0}
            return {ws.title: _onglet(ws, compte) for ws in wb.worksheets}
        except FichierInvalide:
            raise
        except Exception:  # feuille abîmée, lue seulement ici (lecture au fil de l'eau) : XML invalide, zip tronqué…
            raise FichierInvalide(libelle("suivi.fichier.erreur.excel_illisible"))
        finally:
            wb.close()
    raise FichierInvalide(libelle("suivi.fichier.erreur.formats"))


# Encodages d'un CSV : UTF-8 (avec ou sans BOM), UTF-16 et UTF-32 avec BOM (« Texte Unicode » d'Excel), sinon
# Windows-1252 (Excel français) ; Latin-1 en dernier (il lit tout octet).
BOMS = ((codecs.BOM_UTF32_LE, "utf-32"), (codecs.BOM_UTF32_BE, "utf-32"), (codecs.BOM_UTF8, "utf-8-sig"),
        (codecs.BOM_UTF16_LE, "utf-16"), (codecs.BOM_UTF16_BE, "utf-16"))
csv.field_size_limit(max(csv.field_size_limit(), TAILLE_MAX))  # une cellule peut être longue (commentaire) : bornée par la taille du fichier


def decoder_csv(brut):
    """Texte d'un CSV déposé (voir BOMS). FichierInvalide si ce n'est pas du texte (octets nuls d'un fichier binaire)."""
    for bom, encodage in BOMS:
        if brut.startswith(bom):
            try:
                return brut.decode(encodage)
            except UnicodeDecodeError:
                raise FichierInvalide(libelle("suivi.fichier.erreur.csv_illisible"))
    if brut[:4000].count(b"\x00") > len(brut[:4000]) // 4:  # UTF-16 sans BOM, ou fichier binaire
        for encodage in ("utf-16-le", "utf-16-be"):
            try:
                t = brut.decode(encodage)
            except UnicodeDecodeError:
                continue
            if "\x00" not in t and sum(c.isprintable() or c in "\r\n\t" for c in t[:2000]) > 0.95 * len(t[:2000]):
                return t
        raise FichierInvalide(libelle("suivi.fichier.erreur.csv_illisible"))
    for encodage in ("utf-8", "cp1252", "latin-1"):
        try:
            return brut.decode(encodage)
        except UnicodeDecodeError:
            continue


def texte(v):
    """Contenu d'une cellule en texte (un nombre entier lu comme 12.0 redevient « 12 »)."""
    if v is None:
        return ""
    if isinstance(v, PourcentExcel):  # comme Excel l'affiche : « 12,5 % »
        return format((Decimal(str(float(v))) * 100).normalize(), "f").replace(".", ",") + " %"
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    if isinstance(v, datetime.datetime):
        return v.strftime("%d/%m/%Y %H:%M")
    v = sans_controle(str(v)).strip()
    return v[1:] if v.startswith("'") and v[1:2] in DANGEREUX else v


def trouver_colonnes(lignes, colonnes, requises):
    """Repère la ligne d'en-têtes (dans les 15 premières) : (index de la ligne, {clé: index de colonne}).

    ``colonnes`` : {clé: [en-têtes acceptés]} ; le premier en-tête reconnu l'emporte.
    """
    acceptes = {cle: [normaliser(a) for a in alias] for cle, alias in colonnes.items()}
    for i, ligne in enumerate(lignes[:15]):
        entetes = [normaliser(h) for h in ligne]
        trouve = {}
        for cle, alias in acceptes.items():
            for a in alias:
                if a in entetes:
                    trouve[cle] = entetes.index(a)
                    break
        if all(c in trouve for c in requises):
            return i, trouve
    return None, {}


def lire_decimal_ou_none(v):
    """Nombre d'une cellule, ou None si elle est vide ou n'est pas un nombre."""
    try:
        return lire_decimal(v)
    except (ValueError, TypeError, InvalidOperation):
        return None


def lire_decimal(v):
    """Nombre d'une cellule : 1234,5 · 1 234,5 · 1,234.5 · 12 % ; None si vide. ValueError si ce n'est pas un nombre."""
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        raise ValueError
    if isinstance(v, (int, float, Decimal)):
        d = Decimal(str(v))
    else:
        t = re.sub(r"[\s  ]", "", str(v)).rstrip("%")
        if not t:
            return None
        if "," in t and "." in t:
            t = t.replace(",", "") if t.rfind(".") > t.rfind(",") else t.replace(".", "").replace(",", ".")
        else:
            t = t.replace(",", ".")
        try:
            d = Decimal(t)
        except InvalidOperation:
            raise ValueError
    if not d.is_finite():
        raise ValueError
    return d


EXPOSANT = re.compile(r"[-+]?(\d+(\.\d*)?|\.\d+)[eE][-+]?\d{1,4}", re.ASCII)  # « 1.5E-05 » d'un CSV de tableur


def lire_nombre_importe(v, langue=None):
    """Nombre d'une cellule « Valeur » d'un fichier de valeurs importé (import de valeurs, import en arrière-plan,
    assistant de reprise, commande ``import_valeurs``, rapport des lignes rejetées) : la seule lecture de ces chemins.

    - Cellule numérique (nombre d'Excel) : telle quelle, quelle que soit la langue.
    - Texte (CSV, cellule texte d'Excel) : lu comme à l'écran dans la langue du fichier, ``langue``
      (``imports.langue_des_nombres`` ; par défaut celle de ``saisie.nombres_lus_en``, sinon de l'écran) :
      ``saisie.texte_nombre``. En anglais « 1,234 » vaut 1234, ailleurs 1,234 (l'aperçu le signale) ; « 1 234,5 »,
      « 1,234.5 », « 1.234,5 » partout 1234,5 ; « 12 % » : 12.
    - Écriture scientifique d'un tableur (« 1.5E-05 », « 1e30 ») : lue, comme avant (l'écran ne l'accepte pas).
    - Ce qui n'est pas un nombre dans cette langue (« 0,205.5 », « 0,205,123 », « 12 kWh ») : ValueError, la ligne est
      rejetée avec un message, jamais lue autrement. None si vide."""
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        raise ValueError
    if isinstance(v, (int, float, Decimal)):
        d = Decimal(str(v))
    else:
        from .saisie import NOMBRE_SAISI, texte_nombre

        t = texte_nombre(str(v).strip(), langue)
        t = t[:-1] if t.endswith("%") else t
        if not t:
            return None
        if not (NOMBRE_SAISI.fullmatch(t) or EXPOSANT.fullmatch(t)) or len(t) > 60:
            raise ValueError
        d = Decimal(t)
    if not d.is_finite():
        raise ValueError
    return d


def lire_nombre_importe_ou_none(v, langue=None):
    """``lire_nombre_importe``, ou None si la cellule est vide ou n'est pas un nombre dans cette langue."""
    try:
        return lire_nombre_importe(v, langue)
    except (ValueError, TypeError, InvalidOperation):
        return None


MOTS_OUI = ("oui", "yes", "si", "vrai", "true", "1", "x", "na")  # « sí » (espagnol) s'écrit « si » une fois normalisé


@lru_cache(maxsize=8)
def _mots_oui(langues):
    """Les mots fixes, plus le « oui » écrit par l'outil dans chaque langue de l'interface (« Ja », « Sim »…) : un fichier
    exporté dans une langue se relit tel quel."""
    return frozenset(MOTS_OUI) | {normaliser(t) for t in (table_libelles(l).get("suivi.export.terme.oui") for l in langues) if t}


def oui(v):
    return normaliser(v) in _mots_oui(tuple(langues_disponibles()))


# oui / non tapé à la main (écran, import, serveur MCP : ``saisie.lire_reponse``) : mots fixes, plus le « oui » et le
# « non » de chaque langue de l'interface. « na » n'en fait pas partie (colonne N/A : ``oui``).
MOTS_OUI_SAISIE = ("oui", "yes", "o", "y", "vrai", "true", "1", "x")
MOTS_NON_SAISIE = ("non", "no", "n", "faux", "false", "0")


@lru_cache(maxsize=8)
def _mots_oui_non(langues):
    """(mots « oui », mots « non ») normalisés ; un mot présent des deux côtés (deux langues qui se contrediraient) est
    retiré des deux : ambigu, il est refusé plutôt que lu au hasard."""
    def termes(cle):
        return {normaliser(t) for t in (table_libelles(l).get(cle) for l in langues) if t}

    ouis = set(MOTS_OUI_SAISIE) | termes("suivi.export.terme.oui")
    nons = set(MOTS_NON_SAISIE) | termes("suivi.export.terme.non")
    ambigus = ouis & nons
    return frozenset(ouis - ambigus), frozenset(nons - ambigus)


def oui_non(v):
    """True (oui), False (non) ou None (ni l'un ni l'autre, ou ambigu) d'un texte tapé, dans n'importe quelle langue de
    l'interface."""
    n = normaliser(v)
    ouis, nons = _mots_oui_non(tuple(langues_disponibles()))
    return True if n in ouis else False if n in nons else None


# ---------------------------------------------------------------- écriture
def date_locale(d):
    """Excel ne connaît pas les fuseaux horaires : heure de Paris, sans fuseau."""
    if isinstance(d, datetime.datetime) and timezone.is_aware(d):
        return timezone.localtime(d).replace(tzinfo=None)
    return d


def nombre(v):
    """Decimal sans zéros inutiles (1.5000000000 → 1.5), sans notation scientifique."""
    if v is None:
        return None
    v = v.normalize()
    return v.quantize(Decimal(1)) if v == v.to_integral() else v


def couleurs_marque():
    """Aligne les couleurs des fichiers Excel sur l'identité de l'installation (Paramètres › Identité et Niveaux)."""
    from parametres.models import Instance, NiveauHierarchique

    g = {k: v.lstrip("#") for k, v in Instance.courante().gamme().items()}
    _PALETTE.set({
        "MAGENTA": g["principale"], "ROSE": g["principale-teinte"], "ROSE_PALE": g["principale-pale"],
        "VIOLET": g["accent-texte"], "VIOLET_PALE": g["accent-teinte"], "GRIS": g["fond"], "GRIS_TEXTE": g["texte-doux"],
        "NIVEAU_COULEURS": {n.code: (n.couleur_fond.lstrip("#"), n.couleur_texte.lstrip("#"))
                            for n in NiveauHierarchique.objects.all()},
    })


def classeur(ecriture_seule=False):
    """Classeur vide aux couleurs de l'installation. ``ecriture_seule`` : écrit au fil de l'eau (mode « write_only »
    d'openpyxl) : quelques dizaines de Mo de mémoire quel que soit le nombre de lignes (export de toutes les années),
    mais chaque onglet s'écrit de haut en bas avec ``ws.append`` ; largeurs, volets figés, mise en page et hauteur des
    lignes se règlent avant la première ligne (voir ``ligne_flux``, ``entetes_flux``)."""
    from .styles_excel import accelerer

    couleurs_marque()
    if ecriture_seule:
        return signer(accelerer(Workbook(write_only=True)))
    wb = accelerer(Workbook())
    wb.remove(wb.active)
    return signer(wb)


def signer(wb):
    """Auteur du classeur (propriétés du fichier) : le nom de l'outil de l'installation (Paramètres › Identité), et non
    « openpyxl ». Posé à la création (``classeur``) et de nouveau à l'enregistrement (``reponse_excel``), pour les
    classeurs créés ailleurs."""
    from parametres.models import Instance

    wb.properties.creator = wb.properties.lastModifiedBy = Instance.courante().titre or "Probant"
    return wb


def ecrire_cellule(ws, ligne, colonne, v):
    """Écrit ``v`` dans une cellule : un texte qui commence par = + - @ reste du texte (jamais une formule). Toute
    écriture d'un texte venu de l'outil (commentaire, nom, libellé) passe par ici, ou par ajouter / ecrire_tableau."""
    v = sans_controle(v)
    cell = ws.cell(ligne, colonne, v)
    if isinstance(v, str) and v.startswith(DANGEREUX):
        cell.data_type = "s"
    return cell


def ajouter(ws, valeurs):
    """Ajoute une ligne ; un texte qui commence par « = » reste du texte (jamais une formule)."""
    valeurs = [sans_controle(v) for v in valeurs]
    ws.append([date_locale(v) for v in valeurs])
    ligne = ws._current_row  # ws.max_row parcourt toutes les cellules : trop lent sur 30 000 lignes
    for col, v in enumerate(valeurs, start=1):
        if isinstance(v, str) and v.startswith(DANGEREUX):
            ws.cell(ligne, col).data_type = "s"


def cellule_flux(ws, v, number_format=None):
    """Cellule d'un onglet en écriture seule, mêmes règles que ``ajouter`` : un texte qui commence par = + - @ reste du
    texte, une date garde l'heure de Paris ; ``number_format`` : format Excel de la cellule."""
    v = sans_controle(v)
    c = WriteOnlyCell(ws, date_locale(v))
    if isinstance(v, str) and v.startswith(DANGEREUX):
        c.data_type = "s"
    if number_format:
        c.number_format = number_format
    return c


def ligne_flux(ws, valeurs, formats=None):
    """Ligne à donner à ``ws.append`` dans un onglet en écriture seule (même contenu que ``ajouter``). ``formats`` :
    {indice de colonne, à partir de 0 : format Excel}. Seules les cellules qui ont un format ou un texte à protéger
    deviennent des objets : le reste passe tel quel (mémoire)."""
    formats = formats or {}
    valeurs = [sans_controle(v) for v in valeurs]
    return [cellule_flux(ws, v, formats.get(i)) if i in formats or (isinstance(v, str) and v.startswith(DANGEREUX))
            else date_locale(v) for i, v in enumerate(valeurs)]


_TYPES_DATE = (datetime.datetime, datetime.date, datetime.time, datetime.timedelta)


class LignesRapides:
    """Lignes de données d'un onglet en écriture seule, écrites directement en XML (même texte, au caractère près, que
    ``ws.append(ligne_flux(ws, valeurs, formats))``) : openpyxl fabrique une cellule et un élément XML pour chacune des
    centaines de milliers de cases d'un gros export, ce qui en faisait l'essentiel du temps (export Power BI de toutes
    les années : 17 s sur la démo, moins de 5 s ainsi).

    Les lignes s'écrivent dans un fichier temporaire, puis se placent dans l'onglet à sa fermeture (à l'enregistrement
    du classeur), après les lignes écrites par openpyxl (en-têtes, avec leurs styles et bulles). Les styles (format de
    nombre, format de date par défaut) sont demandés à openpyxl à leur première apparition, dans le même ordre que s'il
    écrivait les cellules lui-même : les numéros de styles du fichier sont les mêmes."""

    def __init__(self, ws, premiere_ligne):
        import tempfile

        from openpyxl.cell.cell import ERROR_CODES
        from openpyxl.compat import safe_string
        from openpyxl.utils.datetime import to_excel

        self.ws, self.ligne, self.nb = ws, premiere_ligne, 0
        self._fichier = tempfile.TemporaryFile()
        self._lettres = []
        self._styles = {}
        self._textes = {}  # texte → (type, contenu XML) : noms, thèmes, statuts reviennent sur des milliers de lignes
        self._erreurs, self._nombre, self._to_excel = ERROR_CODES, safe_string, to_excel
        fermer = ws.close

        def close():  # appelé par openpyxl à l'enregistrement : l'onglet se termine, puis les lignes s'y insèrent
            fermer()
            self._inserer(ws._writer.out)
        ws.close = close

    def _lettre(self, i):
        while len(self._lettres) <= i:
            self._lettres.append(get_column_letter(len(self._lettres) + 1))
        return self._lettres[i]

    def _style(self, fmt, v):
        """Attribut ``s="…"`` d'une cellule (format ``fmt`` et valeur ``v``), comme openpyxl le calcule."""
        cle = (fmt, type(v) if isinstance(v, _TYPES_DATE) else None)
        if cle not in self._styles:
            c = WriteOnlyCell(self.ws, v)  # comme cellule_flux : une date reçoit d'abord le format de date d'openpyxl
            if fmt is not None:
                c.number_format = fmt
            self._styles[cle] = f' s="{c.style_id}"' if c.has_style else ""
        return self._styles[cle]

    def _texte(self, v):
        return sans_controle(v)[:32767]  # comme ligne_flux : caractères de contrôle retirés, puis coupé comme openpyxl

    def _xml_texte(self, v):
        """Fin de l'élément ``<c>`` d'un texte, après la référence et le style."""
        v = self._texte(v)
        if v == "":
            return ' t="inlineStr"></c>' if v not in self._erreurs else ' t="e"></c>'
        if v in self._erreurs:  # « #N/A », « #DIV/0! »… : valeur d'erreur, comme openpyxl
            return f' t="e"><v>{_echapper(v)}</v></c>'
        espace = ' xml:space="preserve"' if v != v.strip() else ""
        return f' t="inlineStr"><is><t{espace}>{_echapper(v)}</t></is></c>'

    def ecrire(self, valeurs, formats=None):
        """Une ligne : ``valeurs`` comme pour ``ligne_flux`` ; ``formats`` : {indice de colonne à partir de 0 : format}."""
        formats = formats or {}
        r = self.ligne
        morceaux = [f'<row r="{r}">']
        for i, v in enumerate(valeurs):
            fmt = formats.get(i)
            if v is None and fmt is None:
                continue
            ref = f"{self._lettre(i)}{r}"
            if isinstance(v, str):
                xml = self._textes.get(v)
                if xml is None:
                    xml = self._xml_texte(v)
                    if len(v) < 500 and len(self._textes) < 200_000:
                        self._textes[v] = xml
                s = self._style(fmt, sans_controle(v)) if fmt is not None else ""
                morceaux.append(f'<c r="{ref}"{s}{xml}')
            elif v is None:  # case vide : écrite seulement si elle a un style (format de nombre autre que « General »)
                s = self._style(fmt, v)
                if s:
                    morceaux.append(f'<c r="{ref}"{s} t="n"></c>')
            elif isinstance(v, bool):
                s = self._style(fmt, v) if fmt is not None else ""
                morceaux.append(f'<c r="{ref}"{s} t="b"><v>{self._nombre(v)}</v></c>')
            elif isinstance(v, (int, float, Decimal)):
                s = self._style(fmt, v) if fmt is not None else ""
                morceaux.append(f'<c r="{ref}"{s} t="n"><v>{self._nombre(v)}</v></c>')
            elif isinstance(v, _TYPES_DATE):
                v = date_locale(v)
                n = self._to_excel(v, self.ws.parent.epoch)
                morceaux.append(f'<c r="{ref}"{self._style(fmt, v)} t="n"><v>{self._nombre(n)}</v></c>')
            else:
                raise ValueError(f"Cannot convert {v!r} to Excel")
        morceaux.append("</row>")
        self._fichier.write("".join(morceaux).encode("ascii", "xmlcharrefreplace"))
        self.ligne += 1
        self.nb += 1

    def _inserer(self, chemin):
        """Place les lignes écrites à la fin de ``<sheetData>`` du fichier XML de l'onglet (petit : en-têtes et fin)."""
        import shutil

        with open(chemin, "rb") as f:
            xml = f.read()
        if b"</sheetData>" in xml:
            debut, _, fin = xml.partition(b"</sheetData>")
        else:
            debut, _, fin = xml.partition(b"<sheetData/>")
            debut += b"<sheetData>"
        self._fichier.seek(0)
        with open(chemin, "wb") as f:
            f.write(debut)
            shutil.copyfileobj(self._fichier, f, 1 << 20)
            f.write(b"</sheetData>")
            f.write(fin)
        self._fichier.close()


def _echapper(v):
    """Texte d'une cellule comme lxml l'écrit (« & », « < », « > » et retour chariot échappés)."""
    if "&" in v:
        v = v.replace("&", "&amp;")
    if "<" in v:
        v = v.replace("<", "&lt;")
    if ">" in v:
        v = v.replace(">", "&gt;")
    if "\r" in v:
        v = v.replace("\r", "&#13;")
    return v


def entetes_flux(ws, valeurs, roles):
    """Ligne d'en-têtes d'un onglet en écriture seule, aux couleurs de la légende (``roles`` : rôle de chaque colonne)."""
    cellules = []
    for v, role in zip(valeurs, roles):
        c = cellule_flux(ws, v)
        style_entete(c, role)
        cellules.append(c)
    return cellules


def entetes(ws, ligne=1, fond=None, couleur="FFFFFF"):
    fond = fond or palette()["MAGENTA"]  # lu à l'appel : suit l'identité de l'installation
    for cell in ws[ligne]:
        if cell.value is not None:
            cell.font = Font(bold=True, color=couleur)
            cell.fill = PatternFill("solid", fgColor=fond)
            cell.alignment = Alignment(vertical="center", wrap_text=True)
    ws.row_dimensions[ligne].height = 30


def largeurs(ws, tailles):
    for i, t in enumerate(tailles, start=1):
        ws.column_dimensions[get_column_letter(i)].width = t


def table(ws, nom, nb_colonnes, nb_lignes, debut=1, entetes=None):
    """Plage déclarée comme tableau Excel : Power BI et les tableaux croisés la reconnaissent par son nom.
    ``entetes`` : textes des en-têtes, à donner pour un onglet en écriture seule (ils ne s'y relisent pas)."""
    if nb_lignes < 1:
        return
    ref = f"A{debut}:{get_column_letter(nb_colonnes)}{debut + nb_lignes}"
    t = Table(displayName=nom, ref=ref)
    if entetes is not None:
        t._initialise_columns()
        for colonne, texte in zip(t.tableColumns, entetes):
            colonne.name = str(texte)
    t.tableStyleInfo = TableStyleInfo(name="TableStyleLight1", showRowStripes=True)
    with warnings.catch_warnings():
        if entetes is not None:  # openpyxl rappelle d'ajouter les colonnes à la main en écriture seule : c'est fait
            warnings.filterwarnings("ignore", "In write-only mode", UserWarning)
        ws.add_table(t)


def feuille_lisez_moi(wb, titre, paragraphes, index=0, nom="Lisez-moi"):
    """Onglet d'explications : titre, puis lignes de texte (un couple = libellé en gras et texte)."""
    ws = wb.create_sheet(nom, index)
    ws.sheet_view.showGridLines = False
    ecrire_cellule(ws, 1, 1, titre)
    ws["A1"].font = Font(bold=True, size=16, color=palette()["MAGENTA"])
    ligne = 3
    for p in paragraphes:
        if isinstance(p, tuple):
            ecrire_cellule(ws, ligne, 1, p[0]).font = Font(bold=True)
            ecrire_cellule(ws, ligne, 2, p[1])
            ws.cell(ligne, 2).alignment = Alignment(wrap_text=True, vertical="top")
            ws.cell(ligne, 1).alignment = Alignment(vertical="top")
        elif p.startswith("# "):
            ligne += 1
            ecrire_cellule(ws, ligne, 1, p[2:]).font = Font(bold=True, size=12, color=palette()["VIOLET"])
        else:
            ecrire_cellule(ws, ligne, 1, p).alignment = Alignment(wrap_text=False)
        ligne += 1
    largeurs(ws, [34, 100])
    return ws


def reponse_excel(wb, nom):
    signer(wb)
    flux = io.BytesIO()
    wb.save(flux)
    r = HttpResponse(flux.getvalue(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    r["Content-Disposition"] = f'attachment; filename="{nom}.xlsx"'
    r["Content-Length"] = len(r.content)  # barre de progression du téléchargement
    return r


def valeur_csv(v, style):
    """Cellule CSV : style « fr » (virgule décimale, dates jj/mm/aaaa) ou « intl » (point, dates ISO)."""
    if type(v) is str:  # le cas le plus fréquent, en premier (gros exports)
        return "'" + v if v.startswith(DANGEREUX) else v
    if v is None:
        return ""
    if isinstance(v, bool):
        return libelle("commun.oui" if v else "commun.non")
    if isinstance(v, (Decimal, int, float)):
        t = format(v, "f") if isinstance(v, Decimal) else str(v)
        return t.replace(".", ",") if style == "fr" else t
    if isinstance(v, datetime.datetime):
        v = date_locale(v)
        return v.strftime("%d/%m/%Y %H:%M") if style == "fr" else v.strftime("%Y-%m-%d %H:%M")
    if isinstance(v, datetime.date):
        return v.strftime("%d/%m/%Y") if style == "fr" else v.isoformat()
    v = str(v)
    return "'" + v if v.startswith(DANGEREUX) else v


def reponse_csv(lignes, nom, style="fr"):
    """CSV en UTF-8 avec BOM (accents lus correctement par Excel) ; « ; » en style français, « , » sinon."""
    flux = io.StringIO()
    w = csv.writer(flux, delimiter=";" if style == "fr" else ",", lineterminator="\r\n")
    for ligne in lignes:
        w.writerow([valeur_csv(v, style) for v in ligne])
    r = HttpResponse(("﻿" + flux.getvalue()).encode("utf-8"), content_type="text/csv; charset=utf-8")
    r["Content-Disposition"] = f'attachment; filename="{nom}.csv"'
    r["Content-Length"] = len(r.content)
    return r


# ================================================================= règles communes des fichiers (fichiers lisibles)
# Toutes les cellules suivent la même légende : jaune = à remplir, gris = clé à ne pas modifier, blanc = information.
# Les fichiers produits par l'outil s'appuient sur ces fonctions (fichier à remplir, rapport des rejets ; exports et
# fichiers d'administration ensuite) : même onglet « À lire » en premier, même bandeau, même légende partout.
from dataclasses import dataclass, field  # noqa: E402

from openpyxl.comments import Comment  # noqa: E402
from .styles_excel import Border, Protection, Side  # noqa: E402

JAUNE_CELLULE, JAUNE_ENTETE, JAUNE_TEXTE = "FFF5C2", "F2C94C", "4A3B00"
JAUNE_BORD = "D8C26A"  # fin cadre des cases à remplir (la grille Excel est masquée)
GRIS_CELLULE, GRIS_ENTETE, GRIS_ENTETE_TEXTE = "EDEDED", "BDBDBD", "2B2B2B"
ORANGE_ALERTE, ORANGE_TEXTE = "FCD9B6", "7A3A00"
ROLES = ("remplir", "cle", "info")


def anglais(langue):
    return (langue or "fr") != "fr"


def selon(langue, fr, en):
    """Texte du fichier dans sa langue : français, ou anglais pour toute autre langue. Gardé pour les fichiers d'administration
    (zone « admin ») ; les fichiers de la zone « suivi » passent par ``t()`` (fichiers de langue, avec l'espagnol)."""
    return en if anglais(langue) else fr


def langue_fichier(langue):
    """Langue des textes d'un fichier : celle de l'export si elle a des fichiers de langue (français, anglais, espagnol…),
    sinon l'anglais (comme avant les fichiers de langue) ; le français sans langue."""
    langue = langue or "fr"
    proposees = langues_disponibles()  # une langue incomplète n'est jamais utilisée
    return langue if langue == "fr" or langue in proposees or langue.split("-")[0] in proposees else "en"


def t(langue, cle, n=None, **valeurs):
    """Texte d'un fichier produit par l'outil, dans la langue de l'export (``libelle`` : repli sur la langue par défaut,
    puis le français)."""
    return libelle(cle, langue_fichier(langue), n=n, **valeurs)


def tous_les_textes(cle):
    """Texte d'une clé dans chaque langue disponible, sans doublon : en-têtes reconnus à la lecture d'un fichier déposé,
    quelle que soit sa langue."""
    vus = []
    for langue in langues_disponibles():
        texte = table_libelles(langue).get(cle)
        if isinstance(texte, str) and texte not in vus:
            vus.append(texte)
    return vus


@dataclass
class Colonne:
    """Colonne d'un fichier : clé interne, clé du libellé (fichiers de langue) ou texte déjà prêt, largeur, rôle (remplir,
    cle, info), format des nombres."""

    cle: str
    libelle: str = ""
    largeur: int = 14
    role: str = "info"
    format: str | None = None
    retour: bool = False  # texte long : retour à la ligne
    texte: str = ""  # en-tête qui ne se traduit pas (nom d'organisation, de niveau…)
    valeurs: dict = field(default_factory=dict)  # paramètres du libellé (ex. la comparaison de « Valeur N-1 »)

    def titre(self, langue):
        return self.texte or t(langue, self.libelle, **self.valeurs)


def format_nombre(decimales, milliers=True):
    """Format Excel d'un nombre avec ``decimales`` chiffres après la virgule (séparateur de milliers, sauf
    ``milliers=False`` : année)."""
    from .nombres import format_excel

    return format_excel(decimales, milliers)


def format_nombre_du_kpi(k):
    """Format Excel des valeurs d'un KPI : décimales de l'unité ; une année sans séparateur de milliers."""
    from .nombres import sans_milliers

    return format_nombre(k.decimales, not sans_milliers(k))


FORMAT_DATE = "DD/MM/YYYY"


def nom_fichier(*morceaux):
    """Nom de fichier explicite : morceaux sans accents ni espaces, reliés par « _ », et la date du jour à la fin.
    nom_fichier("À remplir", "Exercice 2026", "Site Lyon") → « A-remplir_Exercice-2026_Site-Lyon_2026-10-27 »."""
    propres = []
    for m in [*morceaux, f"{timezone.localdate():%Y-%m-%d}"]:
        t = unicodedata.normalize("NFKD", str(m or "")).encode("ascii", "ignore").decode()
        t = re.sub(r"[^A-Za-z0-9.]+", "-", t).strip("-")
        if t:
            propres.append(t[:40])
    return "_".join(propres)


def _fond(couleur):
    return PatternFill("solid", fgColor=couleur)


def style_entete(cell, role):
    fond, texte = {"remplir": (JAUNE_ENTETE, JAUNE_TEXTE), "cle": (GRIS_ENTETE, GRIS_ENTETE_TEXTE),
                   "info": (palette()["VIOLET"], "FFFFFF")}[role]
    cell.font = Font(bold=True, color=texte)
    cell.fill = _fond(fond)
    cell.alignment = Alignment(vertical="center", wrap_text=True)


def style_cellule(cell, colonne):
    if colonne.role == "remplir":
        cell.fill = _fond(JAUNE_CELLULE)
        cell.protection = Protection(locked=False)
    elif colonne.role == "cle":
        cell.fill = _fond(GRIS_CELLULE)
        cell.font = Font(color=GRIS_ENTETE_TEXTE, size=10)
    if colonne.format:
        cell.number_format = colonne.format
    cell.alignment = Alignment(vertical="top", wrap_text=colonne.retour)


def legende(ws, ligne, colonne=1, langue="fr", exemples=None):
    """Légende sur une ligne : « Légende : » puis des cases d'exemple, chacune dans les vraies couleurs du fichier (jamais
    un nom de couleur, qui serait faux sous une autre palette). Par défaut, les rôles des colonnes d'un fichier qui se
    réimporte (à remplir, clé, pour information) ; ``exemples`` : [(texte, fond, encre, gras, italique, motif)] pour
    les fichiers à lire. Chaque case s'étend sur assez de colonnes pour être lisible (à appeler une fois les largeurs
    posées)."""
    ws.cell(ligne, colonne, t(langue, "suivi.fichier.legende.titre")).font = Font(bold=True, size=10, color=palette()["GRIS_TEXTE"])
    if exemples is None:
        exemples = [(t(langue, "suivi.fichier.legende.remplir"), JAUNE_CELLULE, JAUNE_TEXTE, True, False, None),
                    (t(langue, "suivi.fichier.legende.cle"), GRIS_CELLULE, GRIS_ENTETE_TEXTE, False, False, None),
                    # « pour information » : la couleur de ses en-têtes de colonne
                    (t(langue, "suivi.fichier.legende.info"), palette()["VIOLET"], "FFFFFF", True, False, None)]
    col = colonne + 1
    for texte_, fond, encre, gras, italique, motif in exemples:
        debut, largeur = col, 0
        while largeur < 20:
            largeur += ws.column_dimensions[get_column_letter(col)].width or 9
            col += 1
        if col - 1 > debut:
            ws.merge_cells(start_row=ligne, start_column=debut, end_row=ligne, end_column=col - 1)
        c = ws.cell(ligne, debut, texte_)
        c.font = Font(size=10, bold=gras, italic=italique, color=encre)
        c.fill = motif or _fond(fond)
        c.border = Border(*(Side(style="thin", color="D0D0D0"),) * 4)
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[ligne].height = 30


def bandeau(ws, titre, lignes, langue="fr", nb_colonnes=8, roles=True, exemples=None):
    """En haut d'un onglet : titre, quelques lignes d'explication courtes, légende, puis une ligne vide. ``roles`` :
    légende des rôles de colonnes (seulement les fichiers qui se réimportent) ; ``exemples`` : légende propre au
    fichier (cases d'exemple). Renvoie le numéro de la ligne où écrire les en-têtes."""
    ecrire_cellule(ws, 1, 1, titre).font = Font(bold=True, size=14, color=palette()["MAGENTA"])
    n = 2
    for t in lignes:
        c = ecrire_cellule(ws, n, 1, t)
        c.font = Font(size=10, color=palette()["GRIS_TEXTE"])
        c.alignment = Alignment(wrap_text=False, vertical="top")
        n += 1
    if not roles and not exemples:
        return n + 1
    ws._ligne_legende = (n, langue, exemples)  # posée par ecrire_tableau, une fois les largeurs connues
    return n + 2


def ecrire_tableau(ws, colonnes, lignes, langue="fr", debut=1, figer=None, filtre=True):
    """En-têtes (ligne ``debut``) puis lignes de données, aux couleurs du rôle de chaque colonne ; largeurs, filtre,
    volet figé (``figer`` : clé de la première colonne qui défile, None : aucune colonne figée).
    ``lignes`` : listes de valeurs dans l'ordre des colonnes. Renvoie la dernière ligne écrite."""
    for j, c in enumerate(colonnes, start=1):
        cell = ecrire_cellule(ws, debut, j, c.titre(langue))  # titres d'organisation (tableau) : du texte
        style_entete(cell, c.role)
        ws.column_dimensions[get_column_letter(j)].width = c.largeur
    ws.row_dimensions[debut].height = 32
    n = debut
    # style de chaque colonne posé une fois (première cellule écrite), puis recopié tel quel dans les suivantes : mêmes
    # numéros de style, même fichier, sans repasser 5 fois par cellule dans les listes de styles du classeur (fichier à
    # remplir de 1,7 million de cellules). Une cellule déjà mise en forme reçoit le style complet.
    gabarits = {}
    for valeurs in lignes:
        n += 1
        for j, (c, v) in enumerate(zip(colonnes, valeurs), start=1):
            cell = ecrire_cellule(ws, n, j, date_locale(v))
            gabarit, vierge = gabarits.get(j), cell._style is None or not any(cell._style)
            if gabarit is not None and vierge:
                cell._style = StyleArray(gabarit)
            else:
                style_cellule(cell, c)
                if gabarit is None and vierge:
                    gabarits[j] = StyleArray(cell._style)
    rang = next((j for j, c in enumerate(colonnes, start=1) if c.cle == figer), 1)
    ws.freeze_panes = ws.cell(debut + 1, rang)
    if filtre:
        ws.auto_filter.ref = f"A{debut}:{get_column_letter(len(colonnes))}{max(n, debut + 1)}"
    if getattr(ws, "_ligne_legende", None):
        ligne, langue_, exemples = ws._ligne_legende
        legende(ws, ligne, 1, langue_, exemples=exemples)
        ws._ligne_legende = None
    mise_en_page(ws, debut)
    return n


def mise_en_page(ws, ligne_entete=None, paysage=True):
    """Impression lisible : paysage, une page de large, en-têtes répétés sur chaque page."""
    ws.page_setup.orientation = "landscape" if paysage else "portrait"
    ws.page_setup.paperSize = Worksheet.PAPERSIZE_A4  # constante de la classe : vaut aussi en écriture seule
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = 1, 0
    ws.page_margins.left = ws.page_margins.right = 0.4
    if ligne_entete:
        ws.print_title_rows = f"{ligne_entete}:{ligne_entete}"


def proteger(ws):
    """Protège les cellules qui ne sont pas à remplir, sans mot de passe (Révision › Ôter la protection pour lever) ;
    filtres, tri, largeurs et hauteurs restent utilisables."""
    p = ws.protection
    p.sheet = True
    p.autoFilter = p.sort = p.formatColumns = p.formatRows = p.formatCells = False
    p.selectLockedCells = p.selectUnlockedCells = False


def bulle(cell, texte, auteur="", largeur=360, hauteur=160):
    """Bulle (commentaire Excel) sur une cellule : définition d'un KPI, aide."""
    if texte:
        c = Comment(texte[:2000], auteur or "Probant")
        c.width, c.height = largeur, hauteur
        cell.comment = c


def feuille_a_lire(wb, titre, paragraphes, langue="fr", index=0, exemples=None):
    """Onglet « À lire » (« Read me ») en premier : titre, légende des couleurs, puis paragraphes (même forme que
    feuille_lisez_moi : (libellé, texte) ou « # Titre de section »). ``exemples`` : légende propre à un fichier à lire
    [(texte, fond, encre, gras, italique, motif, aide)] ; par défaut, les rôles des colonnes d'un fichier qui se
    réimporte."""
    if wb.write_only:
        return _feuille_a_lire_flux(wb, titre, paragraphes, langue, index, exemples)
    exemples = exemples or exemples_roles(langue)
    ws = feuille_lisez_moi(wb, titre, paragraphes, index=index, nom=t(langue, "suivi.fichier.a_lire"))
    ws.insert_rows(2, len(exemples) + 2)  # légende des couleurs, en colonne, sous le titre
    ws.cell(3, 1, t(langue, "suivi.fichier.couleurs")).font = Font(bold=True, size=12, color=palette()["VIOLET"])
    for i, (texte_, fond, encre, gras, italique, motif, aide) in enumerate(exemples, start=4):
        c = ws.cell(i, 1, texte_)
        c.fill = motif or _fond(fond)
        c.border = Border(*(Side(style="thin", color="D0D0D0"),) * 4)
        c.font = Font(bold=gras, italic=italique, color=encre)
        ws.cell(i, 2, aide)
    ws.sheet_properties.tabColor = palette()["MAGENTA"]
    mise_en_page(ws, paysage=False)
    return ws


def exemples_roles(langue):
    """Légende des rôles de colonnes (fichiers qui se réimportent) : cases d'exemple aux vraies couleurs, avec leur aide.
    « Pour information » : la couleur de ses en-têtes de colonne."""
    return [(t(langue, "suivi.fichier.legende.remplir"), JAUNE_CELLULE, JAUNE_TEXTE, True, False, None,
             t(langue, "suivi.fichier.legende.aide_remplir")),
            (t(langue, "suivi.fichier.legende.cle"), GRIS_CELLULE, GRIS_ENTETE_TEXTE, True, False, None,
             t(langue, "suivi.fichier.legende.aide_cle")),
            (t(langue, "suivi.fichier.legende.info"), palette()["VIOLET"], "FFFFFF", True, False, None,
             t(langue, "suivi.fichier.legende.aide_info"))]


def _feuille_a_lire_flux(wb, titre, paragraphes, langue, index, exemples=None):
    """``feuille_a_lire`` pour un classeur en écriture seule : même onglet, cellule par cellule, écrit de haut en bas."""
    ws = wb.create_sheet(t(langue, "suivi.fichier.a_lire"), index)
    ws.sheet_view.showGridLines = False
    largeurs(ws, [34, 100])
    ws.sheet_properties.tabColor = palette()["MAGENTA"]
    mise_en_page(ws, paysage=False)

    def cellule(v, **styles):
        c = cellule_flux(ws, v)
        for nom, valeur in styles.items():
            setattr(c, nom, valeur)
        return c
    ws.append([cellule(titre, font=Font(bold=True, size=16, color=palette()["MAGENTA"]))])
    ws.append([])
    ws.append([cellule(t(langue, "suivi.fichier.couleurs"), font=Font(bold=True, size=12, color=palette()["VIOLET"]))])
    for texte_, fond, encre, gras, italique, motif, aide in exemples or exemples_roles(langue):
        ws.append([cellule(texte_, fill=motif or _fond(fond), border=Border(*(Side(style="thin", color="D0D0D0"),) * 4),
                           font=Font(bold=gras, italic=italique, color=encre)),
                   cellule_flux(ws, aide)])
    ws.append([])
    for p in paragraphes:  # même disposition que feuille_lisez_moi, décalée sous la légende
        if isinstance(p, tuple):
            ws.append([cellule(p[0], font=Font(bold=True), alignment=Alignment(vertical="top")),
                       cellule(p[1], alignment=Alignment(wrap_text=True, vertical="top"))])
        elif p.startswith("# "):
            ws.append([])
            ws.append([cellule(p[2:], font=Font(bold=True, size=12, color=palette()["VIOLET"]))])
        else:
            ws.append([cellule(p, alignment=Alignment(wrap_text=False))])
    return ws


# ================================================================= fichiers d'administration (configuration, référentiel)
# Mêmes en-têtes dans le classeur de configuration et le fichier référentiel : le texte français d'origine → la clé de son
# libellé (suivi.fichier.entete.*, suivi.fichier.onglet.*), traduit dans la langue du fichier (français, anglais, espagnol ;
# l'anglais pour une autre langue). À la lecture, toutes les langues sont reconnues.
def _slug(texte_):
    texte_ = unicodedata.normalize("NFKD", texte_).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", texte_).strip("_")


ENTETES = ('ID KPI', 'Code', 'Nom', 'Nom au pluriel', 'Rang', 'Couleur', 'Symbole', 'Libellé', 'Nombre entier', 'Décimales', 'Famille', 'Ordre', 'Étiquette courte', 'Comportement', 'Format', 'Valeurs possibles', 'Colonnes (tableau)', 'Affichée au contributeur', 'Obligatoire', 'Type', 'Type de saisie', 'Type de réponse', 'Unité', 'Granularité', 'Agrégation', 'Agrégation dans le temps', 'Formule', 'Équipe responsable', 'Preuve obligatoire', 'Confidentialité', 'Actif', 'Active', 'Saisie aux niveaux supérieurs', 'Rattachée à', 'Nom court', 'Type de site', 'Organisation', 'Source', 'ID externe', 'Description', 'Partie gauche', 'Opérateur', 'Partie droite', 'Tolérance (%)', 'Niveau', 'Bloquante', 'Par défaut', 'Référentiel', 'Fréquence', "Mois de début d'exercice", 'Comparaison', 'Parent', 'Thème', 'Libellé dans le référentiel', 'Ordre dans le thème', 'Dans le référentiel', 'Identifiant', 'Version', 'Date de la version', 'Origine', 'Langue de référence', 'Exporté le', 'Exporté de', 'Information', 'Valeur', 'Définition', 'Oui / Non', 'Type de champ', 'Ouverte depuis', 'Monnaie')
ONGLETS = ('Langues', 'Niveaux', 'Unités', 'Types de saisie', 'Types de réponse', 'Catégories', 'Champs', 'Référentiels', 'Thèmes', 'KPI', 'Éléments', 'Organisations', 'Alias', 'Règles de cohérence', 'Listes', 'Référentiel', 'Exemple – KPI', 'Réglages')
CLE_ENTETE = {fr: f"suivi.fichier.entete.{_slug(fr)}" for fr in ENTETES}
CLE_ONGLET = {fr: f"suivi.fichier.onglet.{_slug(fr)}" for fr in ONGLETS}
_SUFFIXE = re.compile(r"^(?P<base>.+?)\s*(?P<suffixe>\([A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})?\))$")


def _cle_entete(texte_):
    """(clé du libellé, suffixe de langue) d'un en-tête français : « Nom (FR) » → (clé de « Nom », « (FR) »)."""
    if texte_ in CLE_ENTETE:
        return CLE_ENTETE[texte_], ""
    m = _SUFFIXE.match(texte_ or "")
    if m and m.group("base") in CLE_ENTETE:
        return CLE_ENTETE[m.group("base")], m.group("suffixe")
    return None, ""


def entete(texte_, langue="fr"):
    """En-tête d'une colonne dans la langue du fichier : « Nom (FR) » → « Name (FR) » en anglais, « Nombre (FR) » en espagnol."""
    if not texte_ or langue_fichier(langue) == "fr":
        return texte_
    cle, suffixe = _cle_entete(texte_)
    if cle is None:
        return texte_
    return f"{t(langue, cle)} {suffixe}" if suffixe else t(langue, cle)


def entetes_acceptes(texte_):
    """En-têtes reconnus à la lecture pour une colonne : le français et toutes les langues des fichiers de langue."""
    cle, suffixe = _cle_entete(texte_)
    acceptes = [texte_]
    for autre in (tous_les_textes(cle) if cle else []):
        autre = f"{autre} {suffixe}" if suffixe else autre
        if autre not in acceptes:
            acceptes.append(autre)
    return acceptes


def nom_onglet(nom, langue="fr"):
    return t(langue, CLE_ONGLET[nom]) if nom in CLE_ONGLET and langue_fichier(langue) != "fr" else nom


def onglets_en_francais(par_nom):
    """{nom normalisé: lignes} d'un classeur lu : les onglets dans une autre langue sont aussi rangés sous leur nom français."""
    for fr, cle in CLE_ONGLET.items():
        for autre in tous_les_textes(cle):
            if normaliser(autre) in par_nom and normaliser(fr) not in par_nom:
                par_nom[normaliser(fr)] = par_nom[normaliser(autre)]
    return par_nom


def onglet_donnees(wb, nom, colonnes, lignes, roles, langue="fr", figer=2, index=None):
    """Onglet de données d'un fichier d'administration : en-têtes en ligne 1 (dans la langue du fichier) aux couleurs de
    la légende, clés grises, cellules modifiables jaunes, largeurs, volet figé (``figer`` : première colonne qui défile),
    filtre, mise en page. ``colonnes`` : [(en-tête français, largeur)] ; ``roles`` : rôle de chaque colonne."""
    ws = wb.create_sheet(nom_onglet(nom, langue), index)
    ajouter(ws, [entete(e, langue) for e, _ in colonnes])
    for l in lignes:
        ajouter(ws, l)
    remplissages = {"cle": _fond(GRIS_CELLULE), "remplir": _fond(JAUNE_CELLULE)}
    gris = Font(color=GRIS_ENTETE_TEXTE, size=10)
    for j, ((_, largeur), role) in enumerate(zip(colonnes, roles), start=1):
        style_entete(ws.cell(1, j), role)
        ws.column_dimensions[get_column_letter(j)].width = largeur
        fond = remplissages.get(role)
        if fond is None:
            continue
        for i in range(2, len(lignes) + 2):
            c = ws.cell(i, j)
            c.fill = fond
            if role == "cle":
                c.font = gris
    ws.row_dimensions[1].height = 32
    ws.freeze_panes = ws.cell(2, figer)
    ws.auto_filter.ref = f"A1:{get_column_letter(max(len(colonnes), 1))}{max(len(lignes) + 1, 2)}"
    mise_en_page(ws, 1)
    return ws


def replier_colonnes(ws, debut, fin):
    """Colonnes ``debut`` à ``fin`` (numéros) regroupées et repliées : bouton « + » au-dessus pour les afficher."""
    if fin < debut:
        return
    for j in range(debut, fin + 1):
        d = ws.column_dimensions[get_column_letter(j)]
        d.outlineLevel, d.hidden = 1, True
    ws.column_dimensions[get_column_letter(fin + 1)].collapsed = True
    ws.sheet_properties.outlinePr.summaryRight = False
