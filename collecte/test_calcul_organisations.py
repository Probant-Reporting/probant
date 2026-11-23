"""Organisations dans le calcul : orphelines (sans ancêtre du bon niveau), fermées pendant la période, avec ou sans valeurs."""
from decimal import Decimal

from django.urls import reverse

from . import saisie as S
from .aides_tests.arbre_france import Arbre, csv_
from .calcul import Calculateur, recalculer
from .models import Reponse
from referentiel.models import Attribution, KPI, Niveau, Organisation, Utilisateur
import datetime

from .aides_tests.arbre_valeurs import Base
from .models import Campagne


D = Decimal


class OrphelinsTests(Arbre):
    """Le constat : France › E1 › Entrepôt 1, et France › Entrepôt direct (site rattaché directement au pays) ;
    FE-ELEC (facteur d'émission, niveau Entité), S2 = [ELEC] * [FE-ELEC] / 1000 au niveau Site. Avant : le facteur de
    l'Entrepôt direct était introuvable et personne ne pouvait le saisir ; S2 de l'entrepôt et du pays restaient bloqués."""

    def setUp(self):
        super().setUp()
        self.s1 = Organisation.objects.create(nom="Entrepôt 1", niveau_id=Niveau.SITE, parent=self.e1)
        self.sd = Organisation.objects.create(nom="Entrepôt direct", niveau_id=Niveau.SITE, parent=self.fr)
        self.fe = self.kpi("FE-ELEC", "FE", agg="Aucune")
        self.eff = self.kpi("EFF")
        self.elec = KPI.objects.create(code="ELEC", libelle="ELEC", type_saisie_id="Saisi", granularite_id=Niveau.SITE,
                                       methode_agregation="Somme")
        self.s2 = KPI.objects.create(code="S2", libelle="S2", type_saisie_id="Calculé", formule="[ELEC] * [FE-ELEC] / 1000",
                                     granularite_id=Niveau.SITE, methode_agregation="Somme")
        from referentiel.composition import composer
        from referentiel.models import Referentiel

        composer({code: ["Énergie"] for code in ("FE-ELEC", "EFF", "ELEC", "S2")}, Referentiel.objects.get(pk=self.c.referentiel_id))
        self.saisir("FE-ELEC", self.e1, "0.05")
        self.saisir("ELEC", self.s1, 1000)
        self.saisir("ELEC", self.sd, 2000)
        self.contrib = Utilisateur.objects.create(username="contrib", email="contrib@exemple.test", first_name="Camille")
        self.valid = Utilisateur.objects.create(username="valid", email="valid@exemple.test", role=Utilisateur.Role.VALIDATEUR)

    def paires(self, u, **kw):
        return sorted((k.code, o.nom) for k, o in S.cellules(u, **kw))

    def test_case_attendue_sans_doublon(self):
        paires = self.paires(self.admin, campagne=self.c)
        self.assertEqual(len(paires), len(set(paires)))
        self.assertEqual([p for p in paires if p[0] == "FE-ELEC"], [("FE-ELEC", "E1"), ("FE-ELEC", "E2"), ("FE-ELEC", "Entrepôt direct")])
        self.assertNotIn(("FE-ELEC", "Entrepôt 1"), paires)  # repris de E1
        self.assertNotIn(("EFF", "Entrepôt direct"), paires)  # un KPI saisi ne se reprend pas : pas de case
        self.assertTrue(self.fe.se_saisit_a(self.sd) and not self.fe.se_saisit_a(self.s1) and not self.eff.se_saisit_a(self.sd))

    def test_calcul_lit_la_case_de_l_organisation(self):
        calc = Calculateur(self.c)
        self.assertIsNone(calc.valeur("S2", self.sd.id))
        self.assertEqual(calc.message("S2", self.sd.id), "Source manquante : FE-ELEC")  # avant : introuvable, sans case
        self.assertEqual(calc.valeur("S2", self.s1.id), D("0.05"))
        S.enregistrer(self.admin, self.c, self.fe, self.sd, "0,06", False, "")  # recalcul des dépendants
        self.assertEqual(self.cellule("S2", self.sd).valeur, D("0.12"))
        self.assertEqual(self.cellule("S2", self.s1).valeur, D("0.05"))
        self.assertEqual(self.cellule("S2", self.fr).valeur, D("0.17"))
        self.assertEqual(self.cellule("S2", self.g).valeur, D("0.17"))
        calc = Calculateur(self.c)
        self.assertEqual((calc.porteur(self.fe, self.s1), calc.porteur(self.fe, self.sd)), (self.e1, self.sd))

    def test_niveau_de_plus_sous_l_organisation_qui_porte(self):
        from parametres.models import NiveauHierarchique

        NiveauHierarchique.objects.create(code="Atelier", rang=5, nom="Atelier", nom_pluriel="Ateliers", couleur="#335577",
                                          couleur_fond="#EEEEEE", couleur_texte="#222222", couleur_pale="#F5F5F5")
        atelier = Organisation.objects.create(nom="Atelier A", niveau_id="Atelier", parent=self.sd)
        self.saisir("FE-ELEC", self.sd, "0.06")
        calc = Calculateur(self.c)
        self.assertEqual(calc.valeur("FE-ELEC", atelier.id), D("0.06"))  # repris de l'entrepôt qui le porte
        self.assertNotIn(("FE-ELEC", "Atelier A"), self.paires(self.admin))

    def test_droits_attribution_et_saisie(self):
        S.attribuer(self.admin, [(self.fe, self.sd)], self.contrib)
        with self.assertRaisesMessage(Exception, "Ce KPI se saisit au niveau"):
            S.attribuer(self.admin, [(self.fe, self.s1)], self.contrib)
        with self.assertRaisesMessage(Exception, "Ce KPI se saisit au niveau"):
            S.attribuer(self.admin, [(self.eff, self.sd)], self.contrib)
        self.assertEqual(self.paires(self.contrib), [("FE-ELEC", "Entrepôt direct")])
        self.assertEqual(S.role_sur(self.contrib, self.fe, self.sd), "contributeur")
        self.assertIsNone(S.role_sur(self.contrib, self.fe, self.s1))
        d = S.droits(self.contrib, self.c, self.fe, self.sd)
        self.assertTrue(d.modifier)
        self.assertTrue(S.droits(self.contrib, self.c, self.fe, self.s1).motif)  # repris de E1 : pas saisissable ici
        S.enregistrer(self.contrib, self.c, self.fe, self.sd, "0,06", False, "")
        S.valider(self.contrib, self.c, self.fe, self.sd)
        self.assertEqual(self.cellule("FE-ELEC", self.sd).statut, Reponse.Statut.VALIDE)
        Attribution.objects.create(kpi=self.fe, organisation=self.fr, utilisateur=self.valid, role=Attribution.Role.VALIDATEUR)
        self.assertIn(("FE-ELEC", "Entrepôt direct"), self.paires(self.valid))
        self.assertEqual(S.role_sur(self.valid, self.fe, self.sd), "validateur")
        lecteur = Utilisateur.objects.create(username="lecteur", email="lecteur@exemple.test", role=Utilisateur.Role.LECTEUR)
        self.assertEqual(S.role_sur(lecteur, self.fe, self.sd), "lecture")
        self.assertFalse(S.droits(lecteur, self.c, self.fe, self.sd).modifier)

    def test_pages_et_comptes(self):
        from . import relances as RL

        S.attribuer(self.admin, [(self.fe, self.sd)], self.contrib)
        self.client.force_login(self.admin)
        rep = self.client.get(reverse("collecte:tableau_de_bord") + f"?campagne={self.c.pk}")
        self.assertEqual(rep.context["total"].total, 7)  # FE-ELEC ×3 (E1, E2, Entrepôt direct), EFF ×2, ELEC ×2
        orgs = {o.nom: (t, v) for o, t, v, _ in S.organisations_visibles(self.admin, self.c)}
        self.assertEqual(orgs["Entrepôt direct"], (2, 1))  # ELEC (validé) et FE-ELEC (à saisir)
        rep = self.client.get(reverse("collecte:saisie") + f"?campagne={self.c.pk}&org={self.sd.id}")
        self.assertEqual(rep.context["org"], self.sd)
        self.assertContains(rep, f'data-cle="FE-ELEC|{self.sd.id}" data-statut="a_saisir"')  # saisissable, attendue
        rep = self.client.get(reverse("collecte:cellule", args=[self.c.pk, "FE-ELEC", self.sd.id]))
        self.assertFalse(rep.context["calculee"])
        self.assertTrue(rep.context["droits"].modifier)
        self.assertEqual([(af.personne, [(l.kpi.code, l.organisation.nom) for l in af.lignes]) for af in RL.a_faire([self.c])],
                         [(self.contrib, [("FE-ELEC", "Entrepôt direct")])])
        self.client.force_login(self.contrib)
        rep = self.client.get(reverse("collecte:pour_moi") + f"?campagne={self.c.pk}")
        self.assertEqual((rep.context["etat"].total, rep.context["etat"].valeurs), (1, 1))
        rep = self.client.get(reverse("collecte:choix_reponse"))
        self.assertEqual(rep.context["blocs"][0]["en_cours"][0][1].total, 1)

    def test_composantes_du_calcul(self):
        self.client.force_login(self.admin)
        rep = self.client.get(reverse("collecte:cellule", args=[self.c.pk, "S2", self.s1.id]))
        fe = next(x for x in rep.context["sources"] if x[0].code == "FE-ELEC")
        self.assertEqual((fe[2].valeur, fe[3]), (D("0.05"), self.e1))  # lu là où il se saisit (avant : « — »)
        self.assertContains(rep, "repris de E1")
        self.saisir("FE-ELEC", self.sd, "0.06")
        rep = self.client.get(reverse("collecte:cellule", args=[self.c.pk, "S2", self.sd.id]))
        fe = next(x for x in rep.context["sources"] if x[0].code == "FE-ELEC")
        self.assertEqual((fe[2].valeur, fe[3]), (D("0.06"), self.sd))
        self.assertContains(rep, reverse("collecte:cellule", args=[self.c.pk, "FE-ELEC", self.sd.id]))

    def test_import_et_rapport_des_rejets(self):
        from . import imports as I

        lignes = [["ID KPI", "Organisation", "Exercice", "Valeur"], ["FE-ELEC", "Entrepôt direct", 2026, "0,06"],
                  ["FE-ELEC", "Entrepôt 1", 2026, "0,07"]]
        a = I.analyser(self.admin, csv_(lignes))
        self.assertEqual([(l.action, l.motif) for l in a.lignes],
                         [("creer", ""), ("rejet", "Ce KPI se saisit au niveau Entité, pas Site.")])
        self.assertEqual([d["organisation"] for d in I.lignes_rejetees(a, self.admin)], ["Entrepôt 1"])
        S.attribuer(self.admin, [(self.fe, self.sd)], self.contrib)
        a, n, _ = I.appliquer(self.contrib, csv_(lignes[:2]))
        self.assertEqual(n, 1)
        self.assertEqual(self.cellule("FE-ELEC", self.sd).valeur, D("0.06"))
        self.assertEqual(self.cellule("S2", self.sd).valeur, D("0.12"))
        modele = I.lignes_modele(self.contrib, self.c)
        self.assertEqual([(l.kpi.code, l.organisation.nom) for l in modele], [("FE-ELEC", "Entrepôt direct")])

    def test_exports(self):
        from . import exports as E

        p = E.Parametres.depuis(E.PRESETS["manquantes"][2])
        manquantes = sorted((l.kpi.code, l.org.nom) for l in E.collecter(self.admin, p))
        self.assertIn(("FE-ELEC", "Entrepôt direct"), manquantes)
        self.assertNotIn(("FE-ELEC", "Entrepôt 1"), manquantes)
        p = E.Parametres.depuis(E.PRESETS["revue"][2])
        avancement = {o.nom: c for o, c in E._avancement(E.collecter(self.admin, p)).items()}
        self.assertEqual(avancement["Entrepôt direct"][:2], [2, 1])

    def test_grille_des_attributions(self):
        self.client.force_login(self.admin)
        rep = self.client.get(reverse("collecte:admin_attributions") + f"?niveau={Niveau.ENTITY}")
        self.assertEqual([o.nom for o in rep.context["orgs"]], ["E1", "E2", "Entrepôt direct"])
        onglet = rep.context["onglet"]
        self.assertEqual((onglet["total"], onglet["sans"], onglet["nb_kpi"]), (5, 5, 2))  # FE-ELEC ×3, EFF ×2
        self.assertContains(rep, "2 KPI × 2 Entités + 1 paramètre hérité × 1 organisation sans Entité au-dessus = 5 cases")
        lignes = {l["kpi"].code: l for _, ls in rep.context["themes"] for l in ls}
        self.assertIsNone(lignes["EFF"]["cellules"][2][1])  # pas de case pour un KPI saisi
        self.assertEqual(lignes["FE-ELEC"]["cellules"][2][1], [])
        self.assertContains(rep, "paramètres hérités")
        self.assertContains(rep, f'data-cle="FE-ELEC|{self.sd.id}"')
        self.assertNotContains(rep, f'data-cle="EFF|{self.sd.id}"')
        rep = self.client.post(reverse("collecte:attribuer"), {"cles": [f"FE-ELEC|{self.sd.id}"], "utilisateur": self.contrib.pk,
                                                               "format": "cellule"}, content_type="application/json")
        self.assertTrue(rep.json()["ok"])

    def test_deplacement_et_arbre_regulier(self):
        from .calcul import recalculer_en_cours

        self.saisir("FE-ELEC", self.sd, "0.06")
        recalculer(self.c)
        self.assertEqual(self.cellule("S2", self.sd).valeur, D("0.12"))
        self.sd.parent = self.e1  # rattaché sous E1 : il reprend le facteur de E1
        self.sd.save()
        recalculer_en_cours()
        self.assertEqual(self.cellule("S2", self.sd).valeur, D("0.1"))
        self.assertNotIn(("FE-ELEC", "Entrepôt direct"), self.paires(self.admin))
        self.assertEqual(self.cellule("FE-ELEC", self.sd).valeur, D("0.06"))  # sa saisie reste en base (sans perte)
        # arbre régulier : mêmes cases qu'avant (KPI × organisations actives de son niveau)
        attendu = sorted((k.code, o.nom) for k in KPI.objects.exclude(type_saisie_id="Calculé")
                         for o in Organisation.objects.filter(actif=True, niveau_id=k.granularite_id))
        self.assertEqual(self.paires(self.admin), attendu)

    def test_coherence_et_desactivation(self):
        from . import coherence as CO
        from .calcul import recalculer_en_cours
        from .models import Alerte

        S.attribuer(self.admin, [(self.fe, self.sd)], self.contrib)
        self.saisir("FE-ELEC", self.sd, "0.03", camp=self.c0)
        self.saisir("FE-ELEC", self.sd, "0.06")
        CO.controler(self.c)
        a = Alerte.objects.get(campagne=self.c, kpi=self.fe, organisation=self.sd)  # facteur modifié par rapport à N-1
        self.assertEqual(a.controle, Alerte.Controle.FE)
        self.assertEqual(CO.alertes_visibles(self.contrib, self.c), [a])
        self.sd.actif = False
        self.sd.save()
        recalculer_en_cours()
        self.assertNotIn(("FE-ELEC", "Entrepôt direct"), self.paires(self.admin))
        self.assertEqual(self.cellule("S2", self.fr).valeur, D("0.05"))  # l'entrepôt désactivé ne compte plus

    def test_cumul_dans_le_temps_de_l_organisation_qui_porte(self):
        from .calcul import cellules_calculees

        rangs = {Niveau.GROUP: 1, Niveau.COUNTRY: 2, Niveau.ENTITY: 3, Niveau.SITE: 4}
        sortie = list(cellules_calculees(self.fe, [self.e1, self.s1, self.sd], rangs, cumul=True, orphelins={self.sd.id}))
        self.assertEqual([(o.nom, origine) for o, origine in sortie], [("E1", Reponse.Origine.CUMUL), ("Entrepôt direct", Reponse.Origine.CUMUL)])
        self.assertEqual(Calculateur(self.c).orphelins(Niveau.ENTITY), {self.sd.id})


