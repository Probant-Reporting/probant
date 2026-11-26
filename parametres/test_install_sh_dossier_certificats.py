"""``install.sh`` et ``update.sh`` devant un dossier ``certificates/`` qui existe déjà avec d'autres droits : cas d'une
installation par Git mise à jour depuis une version d'avant ce dossier (l'ANCIEN ``update.sh`` tourne : ``git pull``
puis ``docker compose up -d`` avec le nouveau docker-compose.yml, et Docker crée ``./certificates/ca`` au nom de root,
constaté avec un vrai Docker). Lancés ensuite par un membre non root du groupe docker :

- ``install.sh`` sans certificat à poser ne s'arrête pas sur ce dossier (pas de ``chmod`` d'un dossier d'un autre) ;
- ``install.sh --ca-cert`` qui ne peut pas y écrire le dit en une phrase (relancer avec sudo, ou sudo chown), sans
  trace d'une commande système en échec ;
- ``update.sh`` crée les dossiers manquants avec les droits que leur donne ``install.sh`` (0755, et 0700 pour
  ``https``), quel que soit le masque (mise à jour automatique : umask 077)."""
import os
import stat
import unittest

from django.test import SimpleTestCase

from parametres.aides_tests.scripts_installation import RACINE

from .test_install_sh_certificat import ENV_HTTPS, AidesCertificat

UTILISATEUR = (4321, 4322)


def mode(p):
    return stat.S_IMODE(p.stat().st_mode)


@unittest.skipUnless(os.geteuid() == 0, "jouer un membre non root du groupe docker demande root")
class DossierCertificatsDeRootTests(AidesCertificat, SimpleTestCase):
    def installation_de_l_utilisateur(self):
        d = self.tmp / "installation"  # comme test_install_sh_certificat.EnLigneTests
        (d / "docker").mkdir(parents=True)
        for f in ("install.sh", "check.sh", ".env.example", "docker-compose.yml", "docker/Caddyfile"):
            (d / f).write_bytes((RACINE / f).read_bytes())
        (d / ".env").write_text(ENV_HTTPS, encoding="utf-8")
        self.env = self.environnement_hors_ligne(self.tmp)
        for racine, dossiers, fichiers in os.walk(self.tmp):
            for nom in [*dossiers, *fichiers]:
                os.lchown(os.path.join(racine, nom), *UTILISATEUR)
        os.chown(self.tmp, *UTILISATEUR)
        os.chmod(self.tmp, 0o755)
        (d / "certificates" / "ca").mkdir(parents=True)  # fait par Docker : à root, 0755
        os.chmod(d / "certificates", 0o755)
        os.chmod(d / "certificates" / "ca", 0o755)
        return d

    def lancer_en_utilisateur(self, d, *commande):
        return self.lancer(list(commande), cwd=d, env=self.env, user=UTILISATEUR[0], group=UTILISATEUR[1],
                           extra_groups=[])

    def test_install_sans_certificat_ne_s_arrete_pas(self):
        d = self.installation_de_l_utilisateur()
        r = self.lancer_en_utilisateur(d, "sh", "install.sh", "--port", "8080")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("Operation not permitted", r.stdout + r.stderr)
        self.assertEqual(os.stat(d / "certificates" / "ca").st_uid, 0)  # laissé tel quel

    def test_install_ca_cert_dit_quoi_faire(self):
        d = self.installation_de_l_utilisateur()
        r = self.lancer_en_utilisateur(d, "sh", "install.sh", "--ca-cert", str(self.ca))
        self.assertNotEqual(r.returncode, 0)
        sortie = r.stdout + r.stderr
        self.assertNotIn("Operation not permitted", sortie)
        self.assertNotIn("Permission denied", sortie)
        self.assertIn("certificates/ca", sortie)
        self.assertIn("sudo", sortie)
        self.assertIn("chown", sortie)
        self.assertFalse(list((d / "certificates" / "ca").iterdir()))


class UpdateShDossiersCertificatsTests(AidesCertificat, SimpleTestCase):
    def test_dossiers_crees_avec_les_droits_d_install_sh(self):
        dossier = self.paquet_extrait()
        (dossier / ".env").write_text(ENV_HTTPS.replace("9.9.1", "9.9.0"), encoding="utf-8")
        nouveau = self.extraire(self.paquet(self.tmp, "9.9.2"), self.tmp / "nouveau")
        env = self.environnement_hors_ligne(self.tmp)
        self.assertFalse((dossier / "certificates").exists())
        r = self.lancer(["sh", "-c", 'umask 077 && exec sh update.sh --offline "$1"', "sh",
                         str(nouveau / "probant-image-9.9.2.tar.gz")], cwd=dossier, env=env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(oct(mode(dossier / "certificates")), oct(0o755))
        self.assertEqual(oct(mode(dossier / "certificates" / "ca")), oct(0o755))
        self.assertEqual(oct(mode(dossier / "certificates" / "https")), oct(0o700))
