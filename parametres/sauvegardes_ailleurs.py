"""Restaurer depuis l'outil une sauvegarde d'une autre installation (version 1.1.1).

Une archive sans signature valide de cette installation (faite par un autre serveur, par l'ordinateur de la version
tout-en-un, avant un changement de la clé secrète, ou modifiée) n'est JAMAIS vérifiable : le secret de l'installation ne
quitte pas le serveur. Son contenu est donc traité comme non fiable. Règles :

- Qui : un gestionnaire des espaces seulement (``espaces.comptes.est_gestionnaire``), sur une installation en service
  comme sur une installation encore vide (assistant de mise en place, ``installation_vide``). Une archive signée par
  cette installation garde les contrôles d'avant, pour tout le monde. La ligne de commande ne change pas.
- Où : dans l'espace courant (comme « restore --other-space ») ; le registre commun n'est jamais remplacé depuis l'écran.
- Dépôt : l'archive va dans un dossier caché du dossier des sauvegardes (``QUARANTAINE``) : jamais dans la liste des
  sauvegardes, ni dans la rotation, ni dans la copie externe, ni proposée comme « dernière archive saine ».
- Comptes (``plan`` avant, ``preparer_registre`` et ``assurer_restaurateur`` après le remplacement de la base) : les
  numéros de comptes d'une autre installation n'ont rien à voir avec ceux d'ici. Les comptes du registre qui n'ont de
  copie que dans cet espace (sauf la personne qui restaure) quittent le registre, comme à la suppression de leur dernière
  copie ; les comptes de la sauvegarde y entrent, SANS mot de passe (aucune empreinte n'est lue dans l'archive, même
  forgée). Un compte de la sauvegarde qui a le numéro ET l'e-mail d'un compte gardé (copie dans un autre espace) est ce
  compte : le registre fait foi (mot de passe, gestionnaire). Un numéro, un e-mail ou un identifiant déjà porté par un
  autre compte gardé : refusé avant tout changement (on mêlerait deux personnes). La personne qui restaure garde son
  mot de passe et son rôle de gestionnaire, et redevient administratrice active de l'espace (ligne d'historique).
- Sessions et liens avec un compte d'entreprise des comptes qui quittent le registre : supprimés (un numéro repris par
  une autre personne n'ouvre jamais la session ni le compte d'entreprise de l'ancienne).
"""
import io
import json
import os
import shutil
import sqlite3
import tempfile
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from django.db import DatabaseError, transaction
from django.utils import timezone

from espaces import contexte as ESP

from . import sauvegardes as SV
from .libelles import libelle

QUARANTAINE = ".other-installation"  # dans le dossier des sauvegardes de l'espace
MOTIF_DEPOT = "other-installation"
GARDE_QUARANTAINE = 24 * 3600  # archive déposée et pas restaurée : effacée au démarrage après un jour


# ---------------------------------------------------------------- dépôt
def dossier():
    return SV.dossier() / QUARANTAINE


def est_d_ailleurs(chemin):
    """Vrai si ``chemin`` est une archive déposée d'une autre installation (dossier caché du dossier des sauvegardes)."""
    return Path(chemin).parent.name == QUARANTAINE


def ranger(partiel):
    """Range l'archive déposée ``partiel`` (format lu, signature non valide) sous un nom unique (deux dépôts dans la même
    seconde ne s'écrasent jamais) ; les dépôts précédents sont effacés, jamais l'archive d'une restauration en cours
    (``SV.deposer`` refuse d'ailleurs tout dépôt pendant une restauration). Renvoie l'``SV.Archive``."""
    import secrets

    d = dossier()
    d.mkdir(parents=True, exist_ok=True)
    en_cours = (SV.restauration_en_cours() or {}).get("archive", "")
    for ancienne in d.iterdir():
        if ancienne.is_file() and str(ancienne.resolve()) != en_cours:
            ancienne.unlink(missing_ok=True)
    nom = f"backup-{timezone.localtime():%Y%m%d-%H%M%S}-{MOTIF_DEPOT}-{secrets.token_hex(4)}.zip"
    os.replace(partiel, d / nom)
    return SV.Archive(d / nom)


