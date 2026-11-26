"""Autorités de certification ajoutées par l'IT (réseau d'entreprise) : un seul mécanisme pour TOUS les appels sortants
de Python, sans qu'aucun module ait à le savoir.

L'IT donne un ou plusieurs fichiers PEM (``EXTRA_CA_CERTS`` : fichiers ou dossiers, séparés par « : » ; dans l'image
Docker, le dossier ``certificates/ca`` de l'installation, monté en ``/etc/probant/ca``). Au démarrage, ils sont réunis
avec les autorités du système dans un seul fichier (``<dossier des données>/ca-bundle.pem``, jamais sauvegardé), donné à
OpenSSL par ``SSL_CERT_FILE`` (et à ``requests`` par ``REQUESTS_CA_BUNDLE``). Tout contexte TLS fait par
``ssl.create_default_context()`` (moteur SMTP de Django, ``urllib``, ``http.client``, prise IA, ``httpx``…) lit ce fichier ;
les autorités publiques restent de confiance (elles sont dans le fichier, en tête).

- ``docker/entrypoint.sh`` lance ``python -m config.autorites_certificats`` une fois : messages au journal du démarrage,
  chemin du fichier sur la sortie standard, exporté pour tous les processus de l'outil (``PROBANT_CA_BUNDLE`` le marque).
- Hors Docker (hébergement géré, ``runserver``) : ``config/settings.py`` appelle ``appliquer`` ; il ne refait rien quand
  le processus parent l'a déjà fait.

Un fichier illisible, sans certificat, ou dont un certificat n'est pas celui d'une AUTORITÉ (certificat de serveur) est
écarté avec un message clair ; l'outil démarre quand même. Aucune dépendance (ni Django ni ``cryptography``) : un
certificat est une autorité quand OpenSSL le dit (``SSLContext.get_ca_certs``, contraintes de base « CA »)."""
import datetime
import os
import re
import ssl
import sys
from dataclasses import dataclass, field
from pathlib import Path

VARIABLE = "EXTRA_CA_CERTS"
MARQUE = "PROBANT_CA_BUNDLE"  # chemin du fichier réuni, posé avec SSL_CERT_FILE par le processus qui l'a écrit
FICHIER = "ca-bundle.pem"
VARIABLES_DONNEES = ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE")
EXTENSIONS = (".pem", ".crt", ".cer")
ALERTE_JOURS = 30
BLOC = re.compile(rb"-----BEGIN CERTIFICATE-----\s.*?-----END CERTIFICATE-----", re.S)
# raisons d'un fichier écarté (libellés : admin.sante.autorites.raison.<code>)
ILLISIBLE, INTROUVABLE, PAS_CERTIFICAT, PAS_AUTORITE = "illisible", "introuvable", "pas_certificat", "pas_autorite"
MESSAGES = {
    ILLISIBLE: "cannot be read by the tool (rights of the file?)",
    INTROUVABLE: "not found",
    PAS_CERTIFICAT: "holds no certificate in PEM format (-----BEGIN CERTIFICATE-----)",
    PAS_AUTORITE: "holds a certificate that is not a certificate authority (a server certificate?)",
}


@dataclass(frozen=True)
class Autorite:
    fichier: str
    sujet: str
    expire: datetime.datetime  # UTC

    def jours_restants(self, maintenant=None):
        maintenant = maintenant or datetime.datetime.now(datetime.timezone.utc)
        return (self.expire - maintenant).total_seconds() / 86400

    def a_regarder(self, maintenant=None):
        return self.jours_restants(maintenant) < ALERTE_JOURS


@dataclass
class Bilan:
    """Ce que donnent les fichiers de ``EXTRA_CA_CERTS`` : autorités retenues, fichiers écartés [(fichier, raison)]."""

    autorites: list = field(default_factory=list)
    ecartes: list = field(default_factory=list)
    blocs: list = field(default_factory=list)  # textes PEM retenus, dans l'ordre

    @property
    def demande(self):
        return bool(self.autorites or self.ecartes)


