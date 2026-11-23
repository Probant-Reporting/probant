"""Page Santé, ligne « Dernière sauvegarde » : « {quand}, il y a {duree}. » dans les sept langues, la durée venant de
``timesince`` de Django (nominatif). En allemand, « vor {duree} » donnait « vor 2 Tage » (il faut le datif « vor 2 Tagen ») :
formulation sans préposition. Les autres langues restent justes avec la forme de Django (« il y a 2 jours », « hace 2
días », « 2 giorni fa », « 2 dagen geleden », « há 2 dias », « 2 days ago »)."""
import datetime

from django.test import SimpleTestCase
from django.utils import timezone

from collecte.templatetags.collecte import depuis
from parametres import langues as L
from parametres.libelles import libelle

ATTENDUS = {"en": "2 days ago", "fr": "il y a 2 jours", "es": "hace 2 días", "it": "2 giorni fa", "nl": "2 dagen geleden",
            "pt": "há 2 dias", "de": "2 Tage"}


class DerniereSauvegardeLanguesTests(SimpleTestCase):
    def phrase(self, langue, jours):
        d = timezone.now() - datetime.timedelta(days=jours, minutes=1)
        with L.activer_interface(langue):
            return libelle("admin.sante.sauvegarde.derniere", langue=langue, quand="QUAND", duree=depuis(d))

    def test_sept_langues(self):
        for langue, attendu in ATTENDUS.items():
            with self.subTest(langue=langue):
                texte = self.phrase(langue, 2).replace("\xa0", " ")  # espace insécable de timesince
                self.assertIn(attendu, texte)
                self.assertTrue(texte.startswith("QUAND"))

    def test_allemand_sans_preposition_avant_le_nominatif(self):
        for jours in (1, 2, 40, 800):
            with self.subTest(jours=jours):
                self.assertNotIn("vor ", self.phrase("de", jours))
