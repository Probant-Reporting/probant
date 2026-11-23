"""Signal ``recalcul_apres_saisie`` : un changement de statut seul (validation, retour en brouillon, preuve déposée sur
une valeur validée) ne relance pas le recalcul ni le contrôle de cohérence.

Ni les totaux enregistrés ni les alertes ne dépendent du statut d'une saisie : le recalcul refaisait exactement ce qui
était en base, en tenant le verrou de toutes les périodes (``calcul._recalculer``). Sous charge (50 personnes sur la grosse
base, PostgreSQL), chaque validation tenait ainsi ce verrou une à cinq secondes de plus et les enregistrements des
autres attendaient derrière (``qa/load/concurrent_users.py``).

1. Cas écrits à la main : la validation, le retour en brouillon et la preuve sur une valeur validée n'appellent plus
   ``recalculer`` ; une saisie de valeur l'appelle toujours.
2. Équivalence sur des cas générés (graine fixe) : une suite de saisies, validations, retours en brouillon, preuves et
   remises à saisir au hasard sur le jeu à trois niveaux (référentiel annuel et mois cumulés dans l'année) ; après CHAQUE
   opération, l'état (réponses, alertes, journal) est comparé à celui de la même opération suivie du recalcul et du
   contrôle que faisait le signal avant (``signals.apres_modification``). Données inventées uniquement."""
import random
from decimal import Decimal
from unittest import mock

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.test import TestCase, override_settings

from referentiel.models import Utilisateur

from . import saisie as S
from . import signals as SG
from .models import Alerte, Campagne, Journal, Reponse

PDF = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj "
       b"3 0 obj<</Type/Page/MediaBox[0 0 200 200]/Parent 2 0 R>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n")
COLONNES = ("periode_id", "kpi_id", "organisation_id", "valeur", "texte", "non_applicable", "statut", "origine",
            "message_calcul", "commentaire", "saisi_par_id", "valide_par_id")


def _cases(campagne):
    """Cases saisissables numériques de la campagne (KPI collectés, organisation de leur granularité, pas calculées)."""
    from referentiel.models import Organisation

    orgs = list(Organisation.objects.filter(actif=True))
    sortie = []
    for k in S.kpis_collectes(campagne.referentiel).select_related("type_reponse", "type_saisie", "unite").order_by("code"):
        if not k.est_numerique or k.est_herite or not S.dans_la_campagne(campagne, k):
            continue
        sortie += [(k, o) for o in orgs if o.niveau_id == k.granularite_id and not S.est_calculee(k, o, None, campagne)]
    return sortie


def _etat():
    # réponse du journal désignée par sa case, pas par son numéro : sous PostgreSQL, une réponse créée après un retour au
    # point de sauvegarde reçoit un autre numéro (la séquence n'est pas annulée)
    cases = {str(pk): (p, k, o) for pk, p, k, o in Reponse.objects.values_list("pk", "periode_id", "kpi_id", "organisation_id")}
    journal = [(a, ob, str(cases.get(i, i)) if ob == "Reponse" else i, ch, av, ap)
               for a, ob, i, ch, av, ap in Journal.objects.values_list("action", "objet", "objet_id", "champ", "avant", "apres")]
    return (sorted(Reponse.objects.values_list(*COLONNES)),
            sorted(Alerte.objects.values_list("campagne_id", "kpi_id", "organisation_id", "controle", "regle_id", "statut",
                                              "valeur", "reference", "message")),
            sorted(journal))


@override_settings(PREUVE_TAILLE_MAX=5 * 1024 * 1024)
class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        from .aides_tests import jeu_trois_niveaux as J

        J.charger()

    def setUp(self):
        self.admin = Utilisateur.objects.get(username="admin")
        self.annuelle = Campagne.objects.get(referentiel_id="REPORTING", exercice=2026)
        self.mensuelle = Campagne.objects.filter(referentiel_id="ENERGIE", statut=Campagne.Statut.OUVERTE).get()


