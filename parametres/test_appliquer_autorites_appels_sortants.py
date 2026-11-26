"""Autorités de certification ajoutées par l'IT (``EXTRA_CA_CERTS``, ``config/autorites_certificats.py``) : CHAQUE
chemin d'appel sortant de l'outil les respecte, sans que son module le sache.

Pour de vrai, sans réseau : une autorité de test créée dans le test signe le certificat de faux serveurs locaux (SMTP en
STARTTLS et en SSL, HTTPS). Chaque essai tourne dans un processus Python neuf qui lit les réglages de l'outil au
démarrage, comme le serveur : sans l'autorité, chaque appel est refusé (certificat inconnu) ; avec elle, il passe.
Chemins essayés : moteur SMTP de Django par le point unique ``envoi_emails.connexion_envoi`` (STARTTLS et SSL), copie
externe des sauvegardes vers un stockage S3 (``copie_s3``), prise IA
(``ia_fournisseurs._ouvrir``), ``urllib.request.urlopen`` et ``http.client`` sans contexte (ce qu'un module futur ferait,
la connexion OIDC par exemple), ``httpx2`` (client des tests de l'assistant MCP). Les autorités publiques restent de
confiance ; un fichier illisible, sans certificat ou qui n'est pas une autorité est dit au démarrage et écarté, et
l'outil démarre quand même."""
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

from django.test import SimpleTestCase

from config import autorites_certificats as AC
from parametres.aides_tests.serveurs_tls import (RACINE, Autorite, ServeurHttps, ServeurSmtp, dossier_temporaire,
                                                 environnement, lancer_python)

# Le processus de l'outil : réglages lus au démarrage, puis chaque chemin d'appel ; un résultat JSON par chemin.
ESSAI = r"""
import json, os, sys
import django
django.setup()
resultats = {}
def essayer(nom, appel):
    try:
        appel()
        resultats[nom] = "ok"
    except Exception as e:  # noqa: BLE001
        resultats[nom] = f"{type(e).__name__}: {e}"

URL = os.environ["ESSAI_URL"]

def smtp(securite, port):
    def envoyer():
        from django.conf import settings
        from django.core.mail import EmailMessage
        from parametres import envoi_emails as EE
        settings.EMAIL_PORT = int(port)
        settings.EMAIL_USE_TLS = securite == "starttls"
        settings.EMAIL_USE_SSL = securite == "ssl"
        connexion, expediteur = EE.connexion_envoi(timeout=10)
        EmailMessage("Essai", "Texte", expediteur, ["destinataire@example.test"], connection=connexion).send()
    return envoyer

def ia():
    import urllib.request
    from parametres import ia_fournisseurs as F
    F._ouvrir(urllib.request.Request(URL), 10).read()

def urllib_sans_contexte():
    import urllib.request
    urllib.request.urlopen(URL, timeout=10).read()

def http_client():
    import http.client
    c = http.client.HTTPSConnection("localhost", int(os.environ["ESSAI_PORT"]), timeout=10)
    c.request("GET", "/")
    c.getresponse().read()

def copie_s3():  # copie externe des sauvegardes vers un stockage compatible S3 (parametres/copie_s3.py)
    from django.conf import settings
    settings.COPIE_EXTERNE_LOCAL = True  # faux serveur sur la machine elle-même
    from parametres.copie_s3 import ClientS3
    with ClientS3(URL.rstrip("/"), "", "compartiment", "path", "ID", "secret", delai=10, essais=1) as c:
        c.lire("objet")

def httpx2_():
    import httpx2
    httpx2.get(URL, timeout=10).raise_for_status()

essayer("smtp_starttls", smtp("starttls", os.environ["ESSAI_SMTP_STARTTLS"]))
essayer("smtp_ssl", smtp("ssl", os.environ["ESSAI_SMTP_SSL"]))
essayer("ia", ia)
essayer("urllib", urllib_sans_contexte)
essayer("http_client", http_client)
essayer("copie_s3", copie_s3)
try:
    import httpx2  # noqa: F401
    essayer("httpx2", httpx2_)
except ImportError:
    pass
print("RESULTATS " + json.dumps(resultats))
"""
CHEMINS = ("smtp_starttls", "smtp_ssl", "ia", "urllib", "http_client", "copie_s3")
# cause en clair de la copie externe (jamais le texte de l'erreur TLS) : « certificat »
REFUS = {"copie_s3": "certificat"}


