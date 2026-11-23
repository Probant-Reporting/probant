"""Filet de tests du moteur de calcul (collecte/calcul.py) : figent le comportement actuel.

Décompte des réponses oui / non et liste, N/A et valeurs manquantes dans les formules, décalages de période,
granularité (hérité, sous la granularité, rattachement à un niveau quelconque, saisie au-dessus), écriture des cellules
calculées (arrondi à 10 décimales, nombre trop grand, valeurs saisies ou importées jamais écrasées), dépendances et
propagation entre périodes, agrégation dans le temps (somme, moyenne, dernière valeur, N/A, mois manquants)."""
import datetime
from decimal import Decimal

from django.test import TestCase

from parametres.models import TypeReponse
from referentiel.composition import composer
from referentiel.formule import NA
from referentiel.models import KPI, Niveau, Organisation, Referentiel

from . import periodes as P
from .calcul import Calculateur, Decompte, cellules_calculees, figee, kpis_dependants, recalculer
from .models import Campagne, Reponse

D = Decimal


class Arbre(TestCase):
    """Groupe > Pays > E1, E2 > S1 (sous E1), S2 (sous E2) ; exercices 2025 (clôturé) et 2026 (ouvert)."""

    def setUp(self):
        self.g = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        self.p = Organisation.objects.create(nom="Pays", niveau_id=Niveau.COUNTRY, parent=self.g)
        self.e1 = Organisation.objects.create(nom="E1", niveau_id=Niveau.ENTITY, parent=self.p)
        self.e2 = Organisation.objects.create(nom="E2", niveau_id=Niveau.ENTITY, parent=self.p)
        self.s1 = Organisation.objects.create(nom="S1", niveau_id=Niveau.SITE, parent=self.e1)
        self.s2 = Organisation.objects.create(nom="S2", niveau_id=Niveau.SITE, parent=self.e2)
        self.c0 = Campagne.objects.create(exercice=2025, statut=Campagne.Statut.CLOTUREE)
        self.c = Campagne.objects.create(exercice=2026, statut=Campagne.Statut.OUVERTE)
        self.ouinon = TypeReponse.objects.create(code="OuiNon", libelle="Oui / non", format="oui_non")
        self.liste = TypeReponse.objects.create(code="Certif", libelle="Certification", format="liste",
                                                valeurs=["ISO 14001", "ISO 50001", "Aucune"])

    def kpi(self, code, t="Saisi", f="", gran=Niveau.ENTITY, agg="Somme", **autres):
        return KPI.objects.create(code=code, type_saisie_id=t, formule=f, granularite_id=gran, methode_agregation=agg, **autres)

    def saisir(self, kpi, org, v=None, camp=None, na=False, texte="", origine=Reponse.Origine.IMPORT):
        return Reponse.objects.create(periode=(camp or self.c).periode, kpi_id=kpi, organisation=org,
                                      valeur=None if na or v is None else D(v), texte=texte, non_applicable=na, origine=origine)

    def cellule(self, kpi, org, camp=None):
        return Reponse.objects.get(periode=(camp or self.c).periode, kpi_id=kpi, organisation=org)


