"""Historique d'une case (``saisie._journaliser``) : la première saisie écrit des lignes « creation » (sans valeur
avant), toute saisie suivante des lignes « modification » avec l'ancienne et la nouvelle valeur."""
from decimal import Decimal

from .models import Journal, Reponse
from .aides_tests.saisie import Base


class JournaliserTests(Base):
    def lignes(self, r):
        # valeurs comparées en nombres (l'ancienne valeur est notée telle que lue en base, avec ses décimales)
        return [(action, avant and Decimal(avant), Decimal(apres)) for action, avant, apres in
                Journal.objects.filter(objet="Reponse", objet_id=str(r.pk), champ="valeur").order_by("pk")
                .values_list("action", "avant", "apres")]

    def test_premiere_saisie_creation_puis_modification(self):
        self.enregistrer("40")
        r = Reponse.objects.get(periode=self.c.periode, kpi=self.eff, organisation=self.e1)
        self.assertEqual(self.lignes(r), [("creation", "", 40)])
        self.assertEqual(set(Journal.objects.filter(objet="Reponse", objet_id=str(r.pk)).values_list("action", flat=True)), {"creation"})
        self.enregistrer("45")
        self.assertEqual(self.lignes(r), [("creation", "", 40), ("modification", 40, 45)])
