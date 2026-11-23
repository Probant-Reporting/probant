"""L'exemple de la page Unités et formats se cherche par une sous-requête EXISTS (une seule lecture indexée de la table
des descriptions), pas par une double jointure : sous PostgreSQL, juste après un gros chargement, la double jointure a
tourné plusieurs minutes (statistiques du planificateur pas encore relevées)."""
from django.test import TestCase

from parametres.views import kpis_decrits


class KpisDecritsTests(TestCase):
    def test_sous_requete_exists_sans_jointure(self):
        sql = str(kpis_decrits().query).upper()
        self.assertIn("EXISTS", sql)
        # la table des descriptions n'est lue que dans la sous-requête, jamais jointe
        self.assertNotIn('JOIN "REFERENTIEL_DESCRIPTION"', sql)

    def test_base_sans_kpi(self):
        self.assertIsNone(kpis_decrits().first())