def origine(chemin, d):
    """Seule règle de l'origine d'une archive : « ici » si sa signature est valide (secret de cette installation) ET que
    l'identifiant de l'installation et l'espace sont ceux d'ici ; « autre_espace » (signée ici, même installation, autre
    espace : réservée à l'IT, « restore --other-space », comme avant) ; sinon « ailleurs », signée ou non : une installation
    qui a la même clé secrète (serveur reconstruit, « .env » recopié) signe aussi ses archives, ce qui ne prouve rien de
    leur contenu pour celle-ci. Une archive sans identifiant n'est jamais « d'ici »."""
    if not SV.signature_valide(chemin):
        return "ailleurs"
    # identifiant absent de l'archive alors qu'ici en a un : différent, donc « ailleurs »
    if str(d.get("identifiant_installation") or "") != SV.identifiant_de_l_installation():
        return "ailleurs"
    return "ici" if (d.get("espace") or ESP.PRINCIPAL) == ESP.code_courant() else "autre_espace"


def mettre_a_part(chemin):
    """Copie d'une archive d'ailleurs de la liste des sauvegardes rangée à part (``ranger``), pour la page d'une autre
    installation : jamais restaurée par l'ancien chemin. Renvoie l'``SV.Archive``."""
    partiel = SV.dossier() / f".copie-{os.getpid()}-{time.monotonic_ns()}.partiel"
    try:
        shutil.copyfile(chemin, partiel)
        return ranger(partiel)
    finally:
        partiel.unlink(missing_ok=True)


def archive(nom):
    """Archive d'une autre installation par son nom (même modèle de nom que les sauvegardes : pas de chemin arbitraire)."""
    if not SV.NOM.match(nom or "") or not (dossier() / nom).is_file():
        raise SV.ErreurSauvegarde(libelle("admin.sauvegarde.introuvable", nom=nom))
    return SV.Archive(dossier() / nom)


def nettoyer(age=GARDE_QUARANTAINE):
    """Démarrage : archives d'ailleurs déposées et pas restaurées depuis ``age`` secondes, effacées (jamais celle d'une
    restauration en cours). Renvoie le nombre d'archives effacées."""
    d = dossier()
    if not d.is_dir():
        return 0
    en_cours = (SV.restauration_en_cours() or {}).get("archive", "")
    n = 0
    for p in d.iterdir():
        try:
            if p.is_file() and str(p.resolve()) != en_cours and time.time() - p.stat().st_mtime > age:
                p.unlink()
                n += 1
        except OSError:
            continue
    return n


# ---------------------------------------------------------------- installation vide
def installation_vide():
    """Seule définition d'une installation « encore vide » : celle où l'assistant de mise en place propose de partir d'une
    sauvegarde. Espace principal seulement, un seul espace, mise en place pas terminée, un seul compte (celui que l'étape 1
    vient de créer : registre et copie), aucune organisation, aucun KPI, aucune campagne, aucune valeur. Dès qu'une de ces
    conditions tombe, la proposition disparaît ; restaurer une sauvegarde d'ailleurs reste possible pour un gestionnaire des
    espaces (Paramètres › Hébergement). Sans aucun compte (``mise_en_place.sans_compte``), l'étape 1 crée d'abord le
    compte : la proposition n'est jamais faite à un visiteur non connecté."""
    from collecte.models import Campagne, Reponse
    from espaces.models import Compte, Espace
    from referentiel.models import KPI, Organisation, Utilisateur

    from .models import Instance

    if not ESP.est_principal() or SV.base_vide():
        return False
    if Instance.courante().mise_en_place_terminee:
        return False
    with ESP.toutes_les_bases():
        if Espace.objects.exclude(code=ESP.PRINCIPAL).exists() or Compte.objects.count() != 1:
            return False
    if Utilisateur.objects.count() != 1:
        return False
    return not any(m.objects.exists() for m in (Organisation, KPI, Campagne, Reponse))


# ---------------------------------------------------------------- contenu de l'archive : une seule lecture
MAX_OBJET = 16 * 1024 * 1024  # un objet du JSON (une ligne de table) : au-delà, archive refusée (mémoire et temps bornés)
MORCEAU = 1 << 20


