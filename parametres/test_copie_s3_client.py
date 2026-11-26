"""Client du stockage compatible S3 de la copie externe (``copie_s3.ClientS3``), contre un faux stockage local qui vérifie
la signature et l'empreinte de chaque envoi (``aides_tests/faux_s3.py``) : dépôt en un envoi et en morceaux, relecture,
liste par pages, suppression ; causes en clair sans jamais recopier le message du service ; nouveaux essais bornés ;
connexion coupée pendant un dépôt puis reprise ; envoi abandonné annulé ; autorité de certification interne
(``SSL_CERT_FILE``) prise en compte par le contexte TLS par défaut."""
import hashlib
import os
import tempfile
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase, override_settings

from parametres import copie_s3 as S
from parametres.aides_tests.faux_s3 import ID, SECRET, FauxS3
from parametres.copie_reseau import ErreurCopie

SANS_PROXY = mock.patch.dict(os.environ, {k: "" for k in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy",
                                                           "ALL_PROXY", "all_proxy")})


def fichier(dossier, taille, nom="archive.zip"):
    p = Path(dossier) / nom
    contenu = os.urandom(taille)
    p.write_bytes(contenu)
    return p, hashlib.sha256(contenu).hexdigest(), contenu


@override_settings(COPIE_EXTERNE_LOCAL=True)
@SANS_PROXY
class ClientTests(SimpleTestCase):
    def setUp(self):
        self.faux = FauxS3(page=2)
        self.addCleanup(self.faux.fermer)
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)

    def ouvrir(self, secret=SECRET, compartiment="sauvegardes", **k):
        return S.ClientS3(self.faux.adresse, "", compartiment, "auto", ID, secret, base="pre/inst/", delai=5, pause=0.01, **k)

    def test_deposer_relire_lister_supprimer(self):
        p, sha, contenu = fichier(self.tmp, 3000)
        with self.ouvrir() as c:
            c.deposer("backup-20261101-023000-auto.zip", p, 3000, sha)
            for i in range(3):
                c.deposer(f"spaces/achats/backup-2026110{i + 1}-023000-auto.zip", p, 3000, sha)
            self.assertEqual(c.taille("backup-20261101-023000-auto.zip"), (3000, sha))
            self.assertIsNone(c.taille("absente.zip"))
            self.assertEqual(c.lire("backup-20261101-023000-auto.zip"), contenu)
            liste = c.lister()  # 4 objets, pages de 2 : la suite est lue
            self.assertEqual(len(liste), 4)
            self.assertIn(("spaces/achats/backup-20261103-023000-auto.zip", 3000), liste)
            c.supprimer("backup-20261101-023000-auto.zip")
            c.supprimer("backup-20261101-023000-auto.zip")  # déjà absente : sans erreur
            self.assertIsNone(c.taille("backup-20261101-023000-auto.zip"))
        self.assertIn("pre/inst/spaces/achats/backup-20261101-023000-auto.zip", self.faux.objets)
        self.assertEqual(self.faux.signatures_refusees, 0)

    def test_grosse_archive_en_morceaux(self):
        p, sha, contenu = fichier(self.tmp, 5 * 1024 + 17)
        with mock.patch.object(S, "MORCEAU", 1024), self.ouvrir() as c:
            c.deposer("backup-20261101-023000-auto.zip", p, len(contenu), sha)
        o = self.faux.objets["pre/inst/backup-20261101-023000-auto.zip"]
        self.assertEqual((o.contenu, o.sha, o.meta), (contenu, sha, sha))
        parts = [r for r in self.faux.requetes if r[0] == "PUT" and "partNumber" in r[2]]
        self.assertEqual(len(parts), 6)
        self.assertEqual(self.faux.envois, {})

    def test_causes_en_clair_sans_le_message_du_service(self):
        p, sha, _ = fichier(self.tmp, 100)
        cas = [(dict(secret="autre-secret"), "identifiants"), (dict(compartiment="absent"), "compartiment")]
        for options, cause in cas:
            with self.subTest(cause=cause), self.ouvrir(**options) as c:
                with self.assertRaises(ErreurCopie) as e:
                    c.deposer("backup-20261101-023000-auto.zip", p, 100, sha)
                self.assertEqual(e.exception.code, cause)
                self.assertNotIn("message-interne-du-service", str(e.exception) + e.exception.resume)
        self.faux.refus = {"PUT"}
        with self.ouvrir() as c, self.assertRaises(ErreurCopie) as e:
            c.deposer("backup-20261101-023000-auto.zip", p, 100, sha)
        self.assertEqual((e.exception.code, e.exception.resume), ("droits_ecrire", "HTTP 403 AccessDenied"))
        self.faux.refus = {"DELETE"}
        with self.ouvrir() as c, self.assertRaises(ErreurCopie) as e:
            c.supprimer("x.zip")
        self.assertEqual(e.exception.code, "droits_supprimer")
        with self.ouvrir(secret="autre") as c, self.assertRaises(ErreurCopie) as e:
            c.taille("x.zip")  # HEAD : pas de corps, la cause reste générale
        self.assertEqual(e.exception.code, "acces")

    def test_service_momentanement_indisponible_puis_borne(self):
        p, sha, _ = fichier(self.tmp, 100)
        self.faux.pannes = 2
        with self.ouvrir() as c:
            c.deposer("backup-20261101-023000-auto.zip", p, 100, sha)  # 2 refus 503, puis réussi au 3e essai
        self.faux.pannes = 10
        with self.ouvrir() as c, self.assertRaises(ErreurCopie) as e:
            c.deposer("backup-20261102-023000-auto.zip", p, 100, sha)
        self.assertEqual((e.exception.code, e.exception.resume), ("service", "HTTP 503 SlowDown"))
        self.assertEqual(self.faux.pannes, 10 - 3)  # 3 essais au plus

    def test_connexion_coupee_pendant_un_depot_reprise(self):
        p, sha, contenu = fichier(self.tmp, 4000)
        self.faux.couper_apres = 1000
        with self.ouvrir() as c:
            c.deposer("backup-20261101-023000-auto.zip", p, 4000, sha)
        self.assertEqual(self.faux.objets["pre/inst/backup-20261101-023000-auto.zip"].contenu, contenu)

    def test_envoi_en_morceaux_abandonne_est_annule(self):
        p, sha, contenu = fichier(self.tmp, 5000)
        with mock.patch.object(S, "MORCEAU", 1024), self.ouvrir(essais=1) as c:
            self.faux.refus = set()
            original = c._envoyer

            def panne(methode, *a, **k):
                if methode == "PUT" and ("partNumber", "3") in list(k.get("params", ())):
                    raise ErreurCopie("coupee", "simulated")
                return original(methode, *a, **k)
            with mock.patch.object(c, "_envoyer", side_effect=panne), self.assertRaises(ErreurCopie):
                c.deposer("backup-20261101-023000-auto.zip", p, 5000, sha)
        self.assertEqual(self.faux.envois, {})  # annulé chez le service
        self.assertNotIn("pre/inst/backup-20261101-023000-auto.zip", self.faux.objets)

    def test_style_d_adresse(self):
        c = S.ClientS3("https://s3.eu-west-3.amazonaws.com", "eu-west-3", "mon-compartiment", "auto", ID, SECRET)
        self.assertEqual((c.entete_hote, c._chemin("a b.zip")), ("mon-compartiment.s3.eu-west-3.amazonaws.com", "/a%20b.zip"))
        c = S.ClientS3("https://stockage.exemple.test:9000", "", "sauvegardes", "auto", ID, SECRET, base="p/")
        self.assertEqual((c.entete_hote, c._chemin("x.zip"), c.region), ("stockage.exemple.test:9000", "/sauvegardes/p/x.zip",
                                                                         "us-east-1"))
        c = S.ClientS3("https://stockage.exemple.test", "fr-par", "sauvegardes", "virtual", ID, SECRET)
        self.assertEqual(c.entete_hote, "sauvegardes.stockage.exemple.test")
        for faux in ("ftp://x", "https://u:p@x", "https://x/?a=1", "https://", "https://x y"):
            with self.subTest(adresse=faux), self.assertRaises(ValueError):
                S.verifier_adresse(faux)

    def test_reponse_avec_dtd_refusee(self):
        with self.assertRaises(ErreurCopie):
            S._xml(b'<!DOCTYPE x [<!ENTITY a "aaaa">]><x>&a;</x>')


