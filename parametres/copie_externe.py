"""Copie externe des sauvegardes : une destination hors du serveur, réglée dans l'outil (Administration › Paramètres ›
Hébergement › Copie externe), où l'outil dépose lui-même chaque archive. Sans elle, l'IT copie le dossier des
sauvegardes par ses propres moyens, comme avant (docs/installation.md, section 5).

- Réglage : une seule destination pour toute l'installation, au registre commun (``espaces.DestinationCopie``),
  modifiable seulement par un gestionnaire des espaces (``espaces.comptes.est_gestionnaire``).
  Deux genres : stockage objet compatible S3 (``copie_s3``) ou SFTP (``copie_sftp``). Secrets (clé secrète S3, mot de
  passe ou clé privée SFTP) chiffrés avec le secret de l'installation (``chiffrement.py``), jamais renvoyés au
  navigateur ; secret illisible (autre serveur, secret changé) : « à saisir de nouveau », jamais une erreur.
- Ce qui part : chaque archive de chaque espace (``backup-….zip``) ET chaque archive du registre commun
  (``registry-….zip``) : sans le registre, la copie ne permet pas de tout reconstruire. Rangement à distance : celui du
  dossier des sauvegardes, sous « <préfixe ou dossier>/<identifiant de l'installation>/ » (``spaces/<code>/``,
  ``shared/``) : pour reconstruire, on recopie ce dossier tel quel dans ``backups/``.
- Quand : à chaque tour du planificateur des sauvegardes (``backup --schedule``, chaque minute), jamais dans une requête
  web : ce qui n'est pas encore copié part (rattrapage après une panne). État hors des bases des espaces
  (``espaces.EtatCopie``, registre commun, jamais sauvegardé). Après un échec : attente croissante avant le nouvel essai
  (``ATTENTES``), alerte (``alertes.signaler``, clé ``CLE_ALERTE``), résolue à la réussite suivante. Un seul
  passage à la fois (``en_cours_le``, signe de vie chaque minute pendant l'envoi) ; un processus arrêté en route (conteneur
  redémarré) ne bloque plus rien au bout de ``BAIL``, et le démarrage libère sa réservation (``liberer_abandonnee``).
- Suppression à distance : par défaut, rien (``conserver`` = 0, dit à l'écran) ; sinon les ``conserver`` plus récentes
  de chaque dossier sont gardées, et seuls les fichiers que l'outil a déposés (dossier et nom reconnus) sont supprimés.
- Version tout-en-un (sans ``cryptography`` ni ``paramiko``) : la fonction n'existe pas (``disponible``), l'écran le dit.
"""
import datetime
import hashlib
import logging
import math
import secrets as aleatoire
import threading
from dataclasses import dataclass
from pathlib import Path

from django.db import DatabaseError, connections, transaction
from django.utils import timezone

from espaces import contexte as ESP

from . import chiffrement as CH
from .copie_reseau import ErreurCopie

journal = logging.getLogger("reporting.copie")

CLE_ALERTE = "copie_externe"
GENRES = ("s3", "sftp")
STYLES = ("auto", "path", "virtual")
ESSAIS_MAX, ESSAIS_FENETRE = 5, datetime.timedelta(minutes=15)  # bouton « Essayer la destination », toute l'installation
DELAI_ESSAI, DELAI_COPIE = 15, 60  # secondes, par opération réseau
ATTENTES = (5, 15, 60, 180, 360)  # minutes avant un nouvel essai après 1, 2, 3, 4, 5 échecs de suite (et au-delà)
BAIL = datetime.timedelta(minutes=15)  # passage réservé sans signe de vie depuis plus longtemps : plus rien de bloqué
VIE = 60  # secondes : un passage en cours rafraîchit sa réservation (``en_cours_le``) à ce rythme, même pendant un envoi
SANS_VIE = datetime.timedelta(minutes=3)  # au démarrage : réservation sans signe de vie depuis plus longtemps, libérée
PROPOSITION = datetime.timedelta(hours=1)  # clé SFTP montrée à l'essai : à confirmer dans l'heure
RETARD = datetime.timedelta(hours=24)  # archive pas encore copiée au bout de ce délai, sans échec noté : à regarder
SECRET_MAX, CLE_PRIVEE_MAX = 512, 16384
TEMOIN = ".probant-test-"
CHAMPS = {"s3": ("adresse", "region", "compartiment", "style", "identifiant", "chemin", "conserver"),
          "sftp": ("hote", "port", "identifiant", "chemin", "conserver")}
