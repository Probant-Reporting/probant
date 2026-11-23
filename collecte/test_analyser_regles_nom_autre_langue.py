"""Mise à jour d'un modèle de la bibliothèque (``paquets.analyse_kpis._analyser_regles``) : une règle existante est
reconnue sous chacun des noms que le paquet lui donne (``regles_textes.textes_regle``), pas seulement sous celui de la langue
de référence de l'installation.

Défaut corrigé : une installation de référence anglaise qui a installé le modèle avec une version d'avant a gardé le nom
français de la règle ; à la mise à jour, la règle n'était cherchée que sous son nom anglais, se retrouvait « ignorée : même
contrôle que » elle-même, et une explication ou un « bloquante » corrigé dans le modèle n'était jamais appliqué."""
import copy

from parametres.models import Instance

from . import paquets as P
from .aides_tests.paquets import vider
from .aides_tests.saisie import Base
from .models import RegleCoherence

NOM_FR, NOM_EN = "Effectif féminin ≤ effectif total", "Female headcount ≤ total headcount"


def analyser(paquet):
    a = P.analyser(paquet, source="vs_base.json", fourni=True)
    assert a.erreur == "", a.erreur
    return a


class ReglesNomFrancaisInstallationAnglaiseTests(Base):
    @classmethod
    def setUpTestData(cls):
        i = Instance.courante()
        i.langue_reference, i.langue = "en", "en"
        i.save()
        vider()
        P.appliquer(None, analyser(P.fourni("vs_base.json").paquet))
        # installé avec une version d'avant : le nom français a été enregistré
        RegleCoherence.objects.filter(nom=NOM_EN).update(nom=NOM_FR)

    def paquet_corrige(self):
        p = copy.deepcopy(P.fourni("vs_base.json").paquet)
        r = next(r for r in p.regles if r["nom"] == NOM_FR)
        r["bloquante"] = not r.get("bloquante")
        return p, bool(r["bloquante"])

    def test_regle_mise_a_jour_sous_son_nom_francais(self):
        avant = RegleCoherence.objects.count()
        p, bloquante = self.paquet_corrige()
        a = analyser(p)
        self.assertEqual(a.mode, "mise_a_jour")
        ligne = next(l for l in a.regles if l["nom"] == NOM_EN)
        self.assertEqual(ligne["statut"], "modifie", ligne["motif"])
        P.appliquer(None, a)
        self.assertEqual(RegleCoherence.objects.count(), avant)  # aucun doublon
        regle = RegleCoherence.objects.get(gauche="[SOC-EFF-FEMMES]", droite="[SOC-EFFECTIF]")
        self.assertEqual((regle.nom, regle.bloquante), (NOM_FR, bloquante))  # nom enregistré gardé, correction appliquée

    def test_paquet_identique_inchange(self):
        ligne = next(l for l in analyser(P.fourni("vs_base.json").paquet).regles if l["nom"] == NOM_EN)
        self.assertEqual(ligne["statut"], "inchange", ligne["motif"])