def _objets_json(flux, max_objet=MAX_OBJET):
    """Objets d'un tableau JSON lus un par un (fichier « database.json » de plusieurs Go : jamais tout en mémoire). Un
    objet plus long que ``max_objet`` est refusé : chaque essai de lecture porte au plus sur ``max_objet`` caractères,
    la mémoire et le temps restent bornés."""
    texte = io.TextIOWrapper(flux, encoding="utf-8")
    decodeur = json.JSONDecoder()
    tampon, pos, ouvert, fini = "", 0, False, False
    while True:
        while pos < len(tampon) and tampon[pos] in " \t\r\n,":
            pos += 1
        if pos < len(tampon):
            if not ouvert:
                if tampon[pos] != "[":
                    raise ValueError("not a JSON array")
                ouvert, pos = True, pos + 1
                continue
            if tampon[pos] == "]":
                return
            try:
                objet, fin = decodeur.raw_decode(tampon, pos)
            except json.JSONDecodeError:
                objet = None
            if objet is not None:
                if not isinstance(objet, dict):
                    raise ValueError("unexpected JSON value")
                if fin - pos > max_objet:
                    raise ValueError("JSON object too large")
                yield objet
                pos = fin
                continue
            if len(tampon) - pos > max_objet:
                raise ValueError("JSON object too large")
        if fini:
            raise ValueError("truncated JSON")
        morceau = texte.read(MORCEAU)
        fini = not morceau
        tampon, pos = tampon[pos:] + morceau, 0


@dataclass
class Contenu:
    fichier: Path  # copie assainie : ce qui sera chargé, et ce que la page de confirmation a lu
    sqlite: bool
    comptes: list  # [{pk, email (minuscules), username, actif, admin}]


def _compte(pk, email, username, actif, role):
    if not isinstance(pk, int) or isinstance(pk, bool):
        raise SV.ErreurSauvegarde(libelle("admin.sauvegarde.incomplete"))
    return {"pk": pk, "email": str(email or "").strip().lower(), "username": str(username or ""),
            "actif": bool(actif), "admin": role == "admin"}


def modeles_permis():
    """Étiquettes canoniques des modèles qu'une sauvegarde de l'outil contient (``SV.modeles_sauvegardes``) : liste
    fermée ; tout autre nom (registre commun, jetons, permissions, sessions, autre casse…) fait refuser l'archive."""
    return {m._meta.label_lower for m in SV.modeles_sauvegardes()}


def _refus_modele(nom):
    return SV.ErreurSauvegarde(libelle("admin.ailleurs.modele_refuse", modele=str(nom)[:80]))


def assainir_json(flux, cible):
    """JSON d'une archive d'ailleurs lu objet par objet et récrit dans ``cible`` (ce que ``loaddata`` chargera) : chaque
    nom de modèle résolu comme le fera ``loaddata`` et exigé sous sa forme canonique, dans la liste fermée ; clé (modèle,
    numéro) unique ; comptes sans empreinte, droits du mode expert recalculés d'après le rôle (``is_superuser`` et
    ``is_staff`` : administrateur seulement, comme l'écran Comptes), sans groupe ni permission ; groupes non repris ;
    assistant IA, assistants (MCP) et relances automatiques de l'espace éteints, imports et exports en arrière-plan en
    attente interrompus (rien ne part tout seul après la restauration). Renvoie les comptes, lus dans ce même passage."""
    from django.apps import apps

    permis, vus, comptes = modeles_permis(), set(), []
    with open(cible, "w", encoding="utf-8") as sortie:
        sortie.write("[")
        premier = True
        for o in _objets_json(flux):
            nom, pk, champs = o.get("model"), o.get("pk"), o.get("fields")
            try:
                modele = apps.get_model(nom) if isinstance(nom, str) else None
            except (LookupError, ValueError):
                modele = None
            if modele is None or nom != modele._meta.label_lower or nom not in permis:
                raise _refus_modele(nom)
            if not isinstance(champs, dict) or pk is None or isinstance(pk, (dict, list, bool)):
                raise SV.ErreurSauvegarde(libelle("admin.sauvegarde.incomplete"))
            cle = (nom, json.dumps(pk))
            if cle in vus:
                raise _refus_modele(f"{nom} {pk}")
            vus.add(cle)
            if nom == "auth.group":
                continue
            if nom == "referentiel.utilisateur":
                admin = champs.get("role") == "admin"
                champs.update(password=SV.MOT_DE_PASSE_RETIRE, is_superuser=admin, is_staff=admin, groups=[],
                              user_permissions=[])
                comptes.append(_compte(pk, champs.get("email"), champs.get("username"), champs.get("is_active"),
                                       champs.get("role")))
            elif nom == "parametres.instance":
                champs.update(ia_active=False, ia_kpi_sensibles=False, relance_auto=False)
            elif nom in ("collecte.tacheimport", "collecte.tacheexport") and champs.get("statut") in ("attente", "en_cours"):
                champs["statut"] = "interrompue"
            elif nom == "serveur_mcp.reglagemcp":
                champs.update(actif=False, ecriture=False)
            sortie.write(("" if premier else ", ") + json.dumps({"model": nom, "pk": pk, "fields": champs},
                                                                 ensure_ascii=False))
            premier = False
        sortie.write("]")
    return comptes


