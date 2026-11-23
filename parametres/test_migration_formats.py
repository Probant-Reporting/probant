"""Migration 0011 : formats « Nombre entier » et « Montant » repris par l'unité, sans perte."""
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

from referentiel.models import Niveau


class FormatsSimplifiesTests(TransactionTestCase):
    avant = [("parametres", "0010_thematique_pourcentage"), ("referentiel", "0009_versions_referentiels")]
    apres = [("parametres", "0011_formats_simplifies")]

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def test_entier_et_montant_passent_a_l_unite(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.avant)
        apps = executor.loader.project_state(self.avant).apps
        TR, U, K = (apps.get_model("parametres", "TypeReponse"), apps.get_model("parametres", "Unite"),
                    apps.get_model("referentiel", "KPI"))
        c6 = dict(couleur="#000000", couleur_fond="#FFFFFF", couleur_texte="#000000")
        apps.get_model("parametres", "NiveauHierarchique").objects.get_or_create(
            code=Niveau.ENTITY, defaults=dict(rang=2, nom="Entité", nom_pluriel="Entités", couleur_pale="#FFFFFF", **c6))
        apps.get_model("parametres", "TypeSaisie").objects.get_or_create(code="Saisi", defaults=dict(libelle="Saisie", abrege="S", **c6))
        TR.objects.create(code="Ent", libelle="Entier", format="entier")
        TR.objects.create(code="Mnt", libelle="Montant", format="montant", devise="CHF")
        TR.objects.get_or_create(code="Num", defaults=dict(libelle="Nombre", format="nombre"))
        U.objects.filter(symbole__in=["salariés", "nombre", "CHF"]).delete()  # unités d'installation : partir d'un état connu
        sal = U.objects.create(code="sal", symbole="salariés", entier=False, decimales=1)  # aussi utilisée par un nombre
        km = U.objects.update_or_create(code="km", defaults=dict(symbole="km", entier=False, decimales=1))[0]  # seulement par un entier
        ke = U.objects.update_or_create(code="k€", defaults=dict(symbole="k€", decimales=0))[0]

        def kpi(code, tr, unite=None):
            return K.objects.create(code=code, libelle=code, type_saisie_id="Saisi", granularite_id=Niveau.ENTITY,
                                    type_reponse_id=tr, unite=unite, decimales=2)
        kpi("E1", "Ent", sal), kpi("N1", "Num", sal), kpi("E2", "Ent", km), kpi("E3", "Ent"), kpi("M1", "Mnt"), kpi("M2", "Mnt", ke)

        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(self.apres)
        apps = executor.loader.project_state(self.apres).apps
        TR, U, K = (apps.get_model("parametres", "TypeReponse"), apps.get_model("parametres", "Unite"),
                    apps.get_model("referentiel", "KPI"))
        self.assertEqual(set(TR.objects.filter(code__in=["Ent", "Mnt"]).values_list("format", flat=True)), {"nombre"})
        k = {x.code: x for x in K.objects.select_related("unite")}
        # unité partagée avec un nombre : copie entière ; unité propre : cochée entière ; sans unité : « nombre »
        self.assertEqual((k["E1"].unite.symbole, k["E1"].unite.entier, k["E1"].decimales), ("salariés", True, 0))
        self.assertFalse(k["N1"].unite.entier)
        self.assertEqual((k["E2"].unite.code, k["E2"].unite.entier), ("km", True))
        self.assertEqual((k["E3"].unite.symbole, k["E3"].unite.entier), ("nombre", True))
        # montant : la devise devient l'unité ; une unité existante est gardée
        self.assertEqual((k["M1"].unite.symbole, k["M1"].unite.famille), ("CHF", "Monnaie"))
        self.assertEqual(k["M2"].unite.symbole, "k€")
