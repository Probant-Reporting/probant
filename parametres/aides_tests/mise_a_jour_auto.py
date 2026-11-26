"""Aides des tests de ``auto-update.sh`` (mise à jour automatique), sans Docker ni réseau : un faux ``docker`` écrit en
Python qui joue une installation (outil en marche ou arrêté, image qui tourne, registre, cosign, base de chaque espace)
selon un scénario JSON, et note chaque appel ; un faux ``sleep`` qui rend la main tout de suite. Le vrai ``update.sh``
et le vrai ``curl`` tournent, contre le dépôt factice de ``scripts_installation``.

État du faux (fichier JSON ``etat.json`` du dossier du test) :
- ``running`` : le service web est en marche ; ``image`` : identifiant de l'image qui tourne ;
- ``empreintes`` : {partie : empreinte} des migrations de chaque base (« registry », « space principal »…) ;
- ``archives`` : {espace : [noms]} des sauvegardes ; ``choice`` : contenu du fichier de choix ; ``result`` : dernier
  résultat écrit dans le volume ;
- ``scenario`` : réglages du cas joué (voir ``SCENARIO``)."""
import json
import sys
from pathlib import Path

from .scripts_installation import RACINE, AidesScripts, ecrire_executable, version_des_fichiers

ANCIENNE, NOUVELLE = "sha256:" + "a" * 64, "sha256:" + "b" * 64  # empreintes (identifiants) des images
EMPREINTE_AVANT = {"registry": "1" * 64, "space principal": "2" * 64, "space second": "3" * 64}

SCENARIO = {
    "latest": "9.9.1",           # version que donne /releases/latest (dépôt factice)
    "pull_ok": True,             # le registre répond
    "cosign_present": True,      # l'image de cosign est là (ou se télécharge)
    "cosign_rc": 0,              # code de sortie de « cosign verify »
    "liste_rc": None,            # code de sortie imposé de « cosign verify-blob » (liste des sommes) ; None : la
                                 # signature factice est vérifiée (scripts_installation, signature_factice)
    "created": "2020-01-01T00:00:00Z",  # date de construction de la nouvelle image
    "busy": "idle",              # réponse de « auto_update --busy »
    "registry_old": ["espaces/0001_initial.py"],  # migrations du registre commun de l'ancienne et de la nouvelle image
    "registry_new": ["espaces/0001_initial.py"],
    "new_healthy": True,         # la nouvelle image répond sur /sante/
    "new_migrates": [],          # parties dont la nouvelle version change les migrations
    "old_healthy": True,         # l'ancienne image répond après le retour arrière
    "restore_rc": 0,             # code de sortie de « restore »
    "backup_rc": 0,              # code de sortie de « backup --reason before-update »
}