def chemins(valeur):
    """Fichiers nommés par ``valeur`` : chaque élément (séparé par « : », « ; » sous Windows) est un fichier, ou un dossier
    dont on prend les fichiers .pem, .crt et .cer (triés). [(chemin, existe)]."""
    sortie = []
    for morceau in (valeur or "").split(os.pathsep):
        morceau = morceau.strip()
        if not morceau:
            continue
        p = Path(morceau)
        if p.is_dir():
            try:
                sortie += [(f, True) for f in sorted(p.iterdir()) if f.suffix.lower() in EXTENSIONS and f.is_file()]
            except OSError:
                sortie.append((p, True))  # dossier illisible : dit comme un fichier illisible
        else:
            sortie.append((p, p.exists()))
    return sortie


def _sujet(info):
    noms = {k: v for rdn in info.get("subject", ()) for k, v in rdn}
    return noms.get("commonName") or noms.get("organizationalUnitName") or noms.get("organizationName") or "?"


def _lire_bloc(pem):
    """Infos OpenSSL d'un certificat PEM s'il est celui d'une autorité ; None sinon (lève ValueError s'il est abîmé)."""
    try:
        der = ssl.PEM_cert_to_DER_cert(pem.decode("ascii"))
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.load_verify_locations(cadata=der)
    except (ssl.SSLError, ValueError, UnicodeDecodeError) as e:
        raise ValueError(str(e)) from e
    autorites = ctx.get_ca_certs()  # seuls les certificats d'autorité (X509_check_ca)
    return autorites[0] if autorites else None


def lire(valeur):
    """``Bilan`` des fichiers de ``valeur`` (``EXTRA_CA_CERTS``). Un fichier dont un certificat n'est pas une autorité est
    écarté en entier : il n'a pas été préparé pour cet usage."""
    bilan = Bilan()
    for chemin, existe in chemins(valeur):
        nom = str(chemin)
        if not existe:
            bilan.ecartes.append((nom, INTROUVABLE))
            continue
        try:
            contenu = chemin.read_bytes()
        except OSError:
            bilan.ecartes.append((nom, ILLISIBLE))
            continue
        blocs = BLOC.findall(contenu)
        if not blocs:
            bilan.ecartes.append((nom, PAS_CERTIFICAT))
            continue
        retenues = []
        try:
            infos = [_lire_bloc(b) for b in blocs]
        except ValueError:
            bilan.ecartes.append((nom, PAS_CERTIFICAT))
            continue
        if any(i is None for i in infos):
            bilan.ecartes.append((nom, PAS_AUTORITE))
            continue
        for b, i in zip(blocs, infos):
            expire = datetime.datetime.fromtimestamp(ssl.cert_time_to_seconds(i["notAfter"]), datetime.timezone.utc)
            retenues.append(Autorite(nom, _sujet(i), expire))
            bilan.blocs.append(b.decode("ascii"))
        bilan.autorites += retenues
    return bilan


def base_systeme(environ):
    """Fichier des autorités du système : celui que l'IT a déjà donné par ``SSL_CERT_FILE`` (sauf le nôtre), sinon celui
    d'OpenSSL, sinon celui de ``certifi`` s'il est installé. None : aucun (le dossier du système reste lu par OpenSSL)."""
    deja = environ.get("SSL_CERT_FILE", "")
    if deja and deja != environ.get(MARQUE) and os.path.isfile(deja):
        return Path(deja)
    chemins_ = ssl.get_default_verify_paths()
    for c in (chemins_.openssl_cafile, "/etc/ssl/certs/ca-certificates.crt", "/etc/pki/tls/certs/ca-bundle.crt"):
        if c and os.path.isfile(c):
            return Path(c)
    try:
        import certifi
    except ImportError:
        return None
    return Path(certifi.where())


def contenu_reuni(bilan, environ):
    base = base_systeme(environ)
    texte = ""
    if base is not None:
        try:
            texte = base.read_text(encoding="ascii", errors="replace")
        except OSError:
            texte = ""
    texte = texte.rstrip("\n") + "\n" if texte else ""
    ajouts = "".join(f"# added by Probant ({VARIABLE}): {a.sujet} ({a.fichier})\n{b}\n"
                     for a, b in zip(bilan.autorites, bilan.blocs))
    return texte + ajouts


