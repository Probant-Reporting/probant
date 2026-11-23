"""``views._controle`` : une valeur d'une liste de choix encore utilisée dans des réponses ne se retire pas, y compris quand
la liste sert à une colonne d'un tableau (vie d'un groupe, quatrième année, « list_value_used_in_table_removed »).

Avant : seule la réponse d'un KPI dont le type est la liste elle-même était cherchée ; une valeur utilisée dans la
colonne d'un tableau (« | Plastique | 2 | ») se retirait sans un mot, et ces réponses ne pouvaient plus être enregistrées
de nouveau, ni l'export réimporté tel quel."""
from collecte.models import Reponse
from referentiel.models import KPI, Niveau

from .aides_tests.referentiel import Base
from .models import TypeReponse


class ValeurListeDansTableauTests(Base):
    def setUp(self):
        super().setUp()
        TypeReponse.objects.create(code="DECH", libelle="Type de déchet", format="liste", valeurs=["Papier", "Plastique"], ordre=30)
        tableau = TypeReponse.objects.create(code="DTAB", libelle="Déchets par type", format="tableau", ordre=31, colonnes=[
            {"code": "type", "libelle": {"fr": "Type"}, "type": "liste", "liste": "DECH"},
            {"code": "masse", "libelle": {"fr": "Masse"}, "type": "nombre"}])
        k = KPI.objects.create(code="DECHT", libelle="Déchets", type_saisie_id="Saisi", type_reponse=tableau,
                               granularite_id=Niveau.ENTITY, methode_agregation="Aucune")
        Reponse.objects.create(periode=self.c.periode, kpi=k, organisation=self.e1,
                               texte="| Type | Masse |\n| --- | ---: |\n| Plastique | 2 |")

    def retirer(self, valeurs):
        types = list(TypeReponse.objects.all())
        i = [x.pk for x in types].index("DECH")
        return self.page("types-reponse", action="enregistrer", nb=len(types), **{f"code__{j}": x.pk for j, x in enumerate(types)},
                         **{f"libelle__{i}": "Type de déchet", f"valeurs__{i}": valeurs})

    def test_valeur_utilisee_dans_un_tableau_gardee(self):
        rep = self.retirer("Papier\nVerre")
        self.assertContains(rep, "encore utilisée dans des réponses : Plastique")
        self.assertEqual(TypeReponse.objects.get(code="DECH").valeurs, ["Papier", "Plastique"])

    def test_valeur_inutilisee_retiree(self):
        self.retirer("Plastique\nVerre")
        self.assertEqual(TypeReponse.objects.get(code="DECH").valeurs, ["Plastique", "Verre"])

    def test_classeur_de_configuration_meme_regle(self):
        """Même porte par le classeur de configuration (``configuration._controle_reglable``)."""
        from collecte import configuration as C

        liste = TypeReponse.objects.get(code="DECH")
        avant = {"valeurs": list(liste.valeurs), "format": liste.format}
        liste.valeurs = ["Papier", "Verre"]
        self.assertIn("Plastique", C._controle_reglable(liste, avant, 1))
        liste.valeurs = ["Plastique", "Verre"]
        self.assertEqual(C._controle_reglable(liste, avant, 1), "")
