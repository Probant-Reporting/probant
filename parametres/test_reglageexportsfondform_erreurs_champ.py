"""Seconde recette (B7) : Paramètres › Hébergement › Gros exports, une saisie refusée est signalée sur son champ (WCAG
3.3.1 et 1.3.1) : message sous le champ, relié par ``aria-describedby``, champ marqué ``aria-invalid`` ; plus de message
seul sous le formulaire."""
import re

from django.test import TestCase
from django.urls import reverse

from parametres.libelles import libelle
from referentiel.models import Utilisateur


class ErreursSurLeChampTests(TestCase):
    def setUp(self):
        admin = Utilisateur.objects.create(username="admin", email="a@exemple.test", role=Utilisateur.Role.ADMIN)
        self.client.force_login(admin)

    def section(self, cellules, jours):
        rep = self.client.post(reverse("parametres:hebergement"), {"action": "reglage_exports_fond",
                                                                    "exports_fond_cellules": cellules, "exports_fond_jours": jours})
        self.assertEqual(rep.status_code, 200)
        html = rep.content.decode()
        return html[html.index('id="reglage-exports-fond"'):].split("</section>")[0]

    def champ(self, section, nom):
        return re.search(rf'<input[^>]*name="{nom}"[^>]*>', section).group(0)

    def test_jours_refuses_signales_sur_leur_champ(self):
        s = self.section("1000", "99")
        champ = self.champ(s, "exports_fond_jours")
        self.assertIn('aria-invalid="true"', champ)
        ident = re.search(r'aria-describedby="([^"]*)"', champ).group(1).split()[0]
        message = re.search(rf'id="{ident}"[^>]*>([^<]*)<', s)
        self.assertIsNotNone(message, s)
        self.assertEqual(message.group(1).strip(), libelle("admin.hebergement.exports_fond.erreur_jours").replace("'", "&#x27;"))
        self.assertLess(s.index(f'id="{ident}"'), s.index("</form>"))  # dans le formulaire, avec son champ
        self.assertNotIn('aria-invalid', self.champ(s, "exports_fond_cellules"))  # l'autre champ n'est pas en erreur

    def test_les_deux_champs_refuses(self):
        s = self.section("abc", "0")
        for nom in ("exports_fond_cellules", "exports_fond_jours"):
            self.assertIn('aria-invalid="true"', self.champ(s, nom), nom)
