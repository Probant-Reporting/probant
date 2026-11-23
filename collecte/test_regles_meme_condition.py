"""Une règle de cohérence = une condition (``regles_textes.condition``, ``coherence.doublons``) ; textes des règles des
modèles de la bibliothèque dans la langue de la personne qui lit (``regles_textes.traduire``).

Défauts corrigés :
- deux modèles qui portent le même contrôle (norme VS de base et ESRS E5 : « Déchets recyclés ≤ déchets générés ») créaient
  deux règles dès que le nom de la première n'était plus le nom français (démo en anglais, nom changé par l'administrateur) :
  la bibliothèque ne reconnaissait une règle que par son nom, et une même violation donnait deux alertes ;
- une installation qui a déjà les deux règles : la règle en double n'est plus contrôlée, une seule alerte s'affiche ; une
  alerte de la règle en double déjà justifiée ou décidée garde son statut et sa justification ;
- le nom et l'explication d'une règle d'un modèle s'affichaient en français dans une interface anglaise ou allemande."""
from decimal import Decimal

from django.test import TestCase

from parametres import langues as L
from referentiel.models import Niveau

from . import coherence as CO
from . import paquets as P
from . import regles_textes as RT
from .aides_tests.paquets import vider
from .aides_tests.saisie import Base
from .models import Alerte, RegleCoherence, Reponse

D = Decimal
DECHETS = ("[DEC-RECYCLES]", "<=", "[DEC-TOTAL]")


def installer(fichier):
    a = P.analyser(P.fourni(fichier).paquet, source=fichier, fourni=True)
    assert a.erreur == "", a.erreur
    P.appliquer(None, a)
    return a


def regles_dechets():
    return [r for r in RegleCoherence.objects.all() if (r.gauche, r.operateur, r.droite) == DECHETS]


class InstallationMemeConditionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        vider()
        installer("vs_base.json")

    def test_nom_change_meme_condition_pas_recree(self):
        """Démo en anglais, ou nom changé par l'administrateur : ESRS E5 ne recrée pas la règle."""
        RegleCoherence.objects.filter(nom="Déchets recyclés ≤ déchets générés").update(nom="Recycled waste ≤ waste generated")
        a = installer("esrs_e5.json")
        self.assertEqual(len(regles_dechets()), 1)
        ligne = next(r for r in a.regles if r["nom"] == "Déchets recyclés ≤ déchets générés")
        self.assertEqual(ligne["statut"], "ignore")
        self.assertIn("Déchets recyclés ≤ déchets générés", ligne["motif"])  # nom de la règle existante, dans la langue de l'écran

    def test_meme_nom_meme_contenu_inchange(self):
        a = installer("esrs_e5.json")
        self.assertEqual(len(regles_dechets()), 1)
        self.assertEqual(next(r for r in a.regles if r["nom"] == "Déchets recyclés ≤ déchets générés")["statut"], "inchange")

    def test_condition_normalisee(self):
        # casse gardée (codes des KPI sensibles à la casse : test_formule_normalisee_casse)
        self.assertEqual(RT.condition("[A] + [B]", "<=", "[C]", D("0.0000"), "Site"), RT.condition("[A]+[B]", "<=", "[C]", 0, "Site"))
        self.assertNotEqual(RT.condition("[A]", "<=", "[C]", 0, "Site"), RT.condition("[A]", "<=", "[C]", 0, "Entity"))


