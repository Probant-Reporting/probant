"""Espace courant d'une requête ou d'une commande, et garde contre les requêtes SQL vers un autre espace.

- ``alias_courant()`` : alias de base de l'espace courant (``default`` pour l'espace principal, ``espace_<code>``
  pour les autres) ; lu par le routeur (``espaces.routeur``), le stockage des fichiers et les sauvegardes.
- ``activer(code)`` : pendant le bloc, l'espace ``code`` est l'espace courant ; les liens (``reverse``, ``{% url %}``)
  prennent le préfixe ``/espace/<code>/`` ; toute requête SQL vers la base d'un autre espace lève ``FuiteEspace``.
- ``toutes_les_bases()`` : lève la garde, pour le seul code qui doit parler à plusieurs espaces (comptes communs,
  création d'un espace, boucles planifiées).
- ``atomic()`` et ``connexion()`` : ``transaction.atomic`` et ``connection`` de l'espace courant.
"""
import contextvars
import functools
import re
import threading
from contextlib import ExitStack, contextmanager
from pathlib import Path

from django.conf import settings
from django.db import connections, transaction
from django.urls import get_script_prefix, set_script_prefix

CODE = re.compile(r"^[a-z][a-z0-9]{1,19}$")
RESERVES = {"principal", "commun", "essai", "static", "media", "admin"}
PRINCIPAL = "principal"
COMMUN = "commun"

_alias = contextvars.ContextVar("espace_alias", default=None)
_racine = contextvars.ContextVar("espace_racine", default=None)  # préfixe d'origine (SCRIPT_NAME), hors espace
_tout = contextvars.ContextVar("espaces_toutes_les_bases", default=False)
_acteur = contextvars.ContextVar("espaces_acteur", default=None)  # numéro du compte connecté (requête), None : commande
_cache = contextvars.ContextVar("espace_objet", default=None)
_verrou = threading.Lock()

ANONYME = 0  # acteur d'une requête sans personne connectée


class FuiteEspace(Exception):
    """Requête SQL vers la base d'un autre espace que l'espace courant."""


# ---------------------------------------------------------------- noms
def alias_de(code):
    return "default" if code in (None, "", PRINCIPAL) else f"espace_{code}"


def code_de(alias):
    return PRINCIPAL if alias in (None, "", "default") else alias.removeprefix("espace_")


def alias_courant():
    return _alias.get() or "default"


def code_courant():
    return code_de(alias_courant())


def est_principal():
    return alias_courant() == "default"


def schema_de(conf):
    """Schéma PostgreSQL d'une configuration (option search_path), ou None."""
    m = re.search(r"search_path=([a-z0-9_]+)", (conf.get("OPTIONS") or {}).get("options", ""))
    return m.group(1) if m else None


def espace_courant():
    """Objet ``Espace`` de l'espace courant (lu dans le registre, gardé pour la durée du contexte). Sans ligne au registre
    (base de tests, registre pas encore amorcé) : un espace non enregistré du même code."""
    from .models import Espace

    code = code_courant()
    e = _cache.get()
    if e is not None and e.code == code:
        return e
    e = Espace.objects.filter(code=code).first() or Espace(code=code, nom="Espace principal" if code == PRINCIPAL else code,
                                                           etat=Espace.Etat.ACTIF)
    _cache.set(e)
    return e


# ---------------------------------------------------------------- dossiers
def dossier_espace(code):
    """Dossier des données d'un espace supplémentaire (base SQLite, fichiers déposés)."""
    if not CODE.match(code or ""):
        raise ValueError(f"Code d'espace non valide : {code!r}")
    return Path(settings.ESPACES_DOSSIER) / code


def dossier_medias(code=None):
    code = code or code_courant()
    from parametres.rangement import FICHIERS

    return Path(settings.MEDIA_ROOT) if code == PRINCIPAL else dossier_espace(code) / FICHIERS


