"""Services de métadonnées des hébergeurs refusés par la règle des adresses sortantes (``sortant.adresse_ip_permise``,
reprise par la copie externe ``parametres/copie_reseau.ip_permise``). Ils donnent les identifiants de la machine : une
adresse de fournisseur d'identité ou de destination de copie qui les vise les ferait lire par l'outil. 169.254.169.254
(locale au lien) était déjà refusée ; ces adresses-ci passaient, car elles ne sont ni locales au lien ni réservées :

- fd00:ec2::254 : service de métadonnées d'AWS en IPv6 (Nitro) ;
- fd20:ce::254 : serveur de métadonnées de Google Compute Engine en IPv6 ;
- 100.100.100.200 : service de métadonnées d'Alibaba Cloud ;
- 192.0.0.192 : service de métadonnées d'Oracle Cloud (Classic) ;
- 168.63.129.16 : « WireServer » d'Azure (configuration de la machine, certificats des extensions).

Les adresses privées ordinaires restent permises (fournisseur d'identité interne, NAS, MinIO)."""
from django.test import SimpleTestCase, override_settings

from parametres import copie_reseau

from . import sortant

METADONNEES = ["fd00:ec2::254", "fd20:ce::254", "100.100.100.200", "192.0.0.192", "168.63.129.16", "169.254.169.254",
               "::ffff:100.100.100.200", "FD00:EC2:0:0:0:0:0:254"]
PERMISES = ["10.0.0.5", "172.16.3.4", "192.168.1.10", "fd12:3456::1", "100.100.100.201", "100.64.0.1", "8.8.8.8",
            "2a00:1450:4007:80c::200e"]


@override_settings(CONNEXION_ENTREPRISE_LOCAL=False, COPIE_EXTERNE_LOCAL=False)
class MetadonneesTests(SimpleTestCase):
    def test_refusees(self):
        for ip in METADONNEES:
            self.assertFalse(sortant.adresse_ip_permise(ip), ip)
            self.assertFalse(copie_reseau.ip_permise(ip), ip)

    def test_adresses_privees_ordinaires_permises(self):
        for ip in PERMISES:
            self.assertTrue(sortant.adresse_ip_permise(ip), ip)
            self.assertTrue(copie_reseau.ip_permise(ip), ip)

    def test_url_vers_une_adresse_de_metadonnees_refusee(self):
        with self.assertRaises(sortant.ErreurReseau) as e:
            sortant.demander("https://[fd00:ec2::254]/latest/meta-data/")
        self.assertEqual(e.exception.code, "adresse_refusee")
