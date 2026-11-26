"""``check.sh`` et le réseau d'entreprise : certificat HTTPS fourni par l'IT (``--cert``, ``--key``) et autorités de
certification de l'entreprise (``--ca-cert``).

Certificats réels faits dans le test (autorité de test, ``parametres/aides_tests/serveurs_tls.py``), lus par le vrai
``openssl`` ; le reste de la machine est simulé (``faux_diagnostic``). Contrôles : la clé correspond au certificat, le
certificat couvre le nom de domaine, il n'a pas expiré (avertissement à moins de 30 jours), sa chaîne est complète
(avertissement sinon) ; une autorité qui n'en est pas une est refusée ; les contrôles du réseau utilisent l'autorité
(``curl --cacert``) ; avec le certificat de l'entreprise, le DNS n'est qu'un avertissement, aussi hors ligne."""
import shutil

from django.test import SimpleTestCase

from parametres.aides_tests.faux_diagnostic import journal_reseau
from parametres.aides_tests.serveurs_tls import Autorite

from .test_check_sh_diagnostic import IMAGE, AidesDiagnostic

NOM = "reporting.example.test"
BON_DNS = {"F_ADRESSES_DU_NOM": "203.0.113.10"}


class AidesCertificats(AidesDiagnostic):
    def setUp(self):
        if not shutil.which("openssl"):
            self.skipTest("openssl absent de cette machine")
        self.certs = self.dossier()
        self.autorite = Autorite("Probant Test Company CA")
        self.ca = self.autorite.ecrire(self.certs, "company-ca.pem")
        self.cert, self.cle = self.autorite.certificat_serveur(self.certs, noms=(NOM,), adresses=(), jours=90)

    def options(self, *autres, cert=None, cle=None, ca=True):
        o = ["--image", IMAGE, "--domain", NOM, "--cert", str(cert or self.cert), "--key", str(cle or self.cle)]
        if ca:
            o += ["--ca-cert", str(self.ca)]
        return [*o, *autres]