def preparer(z, noms, d, tmp):
    """Une seule lecture de la base d'une archive d'ailleurs, pour la page de confirmation comme pour la restauration :
    contrôles (SQLite : base de l'outil, objets interdits, schéma), copie assainie dans ``tmp`` et ses comptes, lus
    dans la copie assainie, c'est-à-dire exactement ce qui sera chargé."""
    from referentiel.models import Utilisateur

    try:
        if SV.nom_dans(noms, SV.BASE_SQLITE):
            nom = SV.nom_dans(noms, SV.BASE_SQLITE)
            z.extract(nom, tmp)
            f = Path(tmp) / nom
            SV.controler_base_sqlite(f, d)
            SV.assainir_copie(f)
            c = sqlite3.connect(f"file:{f}?mode=ro", uri=True)
            try:
                lignes = c.execute(f'SELECT id, email, username, is_active, role FROM "{Utilisateur._meta.db_table}"').fetchall()
            finally:
                c.close()
            return Contenu(f, True, [_compte(*ligne) for ligne in lignes])
        cible = Path(tmp) / "database-checked.json"
        with z.open(SV.nom_dans(noms, SV.BASE_JSON)) as flux:
            comptes = assainir_json(flux, cible)
        return Contenu(cible, False, comptes)
    except (zipfile.BadZipFile, KeyError, OSError, ValueError, RecursionError, sqlite3.Error) as e:  # JSON imbriqué sans fin compris
        raise SV.ErreurSauvegarde(libelle("admin.sauvegarde.pas_une_sauvegarde", erreur=str(e)[:200])) from e


# ---------------------------------------------------------------- plan des comptes
@dataclass
class Plan:
    comptes: int = 0  # comptes dans la sauvegarde
    gardes: int = 0  # même numéro et même e-mail qu'un compte d'un autre espace : gardent leur mot de passe
    sans_mot_de_passe: int = 0  # comptes actifs sans mot de passe après la restauration (hors la personne qui restaure)
    remplaces: int = 0  # comptes qui n'avaient de copie que dans cet espace (hors la personne) : quittent le registre
    gestionnaires_perdus: int = 0  # parmi eux, gestionnaires des espaces
    restaurateur: str = ""  # « admin » (déjà administrateur actif), « remis_admin », « ajoute »
    admins: list = field(default_factory=list)  # e-mails des administrateurs actifs de la sauvegarde
    conflits: list = field(default_factory=list)  # e-mails des comptes qui mêleraient deux personnes


def _numeros_hors_de(code):
    """Numéros des comptes qui ont une copie dans un AUTRE espace que ``code`` : espaces ouverts (copies lues), espaces
    archivés, en création ou indisponibles (index des accès). Un espace ouvert illisible : son index fait foi."""
    from espaces import comptes as EC
    from espaces.models import AccesEspace
    from referentiel.models import Utilisateur

    hors = set()
    ouverts = EC.codes_ouverts()
    for autre in ouverts:
        if autre == code:
            continue
        try:
            hors |= set(Utilisateur.objects.using(ESP.declarer(autre)).values_list("pk", flat=True))
        except DatabaseError:
            hors |= set(AccesEspace.objects.filter(espace__code=autre).values_list("compte_id", flat=True))
    hors |= set(AccesEspace.objects.exclude(espace__code__in=ouverts).exclude(espace__code=code)
                .values_list("compte_id", flat=True))
    return hors