CHAMPS_CACHES = {"identifiant"}  # au journal : « modifié », sans la valeur
EFFACES_DESTINATION_CHANGEE = "effacé (destination changée)"  # au journal, sans rien de secret


def _forme(champ, valeur):
    """Valeur d'un champ de la destination comparée sans la casse ni les espaces autour (noms d'hôte, adresse du
    service, région) ; le compartiment et l'identifiant tels quels."""
    texte = str(valeur if valeur is not None else "").strip()
    if champ in ("hote", "region"):
        return texte.lower()
    if champ == "adresse":
        return texte.rstrip("/").lower()
    return texte


DESTINATION = {"s3": ("adresse", "region", "compartiment", "identifiant"), "sftp": ("hote", "port", "identifiant")}


def destination_changee(d, genre, valeurs):
    """Les secrets enregistrés partiraient-ils ailleurs que là où ils ont été saisis ? Vrai pour un autre genre, un
    autre service S3 (adresse, région, compartiment), un autre serveur SFTP (hôte, port) ou un autre identifiant (clé
    d'accès S3, compte SFTP : un secret est celui d'un compte). Le préfixe ou le dossier, le style d'adresse et le
    nombre de copies gardées ne changent pas la destination. ``d`` : la ligne enregistrée (ou None)."""
    if d is None or not d.genre:
        return False
    if d.genre != genre:
        return True
    return any(_forme(c, getattr(d, c)) != _forme(c, valeurs.get(c)) for c in DESTINATION[genre])


def disponible():
    """La copie externe existe dans cette installation : ``cryptography`` et ``paramiko`` sont là (pas dans la version
    tout-en-un, en Python pur)."""
    try:
        import cryptography  # noqa: F401
    except ImportError:
        return False
    from .copie_sftp import disponible as sftp

    return sftp()


# ---------------------------------------------------------------- lecture
def ligne():
    """La ligne du registre commun (ou None : jamais réglée, ou registre pas encore à jour pendant une mise à jour)."""
    from espaces.models import DestinationCopie

    try:
        return DestinationCopie.objects.filter(pk=1).first()
    except DatabaseError:
        return None


def etat():
    from espaces.models import EtatCopie

    try:
        return EtatCopie.objects.filter(pk=1).first() or EtatCopie()
    except DatabaseError:
        return EtatCopie()


def _lisible(valeur, usage):
    if not valeur:
        return False
    try:
        CH.dechiffrer(valeur, usage)
    except CH.Illisible:
        return False
    return True


@dataclass(frozen=True)
class Reglage:
    """Réglage en vigueur, sans aucun secret (seulement s'il y en a un, et s'il se lit)."""

    genre: str = ""
    secret: bool = False
    secret_illisible: bool = False
    cle_privee: bool = False
    cle_privee_illisible: bool = False
    cle_serveur: str = ""
    cle_proposee: str = ""
    manques: tuple = ()

    @property
    def configure(self):
        return bool(self.genre)

    @property
    def complet(self):
        return self.configure and not self.manques

    @property
    def cle_a_confirmer(self):
        return self.genre == "sftp" and not self.cle_serveur


def reglage(d=None):
    d = d if d is not None else ligne()
    if d is None or d.genre not in GENRES:
        return Reglage()
    secret, cle = bool(d.secret_chiffre), bool(d.cle_privee_chiffree)
    secret_ko = secret and not _lisible(d.secret_chiffre, CH.SECRET_COPIE)
    cle_ko = cle and not _lisible(d.cle_privee_chiffree, CH.CLE_PRIVEE_COPIE)
    manques = []
    if d.genre == "s3":
        if not (d.adresse and d.compartiment and d.identifiant):
            manques.append("champs")
        if not secret or secret_ko:
            manques.append("secret_illisible" if secret_ko else "secret")
    else:
        if not (d.hote and d.identifiant):
            manques.append("champs")
        if not (secret or cle) or secret_ko or cle_ko:
            manques.append("secret_illisible" if (secret_ko or cle_ko) else "secret")
        if not d.cle_serveur:
            manques.append("empreinte_a_confirmer")
    return Reglage(d.genre, secret, secret_ko, cle, cle_ko, d.cle_serveur, d.cle_proposee, tuple(manques))


