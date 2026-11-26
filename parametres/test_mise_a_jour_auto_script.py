"""``auto-update.sh`` : la tâche de la machine qui met l'outil à jour la nuit, jouée avec un faux ``docker`` (installation,
registre, cosign, bases des espaces), le vrai ``update.sh`` et le vrai ``curl`` contre un dépôt factice.

Chaque cas lit le résultat écrit dans le volume avec l'analyse de l'outil (``mise_a_jour_auto.analyser_resultat``) :
ce que la tâche écrit est exactement ce que l'outil accepte. L'essai réel, avec Docker, un registre local et cosign :
``docker/test_auto_update.sh``."""
import os
import random
import subprocess
from datetime import date, timedelta

from django.test import SimpleTestCase

from parametres.aides_tests.mise_a_jour_auto import ANCIENNE, NOUVELLE, AidesMiseAJourAuto, fichier
from parametres.aides_tests.scripts_installation import RACINE

IMAGE = "ghcr.io/probant-reporting/probant"


class MiseAJourAutoScriptTests(AidesMiseAJourAuto, SimpleTestCase):
    def jouer(self, scenario=None, *options, **reglages):
        tmp, dossier, env = self.installation(scenario, **reglages)
        r = self.lancer_auto(dossier, env, *options)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return tmp, dossier, env, r

    def appels(self, tmp):
        return [x.split("|", 1)[1] for x in super().appels(tmp)]

    # ---- rien à faire
    def test_choix_eteint_ou_absent_rien_n_est_cherche(self):
        for choix in ("mode=off\ndelay=0\n", ""):
            with self.subTest(choix=choix):
                tmp, dossier, env, r = self.jouer(choix=choix)
                res = self.resultat(tmp)
                self.assertEqual((res["state"], res["installed"], res["task"]), ("off", "9.9.0", "manual"))
                self.assertFalse([a for a in self.appels(tmp) if a.startswith("pull")], "rien n'est téléchargé")
                self.assertEqual(self.image_env(dossier), f"{IMAGE}:9.9.0")

    def test_meme_empreinte_rien_a_faire(self):
        tmp, dossier, env, r = self.jouer({"latest": "9.9.0", "latest_is_new": False})
        self.assertEqual(self.resultat(tmp)["state"], "up_to_date")
        self.assertFalse(self.etat(tmp).get("cosign"), "pas de vérification sans nouvelle image")
        self.assertEqual(self.image_env(dossier), f"{IMAGE}:9.9.0")

    def test_meme_numero_autre_empreinte_c_est_une_nouvelle_image(self):
        """Les numéros ne sont jamais comparés : une image republiée sous le même numéro (autre empreinte) est vérifiée et
        installée comme une autre."""
        tmp, dossier, env, r = self.jouer({"latest": "9.9.0"})
        self.assertEqual(self.resultat(tmp)["state"], "updated")
        self.assertEqual(self.image_env(dossier), f"{IMAGE}:9.9.0@{NOUVELLE}")

    # ---- signature
    def test_signature_verifiee_avec_l_identite_du_workflow_public(self):
        tmp, dossier, env, r = self.jouer({"cosign_rc": 0})
        appel = self.etat(tmp)["cosign"][0]
        i = appel.index("verify")
        self.assertEqual(appel[i + 1], f"{IMAGE}@{NOUVELLE}", "vérifiée par son empreinte, jamais par l'étiquette")
        self.assertEqual(appel[appel.index("--certificate-identity-regexp") + 1],
                         r"^https://github\.com/Probant-Reporting/probant/\.github/workflows/image\.yml@refs/tags/[vV]9\.9\.1$")
        self.assertEqual(appel[appel.index("--certificate-oidc-issuer") + 1], "https://token.actions.githubusercontent.com")
        self.assertNotIn("--key", appel)
        image_cosign = appel[i - 1]
        self.assertRegex(image_cosign, r"^ghcr\.io/sigstore/cosign/cosign:v[0-9.]+@sha256:[0-9a-f]{64}$")
        for option in ("--read-only", "--cap-drop", "--rm"):
            self.assertIn(option, appel)
        self.assertNotIn("/var/run/docker.sock", " ".join(appel))

    def test_signature_absente_ou_fausse_rien_n_est_installe(self):
        tmp, dossier, env, r = self.jouer({"cosign_rc": 1})
        res = self.resultat(tmp)
        self.assertEqual((res["state"], res["reason"], res["available"]), ("refused", "signature", "9.9.1"))
        self.assertEqual(self.image_env(dossier), f"{IMAGE}:9.9.0")
        self.assertIn("# files of version 9.9.0", fichier(dossier / "docker-compose.yml"))
        appels = self.appels(tmp)
        self.assertIn(f"image rm {IMAGE}:9.9.1", appels)
        self.assertFalse([a for a in appels if "before-update" in a], "ni sauvegarde ni mise à jour")

    def test_verification_impossible_rien_n_est_installe(self):
        tmp, dossier, env, r = self.jouer({"cosign_present": False})
        res = self.resultat(tmp)
        self.assertEqual((res["state"], res["reason"]), ("refused", "verifier"))
        self.assertEqual(self.image_env(dossier), f"{IMAGE}:9.9.0")
        self.assertFalse(self.etat(tmp).get("cosign"))

    def test_variables_de_test_de_cosign_ignorees_pour_l_image_publiee(self):
        """La clé de test et l'image de cosign de test ne valent qu'avec un nom d'image de test (PROBANT_TEST_IMAGE) :
        l'image publiée est toujours vérifiée avec l'identité du dépôt public."""
        tmp, dossier, env = self.installation()
        env.update(PROBANT_TEST_COSIGN_KEY=str(tmp / "cle.pub"), PROBANT_TEST_COSIGN_IMAGE="cosign-de-test:1")
        self.assertEqual(self.lancer_auto(dossier, env).returncode, 0)
        appel = self.etat(tmp)["cosign"][0]
        self.assertNotIn("--key", appel)
        self.assertNotIn("cosign-de-test:1", appel)
        self.assertIn("--certificate-identity-regexp", appel)

    # ---- choix et fenêtre
    def test_prevenir_seulement(self):
        tmp, dossier, env, r = self.jouer(choix="mode=notify\ndelay=0\n")
        res = self.resultat(tmp)
        self.assertEqual((res["state"], res["available"], res["available_digest"]), ("available", "9.9.1", NOUVELLE))
        self.assertEqual(self.image_env(dossier), f"{IMAGE}:9.9.0")

    def test_fenetre_de_n_jours_apres_la_publication(self):
        aujourd_hui = date.today()
        tmp, dossier, env, r = self.jouer({"created": f"{aujourd_hui.isoformat()}T01:02:03.4Z"}, choix="mode=automatic\ndelay=3\n")
        res = self.resultat(tmp)
        self.assertEqual(res["state"], "waiting")
        self.assertEqual(res["install_after"], aujourd_hui + timedelta(days=3))
        self.assertEqual(self.image_env(dossier), f"{IMAGE}:9.9.0")
        # publiée il y a 3 jours : installée
        il_y_a = (aujourd_hui - timedelta(days=3)).isoformat()
        tmp, dossier, env, r = self.jouer({"created": f"{il_y_a}T01:02:03Z"}, choix="mode=automatic\ndelay=3\n")
        self.assertEqual(self.resultat(tmp)["state"], "updated")

    def test_choix_malveillant_rien_n_est_evalue(self):
        """Le fichier de choix est écrit par l'outil : pour la tâche, une entrée non sûre. Seules des valeurs d'une liste
        fermée sont lues ; rien n'est évalué."""
        for choix in ("mode=$(touch /tmp/PIEGE-auto)\n", "mode=automatic;touch PIEGE\ndelay=0\n", "mode=`touch PIEGE`\n",
                      "MODE=automatic\n", "mode= automatic\n", "mode=automatic\\\ndelay=0\n", "mode=automatic x\n"):
            with self.subTest(choix=choix):
                tmp, dossier, env, r = self.jouer(choix=choix)
                self.assertEqual(self.resultat(tmp)["state"], "off", choix)
                self.assertFalse((dossier / "PIEGE").exists())
                self.assertFalse(os.path.exists("/tmp/PIEGE-auto"))
        # délai hors de la liste : le délai par défaut (3 jours), jamais 999 ; image de 2020, donc installée
        tmp, dossier, env, r = self.jouer({"created": f"{date.today().isoformat()}T00:00:00Z"}, choix="mode=automatic\ndelay=999\n")
        res = self.resultat(tmp)
        self.assertEqual((res["state"], res["install_after"]), ("waiting", date.today() + timedelta(days=3)))

    def test_outil_occupe_rien_n_est_fait(self):
        for raison in ("busy_restore", "busy_backup", "busy_import", "busy_export"):
            with self.subTest(raison):
                tmp, dossier, env, r = self.jouer({"busy": raison})
                res = self.resultat(tmp)
                self.assertEqual((res["state"], res["reason"]), ("postponed", raison))
                self.assertEqual(self.image_env(dossier), f"{IMAGE}:9.9.0")
        tmp, dossier, env, r = self.jouer({"busy": "rien de lisible"})
        self.assertEqual(self.resultat(tmp)["reason"], "busy_unknown")

    def test_migration_du_registre_commun_prevenir_seulement(self):
        """Le registre commun (comptes) n'est restauré que par son contenu, jamais par sa structure : une version qui lui
        ajoute une migration ne peut pas être défaite automatiquement, elle n'est donc pas installée automatiquement."""
        tmp, dossier, env, r = self.jouer({"registry_new": ["espaces/0001_initial.py", "espaces/0002_nouveau.py"]})
        res = self.resultat(tmp)
        self.assertEqual((res["state"], res["reason"]), ("available", "registry_migrations"))
        self.assertEqual(self.image_env(dossier), f"{IMAGE}:9.9.0")
        tmp, dossier, env, r = self.jouer({"registry_new": []})  # liste illisible : même prudence
        self.assertEqual(self.resultat(tmp)["reason"], "registry_migrations")

    def test_installations_hors_perimetre(self):
        tmp, dossier, env = self.installation()
        (dossier / ".git").mkdir()
        self.assertEqual(self.lancer_auto(dossier, env).returncode, 0)
        self.assertEqual((self.resultat(tmp)["state"], self.resultat(tmp)["reason"]), ("not_available", "git"))
        for image in ("probant:local", "probant:9.9.0", f"{IMAGE}:latest", "registre.example/probant:9.9.0"):
            with self.subTest(image):
                tmp, dossier, env = self.installation()
                (dossier / ".env").write_text(f"IMAGE={image}\n", encoding="utf-8")
                self.assertEqual(self.lancer_auto(dossier, env).returncode, 0)
                self.assertEqual((self.resultat(tmp)["state"], self.resultat(tmp)["reason"]), ("not_available", "image"))
                self.assertFalse([a for a in self.appels(tmp) if a.startswith("pull")])

    def test_outil_arrete_rien_n_est_fait(self):
        tmp, dossier, env, r = self.jouer(running=False)
        res = self.resultat(tmp)
        self.assertEqual((res["state"], res["reason"]), ("check_failed", "tool_stopped"))
        self.assertFalse([a for a in self.appels(tmp) if a.startswith("pull")])

    def test_reseau_ou_registre_injoignable(self):
        tmp, dossier, env, r = self.jouer({"pull_ok": False})
        self.assertEqual((self.resultat(tmp)["state"], self.resultat(tmp)["reason"]), ("check_failed", "registry"))
        tmp, dossier, env = self.installation()
        env["PROBANT_TEST_SOURCE"] = "http://127.0.0.1:9"  # rien n'écoute
        self.assertEqual(self.lancer_auto(dossier, env).returncode, 0)
        self.assertEqual((self.resultat(tmp)["state"], self.resultat(tmp)["reason"]), ("check_failed", "network"))

    # ---- mise à jour et retour arrière
    def test_mise_a_jour_reussie(self):
        tmp, dossier, env, r = self.jouer(espaces=("second",))
        res = self.resultat(tmp)
        self.assertEqual((res["state"], res["installed"], res["previous"], res["installed_digest"]),
                         ("updated", "9.9.1", "9.9.0", NOUVELLE))
        self.assertEqual(self.image_env(dossier), f"{IMAGE}:9.9.1@{NOUVELLE}", "épinglée sur l'empreinte vérifiée")
        self.assertIn("# files of version 9.9.1", fichier(dossier / "docker-compose.yml"))
        e = self.etat(tmp)
        self.assertEqual(e["image"], NOUVELLE)
        self.assertEqual(len(e["archives"]["second"]), 1, "sauvegarde avant de chaque espace (update.sh)")
        self.assertFalse((dossier / ".update.lock").exists(), "verrou rendu")
        self.assertIn("Update complete", fichier(dossier / "auto-update.log"))
        # la nuit suivante : même empreinte que celle qui tourne
        self.assertEqual(self.lancer_auto(dossier, env).returncode, 0)
        self.assertEqual(self.resultat(tmp)["state"], "up_to_date")

    def test_nouvelle_image_qui_ne_repond_pas_retour_arriere_sans_restauration(self):
        tmp, dossier, env, r = self.jouer({"new_healthy": False})
        res = self.resultat(tmp)
        self.assertEqual((res["state"], res["reason"], res["restored"], res["installed"], res["available"]),
                         ("rolled_back", "health", "no", "9.9.0", "9.9.1"))
        self.assertEqual(self.image_env(dossier), f"{IMAGE}:9.9.0")
        self.assertIn("# files of version 9.9.0", fichier(dossier / "docker-compose.yml"))
        self.assertEqual(fichier(dossier / "auto-update.sh"), fichier(RACINE / "auto-update.sh"))
        e = self.etat(tmp)
        self.assertEqual(e["image"], ANCIENNE)
        self.assertTrue(e["running"])
        self.assertFalse(e.get("restaurations"), "rien à restaurer : la nouvelle version n'a pas touché aux bases")
        # la nuit suivante : la même image n'est pas réessayée ; --retry la réessaie
        self.assertEqual(self.lancer_auto(dossier, env).returncode, 0)
        self.assertEqual((self.resultat(tmp)["state"], self.resultat(tmp)["reason"]), ("available", "already_failed"))
        self.assertEqual(self.image_env(dossier), f"{IMAGE}:9.9.0")
        self.assertEqual(self.lancer_auto(dossier, env, "--retry").returncode, 0)
        self.assertEqual(self.resultat(tmp)["state"], "rolled_back")

    def test_migration_appliquee_puis_echec_restauration_de_chaque_espace_change(self):
        tmp, dossier, env, r = self.jouer({"new_healthy": False, "new_migrates": ["space principal", "space second"]},
                                          espaces=("second",))
        res = self.resultat(tmp)
        self.assertEqual((res["state"], res["restored"]), ("rolled_back", "yes"))
        e = self.etat(tmp)
        self.assertEqual(e["empreintes"], e["avant"])
        restaurations = e["restaurations"]
        self.assertEqual(len(restaurations), 2)
        # la plus ancienne sauvegarde « before-update » de la mise à jour (celle d'update.sh, faite avec la version d'avant)
        self.assertIn("principal python manage.py restore backup-20990101-030001-before-update.zip --yes --rebuild --no-backup-before",
                      restaurations[0])
        self.assertIn("second python manage.py restore backup-20990101-030000-before-update.zip", restaurations[1])
        self.assertEqual(e["image"], ANCIENNE)
        self.assertEqual(self.image_env(dossier), f"{IMAGE}:9.9.0")

    def test_seul_l_espace_change_est_restaure(self):
        tmp, dossier, env, r = self.jouer({"new_healthy": False, "new_migrates": ["space second"]}, espaces=("second",))
        self.assertEqual(self.resultat(tmp)["restored"], "yes")
        self.assertEqual([x.split()[0] for x in self.etat(tmp)["restaurations"]], ["second"])

    def test_restauration_impossible_panne(self):
        tmp, dossier, env, r = self.jouer({"new_healthy": False, "new_migrates": ["space principal"], "restore_rc": 1})
        res = self.resultat(tmp)
        self.assertEqual((res["state"], res["reason"], res["previous"], res["available"]),
                         ("failed", "restore_failed", "9.9.0", "9.9.1"))
        self.assertTrue(self.etat(tmp)["running"], "l'outil d'avant est relancé")

    def test_apres_un_echec_sans_retour_complet_plus_rien_d_automatique(self):
        """Retour arrière incomplet : les nuits suivantes, rien n'est retenté (ni cette image ni une autre) tant que l'IT
        n'a pas regardé ; le résultat reste « échec ». « --retry » rend la main."""
        tmp, dossier, env, r = self.jouer({"new_healthy": False, "new_migrates": ["space principal"], "restore_rc": 1})
        self.assertEqual(self.resultat(tmp)["state"], "failed")
        appels = len(self.appels(tmp))
        self.assertEqual(self.lancer_auto(dossier, env).returncode, 0)
        res = self.resultat(tmp)
        self.assertEqual((res["state"], res["reason"], res["available"], res["previous"]),
                         ("failed", "restore_failed", "9.9.1", "9.9.0"))
        nouveaux = self.appels(tmp)[appels:]
        self.assertFalse([a for a in nouveaux if a.startswith("pull") or "before-update" in a], nouveaux)
        self.assertIn("nothing is done until IT", fichier(dossier / "auto-update.log"))
        self.assertEqual(self.lancer_auto(dossier, env, "--retry").returncode, 0)
        self.assertTrue([a for a in self.appels(tmp)[appels:] if a.startswith("pull")])

    def test_registre_commun_change_retour_arriere_impossible(self):
        tmp, dossier, env, r = self.jouer({"new_healthy": False, "new_migrates": ["registry", "space principal"]})
        res = self.resultat(tmp)
        self.assertEqual((res["state"], res["reason"]), ("failed", "restore_failed"))
        self.assertFalse(self.etat(tmp).get("restaurations"))

    def test_ancienne_version_ne_repond_plus_panne(self):
        tmp, dossier, env, r = self.jouer({"new_healthy": False, "old_healthy": False})
        self.assertEqual((self.resultat(tmp)["state"], self.resultat(tmp)["reason"]), ("failed", "rollback_health"))

    def test_update_sh_arrete_avant_la_nouvelle_version_rien_de_change(self):
        """Sauvegarde « before-update » impossible : update.sh s'arrête sans rien changer ; ce n'est pas un échec de la
        version (elle sera réessayée la nuit suivante)."""
        tmp, dossier, env, r = self.jouer({"backup_rc": 1})
        res = self.resultat(tmp)
        self.assertEqual((res["state"], res["reason"]), ("check_failed", "update_script"))
        self.assertEqual(self.image_env(dossier), f"{IMAGE}:9.9.0")
        self.assertFalse((dossier / ".auto-update" / "failed").exists())

    # ---- verrou
    def test_verrou_tenu_par_un_processus_vivant(self):
        tmp, dossier, env = self.installation()
        veille = subprocess.Popen(["sleep", "30"])
        self.addCleanup(veille.kill)
        (dossier / ".update.lock").mkdir()
        (dossier / ".update.lock" / "pid").write_text(str(veille.pid))
        r = self.lancer_auto(dossier, env)
        self.assertEqual(r.returncode, 0)
        self.assertIn("Another update is running", r.stdout)
        self.assertNotIn("result", self.etat(tmp))
        self.assertEqual(self.appels(tmp), [])
        # update.sh à la main pendant ce temps : refusé, rien n'est changé
        r = self.lancer(["sh", str(dossier / "update.sh")], cwd=dossier, env=env)
        self.assertEqual(r.returncode, 1)
        self.assertIn("Another update is running", r.stdout)
        self.assertEqual(self.appels(tmp), [])

    def test_verrou_abandonne_repris(self):
        tmp, dossier, env = self.installation()
        mort = subprocess.Popen(["true"])
        mort.wait()
        (dossier / ".update.lock").mkdir()
        (dossier / ".update.lock" / "pid").write_text(str(mort.pid))
        self.assertEqual(self.lancer_auto(dossier, env).returncode, 0)
        self.assertEqual(self.resultat(tmp)["state"], "updated")
        self.assertFalse((dossier / ".update.lock").exists())

    # ---- résultat
    def test_resultat_borne_et_depuis_garde(self):
        tmp, dossier, env, r = self.jouer({"cosign_rc": 1})
        premier = self.resultat(tmp)
        self.lancer_auto(dossier, env)
        second = self.resultat(tmp)
        self.assertEqual(second["since"], premier["since"], "même état : « depuis » garde le premier passage")
        self.assertLessEqual(len(self.etat(tmp)["result"].encode()), 4096)
        self.assertIn("refused", fichier(dossier / ".auto-update" / "last"))
        r = self.lancer_auto(dossier, env, "--status")
        self.assertIn("state=refused", r.stdout)


class DatesTests(SimpleTestCase):
    """Fenêtre de N jours : jours depuis le 1er janvier 1970 d'une date, et l'inverse, écrits en awk POSIX dans
    auto-update.sh ; comparés au calendrier de Python sur des dates tirées au hasard (graine fixe)."""

    def fonction(self, nom, valeur):
        texte = fichier(RACINE / "auto-update.sh")
        debut = texte.index(f"{nom}() {{")
        fin = texte.index("}'; }", debut) + len("}'; }")
        script = texte[debut:fin] + f'\n{nom} "$1"\n'
        return subprocess.run(["sh", "-c", script, "sh", valeur], capture_output=True, text=True, check=True).stdout.strip()

    def test_equivalence_avec_le_calendrier(self):
        hasard = random.Random(20261125)
        origine = date(1970, 1, 1)
        jours = [0, 1, 59, 60, 365, 10956, 11016, 18321, 20000, 20788, 29220, 47481] + [hasard.randrange(0, 47482) for _ in range(150)]
        for n in jours:
            d = origine + timedelta(days=n)
            self.assertEqual(self.fonction("days_of", d.isoformat()), str(n), d)
            self.assertEqual(self.fonction("date_of", str(n)), d.isoformat(), n)