class StatutSeulTests(Base):
    def _brouillon(self, campagne):
        """Une case de la campagne en brouillon, avec une valeur qui peut être validée (pas d'écart avec N-1)."""
        for k, o in _cases(campagne):
            n1 = S.reponse_n1(campagne, k, o)
            if n1 is None or n1.valeur is None or kpi_bloque(k):
                continue
            S.enregistrer(self.admin, campagne, k, o, str(n1.valeur), False, "")
            r = S.reponse_de(campagne, k, o)
            if not S.controles_validation(r, campagne):
                return k, o
        self.fail("aucune case validable")

    def test_validation_brouillon_preuve_sans_recalcul(self):
        for campagne in (self.annuelle, self.mensuelle):
            with self.subTest(campagne=str(campagne)):
                k, o = self._brouillon(campagne)
                with mock.patch("collecte.calcul.recalculer") as rc, mock.patch("collecte.coherence.controler") as ct:
                    S.valider(self.admin, campagne, k, o)
                    S.repasser_brouillon(self.admin, campagne, k, o)
                    S.valider(self.admin, campagne, k, o)
                    S.ajouter_preuve(self.admin, campagne, k, o, SimpleUploadedFile("p.pdf", PDF, "application/pdf"))
                self.assertEqual((rc.call_count, ct.call_count), (0, 0))
                self.assertEqual(S.reponse_de(campagne, k, o).statut, Reponse.Statut.BROUILLON)  # la preuve l'y a remise

    def test_saisie_de_valeur_toujours_recalculee(self):
        k, o = self._brouillon(self.annuelle)
        with mock.patch("collecte.calcul.recalculer") as rc:
            S.enregistrer(self.admin, self.annuelle, k, o, "123456", False, "")
        self.assertEqual(rc.call_count, 1)


def kpi_bloque(k):
    return k.preuve_obligatoire


class EquivalenceTests(Base):
    """Après chaque opération, même état qu'avec le recalcul et le contrôle d'avant (graines fixes)."""

    def _operation(self, R, campagne, k, o):
        r = S.reponse_de(campagne, k, o)
        choix = R.random()
        if choix < 0.35 or r is None or r.valeur is None:
            n1 = S.reponse_n1(campagne, k, o)
            base = n1.valeur if n1 is not None and n1.valeur else Decimal(R.randint(10, 5000))
            v = (base * Decimal(R.choice(["1", "1.05", "0.97", "2", "0.4"]))).quantize(Decimal("1"))
            S.enregistrer(self.admin, campagne, k, o, str(v), False, "essai")
        elif choix < 0.65:
            S.valider(self.admin, campagne, k, o)
        elif choix < 0.8:
            S.repasser_brouillon(self.admin, campagne, k, o)
        elif choix < 0.93:
            S.ajouter_preuve(self.admin, campagne, k, o, SimpleUploadedFile("p.pdf", PDF, "application/pdf"))
        else:
            S.remettre_a_saisir(self.admin, campagne, k, o)

    def test_equivalence(self):
        cases = [(self.annuelle, k, o) for k, o in _cases(self.annuelle)] + [(self.mensuelle, k, o) for k, o in _cases(self.mensuelle)]
        self.assertGreater(len(cases), 20)
        operations = sautees = 0
        for graine in (1, 2, 3):
            R = random.Random(graine)
            for _ in range(40):
                campagne, k, o = R.choice(cases)
                etat_r = R.getstate()
                point = transaction.savepoint()
                try:
                    self._operation(R, campagne, k, o)
                except ValidationError:
                    transaction.savepoint_rollback(point)
                    sautees += 1
                    continue
                nouveau = _etat()
                transaction.savepoint_rollback(point)
                R.setstate(etat_r)
                self._operation(R, campagne, k, o)
                SG.apres_modification(campagne.periode, [k.code], {o.id})  # ce que faisait le signal après chaque écriture
                self.assertEqual(nouveau, _etat(), f"graine {graine}, {k.code} / {o} / {campagne}")
                transaction.savepoint_commit(point)
                operations += 1
        self.assertGreater(operations, 60)
        self.assertLess(sautees, operations)
