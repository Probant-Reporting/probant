"""Nom de l'outil par défaut : « Probant » dans toute l'histoire des migrations de ``parametres``.

Une base neuve crée la ligne de l'instance avec le nom par défaut de l'état des migrations (``0002_identite``) : ce nom
est « Probant » dès ``0001_instance``, et ``0028_nom_probant`` ne fait plus que poser le défaut du modèle. Aller et retour
autour de ``0028`` : un nom, choisi ou par défaut, n'est jamais changé.

``TransactionTestCase`` sans ``serialized_rollback``, comme les autres tests de migration de l'application (voir
``test_visualisation.MigrationParametresTests`` : une remise des données après un test qui a vidé la base échouerait
sur les types de contenu). Le ``tearDown`` ramène la base à la dernière migration."""
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class MigrationNomProbantTests(TransactionTestCase):
    AVANT = [("parametres", "0027_categories_traduites")]
    APRES = [("parametres", "0028_nom_probant")]

    def migrer(self, cible):
        e = MigrationExecutor(connection)
        e.loader.build_graph()
        e.migrate(cible)
        return e.loader.project_state(cible).apps

    def tearDown(self):
        self.migrer(MigrationExecutor(connection).loader.graph.leaf_nodes())
        super().tearDown()

    def instance(self, apps):
        return apps.get_model("parametres", "Instance")

    def test_defaut_probant_dans_tous_les_etats(self):
        e = MigrationExecutor(connection)
        noeuds = [n for n in e.loader.graph.forwards_plan(e.loader.graph.leaf_nodes("parametres")[0])
                  if n[0] == "parametres"]
        for noeud in noeuds:
            with self.subTest(migration=noeud[1]):
                modele = self.instance(e.loader.project_state(noeud).apps)
                self.assertEqual(modele._meta.get_field("titre").default, "Probant")

    def test_retour_avant_0028_garde_le_nom(self):
        nouvelles = self.migrer(self.APRES)
        self.instance(nouvelles).objects.update_or_create(pk=1, defaults={"titre": "Probant", "nom": "Client"})
        anciennes = self.migrer(self.AVANT)
        i = self.instance(anciennes).objects.get(pk=1)
        self.assertEqual((i.titre, i.nom), ("Probant", "Client"))

    def test_nom_choisi_conserve(self):
        anciennes = self.migrer(self.AVANT)
        for choisi in ("Mon outil", "Outil Groupe"):
            with self.subTest(titre=choisi):
                self.instance(anciennes).objects.update_or_create(pk=1, defaults={"titre": choisi})
                self.assertEqual(self.instance(self.migrer(self.APRES)).objects.get(pk=1).titre, choisi)
                self.assertEqual(self.instance(self.migrer(self.AVANT)).objects.get(pk=1).titre, choisi)

    def test_nouveau_defaut_enregistre(self):
        nouvelles = self.migrer(self.APRES)
        self.assertEqual(self.instance(nouvelles)._meta.get_field("titre").default, "Probant")
