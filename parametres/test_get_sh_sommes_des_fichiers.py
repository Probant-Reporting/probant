"""``get.sh`` : chaque fichier téléchargé depuis l'étiquette d'une version est vérifié par son empreinte SHA-256, contre la
liste jointe à la release de cette version (``probant-X.Y.Z-files.sha256``), avant d'être mis à sa place ; la signature
de la liste est vérifiée quand c'est possible (cosign de la machine, ou son conteneur officiel si Docker répond).

Une liste absente, une signature refusée ou un seul fichier qui ne correspond pas : rien n'est installé. Joué avec le vrai
``curl`` contre une copie locale du dépôt (``PROBANT_TEST_SOURCE``), un faux ``docker`` qui note chaque appel et joue le
conteneur de cosign, et une signature factice (``aides_tests/scripts_installation.py``) : une liste changée après sa
signature est refusée. L'essai réel, avec Docker et le vrai cosign (clé de test) : ``docker/test_get.sh``."""
import re

from django.test import SimpleTestCase

from parametres.aides_tests.scripts_installation import (
    FICHIERS_LISTE, FICHIERS_VERSION, RACINE, AidesScripts, chemin_sans, liste_des_sommes, nom_liste, release_de,
    version_des_fichiers)

IDENTITE = r"^https://github\.com/Probant-Reporting/probant/\.github/workflows/image\.yml@refs/tags/[vV]9\.9\.1$"