class DecompteTests(Arbre):
    def test_texte_dans_l_ordre_des_choix_puis_alphabetique_sans_les_zeros(self):
        d = Decompte({"Non": 2, "Oui": 1, "Zèbre": 1, "Autre": 3, "Vide": 0})
        self.assertEqual(d.texte(["Oui", "Non"]), "Oui : 1 · Non : 2 · Autre : 3 · Zèbre : 1")
        self.assertEqual(d.texte(), "Autre : 3 · Non : 2 · Oui : 1 · Zèbre : 1")
        self.assertEqual(Decompte().texte(["Oui", "Non"]), "")

    def test_oui_non_decompte_aux_niveaux_superieurs(self):
        self.kpi("POL", agg="Décompte", type_reponse=self.ouinon)
        self.saisir("POL", self.e1, texte="Oui")
        self.saisir("POL", self.e2, texte="Non")
        calc = Calculateur(self.c)
        self.assertEqual(calc.valeur("POL", self.e1.id), "Oui")
        self.assertEqual(calc.valeur("POL", self.p.id), Decompte({"Oui": 1, "Non": 1}))
        self.assertEqual(calc.valeur("POL", self.g.id), Decompte({"Oui": 1, "Non": 1}))  # décompte de décomptes

    def test_oui_non_na_exclu_tous_na_et_manquant(self):
        self.kpi("POL", agg="Décompte", type_reponse=self.ouinon)
        self.saisir("POL", self.e1, texte="Oui")
        self.saisir("POL", self.e2, na=True)
        self.assertEqual(Calculateur(self.c).valeur("POL", self.p.id), Decompte({"Oui": 1}))
        Reponse.objects.filter(kpi_id="POL", organisation=self.e1).update(texte="", non_applicable=True)
        self.assertIs(Calculateur(self.c).valeur("POL", self.p.id), NA)
        Reponse.objects.filter(kpi_id="POL", organisation=self.e2).delete()
        calc = Calculateur(self.c)
        self.assertIsNone(calc.valeur("POL", self.p.id))
        self.assertEqual(calc.message("POL", self.p.id), "Incomplet : E2")

    def test_decompte_enregistre_en_nombre_et_en_texte(self):
        self.kpi("CERT", agg="Décompte", type_reponse=self.liste)
        self.saisir("CERT", self.e1, texte="ISO 50001")
        self.saisir("CERT", self.e2, texte="ISO 14001")
        recalculer(self.c)
        r = self.cellule("CERT", self.p)
        self.assertEqual((r.valeur, r.texte, r.origine, r.statut, r.non_applicable),
                         (D(2), "ISO 14001 : 1 · ISO 50001 : 1", Reponse.Origine.AGREGATION, Reponse.Statut.CALCULE, False))
        self.assertEqual(self.cellule("CERT", self.g).texte, "ISO 14001 : 1 · ISO 50001 : 1")

    def test_decompte_tous_na_enregistre_na(self):
        self.kpi("POL", agg="Décompte", type_reponse=self.ouinon)
        self.saisir("POL", self.e1, na=True)
        self.saisir("POL", self.e2, na=True)
        recalculer(self.c)
        r = self.cellule("POL", self.p)
        self.assertEqual((r.valeur, r.texte, r.non_applicable, r.statut), (None, "", True, Reponse.Statut.CALCULE))

    def test_agregation_aucune_pas_de_cellule_au_dessus(self):
        self.kpi("POL", agg="Aucune", type_reponse=self.ouinon)
        self.saisir("POL", self.e1, texte="Oui")
        self.saisir("POL", self.e2, texte="Oui")
        self.assertIsNone(Calculateur(self.c).valeur("POL", self.p.id))
        recalculer(self.c)
        self.assertFalse(Reponse.objects.filter(kpi_id="POL", organisation=self.p).exists())


