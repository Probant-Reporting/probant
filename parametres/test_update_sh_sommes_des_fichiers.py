"""``update.sh`` d'une installation faite par ``get.sh`` : les fichiers de la nouvelle version sont vérifiés par leur
empreinte SHA-256 contre la liste de sa release (et la signature de la liste, quand c'est possible) avant d'être mis à
leur place. Un refus (liste absente, signature refusée, un fichier qui ne correspond pas) : rien n'est remplacé, ni
``.env``, ni l'image, code de sortie 3. Avec ``--sums`` (``auto-update.sh``) : la liste donnée, dont la tâche a vérifié la
signature, et rien d'autre n'est téléchargé de la release. Joué avec le vrai ``curl`` contre un dépôt factice et un faux
``docker`` (``aides_tests/scripts_installation.py``)."""
import shutil

from django.test import SimpleTestCase

from parametres.aides_tests.scripts_installation import (
    FICHIERS_VERSION, IMAGE_PUBLIQUE, RACINE, AidesScripts, liste_des_sommes, nom_liste, release_de, version_des_fichiers)

ENV = f"DOMAIN=reporting.example.com\nIMAGE={IMAGE_PUBLIQUE}:9.9.0\nSMTP_PASSWORD=garde\n"


class MiseAJourSommesTests(AidesScripts, SimpleTestCase):
    def preparer(self, fichiers=None, releases=None, **autres):
        """Installation de la version 9.9.0 ; dépôt factice avec la version 9.9.1 (``fichiers``) et sa release."""
        tmp = self.dossier()
        for f, contenu in version_des_fichiers("9.9.0").items():
            if f != "VERSION":
                (tmp / f).parent.mkdir(parents=True, exist_ok=True)
                (tmp / f).write_bytes(contenu)
        shutil.copy(RACINE / "update.sh", tmp / "update.sh")
        (tmp / ".env").write_text(ENV, encoding="utf-8")
        fichiers = fichiers or version_des_fichiers("9.9.1")
        depot = self.depot({"v9.9.0": version_des_fichiers("9.9.0"), "v9.9.1": fichiers}, "v9.9.1",
                           None if releases is None else {"v9.9.1": releases})
        return tmp, depot, self.environnement(tmp, depot, **autres)

    def update(self, tmp, env, *options):
        return self.lancer(["sh", "update.sh", *options], cwd=tmp, env=env)

    def assertRienChange(self, tmp, r):
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertIn("Nothing was changed.", r.stdout)
        self.assertEqual((tmp / ".env").read_text(encoding="utf-8"), ENV)
        for f in FICHIERS_VERSION:
            if f != "update.sh":
                self.assertEqual((tmp / f).read_bytes(), version_des_fichiers("9.9.0")[f], f)
        self.assertEqual((tmp / "update.sh").read_bytes(), (RACINE / "update.sh").read_bytes())
        appels = [a.split("|", 1)[1] for a in self.appels(tmp)]
        self.assertFalse([a for a in appels if a in ("compose pull web", "compose up -d")], appels)
        self.assertFalse(list(tmp.glob(".download*")), "dossier de téléchargement laissé")

    def test_fichiers_verifies_puis_mis_en_place(self):
        tmp, depot, env = self.preparer()
        r = self.update(tmp, env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Files checked: each one matches its SHA-256 sum in the list of the release; signature of the list "
                      "verified (workflow image.yml of Probant-Reporting/probant, tag v9.9.1).", r.stdout)
        for f in FICHIERS_VERSION:
            self.assertEqual((tmp / f).read_bytes(), version_des_fichiers("9.9.1")[f], f)
        self.assertEqual(self.valeur(tmp / ".env", "IMAGE"), f"{IMAGE_PUBLIQUE}:9.9.1")
        appels = [a.split("|", 1)[1] for a in self.appels(tmp)]
        verification = [a for a in appels if "verify-blob" in a]
        self.assertEqual(len(verification), 1)
        # les autorités de l'entreprise (certificates/ca) sont données au conteneur de cosign quand le dossier existe
        self.assertNotIn("/etc/probant/ca:ro", verification[0])
        self.assertLess(appels.index(verification[0]), appels.index("compose pull web"))

    def test_autorites_de_l_entreprise_pour_le_conteneur_de_cosign(self):
        tmp, depot, env = self.preparer()
        (tmp / "certificates" / "ca").mkdir(parents=True)
        r = self.update(tmp, env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        verification = [a for a in self.appels(tmp) if "verify-blob" in a][0]
        self.assertIn(f"-v {tmp}/certificates/ca:/etc/probant/ca:ro", verification)

    def test_un_fichier_change_rien_n_est_remplace(self):
        """Le dernier fichier téléchargé est faux : aucun des autres n'a été mis en place avant."""
        for fichier in ("docker-compose.yml", "docker/Caddyfile", "update.sh"):
            with self.subTest(fichier):
                change = version_des_fichiers("9.9.1")
                liste = liste_des_sommes(change)
                change[fichier] += b"\n# piege\n"
                tmp, depot, env = self.preparer(change, release_de(version_des_fichiers("9.9.1"), liste))
                r = self.update(tmp, env)
                self.assertRienChange(tmp, r)
                self.assertIn(f"{fichier} does not match its SHA-256 sum in {nom_liste('9.9.1')}", r.stdout)

    def test_liste_absente_rien_ne_change(self):
        for releases in ({}, {nom_liste("9.9.1"): liste_des_sommes(version_des_fichiers("9.9.1"))}):
            with self.subTest(sorted(releases)):
                tmp, depot, env = self.preparer(releases=releases)
                r = self.update(tmp, env)
                self.assertRienChange(tmp, r)
                self.assertIn("has no list of the SHA-256 sums of its files", r.stdout)

    def test_liste_changee_apres_sa_signature_rien_ne_change(self):
        fichiers = version_des_fichiers("9.9.1")
        signee = release_de(fichiers)
        change = {**fichiers, "install.sh": fichiers["install.sh"] + b"\n# piege\n"}
        releases = {nom_liste("9.9.1"): liste_des_sommes(change),
                    f"{nom_liste('9.9.1')}.sigstore.json": signee[f"{nom_liste('9.9.1')}.sigstore.json"]}
        tmp, depot, env = self.preparer(change, releases)
        r = self.update(tmp, env)
        self.assertRienChange(tmp, r)
        self.assertIn("was refused by cosign", r.stdout)

    def test_racine_de_sigstore_injoignable_sommes_verifiees(self):
        tmp, depot, env = self.preparer(FAUX_COSIGN_INIT_RC="1")
        r = self.update(tmp, env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("signature of the list not verified: cosign could not read the trusted root of Sigstore", r.stdout)
        self.assertEqual(self.valeur(tmp / ".env", "IMAGE"), f"{IMAGE_PUBLIQUE}:9.9.1")

    def test_meme_version_rien_a_verifier(self):
        """Déjà la dernière version : rien n'est téléchargé, donc rien n'est vérifié (le redémarrage reste)."""
        tmp, depot, env = self.preparer(releases={})
        env_fichier = ENV.replace(":9.9.0", ":9.9.1")
        (tmp / ".env").write_text(env_fichier, encoding="utf-8")
        r = self.update(tmp, env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse([d for d in depot.demandes if d.startswith("/releases/download/")])

    # ---- --sums : la liste vérifiée par auto-update.sh
    def liste_donnee(self, tmp, fichiers):
        chemin = tmp / "liste-verifiee.sha256"
        chemin.write_bytes(liste_des_sommes(fichiers))
        return chemin

    def test_liste_donnee_par_auto_update(self):
        tmp, depot, env = self.preparer(releases={})
        liste = self.liste_donnee(tmp, version_des_fichiers("9.9.1"))
        r = self.update(tmp, env, "--version", "9.9.1", "--sums", str(liste))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("files checked: each one matches its SHA-256 sum in the list verified by auto-update.sh", r.stdout)
        self.assertFalse([d for d in depot.demandes if d.startswith("/releases/download/")], "liste non retéléchargée")
        self.assertFalse([a for a in self.appels(tmp) if "verify-blob" in a], "signature déjà vérifiée par la tâche")
        self.assertEqual(self.valeur(tmp / ".env", "IMAGE"), f"{IMAGE_PUBLIQUE}:9.9.1")

    def test_liste_donnee_fichier_change_ou_autre_version(self):
        change = version_des_fichiers("9.9.1")
        change["check.sh"] += b"\n"
        cas = {"fichier changé": (change, version_des_fichiers("9.9.1")),
               "liste d'une autre version": (version_des_fichiers("9.9.1"), version_des_fichiers("9.9.2"))}
        for nom, (servis, listes) in cas.items():
            with self.subTest(nom):
                tmp, depot, env = self.preparer(servis, releases={})
                liste = self.liste_donnee(tmp, listes)
                r = self.update(tmp, env, "--version", "9.9.1", "--sums", str(liste))
                self.assertRienChange(tmp, r)

    def test_liste_donnee_absente(self):
        tmp, depot, env = self.preparer()
        r = self.update(tmp, env, "--version", "9.9.1", "--sums", str(tmp / "absente.sha256"))
        self.assertRienChange(tmp, r)

    def test_option_sums_hors_installation_par_get_sh(self):
        tmp, depot, env = self.preparer()
        (tmp / ".git").mkdir()
        r = self.update(tmp, env, "--sums", "liste.sha256")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("--digest and --sums are for an installation made by get.sh", r.stdout)
        self.assertEqual(self.appels(tmp), [])
