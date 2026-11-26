"""``install.sh --auto-update on|off`` : la minuterie de la machine qui lance ``auto-update.sh`` chaque nuit (systemd, sinon
cron du système ou de la personne), posée par ``get.sh`` pour une installation neuve (avec le choix « automatique » dans
l'outil) ; et ce qu'en attendent ``get.sh`` et ``update.sh`` (fichier ``auto-update.sh`` de chaque version, image
épinglée par ``--digest``, verrou commun). Joué avec des faux ``docker``, ``systemctl`` et ``crontab`` : aucune vraie
commande d'administration ne part."""
import re

from django.test import SimpleTestCase

from parametres.aides_tests.scripts_installation import (
    IMAGE_PUBLIQUE, RACINE, AidesScripts, ecrire_executable, version_des_fichiers)

FAUX_SYSTEMCTL = '#!/bin/sh\necho "systemctl $*" >> "$JOURNAL"\n'
FAUX_CRONTAB = """#!/bin/sh
# faux crontab : la table de la personne dans $CRONTAB_FICHIER
echo "crontab $*" >> "$JOURNAL"
case "$1" in
  -l) [ -f "$CRONTAB_FICHIER" ] && cat "$CRONTAB_FICHIER" || exit 1 ;;
  -) cat > "$CRONTAB_FICHIER.tmp" && mv "$CRONTAB_FICHIER.tmp" "$CRONTAB_FICHIER" ;;  # comme crontab : lu entier, puis remplacé
esac
"""
EMPREINTE = "sha256:" + "c" * 64


def fichiers_avec_auto(version):
    return {**version_des_fichiers(version), "auto-update.sh": (RACINE / "auto-update.sh").read_bytes()}


