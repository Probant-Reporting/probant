"""Conversion des tableaux de la Visualisation en vues, sans perte (migration collecte/0023_tableaux_en_vues)."""
import datetime
import importlib

from django.apps import apps
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from referentiel.models import Utilisateur

from .models import AccueilVisu, PreferenceVisu, TableauVisu, VueVisu
from .outils_tests import RetourSerialiseIndependantDeLOrdre

CT = importlib.import_module("collecte.migrations.0023_tableaux_en_vues")

TOUTES = [
    {"type": "chiffre", "kpi": "EFF", "titre": "Effectif du groupe"},
    {"type": "evolution", "kpi": "EFF", "largeur": 3},
    {"type": "organisations", "kpi": "NRJ"},
    {"type": "repartition", "kpi": "OUI", "largeur": 2},
    {"type": "tableau", "source": "liste:4", "titre": ""},
    {"type": "tableau", "source": "theme:999"},  # thème supprimé : gardé, le visuel le dira
    {"type": "chiffre", "kpi": "DISPARU"},  # KPI supprimé : gardé
    {"type": "jauge", "kpi": "EFF", "couleur": "rouge"},  # forme inconnue
    {"type": "chiffre", "saisi": "XYZ · inconnu"},  # KPI tapé mais introuvable
]


class ConvertirTuilesTests(TestCase):
    def test_toutes_les_formes(self):
        v = CT.convertir_tuiles(12, TOUTES)
        self.assertEqual(len(v), len(TOUTES))
        self.assertEqual([x["id"] for x in v], [f"t12-{i}" for i in range(1, 10)])
        self.assertEqual([x["type"] for x in v], ["chiffre", "barres", "organisations", "anneau", "tableau", "tableau",
                                                  "chiffre", "indisponible", "chiffre"])
        self.assertEqual([x["largeur"] for x in v], [4, 12, 8, 8, 12, 12, 4, 4, 4])  # tiers → colonnes, ou défaut
        self.assertEqual(v[0]["titre"], "Effectif du groupe")
        self.assertEqual(v[0]["kpis"], ["EFF"])
        self.assertEqual((v[1]["axe"], v[2]["axe"]), ("periodes", "organisations"))
        self.assertEqual((v[4]["source"], v[5]["source"], v[0]["source"]), ("liste:4", "theme:999", ""))
        self.assertEqual(v[4]["kpis"], [])
        self.assertEqual(v[6]["kpis"], ["DISPARU"])
        self.assertEqual(v[7]["origine"], {"tableau": 12, "tuile": 8, "type": "jauge", "brut": TOUTES[7]})
        self.assertEqual(v[8]["origine"]["saisi"], "XYZ · inconnu")
        self.assertEqual(v[8]["kpis"], [])
        self.assertTrue(all(x["hauteur"] == "m" and x["filtres"] == {} and x["options"] == {} for x in v))
        self.assertEqual(v[3]["origine"], {"tableau": 12, "tuile": 4, "type": "repartition"})

    def test_cas_limites(self):
        self.assertEqual(CT.convertir_tuiles(1, []), [])
        self.assertEqual(CT.convertir_tuiles(1, None), [])
        # contenu abîmé (pas une liste) : une tuile « indisponible » qui le garde tel quel, jamais jeté
        abime = CT.convertir_tuiles(1, {"pas": "une liste"})
        self.assertEqual([x["type"] for x in abime], ["indisponible"])
        self.assertEqual(abime[0]["origine"]["brut"], {"pas": "une liste"})
        v = CT.convertir_tuiles(1, ["chiffre", {}, {"type": "tableau"}, {"type": "chiffre", "largeur": 7, "titre": "x" * 300}])
        self.assertEqual([x["type"] for x in v], ["chiffre", "indisponible", "tableau", "chiffre"])
        self.assertEqual(v[1]["origine"]["brut"], {})
        self.assertEqual(v[2]["source"], "")
        self.assertEqual(v[3]["largeur"], 4)  # largeur inconnue
        self.assertEqual(len(v[3]["titre"]), 150)


