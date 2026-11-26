"""``auto-update.sh`` : avant d'installer une nouvelle version, la tâche télécharge la liste des sommes SHA-256 de ses
fichiers (release de son étiquette) et vérifie sa signature, obligatoirement, avec le conteneur de cosign et l'identité
qui servent pour l'image ; ``update.sh`` vérifie ensuite chaque fichier contre cette liste (``--sums``). Liste absente,
signature refusée, ou un fichier qui ne correspond pas : rien n'est installé (« refused »), les fichiers et l'image
restent ceux d'avant. Joué avec le faux ``docker`` de ``aides_tests/mise_a_jour_auto.py`` (signature factice des listes :
le paquet contient l'empreinte de la liste signée), le vrai ``update.sh`` et le vrai ``curl``."""
from django.test import SimpleTestCase

from parametres.aides_tests.mise_a_jour_auto import ANCIENNE, AidesMiseAJourAuto, fichier
from parametres.aides_tests.scripts_installation import RACINE, liste_des_sommes, nom_liste, release_de, version_des_fichiers

IMAGE = "ghcr.io/probant-reporting/probant"


def fichiers_publies(version):
    """Fichiers de l'étiquette d'une version dans le dépôt factice de la tâche (auto-update.sh compris)."""
    return {**version_des_fichiers(version), "auto-update.sh": (RACINE / "auto-update.sh").read_bytes()}