class AlertesUneParConditionTests(Base):
    """Installation existante qui a déjà deux règles de même condition (avant la correction)."""

    def setUp(self):
        super().setUp()
        self.a = RegleCoherence.objects.create(nom="Effectif féminin ≤ effectif total", gauche="[EFF]", operateur="<=",
                                               droite="10", niveau_id=Niveau.ENTITY)
        self.b = RegleCoherence.objects.create(nom="Female headcount ≤ total headcount", gauche="[EFF] ", operateur="<=",
                                               droite="10", niveau_id=Niveau.ENTITY)
        for org in (self.e1, self.e2):
            Reponse.objects.create(periode=self.c.periode, kpi=self.eff, organisation=org, valeur=D(20), statut=Reponse.Statut.BROUILLON)

    def alertes(self, regle):
        return {a.organisation_id: a for a in Alerte.objects.filter(campagne=self.c, regle=regle)}

    def test_une_seule_alerte_par_violation(self):
        CO.controler(self.c)
        self.assertEqual(set(self.alertes(self.a)), {self.e1.pk, self.e2.pk})
        self.assertEqual(self.alertes(self.b), {})
        self.assertEqual(CO.doublons([self.a, self.b]), {self.b.pk: self.a})

    def test_alertes_de_la_regle_en_double_existantes(self):
        """Alertes créées avant la correction : celle déjà justifiée reste justifiée, celle à traiter passe « corrigée »
        (le même constat reste à traiter sur la règle gardée)."""
        commun = dict(campagne=self.c, kpi=self.eff, controle=Alerte.Controle.REGLE, regle=self.b, message="x", empreinte="20|10")
        justifiee = Alerte.objects.create(organisation=self.e1, statut=Alerte.Statut.JUSTIFIEE, justification="Explication", **commun)
        ouverte = Alerte.objects.create(organisation=self.e2, **commun)
        CO.controler(self.c)
        justifiee.refresh_from_db()
        ouverte.refresh_from_db()
        self.assertEqual((justifiee.statut, justifiee.justification), (Alerte.Statut.JUSTIFIEE, "Explication"))
        self.assertEqual(ouverte.statut, Alerte.Statut.CORRIGEE)
        self.assertEqual(set(self.alertes(self.a)), {self.e1.pk, self.e2.pk})

    def test_regle_bloquante_gardee(self):
        self.b.bloquante = True
        self.b.save()
        self.assertEqual(CO.doublons([self.a, self.b]), {self.a.pk: self.b})


class TextesReglesModelesTests(TestCase):
    def test_nom_et_explication_dans_la_langue_de_l_interface(self):
        r = RegleCoherence(nom="Déchets recyclés ≤ déchets générés", description="Les déchets recyclés font partie des déchets générés.")
        with L.activer("en"):
            self.assertEqual(r.nom_affiche, "Recycled waste ≤ waste generated")
            self.assertEqual(r.description_affichee, "Recycled waste is part of the waste generated.")
        with L.activer("de"):  # l'allemand vient des traductions des modèles ESRS (referentiel/bibliotheque/traductions)
            self.assertEqual(r.nom_affiche, "Recycelte Abfälle ≤ angefallene Abfälle")
        with L.activer("fr"):
            self.assertEqual(r.nom_affiche, "Déchets recyclés ≤ déchets générés")

    def test_nom_anglais_enregistre_affiche_en_francais(self):
        with L.activer("fr"):
            self.assertEqual(RT.traduire("Recycled waste ≤ waste generated"), "Déchets recyclés ≤ déchets générés")

    def test_suffixe_et_nom_propre_a_l_installation(self):
        with L.activer("en"):
            self.assertEqual(RT.traduire("Déchets recyclés ≤ déchets générés (ESRS_E5)"), "Recycled waste ≤ waste generated (ESRS_E5)")
            self.assertEqual(RT.traduire("Ma règle à moi"), "Ma règle à moi")

    def test_constat_d_une_alerte_recompose(self):
        a = Alerte(textes={"message": {"cle": "saisie.coherence.msg.regle_non_respectee",
                                       "v": {"regle": "Déchets recyclés ≤ déchets générés"}}}, message="x")
        with L.activer("en"):
            self.assertIn("Recycled waste ≤ waste generated", CO.texte_alerte(a, "message"))

    def test_paquet_textes_par_langue(self):
        self.assertEqual(RT.texte_paquet({"fr": "Nom", "en": "Name"}, "fr"), "Nom")
        self.assertEqual(RT.texte_paquet("Nom", "fr"), "Nom")