def dossier_sauvegardes(code=None):
    code = code or code_courant()
    racine = Path(settings.SAUVEGARDES_DIR)
    if code == PRINCIPAL:
        return racine
    if not CODE.match(code):
        raise ValueError(f"Code d'espace non valide : {code!r}")
    return racine / "spaces" / code


def dossier_sauvegardes_commun():
    return Path(settings.SAUVEGARDES_DIR) / "shared"


# ---------------------------------------------------------------- alias de base
def configuration(code):
    """Configuration de base d'un espace supplémentaire, tirée de celle de l'espace principal : un fichier SQLite dans
    son dossier, ou un schéma PostgreSQL (search_path) dans la même base."""
    base = {k: v for k, v in connections.settings["default"].items() if k != "TEST"}
    if base["ENGINE"].endswith("sqlite3"):
        d = dossier_espace(code)
        d.mkdir(parents=True, exist_ok=True)
        for suffixe in ("", "-wal", "-shm", "-journal"):  # ancien nom français (avant la mise à jour)
            ancien, nouveau = d / f"base.sqlite3{suffixe}", d / f"database.sqlite3{suffixe}"
            if ancien.exists() and not nouveau.exists():
                ancien.rename(nouveau)
        return {**base, "NAME": d / "database.sqlite3"}
    options = dict(base.get("OPTIONS") or {})
    options["options"] = f"-c search_path=espace_{code}"
    return {**base, "OPTIONS": options, "CONN_MAX_AGE": settings.ESPACES_CONN_MAX_AGE}


def declarer(code):
    """Déclare dans ce processus l'alias de base de l'espace ``code`` s'il manque, et le renvoie. Les dictionnaires de
    configuration sont remplacés d'un bloc, sous verrou : un autre fil qui les parcourt n'est jamais gêné."""
    alias = alias_de(code)
    if alias in connections.settings:
        return alias
    if not CODE.match(code or ""):
        raise ValueError(f"Code d'espace non valide : {code!r}")
    with _verrou:
        if alias in connections.settings:
            return alias
        conf = connections.configure_settings({"default": {}, alias: configuration(code)})[alias]
        connections.settings = {**connections.settings, alias: conf}
        settings.DATABASES = {**settings.DATABASES, alias: conf}
    return alias


def aliases_espaces():
    """Alias déclarés dans ce processus qui sont des bases d'espace (tout sauf le registre)."""
    return [a for a in connections.settings if a != COMMUN]


# ---------------------------------------------------------------- garde
def _garde(execute, sql, params, many, context):
    if not _tout.get():
        alias = context["connection"].alias
        courant = alias_courant()
        if alias != courant and alias != COMMUN:
            raise FuiteEspace(f"Requête vers la base « {alias} » pendant l'espace « {courant} » : {str(sql)[:120]}")
    return execute(sql, params, many, context)


@contextmanager
def activer(code):
    """Rend l'espace ``code`` courant pendant le bloc (base, fichiers, préfixe des liens) et pose la garde sur les bases
    des autres espaces déclarés. Tout est remis en place à la sortie, même en cas d'erreur."""
    code = code or PRINCIPAL
    alias = declarer(code)
    racine = _racine.get()
    jetons = [(_alias, _alias.set(alias)), (_cache, _cache.set(None))]
    if racine is None:
        racine = get_script_prefix()
        jetons.append((_racine, _racine.set(racine)))
    ancien_prefixe = get_script_prefix()
    set_script_prefix(racine if code == PRINCIPAL else f"{racine.rstrip('/')}/espace/{code}/")
    try:
        with ExitStack() as pile:
            for a in aliases_espaces():
                if a != alias:
                    pile.enter_context(connections[a].execute_wrapper(_garde))
            yield alias
    finally:
        set_script_prefix(ancien_prefixe)
        for var, jeton in reversed(jetons):
            var.reset(jeton)


@contextmanager
def toutes_les_bases():
    """Lève la garde (comptes communs, création d'un espace, boucles planifiées) : à n'utiliser que là."""
    jeton = _tout.set(True)
    try:
        yield
    finally:
        _tout.reset(jeton)