class MiseAJourAutoSommesTests(AidesMiseAJourAuto, SimpleTestCase):
    def jouer(self, release=None, scenario=None, fichiers=None, **reglages):
        """Une nuit : la version 9.9.1 publiée avec ``fichiers`` (par défaut, les siens) et sa release ``release``."""
        tmp, dossier, env = self.installation(scenario, **reglages)
        depot = self.depot({"v9.9.0": fichiers_publies("9.9.0"), "v9.9.1": fichiers or fichiers_publies("9.9.1")}, "v9.9.1",
                           None if release is None else {"v9.9.1": release})
        env["PROBANT_TEST_SOURCE"] = depot.adresse
        r = self.lancer_auto(dossier, env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return tmp, dossier, depot, r

    def assertRefusee(self, tmp, dossier, raison="signature"):
        res = self.resultat(tmp)
        self.assertEqual((res["state"], res.get("reason"), res["installed"], res["available"]), ("refused", raison, "9.9.0", "9.9.1"))
        self.assertEqual(self.image_env(dossier), f"{IMAGE}:9.9.0")
        self.assertIn("# files of version 9.9.0", fichier(dossier / "docker-compose.yml"))
        self.assertEqual(self.etat(tmp)["image"], ANCIENNE, "l'image d'avant tourne toujours")

    def test_liste_verifiee_puis_donnee_a_update_sh(self):
        tmp, dossier, depot, r = self.jouer()
        self.assertEqual(self.resultat(tmp)["state"], "updated")
        self.assertIn("# files of version 9.9.1", fichier(dossier / "docker-compose.yml"))
        appel = self.etat(tmp)["cosign_listes"][0]
        i = appel.index("verify-blob")
        self.assertRegex(appel[i - 1], r"^ghcr\.io/sigstore/cosign/cosign:v[0-9.]+@sha256:[0-9a-f]{64}$")
        self.assertEqual(appel[appel.index("--certificate-identity-regexp") + 1],
                         r"^https://github\.com/Probant-Reporting/probant/\.github/workflows/image\.yml@refs/tags/[vV]9\.9\.1$")
        self.assertEqual(appel[appel.index("--certificate-oidc-issuer") + 1], "https://token.actions.githubusercontent.com")
        for option in ("--read-only", "--cap-drop", "--rm", "--user"):
            self.assertIn(option, appel)
        self.assertIn(f"{dossier}/.auto-update/sums:/work:ro", appel)
        journal = fichier(dossier / "auto-update.log")
        self.assertIn("Signature verified: the list of the SHA-256 sums of the files of version 9.9.1", journal)
        self.assertIn("files checked: each one matches its SHA-256 sum in the list verified by auto-update.sh", journal)
        # update.sh ne retélécharge pas la liste : une seule demande de chaque pièce
        self.assertEqual(len([d for d in depot.demandes if d.endswith(nom_liste("9.9.1"))]), 1)

    def test_liste_absente_rien_n_est_installe(self):
        liste = liste_des_sommes(fichiers_publies("9.9.1"))
        for release in ({}, {nom_liste("9.9.1"): liste}):
            with self.subTest(sorted(release)):
                tmp, dossier, depot, r = self.jouer(release)
                self.assertRefusee(tmp, dossier)
                self.assertIn("has no list of the SHA-256 sums of its files", fichier(dossier / "auto-update.log"))
                self.assertFalse([a for a in self.appels(tmp) if "before-update" in a], "ni sauvegarde ni mise à jour")

    def test_liste_changee_apres_sa_signature_rien_n_est_installe(self):
        publies = fichiers_publies("9.9.1")
        change = {**publies, "install.sh": publies["install.sh"] + b"\n# piege\n"}
        signee = release_de(publies)
        release = {nom_liste("9.9.1"): liste_des_sommes(change),
                   f"{nom_liste('9.9.1')}.sigstore.json": signee[f"{nom_liste('9.9.1')}.sigstore.json"]}
        tmp, dossier, depot, r = self.jouer(release, fichiers=change)
        self.assertRefusee(tmp, dossier)
        self.assertIn("no valid signature of Probant-Reporting/probant (workflow image.yml, tag v9.9.1) for the list of sums",
                      fichier(dossier / "auto-update.log"))
        self.assertFalse([a for a in self.appels(tmp) if "before-update" in a])

    def test_signature_de_la_liste_impossible_a_verifier_rien_n_est_installe(self):
        """Pas de repli : la tâche n'installe rien sans signature vérifiée (au contraire de get.sh et update.sh)."""
        tmp, dossier, depot, r = self.jouer(scenario={"liste_rc": 1})
        self.assertRefusee(tmp, dossier)

    def test_un_fichier_change_rien_n_est_installe(self):
        """La liste signée est bonne, mais un fichier servi par l'étiquette ne lui correspond pas (étiquette déplacée,
        fichier changé en chemin) : update.sh refuse avant tout remplacement, la tâche le note « refused »."""
        publies = fichiers_publies("9.9.1")
        change = {**publies, "docker/Caddyfile": publies["docker/Caddyfile"] + b"\n# piege\n"}
        tmp, dossier, depot, r = self.jouer(release_de(publies), fichiers=change)
        self.assertRefusee(tmp, dossier)
        journal = fichier(dossier / "auto-update.log")
        self.assertIn("docker/Caddyfile does not match its SHA-256 sum", journal)
        self.assertIn("a file of version 9.9.1 does not match the verified list of sums", journal)
        self.assertEqual(fichier(dossier / "docker/Caddyfile"), version_des_fichiers("9.9.0")["docker/Caddyfile"].decode())
        self.assertFalse([a for a in self.appels(tmp) if a == "compose pull web"])

    def test_liste_lue_seulement_au_moment_d_installer(self):
        """Prévenir seulement, ou attente de N jours : la liste n'est pas encore demandée (une version publiée depuis
        peu n'a peut-être pas encore la sienne)."""
        for choix in ("mode=notify\ndelay=0\n", "mode=automatic\ndelay=14\n"):
            with self.subTest(choix):
                tmp, dossier, depot, r = self.jouer({}, choix=choix, scenario={"created": "2999-01-01T00:00:00Z"})
                self.assertIn(self.resultat(tmp)["state"], ("available", "waiting"))
                self.assertFalse([d for d in depot.demandes if d.startswith("/releases/download/")])

    def appels(self, tmp):
        return [x.split("|", 1)[1] for x in super().appels(tmp)]
