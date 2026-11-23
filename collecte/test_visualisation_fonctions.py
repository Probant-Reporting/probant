"""Filet de tests de la visualisation (collecte/visualisation.py) : figent le comportement actuel.

Décompte relu depuis le texte enregistré, égalité tolérante entre valeur validée et valeur de l'outil, répartition
(« Autres » au-delà de 6 organisations, « Autres réponses » au-delà de 8 réponses), comparaison triée, évolution
qui commence au début de l'historique, écart avec N-1, périodes proposées et période par défaut."""
from collections import Counter
from decimal import Decimal

from parametres.models import TypeReponse
from referentiel.formule import NA
from referentiel.models import KPI, Niveau, Organisation

from . import saisie as S
from . import visualisation as V
from .calcul import Decompte
from .models import Campagne, Reponse
from .aides_tests.echanges import Base

D = Decimal


class FonctionsTests(Base):
    def test_decompte_relu(self):
        self.assertEqual(V.decompte("Oui : 3 · Non : 2"), Counter({"Oui": 3, "Non": 2}))
        self.assertEqual(V.decompte("Oui"), Counter({"Oui": 1}))
        self.assertEqual(V.decompte(""), Counter())
        self.assertEqual(V.decompte(None), Counter())
        self.assertEqual(V.decompte(D(3)), Counter())
        self.assertEqual(V.decompte(Decompte({"Oui": 2})), Counter({"Oui": 2}))
        self.assertEqual(V.decompte("Note : A · Oui : 2"), Counter({"Note : A": 1, "Oui": 2}))  # « : » sans nombre : une réponse

    def test_egalite_tolerante(self):
        k = self.eff
        self.assertTrue(V._egales(D("100"), D("100.000000001"), k))
        self.assertFalse(V._egales(D("100"), D("100.01"), k))
        self.assertTrue(V._egales(NA, NA, k))
        self.assertFalse(V._egales(NA, D(0), k))
        self.assertFalse(V._egales(None, None, k))
        self.assertTrue(V._egales(Decompte({"Oui": 1, "Non": 1}), "Oui : 1 · Non : 1", k))

    def test_point_et_ecart(self):
        p, n1 = V.Point(D(110)), V.Point(D(100))
        self.assertEqual((p.nombre, p.na), (D(110), False))
        self.assertEqual(V.ecart(p, n1), D("0.1"))
        self.assertIsNone(V.ecart(p, None))
        self.assertIsNone(V.ecart(p, V.Point(NA)))
        self.assertIsNone(V.ecart(V.Point("Oui"), n1))
        self.assertTrue(V.Point(NA).na)
        self.assertIsNone(V.Point("Oui").nombre)

    def test_sources_de_proche_en_proche(self):
        KPI.objects.create(code="QUAD", libelle="Quadruple", type_saisie_id="Calculé", formule="[DBL] * 2",
                           granularite_id=Niveau.ENTITY, methode_agregation="Somme")
        self.assertEqual(V.sources(["QUAD"]), {"QUAD", "DBL", "EFF"})
        self.assertEqual(V.sources(["EFF"]), {"EFF"})


class RepartitionTests(Base):
    def setUp(self):
        super().setUp()
        for i in range(3, 10):  # 9 entités en tout sous le pays
            o = Organisation.objects.create(nom=f"E{i}", niveau_id=Niveau.ENTITY, parent=self.p)
            S.enregistrer(self.admin, self.c, self.eff, o, str(i), False, "")

    def test_somme_six_parts_puis_autres(self):
        s = V.Source(self.admin, ["EFF"], brouillons=True)
        parts, total = s.repartition("EFF", self.p, self.c.periode)
        self.assertEqual(total, D(110 + 40 + sum(range(3, 10))))
        self.assertEqual([libelle for libelle, *_ in parts], ["E1", "E2", "E9", "E8", "E7", "E6", "Autres (3)"])
        self.assertEqual(parts[-1][1], D(3 + 4 + 5))
        self.assertEqual(sum(p for _, _, p, _ in parts), D(1))

    def test_valeurs_negatives_ou_nulles_ecartees(self):
        S.enregistrer(self.admin, self.c, self.eff, self.e2, "-40", False, "")
        S.enregistrer(self.admin, self.c, self.eff, Organisation.objects.get(nom="E9"), "0", False, "")
        parts, total = V.Source(self.admin, ["EFF"], brouillons=True).repartition("EFF", self.p, self.c.periode)
        self.assertNotIn("E2", [l for l, *_ in parts])
        self.assertNotIn("E9", [l for l, *_ in parts])
        self.assertEqual(total, D(110 + sum(range(3, 9))))

    def test_pourcentage_et_formule_ne_se_repartissent_pas(self):
        s = V.Source(self.admin, ["TX", "DBL"], brouillons=True)
        self.assertEqual(s.repartition("TX", self.p, self.c.periode), ([], None))

    def test_comparaison_triee_sans_valeur_a_la_fin(self):
        Organisation.objects.create(nom="E10", niveau_id=Niveau.ENTITY, parent=self.p)
        s = V.Source(self.admin, ["EFF"], brouillons=True)
        lignes = s.comparaison("EFF", self.p, self.c.periode)
        self.assertEqual([o.nom for o, _, _ in lignes][:3], ["E1", "E2", "E9"])
        self.assertEqual(lignes[-1][0].nom, "E10")
        self.assertIsNone(lignes[-1][1].valeur)
        self.assertEqual(lignes[0][2].valeur, D(100))  # N-1 de E1


