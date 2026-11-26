"""Aides des tests des scripts d'installation (``get.sh``, ``install.sh``, ``update.sh``), sans Docker ni réseau.

- ``DepotFactice`` : copie locale du dépôt public, servie en HTTP sur 127.0.0.1 (le vrai ``curl`` des scripts la lit par
  ``PROBANT_TEST_SOURCE``) : ``/releases/latest`` mène à ``/releases/tag/<étiquette>`` comme sur GitHub,
  ``/raw/refs/tags/<étiquette>/<fichier>`` donne les fichiers d'une version, et ``/releases/download/<étiquette>/<nom>``
  les pièces jointes de sa release (par défaut, la liste des sommes SHA-256 de ses fichiers et sa « signature ») ;
  chaque demande est notée.
- Signature factice d'une liste de sommes : le « paquet » de signature (``.sigstore.json``) contient l'empreinte SHA-256
  de la liste signée. Le faux cosign (``FAUX_COSIGN``, et le faux ``docker`` pour le conteneur de cosign) la compare à la
  liste reçue : une liste changée après la signature est refusée, comme par le vrai cosign.
- ``FAUX_DOCKER`` : faux ``docker`` qui note chaque appel (avec la dernière ligne de docker-compose.yml, pour savoir
  quelle version des fichiers était en place) et répond comme un Docker en marche, outil arrêté.
- ``chemin_sans(dossier, noms)`` : un PATH où les commandes nommées n'existent pas (Docker absent, ``apt-get``…), pour
  qu'aucune vraie commande d'administration ne puisse partir d'un test."""
import hashlib
import os
import shutil
import stat
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent.parent

# fichiers d'une version qui font tourner l'outil (la liste FILES de get.sh et de update.sh)
FICHIERS_VERSION = ("docker-compose.yml", ".env.example", "install.sh", "update.sh", "check.sh", "docker/Caddyfile")
IMAGE_PUBLIQUE = "ghcr.io/probant-reporting/probant"

# vérification factice d'une signature de liste (cosign verify-blob) : le paquet BUNDLE contient l'empreinte de LIST ;
# FAUX_COSIGN_RC impose le résultat, FAUX_COSIGN_INIT_RC celui de « cosign initialize » (racine de confiance)
VERIFIER_FACTICE = r"""
verifier_factice() {  # verifier_factice DOSSIER ARGUMENTS… : DOSSIER remplace /work (conteneur) ; vide : chemins tels quels
  d="$1"; shift
  case " $* " in *" initialize "*) exit "${FAUX_COSIGN_INIT_RC:-0}" ;; esac
  if [ -n "${FAUX_COSIGN_RC:-}" ]; then exit "$FAUX_COSIGN_RC"; fi
  prev=""; b=""; l=""
  for a in "$@"; do if [ "$prev" = --bundle ]; then b="$a"; fi; prev="$a"; l="$a"; done
  if [ -n "$d" ]; then b="$d${b#/work}"; l="$d${l#/work}"; fi
  [ -f "$b" ] && [ -f "$l" ] && [ "$(sha256sum < "$l" | cut -d' ' -f1)" = "$(cat "$b")" ] && exit 0
  echo "Error: invalid signature" >&2; exit 1
}
"""

FAUX_DOCKER = r"""#!/bin/sh
# faux docker : note l'appel (fichiers en place | arguments) et simule un Docker en marche, outil arrêté ; le conteneur de
# cosign vérifie la signature factice des listes de sommes
echo "$(tail -1 docker-compose.yml 2>/dev/null)|$*" >> "$JOURNAL"
""" + VERIFIER_FACTICE + r"""
case "$*" in
  "compose ps"*) exit 0 ;;
  *"cat /app/VERSION"*) echo "0.9.0" ;;
  info*) exit "${FAUX_DOCKER_INFO_RC:-0}" ;;
  "run "*" verify-blob "*|"run "*" initialize"*)
    dossier=$(printf '%s\n' "$*" | sed -n 's|.* -v \([^ ]*\):/work:ro .*|\1|p')
    verifier_factice "$dossier" "$@" ;;
esac
exit 0
"""

