"""Deux gestionnaires des espaces se retirent le rôle l'un l'autre au même instant (page Espaces, fiche d'un compte) :
``comptes.changer_gestionnaire`` relit l'acteur sous verrou au registre commun, donc un seul retrait passe et
l'installation garde un gestionnaire actif. À lancer aussi sous PostgreSQL (``DATABASE_URL``)."""
import threading

from django.core.exceptions import PermissionDenied
from django.db import connections
from django.test import TransactionTestCase

from referentiel.models import Utilisateur

from . import comptes as EC
from .aides_tests import creer
from .models import Compte


class RetraitsCroisesTests(TransactionTestCase):
    databases = {"default", "commun"}

    def setUp(self):
        # bases de test SQLite en mémoire partagée : un verrou de table y répond « table is locked » sans attendre (les
        # vraies bases SQLite, en fichier, WAL et transactions IMMEDIATE, font attendre le second) ; essai à plusieurs
        # fils donc sous PostgreSQL seulement. Sous SQLite : test_acteur_relu_sous_verrou (acteur relu dans la transaction)
        if connections["commun"].vendor == "sqlite":
            self.skipTest("bases SQLite de test en mémoire partagée : voir le commentaire")

    def test_un_seul_retrait_passe(self):
        for _ in range(5):  # plusieurs tours : l'ordre d'arrivée change
            a = creer(f"a{_}@exemple.example", "admin")
            b = creer(f"b{_}@exemple.example", "admin")
            Compte.objects.filter(pk__in=[a.pk, b.pk]).update(gestionnaire=True)
            Compte.objects.exclude(pk__in=[a.pk, b.pk]).update(gestionnaire=False)
            barriere, resultats = threading.Barrier(2), []

            def fil(acteur, cible):
                try:
                    barriere.wait()
                    resultats.append(EC.changer_gestionnaire(Utilisateur.objects.get(pk=acteur), cible, False)[0])
                except PermissionDenied:
                    resultats.append("refus")
                except Exception as e:  # noqa: BLE001 - dit par le test
                    resultats.append(repr(e))
                finally:
                    for c in connections.all():
                        c.close()

            fils = [threading.Thread(target=fil, args=(a.pk, b.pk)), threading.Thread(target=fil, args=(b.pk, a.pk))]
            for f in fils:
                f.start()
            for f in fils:
                f.join(30)
            self.assertEqual(sorted(map(str, resultats)), ["True", "refus"])
            self.assertEqual(Compte.objects.filter(gestionnaire=True, actif=True).count(), 1)

    def test_deux_desactivations_croisees(self):
        """Deux administrateurs désactivent chacun l'un des deux derniers gestionnaires au même instant (fiche, ou toute
        copie enregistrée) : ``comptes.appliquer`` relit sous verrou, un seul passe, un gestionnaire capable d'agir
        reste."""
        from django.db import transaction

        from .models import Espace

        Espace.objects.get_or_create(code="principal", defaults={"nom": "Principal", "etat": "actif"})
        for _ in range(5):
            g1 = creer(f"g1{_}@exemple.example", "admin")
            g2 = creer(f"g2{_}@exemple.example", "admin")
            Compte.objects.filter(pk__in=[g1.pk, g2.pk]).update(gestionnaire=True)
            Compte.objects.exclude(pk__in=[g1.pk, g2.pk]).update(gestionnaire=False)
            barriere, resultats = threading.Barrier(2), []

            def fil(cible):
                try:
                    u = Utilisateur.objects.get(pk=cible)
                    barriere.wait()
                    with transaction.atomic():
                        u.is_active = False
                        u.save(update_fields=["is_active"])
                    resultats.append("fait")
                except EC.DernierGestionnaire:
                    resultats.append("refus")
                except Exception as e:  # noqa: BLE001 - dit par le test
                    resultats.append(repr(e))
                finally:
                    for c in connections.all():
                        c.close()

            fils = [threading.Thread(target=fil, args=(g1.pk,)), threading.Thread(target=fil, args=(g2.pk,))]
            for f in fils:
                f.start()
            for f in fils:
                f.join(30)
            self.assertEqual(sorted(resultats), ["fait", "refus"])
            self.assertEqual(len(EC.gestionnaires_capables()), 1)
            self.assertEqual(Utilisateur.objects.filter(pk__in=[g1.pk, g2.pk], is_active=True).count(), 1)
