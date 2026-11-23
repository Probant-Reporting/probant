"""Champ « retour » des formulaires des référentiels (lot V5) : une adresse qui commence
par « /\\ » passait le contrôle « commence par / et pas par // » ; les navigateurs la lisent comme « //site » et la
redirection quittait l'outil. Seules les adresses de l'outil sont suivies (même règle que partout ailleurs :
``url_has_allowed_host_and_scheme``)."""
from django.test import RequestFactory, SimpleTestCase

from . import vues_referentiels as VR


class RetourTests(SimpleTestCase):
    def retour(self, valeur):
        request = RequestFactory().post("/administration/referentiels/", {"retour": valeur})
        return VR._retour(request, "/defaut/")

    def test_autre_site_refuse(self):
        for valeur in ("/\\autre.exemple.test", "/\\/autre.exemple.test", "//autre.exemple.test", "https://autre.exemple.test/",
                       "/\t/autre.exemple.test", "javascript:alert(1)"):
            self.assertEqual(self.retour(valeur), "/defaut/", valeur)

    def test_page_de_l_outil_gardee(self):
        for valeur in ("/administration/referentiels/VS_BASE/", "/administration/referentiels/VS_BASE/?ajouter=1#kpi"):
            self.assertEqual(self.retour(valeur), valeur)