def ecrire(chemin, texte):
    """Écrit ``chemin`` d'un coup (fichier à part puis renommé), seulement si le contenu change."""
    try:
        if chemin.read_text(encoding="ascii", errors="replace") == texte:
            return
    except OSError:
        pass
    tmp = chemin.with_name(f".{chemin.name}.{os.getpid()}.tmp")
    tmp.write_text(texte, encoding="ascii", errors="replace")
    os.replace(tmp, chemin)


def messages(bilan, maintenant=None):
    """Messages du démarrage, en anglais (journal du serveur)."""
    sortie = [f"Certificate authority file {f} {MESSAGES[r]}: ignored ({VARIABLE}, docs/installation.md, "
              "\"Company network\")." for f, r in bilan.ecartes]
    for a in bilan.autorites:
        jours = a.jours_restants(maintenant)
        if jours < 0:
            sortie.append(f"The added certificate authority \"{a.sujet}\" ({a.fichier}) expired on "
                          f"{a.expire:%Y-%m-%d}: replace it.")
        elif jours < ALERTE_JOURS:
            sortie.append(f"The added certificate authority \"{a.sujet}\" ({a.fichier}) expires on "
                          f"{a.expire:%Y-%m-%d}: replace it soon.")
    return sortie


def preparer(environ, dossier, sortie=sys.stderr):
    """Réunit les autorités : écrit le fichier, pose ``SSL_CERT_FILE``, ``REQUESTS_CA_BUNDLE`` et la marque dans
    ``environ``. Renvoie le chemin du fichier réuni, ou None (rien de demandé, ou aucune autorité valable). Ne lève
    jamais : l'outil démarre quand même."""
    bilan = lire(environ.get(VARIABLE, ""))
    for m in messages(bilan):
        print(m, file=sortie)
    if not bilan.autorites:
        if bilan.ecartes:
            print("No added certificate authority is in use: outgoing connections trust the authorities of the "
                  "system only.", file=sortie)
        return None
    chemin = Path(dossier) / FICHIER
    try:
        ecrire(chemin, contenu_reuni(bilan, environ))
    except OSError as e:
        print(f"The file of the certificate authorities {chemin} cannot be written ({e}): the added authorities are "
              "not in use.", file=sortie)
        return None
    for v in VARIABLES_DONNEES + (MARQUE,):
        environ[v] = str(chemin)
    return chemin


def appliquer(environ, dossier):
    """Appelé par ``config/settings.py`` : ne refait rien si le processus parent a préparé le fichier (marque posée,
    ``SSL_CERT_FILE`` égal, fichier présent) ou si rien n'est demandé."""
    if not environ.get(VARIABLE, "").strip():
        return None
    fait = environ.get(MARQUE, "")
    if fait and environ.get("SSL_CERT_FILE") == fait and os.path.isfile(fait):
        return Path(fait)
    return preparer(environ, dossier)


def en_service(environ=None):
    """Chemin du fichier réuni en service dans ce processus, ou None."""
    environ = os.environ if environ is None else environ
    fait = environ.get(MARQUE, "")
    return Path(fait) if fait and environ.get("SSL_CERT_FILE") == fait and os.path.isfile(fait) else None


def _dossier_donnees():
    """Même règle que ``config/settings.py`` (``DATA_DIR``, ancien nom ``DOSSIER_DONNEES``, relatif au projet)."""
    valeur = (os.environ.get("DATA_DIR") or os.environ.get("DOSSIER_DONNEES") or "").strip()
    projet = Path(__file__).resolve().parent.parent
    return projet / valeur if valeur else projet / "local-data"


if __name__ == "__main__":
    # docker/entrypoint.sh : messages sur la sortie d'erreur, chemin du fichier réuni (ou rien) sur la sortie standard
    resultat = preparer(dict(os.environ), _dossier_donnees()) if os.environ.get(VARIABLE, "").strip() else None
    if resultat:
        print(resultat)