class AidesAutorites:
    def preparer(self):
        self.tmp = dossier_temporaire(self)
        (self.tmp / "data").mkdir()
        self.autorite = Autorite()
        contexte = self.autorite.contexte_serveur(self.tmp)
        self.https = ServeurHttps(contexte)
        self.starttls = ServeurSmtp(contexte, "starttls")
        self.ssl = ServeurSmtp(contexte, "ssl")
        for s in (self.https, self.starttls, self.ssl):
            self.addCleanup(s.fermer)

    def env(self, **variables):
        return environnement(DATA_DIR=self.tmp / "data", SMTP_HOST="localhost", SMTP_FROM="outil@example.test",
                             ESSAI_URL=self.https.url, ESSAI_PORT=self.https.port, ESSAI_SMTP_STARTTLS=self.starttls.port,
                             ESSAI_SMTP_SSL=self.ssl.port, NO_PROXY="*", no_proxy="*", **variables)

    def essai(self, **variables):
        r = lancer_python(ESSAI, self.env(**variables))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        ligne = [x for x in r.stdout.splitlines() if x.startswith("RESULTATS ")]
        self.assertTrue(ligne, r.stdout + r.stderr)
        r.resultats = json.loads(ligne[-1][len("RESULTATS "):])
        return r


class ChaqueCheminTests(AidesAutorites, SimpleTestCase):
    def setUp(self):
        self.preparer()

    def test_sans_l_autorite_chaque_appel_est_refuse(self):
        r = self.essai()
        for chemin in CHEMINS + tuple(x for x in ("httpx2",) if x in r.resultats):
            with self.subTest(chemin):
                self.assertIn(REFUS.get(chemin, "CERTIFICATE_VERIFY_FAILED"), r.resultats[chemin])
        self.assertEqual(self.starttls.recus + self.ssl.recus, [])

    def test_avec_l_autorite_chaque_appel_passe(self):
        fichier = self.autorite.ecrire(self.tmp)
        r = self.essai(EXTRA_CA_CERTS=fichier)
        for chemin in CHEMINS + tuple(x for x in ("httpx2",) if x in r.resultats):
            with self.subTest(chemin):
                self.assertEqual(r.resultats[chemin], "ok")
        self.assertEqual(len(self.starttls.recus), 1)
        self.assertEqual(len(self.ssl.recus), 1)
        self.assertIn(b"Subject: Essai", self.ssl.recus[0])
        self.assertEqual(r.stderr, "", "aucun message quand tout va bien")

    def test_httpx2_essaye_quand_il_est_installe(self):
        """httpx2 est une dépendance des tests (assistant MCP) : son chemin est bien essayé ici."""
        try:
            import httpx2  # noqa: F401
        except ImportError:
            self.skipTest("httpx2 absent")
        fichier = self.autorite.ecrire(self.tmp)
        self.assertEqual(self.essai(EXTRA_CA_CERTS=fichier).resultats["httpx2"], "ok")

    def test_dossier_de_fichiers(self):
        """Un dossier (celui de l'image Docker) : ses fichiers .pem, .crt, .cer ; les autres sont laissés."""
        dossier = self.tmp / "ca"
        dossier.mkdir()
        self.autorite.ecrire(dossier, "interne.crt")
        (dossier / "LISEZ-MOI.txt").write_text("rien", encoding="utf-8")
        r = self.essai(EXTRA_CA_CERTS=dossier)
        self.assertEqual(r.resultats["ia"], "ok")
        self.assertEqual(r.resultats["smtp_starttls"], "ok")

    def test_les_autorites_publiques_restent_de_confiance(self):
        """La base du système (ici : une autre autorité, donnée par SSL_CERT_FILE comme le ferait le système) reste dans
        le fichier réuni : un serveur qu'elle signe reste joignable avec l'autorité interne ajoutée."""
        publique = Autorite("Public Root Test")
        base = self.tmp / "systeme.pem"
        base.write_bytes(publique.pem)
        serveur = ServeurHttps(publique.contexte_serveur(self.tmp / "data"))
        self.addCleanup(serveur.fermer)
        interne = self.autorite.ecrire(self.tmp)
        env = self.env(EXTRA_CA_CERTS=interne, SSL_CERT_FILE=base)
        env.update({"ESSAI_URL": serveur.url, "ESSAI_PORT": str(serveur.port)})
        r = lancer_python(ESSAI, env)
        resultats = json.loads(r.stdout.split("RESULTATS ")[-1])
        self.assertEqual(resultats["urllib"], "ok", "autorité « publique » de la base")
        self.assertEqual(resultats["smtp_ssl"], "ok", "autorité interne ajoutée")

    def test_fichier_reuni_commence_par_les_autorites_du_systeme(self):
        base = AC.base_systeme({})
        if base is None:
            self.skipTest("aucun fichier d'autorités sur ce système")
        fichier = self.autorite.ecrire(self.tmp)
        environ = {AC.VARIABLE: str(fichier)}
        chemin = AC.preparer(environ, self.tmp / "data")
        texte = chemin.read_text(encoding="ascii")
        systeme = base.read_text(encoding="ascii", errors="replace").rstrip("\n")
        self.assertTrue(texte.startswith(systeme))
        self.assertIn(self.autorite.pem.decode("ascii").strip(), texte)
        self.assertEqual(environ["SSL_CERT_FILE"], str(chemin))
        self.assertEqual(environ["REQUESTS_CA_BUNDLE"], str(chemin))
        self.assertEqual(stat.S_IMODE(chemin.stat().st_mode) & 0o077, 0)


