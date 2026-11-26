"""Installation et mise à jour sans accès à Internet : paquet hors ligne (``docker/make_offline_package.sh``),
``./install.sh --offline`` et ``./update.sh --offline``.

Joué sans Docker ni réseau : un faux ``docker`` (``save`` écrit le nom de l'image dans l'archive, ``load`` le relit et
répond « Loaded image: … » comme Docker, chaque appel noté avec la version des fichiers en place) ; ``curl`` et
``wget`` sont des faux qui notent tout appel et échouent : aucune requête réseau ne doit partir. L'essai réel avec
Docker est ``docker/test_offline.sh``."""

import os
import shutil
import subprocess
import tarfile

from django.test import SimpleTestCase

from parametres.aides_tests.faux_diagnostic import preparer_faux
from parametres.aides_tests.scripts_installation import (
    FICHIERS_VERSION, IMAGE_PUBLIQUE, RACINE, AidesScripts, chemin_sans, ecrire_executable, version_des_fichiers)

FAUX_DOCKER_HORS_LIGNE = r"""#!/bin/sh
# réponses du contrôle du serveur (check.sh), non notées : un Docker 27 en marche
case "$*" in
  "version --format"*|"info --format {{.ServerVersion}}") echo "27.3.1"; exit 0 ;;
  "compose version"*) echo "2.29.1"; exit 0 ;;
  "info --format"*) exit 0 ;;
esac
echo "$(tail -1 docker-compose.yml 2>/dev/null)|$*" >> "$JOURNAL"
case "$1" in
  save) echo "IMAGE=$2" ; exit 0 ;;
  load) shift; [ -z "$F_LOAD_ECHOUE" ] && [ "$1" = -i ] || exit 1; nom=$(gzip -dc "$2" | sed -n 's/^IMAGE=//p'); [ -n "$nom" ] || exit 1
        echo "Loaded image: $nom" ; exit 0 ;;
  run) for a in "$@"; do i="$a"; done; [ "$i" = /app/VERSION ] && { for a in "$@"; do case "$a" in *:*) v="${a##*:}" ;; esac; done; echo "$v"; } ; exit 0 ;;
esac
case "$*" in
  "compose ps"*) exit 0 ;;
  *"cat /app/VERSION"*) echo "0.9.0" ;;
esac
exit 0
"""
FAUX_RESEAU = '#!/bin/sh\necho "$(basename "$0") $*" >> "$JOURNAL_RESEAU"\nexit 7\n'