@contextmanager
def acteur(numero):
    """Personne qui agit (numéro de compte) pendant une requête ; ``ANONYME`` sans personne connectée."""
    jeton = _acteur.set(numero)
    try:
        yield
    finally:
        _acteur.reset(jeton)


def acteur_courant():
    return _acteur.get()


# ---------------------------------------------------------------- base courante
def atomic(fonction=None, **kwargs):
    """``transaction.atomic`` sur la base de l'espace courant : ``with E.atomic():`` ou ``@E.atomic`` (la base est
    choisie à chaque appel, jamais à l'import)."""
    if callable(fonction):
        @functools.wraps(fonction)
        def enveloppe(*a, **k):
            with transaction.atomic(using=alias_courant(), **kwargs):
                return fonction(*a, **k)
        return enveloppe
    return transaction.atomic(using=alias_courant(), **kwargs)


def connexion():
    """Connexion à la base de l'espace courant (à la place de ``django.db.connection``)."""
    return connections[alias_courant()]


def url_espace(code, nom="collecte:accueil", *args):
    """Adresse d'une page dans l'espace ``code`` (préfixe ``/espace/<code>/`` hors espace principal)."""
    from django.urls import reverse

    racine = _racine.get() or get_script_prefix()
    ancien = get_script_prefix()
    set_script_prefix(racine if code == PRINCIPAL else f"{racine.rstrip('/')}/espace/{code}/")
    try:
        return reverse(nom, args=args or None)
    finally:
        set_script_prefix(ancien)


def codes_actifs():
    """Espaces ouverts à tous : le principal, puis les espaces actifs du registre (relus à chaque appel)."""
    from .models import Espace

    autres = Espace.objects.filter(etat=Espace.Etat.ACTIF).exclude(code=PRINCIPAL).order_by("rang", "nom")
    return [PRINCIPAL] + list(autres.values_list("code", flat=True))


def chaque_espace(codes=None):
    """Parcourt les espaces actifs (ou ``codes``), chacun activé pendant son tour : ``for code in chaque_espace(): …``.
    Avec ESPACE=<code> (commande), seulement cet espace."""
    import os

    seul = (os.environ.get("SPACE", "") or os.environ.get("ESPACE", "")).strip()
    for code in codes or ([seul] if seul else codes_actifs()):
        with activer(code):
            yield code


def codes_planifies(journal):
    """Espaces d'un tour de boucle planifiée, relus à chaque tour (un espace créé depuis est traité aussi) ; registre
    injoignable : l'espace principal seul (erreur journalisée)."""
    try:
        return codes_actifs()
    except Exception:  # noqa: BLE001
        journal.exception("Space registry unreachable")
        return [PRINCIPAL]


def pour_chaque_espace(action, journal, echec, codes=None):
    """Un tour de boucle planifiée (imports, sauvegardes, contrôle, relances) : ``action()`` dans chaque espace (``codes``,
    sinon ``codes_planifies``), activé pendant son tour. Une erreur est journalisée (``echec`` : message avec « %s »
    pour le code de l'espace) sans arrêter le tour : on réessaiera au tour suivant. Renvoie vrai si tout a réussi."""
    reussi = True
    for code in codes if codes is not None else codes_planifies(journal):
        try:
            with activer(code):
                action()
        except Exception:  # noqa: BLE001 - on réessaiera au prochain tour
            journal.exception(echec, code)
            reussi = False
    return reussi


def fichier_indisponible(code):
    return dossier_espace(code) / "INDISPONIBLE"


def marquer_indisponible(code, motif=""):
    """Démarrage : un espace en défaut est marqué indisponible (fichier dans son dossier, lu à chaque requête) ;
    ``motif`` vide : de nouveau disponible."""
    f = fichier_indisponible(code)
    if motif:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(motif, encoding="utf-8")
    elif f.exists():
        f.unlink()


def indisponible(code):
    return code != PRINCIPAL and fichier_indisponible(code).exists()
