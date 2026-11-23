"""LangueMiddleware : seule la vraie route de supervision (/sante/, /espace/<code>/sante/) est servie sans langue ; la page
Administration › Paramètres › Santé (/administration/parametres/sante/) s'affiche dans la langue de la personne."""
from django.test import Client

from espaces import contexte as E
from espaces.aides_tests import creer
from espaces.essais import EspacesTestCase
from parametres.libelles import libelle
from referentiel.models import Utilisateur

URL = "/administration/parametres/sante/"


class PageSanteLangueTests(EspacesTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.admin = creer("admin@exemple.example", "admin")
        cls.admin_essai = creer("admin.essai@exemple.example", "admin", "essai")

    def page(self, u, langue, espace="principal"):
        c = Client()
        with E.activer(espace):
            c.force_login(Utilisateur.objects.get(pk=u.pk))
        s = c.session
        s["langue"] = langue  # choix de la barre du haut
        s.save()
        prefixe = "" if espace == "principal" else f"/espace/{espace}"
        rep = c.get(prefixe + URL)
        self.assertEqual(rep.status_code, 200)
        return rep

    def verifier(self, rep, langue):
        self.assertContains(rep, f"<title>{libelle('admin.sante.titre', langue=langue)}", html=False)
        self.assertContains(rep, libelle("cadre.deconnexion", langue=langue))  # barre du haut
        self.assertContains(rep, f'lang="{langue}"')

    def test_page_sante_en_anglais_et_en_allemand(self):
        for langue in ("en", "de"):
            with self.subTest(langue=langue):
                self.verifier(self.page(self.admin, langue), langue)

    def test_page_sante_d_un_autre_espace_en_allemand(self):
        self.verifier(self.page(self.admin_essai, "de", "essai"), "de")

    def test_supervision_toujours_libre(self):
        """La route de supervision garde son comportement : réponse sans session ni langue, dans chaque espace."""
        self.assertIn(Client().get("/sante/").status_code, (200, 503))
        self.assertIn(Client().get("/espace/essai/sante/").status_code, (200, 503))