class FormuleTests(Arbre):
    def test_source_na_ratio_na_et_somme_comptee_zero(self):
        self.kpi("A")
        self.kpi("B")
        self.kpi("R", "Calculé", "[A] / [B]", agg="Formule")
        self.kpi("S", "Calculé", "[A] + [B]", agg="Formule")  # une somme : « Une source N/A compte comme 0 » cochée d'office
        self.assertEqual((KPI.objects.get(code="R").na_compte_zero, KPI.objects.get(code="S").na_compte_zero), (False, True))
        self.saisir("A", self.e1, 5)
        self.saisir("B", self.e1, na=True)
        calc = Calculateur(self.c)
        self.assertIs(calc.valeur("R", self.e1.id), NA)  # ratio : N/A, pas une division par zéro
        self.assertEqual(calc.message("R", self.e1.id), "")
        self.assertEqual(calc.valeur("S", self.e1.id), D(5))  # (avant : N/A)
        self.assertEqual(calc.message("S", self.e1.id), "B : N/A, compté comme 0")

    def test_source_na_enregistree_en_na(self):
        self.kpi("A")
        self.kpi("DBL", "Calculé", "[A] * 2")
        self.saisir("A", self.e1, na=True)
        self.saisir("A", self.e2, na=True)
        recalculer(self.c)
        r = self.cellule("DBL", self.e1)
        self.assertEqual((r.valeur, r.non_applicable, r.statut, r.origine), (None, True, Reponse.Statut.CALCULE, Reponse.Origine.CALCUL))
        self.assertTrue(self.cellule("DBL", self.p).non_applicable)  # somme de N/A : N/A

    def test_source_manquante_message_et_statut_incomplet(self):
        self.kpi("A")
        self.kpi("B")
        self.kpi("R", "Calculé", "[A] - [B]", agg="Formule")
        self.saisir("A", self.e1, 5)
        calc = Calculateur(self.c)
        self.assertIsNone(calc.valeur("R", self.e1.id))
        self.assertEqual(calc.message("R", self.e1.id), "Source manquante : B")
        recalculer(self.c)
        r = self.cellule("R", self.e1)
        self.assertEqual((r.valeur, r.statut, r.message_calcul), (None, Reponse.Statut.INCOMPLET, "Source manquante : B"))

    def test_periode_inexistante_et_libelle_de_la_periode_visee(self):
        self.kpi("CA", gran=Niveau.GROUP, agg="Aucune")
        self.kpi("CROISS", "Calculé", "[CA] / [CA@N-1]", gran=Niveau.GROUP, agg="Aucune")
        self.saisir("CA", self.g, 110, camp=self.c0)
        calc = Calculateur(self.c0)  # 2024 : aucune campagne
        self.assertIsNone(calc.valeur("CROISS", self.g.id))
        self.assertEqual(calc.message("CROISS", self.g.id), "Source manquante : CA (2024)")

    def test_references_annee_fixe_periode_precedente_et_moins_unaire(self):
        self.kpi("CA", gran=Niveau.GROUP, agg="Aucune")
        self.kpi("IDX", "Calculé", "[CA] / [CA@2025] * 100", gran=Niveau.GROUP, agg="Aucune")
        self.kpi("PREC", "Calculé", "[CA@P-1]", gran=Niveau.GROUP, agg="Aucune")
        self.kpi("NEG", "Calculé", "-[CA] + 10 * (2 - 1)", gran=Niveau.GROUP, agg="Aucune")
        self.saisir("CA", self.g, 120)
        self.saisir("CA", self.g, 100, camp=self.c0)
        calc = Calculateur(self.c)
        self.assertEqual(calc.valeur("IDX", self.g.id), D(120))
        self.assertEqual(calc.valeur("PREC", self.g.id), D(100))  # année : P-1 = exercice précédent
        self.assertEqual(calc.valeur("NEG", self.g.id), D(-110))

    def test_formule_invalide_ou_vide(self):
        self.kpi("A")
        self.kpi("MAL", "Calculé", "[A] +")
        k = self.kpi("VIDE", "Calculé", "")
        self.saisir("A", self.e1, 1)
        calc = Calculateur(self.c)
        self.assertIsNone(calc.valeur("MAL", self.e1.id))
        self.assertTrue(calc.message("MAL", self.e1.id).startswith("Formule invalide : "))
        self.assertIsNone(calc.valeur("VIDE", self.e1.id))
        self.assertEqual(calc.message("VIDE", self.e1.id), "Pas de formule")
        recalculer(self.c)
        self.assertEqual(self.cellule("MAL", self.e1).statut, Reponse.Statut.ERREUR)
        self.assertEqual(self.cellule("VIDE", self.e1).statut, Reponse.Statut.INCOMPLET)
        self.assertTrue(k.actif)

    def test_division_par_zero_message(self):
        self.kpi("A")
        self.kpi("B")
        self.kpi("R", "Calculé", "[A] / [B]", agg="Formule")
        self.saisir("A", self.e1, 1)
        self.saisir("B", self.e1, 0)
        calc = Calculateur(self.c)
        self.assertIsNone(calc.valeur("R", self.e1.id))
        self.assertEqual(calc.message("R", self.e1.id), "Erreur : Division par zéro")

    def test_arrondi_a_dix_decimales_a_l_enregistrement(self):
        self.kpi("A")
        self.kpi("TIERS", "Calculé", "[A] / 3", agg="Formule")
        self.saisir("A", self.e1, 1)
        self.saisir("A", self.e2, 2)
        calc = Calculateur(self.c)
        self.assertEqual(calc.valeur("TIERS", self.e1.id), D(1) / D(3))  # précision Decimal en mémoire
        recalculer(self.c)
        self.assertEqual(self.cellule("TIERS", self.e1).valeur, D("0.3333333333"))
        self.assertEqual(self.cellule("TIERS", self.p).valeur, D(1))  # formule refaite au niveau supérieur : 3 / 3

    def test_somme_de_kpi_calcule_et_formule_refaite_avec_saisie_au_dessus(self):
        self.kpi("A")
        self.kpi("B", saisie_au_dessus=True)
        self.kpi("AB", "Calculé", "[A] + [B]", agg="Somme")
        self.saisir("A", self.e1, 1)
        self.saisir("A", self.e2, 2)
        self.saisir("A", self.p, 3)  # sans effet : A ne se saisit pas au-dessus
        self.saisir("B", self.p, 10)  # B saisi directement au niveau Pays (le détail manque)
        calc = Calculateur(self.c)
        self.assertEqual(calc.valeur("B", self.p.id), D(10))
        self.assertEqual(calc.valeur("A", self.p.id), D(3))  # somme de E1 et E2
        self.assertEqual(calc.valeur("AB", self.p.id), D(13))  # somme impossible (détail de B manquant) : formule ici
        self.assertEqual(calc.message("AB", self.p.id), "")
        self.assertEqual(calc.valeur("AB", self.g.id), D(13))

    def test_kpi_calcule_au_dessus_sans_agregation(self):
        self.kpi("A")
        self.kpi("C", "Calculé", "[A] * 2", agg="Aucune")
        self.saisir("A", self.e1, 1)
        self.saisir("A", self.e2, 2)
        self.assertIsNone(Calculateur(self.c).valeur("C", self.p.id))
        self.assertEqual(list(o for o, _ in cellules_calculees(KPI.objects.get(code="C"), [self.p, self.e1, self.s1],
                                                                {Niveau.GROUP: 1, Niveau.COUNTRY: 2, Niveau.ENTITY: 3, Niveau.SITE: 4})),
                         [self.e1])