class AidesHorsLigne(AidesScripts):
    def environnement_hors_ligne(self, tmp, **autres):
        faux = tmp / "faux-hors-ligne"
        faux.mkdir(exist_ok=True)
        ecrire_executable(faux / "docker", FAUX_DOCKER_HORS_LIGNE)
        for nom in ("curl", "wget"):
            ecrire_executable(faux / nom, FAUX_RESEAU)
        (tmp / "reseau.txt").touch()
        chemin = f"{faux}{os.pathsep}{chemin_sans(tmp / 'systeme', {'docker', 'curl', 'wget'})}"
        return self.environnement(tmp, chemin=chemin, JOURNAL_RESEAU=str(tmp / "reseau.txt"), **autres)

    def paquet(self, tmp, version, marque=True):
        """Paquet hors ligne de ``version`` fait par docker/make_offline_package.sh (faux docker), depuis une copie des
        fichiers du dépôt (docker-compose.yml marqué à la dernière ligne). Renvoie le chemin du .tar."""
        code = tmp / f"code-{version}"
        (code / "docker").mkdir(parents=True)
        contenus = version_des_fichiers(version) if marque else {f: (RACINE / f).read_bytes() for f in FICHIERS_VERSION}
        for f in FICHIERS_VERSION:
            (code / f).write_bytes(contenus[f])
        for f in ("install.sh", "update.sh", "check.sh"):
            (code / f).chmod(0o755)
        shutil.copy(RACINE / "docker" / "make_offline_package.sh", code / "docker")
        env = self.environnement_hors_ligne(tmp)
        r = self.lancer(["bash", str(code / "docker" / "make_offline_package.sh"), f"{IMAGE_PUBLIQUE}:{version}",
                         str(tmp / "dist")], cwd=tmp, env=env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return tmp / "dist" / f"probant-{version}-offline.tar"

    def extraire(self, paquet, dossier):
        dossier.mkdir(parents=True, exist_ok=True)
        subprocess.run(["tar", "-xf", str(paquet), "-C", str(dossier)], check=True)
        return dossier / "probant"

    def appels_docker(self, tmp):
        return [tuple(a.split("|", 1)) for a in self.appels(tmp)]

    def reseau(self, tmp):
        return (tmp / "reseau.txt").read_text(encoding="utf-8").splitlines()


class PaquetTests(AidesHorsLigne, SimpleTestCase):
    def test_contenu_et_sommes(self):
        tmp = self.dossier()
        paquet = self.paquet(tmp, "9.9.1", marque=False)
        with tarfile.open(paquet) as t:
            noms = sorted(m.name for m in t.getmembers() if m.isfile())
            modes = {m.name: m.mode for m in t.getmembers()}
            sommes = t.extractfile("probant/SHA256SUMS").read().decode()
            self.assertEqual(t.extractfile("probant/VERSION").read(), b"9.9.1\n")
            image = t.extractfile("probant/probant-image-9.9.1.tar.gz").read()
        attendus = sorted(f"probant/{f}" for f in (*FICHIERS_VERSION, "VERSION", "SHA256SUMS", "probant-image-9.9.1.tar.gz",
                                                     "caddy-image.tar.gz"))
        self.assertEqual(noms, attendus)
        for f in ("install.sh", "update.sh", "check.sh"):
            self.assertTrue(modes[f"probant/{f}"] & 0o111, f)
        # chaque fichier du dossier, sauf SHA256SUMS lui-même, a sa somme
        self.assertEqual(sorted(x.split()[1] for x in sommes.splitlines()),
                         sorted(n.removeprefix("probant/") for n in attendus if not n.endswith("SHA256SUMS")))
        # archive de l'image : docker save, compressé
        import gzip
        self.assertEqual(gzip.decompress(image), f"IMAGE={IMAGE_PUBLIQUE}:9.9.1\n".encode())
        # somme du paquet entier, vérifiable par sha256sum -c
        r = subprocess.run(["sha256sum", "-c", paquet.name + ".sha256"], cwd=paquet.parent, capture_output=True)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(self.reseau(tmp), [])

    def test_version_lue_dans_l_image(self):
        tmp = self.dossier()
        env = self.environnement_hors_ligne(tmp)
        r = self.lancer(["bash", str(RACINE / "docker" / "make_offline_package.sh"), "probant:local", str(tmp / "dist")],
                        cwd=tmp, env=env)
        self.assertEqual(r.returncode, 1)  # « local » n'est pas une version X.Y.Z
        self.assertIn("No version X.Y.Z", r.stdout)
        self.assertFalse(list((tmp / "dist").glob("*.tar")) if (tmp / "dist").exists() else [])


class InstallationHorsLigneTests(AidesHorsLigne, SimpleTestCase):
    def preparer(self, **autres):
        tmp = self.dossier()
        dossier = self.extraire(self.paquet(tmp, "9.9.1"), tmp / "serveur")
        return tmp, dossier, self.environnement_hors_ligne(tmp, **autres)

    def test_installation_sans_aucune_requete(self):
        tmp, dossier, env = self.preparer()
        r = self.lancer(["sh", "install.sh", "--offline", "probant-image-9.9.1.tar.gz", "--port", "8090"], cwd=dossier, env=env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.valeur(dossier / ".env", "IMAGE"), f"{IMAGE_PUBLIQUE}:9.9.1")
        self.assertEqual(self.valeur(dossier / ".env", "HTTP_PORT"), "8090")
        appels = [a for v, a in self.appels_docker(tmp) if not a.startswith(("save", "run "))]
        self.assertIn(f"load -i {dossier / 'probant-image-9.9.1.tar.gz'}", appels)
        self.assertIn("compose up -d --pull never", appels)
        self.assertFalse([a for a in appels if "pull web" in a or "build" in a], appels)
        self.assertEqual(self.reseau(tmp), [])
        self.assertIn("./update.sh --offline", r.stdout)

    def test_chemin_relatif_depuis_un_autre_dossier(self):
        tmp, dossier, env = self.preparer()
        r = self.lancer(["sh", "serveur/probant/install.sh", "--offline", "serveur/probant/probant-image-9.9.1.tar.gz"],
                        cwd=tmp, env=env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.valeur(dossier / ".env", "IMAGE"), f"{IMAGE_PUBLIQUE}:9.9.1")

    def test_controle_hors_ligne(self):
        """Sans PROBANT_TEST_SKIP_CHECK : le contrôle tourne, en mode hors ligne (aucun accès au registre ni à GitHub)."""
        tmp = self.dossier()
        dossier = self.extraire(self.paquet(tmp, "9.9.1"), tmp / "serveur")
        chemin, variables = preparer_faux(tmp)
        faux = tmp / "faux-hors-ligne"
        env = self.environnement(tmp, chemin=f"{faux}{os.pathsep}{chemin}", diagnostic=True, **variables)
        r = self.lancer(["sh", "install.sh", "--offline", "probant-image-9.9.1.tar.gz"], cwd=dossier, env=env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Not checked  Network: installation without Internet access", r.stdout)
        self.assertIn("Ready", r.stdout)
        self.assertFalse([x for x in self.reseau(tmp) if x.startswith(("curl", "wget"))])

    def test_fichier_modifie_refuse_avant_tout(self):
        tmp, dossier, env = self.preparer()
        with open(dossier / "docker-compose.yml", "a", encoding="utf-8") as f:
            f.write("# changed\n")
        r = self.lancer(["sh", "install.sh", "--offline", "probant-image-9.9.1.tar.gz"], cwd=dossier, env=env)
        self.assertEqual(r.returncode, 1)
        self.assertIn("do not match SHA256SUMS", r.stdout)
        self.assertFalse((dossier / ".env").exists())
        self.assertFalse([a for v, a in self.appels_docker(tmp) if not a.startswith(("save", "run "))])

    def test_archive_hors_du_paquet_refusee(self):
        tmp, dossier, env = self.preparer()
        autre = dossier / "autre.tar.gz"
        autre.write_bytes(b"\x1f\x8b")
        for archive in ("autre.tar.gz", "absente.tar.gz"):
            with self.subTest(archive):
                r = self.lancer(["sh", "install.sh", "--offline", archive], cwd=dossier, env=env)
                self.assertEqual(r.returncode, 1)
                self.assertIn("Nothing was changed", r.stdout)
                self.assertFalse((dossier / ".env").exists())

    def test_options_incompatibles(self):
        tmp, dossier, env = self.preparer()
        for options, mot in ((["--domain", "reporting.example.com"], "HTTPS proxy"), (["--image", "x:9.9.1"], "--image")):
            with self.subTest(options):
                r = self.lancer(["sh", "install.sh", "--offline", "probant-image-9.9.1.tar.gz", *options], cwd=dossier, env=env)
                self.assertEqual(r.returncode, 2)
                self.assertIn(mot, r.stdout)
                self.assertFalse((dossier / ".env").exists())
        self.assertEqual(self.lancer(["sh", "install.sh", "--offline"], cwd=dossier, env=env).returncode, 2)

    def test_docker_absent_jamais_installe_depuis_internet(self):
        tmp, dossier, env = self.preparer()
        (tmp / "faux-hors-ligne" / "docker").unlink()
        ecrire_executable(tmp / "faux-hors-ligne" / "apt-get", FAUX_RESEAU)
        r = self.lancer(["sh", "install.sh", "--offline", "probant-image-9.9.1.tar.gz", "--yes"], cwd=dossier, env=env)
        self.assertEqual(r.returncode, 1)
        self.assertIn("package", r.stdout)
        self.assertIn("mirror of your company", r.stdout)
        self.assertEqual(self.reseau(tmp), [])  # ni apt-get, ni curl
        self.assertFalse((dossier / ".env").exists())


class MiseAJourHorsLigneTests(AidesHorsLigne, SimpleTestCase):
    ENV = f"DOMAIN=10.0.0.4\nIMAGE={IMAGE_PUBLIQUE}:9.9.0\nSMTP_PASSWORD=garde\n"

    def preparer(self, version_paquet="9.9.1", env_fichier=None):
        """Installation de la version 9.9.0 (fichiers marqués), paquet ``version_paquet`` extrait dans un autre dossier."""
        tmp = self.dossier()
        dossier = tmp / "probant"
        dossier.mkdir()
        for f, contenu in version_des_fichiers("9.9.0").items():
            (dossier / f).parent.mkdir(parents=True, exist_ok=True)
            (dossier / f).write_bytes(contenu)
        shutil.copy(RACINE / "update.sh", dossier / "update.sh")  # l'update.sh de cette version-ci
        (dossier / ".env").write_text(env_fichier or self.ENV, encoding="utf-8")
        nouveau = self.extraire(self.paquet(tmp, version_paquet), tmp / "nouveau")
        (tmp / "journal.txt").write_text("", encoding="utf-8")  # le journal commence après la fabrication du paquet
        return tmp, dossier, nouveau, self.environnement_hors_ligne(tmp)

    def update(self, dossier, env, archive, *options):
        return self.lancer(["sh", "update.sh", "--offline", str(archive), *options], cwd=dossier, env=env)

    def test_mise_a_jour_sans_aucune_requete(self):
        tmp, dossier, nouveau, env = self.preparer()
        r = self.update(dossier, env, nouveau / "probant-image-9.9.1.tar.gz")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual((dossier / ".env").read_text(encoding="utf-8"), self.ENV.replace(":9.9.0", ":9.9.1"))
        for f in FICHIERS_VERSION:
            self.assertEqual((dossier / f).read_bytes(), (nouveau / f).read_bytes(), f)
        appels = self.appels_docker(tmp)
        # sauvegarde avec les fichiers et l'image installés, puis image du paquet chargée, puis démarrage sans téléchargement
        sauvegarde = next(i for i, (v, a) in enumerate(appels) if "manage.py backup" in a)
        chargement = next(i for i, (v, a) in enumerate(appels) if a.startswith("load -i "))
        self.assertEqual(appels[sauvegarde][0], "# files of version 9.9.0")
        self.assertLess(sauvegarde, chargement)
        self.assertIn(("# files of version 9.9.1", "compose up -d --pull never"), appels)
        self.assertFalse([a for v, a in appels if "pull web" in a or "build" in a])
        self.assertEqual(self.reseau(tmp), [])
        self.assertIn(f"Image before the update: {IMAGE_PUBLIQUE}:9.9.0", r.stdout)

    def test_chemin_relatif(self):
        tmp, dossier, nouveau, env = self.preparer()
        r = self.update(dossier, env, "../nouveau/probant/probant-image-9.9.1.tar.gz")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.valeur(dossier / ".env", "IMAGE"), f"{IMAGE_PUBLIQUE}:9.9.1")

    def test_version_plus_ancienne_refusee_avant_tout(self):
        tmp, dossier, nouveau, env = self.preparer(version_paquet="9.8.5")
        r = self.update(dossier, env, nouveau / "probant-image-9.8.5.tar.gz")
        self.assertEqual(r.returncode, 1)
        self.assertIn("older than the installed version 9.9.0", r.stdout)
        self.assertEqual(self.appels_docker(tmp), [])
        self.assertEqual((dossier / ".env").read_text(encoding="utf-8"), self.ENV)

    def test_paquet_abime_refuse_avant_tout(self):
        tmp, dossier, nouveau, env = self.preparer()
        archive = nouveau / "probant-image-9.9.1.tar.gz"
        archive.write_bytes(archive.read_bytes() + b"x")
        r = self.update(dossier, env, archive)
        self.assertEqual(r.returncode, 1)
        self.assertIn("do not match SHA256SUMS", r.stdout)
        self.assertEqual(self.appels_docker(tmp), [])
        self.assertEqual((dossier / "docker-compose.yml").read_bytes(), version_des_fichiers("9.9.0")["docker-compose.yml"])

    def test_image_qui_ne_se_charge_pas_fichiers_inchanges(self):
        """L'image du paquet se charge avant que ses fichiers prennent la place des fichiers installés."""
        tmp, dossier, nouveau, env = self.preparer()
        env["F_LOAD_ECHOUE"] = "1"
        r = self.update(dossier, env, nouveau / "probant-image-9.9.1.tar.gz")
        self.assertNotEqual(r.returncode, 0)
        for f in FICHIERS_VERSION:
            if f != "update.sh":
                self.assertEqual((dossier / f).read_bytes(), version_des_fichiers("9.9.0")[f], f)
        self.assertEqual((dossier / ".env").read_text(encoding="utf-8"), self.ENV)
        self.assertFalse([a for v, a in self.appels_docker(tmp) if a.startswith("compose up")])

    def test_refus(self):
        tmp, dossier, nouveau, env = self.preparer()
        archive = nouveau / "probant-image-9.9.1.tar.gz"
        r = self.update(dossier, env, archive, "--version", "9.9.1")
        self.assertEqual(r.returncode, 2)
        (dossier / ".git").mkdir()
        r = self.update(dossier, env, archive)
        self.assertEqual(r.returncode, 2)
        self.assertIn("Git clone", r.stdout)
        self.assertEqual(self.appels_docker(tmp), [])
        self.assertEqual((dossier / ".env").read_text(encoding="utf-8"), self.ENV)

    def test_installation_construite_passe_a_l_image_du_paquet(self):
        """Une installation sans image réglée (IMAGE= vide) passe elle aussi à l'image du paquet, sans rien construire."""
        tmp, dossier, nouveau, env = self.preparer(env_fichier="IMAGE=\n")
        r = self.update(dossier, env, nouveau / "probant-image-9.9.1.tar.gz")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.valeur(dossier / ".env", "IMAGE"), f"{IMAGE_PUBLIQUE}:9.9.1")
        self.assertFalse([a for v, a in self.appels_docker(tmp) if "build" in a])


