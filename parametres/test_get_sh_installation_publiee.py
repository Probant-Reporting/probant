"""``get.sh`` : installation en une commande avec l'image publiée, sans Git et sans construire l'image.

Le script trouve la version (la dernière publiée, ou ``--version``), télécharge dans ``probant/`` les seuls fichiers qui
font tourner l'outil, depuis l'étiquette de la version dans le dépôt public, puis lance ``install.sh`` avec l'image
publiée de cette version. Joué ici avec le vrai ``curl`` contre une copie locale du dépôt (serveur HTTP,
``PROBANT_TEST_SOURCE``) et un faux ``docker`` qui note chaque appel."""
import re
import subprocess
from pathlib import Path

from django.test import SimpleTestCase

from parametres.aides_tests.scripts_installation import (
    FICHIERS_VERSION, IMAGE_PUBLIQUE, RACINE, AidesScripts, version_des_fichiers)


class GetShTests(AidesScripts, SimpleTestCase):
    def preparer(self, etiquettes=None, derniere="V9.9.1"):
        """Dépôt factice : v9.9.0 (étiquette en minuscule) et V9.9.1 (en majuscule, comme une étiquette publiée)."""
        etiquettes = etiquettes if etiquettes is not None else {
            "v9.9.0": version_des_fichiers("9.9.0"), "V9.9.1": version_des_fichiers("9.9.1")}
        tmp = self.dossier()
        depot = self.depot(etiquettes, derniere)
        return tmp, depot, self.environnement(tmp, depot)

    def get_sh(self, tmp, env, *options):
        return self.lancer(["sh", str(RACINE / "get.sh"), *options], cwd=tmp, env=env)

    def test_derniere_version_publiee_installee_avec_son_image(self):
        tmp, depot, env = self.preparer()
        r = self.get_sh(tmp, env, "--port", "8090")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        dossier = tmp / "probant"
        # seulement les fichiers de la version (et le .env créé par install.sh), rien d'autre (ni code, ni Dockerfile)
        presents = sorted(p.relative_to(dossier).as_posix() for p in dossier.rglob("*") if p.is_file())
        self.assertEqual(presents, sorted([*FICHIERS_VERSION, ".env"]))
        for f in FICHIERS_VERSION:
            self.assertEqual((dossier / f).read_bytes(), version_des_fichiers("9.9.1")[f], f)
        self.assertEqual(self.valeur(dossier / ".env", "IMAGE"), f"{IMAGE_PUBLIQUE}:9.9.1")
        self.assertEqual(self.valeur(dossier / ".env", "HTTP_PORT"), "8090")
        appels = [a.split("|", 1)[1] for a in self.appels(tmp)]
        self.assertIn("compose pull web", appels)
        self.assertIn("compose up -d", appels)
        self.assertFalse([a for a in appels if "build" in a], "l'image n'est jamais construite")
        self.assertIn("/releases/latest", depot.demandes)
        # étiquette vX.Y.Z essayée d'abord (absente ici), puis VX.Y.Z
        self.assertEqual(depot.fichiers_demandes()[:2], ["/raw/refs/tags/v9.9.1/VERSION", "/raw/refs/tags/V9.9.1/VERSION"])
        self.assertTrue(all("/V9.9.1/" in d for d in depot.fichiers_demandes()[1:]), depot.demandes)

    def test_dossier_sans_git_aucune_ligne_vide_qui_cache_le_commit_de_l_image(self):
        """Avant : install.sh écrivait « VERSION_COMMIT= » (vide, faute de Git) dans .env ; le fichier passant tout entier
        à l'outil, la valeur vide remplaçait le commit inscrit dans l'image publiée, et la version s'affichait sans lui."""
        tmp, depot, env = self.preparer()
        r = self.get_sh(tmp, env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIsNone(self.valeur(tmp / "probant" / ".env", "VERSION_COMMIT"))

    def test_version_demandee(self):
        tmp, depot, env = self.preparer()
        r = self.get_sh(tmp, env, "--version", "9.9.0", "--dir", "outil")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.valeur(tmp / "outil" / ".env", "IMAGE"), f"{IMAGE_PUBLIQUE}:9.9.0")
        self.assertEqual((tmp / "outil" / "docker-compose.yml").read_bytes(), version_des_fichiers("9.9.0")["docker-compose.yml"])
        self.assertNotIn("/releases/latest", depot.demandes)

    def test_par_un_tube_avec_les_options_d_install(self):
        """« curl … | sh -s -- --domain … » : le script vient par l'entrée standard ; l'option va à install.sh."""
        tmp, depot, env = self.preparer()
        texte = (RACINE / "get.sh").read_text(encoding="utf-8")
        r = self.lancer(["sh", "-s", "--", "--domain", "reporting.example.com"], cwd=tmp, env=env, entree=texte)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        env_fichier = tmp / "probant" / ".env"
        self.assertEqual(self.valeur(env_fichier, "DOMAIN"), "reporting.example.com")
        self.assertEqual(self.valeur(env_fichier, "COMPOSE_PROFILES"), "https")
        self.assertEqual(self.valeur(env_fichier, "IMAGE"), f"{IMAGE_PUBLIQUE}:9.9.1")

    def test_installation_existante_jamais_touchee(self):
        tmp, depot, env = self.preparer()
        (tmp / "probant").mkdir()
        (tmp / "probant" / ".env").write_text("DOMAIN=garde.example.com\n", encoding="utf-8")
        r = self.get_sh(tmp, env)
        self.assertEqual(r.returncode, 1)
        self.assertIn("./update.sh", r.stdout)
        self.assertEqual(depot.demandes, [])
        self.assertEqual(sorted(p.name for p in (tmp / "probant").iterdir()), [".env"])
        self.assertEqual(self.appels(tmp), [])

    def test_clone_git_jamais_touche(self):
        tmp, depot, env = self.preparer()
        (tmp / "probant" / ".git").mkdir(parents=True)
        r = self.get_sh(tmp, env)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(depot.demandes, [])

    def test_version_introuvable_rien_n_est_installe(self):
        tmp, depot, env = self.preparer()
        r = self.get_sh(tmp, env, "--version", "8.0.0")
        self.assertEqual(r.returncode, 1)
        self.assertIn("could not be downloaded", r.stdout)
        self.assertEqual([p.name for p in (tmp / "probant").iterdir()], [])
        self.assertEqual(self.appels(tmp), [])

    def test_fichier_version_d_une_autre_version_refuse(self):
        """L'étiquette doit porter la version demandée : sinon rien n'est installé."""
        fausse = version_des_fichiers("9.9.0")
        fausse["VERSION"] = b"9.9.2\n"
        tmp, depot, env = self.preparer({"v9.9.0": fausse})
        r = self.get_sh(tmp, env, "--version", "9.9.0")
        self.assertEqual(r.returncode, 1)
        self.assertFalse((tmp / "probant" / "install.sh").exists())

    def test_version_d_avant_ce_script_refusee_proprement(self):
        """Une version publiée avant get.sh : son install.sh ne connaît pas --image. Constaté contre le vrai dépôt public
        (« Unknown option: --image ») : refusée avant tout, avec un message, sans fichiers laissés."""
        ancienne = version_des_fichiers("9.8.0")
        ancienne["install.sh"] = b'#!/usr/bin/env sh\ncase "$1" in --domain) ;; --port) ;; esac\necho "Probant is running"\n'
        tmp, depot, env = self.preparer({"v9.8.0": ancienne})
        r = self.get_sh(tmp, env, "--version", "9.8.0")
        self.assertEqual(r.returncode, 1)
        self.assertIn("came before this way of installing", r.stdout)
        self.assertEqual([p.name for p in (tmp / "probant").iterdir()], [])
        self.assertEqual(self.appels(tmp), [])

    def test_aucune_version_publiee(self):
        tmp, depot, env = self.preparer(derniere=None)
        r = self.get_sh(tmp, env)
        self.assertEqual(r.returncode, 1)
        self.assertIn("--version X.Y.Z", r.stdout)
        self.assertFalse((tmp / "probant").exists())

    def test_options_refusees(self):
        tmp, depot, env = self.preparer()
        for options in (["--version"], ["--version", "1.0"], ["--inconnue"]):
            with self.subTest(options):
                r = self.get_sh(tmp, env, *options)
                self.assertEqual(r.returncode, 2, r.stdout)
        self.assertEqual(depot.demandes, [])

    def test_aide(self):
        tmp, depot, env = self.preparer()
        r = self.get_sh(tmp, env, "--help")
        self.assertEqual(r.returncode, 0)
        self.assertIn("--version X.Y.Z", r.stdout)
        self.assertEqual(depot.demandes, [])


