"""Ce que les outils disent d'un KPI à choix ou en tableau (``outils.json_kpi``, ``outils.json_valeur``) : les choix
possibles d'un oui / non ou d'une liste, les colonnes d'un tableau (code, libellé, type, liste), et, pour une réponse en
tableau, ses lignes lues colonne par colonne (nombre en texte exact, cellule texte dans son enveloppe « user_text »).

Données inventées uniquement."""
from collecte import saisie as S
from parametres.models import TypeReponse
from referentiel.models import KPI, ElementReferentiel, Niveau

from .aides_tests import MODERNE, BaseMCP

COLONNES = [
    {"code": "polluant", "libelle": {"fr": "Polluant", "en": "Pollutant"}, "type": "liste", "liste": "ESSAI-POLLUANT"},
    {"code": "air", "libelle": {"fr": "Rejets dans l'air", "en": "Emissions to air"}, "type": "nombre", "unite": "kg"},
    {"code": "note", "libelle": {"fr": "Remarque", "en": "Note"}, "type": "texte"},
]


class KpiChoixEtTableauTests(BaseMCP):
    def setUp(self):
        super().setUp()
        liste = TypeReponse.objects.create(code="ESSAI-POLLUANT", libelle="Polluant d'essai", format="liste",
                                           valeurs=["Ammoniac", "Benzène"])
        tableau = TypeReponse.objects.create(code="ESSAI-TAB", libelle="Rejets d'essai", format="tableau", colonnes=COLONNES)
        self.pol = KPI.objects.create(code="POL", libelle="Polluant principal", type_saisie_id="Saisi",
                                      granularite_id=Niveau.ENTITY, type_reponse=liste, methode_agregation="Décompte")
        self.tab = KPI.objects.create(code="TAB", libelle="Rejets", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY,
                                      type_reponse=tableau, methode_agregation="Aucune")
        for i, k in enumerate((self.pol, self.tab), start=10):
            ElementReferentiel.objects.create(referentiel=self.c.referentiel, kpi=k, theme=self.theme, ordre=i)

    def kpi(self, code):
        _, res, d = self.outil("admin", "list_kpis", {"campaign_id": self.c.pk, "search": code}, MODERNE)
        self.assertFalse(res["isError"], d)
        return next(k for k in d["kpis"] if k["code"] == code)

    def test_choix_d_une_liste(self):
        k = self.kpi("POL")
        self.assertEqual(k["choices"], [{"value": "Ammoniac", "label": "Ammoniac"}, {"value": "Benzène", "label": "Benzène"}])
        self.assertNotIn("columns", k)

    def test_colonnes_d_un_tableau(self):
        k = self.kpi("TAB")
        self.assertEqual([(c["code"], c["type"], c["list"]) for c in k["columns"]],
                         [("polluant", "liste", "ESSAI-POLLUANT"), ("air", "nombre", None), ("note", "texte", None)])
        self.assertEqual([c["label"] for c in k["columns"]][:1], ["Polluant"])
        self.assertNotIn("choices", k)

    def test_lignes_d_une_reponse_en_tableau(self):
        S.enregistrer(self.admin, self.c, self.tab, self.e1, "| Ammoniac | 1234,5 | à vérifier |\n| Benzène | 12 | |", False, "")
        _, res, d = self.outil("admin", "get_value", self.case(kpi=self.tab), MODERNE)
        self.assertFalse(res["isError"], d)
        self.assertEqual(d["rows"], [{"polluant": "Ammoniac", "air": "1234.5", "note": {"user_text": "à vérifier"}},
                                     {"polluant": "Benzène", "air": "12", "note": None}])