class CertificatTests(AidesCertificats, SimpleTestCase):
    def test_tout_bon(self):
        r = self.diagnostic(*self.options(), **BON_DNS)
        self.assertPret(r)
        self.assertEtat(r, "Private key", "OK", "matches the certificate")
        self.assertEtat(r, "HTTPS certificate: valid until", "OK")
        self.assertEtat(r, f"HTTPS certificate: covers {NOM}", "OK")
        self.assertEtat(r, "Chain of the certificate", "OK", "complete")
        self.assertEtat(r, "Certificate authority", "OK", "Probant Test Company CA", "valid until")
        # la clé n'est jamais montrée
        self.assertNotIn("PRIVATE KEY", r.stdout + r.stderr)

    def test_cle_d_un_autre_certificat(self):
        _, autre_cle = self.autorite.certificat_serveur(self.dossier(), noms=("autre.example.test",))
        r = self.diagnostic(*self.options(cle=autre_cle), **BON_DNS)
        self.assertEtat(r, "Private key", "To fix", "does not match the certificate")
        self.assertManque(r, "does not match")

    def test_cle_avec_mot_de_passe_ou_pas_une_cle(self):
        faux = self.certs / "faux.key"
        faux.write_text("pas une clé\n", encoding="utf-8")
        r = self.diagnostic(*self.options(cle=faux), **BON_DNS)
        self.assertEtat(r, "Private key", "To fix", "not a private key in PEM format, or protected by a password")

    def test_nom_non_couvert(self):
        cert, cle = self.autorite.certificat_serveur(self.dossier(), noms=("autre.example.test",), adresses=(), jours=90)
        r = self.diagnostic(*self.options(cert=cert, cle=cle), **BON_DNS)
        texte = self.assertEtat(r, f"HTTPS certificate: does not cover {NOM}", "To fix", "autre.example.test")
        self.assertIn(f"Ask for a certificate for {NOM}", texte)
        self.assertEqual(r.returncode, 1)

    def test_expire(self):
        cert, cle = self.autorite.certificat_serveur(self.dossier(), noms=(NOM,), adresses=(), jours=-1)
        r = self.diagnostic(*self.options(cert=cert, cle=cle), **BON_DNS)
        self.assertEtat(r, "HTTPS certificate: expired on", "To fix")
        self.assertManque(r, "expired on")

    def test_expire_bientot_avertissement(self):
        cert, cle = self.autorite.certificat_serveur(self.dossier(), noms=(NOM,), adresses=(), jours=10)
        r = self.diagnostic(*self.options(cert=cert, cle=cle), **BON_DNS)
        self.assertPret(r)
        self.assertEtat(r, "HTTPS certificate: expires on", "Warning", "less than 30 days")
        self.assertIn("Ready. 1 warning(s)", r.stdout)

    def test_chaine_incomplete_avertissement(self):
        """Sans l'autorité de l'entreprise, la chaîne ne remonte à aucune autorité connue : avertissement, pas d'arrêt."""
        r = self.diagnostic(*self.options(ca=False), **BON_DNS)
        self.assertPret(r)
        self.assertEtat(r, "Chain of the certificate", "Warning", "intermediate certificates", "--ca-cert")

    def test_chaine_avec_intermediaire(self):
        """Certificat signé par une autorité intermédiaire : complet quand le fichier contient l'intermédiaire."""
        from cryptography import x509
        from cryptography.hazmat.primitives import serialization

        intermediaire = Autorite("Probant Test Intermediate CA")
        # l'intermédiaire, signé par la racine de l'entreprise
        import datetime

        from cryptography.hazmat.primitives import hashes
        maintenant = datetime.datetime.now(datetime.timezone.utc)
        signe = (x509.CertificateBuilder().subject_name(intermediaire.certificat.subject)
                 .issuer_name(self.autorite.certificat.subject).public_key(intermediaire.cle.public_key())
                 .serial_number(x509.random_serial_number()).not_valid_before(maintenant - datetime.timedelta(days=1))
                 .not_valid_after(maintenant + datetime.timedelta(days=200))
                 .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
                 .add_extension(x509.SubjectKeyIdentifier.from_public_key(intermediaire.cle.public_key()), critical=False)
                 .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(self.autorite.cle.public_key()),
                                critical=False)
                 .sign(self.autorite.cle, hashes.SHA256()))
        intermediaire.certificat = signe
        d = self.dossier()
        cert, cle = intermediaire.certificat_serveur(d, noms=(NOM,), adresses=(), jours=90)
        seul = self.diagnostic(*self.options(cert=cert, cle=cle), **BON_DNS)
        self.assertEtat(seul, "Chain of the certificate", "Warning")
        chaine = d / "chaine.pem"
        chaine.write_bytes(cert.read_bytes() + signe.public_bytes(serialization.Encoding.PEM))
        r = self.diagnostic(*self.options(cert=chaine, cle=cle), **BON_DNS)
        self.assertEtat(r, "Chain of the certificate", "OK", "2 certificate(s)")

    def test_options(self):
        self.assertEqual(self.diagnostic("--cert", str(self.cert)).returncode, 2)
        self.assertEqual(self.diagnostic("--key", str(self.cle)).returncode, 2)
        self.assertEqual(self.diagnostic("--ca-cert").returncode, 2)
        aide = self.diagnostic("--help").stdout
        for o in ("--cert FILE --key FILE", "--ca-cert FILE", "--certificate-only"):
            self.assertIn(o, aide)

    def test_certificat_seulement(self):
        r = self.diagnostic("--certificate-only", *self.options(), F_MEMOIRE="100")
        self.assertPret(r)
        self.assertIn("Check of the certificates of the installation", r.stdout)
        self.assertNotIn("Memory", r.stdout)
        self.assertNotIn("Docker", r.stdout)
        self.assertEqual(journal_reseau(r.tmp), [])

    def test_sans_openssl(self):
        r = self.diagnostic(*self.options(), absents=("openssl",), **BON_DNS)
        self.assertEtat(r, "HTTPS certificate: the command openssl is missing", "Not checked")
        self.assertEqual(r.returncode, 0, r.stdout)