class InstallShMinuterieTests(AidesScripts, SimpleTestCase):
    def preparer(self, image=f"{IMAGE_PUBLIQUE}:9.9.0", existante=True, uid="0", systemd=True, cron=True, crontab=True,
                 nom="probant"):
        tmp = self.dossier()
        dossier = tmp / nom
        (dossier / "docker").mkdir(parents=True)
        for f, contenu in fichiers_avec_auto("9.9.0").items():
            if f != "VERSION":
                (dossier / f).write_bytes(contenu)
        if existante:
            (dossier / ".env").write_text(f"HTTP_PORT=8000\nIMAGE={image}\n", encoding="utf-8")
        bin_ = self.faux_bin(tmp)
        if systemd:
            ecrire_executable(bin_ / "systemctl", FAUX_SYSTEMCTL)
        if crontab:
            ecrire_executable(bin_ / "crontab", FAUX_CRONTAB)
        (tmp / "unites").mkdir()
        if systemd:
            (tmp / "run-systemd").mkdir()
        if cron:
            (tmp / "cron.d").mkdir()
        sans = [] if crontab else ["crontab"]
        if not systemd:
            sans.append("systemctl")
        from parametres.aides_tests.scripts_installation import chemin_sans

        chemin = f"{bin_}:{chemin_sans(tmp / 'systeme', sans)}"
        env = self.environnement(tmp, chemin=chemin, PROBANT_TEST_UID=uid, PROBANT_TEST_SYSTEMD_DIR=str(tmp / "unites"),
                                 PROBANT_TEST_SYSTEMD_RUN=str(tmp / "run-systemd"), PROBANT_TEST_CRON_DIR=str(tmp / "cron.d"),
                                 CRONTAB_FICHIER=str(tmp / "crontab.txt"))
        return tmp, dossier, env

    def install(self, dossier, env, *options):
        return self.lancer(["sh", str(dossier / "install.sh"), *options], cwd=dossier, env=env)

    def unites(self, tmp):
        return sorted(p.name for p in (tmp / "unites").iterdir())

    def test_systemd_pose_la_minuterie_seulement(self):
        tmp, dossier, env = self.preparer()
        r = self.install(dossier, env, "--auto-update", "on", "--auto-update-time", "01:30")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        unites = self.unites(tmp)
        self.assertEqual(len(unites), 2)
        nom = unites[0].rsplit(".", 1)[0]
        self.assertRegex(nom, r"^probant-auto-update-\d+$")
        service = (tmp / "unites" / f"{nom}.service").read_text()
        minuterie = (tmp / "unites" / f"{nom}.timer").read_text()
        self.assertIn(f"ExecStart=/bin/sh {dossier}/auto-update.sh\n", service)
        self.assertIn(f"WorkingDirectory={dossier}\n", service)
        self.assertIn("Type=oneshot", service)
        self.assertIn("OnCalendar=*-*-* 01:30:00\n", minuterie)
        self.assertIn("RandomizedDelaySec=3600\n", minuterie)
        appels = self.appels(tmp)
        self.assertIn("systemctl daemon-reload", appels)
        self.assertIn(f"systemctl enable --now {nom}.timer", appels)
        self.assertEqual((dossier / ".auto-update" / "task").read_text(), "systemd 01:30\n")
        docker = [a.split("|", 1)[1] for a in appels if "|" in a]
        self.assertFalse([a for a in docker if a.startswith(("compose up", "compose pull", "compose build"))],
                         "seule la minuterie change")
        self.assertTrue([a for a in docker if "/data/auto-update/.result.new" in a], "résultat « installée » pour l'outil")
        self.assertIn("state=installed", (dossier / ".auto-update" / "last").read_text())
        self.assertIn("did not change", r.stdout)  # le choix de l'administrateur reste le sien

    def test_heure_mal_ecrite_refusee(self):
        tmp, dossier, env = self.preparer()
        for heure in ("4h", "24:00", "04:60", "04:00; reboot"):
            with self.subTest(heure):
                r = self.install(dossier, env, "--auto-update", "on", "--auto-update-time", heure)
                self.assertEqual(r.returncode, 2)
        self.assertEqual(self.unites(tmp), [])

    def test_cron_du_systeme_sans_systemd(self):
        tmp, dossier, env = self.preparer(systemd=False)
        r = self.install(dossier, env, "--auto-update", "on")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        fichiers = list((tmp / "cron.d").iterdir())
        self.assertEqual(len(fichiers), 1)
        ligne = [x for x in fichiers[0].read_text().splitlines() if "auto-update.sh" in x][0]
        m = re.fullmatch(rf"(\d+) (\d+) \* \* \* root /bin/sh {re.escape(str(dossier))}/auto-update\.sh >/dev/null 2>&1", ligne)
        self.assertIsNotNone(m, ligne)
        self.assertTrue(int(m.group(2)) == 4 and 0 <= int(m.group(1)) <= 59, "dans l'heure après 04:00 (délai au hasard)")
        self.assertEqual((dossier / ".auto-update" / "task").read_text(), "cron 04:00\n")

    def test_cron_de_la_personne_sans_droits_d_administrateur(self):
        tmp, dossier, env = self.preparer(uid="1000")
        (tmp / "crontab.txt").write_text("0 1 * * * autre-tache\n")
        r = self.install(dossier, env, "--auto-update", "on")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.unites(tmp), [])
        table = (tmp / "crontab.txt").read_text().splitlines()
        self.assertEqual(table[0], "0 1 * * * autre-tache")
        self.assertRegex(table[1], rf"^\d+ 4 \* \* \* /bin/sh {re.escape(str(dossier))}/auto-update\.sh >/dev/null 2>&1 # probant-auto-update-\d+$")
        # posée deux fois : une seule ligne
        self.install(dossier, env, "--auto-update", "on")
        self.assertEqual(len((tmp / "crontab.txt").read_text().splitlines()), 2)
        r = self.install(dossier, env, "--auto-update", "off")
        self.assertEqual(r.returncode, 0)
        self.assertEqual((tmp / "crontab.txt").read_text().splitlines(), ["0 1 * * * autre-tache"])

    def test_off_retire_la_minuterie(self):
        tmp, dossier, env = self.preparer()
        self.install(dossier, env, "--auto-update", "on")
        nom = self.unites(tmp)[0].rsplit(".", 1)[0]
        r = self.install(dossier, env, "--auto-update", "off")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.unites(tmp), [])
        self.assertIn(f"systemctl disable --now {nom}.timer", self.appels(tmp))
        self.assertEqual((dossier / ".auto-update" / "task").read_text(), "none\n")
        self.assertIn("state=task_removed", (dossier / ".auto-update" / "last").read_text())

    def test_installations_sans_mise_a_jour_automatique_refusees(self):
        cas = {"git": None, "image locale": "probant:local", "paquet hors ligne": "probant:9.9.0",
               "autre registre": "registre.example/probant:9.9.0", "étiquette latest": f"{IMAGE_PUBLIQUE}:latest"}
        for nom, image in cas.items():
            with self.subTest(nom):
                tmp, dossier, env = self.preparer(image=image or f"{IMAGE_PUBLIQUE}:9.9.0")
                if image is None:
                    (dossier / ".git").mkdir()
                r = self.install(dossier, env, "--auto-update", "on")
                self.assertEqual(r.returncode, 1, r.stdout)
                self.assertIn("Nothing was changed", r.stdout)
                self.assertEqual(self.unites(tmp), [])
                self.assertFalse((dossier / ".auto-update").exists())
        tmp, dossier, env = self.preparer(nom="dossier avec espace")
        r = self.install(dossier, env, "--auto-update", "on")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(self.unites(tmp), [])
        tmp, dossier, env = self.preparer(uid="1000", crontab=False)
        r = self.install(dossier, env, "--auto-update", "on")
        self.assertEqual(r.returncode, 1)
        self.assertIn("No timer can be set up here", r.stdout)

    def test_image_epinglee_par_son_empreinte_acceptee(self):
        tmp, dossier, env = self.preparer(image=f"{IMAGE_PUBLIQUE}:9.9.1@{EMPREINTE}")
        self.assertEqual(self.install(dossier, env, "--auto-update", "on").returncode, 0)
        self.assertEqual(len(self.unites(tmp)), 2)

    def test_installation_neuve_choix_automatique(self):
        tmp, dossier, env = self.preparer(existante=False)
        r = self.install(dossier, env, "--image", f"{IMAGE_PUBLIQUE}:9.9.0", "--auto-update", "on")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(len(self.unites(tmp)), 2)
        docker = [a.split("|", 1)[1] for a in self.appels(tmp) if "|" in a]
        self.assertIn("compose exec -T web python manage.py auto_update --set-choice automatic --if-unset", docker)
        self.assertLess(docker.index("compose up -d"), docker.index(
            "compose exec -T web python manage.py auto_update --set-choice automatic --if-unset"))

    def test_installation_neuve_sans_mise_a_jour_automatique(self):
        tmp, dossier, env = self.preparer(existante=False)
        r = self.install(dossier, env, "--image", f"{IMAGE_PUBLIQUE}:9.9.0", "--auto-update", "off")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.unites(tmp), [])
        self.assertFalse((dossier / ".auto-update").exists())
        self.assertFalse([a for a in self.appels(tmp) if "auto_update" in a])
        # sans l'option (install.sh à la main) : rien non plus
        tmp, dossier, env = self.preparer(existante=False)
        self.assertEqual(self.install(dossier, env, "--image", f"{IMAGE_PUBLIQUE}:9.9.0").returncode, 0)
        self.assertEqual(self.unites(tmp), [])
        self.assertFalse((dossier / ".auto-update").exists())

    def test_installation_neuve_hors_ligne_refusee_avant_tout_changement(self):
        tmp, dossier, env = self.preparer(existante=False)
        r = self.install(dossier, env, "--image", "probant:local", "--auto-update", "on")
        self.assertEqual(r.returncode, 1)
        self.assertFalse((dossier / ".env").exists())