def empreinte_destination(d):
    """Empreinte de « où vont les copies » : une autre destination, et tout est à recopier."""
    texte = "|".join(str(x) for x in (d.genre, d.adresse.lower(), d.style, d.compartiment, d.hote.lower(), d.port, d.chemin))
    return hashlib.sha256(texte.encode("utf-8")).hexdigest()


def prefixe(chemin):
    """Préfixe S3 ou dossier SFTP normalisé : sans « / » au début (S3) ni à la fin, puis « / » s'il n'est pas vide."""
    c = (chemin or "").strip().strip("/")
    return f"{c}/" if c else ""


def base(d):
    """Dossier de cette installation à la destination : « <préfixe>/<identifiant de l'installation>/ » (S3) ; pour
    SFTP, l'identifiant sous le dossier réglé."""
    from espaces import comptes as EC

    i = EC.installation()
    ident = i.identifiant if i else "installation"
    return (prefixe(d.chemin) if d.genre == "s3" else "") + f"{ident}/"


def client(d, delai=DELAI_COPIE):
    """Client de la destination (``copie_s3.ClientS3`` ou ``copie_sftp.ClientSFTP``), à ouvrir par ``with``.
    ``ErreurCopie`` « secret_illisible » si un secret ne se lit plus."""
    def lire(valeur, usage):
        if not valeur:
            return ""
        try:
            return CH.dechiffrer(valeur, usage)
        except CH.Illisible:
            raise ErreurCopie("secret_illisible") from None

    if d.genre == "s3":
        from .copie_s3 import ClientS3

        return ClientS3(d.adresse, d.region, d.compartiment, d.style or "auto", d.identifiant, lire(d.secret_chiffre, CH.SECRET_COPIE),
                        base=base(d), delai=delai)
    if d.genre == "sftp":
        from .copie_sftp import ClientSFTP

        cle_privee = lire(d.cle_privee_chiffree, CH.CLE_PRIVEE_COPIE)
        return ClientSFTP(d.hote, d.port, d.identifiant, "" if cle_privee else lire(d.secret_chiffre, CH.SECRET_COPIE), cle_privee,
                          d.chemin or ".", d.cle_serveur, base=base(d), delai=delai)
    raise ErreurCopie("incomplet")


# ---------------------------------------------------------------- enregistrement (registre commun, relu sous verrou)
def _ligne_verrouillee():
    from espaces.models import DestinationCopie

    DestinationCopie.objects.get_or_create(pk=1)
    return DestinationCopie.objects.select_for_update().get(pk=1)


def _etat_verrouille():
    from espaces.models import EtatCopie

    EtatCopie.objects.get_or_create(pk=1)
    return EtatCopie.objects.select_for_update().get(pk=1)


def enregistrer(par, genre, valeurs, secret="", cle_privee=""):
    """Enregistre la destination ; ``secret`` ou ``cle_privee`` vides : ceux qui sont enregistrés sont gardés, tant que
    la destination ne change pas (``destination_changee``, relu sous verrou). Un autre genre : secrets et clé du
    serveur épinglée oubliés ; un autre serveur SFTP (hôte, port) : clé du serveur épinglée oubliée ; une autre
    destination du même genre sans nouveau secret : secrets effacés (``EFFACES_DESTINATION_CHANGEE``), à saisir de
    nouveau. Renvoie les changements [(champ, avant, après)] pour l'historique, sans la valeur de l'identifiant ni
    d'aucun secret."""
    if genre not in GENRES:
        raise ValueError(genre)
    maintenant = timezone.now()
    with transaction.atomic(using=ESP.COMMUN):
        d = _ligne_verrouillee()
        changements = []
        if d.genre == genre and not secret and not cle_privee and (d.secret_chiffre or d.cle_privee_chiffree) \
                and destination_changee(d, genre, valeurs):
            d.secret_chiffre, d.cle_privee_chiffree, d.secret_le = "", "", None
            changements.append(("secret", "", EFFACES_DESTINATION_CHANGEE))
        if d.genre != genre:
            changements.append(("genre", d.genre, genre))
            if d.secret_chiffre or d.cle_privee_chiffree:
                changements.append(("secret", "", "effacé"))
            d.genre, d.secret_chiffre, d.cle_privee_chiffree, d.secret_le = genre, "", "", None
            d.cle_serveur = d.cle_proposee = ""
            d.cle_serveur_le = d.cle_proposee_le = d.cle_serveur_par = None
        for champ in CHAMPS[genre]:
            avant, apres = getattr(d, champ), valeurs[champ]
            if avant != apres:
                cache = champ in CHAMPS_CACHES
                changements.append((champ, "" if cache else avant, "modifié" if cache else apres))
                setattr(d, champ, apres)
                if genre == "sftp" and champ in ("hote", "port") and (d.cle_serveur or d.cle_proposee):
                    d.cle_serveur = d.cle_proposee = ""
                    d.cle_serveur_le = d.cle_proposee_le = d.cle_serveur_par = None
                    changements.append(("cle_serveur", "", "oubliée (autre serveur)"))
        if secret:
            d.secret_chiffre, d.secret_le = CH.chiffrer(secret, CH.SECRET_COPIE), maintenant
            changements.append(("secret", "", "enregistré"))
            if genre == "sftp" and d.cle_privee_chiffree:
                d.cle_privee_chiffree = ""
                changements.append(("cle_privee", "", "effacée"))
        if cle_privee and genre == "sftp":
            d.cle_privee_chiffree, d.secret_le = CH.chiffrer(cle_privee, CH.CLE_PRIVEE_COPIE), maintenant
            changements.append(("cle_privee", "", "enregistrée"))
            if d.secret_chiffre:
                d.secret_chiffre = ""
                changements.append(("secret", "", "effacé"))
        if changements:
            d.modifie_le, d.modifie_par = maintenant, getattr(par, "pk", None)
            d.save()
    if changements:
        _relancer()
    return changements


