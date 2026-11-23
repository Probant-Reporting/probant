"""``OrganisationForm.clean`` (et l'import du classeur de configuration) : une organisation collectée ne se rattache pas à une
organisation qui ne l'est plus (vie d'un groupe, quatrième année : site fermé en 2024, son entité cédée en 2026, puis le site
« rouvert » depuis sa fiche).

Avant : la fiche refusait de fermer une organisation qui a encore des enfants collectés (CALC-10), mais acceptait de
rouvrir un enfant, d'en créer un ou d'en rattacher un sous une organisation fermée ; le contrôle des données de
l'Hébergement signalait aussitôt une erreur (« collected but attached to …, which is not collected any more ») et le site
était demandé sans compter dans les totaux."""
from collecte.outils_tests import xlsx
from referentiel.models import Niveau, Organisation

from . import configuration as CF
from . import controle_donnees as CD
from .aides_tests.arbre import Arbre


def erreurs_arbre():
    return [p for p in CD.controler()["problems"] if p["check"] == "tree" and p["count"]]


class ParentFermeTests(Arbre):
    def setUp(self):
        super().setUp()
        self.e3.actif = False
        self.e3.save()
        Organisation.objects.filter(pk=self.p2.pk).update(actif=False)
        self.p2.refresh_from_db()

    def test_rouvrir_sous_un_parent_ferme_refuse(self):
        res = self.post("admin_organisation", [self.e3.id], nom="E3", niveau=Niveau.ENTITY, parent=self.p2.id, rang=0, actif="on",
                        action="enregistrer")
        self.assertFalse(res["ok"])
        self.assertIn("Pays 2", res["html"])
        self.e3.refresh_from_db()
        self.assertFalse(self.e3.actif)
        self.assertEqual(erreurs_arbre(), [])

    def test_creer_sous_un_parent_ferme_refuse(self):
        self.post("admin_organisation_nouvelle", nom="E4", niveau=Niveau.ENTITY, parent=self.p2.id, rang=0, actif="on",
                  action="enregistrer")
        self.assertFalse(Organisation.objects.filter(nom="E4").exists())

    def test_rattacher_ailleurs_ou_rouvrir_le_parent_reste_possible(self):
        res = self.post("admin_organisation", [self.e3.id], nom="E3", niveau=Niveau.ENTITY, parent=self.p.id, rang=0, actif="on",
                        action="enregistrer")
        self.assertTrue(res["ok"], res["html"])
        res = self.post("admin_organisation", [self.p2.id], nom="Pays 2", niveau=Niveau.COUNTRY, parent=self.g.id, rang=0, actif="on",
                        action="enregistrer")
        self.assertTrue(res["ok"], res["html"])

    def test_import_de_configuration_meme_regle(self):
        lignes = [["Nom", "Niveau", "Rattachée à", "Active"], ["E3", "Entité", "Pays 2", "Oui"]]
        a = CF.analyser(xlsx({"Organisations": lignes}))
        self.assertEqual(a.onglets["Organisations"][0].action, "rejet")
        self.assertIn("Pays 2", a.onglets["Organisations"][0].motif)
        lignes.append(["Pays 2", "Pays", "Groupe", "Oui"])  # le parent rouvert dans le même fichier : accepté
        a = CF.analyser(xlsx({"Organisations": lignes}))
        self.assertEqual([c.action for c in a.onglets["Organisations"]], ["modifier", "modifier"])