def plan(comptes_archive, restaurateur, code=None):
    """Ce que la restauration fera des comptes (lu sans rien changer ; refait sous verrou au moment d'écrire).
    ``restaurateur`` : {pk, email} de la personne connectée qui restaure."""
    from espaces.models import Compte

    code = code or ESP.code_courant()
    with ESP.toutes_les_bases():
        hors = _numeros_hors_de(code)
        registre = {c.pk: c for c in Compte.objects.all()}
    r_email = (restaurateur.get("email") or "").lower()
    r = registre.get(restaurateur.get("pk")) or next((c for c in registre.values() if c.email.lower() == r_email), None)
    p = Plan(comptes=len(comptes_archive))
    gardes = {pk: c for pk, c in registre.items() if pk in hors}
    par_email = {c.email.lower(): c for c in gardes.values()}
    par_ident = {c.username: c for c in gardes.values()}
    r_garde = r is not None and r.pk in hors
    emails, idents = {}, {}
    present = None
    for u in comptes_archive:
        emails[u["email"]] = emails.get(u["email"], 0) + 1
        idents[u["username"]] = idents.get(u["username"], 0) + 1
    for u in comptes_archive:
        est_r = r is not None and u["email"] == r_email
        conflit = emails[u["email"]] > 1 or idents[u["username"]] > 1  # deux comptes de la sauvegarde pour un
        if u["pk"] in gardes:
            conflit = conflit or gardes[u["pk"]].email.lower() != u["email"]
        elif u["email"] in par_email or u["username"] in par_ident:
            conflit = True
        elif r is not None and not r_garde and not est_r and u["username"] == r.username:
            conflit = True  # l'identifiant de la personne qui restaure, porté par une autre personne
        if conflit:
            p.conflits.append(u["email"] or u["username"])
            continue
        if u["actif"] and u["admin"]:
            p.admins.append(u["email"])
        if est_r:
            present = u
        elif u["pk"] in gardes:
            p.gardes += 1
        elif u["actif"]:
            p.sans_mot_de_passe += 1
    liberes = [c for pk, c in registre.items() if pk not in hors and (r is None or pk != r.pk)]
    p.remplaces = len(liberes)
    p.gestionnaires_perdus = sum(1 for c in liberes if c.gestionnaire)
    p.restaurateur = "ajoute" if present is None else "admin" if present["actif"] and present["admin"] else "remis_admin"
    p.admins.sort()
    return p


def texte_conflits(p):
    exemples = ", ".join(sorted(set(p.conflits))[:5])
    return libelle("admin.ailleurs.conflits", n=len(p.conflits), exemples=exemples)


def controler_plan(comptes, restaurateur):
    """Refuse (avant tout changement) une archive dont un compte mêlerait deux personnes ; renvoie le plan sinon."""
    p = plan(comptes, restaurateur)
    if p.conflits:
        raise SV.ErreurSauvegarde(texte_conflits(p))
    return p


def apercu(chemin, d, restaurateur):
    """Pour la page de confirmation : (plan ou None, refus en clair ou ""). Même lecture que la restauration
    (``preparer``) : la page annonce ce qui sera chargé."""
    try:
        SV.controler_compatibilite(chemin, d)
        with tempfile.TemporaryDirectory(prefix=SV.TEMPORAIRE) as tmp, zipfile.ZipFile(chemin) as z:
            p = plan(preparer(z, set(z.namelist()), d, tmp).comptes, restaurateur)
    except SV.ErreurSauvegarde as e:
        return None, str(e)
    except (zipfile.BadZipFile, OSError) as e:
        return None, libelle("admin.sauvegarde.pas_une_sauvegarde", erreur=str(e)[:200])
    return p, texte_conflits(p) if p.conflits else ""


def empreinte(chemin):
    """SHA-256 du fichier : la confirmation porte sur ce fichier-là, revérifiée juste avant l'extraction."""
    import hashlib

    h = hashlib.sha256()
    with open(chemin, "rb") as f:
        for bloc in iter(lambda: f.read(1 << 20), b""):
            h.update(bloc)
    return h.hexdigest()


# ---------------------------------------------------------------- après le remplacement de la base
def _supprimer_sessions(numeros):
    """Sessions (registre commun) des comptes ``numeros`` supprimées."""
    from django.contrib.sessions.models import Session

    numeros = {str(n) for n in numeros}
    if not numeros:
        return 0
    n = 0
    for s in Session.objects.all().iterator():
        try:
            uid = str(s.get_decoded().get("_auth_user_id", ""))
        except Exception:  # noqa: BLE001 - session illisible (secret changé) : elle ne sert déjà plus
            continue
        if uid in numeros:
            s.delete()
            n += 1
    return n


def _liens_entreprise():
    from django.apps import apps
    from django.db import connections

    try:
        m = apps.get_model("connexion_entreprise", "LienEntreprise")
    except LookupError:
        return None
    return m if m._meta.db_table in connections[ESP.COMMUN].introspection.table_names() else None


