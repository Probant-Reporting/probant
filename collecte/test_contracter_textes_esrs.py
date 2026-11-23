"""Textes des onze modèles ESRS révisées : article contracté en français (« liés au personnel », jamais « liés à le
personnel ») et aucun double article en anglais. Le bloc commun des exigences générales (``bloc_gdr``) contracte lui-même
« à le » et « à les » (``contracter``) ; ce test lit tous les textes français et anglais des paquets construits depuis les
définitions (noms, descriptions, thèmes, colonnes des tableaux, listes, règles)."""
import re

from django.test import SimpleTestCase

from referentiel.bibliotheque import socles as S
from referentiel.bibliotheque.definitions import _esrs_communs as EC

# « de le » et « à les » restent justes devant un verbe (pronom : « la norme demande de le dire ») : verbes admis.
VERBES_APRES_PRONOM = {"dire", "traiter"}
FRANCAIS = re.compile(r"\b(à|de) (les?)\s+([\wéèêàâîôûç'-]+)", re.IGNORECASE)
ANGLAIS = re.compile(r"\b(the|a|an) (the|a|an)\b", re.IGNORECASE)


def _tous(noeud):
    if isinstance(noeud, str):
        yield noeud
    elif isinstance(noeud, dict):
        for v in noeud.values():
            yield from _tous(v)
    elif isinstance(noeud, (list, tuple)):
        for v in noeud:
            yield from _tous(v)


def textes(noeud, langue):
    """Toutes les chaînes rangées sous la clé de la langue, à toute profondeur du paquet."""
    if isinstance(noeud, dict):
        for cle, v in noeud.items():
            yield from (_tous(v) if cle == langue else textes(v, langue))
    elif isinstance(noeud, (list, tuple)):
        for v in noeud:
            yield from textes(v, langue)


def paquets_esrs():
    return {s["code"]: S.paquet(s) for s in S.SOCLES if s["code"] in EC.MODELES}


def textes_francais(p):
    """Textes français d'un paquet : ceux rangés sous « fr » et les descriptions des règles (écrites en français)."""
    yield from textes(vars(p), "fr")
    yield from (r["description"] for r in p.regles)


class ContracterTests(SimpleTestCase):
    def test_formes_contractees(self):
        for prep, groupe, attendu in (("à", "le personnel", "au personnel"), ("à", "les communautés", "aux communautés"),
                                      ("de", "le changement", "du changement"), ("de", "les ressources", "des ressources"),
                                      ("à", "l'eau", "à l'eau"), ("à", "la pollution", "à la pollution"),
                                      ("à", "des sujets propres", "à des sujets propres"), ("à", "lequel", "à lequel")):
            with self.subTest(groupe=groupe):
                self.assertEqual(EC.contracter(prep, groupe), attendu)

    def test_bloc_gdr_contracte_et_accepte_une_forme_fournie(self):
        bloc = dict(EC.bloc_gdr("ESSAI", ("les travailleurs", "workers")))
        self.assertIn("liés aux travailleurs ?", bloc["ESSAI-POLITIQUES"]["description"][0])
        bloc = dict(EC.bloc_gdr("ESSAI", ("les ressources et l'eau", "resources and water", "aux ressources et à l'eau")))
        self.assertIn("liés aux ressources et à l'eau ?", bloc["ESSAI-ACTIONS"]["description"][0])
        self.assertIn("Politiques adoptées sur les ressources et l'eau", bloc["ESSAI-POLITIQUES"]["fr"])


class TextesDesOnzeModelesTests(SimpleTestCase):
    def test_onze_modeles_lus(self):
        self.assertEqual(set(paquets_esrs()), set(EC.MODELES))
        self.assertEqual(len(EC.MODELES), 11)

    def test_aucun_article_non_contracte_en_francais(self):
        for code, p in paquets_esrs().items():
            fautes = sorted({m.group(0) for t in textes_francais(p) for m in FRANCAIS.finditer(t)
                             if m.group(3).lower() not in VERBES_APRES_PRONOM})
            with self.subTest(modele=code):
                self.assertEqual(fautes, [])

    def test_aucun_double_article_en_anglais(self):
        for code, p in paquets_esrs().items():
            fautes = sorted({m.group(0) for t in textes(vars(p), "en") for m in ANGLAIS.finditer(t)})
            with self.subTest(modele=code):
                self.assertEqual(fautes, [])