class TableauxEnVuesTests(TestCase):
    def setUp(self):
        self.admin = Utilisateur.objects.create(username="admin", email="a@exemple.test", role=Utilisateur.Role.ADMIN)
        self.lecteur = Utilisateur.objects.create(username="lecteur", email="l@exemple.test", role=Utilisateur.Role.LECTEUR)
        self.contrib = Utilisateur.objects.create(username="contrib", email="c@exemple.test")
        self.t = [
            TableauVisu.objects.create(nom="Comité", description="Pour le comité", tuiles=TOUTES[:5], proprietaire=self.admin, partage=True),
            TableauVisu.objects.create(nom="Mes chiffres", tuiles=TOUTES[5:], proprietaire=self.lecteur),
            TableauVisu.objects.create(nom="Vide", tuiles=[], proprietaire=self.contrib),
            TableauVisu.objects.create(nom="Orphelin", tuiles=[{"type": "chiffre", "kpi": "EFF"}], proprietaire=None),
            TableauVisu.objects.create(nom="Achats", tuiles=[{"type": "chiffre", "kpi": "EFF"}], proprietaire=self.admin, partage=True),
        ]
        ancienne = timezone.now() - datetime.timedelta(days=40)
        TableauVisu.objects.filter(pk=self.t[1].pk).update(date_creation=ancienne, date_maj=ancienne + datetime.timedelta(days=1))
        self.avant = list(TableauVisu.objects.order_by("pk").values())

    def test_conversion(self):
        CT.tableaux_en_vues(apps, None)
        self.assertEqual(VueVisu.objects.count(), TableauVisu.objects.count())
        for t in TableauVisu.objects.all():
            v = VueVisu.objects.get(ancien_tableau=t.pk)
            with self.subTest(tableau=t.nom):
                self.assertEqual((v.nom, v.description, v.proprietaire_id, v.partage), (t.nom, t.description, t.proprietaire_id, t.partage))
                self.assertEqual((v.date_creation, v.date_maj), (t.date_creation, t.date_maj))
                self.assertEqual(len(v.visuels), len(t.tuiles))
                self.assertEqual([x["origine"]["tuile"] for x in v.visuels], list(range(1, len(t.tuiles) + 1)))
                self.assertEqual([x["origine"]["type"] for x in v.visuels], [x.get("type") for x in t.tuiles])
                self.assertEqual(v.filtres, {})
                self.assertFalse(AccueilVisu.objects.filter(vue=v).exists())
        # ordre : partagés d'abord, puis par nom (celui des onglets d'avant)
        self.assertEqual([v.nom for v in VueVisu.objects.order_by("ordre")], ["Achats", "Comité", "Mes chiffres", "Orphelin", "Vide"])
        self.assertEqual(list(TableauVisu.objects.order_by("pk").values()), self.avant)  # tableaux intacts
        # visibilité inchangée : l'orphelin non partagé n'est visible de personne
        self.assertEqual({v.nom for v in VueVisu.visibles(self.lecteur)}, {"Comité", "Achats", "Mes chiffres"})
        self.assertFalse(VueVisu.objects.get(nom="Orphelin").modifiable_par(self.admin))

    def test_idempotente_et_retour(self):
        CT.tableaux_en_vues(apps, None)
        CT.tableaux_en_vues(apps, None)
        self.assertEqual(VueVisu.objects.count(), 5)
        perso = VueVisu.objects.create(nom="Créée après", proprietaire=self.contrib)
        CT.retour(apps, None)
        self.assertEqual(list(VueVisu.objects.all()), [perso])  # seules les vues converties sont retirées
        self.assertEqual(list(TableauVisu.objects.order_by("pk").values()), self.avant)


class ModeleVueTests(TestCase):
    def test_une_seule_vue_d_accueil_par_role(self):
        a = VueVisu.objects.create(nom="A", partage=True)
        b = VueVisu.objects.create(nom="B", partage=True)
        AccueilVisu.objects.create(role="admin", vue=a)
        AccueilVisu.objects.create(role="lecteur", vue=a)
        AccueilVisu.objects.create(role="contributeur", vue=b)
        with self.assertRaises(IntegrityError), transaction.atomic():
            AccueilVisu.objects.create(role="admin", vue=b)
        b.delete()
        self.assertEqual(sorted(AccueilVisu.objects.values_list("role", flat=True)), ["admin", "lecteur"])
        self.assertEqual(AccueilVisu.ROLES, [r.value for r in Utilisateur.Role])

    def test_preference_et_suppression(self):
        u = Utilisateur.objects.create(username="u", email="u@exemple.test")
        v = VueVisu.objects.create(nom="Ma vue", proprietaire=u)
        p = PreferenceVisu.objects.create(utilisateur=u, vue_defaut=v, ordre=[v.pk])
        v.delete()
        p.refresh_from_db()
        self.assertIsNone(p.vue_defaut)  # la vue supprimée n'est plus la vue par défaut, la préférence reste
        self.assertEqual(VueVisu.objects.filter(proprietaire=u).count(), 0)