# ---------------------------------------------------------------- 5. organisation fermée : N/A ou import comptent
class FermeeAvecValeursTests(Base):
    """« Tout compte » : une organisation fermée pendant la période qui n'a que des N/A, ou que des chiffres importés
    tels quels, a des valeurs (Calculateur.avec_valeurs) : une valeur manquante rend le total incomplet."""

    def setUp(self):
        super().setUp()
        self.c = Campagne.objects.create(exercice=2026, statut=Campagne.Statut.OUVERTE)
        self.kpi("A")
        self.kpi("B")
        self.mettre("A", self.e2, self.c.periode, 7)
        self.e1.actif, self.e1.date_desactivation = False, datetime.date(2026, 6, 30)
        self.e1.save()

    def test_sans_aucune_valeur_ne_compte_pas(self):
        calc = Calculateur(self.c)
        self.assertNotIn(self.e1.id, calc.avec_valeurs(self.c.periode))
        self.assertEqual(calc.valeur("A", self.p.id), D(7))

    def test_que_des_na(self):
        Reponse.objects.create(periode=self.c.periode, kpi_id="B", organisation=self.e1, non_applicable=True)
        calc = Calculateur(self.c)
        self.assertIn(self.e1.id, calc.avec_valeurs(self.c.periode))
        self.assertIsNone(calc.valeur("A", self.p.id))  # A manque pour E1 : total incomplet
        self.assertIn("E1", calc.message("A", self.p.id))

    def test_que_des_chiffres_importes(self):
        self.mettre("B", self.e1, self.c.periode, 3, origine=Reponse.Origine.IMPORT)
        calc = Calculateur(self.c)
        self.assertIn(self.e1.id, calc.avec_valeurs(self.c.periode))
        self.assertIsNone(calc.valeur("A", self.p.id))