def effacer_secrets(par):
    """Efface les secrets enregistrés (geste explicite) ; vrai s'il y en avait."""
    with transaction.atomic(using=ESP.COMMUN):
        d = _ligne_verrouillee()
        if not (d.secret_chiffre or d.cle_privee_chiffree):
            return False
        d.secret_chiffre = d.cle_privee_chiffree = ""
        d.secret_le = None
        d.modifie_le, d.modifie_par = timezone.now(), getattr(par, "pk", None)
        d.save()
    return True


def retirer(par):
    """Retire la destination (plus aucune copie ne part) ; rien n'est supprimé à distance. Vrai s'il y en avait une."""
    from espaces.models import DestinationCopie

    with transaction.atomic(using=ESP.COMMUN):
        d = _ligne_verrouillee()
        if not d.genre:
            return False
        vide = DestinationCopie(pk=1, modifie_le=timezone.now(), modifie_par=getattr(par, "pk", None))
        vide.save()
    from . import alertes

    alertes.resoudre(CLE_ALERTE)
    return True


def noter_cle_proposee(cle):
    """Clé présentée par le serveur SFTP à un essai ou à une copie, gardée pour être montrée et confirmée."""
    with transaction.atomic(using=ESP.COMMUN):
        d = _ligne_verrouillee()
        if d.genre != "sftp":
            return
        d.cle_proposee, d.cle_proposee_le = cle, timezone.now()
        d.save(update_fields=["cle_proposee", "cle_proposee_le"])


def confirmer_cle(par, empreinte_vue):
    """Épingle la clé proposée si son empreinte est celle que l'administrateur a confirmée (montrée par la page) et
    qu'elle date de moins d'une heure. Renvoie l'empreinte épinglée, ou "" (rien n'a changé)."""
    from .copie_sftp import empreinte

    maintenant = timezone.now()
    with transaction.atomic(using=ESP.COMMUN):
        d = _ligne_verrouillee()
        if d.genre != "sftp" or not d.cle_proposee or not d.cle_proposee_le or d.cle_proposee_le < maintenant - PROPOSITION:
            return ""
        vue = empreinte(d.cle_proposee)
        if not vue or vue != (empreinte_vue or "").strip():
            return ""
        d.cle_serveur, d.cle_serveur_le, d.cle_serveur_par = d.cle_proposee, maintenant, getattr(par, "pk", None)
        d.cle_proposee, d.cle_proposee_le = "", None
        d.modifie_le, d.modifie_par = maintenant, getattr(par, "pk", None)
        d.save()
    _relancer()
    return vue


def reserver_essai():
    """None si un essai est permis (il est noté), sinon le nombre de minutes à attendre (``ESSAIS_MAX`` par
    ``ESSAIS_FENETRE`` pour toute l'installation)."""
    maintenant = timezone.now()
    with transaction.atomic(using=ESP.COMMUN):
        e = _etat_verrouille()
        recents = []
        for x in e.essais if isinstance(e.essais, list) else []:
            try:
                quand = datetime.datetime.fromisoformat(x)
            except (TypeError, ValueError):
                continue
            if maintenant - ESSAIS_FENETRE < quand <= maintenant:
                recents.append(quand)
        if len(recents) >= ESSAIS_MAX:
            return max(1, math.ceil((min(recents) + ESSAIS_FENETRE - maintenant).total_seconds() / 60))
        e.essais = [d.isoformat() for d in recents] + [maintenant.isoformat()]
        e.save(update_fields=["essais"])
    return None


