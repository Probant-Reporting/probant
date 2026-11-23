"""Écart avec N-1 au-delà du seuil de la campagne (``saisie.ecart``, ``saisie.depasse_seuil``) : une seule règle pour la
saisie, la page Cohérence, l'import, les exports et l'affichage ; un commentaire vide ou fait seulement d'espaces ne
justifie pas l'écart."""
from decimal import Decimal as D

from django.test import SimpleTestCase, TestCase

from . import coherence as CO
from . import saisie as S
from .aides_tests.coherence import BaseCoherence
from .models import Reponse
from .templatetags import collecte as T


class DepasseSeuilTests(SimpleTestCase):
    def test_regle(self):
        self.assertFalse(S.depasse_seuil(None, D("0.2")))
        self.assertFalse(S.depasse_seuil(D("0.5"), None))
        self.assertFalse(S.depasse_seuil(D("0.2"), D("0.2")))  # au seuil : pas au-delà
        self.assertTrue(S.depasse_seuil(D("0.2000001"), D("0.2")))
        self.assertTrue(S.depasse_seuil(D("-0.3"), D("0.2")))  # baisse : en valeur absolue
        self.assertFalse(S.depasse_seuil(D("-0.2"), D("0.2")))

    def test_affichage_suit_la_regle(self):
        for e, seuil in ((D("0.2"), D("0.2")), (D("-0.25"), D("0.2")), (D("0.1"), None), (None, D("0.2"))):
            self.assertEqual(bool(T.ecart_sous(e, seuil)), S.depasse_seuil(e, seuil), (e, seuil))
            if e is not None:
                self.assertEqual("ecart-fort" in T.ecart_fleche(e, seuil), S.depasse_seuil(e, seuil), (e, seuil))

    def test_ecart(self):
        self.assertEqual(S.ecart(D(150), D(100)), D("0.5"))
        self.assertEqual(S.ecart(D(50), D(-100)), D("1.5"))  # rapporté à |N-1|
        self.assertIsNone(S.ecart(D(5), D(0)))
        self.assertIsNone(S.ecart(None, D(5)))


class CommentaireFaitDEspacesTests(TestCase):
    setUp = BaseCoherence.setUp
    saisir = BaseCoherence.saisir
    alertes = BaseCoherence.alertes

    def test_saisie_et_coherence_d_accord(self):
        r = self.saisir(self.eff, 150)
        Reponse.objects.filter(pk=r.pk).update(commentaire="   ")  # base ancienne, mode expert : espaces seuls
        r.refresh_from_db()
        motifs = S.controles_validation(r, self.c)
        self.assertTrue(any("écart" in m for m in motifs), motifs)  # ne justifie pas l'écart
        controles = [d["controle"] for d in CO.controles_automatiques(self.c, [self.eff.pk])]
        self.assertIn("ecart_n1", controles)  # la page Cohérence dit la même chose

    def test_commentaire_justifie(self):
        r = self.saisir(self.eff, 150, com="Rachat d'une filiale")
        self.assertFalse(any("cart" in m for m in S.controles_validation(r, self.c)))

    def test_n1_nul_ou_na_sans_ecart(self):
        for c in self.anciennes:
            Reponse.objects.filter(periode=c.periode, kpi=self.eff).update(valeur=D(0))
        r = self.saisir(self.eff, 150)
        self.assertFalse(any("cart" in m for m in S.controles_validation(r, self.c)))
        self.assertFalse(self.alertes(controle="ecart_n1").exists())
        Reponse.objects.filter(periode=self.anciennes[-1].periode, kpi=self.eff).update(valeur=None, non_applicable=True)
        r = self.saisir(self.eff, 160)
        self.assertFalse(any("cart" in m for m in S.controles_validation(r, self.c)))
        self.assertFalse(self.alertes(controle="ecart_n1").exists())