class FichiersEcartesTests(AidesAutorites, SimpleTestCase):
    def setUp(self):
        self.preparer()

    def test_fichiers_qui_ne_sont_pas_des_autorites_dits_au_demarrage_l_outil_demarre(self):
        bonne = self.autorite.ecrire(self.tmp)
        serveur, _ = self.autorite.certificat_serveur(self.tmp, noms=("serveur.example.test",))
        texte = self.tmp / "texte.pem"
        texte.write_text("ceci n'est pas un certificat\n", encoding="utf-8")
        absent = self.tmp / "absent.pem"
        illisible = self.tmp / "illisible.pem"
        illisible.write_bytes(self.autorite.pem)
        illisible.chmod(0)
        self.addCleanup(illisible.chmod, 0o600)
        valeur = os.pathsep.join(str(p) for p in (serveur, texte, absent, illisible, bonne))
        r = self.essai(EXTRA_CA_CERTS=valeur)
        self.assertIn(f"{serveur} holds a certificate that is not a certificate authority", r.stderr)
        self.assertIn(f"{texte} holds no certificate in PEM format", r.stderr)
        self.assertIn(f"{absent} not found", r.stderr)
        if os.geteuid() != 0:  # root lit tout
            self.assertIn(f"{illisible} cannot be read", r.stderr)
        # la bonne autorité reste en service
        self.assertEqual(r.resultats["ia"], "ok")

    def test_aucune_autorite_valable_l_outil_demarre_avec_celles_du_systeme(self):
        serveur, _ = self.autorite.certificat_serveur(self.tmp, noms=("serveur.example.test",))
        r = self.essai(EXTRA_CA_CERTS=serveur)
        self.assertIn("not a certificate authority", r.stderr)
        self.assertIn("No added certificate authority is in use", r.stderr)
        self.assertIn("CERTIFICATE_VERIFY_FAILED", r.resultats["ia"])

    def test_autorite_expiree_dite_au_demarrage(self):
        vieille = Autorite("Old Internal CA", jours=-2)
        bientot = Autorite("Soon Internal CA", jours=10)
        dossier = self.tmp / "ca"
        dossier.mkdir()
        vieille.ecrire(dossier, "vieille.pem")
        bientot.ecrire(dossier, "bientot.pem")
        r = self.essai(EXTRA_CA_CERTS=dossier)
        self.assertIn('"Old Internal CA"', r.stderr)
        self.assertIn("expired on", r.stderr)
        self.assertIn('"Soon Internal CA"', r.stderr)
        self.assertIn("replace it soon", r.stderr)


