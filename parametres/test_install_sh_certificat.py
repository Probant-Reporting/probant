"""``install.sh`` et le réseau d'entreprise, sans Docker ni réseau (faux ``docker`` de ``test_install_sh_hors_ligne``) :

- ``--domain --cert --key`` : le certificat de l'entreprise et sa clé vont dans ``certificates/https`` (clé en 0600),
  ``HTTPS_CERTIFICATE=files`` ; avec ``--offline``, l'image de Caddy du paquet est chargée (le refus de ``--offline
  --domain`` n'est levé qu'avec ``--cert`` / ``--key``) ; relancé sur une installation, il renouvelle les fichiers et
  recharge Caddy ;
- ``--ca-cert`` : l'autorité va dans ``certificates/ca`` (lisible par l'outil) ; sur une installation, l'outil redémarre ;
- tout est contrôlé avant le moindre changement ; docker-compose.yml : Caddy lit ``certificates/https``, l'outil ne
  reçoit jamais la clé. L'essai réel avec Docker : ``docker/test_custom_certificate.sh``."""
import gzip
import re
import stat
import tarfile

from django.test import SimpleTestCase

from parametres.aides_tests.scripts_installation import IMAGE_PUBLIQUE, RACINE, version_des_fichiers
from parametres.aides_tests.serveurs_tls import Autorite

from .test_install_sh_hors_ligne import AidesHorsLigne

NOM = "reporting.example.test"
ENV_HTTPS = (f"DOMAIN={NOM}\nDJANGO_HTTPS=1\nCOMPOSE_PROFILES=https\nHTTP_PORT=127.0.0.1:8000\n"
             f"IMAGE={IMAGE_PUBLIQUE}:9.9.1\n")


def mode(p):
    return stat.S_IMODE(p.stat().st_mode)


class AidesCertificat(AidesHorsLigne):
    def setUp(self):
        self.tmp = self.dossier()
        self.certs = self.tmp / "fournis"
        self.certs.mkdir()
        self.autorite = Autorite("Probant Test Company CA")
        self.ca = self.autorite.ecrire(self.certs, "company-ca")  # sans extension : rangée en .pem
        self.cert, self.cle = self.autorite.certificat_serveur(self.certs, noms=(NOM,), adresses=(), jours=90)

    def paquet_extrait(self):
        return self.extraire(self.paquet(self.tmp, "9.9.1"), self.tmp / "serveur")

    def appels_seuls(self):
        return [a for v, a in self.appels_docker(self.tmp) if not a.startswith(("save", "run "))]