@override_settings(COPIE_EXTERNE_LOCAL=True)
@SANS_PROXY
class AutoriteInterneTests(SimpleTestCase):
    """HTTPS avec une autorité de test : refusé sans elle (certificat), accepté quand ``SSL_CERT_FILE`` la donne, comme
    l'autorité interne ajoutée par l'IT (``config/autorites_certificats.py``)."""

    def test_https_avec_autorite_de_test(self):
        from parametres.aides_tests.serveurs_tls import Autorite

        tmp = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, tmp, True)
        autorite = Autorite()
        faux = FauxS3(contexte=autorite.contexte_serveur(tmp))
        self.addCleanup(faux.fermer)
        p, sha, _ = fichier(tmp, 100)
        vide = Path(tmp) / "vide.pem"
        vide.write_text("")
        with mock.patch.dict(os.environ, {"SSL_CERT_FILE": str(vide), "SSL_CERT_DIR": tmp}):
            with S.ClientS3(faux.adresse, "", "sauvegardes", "path", ID, SECRET, delai=5) as c, \
                    self.assertRaises(ErreurCopie) as e:
                c.deposer("x.zip", p, 100, sha)
            self.assertEqual(e.exception.code, "certificat")
        with mock.patch.dict(os.environ, {"SSL_CERT_FILE": str(autorite.ecrire(tmp)), "SSL_CERT_DIR": tmp}):
            with S.ClientS3(faux.adresse, "", "sauvegardes", "path", ID, SECRET, delai=5) as c:
                c.deposer("x.zip", p, 100, sha)
        self.assertIn("x.zip", faux.objets)