FAUX_DOCKER = r'''#!PYTHON
"""Faux docker des tests de auto-update.sh (parametres/aides_tests/mise_a_jour_auto.py)."""
import hashlib, json, os, sys
from pathlib import Path

etat_f = Path(os.environ["FAUX_ETAT"])
e = json.loads(etat_f.read_text())
sc = e["scenario"]
a = sys.argv[1:]
ligne = " ".join(a)
with open(os.environ["JOURNAL"], "a") as j:
    j.write(f"{Path('docker-compose.yml').read_text().splitlines()[-1] if Path('docker-compose.yml').exists() else ''}|{ligne}\n")

ANCIENNE, NOUVELLE = "sha256:" + "a" * 64, "sha256:" + "b" * 64
NOM = os.environ.get("PROBANT_TEST_IMAGE") or "ghcr.io/probant-reporting/probant"

def sortir(code=0, texte=None):
    etat_f.write_text(json.dumps(e))
    if texte is not None:
        sys.stdout.write(texte if texte.endswith("\n") or not texte else texte + "\n")
    sys.exit(code)

def image_du_env():  # image de IMAGE= dans .env : la nouvelle (épinglée par update.sh --digest), sinon l'ancienne
    try:
        v = [l for l in Path(".env").read_text().splitlines() if l.startswith("IMAGE=")][-1].split("=", 1)[1]
    except (OSError, IndexError):
        return ANCIENNE
    return NOUVELLE if NOUVELLE in v else ANCIENNE

def espace():
    for i, x in enumerate(a):
        if x == "-e" and a[i + 1].startswith("SPACE="):
            return a[i + 1].split("=", 1)[1]
    return "principal"

def outil(cmd):  # commande dans le conteneur (exec) ou dans l'image (run)
    texte = " ".join(cmd)
    if "cat /data/auto-update/choice" in texte:
        sortir(0, e.get("choice", ""))
    if "cat > /data/auto-update/.result.new" in texte:
        e["result"] = sys.stdin.read()
        e.setdefault("results", []).append(e["result"])
        sortir(0)
    if "cat /app/VERSION" in texte:
        sortir(0, "9.9.0")
    if "urlopen" in texte:  # /sante/
        if not e["running"]:
            sortir(1)
        ok = sc["new_healthy"] if e["image"] == NOUVELLE else sc["old_healthy"]
        sortir(0 if ok else 1)
    if "auto_update --busy" in texte:
        sortir(0 if sc["busy"] == "idle" else 3, sc["busy"])
    if "auto_update --fingerprint" in texte:
        sortir(0, "\n".join(f"{k} {v}" for k, v in e["empreintes"].items()))
    if "backup --list" in texte:
        noms = e["archives"].get(espace(), [])
        sortir(0, "\n".join(f"{n}  1.0 MB" for n in noms) + f"\n{len(noms)} backup(s) in /data/backups")
    if "backup --reason before-update" in texte or "sauvegarde --motif" in texte:
        if sc["backup_rc"]:
            sortir(sc["backup_rc"], "Backup failed")
        n = len(e["archives"].setdefault(espace(), []))
        e["archives"][espace()].append(f"backup-20990101-0300{n:02d}-before-update.zip")
        sortir(0, "Backup created")
    if "spaces --list" in texte:
        sortir(0, "\n".join(f"{c}  Space {c}  active  /espace/{c}/" for c in e.get("espaces", [])))
    if " restore " in f" {texte} ":
        e.setdefault("restaurations", []).append(f"{espace()} {texte}")
        if sc["restore_rc"]:
            sortir(sc["restore_rc"], "Restore failed")
        e["empreintes"][f"space {espace()}"] = e["avant"][f"space {espace()}"]
        sortir(0, "Restore complete.")
    sortir(0)

if a[:1] == ["compose"]:
    c = a[1:]
    if c[:1] == ["ps"]:
        if "-q" in c:
            sortir(0, "c1" if e["running"] or e.get("cree") else "")
        sortir(0, "web" if e["running"] else "")
    if c[:1] == ["exec"]:
        if not e["running"]:
            sortir(1)
        i = c.index("web")
        outil(c[i + 1:])
    if c[:1] == ["run"]:
        i = c.index("web")
        outil(c[i + 1:])
    if c[:1] == ["stop"]:
        e["running"] = False
        sortir(0)
    if c[:2] == ["up", "-d"]:
        e["running"], e["cree"] = True, True
        e["image"] = image_du_env()
        if e["image"] == NOUVELLE:
            for partie in sc["new_migrates"]:
                e["empreintes"][partie] = "f" * 64
        sortir(0)
    if c[:1] == ["pull"]:
        sortir(0 if sc["pull_ok"] else 1)
    sortir(0)
if a[:1] == ["pull"]:
    if "cosign" in ligne:
        sortir(0 if sc["cosign_present"] else 1)
    if not sc["pull_ok"]:
        sortir(1, "Error response from daemon: unreachable")
    sortir(0, f"{sc['latest']}: Pulling from probant\nDigest: {NOUVELLE if sc.get('latest_is_new', True) else ANCIENNE}\nStatus: Downloaded newer image")
if a[:2] == ["image", "inspect"]:
    if "cosign" in ligne:
        sortir(0 if sc["cosign_present"] and sc.get("cosign_local", True) else 1)
    if "{{.Created}}" in ligne:
        sortir(0, sc["created"])
    if "{{.Id}}" in ligne:
        sortir(0, NOUVELLE if NOUVELLE in ligne else ANCIENNE)
    sortir(0)
if a[:1] == ["inspect"]:
    sortir(0, e["image"])
if a[:2] == ["image", "rm"]:
    sortir(0)
if a[:1] == ["run"]:
    if "verify-blob" in a:  # signature de la liste des sommes : le paquet contient l'empreinte de la liste signée
        e.setdefault("cosign_listes", []).append(a)
        if sc.get("liste_rc") is not None:
            sortir(sc["liste_rc"], "Error: no matching signatures" if sc["liste_rc"] else "Verified OK")
        dossier = [x for i, x in enumerate(a) if a[i - 1] == "-v" and x.endswith(":/work:ro")][0][:-len(":/work:ro")]
        paquet, liste = (Path(dossier + x[len("/work"):]) for x in (a[a.index("--bundle") + 1], a[-1]))
        bon = paquet.read_text().strip() == hashlib.sha256(liste.read_bytes()).hexdigest()
        sortir(0 if bon else 1, "Verified OK" if bon else "Error: invalid signature")
    if "verify" in a:
        e.setdefault("cosign", []).append(a)
        sortir(sc["cosign_rc"], "verification" if sc["cosign_rc"] == 0 else "Error: no matching signatures")
    if "--network" in a and a[a.index("--network") + 1] == "none":
        liste = sc["registry_new"] if NOUVELLE in ligne else sc["registry_old"]
        sortir(0, "\n".join(liste))
    sortir(0)
sortir(0)
'''