class HorsLigneTests(AidesCertificat, SimpleTestCase):
    def test_paquet_avec_l_image_de_caddy(self):
        paquet = self.paquet(self.tmp, "9.9.1")
        with tarfile.open(paquet) as t:
            caddy = t.extractfile("probant/caddy-image.tar.gz").read()
            sommes = t.extractfile("probant/SHA256SUMS").read().decode()
        compose = (RACINE / "docker-compose.yml").read_text(encoding="utf-8")
        image = re.search(r"(?m)^  caddy:\n(?:    .*\n)*?    image: (\S+)", compose).group(1)
        self.assertEqual(gzip.decompress(caddy), f"IMAGE={image}\n".encode())
        self.assertIn("caddy-image.tar.gz", sommes)

    def test_installation_hors_ligne_avec_le_certificat_de_l_entreprise(self):
        dossier = self.paquet_extrait()
        env = self.environnement_hors_ligne(self.tmp)
        r = self.lancer(["sh", "install.sh", "--offline", "probant-image-9.9.1.tar.gz", "--domain", NOM,
                         "--cert", str(self.cert), "--key", str(self.cle), "--ca-cert", str(self.ca)], cwd=dossier, env=env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.valeur(dossier / ".env", "HTTPS_CERTIFICATE"), "files")
        self.assertEqual(self.valeur(dossier / ".env", "COMPOSE_PROFILES"), "https")
        https = dossier / "certificates" / "https"
        self.assertEqual((https / "certificate.pem").read_bytes(), self.cert.read_bytes())
        self.assertEqual((https / "key.pem").read_bytes(), self.cle.read_bytes())
        self.assertEqual(mode(https / "key.pem"), 0o600)
        self.assertEqual(mode(https), 0o700)
        self.assertEqual(mode(https / "certificate.pem"), 0o644)
        ca = dossier / "certificates" / "ca" / "company-ca.pem"
        self.assertEqual(ca.read_bytes(), self.ca.read_bytes())
        self.assertEqual(mode(ca), 0o644)
        appels = self.appels_seuls()
        self.assertIn(f"load -i {dossier / 'caddy-image.tar.gz'}", appels)
        self.assertIn("compose up -d --pull never", appels)
        self.assertEqual(self.reseau(self.tmp), [])
        self.assertNotIn("PRIVATE KEY", r.stdout + r.stderr)
        self.assertIn("./install.sh --cert <new certificate> --key <new key>", r.stdout)

    def test_hors_ligne_domaine_seul_toujours_refuse(self):
        dossier = self.paquet_extrait()
        env = self.environnement_hors_ligne(self.tmp)
        r = self.lancer(["sh", "install.sh", "--offline", "probant-image-9.9.1.tar.gz", "--domain", NOM], cwd=dossier,
                        env=env)
        self.assertEqual(r.returncode, 2)
        self.assertIn("--cert and --key", r.stdout)
        self.assertFalse((dossier / ".env").exists())

    def test_paquet_sans_caddy_refuse_avant_tout(self):
        dossier = self.paquet_extrait()
        (dossier / "caddy-image.tar.gz").unlink()
        sommes = dossier / "SHA256SUMS"
        sommes.write_text("".join(x for x in sommes.read_text().splitlines(True) if "caddy" not in x))
        env = self.environnement_hors_ligne(self.tmp)
        r = self.lancer(["sh", "install.sh", "--offline", "probant-image-9.9.1.tar.gz", "--domain", NOM,
                         "--cert", str(self.cert), "--key", str(self.cle)], cwd=dossier, env=env)
        self.assertEqual(r.returncode, 1)
        self.assertIn("no image of Caddy", r.stdout)
        self.assertFalse((dossier / ".env").exists())

    def test_mise_a_jour_hors_ligne_charge_caddy(self):
        dossier = self.paquet_extrait()
        (dossier / ".env").write_text(ENV_HTTPS.replace("9.9.1", "9.9.0"), encoding="utf-8")
        nouveau = self.extraire(self.paquet(self.tmp, "9.9.2"), self.tmp / "nouveau")
        env = self.environnement_hors_ligne(self.tmp)
        r = self.lancer(["sh", "update.sh", "--offline", str(nouveau / "probant-image-9.9.2.tar.gz")], cwd=dossier, env=env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(f"load -i {nouveau / 'caddy-image.tar.gz'}", self.appels_seuls())
        self.assertTrue((dossier / "certificates" / "https").is_dir())


class EnLigneTests(AidesCertificat, SimpleTestCase):
    def dossier_installation(self, env_existant=None):
        d = self.tmp / "installation"
        (d / "docker").mkdir(parents=True)
        for f in ("install.sh", "check.sh", ".env.example", "docker-compose.yml", "docker/Caddyfile"):
            (d / f).write_bytes((RACINE / f).read_bytes())
        if env_existant is not None:
            (d / ".env").write_text(env_existant, encoding="utf-8")
        return d

    def install(self, dossier, *options):
        """install.sh ; nouvelle installation : avec l'image publiée (--image), installation existante : sans."""
        env = self.environnement_hors_ligne(self.tmp)
        image = [] if (dossier / ".env").exists() else ["--image", f"{IMAGE_PUBLIQUE}:9.9.1"]
        return self.lancer(["sh", "install.sh", *image, *options], cwd=dossier, env=env)

    def test_options_controlees_avant_tout(self):
        d = self.dossier_installation()
        cas = ((["--domain", NOM, "--cert", str(self.cert)], 2, "go together"),
               (["--domain", NOM, "--key", str(self.cle)], 2, "go together"),
               (["--cert", str(self.cert), "--key", str(self.cle)], 2, "need --domain"),
               (["--domain", NOM, "--cert", str(self.certs / "absent.pem"), "--key", str(self.cle)], 1, "not found"),
               (["--ca-cert", str(self.certs / "absent.pem")], 1, "not found"))
        for options, code, mot in cas:
            with self.subTest(options):
                r = self.install(d, *options)
                self.assertEqual(r.returncode, code, r.stdout)
                self.assertIn(mot, r.stdout)
                self.assertFalse((d / ".env").exists())
                self.assertFalse((d / "certificates").exists())
        self.assertEqual(self.appels(self.tmp), [])

    def test_installation_neuve_chemins_relatifs(self):
        d = self.dossier_installation()
        env = self.environnement_hors_ligne(self.tmp)
        r = self.lancer(["sh", "installation/install.sh", "--image", f"{IMAGE_PUBLIQUE}:9.9.1", "--domain", NOM,
                         "--cert", "fournis/" + self.cert.name, "--key", "fournis/" + self.cle.name], cwd=self.tmp, env=env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual((d / "certificates/https/key.pem").read_bytes(), self.cle.read_bytes())
        self.assertEqual(self.valeur(d / ".env", "DJANGO_HTTPS"), "1")

    def test_renouvellement_sur_une_installation(self):
        d = self.dossier_installation(ENV_HTTPS)
        ancien = self.install(d, "--cert", str(self.cert), "--key", str(self.cle))
        self.assertEqual(ancien.returncode, 0, ancien.stdout + ancien.stderr)
        nouveau_cert, nouvelle_cle = self.autorite.certificat_serveur(self.tmp, noms=(NOM,), adresses=(), jours=120)
        r = self.install(d, "--cert", str(nouveau_cert), "--key", str(nouvelle_cle))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual((d / "certificates/https/certificate.pem").read_bytes(), nouveau_cert.read_bytes())
        self.assertEqual((d / "certificates/https/key.pem").read_bytes(), nouvelle_cle.read_bytes())
        self.assertEqual(mode(d / "certificates/https/key.pem"), 0o600)
        self.assertIn("compose exec -T caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile --force",
                      self.appels_seuls())
        self.assertIn("Existing .env file kept.", r.stdout)
        # la même version, rien de téléchargé (marche aussi sans accès à Internet)
        self.assertIn("compose up -d --pull never", self.appels_seuls())
        self.assertFalse([a for a in self.appels_seuls() if "pull web" in a or "build" in a])
        self.assertFalse(list((d / "certificates/https").glob("*.new")))

    def test_installation_sans_https_refusee(self):
        d = self.dossier_installation(f"DOMAIN=10.0.0.5\nHTTP_PORT=8000\nIMAGE={IMAGE_PUBLIQUE}:9.9.1\n")
        r = self.install(d, "--cert", str(self.cert), "--key", str(self.cle))
        self.assertEqual(r.returncode, 2)
        self.assertIn("no HTTPS address with Caddy", r.stdout)
        self.assertFalse((d / "certificates").exists())

    def test_autorite_ajoutee_sur_une_installation(self):
        d = self.dossier_installation(ENV_HTTPS)
        r = self.install(d, "--ca-cert", str(self.ca))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue((d / "certificates/ca/company-ca.pem").is_file())
        self.assertIn("compose restart web", self.appels_seuls())
        self.assertIsNone(self.valeur(d / ".env", "HTTPS_CERTIFICATE"))

    def test_installation_automatique_inchangee(self):
        """Sans --cert : rien de nouveau dans .env, Caddy garde le certificat automatique (CADDY_TLS vide)."""
        d = self.dossier_installation()
        r = self.install(d, "--domain", NOM)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(self.valeur(d / ".env", "HTTPS_CERTIFICATE"), ("", None))
        self.assertFalse([a for a in self.appels_seuls() if "reload" in a or "restart" in a])
        self.assertTrue((d / "certificates/ca").is_dir())


class ComposeTests(SimpleTestCase):
    def test_caddy_seul_lit_le_certificat(self):
        compose = (RACINE / "docker-compose.yml").read_text(encoding="utf-8")
        web = compose[compose.index("\n  web:\n"):compose.index("\n  caddy:\n")]
        caddy = compose[compose.index("\n  caddy:\n"):compose.index("\n  db:\n")]
        self.assertNotRegex(web, r"(?m)^ +- [^#\n]*certificates/https")
        self.assertIn("./certificates/https:/etc/probant/https:ro", caddy)
        self.assertIn("CADDY_TLS: ${HTTPS_CERTIFICATE:+tls /etc/probant/https/certificate.pem /etc/probant/https/key.pem}",
                      caddy)
        self.assertIn("{$CADDY_TLS}", (RACINE / "docker" / "Caddyfile").read_text(encoding="utf-8"))

    def test_jamais_dans_l_image_ni_dans_git(self):
        self.assertIn("certificates/", (RACINE / ".dockerignore").read_text(encoding="utf-8").splitlines())
        self.assertIn("/certificates/", (RACINE / ".gitignore").read_text(encoding="utf-8").splitlines())


class EssaiReelTests(SimpleTestCase):
    def test_essai_reel_dans_la_tache_docker(self):
        import os

        from parametres.test_workflows_publics import tache
        bloc = tache("tests.yml", "docker")
        etape = bloc[bloc.index("Certificate of the company (HTTPS)"):]
        etape = etape[:etape.index("- name:")] if "- name:" in etape else etape
        self.assertIn("if: matrix.database == 'sqlite'", etape)
        self.assertIn("IMAGE_UNDER_TEST=probant:local bash docker/test_custom_certificate.sh", etape)
        self.assertTrue(os.access(RACINE / "docker" / "test_custom_certificate.sh", os.X_OK))


class GetShTests(AidesCertificat, SimpleTestCase):
    """get.sh passe --cert, --key et --ca-cert à install.sh (chemins lus depuis le dossier de la commande)."""

    def get_sh(self, etiquettes, *options):
        depot = self.depot(etiquettes or {"V9.9.1": version_des_fichiers("9.9.1")}, "V9.9.1")
        env = self.environnement(self.tmp, depot)
        return self.lancer(["sh", str(RACINE / "get.sh"), *options], cwd=self.tmp, env=env)

    def test_options_passees_a_install_sh(self):
        r = self.get_sh(None, "--domain", NOM, "--cert", f"fournis/{self.cert.name}", "--key", f"fournis/{self.cle.name}",
                        "--ca-cert", "fournis/company-ca")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        d = self.tmp / "probant"
        self.assertEqual(self.valeur(d / ".env", "HTTPS_CERTIFICATE"), "files")
        self.assertEqual((d / "certificates/https/key.pem").read_bytes(), self.cle.read_bytes())
        self.assertTrue((d / "certificates/ca/company-ca.pem").is_file())

    def test_version_d_avant_ces_options_refusee(self):
        ancienne = version_des_fichiers("9.9.1")
        ancienne["install.sh"] = ancienne["install.sh"].replace(b"--cert)", b"--x)")
        r = self.get_sh({"V9.9.1": ancienne}, "--domain", NOM, "--cert", str(self.cert), "--key", str(self.cle))
        self.assertEqual(r.returncode, 1)
        self.assertIn("came before --cert", r.stdout)
        self.assertFalse((self.tmp / "probant" / ".env").exists())