class GranulariteTests(Arbre):
    def test_sous_la_granularite_pas_de_valeur(self):
        self.kpi("A")
        self.saisir("A", self.s1, 5)  # ignoré : A se saisit au niveau des entités
        calc = Calculateur(self.c)
        self.assertIsNone(calc.valeur("A", self.s1.id))
        self.assertEqual(calc.message("A", self.s1.id), "A n'existe pas au niveau Site")

    def test_parametre_herite_repris_au_niveau_du_dessous_et_manquant(self):
        self.kpi("FE", "FE", agg="Aucune")
        self.saisir("FE", self.e1, "0.5")
        calc = Calculateur(self.c)
        self.assertEqual(calc.valeur("FE", self.s1.id), D("0.5"))
        self.assertIsNone(calc.valeur("FE", self.s2.id))
        self.assertEqual(calc.message("FE", self.e2.id), "Valeur non saisie : FE / E2")
        self.assertIsNone(calc.valeur("FE", self.p.id))  # paramètre : pas d'agrégation

    def test_organisation_rattachee_a_un_niveau_quelconque(self):
        self.kpi("A")
        e3 = Organisation.objects.create(nom="E3", niveau_id=Niveau.ENTITY, parent=self.g)  # directement sous le groupe
        site_direct = Organisation.objects.create(nom="S3", niveau_id=Niveau.SITE, parent=self.p)  # site sous le pays
        self.saisir("A", self.e1, 1)
        self.saisir("A", self.e2, 2)
        self.saisir("A", e3, 4)
        self.saisir("A", site_direct, 100)
        calc = Calculateur(self.c)
        self.assertEqual(calc.valeur("A", self.p.id), D(3))  # le site sous la granularité n'est pas attendu
        self.assertEqual(calc.valeur("A", self.g.id), D(7))

    def test_somme_de_negatifs_et_zero(self):
        self.kpi("A")
        self.saisir("A", self.e1, -5)
        self.saisir("A", self.e2, 0)
        self.assertEqual(Calculateur(self.c).valeur("A", self.p.id), D(-5))

    def test_organisation_sans_enfant_au_dessus(self):
        self.kpi("A")
        seul = Organisation.objects.create(nom="Pays vide", niveau_id=Niveau.COUNTRY, parent=self.g)
        self.saisir("A", self.e1, 1)
        self.saisir("A", self.e2, 1)
        calc = Calculateur(self.c)
        self.assertIsNone(calc.valeur("A", seul.id))
        # rien à saisir sous « Pays vide » (aucune entité) : il ne bloque pas le total du groupe
        self.assertEqual(calc.valeur("A", self.g.id), D(2))
        self.assertEqual(calc.message("A", self.g.id), "")

    def test_kpi_ou_organisation_inconnus(self):
        calc = Calculateur(self.c)
        self.assertIsNone(calc.valeur("INCONNU", self.e1.id))
        self.kpi("A")
        self.assertIsNone(calc.valeur("A", 999999))


