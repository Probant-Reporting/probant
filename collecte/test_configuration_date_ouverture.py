"""Date d'ouverture d'une organisation dans le classeur de configuration (export et import)
et dans le serveur MCP (lecture). Données inventées uniquement."""
import datetime

from django.test import TestCase

from collecte.outils_tests import xlsx
from referentiel.models import Niveau, Organisation, Utilisateur

from . import configuration as CF


class ClasseurDateOuvertureTests(TestCase):
    def setUp(self):
        self.g = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        self.p = Organisation.objects.create(nom="Pays", niveau_id=Niveau.COUNTRY, parent=self.g,
                                             date_ouverture=datetime.date(2024, 7, 1))
        self.admin = Utilisateur.objects.create(username="admin", email="admin@exemple.test", role=Utilisateur.Role.ADMIN)

    def test_export_colonne_ouverte_depuis(self):
        ws = CF.classeur(langue="fr")["Organisations"]
        lignes = list(ws.iter_rows(values_only=True))
        col = lignes[0].index("Ouverte depuis")
        par_nom = {l[0]: l[col] for l in lignes[1:] if l[0]}
        self.assertEqual(par_nom["Pays"], "01/07/2024")
        self.assertIn(par_nom["Groupe"], ("", None))

    def test_import_pose_change_et_garde_la_date(self):
        lignes = [["Nom", "Niveau", "Rattachée à", "Ouverte depuis"], ["E1", "Entité", "Pays", "01/03/2026"],
                  ["Pays", "Pays", "Groupe", ""]]
        CF.appliquer(self.admin, xlsx({"Organisations": lignes}))
        self.assertEqual(Organisation.objects.get(nom="E1").date_ouverture, datetime.date(2026, 3, 1))
        self.assertEqual(Organisation.objects.get(nom="Pays").date_ouverture, datetime.date(2024, 7, 1))  # vide : gardée
        a = CF.analyser(xlsx({"Organisations": [["Nom", "Niveau", "Rattachée à", "Ouverte depuis"], ["Pays", "Pays", "Groupe", "—"]]}))
        ch = a.onglets["Organisations"][0]
        self.assertEqual(ch.action, "modifier")  # « — » : date retirée
        self.assertIsNone(ch.objet.date_ouverture)
        a = CF.analyser(xlsx({"Organisations": [["Nom", "Niveau", "Rattachée à", "Ouverte depuis"], ["Pays", "Pays", "Groupe", "2024-07-01"]]}))
        self.assertEqual(a.onglets["Organisations"][0].action, "inchange")

    def test_import_refuse_une_ouverture_apres_la_fermeture(self):
        lignes = [["Nom", "Niveau", "Rattachée à", "Active", "Ouverte depuis"], ["E9", "Entité", "Pays", "Non", "01/03/2026"]]
        Organisation.objects.create(nom="E9", niveau_id=Niveau.ENTITY, parent=self.p, actif=False,
                                    date_desactivation=datetime.date(2025, 12, 31))
        a = CF.analyser(xlsx({"Organisations": lignes}))
        self.assertEqual(a.onglets["Organisations"][0].action, "rejet")


class McpOrganisationTests(TestCase):
    def test_dates_d_ouverture_et_de_fermeture_lues(self):
        from serveur_mcp.outils import json_org

        g = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP, date_ouverture=datetime.date(2020, 1, 1))
        self.assertEqual((json_org(g)["open_since"], json_org(g)["closed_on"]), ("2020-01-01", None))