class ScriptsTests(SimpleTestCase):
    def test_meme_liste_de_fichiers_et_memes_fonctions(self):
        import re
        script = (RACINE / "docker" / "make_offline_package.sh").read_text(encoding="utf-8")
        liste = re.search(r'^FILES="([^"]+)"$', script, re.M).group(1).split()
        self.assertEqual(tuple(liste), FICHIERS_VERSION)
        install = (RACINE / "install.sh").read_text(encoding="utf-8")
        update = (RACINE / "update.sh").read_text(encoding="utf-8")
        for fonction in ("check_package() {", "load_image() {"):
            bloc = install[install.index(fonction):]
            bloc = bloc[:bloc.index("\n}\n") + 3]
            self.assertIn(bloc, update, fonction)

    def test_essai_reel_dans_la_tache_docker(self):
        from parametres.test_workflows_publics import tache
        bloc = tache("tests.yml", "docker")
        etape = bloc[bloc.index("Installation without Internet access"):]
        etape = etape[:etape.index("- name:")]
        self.assertIn("if: matrix.database == 'sqlite'", etape)
        self.assertIn("bash docker/test_offline.sh", etape)
        self.assertTrue(os.access(RACINE / "docker" / "test_offline.sh", os.X_OK))

    def test_paquet_de_chaque_version_dans_image_yml(self):
        """Le workflow de l'image ne tourne que sur GitHub : sa partie « paquet hors ligne » est relue ici."""
        from parametres.test_workflows_publics import tache
        bloc = tache("image.yml", "offline-package")
        self.assertIn("needs: test-and-publish", bloc)
        self.assertIn('docker pull "$REF"', bloc)  # l'image publiée, par son empreinte
        self.assertIn('bash docker/make_offline_package.sh "$IMAGE:$VERSION" dist', bloc)
        self.assertIn("2147483648", bloc)  # taille d'un fichier d'une release : 2 Gio au plus
        self.assertIn('cosign sign-blob --yes --bundle "$PACKAGE.sigstore.json" "$PACKAGE"', bloc)
        # vérifiée en ligne, puis sans aucun réseau avec la racine de confiance de Sigstore
        self.assertIn('cosign verify-blob --bundle "$PACKAGE.sigstore.json"', bloc)
        self.assertIn('sudo unshare --net -- "$(command -v cosign)" verify-blob --trusted-root "$ROOT"', bloc)
        self.assertIn("name: probant-offline-package", bloc)
        self.assertIn("id-token: write", bloc)
        joindre = tache("image.yml", "attach-reports")
        self.assertIn("needs: [test-and-publish, offline-package]", joindre)
        self.assertIn("pattern: probant-*", joindre)
        self.assertIn("--pattern 'probant-*'", joindre)
        self.assertIn('find reports -type f -print0 | xargs -0 gh release upload "$TAG"', joindre)
