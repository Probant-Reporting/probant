"""Chaque modèle de la bibliothèque, installé sur une base vierge puis sur une base qui a déjà les autres modèles (dans les
deux ordres) : chaque KPI reçoit l'unité que sa définition demande (même symbole), jamais une autre unité rapprochée par
une forme sans symboles (« €/h » rangée en « h » avant la mise à jour). Garde aussi le contrôle de ``bibliotheque
--validate`` (``controle.controler_unites``)."""
from django.db import transaction
from django.test import SimpleTestCase, TestCase

from collecte import paquets as P
from parametres.rapprochement_unites import ecritures, symbole_normalise
from referentiel.bibliotheque import controle as C
from referentiel.models import KPI


def modeles():
    return [f.nom_fichier for f in P.bibliotheque()]


def installer(nom):
    a = P.analyser(P.fourni(nom).paquet, fourni=True)
    assert not a.erreur, a.erreur
    P.appliquer(None, a)


def unites_fausses(nom):
    """[(KPI, unité voulue, unité reçue)] des KPI du modèle dont l'unité n'a pas le symbole de leur définition."""
    p = P.fourni(nom).paquet
    unites = {u["code"]: u for u in p.unites}
    fausses = []
    for k in p.kpis:
        if not k.get("unite"):
            continue
        voulu = {symbole_normalise(s) for s in ecritures(unites[k["unite"]])[1]} or {symbole_normalise(k["unite"])}
        recue = KPI.objects.get(pk=k["code"]).unite
        if recue is None or not voulu & {symbole_normalise(s) for s in ecritures(recue)[1]}:
            fausses.append((k["code"], k["unite"], recue.symbole if recue else None))
    return fausses


class ModeleSeulTests(TestCase):
    def test_chaque_modele_sur_une_base_vierge(self):
        for nom in modeles():
            with self.subTest(modele=nom):
                sid = transaction.savepoint()
                installer(nom)
                self.assertEqual(unites_fausses(nom), [])
                transaction.savepoint_rollback(sid)


class ModelesEnsembleTests(TestCase):
    def _ordre(self, noms):
        for nom in noms:
            installer(nom)
            self.assertEqual(unites_fausses(nom), [], nom)

    def test_apres_les_autres(self):
        self._ordre(modeles())

    def test_dans_l_ordre_inverse(self):
        self._ordre(list(reversed(modeles())))

    def test_reinstallation_ne_change_rien(self):
        self._ordre(modeles())
        self._ordre(modeles())


class ControleBibliothequeTests(SimpleTestCase):
    def test_aucune_unite_rapprochee_d_une_autre(self):
        rapports = [C.Rapport(code=s["code"]) for s in C.S.SOCLES]
        C.controler_unites(rapports)
        self.assertEqual([(r.code, r.erreurs) for r in rapports if r.erreurs], [])

    def test_le_controle_voit_une_unite_rapprochee_par_son_libelle(self):
        socle = C.S.SOCLES[0]
        rapports = [C.Rapport(code=socle["code"])]
        connues = C.unites_connues
        try:  # unité d'installation dont le libellé est le symbole d'une unité du modèle : rapprochée, mais pas la même
            u = C.S.paquet(socle).unites[0]
            sym = next(iter(u["symbole"].values()))
            C.unites_connues = lambda: [("essai", [{"code": "autre", "symbole": {"fr": "zz"}, "libelle": {"fr": sym}}])]
            C.controler_unites(rapports)
        finally:
            C.unites_connues = connues
        self.assertTrue(rapports[0].erreurs)