class DnsAvecCertificatTests(AidesCertificats, SimpleTestCase):
    def test_nom_introuvable_avertissement_seulement(self):
        r = self.diagnostic(*self.options())
        self.assertEtat(r, f"Domain name {NOM}: not found in the DNS", "Warning")
        self.assertPret(r)
        # sans le certificat de l'entreprise : à corriger, comme avant
        r = self.diagnostic("--image", IMAGE, "--domain", NOM)
        self.assertEtat(r, f"Domain name {NOM}: not found in the DNS", "To fix")

    def test_hors_ligne_le_nom_est_controle(self):
        o = ["--offline", "--domain", NOM, "--cert", str(self.cert), "--key", str(self.cle), "--ca-cert", str(self.ca)]
        r = self.diagnostic(*o, **BON_DNS)
        self.assertEtat(r, f"Domain name {NOM}: points to this server", "OK")
        self.assertEtat(r, "Private key", "OK")
        self.assertPret(r)


class AutoritesTests(AidesCertificats, SimpleTestCase):
    def test_les_controles_du_reseau_utilisent_l_autorite(self):
        r = self.diagnostic("--image", IMAGE, "--ca-cert", str(self.ca))
        self.assertPret(r)
        appels = [x for x in journal_reseau(r.tmp) if x.startswith("curl ")]
        self.assertTrue(appels)
        self.assertTrue(all("--cacert " in x for x in appels), appels)
        self.assertEtat(r, "Docker and the authority of your company", "Not checked", "docs.docker.com")
        # sans autorité : curl et ses autorités habituelles
        r = self.diagnostic("--image", IMAGE)
        self.assertFalse([x for x in journal_reseau(r.tmp) if "--cacert" in x])
        self.assertNotIn("authority of your company", r.stdout)

    def test_fichier_temporaire_efface(self):
        r = self.diagnostic("--image", IMAGE, "--ca-cert", str(self.ca))
        fichier = next(x for x in journal_reseau(r.tmp) if "--cacert" in x).split("--cacert ")[1].split()[0]
        self.assertTrue(fichier.endswith("ca-bundle.pem"))
        from pathlib import Path
        self.assertFalse(Path(fichier).exists())

    def test_certificat_de_serveur_refuse_comme_autorite(self):
        r = self.diagnostic("--image", IMAGE, "--ca-cert", str(self.cert))
        self.assertEtat(r, "Certificate authority", "To fix", "not the certificate of an authority")
        self.assertEqual(r.returncode, 1)
        texte = self.certs / "texte.pem"
        texte.write_text("rien\n", encoding="utf-8")
        r = self.diagnostic("--image", IMAGE, "--ca-cert", str(texte))
        self.assertEtat(r, "Certificate authority", "To fix", "no certificate in PEM format")
        r = self.diagnostic("--image", IMAGE, "--ca-cert", str(self.certs / "absent.pem"))
        self.assertEtat(r, "Certificate authority", "To fix", "cannot be read")

    def test_autorite_expiree_ou_bientot(self):
        vieille = Autorite("Old CA", jours=-1).ecrire(self.certs, "vieille.pem")
        bientot = Autorite("Soon CA", jours=5).ecrire(self.certs, "bientot.pem")
        r = self.diagnostic("--image", IMAGE, "--ca-cert", str(vieille), "--ca-cert", str(bientot))
        self.assertEtat(r, "Certificate authority CN=Old CA", "To fix", "expired on")
        self.assertEtat(r, "Certificate authority CN=Soon CA", "Warning", "less than 30 days")

    def test_dossier_de_l_installation_lu_tout_seul(self):
        """Installation existante : les autorités de certificates/ca (posées par install.sh --ca-cert) sont reprises."""
        tmp = self.dossier()
        (tmp / "certificates" / "ca").mkdir(parents=True)
        self.autorite.ecrire(tmp / "certificates" / "ca", "company.pem")
        from parametres.aides_tests.faux_diagnostic import preparer_faux

        from .test_check_sh_diagnostic import RACINE
        chemin, variables = preparer_faux(tmp)
        env = self.environnement(tmp, chemin=chemin, diagnostic=True, **variables)
        r = self.lancer(["sh", str(RACINE / "check.sh"), "--image", IMAGE], cwd=tmp, env=env)
        self.assertIn("Certificate authority CN=Probant Test Company CA (certificates/ca/company.pem)", r.stdout)
        self.assertTrue(all("--cacert" in x for x in journal_reseau(tmp) if x.startswith("curl ")))