def _relancer():
    """Réglage changé ou essai réussi : le prochain passage n'attend pas la fin de l'attente après un échec."""
    from espaces.models import EtatCopie

    try:
        EtatCopie.objects.filter(pk=1).update(prochain_essai=None, echecs_suite=0)
    except DatabaseError:
        pass


# ---------------------------------------------------------------- archives locales
def archives_locales():
    """[(chemin relatif dans le dossier des sauvegardes, chemin)] de toutes les archives à copier : registre commun
    (``shared/``) d'abord, puis l'espace principal et chaque autre espace (``spaces/<code>/``) ; la plus récente d'abord
    dans chaque dossier."""
    from . import sauvegardes as SV

    racine = Path(ESP.dossier_sauvegardes(ESP.PRINCIPAL))
    groupes = [(racine / "shared", "shared/", SV.NOM_REGISTRE), (racine, "", SV.NOM)]
    espaces = racine / "spaces"
    try:
        if espaces.is_dir():
            groupes += [(p, f"spaces/{p.name}/", SV.NOM) for p in sorted(espaces.iterdir())
                        if p.is_dir() and ESP.CODE.match(p.name)]
    except OSError:
        pass
    sortie = []
    for dossier, rel, motif in groupes:
        try:
            noms = [p for p in dossier.iterdir() if motif.match(p.name) and p.is_file()] if dossier.is_dir() else []
        except OSError:
            continue
        for p in sorted(noms, key=lambda p: (SV.horodatage(p.name), p.name), reverse=True):
            sortie.append((rel + p.name, p))
    return sortie


def en_attente(e=None, d=None):
    """Archives locales pas encore copiées vers la destination actuelle."""
    d = d if d is not None else ligne()
    e = e if e is not None else etat()
    copiees = e.copiees if isinstance(e.copiees, dict) and d is not None and e.destination == empreinte_destination(d) else {}
    sortie = []
    for rel, chemin in archives_locales():
        try:
            taille = chemin.stat().st_size
        except OSError:
            continue
        if (copiees.get(rel) or {}).get("taille") != taille:
            sortie.append((rel, chemin))
    return sortie


def sha256_fichier(chemin):
    h = hashlib.sha256()
    with open(chemin, "rb") as f:
        for bloc in iter(lambda: f.read(1 << 20), b""):
            h.update(bloc)
    return h.hexdigest()


# ---------------------------------------------------------------- passage (planificateur)
def _reserver(maintenant, empreinte):
    with transaction.atomic(using=ESP.COMMUN):
        e = _etat_verrouille()
        if occupee(e, maintenant):
            return False
        if e.destination != empreinte:
            e.destination, e.copiees = empreinte, {}
        e.en_cours_le = maintenant
        e.save()
    return True


def _signe_de_vie():
    """Rafraîchit la réservation d'un passage en cours (jamais recréée si le passage vient de se terminer)."""
    from espaces.models import EtatCopie

    EtatCopie.objects.filter(pk=1, en_cours_le__isnull=False).update(en_cours_le=timezone.now())


class _GarderEnVie:
    """Pendant un passage : signe de vie toutes les ``VIE`` secondes, dans un fil à part (un envoi peut durer bien plus
    longtemps). Un processus arrêté en route (conteneur redémarré) n'en donne plus : ``liberer_abandonnee``."""

    def __enter__(self):
        self._fin = threading.Event()
        self._fil = threading.Thread(target=self._boucle, name="probant-copie-vie", daemon=True)
        self._fil.start()
        return self

    def _boucle(self):
        try:
            while not self._fin.wait(VIE):
                try:
                    _signe_de_vie()
                except DatabaseError:  # base occupée un instant : au prochain signe
                    pass
        finally:
            connections.close_all()  # connexions de ce fil seulement

    def __exit__(self, *exc):
        self._fin.set()
        self._fil.join()


