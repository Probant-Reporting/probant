"""Second garde-fou du « résultat trop grand » (``calcul.prevoir``) : une valeur rendue par le calculateur au-delà de ce
que la base garde exactement (``VALEUR_MAX``) n'est jamais écrite ; la case passe en erreur, avec le message nommé.

Le premier garde-fou (``Calculateur.valeur``) arrête déjà ces valeurs : ce second contrôle n'est atteint que si une
valeur y échappe ; le test la fait donc rendre directement par le calculateur (remplacé le temps du test)."""
from decimal import Decimal
from unittest import mock

from parametres.libelles import libelle

from . import calcul as C
from .models import VALEUR_MAX, Reponse
from .aides_tests.arbre import Arbre


class PrevoirTropGrandTests(Arbre):
    def test_valeur_hors_limite_en_erreur_nommee(self):
        self.kpi("A")
        self.saisir("A", self.e1, 1)
        self.saisir("A", self.e2, 2)
        calc = C.Calculateur(self.c.periode)
        with mock.patch.object(calc, "valeur", return_value=Decimal(VALEUR_MAX)):
            cellules, _ = C.prevoir(calc, ["A"])
        pays = next(ch for r, kid, org, ch, _ in cellules if kid == "A" and org.pk == self.p.pk)
        self.assertEqual((pays["valeur"], pays["statut"]), (None, Reponse.Statut.ERREUR))
        self.assertEqual(pays["message_calcul"], libelle("messages.calcul.trop_grand")[:300])
        with mock.patch.object(calc, "valeur", return_value=VALEUR_MAX - 1):  # témoin : juste sous la limite, écrite
            cellules, _ = C.prevoir(calc, ["A"])
        pays = next(ch for r, kid, org, ch, _ in cellules if kid == "A" and org.pk == self.p.pk)
        self.assertEqual(pays["statut"], Reponse.Statut.CALCULE)
        self.assertIsNotNone(pays["valeur"])
