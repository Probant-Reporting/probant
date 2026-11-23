"""Certificat de clôture : le titre de la section « Campaign » ne se répète pas sur la ligne qui suit (l'étiquette du nom de la
campagne est « Name » et ses équivalents)."""
from django.test import SimpleTestCase

from parametres.libelles import libelle

LANGUES = ("en", "fr", "es", "de", "it", "nl", "pt")


class TitresDuCertificatTests(SimpleTestCase):
    def test_l_etiquette_du_nom_n_est_pas_le_titre_de_la_section(self):
        for lg in LANGUES:
            self.assertNotEqual(libelle("suivi.certificat.campagne.campagne", lg), libelle("suivi.certificat.campagne.titre", lg), lg)