class TexteDesScriptsTests(SimpleTestCase):
    """Les fonctions de téléchargement sont recopiées dans get.sh et update.sh (chaque script reste autonome) : elles
    restent identiques, et la liste des fichiers couvre ce que docker-compose.yml lit dans le dossier."""

    @staticmethod
    def bloc(nom, debut, fin):
        """Lignes de code de ``debut`` à ``fin`` comprise (sans commentaires ni lignes vides)."""
        t = (RACINE / nom).read_text(encoding="utf-8")
        i = t.index(debut)
        j = t.index(fin, i) + len(fin)
        return [x for x in t[i:j].splitlines() if x.strip() and not x.lstrip().startswith("#")]

    def test_fonctions_identiques(self):
        for debut, fin in (('SOURCE="${PROBANT_TEST_SOURCE', 'docker/Caddyfile"\n'), ('PROTO="=https"', "  return 1\n}\n")):
            with self.subTest(debut):
                self.assertEqual(self.bloc("get.sh", debut, fin), self.bloc("update.sh", debut, fin))
        self.assertGreater(len(self.bloc("update.sh", 'PROTO="=https"', "  return 1\n}\n")), 15)  # le bloc entier

    def test_liste_des_fichiers(self):
        for nom in ("get.sh", "update.sh"):
            t = (RACINE / nom).read_text(encoding="utf-8")
            liste = re.search(r'^FILES="([^"]+)"$', t, re.M).group(1).split()
            self.assertEqual(tuple(liste), FICHIERS_VERSION, nom)
        for f in FICHIERS_VERSION:
            self.assertTrue((RACINE / f).is_file(), f)
        # fichiers du dossier lus par docker-compose.yml (montages « ./… ») : tous téléchargés
        compose = (RACINE / "docker-compose.yml").read_text(encoding="utf-8")
        montages = {m for m in re.findall(r"- \./([\w./-]+):", compose)}
        self.assertTrue(montages)
        # sauf les dossiers des certificats donnés par l'IT : créés (vides) par install.sh et update.sh, jamais téléchargés
        dossiers = {"certificates/ca", "certificates/https"}
        self.assertLessEqual(montages - dossiers, set(FICHIERS_VERSION))
        install = (RACINE / "install.sh").read_text(encoding="utf-8")
        for ligne in ("make_folder certificates/ca 755", "make_folder certificates/https 700"):
            self.assertIn(ligne, install)
        self.assertIn("for d in certificates certificates/ca certificates/https; do", (RACINE / "update.sh").read_text(encoding="utf-8"))

    def test_image_et_depot_publics(self):
        for nom in ("get.sh", "update.sh"):
            t = (RACINE / nom).read_text(encoding="utf-8")
            self.assertIn('SOURCE="${PROBANT_TEST_SOURCE:-https://github.com/Probant-Reporting/probant}"', t)
            self.assertIn(f'IMAGE_NAME="${{PROBANT_TEST_IMAGE:-{IMAGE_PUBLIQUE}}}"', t)
            # HTTPS seulement, redirections comprises, hors essais
            self.assertIn('PROTO="=https"', t)
            self.assertIn('--proto "$PROTO" --proto-redir "$PROTO"', t)

    def test_posix_et_executable(self):
        for nom in ("get.sh", "install.sh", "update.sh"):
            with self.subTest(nom):
                self.assertEqual(subprocess.run(["sh", "-n", str(RACINE / nom)]).returncode, 0)
                self.assertTrue(Path(RACINE / nom).stat().st_mode & 0o111)

    def test_essai_reel_dans_la_tache_docker(self):
        """L'essai de bout en bout (docker/test_get.sh) tourne dans la tâche Docker de tests.yml, une fois (SQLite),
        avec l'image construite par install.sh juste avant (nom par défaut de docker-compose.yml)."""
        from parametres.test_workflows_publics import tache
        bloc = tache("tests.yml", "docker")
        etape = bloc[bloc.index("One-line installation (get.sh)"):]
        etape = etape[:etape.index("- name:")]
        self.assertIn("if: matrix.database == 'sqlite'", etape)
        image = re.search(r"\$\{IMAGE:-([^}]+)\}", (RACINE / "docker-compose.yml").read_text(encoding="utf-8")).group(1)
        self.assertIn(f"run: IMAGE_UNDER_TEST={image} bash docker/test_get.sh", etape)
        self.assertLess(bloc.index("./update.sh"), bloc.index("docker/test_get.sh"))
        self.assertTrue((RACINE / "docker" / "test_get.sh").is_file())