class DemarrageDeLImageTests(AidesAutorites, SimpleTestCase):
    """docker/entrypoint.sh : ``python -m config.autorites_certificats`` une fois, puis les processus de l'outil reçoivent
    SSL_CERT_FILE et la marque ; ils ne refont rien (aucun message en double)."""

    def setUp(self):
        self.preparer()

    def test_une_fois_pour_tous_les_processus(self):
        serveur, _ = self.autorite.certificat_serveur(self.tmp, noms=("serveur.example.test",))
        valeur = os.pathsep.join([str(serveur), str(self.autorite.ecrire(self.tmp))])
        env = self.env(EXTRA_CA_CERTS=valeur)
        r = subprocess.run([sys.executable, "-m", "config.autorites_certificats"], cwd=RACINE, env=env,
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        chemin = r.stdout.strip()
        self.assertEqual(chemin, str(self.tmp / "data" / AC.FICHIER))
        self.assertIn("not a certificate authority", r.stderr)
        env.update({"SSL_CERT_FILE": chemin, "REQUESTS_CA_BUNDLE": chemin, AC.MARQUE: chemin})
        enfant = lancer_python(ESSAI, env)
        self.assertEqual(enfant.stderr, "", "message déjà donné par le démarrage de l'image")
        self.assertIn('"ia": "ok"', enfant.stdout)

    def test_rien_de_demande_rien_ne_change(self):
        env = self.env(EXTRA_CA_CERTS="")
        r = subprocess.run([sys.executable, "-m", "config.autorites_certificats"], cwd=RACINE, env=env,
                           capture_output=True, text=True, timeout=60)
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))
        self.assertFalse((self.tmp / "data" / AC.FICHIER).exists())
        environ = {"SSL_CERT_FILE": "/etc/ssl/autre.pem"}
        self.assertIsNone(AC.appliquer(environ, self.tmp / "data"))
        self.assertEqual(environ, {"SSL_CERT_FILE": "/etc/ssl/autre.pem"})

    def test_l_image_monte_le_dossier_des_autorites(self):
        entree = (RACINE / "docker" / "entrypoint.sh").read_text(encoding="utf-8")
        self.assertIn("python -m config.autorites_certificats", entree)
        self.assertIn('export SSL_CERT_FILE="$BUNDLE" REQUESTS_CA_BUNDLE="$BUNDLE" PROBANT_CA_BUNDLE="$BUNDLE"', entree)
        self.assertLess(entree.index("config.autorites_certificats"), entree.index("python manage.py startup"))
        self.assertIn("ENV EXTRA_CA_CERTS=/etc/probant/ca", (RACINE / "Dockerfile").read_text(encoding="utf-8"))
        compose = (RACINE / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn("./certificates/ca:/etc/probant/ca:ro", compose)
        self.assertIn("EXTRA_CA_CERTS: /etc/probant/ca", compose)
        self.assertTrue(Path(RACINE / ".env.example").read_text(encoding="utf-8").count("EXTRA_CA_CERTS") >= 1)