class RepartitionReponsesTests(Base):
    def test_oui_non_et_liste_de_plus_de_huit_reponses(self):
        choix = [f"R{i}" for i in range(1, 11)]
        t = TypeReponse.objects.create(code="L10", libelle="Dix choix", format="liste", valeurs=choix)
        k = KPI.objects.create(code="L", libelle="L", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY, type_reponse=t,
                               methode_agregation="Décompte")
        orgs = [self.e1, self.e2] + [Organisation.objects.create(nom=f"X{i}", niveau_id=Niveau.ENTITY, parent=self.p) for i in range(8)]
        for o, c in zip(orgs, choix):
            S.enregistrer(self.admin, self.c, k, o, c, False, "")
        S.enregistrer(self.admin, self.c, k, orgs[-1], "R1", False, "")  # R1 deux fois, R10 aucune
        s = V.Source(self.admin, ["L"], brouillons=True)
        parts, total = s.repartition("L", self.p, self.c.periode)
        self.assertEqual(total, D(10))
        self.assertEqual([l for l, *_ in parts], ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "Autres réponses (2)"])
        self.assertEqual((parts[0][1], parts[-1][1]), (D(2), D(2)))
        self.assertEqual(s.repartition("L", Organisation.objects.get(nom="X0"), self.c.periode)[1], D(1))


class SerieEtPeriodesTests(Base):
    def test_evolution_commence_au_debut_de_l_historique(self):
        Campagne.objects.create(exercice=2022, statut=Campagne.Statut.CLOTUREE)
        Campagne.objects.create(exercice=2023, statut=Campagne.Statut.CLOTUREE)
        s = V.Source(self.admin, ["EFF"], brouillons=True)
        serie = s.serie("EFF", self.e1, self.c.periode)
        self.assertEqual([str(p) for p, _ in serie], ["2025", "2026"])  # 2022 et 2023 vides : retirées en tête
        Reponse.objects.create(periode=Campagne.objects.get(exercice=2022).periode, kpi=self.eff, organisation=self.e1,
                               valeur=D(90), statut="valide", origine="import")
        serie = V.Source(self.admin, ["EFF"], brouillons=True).serie("EFF", self.e1, self.c.periode)
        self.assertEqual([(str(p), pt.valeur) for p, pt in serie], [("2022", D(90)), ("2023", None), ("2025", D(100)), ("2026", D(110))])
        self.assertEqual(s.serie("EFF", self.e1, None), [])

    def test_valide_seulement_en_attente(self):
        s = V.Source(self.admin, ["EFF"])
        self.assertEqual((s.point("EFF", self.e1, self.c.periode).valeur, s.point("EFF", self.e1, self.c.periode).en_attente), (None, True))
        self.assertEqual((s.point("EFF", self.e2, self.c0.periode).valeur, s.point("EFF", self.e2, self.c0.periode).en_attente), (None, False))

    def test_periodes_proposees_et_par_defaut(self):
        liste = V.periodes()
        self.assertEqual([str(p) for p in liste], ["2026", "2025"])
        self.assertEqual(V.periode_par_defaut(liste), self.c0.periode)  # l'année clôturée la plus récente
        self.assertIsNone(V.periode_par_defaut([]))
        self.c0.statut = Campagne.Statut.OUVERTE
        self.c0.save()
        self.assertEqual(V.periode_par_defaut(V.periodes()), self.c.periode)  # aucune finie : la plus récente
