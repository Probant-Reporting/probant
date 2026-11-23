"""Organisation fermée depuis (désactivée avec une date de fermeture postérieure au début de la période) : elle compte dans
les totaux de la période (``calcul.ouverte``) et figure dans les exports ; elle est donc aussi
listée sous son parent dans la Visualisation (comparaison des organisations, anneau, colonnes d'un tableau) et dans la
Consolidation, pour que chaque total reste la somme des lignes montrées dessous (``visualisation.Source.organisations``).

Avant : seules les organisations actives aujourd'hui étaient listées ; un site fermé en 2026 disparaissait du détail de
2025 (et de 2026) alors que son chiffre restait dans le total. Données inventées."""
import datetime

from referentiel.models import Organisation

from . import consolidation as CO
from . import visualisation as V
from .aides_tests.visuels import AvecKpis


class OrganisationFermeeDepuis(AvecKpis):
    def setUp(self):
        super().setUp()
        Organisation.objects.filter(pk=self.e2.pk).update(actif=False, date_desactivation=datetime.date(2026, 3, 1))

    def test_comparaison_des_organisations_sous_le_parent(self):
        d = self.donnees(self.admin, {"type": "organisations", "kpis": ["EFF"]},
                         parametres={"org": str(self.p.id), "periode": str(self.c0.periode.pk)})
        v = d["visuels"]["v1"]
        self.assertEqual([c["libelle"] for c in v["categories"]], ["E1", "E2"])
        total = V.Source(self.admin).point("EFF", self.p, self.c0.periode).nombre
        self.assertEqual(sum(x for x in v["series"][0]["valeurs"] if x is not None), float(total))  # 100 + 30

    def test_lignes_de_la_consolidation(self):
        t = CO.tableau(self.admin, self.c0.periode, [self.eff])
        self.assertEqual([l.org.nom for l in t.lignes], ["Groupe", "Pays", "E1", "E2"])

    def test_fermee_avant_la_periode_toujours_absente(self):
        Organisation.objects.filter(pk=self.e2.pk).update(date_desactivation=datetime.date(2024, 12, 31))
        t = CO.tableau(self.admin, self.c0.periode, [self.eff])
        self.assertNotIn("E2", [l.org.nom for l in t.lignes])

    def test_liste_des_organisations_sans_periode_inchangee(self):
        self.assertNotIn(self.e2.id, {o.id for o in V.Source(self.admin).organisations()})  # filtre « Organisation »
