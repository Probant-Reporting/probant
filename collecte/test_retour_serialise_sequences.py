"""Remise à l'état d'origine d'une classe ``serialized_rollback`` (``RetourSerialiseIndependantDeLOrdre``) après un test
qui a ramené les séquences au début : sous PostgreSQL, Django réinsère les lignes du cliché (modèles d'export fournis,
niveaux, types… créés par les migrations) avec leur numéro, sans remettre les séquences au-dessus. La création suivante
reprenait alors le numéro 1, déjà pris : « duplicate key value violates unique constraint collecte_reglageexport_pkey »,
selon l'ordre des tests (constaté sur GitHub, ``test_navigateur_corbeille`` après ``test_restaurer_reconstruire``).

Un test qui restaure une sauvegarde le fait légitimement : ``restaurer`` vide la base par ``flush``, qui remet toutes les
séquences au début (``TRUNCATE … RESTART IDENTITY``), puis ``loaddata`` ne remet au-dessus que celles des tables de
l'archive (côté produit, rien n'est faux : une table absente de l'archive reste vide)."""
from django.core.management import call_command
from django.db import connections
from django.test import TransactionTestCase

from .models import ReglageExport
from .outils_tests import RetourSerialiseIndependantDeLOrdre, tables_en_retard


class SequencesApresLeClicheTests(RetourSerialiseIndependantDeLOrdre, TransactionTestCase):
    serialized_rollback = True

    def test_creation_apres_un_test_qui_a_remis_les_sequences_au_debut(self):
        self.assertTrue(ReglageExport.objects.exists())  # modèles d'export fournis par les migrations, dans le cliché
        # ce que laisse un test précédent qui a restauré une sauvegarde : base vidée, séquences au début
        for alias in ("default", "commun"):
            call_command("flush", interactive=False, verbosity=0, database=alias)
        self.assertFalse(ReglageExport.objects.exists())
        # puis la remise à l'état d'origine de la classe suivante (celle d'avant chaque test d'une classe serialized_rollback)
        type(self)._fixture_setup()
        self.assertTrue(ReglageExport.objects.exists())
        for alias in ("default", "commun"):
            self.assertEqual(tables_en_retard(connections[alias]), [], alias)
        r = ReglageExport.objects.create(nom="Pour le comité", parametres={}, ordre=99)  # avant : IntegrityError (id 1)
        self.assertGreater(r.pk, max(ReglageExport.objects.exclude(pk=r.pk).values_list("pk", flat=True)))