# faux cosign de la machine (dans le PATH du test seulement quand un cas le demande) : note l'appel, même vérification
FAUX_COSIGN = r"""#!/bin/sh
echo "cosign|$*" >> "$JOURNAL"
""" + VERIFIER_FACTICE + r"""
verifier_factice "" "$@"
"""


def version_des_fichiers(version):
    """Fichiers de la version ``version`` : ceux du dépôt, docker-compose.yml marqué à la dernière ligne."""
    contenus = {f: (RACINE / f).read_bytes() for f in FICHIERS_VERSION}
    contenus["docker-compose.yml"] += f"# files of version {version}\n".encode()
    contenus["VERSION"] = f"{version}\n".encode()
    return contenus


# fichiers d'une version dans sa liste de sommes (docker/make_file_sums.sh), dans cet ordre
FICHIERS_LISTE = ("VERSION", "get.sh", *FICHIERS_VERSION, "auto-update.sh")


def nom_liste(version):
    return f"probant-{version}-files.sha256"


def liste_des_sommes(fichiers):
    """Texte de la liste des sommes (format de sha256sum) des fichiers d'une version {chemin : octets}."""
    return "".join(f"{hashlib.sha256(fichiers[f]).hexdigest()}  {f}\n" for f in FICHIERS_LISTE if f in fichiers).encode()


def signature_factice(liste):
    """« Paquet » de signature d'une liste : son empreinte (voir le faux cosign)."""
    return hashlib.sha256(liste).hexdigest().encode()


def release_de(fichiers, liste=None):
    """Pièces jointes de la release d'une version : la liste des sommes de ses fichiers (ou ``liste``) et sa signature
    factice (celle de la liste donnée)."""
    version = fichiers["VERSION"].decode().strip()
    liste = liste if liste is not None else liste_des_sommes(fichiers)
    return {nom_liste(version): liste, f"{nom_liste(version)}.sigstore.json": signature_factice(liste)}


class DepotFactice:
    """Serveur HTTP local : ``etiquettes`` = {étiquette (v1.2.3 ou V1.2.3) : {chemin : octets}}, ``derniere`` = étiquette
    de la dernière version publiée (None : aucune), ``releases`` = {étiquette : {nom : octets}} (par défaut : pour chaque
    étiquette, la liste des sommes de ses fichiers et sa signature factice)."""

    def __init__(self, etiquettes, derniere=None, releases=None):
        self.etiquettes, self.derniere, self.demandes = etiquettes, derniere, []
        self.releases = releases if releases is not None else {
            e: release_de(f) for e, f in etiquettes.items() if "VERSION" in f}
        depot = self

        class Gestion(BaseHTTPRequestHandler):
            def do_GET(self):
                depot.demandes.append(self.path)
                chemin = self.path.split("?")[0]
                if chemin == "/releases/latest":
                    self.send_response(302)
                    self.send_header("Location", f"/releases/tag/{depot.derniere}" if depot.derniere else "/releases")
                    self.end_headers()
                    return
                if chemin == "/releases" or chemin.startswith("/releases/tag/"):
                    return self.repondre(b"<html>releases</html>")
                prefixe = "/raw/refs/tags/"
                if chemin.startswith(prefixe):
                    etiquette, _, fichier = chemin[len(prefixe):].partition("/")
                    contenu = depot.etiquettes.get(etiquette, {}).get(fichier)
                    if contenu is not None:
                        return self.repondre(contenu)
                prefixe = "/releases/download/"
                if chemin.startswith(prefixe):
                    etiquette, _, nom = chemin[len(prefixe):].partition("/")
                    contenu = depot.releases.get(etiquette, {}).get(nom)
                    if contenu is not None:
                        return self.repondre(contenu)
                self.send_response(404)
                self.end_headers()

            def repondre(self, contenu):
                self.send_response(200)
                self.send_header("Content-Length", str(len(contenu)))
                self.end_headers()
                self.wfile.write(contenu)

            def log_message(self, *args):
                pass

        self.serveur = ThreadingHTTPServer(("127.0.0.1", 0), Gestion)
        self.adresse = f"http://127.0.0.1:{self.serveur.server_address[1]}"
        threading.Thread(target=self.serveur.serve_forever, daemon=True).start()

    def fermer(self):
        self.serveur.shutdown()
        self.serveur.server_close()

    def fichiers_demandes(self):
        return [d for d in self.demandes if d.startswith("/raw/")]


