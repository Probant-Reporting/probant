"""``get_value`` : la définition d'un KPI (texte libre saisi par un administrateur, une entrée par catégorie de
description) revient dans l'enveloppe ``{"user_text": …}``, comme tout texte saisi par une personne ; la consigne commune
des outils le dit."""
from parametres.models import CategorieDescription
from referentiel.models import Description

from . import outils as O
from .aides_tests import BaseMCP
from .test_outils_textes_saisis import PIEGE, occurrences


class DefinitionKPITests(BaseMCP):
    def test_definition_dans_l_enveloppe(self):
        cat = CategorieDescription.objects.filter(affichee=True).first()
        self.assertIsNotNone(cat)
        Description.objects.update_or_create(kpi=self.eff, categorie=cat, langue="fr", defaults={"texte": PIEGE})
        _, res, d = self.outil("admin", "get_value", self.case())
        self.assertFalse(res["isError"], d)
        self.assertEqual(d["definition"][cat.libelle], {"user_text": PIEGE})
        for objet, cle in occurrences(d, PIEGE):
            self.assertEqual((cle, list(objet)), ("user_text", ["user_text"]))
        self.assertIn("KPI definitions", O.DONNEES)
