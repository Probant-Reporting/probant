"""Import du fichier de configuration sous PostgreSQL (tout ou rien, une seule transaction) : les statistiques du
planificateur décrivent les KPI et les organisations importés dès la fin de l'import (``statistiques_postgresql``).

Mise en place d'une installation neuve depuis le fichier d'une autre : des centaines de KPI et d'organisations sur des
tables presque vides. Un ANALYZE de l'autovacuum pendant l'import les note vides (``reltuples = 0``) et le planificateur
compte une ligne par table jusqu'à son passage suivant, recalcul des campagnes compris. L'essai reproduit l'autovacuum :
un ANALYZE par une autre connexion au milieu de l'import."""
import io
from unittest import mock, skipUnless

from django.core.files.uploadedfile import SimpleUploadedFile

from . import configuration as C
from .aides_tests import echanges as TE
from .aides_tests.statistiques import (POSTGRES, analyze_par_une_autre_connexion, analyzes_prevus,
                                         verifier_lignes_notees)
from referentiel.models import KPI, Organisation

TABLES = ("referentiel_kpi", "referentiel_organisation")


@skipUnless(POSTGRES, "statistiques du planificateur de PostgreSQL")
class StatistiquesApresImportConfigurationTests(TE.Base):
    def fichier(self, n):
        wb = TE.classeur(C.exporter())
        lignes = {
            "KPI": [{"ID KPI": f"NEUF{i}", "Ordre": 9, "Nom (FR)": f"KPI {i}", "Type de saisie": "Saisi",
                     "Type de réponse": "Numérique", "Unité": "t", "Décimales": 2, "Granularité": "Entité",
                     "Agrégation": "Somme"} for i in range(n)],
            "Organisations": [{"Nom": f"Entité {i}", "Niveau": "Entité", "Rattachée à": "Pays"} for i in range(n)],
        }
        for onglet, ajout in lignes.items():
            tete = [c.value for c in wb[onglet][1]]
            for ligne in ajout:
                wb[onglet].append([ligne.get(t, "") for t in tete])
        flux = io.BytesIO()
        wb.save(flux)
        return SimpleUploadedFile("config.xlsx", flux.getvalue())

    def test_analyze_pendant_l_import(self):
        vraie = C.reconstruire_toutes_dependances

        def reconstruire():  # KPI et organisations écrits, transaction pas encore validée
            analyze_par_une_autre_connexion(TABLES)
            return vraie()

        f = self.fichier(150)
        with self.captureOnCommitCallbacks(execute=True) as rappels, mock.patch.object(C, "reconstruire_toutes_dependances",
                                                                                       reconstruire):
            a, n, _ = C.appliquer(self.admin, f, "config.xlsx")
        self.assertEqual(a.nb_rejets, 0)
        self.assertEqual(len(analyzes_prevus(rappels)), 1)
        self.assertEqual(KPI.objects.filter(code__startswith="NEUF").count(), 150)
        self.assertEqual(Organisation.objects.filter(nom__startswith="Entité ").count(), 150)
        verifier_lignes_notees(self, TABLES, minimum=150)

    def test_fichier_refuse_aucun_analyze(self):
        """Tout ou rien : un fichier refusé n'écrit rien, et ne demande aucun ANALYZE."""
        wb = TE.classeur(C.exporter())
        tete = [c.value for c in wb["KPI"][1]]
        wb["KPI"].append([{"ID KPI": "CASSE", "Nom (FR)": "Cassé", "Type de saisie": "Calculé",
                           "Formule": "[INCONNU] + 1"}.get(t, "") for t in tete])
        flux = io.BytesIO()
        wb.save(flux)
        with self.captureOnCommitCallbacks() as rappels:
            a, n, _ = C.appliquer(self.admin, SimpleUploadedFile("config.xlsx", flux.getvalue()), "config.xlsx")
        self.assertEqual((a.nb_rejets, n), (1, 0))
        self.assertEqual(analyzes_prevus(rappels), [])
