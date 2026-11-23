"""Index des accès (``comptes.indexer``) : à chaque réconciliation (chaque démarrage, chaque restauration), seules les
lignes qui changent sont écrites. Avant, toutes les lignes de l'espace étaient supprimées puis recréées avec de nouveaux
numéros (contenu identique) : écritures inutiles à chaque démarrage, numéros qui grimpent, et un instant sans aucun
accès pour qui ouvrait une page pendant ce temps."""
from referentiel.models import Utilisateur

from . import comptes as EC
from . import contexte as E
from .aides_tests import creer
from .essais import EspacesTestCase
from .models import AccesEspace, Espace


def index(code):
    return {(a.compte_id, a.role, a.actif): a.pk for a in AccesEspace.objects.filter(espace__code=code)}


class IndexerAcces(EspacesTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.admin = creer("admin.essai@exemple.example", "admin", "essai")
        cls.contrib = creer("contrib.essai@exemple.example", "contributeur", "essai")
        cls.lecteur = creer("lecteur.essai@exemple.example", "lecteur", "essai")

    def test_reconciliation_sans_changement_ne_reecrit_rien(self):
        EC.reconcilier()
        avant = index("essai")
        self.assertEqual(len(avant), 3)
        EC.reconcilier()
        EC.reconcilier(["essai"])
        self.assertEqual(index("essai"), avant)  # mêmes lignes, mêmes numéros

    def test_seules_les_lignes_changees_sont_ecrites(self):
        EC.reconcilier()
        avant = {a.compte_id: a.pk for a in AccesEspace.objects.filter(espace__code="essai")}
        with E.activer("essai"):
            Utilisateur.objects.filter(pk=self.contrib.pk).update(role="validateur")  # rôle changé sans signal
            Utilisateur.objects.filter(pk=self.lecteur.pk).update(is_active=False)
            Utilisateur.objects.filter(pk=self.admin.pk).delete()
        nouveau = creer("nouveau.essai@exemple.example", "contributeur", "essai")
        AccesEspace.objects.filter(compte_id=nouveau.pk).delete()  # pas encore indexé
        EC.indexer(Espace.objects.get(code="essai"), "espace_essai")
        apres = {a.compte_id: a for a in AccesEspace.objects.filter(espace__code="essai")}
        self.assertNotIn(self.admin.pk, apres)  # copie supprimée : accès retiré
        self.assertEqual((apres[self.contrib.pk].role, apres[self.contrib.pk].pk), ("validateur", avant[self.contrib.pk]))
        self.assertEqual((apres[self.lecteur.pk].actif, apres[self.lecteur.pk].pk), (False, avant[self.lecteur.pk]))
        self.assertEqual(apres[nouveau.pk].role, "contributeur")