class EcritureTests(Arbre):
    def test_resultat_trop_grand_en_erreur_nommee(self):
        self.kpi("A")
        self.saisir("A", self.e1, "900000000000000")
        self.saisir("A", self.e2, "900000000000000")
        recalculer(self.c)
        r = self.cellule("A", self.p)
        self.assertEqual((r.valeur, r.statut), (None, Reponse.Statut.ERREUR))
        self.assertIn("trop grand", r.message_calcul)

    def test_saisie_et_import_jamais_ecrases_mais_case_vide_remplie(self):
        self.kpi("A", saisie_au_dessus=True)
        self.saisir("A", self.e1, 1)
        self.saisir("A", self.e2, 2)
        self.saisir("A", self.p, 50)  # importé au niveau du pays
        # commentaire seul au niveau du groupe (le signal de saisie recalcule aussitôt)
        vide = Reponse.objects.create(periode=self.c.periode, kpi_id="A", organisation=self.g, commentaire="note",
                                      origine=Reponse.Origine.SAISIE, statut=Reponse.Statut.A_SAISIR)
        recalculer(self.c)
        self.assertEqual(self.cellule("A", self.p).valeur, D(50))
        vide.refresh_from_db()
        self.assertEqual((vide.valeur, vide.origine, vide.commentaire), (D(50), Reponse.Origine.AGREGATION, "note"))

    def test_kpi_inactif_non_ecrit_et_recalcul_cible(self):
        self.kpi("A")
        self.kpi("DBL", "Calculé", "[A] * 2", actif=False)
        self.kpi("TPL", "Calculé", "[A] * 3")
        self.kpi("B")
        self.kpi("DB", "Calculé", "[B] * 2")
        self.saisir("A", self.e1, 1)
        self.saisir("B", self.e1, 1)
        n = recalculer(self.c, ["A"])
        self.assertFalse(Reponse.objects.filter(kpi_id="DBL").exists())
        self.assertFalse(Reponse.objects.filter(kpi_id="DB").exists())  # hors des dépendants de A
        self.assertEqual(self.cellule("TPL", self.e1).valeur, D(3))
        self.assertEqual(n, 6)  # TPL : E1, E2 (incomplet), Pays, Groupe (incomplets) ; A : Pays, Groupe (incomplets)
        self.assertEqual(recalculer(self.c, ["A"]), 0)  # rien n'a changé : rien n'est réécrit

    def test_kpis_dependants_en_chaine_et_decales(self):
        self.kpi("A")
        self.kpi("B", "Calculé", "[A] * 2")
        self.kpi("C", "Calculé", "[B] + 1")
        self.kpi("D", "Calculé", "[A@N-1]")
        self.kpi("E", "Calculé", "[D] + [A@P-1]")
        self.assertEqual(kpis_dependants(["A"]), {"A", "B", "C"})
        self.assertEqual(kpis_dependants(["A"], "N-1"), {"D", "E"})
        self.assertEqual(kpis_dependants(["A"], "P-1"), {"E"})
        self.assertEqual(kpis_dependants(["C"]), {"C"})

    def test_figee_et_propagation_a_l_annee_suivante(self):
        self.assertTrue(figee(self.c0.periode))
        self.assertFalse(figee(self.c.periode))
        self.assertFalse(figee(P.annuelle(2030)))  # aucune campagne
        self.kpi("A", gran=Niveau.GROUP, agg="Aucune")
        self.kpi("VAR", "Calculé", "[A] - [A@N-1]", gran=Niveau.GROUP, agg="Aucune")
        self.saisir("A", self.g, 10)
        self.saisir("A", self.g, 4, camp=self.c0)
        recalculer(self.c0)  # 2025 recalculé : 2026 (ouvert) suit
        self.assertEqual(self.cellule("VAR", self.g).valeur, D(6))
        Reponse.objects.filter(kpi_id="A", periode=self.c0.periode).update(valeur=D(1))
        self.c.statut = Campagne.Statut.CLOTUREE
        self.c.save()
        recalculer(self.c0)  # 2026 clôturé : figé
        self.assertEqual(self.cellule("VAR", self.g).valeur, D(6))
        recalculer(self.c0, propager=False)
        self.c.statut = Campagne.Statut.OUVERTE
        self.c.save()
        recalculer(self.c0, propager=False)
        self.assertEqual(self.cellule("VAR", self.g).valeur, D(6))  # sans propagation : 2026 n'est pas refait
        recalculer(self.c0)
        self.assertEqual(self.cellule("VAR", self.g).valeur, D(9))


