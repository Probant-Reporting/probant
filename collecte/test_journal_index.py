"""Index du journal (migration 0034, additive) : comptes par type de la page Journal (« action ») et historique d'un seul
objet (« objet », « objet_id »)."""
from django.db import connection
from django.db.models import Count
from django.test import TestCase

from .models import Journal


class IndexJournalTests(TestCase):
    def test_index_presents_dans_la_base(self):
        with connection.cursor() as c:
            contraintes = connection.introspection.get_constraints(c, Journal._meta.db_table)
        index = {tuple(v["columns"]) for v in contraintes.values() if v["index"]}
        self.assertIn(("action",), index)
        self.assertIn(("objet", "objet_id"), index)
        self.assertIn(("date",), index)  # l'index d'avant reste

    def test_requetes_les_utilisent(self):
        if connection.vendor != "sqlite":
            self.skipTest("plan de requête lu avec SQLite (EXPLAIN QUERY PLAN)")
        comptes = Journal.objects.filter(action__in=["saisie", "validation"]).values_list("action").annotate(n=Count("pk")).order_by()
        self.assertIn("journal_action_idx", comptes.explain())
        historique = Journal.objects.filter(objet="KPI", objet_id="EFF")
        self.assertIn("journal_objet_idx", historique.explain())
