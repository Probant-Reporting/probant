"""Répétition de la mise à jour : ``manage.py startup`` travaille avec l'interface en anglais (messages pour l'IT) ;
le recalcul posé par une migration réécrit alors le texte des alertes des campagnes ouvertes avec les séparateurs de
l'anglais (« 26,000 », « 0.0 M€ ») dans une installation en français. Le travail doit se faire dans la langue de l'installation."""
from parametres import langues as L
from referentiel.models import TravailApresMiseAJour

from .aides_tests.coherence import BasePanneau
from .mise_a_jour import faire_les_travaux
from .models import Alerte


class TravauxApresMiseAJourLangueTests(BasePanneau):
    def test_recalcul_pendant_le_demarrage_garde_la_langue_de_l_installation(self):
        a = self.historique(26000)
        self.assertIn("26 000", a.message)  # installation en français
        TravailApresMiseAJour.objects.create(code="recalcul", motif="Essai.")
        with L.activer_interface("en"):  # comme ``manage.py startup``
            self.assertEqual(faire_les_travaux(), ["recalcul"])
        a = Alerte.objects.get(pk=a.pk)
        self.assertIn("26 000", a.message)