class GetShSommesTests(AidesScripts, SimpleTestCase):
    def preparer(self, fichiers=None, releases=None, **autres):
        """Dépôt factice : la version 9.9.1 (étiquette V9.9.1, comme une étiquette publiée), ses fichiers ``fichiers`` ;
        sa release : ``releases`` (par défaut, la liste des sommes des fichiers et sa signature)."""
        fichiers = fichiers or version_des_fichiers("9.9.1")
        tmp = self.dossier()
        depot = self.depot({"V9.9.1": fichiers}, "V9.9.1", None if releases is None else {"V9.9.1": releases})
        return tmp, depot, self.environnement(tmp, depot, **autres)

    def get_sh(self, tmp, env, *options):
        return self.lancer(["sh", str(RACINE / "get.sh"), *options], cwd=tmp, env=env)

    def appels_docker(self, tmp):
        return [a.split("|", 1)[1] for a in self.appels(tmp) if not a.startswith("cosign|")]

    def assertRienInstalle(self, tmp, r):
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("Nothing was installed.", r.stdout)
        self.assertEqual([p.name for p in (tmp / "probant").iterdir()], [], "aucun fichier laissé")
        self.assertFalse([a for a in self.appels_docker(tmp) if a.startswith("compose")], "install.sh n'a pas tourné")

    def test_fichiers_verifies_et_signature_par_le_conteneur_de_cosign(self):
        tmp, depot, env = self.preparer()
        r = self.get_sh(tmp, env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for f in FICHIERS_VERSION:
            self.assertEqual((tmp / "probant" / f).read_bytes(), version_des_fichiers("9.9.1")[f], f)
        self.assertIn(f"/releases/download/V9.9.1/{nom_liste('9.9.1')}", depot.demandes)
        self.assertIn(f"/releases/download/V9.9.1/{nom_liste('9.9.1')}.sigstore.json", depot.demandes)
        self.assertIn("Files checked: each one matches its SHA-256 sum in the list of the release; signature of the list "
                      "verified (workflow image.yml of Probant-Reporting/probant, tag V9.9.1).", r.stdout)
        verification = [a for a in self.appels_docker(tmp) if " verify-blob " in f" {a} "]
        self.assertEqual(len(verification), 1, self.appels_docker(tmp))
        appel = verification[0].split()
        image = appel[appel.index("verify-blob") - 1]
        self.assertRegex(image, r"^ghcr\.io/sigstore/cosign/cosign:v[0-9.]+@sha256:[0-9a-f]{64}$")
        self.assertEqual(appel[appel.index("--certificate-identity-regexp") + 1], IDENTITE)
        self.assertEqual(appel[appel.index("--certificate-oidc-issuer") + 1], "https://token.actions.githubusercontent.com")
        for option in ("--read-only", "--cap-drop", "--rm", "--user"):
            self.assertIn(option, appel)
        self.assertNotIn("--key", appel)
        # la racine de confiance de Sigstore est lue d'abord ; la vérification vient avant install.sh
        appels = self.appels_docker(tmp)
        self.assertTrue(appels.index(next(a for a in appels if a.endswith(" initialize"))) < appels.index(verification[0])
                        < appels.index("compose pull web"))

    def test_cosign_de_la_machine_d_abord(self):
        tmp, depot, env = self.preparer()
        self.ajouter_faux_cosign(tmp / "faux-bin")
        r = self.get_sh(tmp, env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        cosign = [a for a in self.appels(tmp) if a.startswith("cosign|")]
        self.assertEqual([a.split("|")[1].split()[0] for a in cosign], ["initialize", "verify-blob"])
        self.assertIn(IDENTITE, cosign[1])
        self.assertFalse([a for a in self.appels_docker(tmp) if "verify-blob" in a], "pas de conteneur avec cosign présent")
        self.assertIn("signature of the list verified", r.stdout)

    def test_un_fichier_change_rien_n_est_installe(self):
        for fichier in ("install.sh", "docker/Caddyfile", "VERSION"):
            with self.subTest(fichier):
                change = version_des_fichiers("9.9.1")
                liste = liste_des_sommes(change)
                if fichier == "VERSION":  # même numéro lu par le script, octets différents de ceux de la liste
                    change["VERSION"] = b"9.9.1"
                else:
                    change[fichier] += b"\necho piege\n"
                tmp, depot, env = self.preparer(change, release_de(version_des_fichiers("9.9.1"), liste))
                r = self.get_sh(tmp, env)
                self.assertRienInstalle(tmp, r)
                self.assertIn(f"{fichier} does not match its SHA-256 sum in {nom_liste('9.9.1')}", r.stdout)

    def test_fichier_absent_de_la_liste_refuse(self):
        fichiers = version_des_fichiers("9.9.1")
        liste = b"".join(x + b"\n" for x in liste_des_sommes(fichiers).splitlines() if not x.endswith(b"  check.sh"))
        tmp, depot, env = self.preparer(fichiers, release_de(fichiers, liste))
        r = self.get_sh(tmp, env)
        self.assertRienInstalle(tmp, r)
        self.assertIn(f"check.sh is not in the list of sums {nom_liste('9.9.1')}.", r.stdout)

    def test_fichier_facultatif_de_la_liste_absent_refuse(self):
        """La liste nomme auto-update.sh, mais l'étiquette ne l'a pas : un fichier de la version manque."""
        fichiers = version_des_fichiers("9.9.1")
        liste = liste_des_sommes({**fichiers, "auto-update.sh": (RACINE / "auto-update.sh").read_bytes()})
        tmp, depot, env = self.preparer(fichiers, release_de(fichiers, liste))
        r = self.get_sh(tmp, env)
        self.assertRienInstalle(tmp, r)
        self.assertIn("auto-update.sh is in the list of sums", r.stdout)

    def test_liste_ou_signature_absente_rien_n_est_installe(self):
        fichiers = version_des_fichiers("9.9.1")
        complete = release_de(fichiers)
        for garde in ({}, {nom_liste("9.9.1"): complete[nom_liste("9.9.1")]}):
            with self.subTest(sorted(garde)):
                tmp, depot, env = self.preparer(fichiers, garde)
                r = self.get_sh(tmp, env)
                self.assertRienInstalle(tmp, r)
                self.assertIn("The release of version 9.9.1 has no list of the SHA-256 sums of its files", r.stdout)
                self.assertIn("try again later", r.stdout)

    def test_liste_changee_apres_sa_signature_refusee(self):
        """La liste et un fichier changés ensemble (les sommes correspondent) : la signature de la liste est refusée."""
        fichiers = version_des_fichiers("9.9.1")
        signee = release_de(fichiers)
        change = {**fichiers, "install.sh": fichiers["install.sh"] + b"\necho piege\n"}
        releases = {nom_liste("9.9.1"): liste_des_sommes(change),
                    f"{nom_liste('9.9.1')}.sigstore.json": signee[f"{nom_liste('9.9.1')}.sigstore.json"]}
        for cosign_machine in (False, True):
            with self.subTest(cosign_machine=cosign_machine):
                tmp, depot, env = self.preparer(change, releases)
                if cosign_machine:
                    self.ajouter_faux_cosign(tmp / "faux-bin")
                r = self.get_sh(tmp, env)
                self.assertRienInstalle(tmp, r)
                self.assertIn("The signature of the list of the SHA-256 sums of version 9.9.1 was refused by cosign", r.stdout)

    def test_signature_impossible_a_verifier_sommes_verifiees_quand_meme(self):
        """Cosign ne lit pas la racine de confiance de Sigstore (réseau), ou son conteneur ne se télécharge pas : la
        signature n'est pas vérifiée, et le message le dit ; les sommes le sont, et la version s'installe."""
        for reglage, raison in (({"FAUX_COSIGN_INIT_RC": "1"}, "cosign could not read the trusted root of Sigstore"),):
            with self.subTest(raison):
                tmp, depot, env = self.preparer(**reglage)
                r = self.get_sh(tmp, env)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertIn(f"signature of the list not verified: {raison}", r.stdout)
                self.assertFalse([a for a in self.appels_docker(tmp) if "verify-blob" in a])
        # même sans vérification de la signature, un fichier changé est refusé
        change = version_des_fichiers("9.9.1")
        liste = liste_des_sommes(change)
        change["update.sh"] += b"\n"
        tmp, depot, env = self.preparer(change, release_de(version_des_fichiers("9.9.1"), liste), FAUX_COSIGN_INIT_RC="1")
        self.assertRienInstalle(tmp, self.get_sh(tmp, env))

    def test_sans_cosign_ni_docker_sommes_verifiees(self):
        """Serveur neuf, sans Docker ni cosign : seule la vérification des sommes est possible ; --check le montre sans
        rien installer (install.sh proposerait d'installer Docker)."""
        tmp, depot, env = self.preparer()
        env["PATH"] = str(chemin_sans(tmp / "sans-docker", {"docker", "cosign"}))
        r = self.get_sh(tmp, env, "--check")
        self.assertIn("signature of the list not verified: no cosign and no Docker on this server", r.stdout)
        self.assertIn("Files checked", r.stdout)

    def test_controle_du_serveur_verifie_avant_de_lancer_check_sh(self):
        change = version_des_fichiers("9.9.1")
        liste = liste_des_sommes(change)
        change["check.sh"] = b"#!/bin/sh\necho CHECK-PIEGE\nexit 0\n"
        tmp, depot, env = self.preparer(change, release_de(version_des_fichiers("9.9.1"), liste), diagnostic=True)
        r = self.get_sh(tmp, env, "--check")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertNotIn("CHECK-PIEGE", r.stdout)
        self.assertIn("check.sh does not match its SHA-256 sum", r.stdout)
        self.assertIn("The check of the server was not run.", r.stdout)
        self.assertFalse((tmp / "probant").exists())

    def test_version_d_avant_les_listes_refusee(self):
        """Une version publiée avant les listes (rien dans sa release) : refusée, sans repli silencieux."""
        tmp, depot, env = self.preparer(releases={})
        r = self.get_sh(tmp, env, "--version", "9.9.1")
        self.assertRienInstalle(tmp, r)
        self.assertIn("A version published before these lists cannot be installed this way.", r.stdout)

    def test_variables_de_test_de_cosign_ignorees_hors_du_depot_de_test(self):
        """La clé et l'image de cosign de test ne valent qu'avec PROBANT_TEST_SOURCE : la liste du dépôt public est
        toujours vérifiée avec l'identité du dépôt public (le texte est lu ici)."""
        t = (RACINE / "get.sh").read_text(encoding="utf-8")
        bloc = t[t.index('TEST_KEY=""\n'):t.index("# download_sums VERSION FOLDER")]
        self.assertIn('if [ -n "${PROBANT_TEST_SOURCE:-}" ]; then', bloc)
        self.assertIn('TEST_KEY="${PROBANT_TEST_COSIGN_KEY:-}"', bloc)
        self.assertEqual(bloc.count("PROBANT_TEST_COSIGN_"), 2)

    def test_cle_de_test_avec_le_depot_de_test(self):
        tmp, depot, env = self.preparer(PROBANT_TEST_COSIGN_KEY=str(RACINE / "VERSION"), PROBANT_TEST_COSIGN_IMAGE="cosign-essai:1")
        r = self.get_sh(tmp, env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        appel = [a for a in self.appels_docker(tmp) if "verify-blob" in a][0].split()
        self.assertIn("cosign-essai:1", appel)
        self.assertEqual(appel[appel.index("--key") + 1], "/run/probant-test.pub")
        self.assertNotIn("--certificate-identity-regexp", appel)
        self.assertFalse([a for a in self.appels_docker(tmp) if a.endswith(" initialize")], "clé de test : pas de racine")


class TexteDesSommesTests(SimpleTestCase):
    """Les fonctions des sommes sont recopiées dans get.sh et update.sh (chaque script reste autonome) : elles restent
    identiques ; la liste couvre tous les fichiers que les scripts téléchargent ; le même cosign partout."""

    @staticmethod
    def bloc(nom, debut, fin):
        t = (RACINE / nom).read_text(encoding="utf-8")
        i = t.index(debut)
        j = t.index(fin, i) + len(fin)
        return t[i:j]

    def test_fonctions_identiques(self):
        debut, fin = "# ---- SHA-256 sums of the files of a version", 'signature of the list $signature."\n}\n'
        self.assertEqual(self.bloc("get.sh", debut, fin), self.bloc("update.sh", debut, fin))
        self.assertGreater(self.bloc("update.sh", debut, fin).count("\n"), 80)

    def test_meme_image_de_cosign_dans_les_trois_scripts(self):
        images = {nom: re.search(r'^COSIGN_IMAGE="([^"]+)"$', (RACINE / nom).read_text(encoding="utf-8"), re.M).group(1)
                  for nom in ("get.sh", "update.sh", "auto-update.sh")}
        self.assertEqual(len(set(images.values())), 1, images)
        self.assertRegex(images["get.sh"], r"^ghcr\.io/sigstore/cosign/cosign:v[0-9.]+@sha256:[0-9a-f]{64}$")

    def test_la_liste_couvre_les_fichiers_telecharges(self):
        script = (RACINE / "docker" / "make_file_sums.sh").read_text(encoding="utf-8")
        liste = tuple(re.search(r'^FILES="([^"]+)"$', script, re.M).group(1).split())
        self.assertEqual(liste, FICHIERS_LISTE)
        for nom in ("get.sh", "update.sh", "auto-update.sh"):
            t = (RACINE / nom).read_text(encoding="utf-8")
            telecharges = re.search(r'^FILES="([^"]+)"$', t, re.M).group(1).split()
            facultatifs = re.search(r'^OPTIONAL_FILES="([^"]+)"$', t, re.M)
            telecharges += facultatifs.group(1).split() if facultatifs else []
            self.assertLessEqual(set(telecharges) | {"VERSION"}, set(liste), nom)

    def test_liste_faite_par_le_script(self):
        """docker/make_file_sums.sh donne la liste que les scripts lisent (format de sha256sum), pour les fichiers d'un
        dossier de code donné."""
        import shutil
        import subprocess
        import tempfile
        from pathlib import Path

        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        code = tmp / "code"
        fichiers = {**version_des_fichiers("9.9.1"), "get.sh": b"get\n", "auto-update.sh": b"auto\n"}
        for f, contenu in fichiers.items():
            (code / f).parent.mkdir(parents=True, exist_ok=True)
            (code / f).write_bytes(contenu)
        r = subprocess.run(["bash", str(RACINE / "docker" / "make_file_sums.sh"), str(tmp / "sortie"), str(code)],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual((tmp / "sortie" / nom_liste("9.9.1")).read_bytes(), liste_des_sommes(fichiers))

    def test_liste_signee_et_jointe_par_image_yml(self):
        """Le workflow de l'image ne tourne que sur GitHub : sa partie « liste des sommes » est relue ici."""
        from parametres.test_workflows_publics import tache
        bloc = tache("image.yml", "test-and-publish")
        etapes = bloc[bloc.index("name: List of the SHA-256 sums of the files (signed)"):]
        etapes = etapes[:etapes.index("name: Known vulnerabilities")]
        self.assertEqual(etapes.count("if: github.ref_type == 'tag'"), 3, "étiquettes seulement : identité du tag")
        self.assertIn("bash docker/make_file_sums.sh sums", etapes)
        self.assertIn('cosign sign-blob --yes --bundle "$LIST.sigstore.json" "$LIST"', etapes)
        # vérifiée comme les scripts la vérifient : conteneur épinglé de auto-update.sh, utilisateur du runner
        self.assertIn("""COSIGN_IMAGE="$(sed -n 's/^COSIGN_IMAGE="\\(.*\\)"$/\\1/p' auto-update.sh)\"""", etapes)
        self.assertIn('--user "$(id -u):$(id -g)" -e HOME=/tmp -v "$PWD/sums:/work:ro" "$COSIGN_IMAGE" verify-blob', etapes)
        self.assertIn(r"/\\.github/workflows/image\\.yml@refs/tags/[vV]${V_RE}\$", etapes)
        self.assertIn('sha256sum -c --strict "sums/probant-$VERSION-files.sha256"', etapes)
        self.assertIn("name: probant-file-sums", etapes)
        self.assertIn("id-token: write", bloc)
        joindre = tache("image.yml", "attach-reports")
        self.assertIn("pattern: probant-*", joindre)
        self.assertIn("--pattern 'probant-*'", joindre)
