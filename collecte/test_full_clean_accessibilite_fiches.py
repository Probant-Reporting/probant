"""Accessibilité des fiches : un champ refusé de la fiche d'une organisation porte
``aria-invalid`` et un ``aria-describedby`` vers son message (le script des pages y met le focus) ; la question de la
réouverture d'un exercice clos rappelle le mode choisi (garder / recalculer).

Données inventées uniquement."""
import re

from django.urls import reverse

from . import calcul as C
from .administration import changer_statut
from .test_changer_statut_reouverture import Reouverture


class ErreurDateOrganisationTests(Reouverture):
    def test_champ_refuse_relie_a_son_message(self):
        self.client.force_login(self.admin)
        rep = self.client.post(reverse("collecte:admin_organisation", args=[self.e1.pk]),
                               {"nom": "E1", "code": self.e1.code, "niveau": self.e1.niveau_id, "parent": self.p.pk, "rang": 0,
                                "actif": "", "date_desactivation": "2025-03-31", "date_ouverture": "2025-06-01",
                                "action": "enregistrer"}, HTTP_X_REQUESTED_WITH="fetch")
        html = rep.json()["html"]
        champ = re.search(r'<input[^>]*name="date_ouverture"[^>]*>', html).group(0)
        self.assertIn('aria-invalid="true"', champ)
        self.assertIn("err-date_ouverture", champ)
        self.assertIn('id="err-date_ouverture"', html)


class RappelModeReouvertureTests(Reouverture):
    def test_question_de_reouverture_rappelle_le_mode(self):
        self.client.force_login(self.admin)
        self.assertTrue(C.figee(self.c.periode))
        page = self.client.get(reverse("collecte:admin_campagne", args=[self.c.pk])).content.decode()
        self.assertIn("data-confirmer-garder=", page)
        self.assertIn("data-confirmer-recalculer=", page)
        self.assertIn("garder les chiffres", page.lower())
        changer_statut(self.admin, self.c, "rouvrir", garder=True)
        page = self.client.get(reverse("collecte:admin_campagne", args=[self.c.pk])).content.decode()
        self.assertNotIn("data-confirmer-garder=", page)  # campagne rouverte : plus de choix à rappeler