class AgregationTempsTests(TestCase):
    """ELEC se collecte chaque mois dans « Énergie » ; l'année en découle."""

    def setUp(self):
        self.g = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        self.e1 = Organisation.objects.create(nom="E1", niveau_id=Niveau.ENTITY, parent=self.g)
        self.ouinon = TypeReponse.objects.create(code="OuiNon", libelle="Oui / non", format="oui_non")
        self.elec = KPI.objects.create(code="ELEC", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY, methode_agregation="Somme")
        self.taux = KPI.objects.create(code="TX", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY, type_reponse_id="Pourcentage")
        self.pol = KPI.objects.create(code="POL", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY, type_reponse=self.ouinon,
                                      methode_agregation="Décompte")
        self.rse = Referentiel.objects.create(code="RSE", nom="RSE", ordre=1)
        self.nrg = Referentiel.objects.create(code="NRG", nom="Énergie", ordre=2, frequence="mois")
        composer({"ELEC": ["Env"], "TX": ["Env"], "POL": ["Env"]}, self.rse)
        composer({"ELEC": ["Conso"], "TX": ["Conso"], "POL": ["Conso"]}, self.nrg)
        self.annee, _ = P.campagne(self.rse, datetime.date(2026, 1, 1), statut=Campagne.Statut.OUVERTE)
        self.mois = {m: P.campagne(self.nrg, datetime.date(2026, m, 1), statut=Campagne.Statut.CLOTUREE)[0] for m in range(1, 13)}

    def mettre(self, kpi, m, v=None, na=False, texte=""):
        Reponse.objects.create(periode=self.mois[m].periode, kpi=kpi, organisation=self.e1, valeur=None if v is None else D(v),
                               non_applicable=na, texte=texte, origine=Reponse.Origine.IMPORT)

    def test_agregations_par_defaut_selon_le_type(self):
        self.assertEqual(self.elec.agregation_temps, KPI.AgregationTemps.SOMME)
        self.assertEqual(self.taux.agregation_temps, KPI.AgregationTemps.MOYENNE)
        self.assertEqual(self.pol.agregation_temps, KPI.AgregationTemps.DERNIERE)
        fe = KPI.objects.create(code="FE", type_saisie_id="FE", granularite_id=Niveau.ENTITY)
        self.assertEqual(fe.agregation_temps, KPI.AgregationTemps.DERNIERE)
        self.pol.agregation_temps = KPI.AgregationTemps.SOMME
        self.pol.save()
        self.assertEqual(KPI.objects.get(code="POL").agregation_temps, KPI.AgregationTemps.DERNIERE)  # jamais additionné

    def test_somme_avec_mois_na(self):
        for m in range(1, 13):
            self.mettre(self.elec, m, na=(m == 6), v=None if m == 6 else 10)
        self.assertEqual(Calculateur(self.annee).valeur("ELEC", self.e1.id), D(110))

    def test_moyenne_des_mois_hors_na(self):
        for m in range(1, 13):
            self.mettre(self.taux, m, na=m > 6, v=None if m > 6 else D(m) / 10)
        self.assertEqual(Calculateur(self.annee).valeur("TX", self.e1.id), D("0.35"))

    def test_tous_les_mois_na_donne_na(self):
        for m in range(1, 13):
            self.mettre(self.elec, m, na=True)
        self.assertIs(Calculateur(self.annee).valeur("ELEC", self.e1.id), NA)

    def test_mois_manquants_liste_tronquee(self):
        for m in range(1, 7):
            self.mettre(self.elec, m, 1)
        calc = Calculateur(self.annee)
        self.assertIsNone(calc.valeur("ELEC", self.e1.id))
        self.assertEqual(calc.message("ELEC", self.e1.id), "Incomplet : juillet 2026, août 2026, septembre 2026, octobre 2026 …")

    def test_derniere_valeur_oui_non_enregistree_en_texte(self):
        for m in range(1, 13):
            self.mettre(self.pol, m, texte="Oui" if m < 12 else "Non")
        calc = Calculateur(self.annee)
        self.assertEqual(calc.valeur("POL", self.e1.id), "Non")
        recalculer(self.annee)
        r = Reponse.objects.get(periode=self.annee.periode, kpi=self.pol, organisation=self.e1)
        self.assertEqual((r.valeur, r.texte, r.origine, r.statut), (None, "Non", Reponse.Origine.CUMUL, Reponse.Statut.CALCULE))
        g = Reponse.objects.get(periode=self.annee.periode, kpi=self.pol, organisation=self.g)
        self.assertEqual((g.valeur, g.texte), (D(1), "Non : 1"))  # décompte au-dessus de la valeur cumulée

    def test_saisie_directe_de_l_annee_prioritaire_et_referentiel_inactif(self):
        for m in range(1, 13):
            self.mettre(self.elec, m, 10)
        Reponse.objects.create(periode=self.annee.periode, kpi=self.elec, organisation=self.e1, valeur=D(7), origine=Reponse.Origine.IMPORT)
        self.assertEqual(Calculateur(self.annee).valeur("ELEC", self.e1.id), D(7))
        Reponse.objects.filter(periode=self.annee.periode).delete()
        self.assertEqual(Calculateur(self.annee).valeur("ELEC", self.e1.id), D(120))
        self.nrg.actif = False
        self.nrg.save()
        calc = Calculateur(self.annee)
        self.assertIsNone(calc.valeur("ELEC", self.e1.id))  # plus de collecte mensuelle : l'année se saisit
        self.assertEqual(calc.message("ELEC", self.e1.id), "Valeur non saisie : ELEC / E1")

    def test_agregation_aucune_dans_le_temps(self):
        self.elec.agregation_temps = KPI.AgregationTemps.AUCUNE
        self.elec.save()
        for m in range(1, 13):
            self.mettre(self.elec, m, 10)
        self.assertIsNone(Calculateur(self.annee).valeur("ELEC", self.e1.id))

    def test_cumul_propage_apres_recalcul_du_mois(self):
        for m in range(1, 13):
            self.mettre(self.elec, m, 10)
        recalculer(self.mois[3])  # le mois refait l'année (non figée)
        self.assertEqual(Reponse.objects.get(periode=self.annee.periode, kpi=self.elec, organisation=self.e1).valeur, D(120))
        self.assertEqual(Reponse.objects.get(periode=self.annee.periode, kpi=self.elec, organisation=self.g).valeur, D(120))