def preparer_registre(restaurateur):
    """Après le remplacement de la base de l'espace, avant ``reconcilier`` : sous verrou du registre, les comptes qui
    n'avaient de copie que dans cet espace (sauf la personne qui restaure) quittent le registre, avec leurs accès, leurs
    liens avec un compte d'entreprise et leurs sessions ; la personne qui restaure prend, si besoin, le numéro de son
    compte dans la sauvegarde (même e-mail), ou un numéro libre si le sien y est porté par une autre personne. Renvoie
    {pk, email} de la personne qui restaure. Rejoué sans dommage (reprise d'une restauration interrompue)."""
    from espaces.models import AccesEspace, Compte
    from referentiel.models import Utilisateur

    code = ESP.code_courant()
    copies = list(Utilisateur.objects.using(ESP.alias_courant()).values_list("pk", "email"))
    numeros_copies = {pk for pk, _ in copies}
    r_email = (restaurateur.get("email") or "").lower()
    with ESP.toutes_les_bases():
        hors = _numeros_hors_de(code)
        liens = _liens_entreprise()
        with transaction.atomic(using=ESP.COMMUN):
            comptes = {c.pk: c for c in Compte.objects.select_for_update()}  # relu sous verrou
            r = next((c for c in comptes.values() if c.email.lower() == r_email), None)
            if r is None:
                raise SV.ErreurSauvegarde(libelle("admin.ailleurs.restaurateur_absent"))
            liberes = [pk for pk in comptes if pk not in hors and pk != r.pk]
            Compte.objects.filter(pk__in=liberes).delete()
            AccesEspace.objects.filter(compte_id__in=liberes).delete()
            if liens is not None:
                liens.objects.filter(compte_id__in=liberes).delete()
            ancien = r.pk
            if r.pk not in hors:  # copie dans cet espace seulement : son numéro suit la sauvegarde
                meme = sorted(pk for pk, e in copies if (e or "").lower() == r_email)
                nouveau = meme[0] if meme else r.pk
                if not meme and r.pk in numeros_copies:
                    nouveau = max([*comptes, *numeros_copies, *hors, 0]) + 1
                if nouveau != r.pk:
                    if Compte.objects.filter(pk=nouveau).exists():
                        raise SV.ErreurSauvegarde(libelle("admin.ailleurs.restaurateur_absent"))
                    Compte.objects.filter(pk=r.pk).update(id=nouveau)
                    AccesEspace.objects.filter(compte_id=r.pk).update(compte_id=nouveau)
                    if liens is not None:
                        liens.objects.filter(compte_id=r.pk).update(compte_id=nouveau)
                    r.pk = nouveau
        _supprimer_sessions(set(liberes) | {ancien})
    SV.journal.info("Restore from another installation: %s account(s) that existed only in this space left the shared "
                    "registry; the account of the person who restored is no. %s", len(liberes), r.pk)
    return {"pk": r.pk, "email": r.email}


def assurer_restaurateur(info):
    """Après ``reconcilier`` : la personne qui restaure est administratrice active de l'espace (copie créée si la
    sauvegarde ne l'a pas, rôle rendu sinon), avec son mot de passe (celui du registre) et une ligne d'historique ; son
    rôle de gestionnaire des espaces, lu avant, est réaffirmé à la fin (aucune règle du registre ne le lui retire en
    route : l'installation garde toujours un gestionnaire actif, administrateur actif). Renvoie « admin »,
    « remis_admin » ou « ajoute »."""
    from collecte.models import Journal
    from espaces.models import Compte
    from referentiel.models import Utilisateur

    with ESP.toutes_les_bases():
        c = Compte.objects.get(pk=info["pk"])
        Compte.objects.filter(pk=c.pk).update(actif=True)
    u = Utilisateur.objects.filter(pk=c.pk).first()
    if u is None:
        u = Utilisateur(pk=c.pk, role=Utilisateur.Role.ADMIN, is_staff=True, is_superuser=True, is_active=True,
                        **{f: getattr(c, f) for f in ("username", "email", "password", "first_name", "last_name",
                                                       "doit_changer_mdp")})
        u.save(force_insert=True)
        Journal.ecrire(u, "creation_compte", u, "rôle", "", "administrateur (restauration d'une autre installation)")
        etat = "ajoute"
    elif u.is_active and u.role == Utilisateur.Role.ADMIN and u.is_superuser and u.is_staff:
        etat = "admin"
    else:
        avant = u.get_role_display() + ("" if u.is_active else " (désactivé)")
        u.role, u.is_active, u.is_staff, u.is_superuser = Utilisateur.Role.ADMIN, True, True, True
        u.save(update_fields=["role", "is_active", "is_staff", "is_superuser"])
        Journal.ecrire(u, "reglage_compte", u, "rôle", avant, "administrateur (restauration d'une autre installation)")
        etat = "remis_admin"
    if c.gestionnaire:
        with ESP.toutes_les_bases():
            Compte.objects.filter(pk=c.pk).update(gestionnaire=True, actif=True)
    return etat