def occupee(e=None, maintenant=None):
    """Date du dernier signe de vie d'un passage en cours (réservation encore valable), ou None."""
    e = e if e is not None else etat()
    maintenant = maintenant or timezone.now()
    if e.en_cours_le and maintenant - BAIL < e.en_cours_le <= maintenant + datetime.timedelta(minutes=5):
        return e.en_cours_le
    return None


def liberer_abandonnee(maintenant=None):
    """Au démarrage, avant les tâches de fond : libère une réservation sans signe de vie depuis plus de ``SANS_VIE``
    (son processus a été arrêté pendant un envoi). Une copie vivante, ailleurs, en donne un chaque minute : gardée.
    Renvoie la date du dernier signe de vie de la réservation libérée, ou None."""
    from espaces.models import EtatCopie

    maintenant = maintenant or timezone.now()
    try:
        e = EtatCopie.objects.filter(pk=1).first()
        if e is None or e.en_cours_le is None:
            return None
        quand = e.en_cours_le
        if maintenant - SANS_VIE <= quand <= maintenant + datetime.timedelta(minutes=5):
            return None
        n = EtatCopie.objects.filter(pk=1, en_cours_le=quand).update(en_cours_le=None)
    except DatabaseError:
        return None
    return quand if n else None


def _noter_copiee(rel, taille, sha):
    maintenant = timezone.now()
    with transaction.atomic(using=ESP.COMMUN):
        e = _etat_verrouille()
        copiees = dict(e.copiees) if isinstance(e.copiees, dict) else {}
        copiees[rel] = {"taille": taille, "sha256": sha, "le": maintenant.isoformat()}
        e.copiees, e.derniere_copie_le, e.en_cours_le = copiees, maintenant, maintenant
        e.save(update_fields=["copiees", "derniere_copie_le", "en_cours_le"])


def _terminer(erreur=None, nb=0):
    from . import alertes

    maintenant = timezone.now()
    presentes = {rel for rel, _ in archives_locales()}
    with transaction.atomic(using=ESP.COMMUN):
        e = _etat_verrouille()
        e.en_cours_le = None
        e.copiees = {k: v for k, v in (e.copiees or {}).items() if k in presentes}  # archives encore là
        if erreur is None:
            e.reussie_le, e.echecs_suite, e.prochain_essai = maintenant, 0, None
            e.echec, e.echec_resume, e.echec_le = "", "", None
        else:
            e.echecs_suite += 1
            e.prochain_essai = maintenant + datetime.timedelta(minutes=ATTENTES[min(e.echecs_suite, len(ATTENTES)) - 1])
            e.echec, e.echec_resume, e.echec_le = erreur.code[:40], erreur.resume[:200], maintenant
        e.save()
    if erreur is None:
        alertes.resoudre(CLE_ALERTE)
    else:
        attente = len(en_attente())
        alertes.signaler(CLE_ALERTE, "admin.sante.copie_externe.titre", "admin.copie.alerte.constat",
                         f"admin.copie.cause.{erreur.code}", {"n": attente, "delai": DELAI_COPIE},
                         etat="panne", detail=f"{erreur.code} {erreur.resume}".strip())
        journal.warning("External copy of the backups failed (%s %s): %s archive(s) waiting, next try in %s minutes",
                        erreur.code, erreur.resume, attente, ATTENTES[min(e.echecs_suite, len(ATTENTES)) - 1])


def passage(maintenant=None, forcer=False):
    """Un tour : copie ce qui attend, puis la rotation à distance. Renvoie le nombre d'archives déposées, ou None (rien à
    faire, pas de destination complète, attente après un échec, autre processus en cours)."""
    if not disponible():
        return None
    d = ligne()
    r = reglage(d)
    if not r.configure or r.cle_a_confirmer:
        return None
    a_copier = en_attente(d=d)
    if not a_copier:
        return None
    maintenant = maintenant or timezone.now()
    e = etat()
    if not forcer and e.prochain_essai and maintenant < e.prochain_essai:
        return None
    if not _reserver(maintenant, empreinte_destination(d)):
        return None
    nb = 0
    try:
        if not r.complet:
            raise ErreurCopie("secret_illisible" if "secret_illisible" in r.manques else "incomplet")
        with _GarderEnVie(), client(d) as c:
            for rel, chemin in a_copier:
                try:
                    taille = chemin.stat().st_size
                    sha = sha256_fichier(chemin)
                except OSError:
                    continue  # archive supprimée par la rotation locale entre-temps
                deja = c.taille(rel)
                if not (deja and deja[0] == taille and deja[1] in (None, sha)):
                    c.deposer(rel, chemin, taille, sha)
                    nb += 1
                    journal.info("External copy: %s (%.1f MB) copied", rel, taille / 1e6)
                _noter_copiee(rel, taille, sha)
            if d.conserver:
                supprimees = tourner(c, d.conserver, garder=dernieres_locales())
                if supprimees:
                    journal.info("External copy: %s old copy(ies) deleted at the destination (%s kept per folder)",
                                 len(supprimees), d.conserver)
    except ErreurCopie as erreur:
        from .copie_sftp import CleDifferente

        if isinstance(erreur, CleDifferente):
            noter_cle_proposee(erreur.cle)
        _terminer(erreur, nb)
        return nb
    except Exception as e:  # noqa: BLE001 - noté et signalé ; on réessaiera après l'attente
        journal.exception("External copy of the backups failed")
        _terminer(ErreurCopie("service", type(e).__name__), nb)
        return nb
    _terminer(None, nb)
    return nb


