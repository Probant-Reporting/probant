"""Date d'ouverture après la date de fermeture EFFECTIVE : une organisation désactivée
dont la date de fermeture est laissée vide est fermée aujourd'hui (vue de la fiche) ; une date d'ouverture future était
acceptée, puis restait après la fermeture. Même contrôle dans l'import du classeur de configuration (le collage ne crée
que des organisations actives).

Données inventées uniquement."""
import datetime

from django.test import TestCase
from django.utils import timezone

from collecte.outils_tests import xlsx
from referentiel.models import Niveau, Organisation

from . import configuration as CF
from .administration import OrganisationForm


class FermetureVideTests(TestCase):
    def setUp(self):
        self.g = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        self.e = Organisation.objects.create(nom="E1", niveau_id=Niveau.ENTITY, parent=self.g)

    def donnees(self, **champs):
        d = {"nom": self.e.nom, "code": self.e.code, "niveau": Niveau.ENTITY, "parent": self.g.pk, "rang": 0}
        d.update(champs)
        return d

    def test_fiche_inactive_sans_date_de_fermeture_ouverture_future_refusee(self):
        futur = (timezone.localdate() + datetime.timedelta(days=400)).isoformat()
        f = OrganisationForm(self.donnees(date_ouverture=futur), instance=self.e)  # « actif » décoché, fermeture vide
        self.assertFalse(f.is_valid())
        self.assertIn("date_ouverture", f.errors)
        passe = (timezone.localdate() - datetime.timedelta(days=10)).isoformat()
        self.assertTrue(OrganisationForm(self.donnees(date_ouverture=passe), instance=self.e).is_valid())

    def test_import_inactive_sans_date_de_fermeture_ouverture_future_refusee(self):
        futur = (timezone.localdate() + datetime.timedelta(days=400)).strftime("%d/%m/%Y")
        lignes = [["Nom", "Niveau", "Rattachée à", "Active", "Ouverte depuis"], ["E1", "Entité", "Groupe", "Non", futur]]
        self.assertEqual(CF.analyser(xlsx({"Organisations": lignes})).onglets["Organisations"][0].action, "rejet")