class GetShMiseAJourAutoTests(AidesScripts, SimpleTestCase):
    def preparer(self, etiquettes):
        tmp = self.dossier()
        depot = self.depot(etiquettes, "v9.9.1")
        bin_ = self.faux_bin(tmp)
        ecrire_executable(bin_ / "systemctl", FAUX_SYSTEMCTL)
        for d in ("unites", "run-systemd"):
            (tmp / d).mkdir()
        env = self.environnement(tmp, depot, PROBANT_TEST_UID="0", PROBANT_TEST_SYSTEMD_DIR=str(tmp / "unites"),
                                 PROBANT_TEST_SYSTEMD_RUN=str(tmp / "run-systemd"), PROBANT_TEST_CRON_DIR=str(tmp / "cron-absent"))
        return tmp, env

    def test_installation_en_une_commande_automatique_par_defaut(self):
        tmp, env = self.preparer({"v9.9.1": fichiers_avec_auto("9.9.1")})
        r = self.lancer(["sh", str(RACINE / "get.sh")], cwd=tmp, env=env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        dossier = tmp / "probant"
        self.assertEqual((dossier / "auto-update.sh").read_bytes(), (RACINE / "auto-update.sh").read_bytes())
        self.assertEqual(len(list((tmp / "unites").iterdir())), 2)
        self.assertTrue([a for a in self.appels(tmp) if "auto_update --set-choice automatic --if-unset" in a])

    def test_auto_update_off(self):
        tmp, env = self.preparer({"v9.9.1": fichiers_avec_auto("9.9.1")})
        r = self.lancer(["sh", str(RACINE / "get.sh"), "--auto-update", "off"], cwd=tmp, env=env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(list((tmp / "unites").iterdir()), [])
        self.assertFalse([a for a in self.appels(tmp) if "auto_update" in a])
        r = self.lancer(["sh", str(RACINE / "get.sh"), "--auto-update", "parfois"], cwd=tmp, env=env)
        self.assertEqual(r.returncode, 2)

    def test_version_d_avant_les_mises_a_jour_automatiques(self):
        """Une version publiée avant auto-update.sh : installée comme avant, sans l'option (son install.sh ne la
        connaît pas)."""
        ancienne = version_des_fichiers("9.9.1")
        ancienne["install.sh"] = re.sub(rb"    --auto-update\).*?;;\n", b"", ancienne["install.sh"], flags=re.S)
        tmp, env = self.preparer({"v9.9.1": ancienne})
        r = self.lancer(["sh", str(RACINE / "get.sh")], cwd=tmp, env=env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse((tmp / "probant" / "auto-update.sh").exists())
        self.assertEqual(list((tmp / "unites").iterdir()), [])


class UpdateShEmpreinteTests(AidesScripts, SimpleTestCase):
    def preparer(self, image=f"{IMAGE_PUBLIQUE}:9.9.0"):
        tmp = self.dossier()
        dossier = tmp / "probant"
        (dossier / "docker").mkdir(parents=True)
        for f, contenu in fichiers_avec_auto("9.9.0").items():
            if f != "VERSION":
                (dossier / f).write_bytes(contenu)
        (dossier / ".env").write_text(f"IMAGE={image}\n", encoding="utf-8")
        depot = self.depot({"v9.9.0": fichiers_avec_auto("9.9.0"), "v9.9.1": fichiers_avec_auto("9.9.1"),
                            "v9.9.2": version_des_fichiers("9.9.2")}, "v9.9.1")
        return tmp, dossier, self.environnement(tmp, depot)

    def update(self, dossier, env, *options):
        return self.lancer(["sh", str(dossier / "update.sh"), *options], cwd=dossier, env=env)

    def test_image_epinglee_et_fichiers_de_la_version(self):
        tmp, dossier, env = self.preparer()
        r = self.update(dossier, env, "--version", "9.9.1", "--digest", EMPREINTE)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.valeur(dossier / ".env", "IMAGE"), f"{IMAGE_PUBLIQUE}:9.9.1@{EMPREINTE}")
        self.assertIn("# files of version 9.9.1", (dossier / "docker-compose.yml").read_text())
        self.assertTrue((dossier / "auto-update.sh").stat().st_mode & 0o100)
        self.assertFalse((dossier / ".update.lock").exists(), "verrou rendu")
        # une mise à jour à la main après : la version installée se lit malgré l'empreinte
        r = self.update(dossier, env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Version 9.9.1 is the latest", r.stdout)
        self.assertEqual(self.valeur(dossier / ".env", "IMAGE"), f"{IMAGE_PUBLIQUE}:9.9.1@{EMPREINTE}")

    def test_meme_version_autre_empreinte(self):
        tmp, dossier, env = self.preparer(f"{IMAGE_PUBLIQUE}:9.9.1@sha256:{'d' * 64}")
        r = self.update(dossier, env, "--version", "9.9.1", "--digest", EMPREINTE)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.valeur(dossier / ".env", "IMAGE"), f"{IMAGE_PUBLIQUE}:9.9.1@{EMPREINTE}")

    def test_empreinte_refusee(self):
        tmp, dossier, env = self.preparer()
        for e in ("sha256:abc", "md5:" + "c" * 64, EMPREINTE + "; reboot"):
            with self.subTest(e):
                self.assertEqual(self.update(dossier, env, "--version", "9.9.1", "--digest", e).returncode, 2)
        tmp, dossier, env = self.preparer("probant:local")
        r = self.update(dossier, env, "--digest", EMPREINTE)
        self.assertEqual(r.returncode, 2)
        self.assertEqual(self.valeur(dossier / ".env", "IMAGE"), "probant:local")

    def test_version_sans_auto_update_sh(self):
        """Fichier facultatif : une étiquette qui ne l'a pas garde le fichier d'avant (rien ne manque au téléchargement)."""
        tmp, dossier, env = self.preparer()
        r = self.update(dossier, env, "--version", "9.9.2")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual((dossier / "auto-update.sh").read_bytes(), (RACINE / "auto-update.sh").read_bytes())


class TexteDesScriptsTests(SimpleTestCase):
    """Fonctions recopiées d'un script à l'autre (chaque script reste autonome) : elles restent identiques."""

    @staticmethod
    def bloc(nom, debut, fin):
        t = (RACINE / nom).read_text(encoding="utf-8")
        i = t.index(debut)
        j = t.index(fin, i) + len(fin)
        return [x for x in t[i:j].splitlines() if x.strip() and not x.lstrip().startswith("#")]

    def test_telechargement_du_fichier_facultatif_identique(self):
        self.assertEqual(self.bloc("get.sh", "download_optional() {", "\n}\n"), self.bloc("update.sh", "download_optional() {", "\n}\n"))
        for nom in ("get.sh", "update.sh"):
            self.assertRegex((RACINE / nom).read_text(), r'(?m)^OPTIONAL_FILES="auto-update.sh"$')

    def test_verrou_identique_dans_update_sh_et_auto_update_sh(self):
        for debut, fin in (("alive() {", "\n"), ("take_lock() {", "\n}\n"), ("release_lock() {", "\n")):
            with self.subTest(debut):
                self.assertEqual(self.bloc("update.sh", debut, fin), self.bloc("auto-update.sh", debut, fin))
        self.assertIn("LOCK=.update.lock", (RACINE / "update.sh").read_text())
        self.assertIn("LOCK=.update.lock", (RACINE / "auto-update.sh").read_text())

    def test_recherche_de_la_derniere_version_identique(self):
        for debut, fin in (("is_version() {", "\n"), ("latest_version() {", "\n}\n")):
            with self.subTest(debut):
                self.assertEqual(self.bloc("update.sh", debut, fin), self.bloc("auto-update.sh", debut, fin))