# ---------------------------------------------------------------- rotation à distance
def reconnue(rel):
    """Vrai pour un fichier que l'outil dépose : une archive au nom reconnu, dans un dossier reconnu (racine pour
    l'espace principal, ``spaces/<code>/``, ``shared/``). Rien d'autre n'est jamais supprimé."""
    from . import sauvegardes as SV

    morceaux = rel.split("/")
    if len(morceaux) == 1:
        return bool(SV.NOM.match(morceaux[0]))
    if len(morceaux) == 2 and morceaux[0] == "shared":
        return bool(SV.NOM_REGISTRE.match(morceaux[1]))
    if len(morceaux) == 3 and morceaux[0] == "spaces" and ESP.CODE.match(morceaux[1]):
        return bool(SV.NOM.match(morceaux[2]))
    return False


def a_supprimer(objets, conserver, garder=()):
    """Chemins à supprimer pour ne garder que les ``conserver`` plus récentes de chaque dossier (fichiers reconnus
    seulement). ``conserver`` < 1 : rien. ``garder`` : jamais supprimés (``dernieres_locales`` : la dernière archive
    faite de chaque dossier, même si une horloge remise en arrière lui a donné un nom plus ancien que les autres)."""
    from . import sauvegardes as SV

    if conserver < 1:
        return []
    groupes = {}
    for rel, _ in objets:
        if reconnue(rel):
            groupes.setdefault(rel.rsplit("/", 1)[0] if "/" in rel else "", []).append(rel)
    sortie = []
    for liste in groupes.values():
        liste.sort(key=lambda r: (SV.horodatage(r.rsplit("/", 1)[-1]), r), reverse=True)
        sortie += [r for r in liste[conserver:] if r not in garder]
    return sortie


def dernieres_locales():
    """La dernière archive faite (date du fichier) de chaque dossier des sauvegardes, en chemin relatif."""
    dernieres = {}
    for rel, chemin in archives_locales():
        try:
            quand = chemin.stat().st_mtime
        except OSError:
            continue
        dossier = rel.rsplit("/", 1)[0] if "/" in rel else ""
        if dossier not in dernieres or quand > dernieres[dossier][0]:
            dernieres[dossier] = (quand, rel)
    return {rel for _, rel in dernieres.values()}


def tourner(c, conserver, garder=()):
    supprimees = []
    for rel in a_supprimer(c.lister(), conserver, garder):
        c.supprimer(rel)
        supprimees.append(rel)
    return supprimees


