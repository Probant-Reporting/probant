"""Adresses que la copie externe peut joindre (``copie_reseau``) : l'hôte est saisi par un administrateur, le bouton
« Essayer » ne doit pas servir à sonder la machine ni le service de métadonnées de l'hébergeur. Jamais la machine
elle-même (hors essais), une adresse locale au lien (169.254.169.254), multicast, réservée ou non précisée ; les
adresses privées restent permises (NAS, MinIO interne) ; http seulement vers une adresse privée ; contrôle du nom
(toutes ses adresses) avant l'appel, puis de l'adresse réellement jointe (un nom qui change d'adresse ne passe pas)."""
import hashlib
import tempfile
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase, override_settings

from parametres import copie_reseau as R
from parametres import copie_s3 as S
from parametres import copie_sftp as F
from parametres.aides_tests.copie import SANS_PROXY
from parametres.aides_tests.faux_s3 import ID, SECRET, FauxS3


@override_settings(COPIE_EXTERNE_LOCAL=False)
@SANS_PROXY
class AdressesTests(SimpleTestCase):
    def test_regle_des_adresses(self):
        for ip in ("127.0.0.1", "127.8.0.1", "::1", "::ffff:127.0.0.1", "169.254.169.254", "fe80::1", "224.0.0.1",
                   "0.0.0.0", "240.0.0.1", "::"):
            self.assertFalse(R.ip_permise(ip), ip)
        for ip in ("10.0.0.5", "172.17.0.2", "192.168.1.20", "fd00::5", "203.0.113.7"):
            self.assertTrue(R.ip_permise(ip), ip)
        self.assertTrue(R.ip_privee("192.168.1.20"))
        self.assertFalse(R.ip_privee("8.8.8.8"))
        self.assertFalse(R.ip_privee("127.0.0.1"))
        with override_settings(COPIE_EXTERNE_LOCAL=True):
            self.assertTrue(R.ip_permise("127.0.0.1"))

    def test_s3_adresses_refusees_sans_connexion(self):
        p = Path(tempfile.mkdtemp()) / "a.zip"
        p.write_bytes(b"x")
        sha = hashlib.sha256(b"x").hexdigest()
        cas = [("https://169.254.169.254", "adresse_refusee"), ("https://127.0.0.1:9000", "adresse_refusee"),
               ("https://localhost", "adresse_refusee"), ("http://8.8.8.8", "http_public")]
        with mock.patch("socket.create_connection", side_effect=AssertionError("aucune connexion")), \
                mock.patch("http.client.HTTPConnection.connect", side_effect=AssertionError("aucune connexion")):
            for adresse, cause in cas:
                with self.subTest(adresse=adresse):
                    with S.ClientS3(adresse, "", "sauvegardes", "path", ID, SECRET, delai=2) as c, \
                            self.assertRaises(R.ErreurCopie) as e:
                        c.deposer("x.zip", p, 1, sha)
                    self.assertEqual(e.exception.code, cause)

    def test_sftp_machine_elle_meme_refusee(self):
        with mock.patch("socket.create_connection", side_effect=AssertionError("aucune connexion")):
            for hote in ("127.0.0.1", "169.254.169.254", "localhost"):
                with self.subTest(hote=hote):
                    with self.assertRaises(R.ErreurCopie) as e, F.ClientSFTP(hote, 22, "copie", "mdp", "", "/", "", delai=2):
                        pass
                    self.assertEqual(e.exception.code, "adresse_refusee")

    def test_adresse_reellement_jointe_controlee(self):
        """Le nom passe le contrôle (résolu en une adresse privée), mais la connexion arrive sur la machine elle-même
        (nom qui change d'adresse entre les deux) : refusé après la connexion, rien n'est envoyé."""
        faux = FauxS3()
        self.addCleanup(faux.fermer)
        p = Path(tempfile.mkdtemp()) / "a.zip"
        p.write_bytes(b"x")
        with mock.patch.object(S, "resoudre", return_value=["10.1.2.3"]), \
                S.ClientS3(faux.adresse, "", "sauvegardes", "path", ID, SECRET, delai=2) as c, \
                self.assertRaises(R.ErreurCopie) as e:
            c.deposer("x.zip", p, 1, hashlib.sha256(b"x").hexdigest())
        self.assertEqual(e.exception.code, "adresse_refusee")
        self.assertEqual(faux.requetes, [])