class SourceDevenueOuiNonTests(TestCase):
    """Une source de formule dont le type de réponse deviendrait oui / non après coup (fiche KPI) : refusé, et la réciproque (une formule qui cite un KPI oui / non) aussi."""

    def setUp(self):
        from parametres.aides_tests.referentiel import Base as BaseFiche

        self.fiche = type("Fiche", (BaseFiche,), {"runTest": lambda self: None})()
        self.fiche.client = self.client
        self.fiche.setUp()
        KPI.objects.create(code="DBL", libelle="Double", type_saisie_id="Calculé", formule="[EFF] * 2",
                           granularite_id=Niveau.ENTITY, methode_agregation="Somme")

    def test_source_d_une_formule_ne_devient_pas_oui_non(self):
        import html

        f = self.fiche
        for type_reponse in ("OuiNon", "Certif"):  # oui / non, liste
            res = f.enregistrer_fiche(f.eff, type_reponse=type_reponse, methode_agregation="Décompte", unite="")
            self.assertFalse(res["ok"])
            self.assertIn("Ce KPI est utilisé dans la formule de DBL", html.unescape(res["html"]))
            self.assertNotIn("Le décompte compte les réponses", html.unescape(res["html"]))  # pas de message en cascade
            self.assertEqual(KPI.objects.get(code="EFF").type_reponse.format, "nombre")
        res = f.enregistrer_fiche(f.eff, type_reponse="Pourcentage", methode_agregation="Aucune", unite="")
        self.assertTrue(res["ok"], res.get("html"))  # un pourcentage reste un nombre : la formule se calcule
        # plus aucune formule ne le cite : le changement est possible
        KPI.objects.filter(code="DBL").delete()
        res = f.enregistrer_fiche(KPI.objects.get(code="EFF"), type_reponse="OuiNon", methode_agregation="Décompte", unite="")
        self.assertTrue(res["ok"], res.get("html"))

    def test_formule_qui_cite_un_kpi_oui_non(self):
        import html

        f = self.fiche
        res = f.enregistrer_fiche(KPI.objects.get(code="DBL"), formule="[POL] * 2")
        self.assertFalse(res["ok"])
        self.assertIn("Réponse oui / non, liste ou texte rédigé, pas un nombre : POL ne peut pas entrer dans une formule.", html.unescape(res["html"]))
        self.assertEqual(KPI.objects.get(code="DBL").formule, "[EFF] * 2")