class AidesMiseAJourAuto(AidesScripts):
    """Installation faite en une commande (fichiers de la version 9.9.0, image publiée), dépôt factice avec la version
    9.9.1, faux docker de ``auto-update.sh``."""

    def installation(self, scenario=None, choix="mode=automatic\ndelay=0\n", espaces=(), **etat):
        tmp = self.dossier()
        sc = {**SCENARIO, **(scenario or {})}
        etiquettes = {f"v{v}": {**version_des_fichiers(v), "auto-update.sh": (RACINE / "auto-update.sh").read_bytes()}
                      for v in ("9.9.0", "9.9.1")}
        depot = self.depot(etiquettes, f"v{sc['latest']}")
        dossier = tmp / "probant"
        (dossier / "docker").mkdir(parents=True)
        for f, contenu in version_des_fichiers("9.9.0").items():
            if f != "VERSION":
                (dossier / f).write_bytes(contenu)
        (dossier / "auto-update.sh").write_bytes((RACINE / "auto-update.sh").read_bytes())
        (dossier / ".env").write_text("HTTP_PORT=8000\nIMAGE=ghcr.io/probant-reporting/probant:9.9.0\n", encoding="utf-8")
        empreintes = {k: v for k, v in EMPREINTE_AVANT.items() if k != "space second" or "second" in espaces}
        archives = {"principal": ["backup-20990101-020000-auto.zip"], **{c: [] for c in espaces}}
        e = {"running": True, "image": ANCIENNE, "empreintes": empreintes, "avant": dict(empreintes), "archives": archives,
             "choice": choix, "espaces": list(espaces), "scenario": sc, **etat}
        (tmp / "etat.json").write_text(json.dumps(e), encoding="utf-8")
        bin_ = tmp / "faux-bin"
        bin_.mkdir()
        ecrire_executable(bin_ / "docker", FAUX_DOCKER.replace("#!PYTHON", f"#!{sys.executable}", 1))
        ecrire_executable(bin_ / "sleep", "#!/bin/sh\nexit 0\n")
        import os

        env = self.environnement(tmp, depot, chemin=f"{bin_}{os.pathsep}{os.environ['PATH']}", FAUX_ETAT=str(tmp / "etat.json"))
        return tmp, dossier, env

    def lancer_auto(self, dossier, env, *options):
        return self.lancer(["sh", str(dossier / "auto-update.sh"), *options], cwd=dossier, env=env)

    @staticmethod
    def etat(tmp):
        return json.loads((tmp / "etat.json").read_text(encoding="utf-8"))

    def resultat(self, tmp):
        """Dernier résultat écrit dans le volume, lu par l'analyse de l'outil (le format que l'outil accepte)."""
        from parametres import mise_a_jour_auto as MA

        texte = self.etat(tmp).get("result")
        self.assertIsNotNone(texte, "aucun résultat écrit dans le volume")
        return MA.analyser_resultat(texte.encode())

    @staticmethod
    def image_env(dossier):
        return [x for x in (dossier / ".env").read_text(encoding="utf-8").splitlines() if x.startswith("IMAGE=")][-1][6:]


def fichier(chemin):
    return Path(chemin).read_text(encoding="utf-8")