# ---------------------------------------------------------------- essai (bouton)
def essayer(d=None):
    """Dépose un petit fichier témoin, le relit, le supprime, avec les réglages ENREGISTRÉS. Renvoie
    {"faits": [étapes réussies], "cause": code ou "", "resume", "cle": clé SFTP à confirmer, "avertissement"}."""
    from .copie_sftp import CleAConfirmer, CleDifferente

    d = d if d is not None else ligne()
    sortie = {"faits": [], "cause": "", "resume": "", "cle": "", "avertissement": ""}
    if d is None or d.genre not in GENRES:
        sortie["cause"] = "incomplet"
        return sortie
    rel = f"{TEMOIN}{aleatoire.token_hex(8)}.txt"
    contenu = aleatoire.token_hex(16).encode("ascii")
    etape = "connexion"
    try:
        with client(d, DELAI_ESSAI) as c:
            if d.genre == "sftp":
                sortie["faits"].append("connexion")
            import tempfile

            with tempfile.NamedTemporaryFile(prefix="probant-copy-test-") as f:
                f.write(contenu)
                f.flush()
                etape = "ecrire"
                c.deposer(rel, f.name, len(contenu), hashlib.sha256(contenu).hexdigest())
            if d.genre == "s3":
                sortie["faits"].append("connexion")
            sortie["faits"].append("ecrire")
            etape = "lire"
            if c.lire(rel, 4096) != contenu:
                raise ErreurCopie("relecture")
            sortie["faits"].append("lire")
            etape = "supprimer"
            try:
                c.supprimer(rel)
            except ErreurCopie as e:
                if e.code != "droits_supprimer" or d.conserver:
                    raise
                sortie["avertissement"] = "supprimer"
            else:
                sortie["faits"].append("supprimer")
    except CleAConfirmer as e:
        noter_cle_proposee(e.cle)
        sortie["cause"], sortie["cle"] = e.code, e.cle
        return sortie
    except CleDifferente as e:
        noter_cle_proposee(e.cle)
        from . import alertes

        alertes.signaler(CLE_ALERTE, "admin.sante.copie_externe.titre", "admin.copie.alerte.constat",
                         "admin.copie.cause.empreinte", {"n": len(en_attente(d=d)), "delai": DELAI_ESSAI},
                         etat="panne", detail="empreinte host key differs from the pinned key")
        sortie["cause"], sortie["resume"], sortie["cle"] = e.code, e.resume, e.cle
        return sortie
    except ErreurCopie as e:
        sortie["cause"], sortie["resume"] = e.code, e.resume
        return sortie
    except Exception as e:  # noqa: BLE001 - jamais une erreur 500 pour un essai
        journal.exception("Test of the external copy destination failed (%s)", etape)
        sortie["cause"], sortie["resume"] = "service", type(e).__name__
        return sortie
    _relancer()
    return sortie


# ---------------------------------------------------------------- santé
def resume_etat(maintenant=None):
    """{etat, reussie_le, attente, plus_ancienne, echec_le, echec, prochain_essai} pour la page Santé, /sante/ et l'écran.
    ``etat`` : « absente » (fonction absente de cette version), « aucune », « a_confirmer », « echec », « retard »,
    « ok »."""
    maintenant = maintenant or timezone.now()
    if not disponible():
        return {"etat": "absente"}
    d = ligne()
    r = reglage(d)
    if not r.configure:
        return {"etat": "aucune"}
    e = etat()
    attente = en_attente(e, d)
    plus_ancienne = None
    for _, chemin in attente:
        try:
            quand = datetime.datetime.fromtimestamp(chemin.stat().st_mtime, tz=datetime.timezone.utc)
        except OSError:
            continue
        plus_ancienne = quand if plus_ancienne is None or quand < plus_ancienne else plus_ancienne
    sortie = {"reussie_le": e.reussie_le, "derniere_copie_le": e.derniere_copie_le, "attente": len(attente),
              "plus_ancienne": plus_ancienne, "echec_le": e.echec_le, "echec": e.echec, "echec_resume": e.echec_resume,
              "prochain_essai": e.prochain_essai, "manques": r.manques}
    if r.cle_a_confirmer:
        sortie["etat"] = "a_confirmer"
    elif e.echec_le and (e.reussie_le is None or e.echec_le > e.reussie_le):
        sortie["etat"] = "echec"
    elif attente and plus_ancienne and plus_ancienne < maintenant - RETARD:
        sortie["etat"] = "retard"
    else:
        sortie["etat"] = "ok"
    return sortie


def pour_sante():
    """Bloc ``external_copy`` de /sante/ (en anglais, pour l'IT) : jamais une cause de 503."""
    s = resume_etat()
    noms = {"absente": "unavailable", "aucune": "off", "a_confirmer": "host key to confirm", "echec": "failing",
            "retard": "late", "ok": "ok"}
    sortie = {"state": noms[s["etat"]]}
    if s["etat"] not in ("absente", "aucune"):
        sortie["last_success"] = s["reussie_le"].isoformat() if s.get("reussie_le") else None
        sortie["pending"] = s["attente"]
        if s["etat"] == "echec":
            sortie["message"] = f"external copy of the backups failing since {s['echec_le'].isoformat()} ({s['echec']})"
        elif s["etat"] == "retard":
            sortie["message"] = "external copy of the backups late: an archive waits for more than 24 hours"
    return sortie