class AllerRetourTests(RetourSerialiseIndependantDeLOrdre, TransactionTestCase):
    """MigrationExecutor : 0021 (tableaux seulement) → 0023 (vues) → 0021 ; tableaux intacts, ligne à ligne."""

    serialized_rollback = True
    AVANT = [("collecte", "0021_relance_notee_a_la_main")]
    APRES = [("collecte", "0023_tableaux_en_vues")]

    def migrer(self, cible):
        e = MigrationExecutor(connection)
        e.loader.build_graph()
        e.migrate(cible)
        return e.loader.project_state(cible).apps

    def tearDown(self):
        self.migrer(MigrationExecutor(connection).loader.graph.leaf_nodes())
        super().tearDown()

    def test_aller_retour(self):
        anciennes = self.migrer(self.AVANT)
        U = anciennes.get_model("referentiel", "Utilisateur")
        T = anciennes.get_model("collecte", "TableauVisu")
        a = U.objects.create(username="adm", email="adm@exemple.test", role="admin")
        l = U.objects.create(username="lec", email="lec@exemple.test", role="lecteur")
        T.objects.create(nom="Comité", tuiles=TOUTES[:5], proprietaire=a, partage=True)
        T.objects.create(nom="Lecteur", tuiles=TOUTES[5:], proprietaire=l)
        T.objects.create(nom="Vide", tuiles=[], proprietaire=l)
        avant = list(T.objects.order_by("pk").values())
        nouvelles = self.migrer(self.APRES)
        V = nouvelles.get_model("collecte", "VueVisu")
        T2 = nouvelles.get_model("collecte", "TableauVisu")
        self.assertEqual(list(T2.objects.order_by("pk").values()), avant)
        self.assertEqual(V.objects.count(), 3)
        for t in avant:
            v = V.objects.get(ancien_tableau=t["id"])
            self.assertEqual((v.nom, v.proprietaire_id, v.partage, v.date_creation, v.date_maj),
                             (t["nom"], t["proprietaire_id"], t["partage"], t["date_creation"], t["date_maj"]))
            self.assertEqual(len(v.visuels), len(t["tuiles"]))
        CT.tableaux_en_vues(nouvelles, None)  # relancée : aucun doublon
        self.assertEqual(V.objects.count(), 3)
        anciennes = self.migrer(self.AVANT)
        self.assertEqual(list(anciennes.get_model("collecte", "TableauVisu").objects.order_by("pk").values()), avant)


class AccueilParRoleTests(RetourSerialiseIndependantDeLOrdre, TransactionTestCase):
    """Migration 0024 : la vue d'accueil pour tous devient celle des 5 rôles (rien ne change à l'écran) ; retour arrière :
    la vue d'accueil du plus grand nombre de rôles redevient la vue d'accueil pour tous. Vues et préférences intactes."""

    serialized_rollback = True
    AVANT = [("collecte", "0023_tableaux_en_vues")]
    APRES = [("collecte", "0024_accueil_par_role")]
    ROLES = ["admin", "validateur", "contributeur", "lecteur", "auditeur"]

    def migrer(self, cible):
        e = MigrationExecutor(connection)
        e.loader.build_graph()
        e.migrate(cible)
        return e.loader.project_state(cible).apps

    def tearDown(self):
        self.migrer(MigrationExecutor(connection).loader.graph.leaf_nodes())
        super().tearDown()

    @staticmethod
    def lignes(apps):
        champs = ["id", "nom", "description", "proprietaire_id", "partage", "ordre", "filtres", "visuels", "version", "date_maj"]
        vues = list(apps.get_model("collecte", "VueVisu").objects.order_by("pk").values(*champs))
        prefs = list(apps.get_model("collecte", "PreferenceVisu").objects.order_by("pk").values("utilisateur_id", "vue_defaut_id", "ordre"))
        return vues, prefs

    def test_aller_retour(self):
        anciennes = self.migrer(self.AVANT)
        U = anciennes.get_model("referentiel", "Utilisateur")
        V = anciennes.get_model("collecte", "VueVisu")
        a = U.objects.create(username="adm", email="adm@exemple.test", role="admin")
        c = U.objects.create(username="con", email="con@exemple.test", role="contributeur")
        comite = V.objects.create(nom="Comité", proprietaire=a, partage=True, accueil=True,
                                  visuels=[{"id": "x", "type": "chiffre", "kpis": ["EFF"]}], filtres={"org": 3})
        energie = V.objects.create(nom="Énergie", proprietaire=a, partage=True, ordre=1)
        perso = V.objects.create(nom="Perso", proprietaire=c)
        anciennes.get_model("collecte", "PreferenceVisu").objects.create(utilisateur=c, vue_defaut=perso, ordre=[perso.pk, comite.pk])
        avant = self.lignes(anciennes)
        nouvelles = self.migrer(self.APRES)
        A = nouvelles.get_model("collecte", "AccueilVisu")
        self.assertEqual(dict(A.objects.values_list("role", "vue_id")), {r: comite.pk for r in self.ROLES})
        self.assertEqual(self.lignes(nouvelles), avant)
        A.objects.filter(role="contributeur").update(vue_id=energie.pk)  # réglé par rôle après la mise à jour
        anciennes = self.migrer(self.AVANT)
        self.assertEqual(list(anciennes.get_model("collecte", "VueVisu").objects.filter(accueil=True).values_list("pk", flat=True)),
                         [comite.pk])  # la vue d'accueil de 4 rôles sur 5
        self.assertEqual(self.lignes(anciennes), avant)

    def test_sans_vue_d_accueil(self):
        anciennes = self.migrer(self.AVANT)
        anciennes.get_model("collecte", "VueVisu").objects.create(nom="Partagée", partage=True)
        nouvelles = self.migrer(self.APRES)
        self.assertFalse(nouvelles.get_model("collecte", "AccueilVisu").objects.exists())
        anciennes = self.migrer(self.AVANT)
        self.assertFalse(anciennes.get_model("collecte", "VueVisu").objects.filter(accueil=True).exists())
