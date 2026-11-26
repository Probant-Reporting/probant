"""Faux programmes pour les tests du contrôle du serveur (``check.sh``) : chacun répond selon une variable ``F_…`` de
l'environnement, avec une valeur « bonne » par défaut (``VALEURS_BONNES``). Le PATH ne contient que ces faux et les
commandes du système qui ne sont pas simulées : une commande retirée (``absents``) l'est vraiment.

- ``uname`` (-s, -m), ``docker`` (version, compose version, info et ses formats), ``free``, ``nproc``, ``df`` (note le
  dossier demandé), ``ss`` (ports à l'écoute), ``getent`` (adresses du nom), ``hostname`` (-I), ``date`` (heure du
  moment réglable, sinon la vraie commande) ;
- ``curl`` : note chaque appel dans ``JOURNAL_RESEAU`` ; une adresse dont l'hôte est dans ``F_BLOQUES`` ne répond pas
  (code 7, comme une connexion refusée), ``--noproxy`` suit ``F_DIRECT`` ; les autres répondent avec un en-tête
  ``date`` (``F_DATE``, sinon l'heure du moment)."""
import email.utils
import os
import shutil
import time
from pathlib import Path

from parametres.aides_tests.scripts_installation import chemin_sans, ecrire_executable

FAUX = {
    "uname": r"""#!/bin/sh
case "$1" in -m) echo "$F_ARCH" ;; *) echo "$F_SYSTEME" ;; esac
""",
    "docker": r"""#!/bin/sh
case "$*" in
  "version --format"*) echo "$F_DOCKER_CLIENT" ;;
  "compose version"*) [ "$F_COMPOSE" = absent ] && { echo "docker: 'compose' is not a docker command." >&2; exit 1; }; echo "$F_COMPOSE" ;;
  "info --format"*)
    case "$F_DOCKER_SERVICE" in
      droits) echo "permission denied while trying to connect to the Docker daemon socket at unix:///var/run/docker.sock" >&2; exit 1 ;;
      arrete) echo "Cannot connect to the Docker daemon at unix:///var/run/docker.sock. Is the docker daemon running?" >&2; exit 1 ;;
    esac
    case "$*" in
      *ServerVersion*) echo "$F_DOCKER_SERVEUR" ;;
      *DockerRootDir*) echo "$F_DOCKER_DOSSIER" ;;
      *HTTPSProxy*) echo "$F_DOCKER_PROXY" ;;
    esac ;;
  *) echo "docker $*" >> "$JOURNAL_RESEAU" ;;
esac
""",
    "free": r"""#!/bin/sh
echo "               total        used        free      shared  buff/cache   available"
echo "Mem:           $F_MEMOIRE         100         100           0         100         100"
echo "Swap:              0           0           0"
""",
    "nproc": '#!/bin/sh\necho "$F_PROCESSEURS"\n',
    "df": r"""#!/bin/sh
for a in "$@"; do d="$a"; done
echo "df $d" >> "$JOURNAL_RESEAU"
echo "Filesystem     1024-blocks      Used Available Capacity Mounted on"
echo "/dev/vda1         99999999  11111111  $F_DISQUE_KO      12% /"
""",
    "ss": r"""#!/bin/sh
for p in $F_ECOUTE; do echo "LISTEN 0      4096         0.0.0.0:$p        0.0.0.0:*"; done
""",
    "getent": r"""#!/bin/sh
[ -n "$F_ADRESSES_DU_NOM" ] || exit 2
for a in $F_ADRESSES_DU_NOM; do echo "$a STREAM $2"; echo "$a DGRAM"; echo "$a RAW"; done
""",
    "hostname": '#!/bin/sh\necho "$F_MES_ADRESSES"\n',
    "curl": r"""#!/bin/sh
echo "curl $*" >> "$JOURNAL_RESEAU"
sortie=1 ; direct=0
for a in "$@"; do
  case "$a" in -o) sortie=0 ;; --noproxy) direct=1 ;; esac
  url="$a"
done
hote=$(printf '%s' "$url" | sed -E 's|^[a-z]+://||; s|/.*||')
if [ "$direct" = 1 ] && [ "$F_DIRECT" != oui ]; then exit 7; fi
for b in $F_BLOQUES; do [ "$b" = "$hote" ] && exit 7; done
if [ "$sortie" = 1 ]; then
  printf 'HTTP/2 200\r\nserver: essai\r\n'
  [ -n "$F_DATE" ] && printf 'date: %s\r\n' "$F_DATE"
  printf '\r\n'
fi
exit 0
""",
    "date": r"""#!/bin/sh
if [ -n "$F_MAINTENANT" ] && [ "$*" = "-u +%s" ]; then echo "$F_MAINTENANT"; exit 0; fi
exec "$VRAIE_DATE" "$@"
""",
}

OS_RELEASE = 'PRETTY_NAME="Ubuntu 24.04.1 LTS"\nID=ubuntu\nVERSION_CODENAME=noble\n'


def date_http(decalage=0):
    return email.utils.formatdate(time.time() + decalage, usegmt=True)


def valeurs_bonnes(tmp):
    return {
        "F_SYSTEME": "Linux", "F_ARCH": "x86_64", "F_DOCKER_CLIENT": "27.3.1", "F_DOCKER_SERVEUR": "27.3.1",
        "F_COMPOSE": "2.29.1", "F_DOCKER_SERVICE": "ok", "F_DOCKER_DOSSIER": str(tmp / "docker-data"),
        "F_DOCKER_PROXY": "", "F_MEMOIRE": "1990", "F_PROCESSEURS": "2", "F_DISQUE_KO": "41000000", "F_ECOUTE": "22",
        "F_ADRESSES_DU_NOM": "", "F_MES_ADRESSES": "203.0.113.10", "F_BLOQUES": "", "F_DIRECT": "oui",
        "F_DATE": date_http(), "F_MAINTENANT": "",
    }


def preparer_faux(tmp, absents=(), garder_curl=False):
    """(PATH, variables) : faux programmes de ``FAUX`` (sauf ``absents``, et sauf ``curl`` si ``garder_curl`` : le
    vrai curl reste), devant les commandes du système qui ne sont pas simulées."""
    simules = set(FAUX) - ({"curl"} if garder_curl else set())
    faux = tmp / "faux-diagnostic"
    faux.mkdir(exist_ok=True)
    for nom, texte in FAUX.items():
        if nom in simules and nom not in absents:
            ecrire_executable(faux / nom, texte)
    systeme = chemin_sans(tmp / "systeme-diagnostic", simules | set(absents))
    (tmp / "os-release").write_text(OS_RELEASE, encoding="utf-8")
    (tmp / "docker-data").mkdir(exist_ok=True)
    (tmp / "reseau.txt").touch()
    variables = valeurs_bonnes(tmp)
    variables.update({"JOURNAL_RESEAU": str(tmp / "reseau.txt"), "VRAIE_DATE": shutil.which("date"),
                      "PROBANT_TEST_OS_RELEASE": str(tmp / "os-release")})
    return f"{faux}{os.pathsep}{systeme}", variables


def journal_reseau(tmp):
    return Path(tmp / "reseau.txt").read_text(encoding="utf-8").splitlines()