def ecrire_executable(chemin, texte):
    chemin.write_text(texte, encoding="utf-8")
    chemin.chmod(stat.S_IRWXU)


def chemin_sans(dossier, noms):
    """Dossier de liens vers toutes les commandes des dossiers du système, sauf ``noms`` : avec lui seul (et les faux),
    une commande absente l'est vraiment, et aucune vraie commande nommée ne peut partir. Seuls les dossiers standard :
    pas ceux qu'un poste de développement met en tête du PATH (enveloppes de commandes)."""
    dossier.mkdir(parents=True, exist_ok=True)
    for rep in ("/usr/local/sbin", "/usr/local/bin", "/usr/sbin", "/usr/bin", "/sbin", "/bin"):
        if not rep or not os.path.isdir(rep):
            continue
        for nom in os.listdir(rep):
            cible = Path(rep) / nom
            lien = dossier / nom
            if nom in noms or lien.exists() or lien.is_symlink() or not os.access(cible, os.X_OK) or cible.is_dir():
                continue
            lien.symlink_to(cible)
    return dossier


class AidesScripts:
    """Mélange pour un ``SimpleTestCase`` : dossier temporaire, faux docker, dépôt factice, lancement d'un script."""

    def dossier(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        return tmp

    def depot(self, etiquettes, derniere=None, releases=None):
        d = DepotFactice(etiquettes, derniere, releases)
        self.addCleanup(d.fermer)
        return d

    def faux_bin(self, tmp):
        bin_ = tmp / "faux-bin"
        bin_.mkdir(exist_ok=True)
        ecrire_executable(bin_ / "docker", FAUX_DOCKER)
        return bin_

    @staticmethod
    def ajouter_faux_cosign(dossier):
        """Un cosign « de la machine » dans ``dossier`` (un dossier du PATH du test)."""
        ecrire_executable(Path(dossier) / "cosign", FAUX_COSIGN)

    def environnement(self, tmp, depot=None, chemin=None, diagnostic=False, **autres):
        """Environnement d'un script. Sans ``diagnostic`` : contrôle du serveur (check.sh) sauté à l'installation, par
        ``PROBANT_TEST_SKIP_CHECK`` (il lit la vraie machine et le réseau ; ses propres tests le jouent avec des faux)."""
        journal = tmp / "journal.txt"
        journal.touch()
        env = {k: v for k, v in os.environ.items()
               if not k.startswith("PROBANT_TEST_") and k.lower() not in ("http_proxy", "https_proxy", "all_proxy", "image")}
        env.update({"PATH": chemin or f"{self.faux_bin(tmp)}{os.pathsep}{os.environ['PATH']}", "JOURNAL": str(journal),
                    "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost", "CODESPACES": ""})
        if not diagnostic:
            env["PROBANT_TEST_SKIP_CHECK"] = "1"
        if depot is not None:
            env["PROBANT_TEST_SOURCE"] = depot.adresse
        env.update(autres)
        return env

    @staticmethod
    def lancer(commande, cwd, env, entree=None, **options):
        # nouvelle session : aucun terminal de contrôle, /dev/tty ne s'ouvre pas (comme sur un serveur sans session)
        options.setdefault("start_new_session", True)
        return subprocess.run(commande, cwd=cwd, env=env, input=entree, capture_output=True, text=True, timeout=60,
                              **options)

    @staticmethod
    def appels(tmp):
        return (tmp / "journal.txt").read_text(encoding="utf-8").splitlines()

    @staticmethod
    def valeur(env_fichier, cle):
        lignes = [x for x in Path(env_fichier).read_text(encoding="utf-8").splitlines() if x.startswith(cle + "=")]
        return lignes[-1].split("=", 1)[1] if lignes else None
