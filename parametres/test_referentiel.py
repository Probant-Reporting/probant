"""Fiche KPI configurable : unités, types de saisie et de réponse, catégories de description, champs personnalisés
(page Paramètres › Unités et types), réponses oui / non et liste de choix (saisie, validation, décompte, formules, exports,
imports), code du KPI figé et conflits de code, classeur de configuration."""
import io
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from openpyxl import load_workbook

from collecte import configuration as C
from collecte import exports as E
from collecte import imports as I
from collecte import saisie as S
from collecte.calcul import recalculer
from collecte.models import Campagne, Journal, Reponse
from referentiel.models import KPI, Description, Niveau, Organisation, Utilisateur, verifier_formule

from . import referentiel as PR
from .models import CategorieDescription, ChampPersonnalise, TypeReponse, TypeSaisie, Unite
from collecte.outils_tests import xlsx
from .aides_tests.referentiel import Base, FETCH, URL
from collecte.aides_tests.arbre_france import Arbre, csv_
from parametres.aides_tests.referentiel import Base as BaseFiche
from parametres.aides_tests.referentiel import Base as BaseReferentiel

D = Decimal


class PageReferentielTests(Base):
    """Administration › Paramètres › Unités et types : créer, renommer, réordonner, supprimer si inutilisé."""

    def test_reserve_a_l_admin(self):
        self.client.force_login(self.contrib)
        self.assertEqual(self.client.get(URL).status_code, 403)

    def test_toutes_les_sections_s_affichent(self):
        self.client.force_login(self.admin)
        for section, attendu in [("unites", "ETP"), ("types-saisie", "Facteur d&#x27;émission"), ("types-reponse", "Certification"),
                                 ("categories", "À inclure"), ("champs", "Aucun élément")]:
            self.assertContains(self.client.get(f"{URL}?section={section}"), attendu)

    def test_ajouter_une_unite(self):
        rep = self.page("unites", action="ajouter", symbole="GJ", libelle="gigajoule", famille="Énergie", decimales="1")
        self.assertEqual(rep.status_code, 302)
        u = Unite.objects.get(code="GJ")
        self.assertEqual((u.symbole, u.libelle, u.famille, u.decimales, u.entier), ("GJ", "gigajoule", "Énergie", 1, False))
        self.assertEqual(u.ordre, Unite.objects.count())  # en fin de liste
        self.assertTrue(Journal.objects.filter(action="reglage_referentiel", apres__contains="gigajoule").exists())
        # aussitôt proposée dans la fiche KPI
        res = self.enregistrer_fiche(self.eff, unite="GJ")
        self.assertTrue(res["ok"], res["html"])
        self.eff.refresh_from_db()
        self.assertEqual(self.eff.symbole, "GJ")
        # un symbole déjà pris garde un code distinct
        self.page("unites", action="ajouter", symbole="GJ", libelle="autre", decimales="0")
        self.assertEqual(Unite.objects.filter(symbole="GJ").count(), 2)
        self.assertTrue(Unite.objects.filter(code="GJ~2").exists())

    def test_unite_sans_symbole_refusee(self):
        rep = self.page("unites", action="ajouter", symbole="", libelle="rien")
        self.assertContains(rep, "le symbole est obligatoire")

    def test_unites_par_thematique_avec_apercu_et_catalogue(self):
        self.client.force_login(self.admin)
        rep = self.client.get(f"{URL}?section=unites")
        self.assertContains(rep, 'class="bloc theme-unites"')
        self.assertContains(rep, "Effectif")  # thématique d'ETP
        self.assertContains(rep, 'value="Énergie|GWh"')  # suggestion du catalogue
        self.assertContains(rep, "data-apercu-unite")
        etp = Unite.objects.get(pk="ETP")
        from collecte.templatetags.collecte import exemple_unite
        self.assertContains(rep, exemple_unite(etp))

    def test_ajouter_depuis_le_catalogue_sans_doublon(self):
        self.page("unites", action="ajouter_catalogue", catalogue=["Énergie|GWh", "Comptages|sites", "Énergie|inconnue"])
        gwh, sites = Unite.objects.get(symbole="GWh"), Unite.objects.get(symbole="sites")
        self.assertEqual((gwh.famille, gwh.libelle, gwh.entier), ("Énergie", "gigawattheure", False))
        self.assertEqual((sites.famille, sites.entier, sites.decimales), ("Comptages", True, 0))
        self.assertFalse(Unite.objects.filter(symbole="inconnue").exists())
        self.page("unites", action="ajouter_catalogue", catalogue=["Énergie|GWh"])
        self.assertEqual(Unite.objects.filter(symbole="GWh").count(), 1)

    def test_catalogue_dans_la_langue_de_l_interface(self):
        """Thématiques, explications et noms des unités du catalogue traduits ; les valeurs enregistrées (champs du
        formulaire, unité ajoutée) restent celles du catalogue (français)."""
        from . import catalogue_unites as CU
        from . import libelles as LB

        self.assertEqual({k: v for k, v in LB.table("fr").items() if k.startswith(CU.PREFIXE)}, CU.cles_catalogue())
        for langue, mots, absents in (("en", ["terawatt-hour", "Duration", "Headcount", "full-time equivalent",
                                               "Consumption of electricity, gas, and heat"], ["térawattheure", '"nom-theme">Durée', "Consommations"]),
                                      ("es", ["teravatio hora", "Duración", "Plantilla", "Residuos, envases"],
                                       ["térawattheure", '"nom-theme">Durée', "Déchets, emballages"])):
            self.admin.langue = langue
            self.admin.save()
            self.client.logout()  # la langue choisie est gardée dans la session
            self.client.force_login(self.admin)
            rep = self.client.get(f"{URL}?section=unites")
            with self.subTest(langue=langue):
                for m in mots:
                    self.assertContains(rep, m)
                for m in absents:
                    self.assertNotContains(rep, m)
                self.assertContains(rep, 'value="Énergie|TWh"')  # valeur cochée : la thématique enregistrée
        self.page("unites", action="ajouter_catalogue", catalogue=["Énergie|TWh"])
        self.assertEqual(Unite.objects.get(symbole="TWh").libelle, "térawattheure")
        self.assertEqual(CU.nom_theme("Ma thématique", "en"), "Ma thématique")  # thématique propre à l'installation

    def test_unite_entiere_sans_decimales(self):
        self.page("unites", action="ajouter", symbole="sites", entier="on", decimales="2")
        self.assertEqual(Unite.objects.get(symbole="sites").decimales, 0)

    def test_ranger_les_unites_sans_thematique(self):
        for s in ("hours/employee", "kWh", "machins"):
            Unite.objects.update_or_create(code=s, defaults={"symbole": s, "famille": ""})
        Unite.objects.filter(pk="ETP").update(famille="Ma thématique")
        self.page("unites", action="ranger")
        f = dict(Unite.objects.values_list("code", "famille"))
        self.assertEqual((f["hours/employee"], f["kWh"], f["machins"], f["ETP"]), ("Intensités", "Énergie", "", "Ma thématique"))

    def test_ajouter_une_categorie_de_description(self):
        self.page("categories", action="ajouter", libelle="Méthode de calcul", affichee="on")
        cat = CategorieDescription.objects.get(libelle="Méthode de calcul")
        self.assertEqual(cat.code, "MethodeDeCalcul")
        self.client.force_login(self.admin)
        html = self.client.get(reverse("collecte:referentiel_kpi", args=["EFF"]), **FETCH).json()["html"]
        self.assertIn("Méthode de calcul", html)
        res = self.enregistrer_fiche(self.eff, desc_MethodeDeCalcul__fr="Somme des relevés mensuels")
        self.assertTrue(res["ok"], res["html"])
        self.assertEqual(self.eff.texte_description("MethodeDeCalcul"), "Somme des relevés mensuels")
        self.assertTrue(Journal.objects.filter(action="reglage_kpi", champ="Méthode de calcul (FR)").exists())
        # utilisée : ne se supprime plus
        rep = self.page("categories", supprimer=cat.code)
        self.assertContains(rep, "est utilisé (1 texte)")
        self.assertTrue(CategorieDescription.objects.filter(pk=cat.code).exists())

    def test_categorie_obligatoire(self):
        CategorieDescription.objects.filter(code="description").update(obligatoire=True)
        res = self.enregistrer_fiche(self.eff, desc_description__fr="")
        self.assertFalse(res["ok"])
        res = self.enregistrer_fiche(self.eff, desc_description__fr="Effectif au 31/12")
        self.assertTrue(res["ok"], res["html"])

    def test_ajouter_un_type_de_reponse_oui_non(self):
        self.page("types-reponse", action="ajouter", libelle="Conformité", format="oui_non")
        t = TypeReponse.objects.get(libelle="Conformité")
        self.assertEqual((t.code, t.format, t.choix, t.numerique), ("Conformite", "oui_non", ["Oui", "Non"], False))
        nouveau = KPI(code="CONF", libelle="Conforme", type_saisie_id="Saisi", type_reponse=t, granularite_id=Niveau.ENTITY,
                      methode_agregation="Somme")
        res = self.enregistrer_fiche(nouveau, code="CONF")
        self.assertFalse(res["ok"])  # un oui / non ne s'additionne pas
        self.assertIn("ne s&#x27;additionne pas", res["html"])
        res = self.enregistrer_fiche(nouveau, code="CONF", methode_agregation="Décompte")
        self.assertTrue(res["ok"], res["html"])
        self.assertEqual(KPI.objects.get(pk="CONF").format, "oui_non")
        # utilisé : le format est figé, le libellé reste modifiable
        types = list(TypeReponse.objects.all())
        i = [x.pk for x in types].index("Conformite")
        donnees = {"action": "enregistrer", "nb": len(types), **{f"code__{j}": x.pk for j, x in enumerate(types)},
                   f"libelle__{i}": "Conformité réglementaire", f"format__{i}": "nombre"}
        self.page("types-reponse", **donnees)
        t.refresh_from_db()
        self.assertEqual((t.libelle, t.format), ("Conformité réglementaire", "oui_non"))

    def test_liste_sans_valeur_refusee_et_valeur_utilisee_gardee(self):
        rep = self.page("types-reponse", action="ajouter", libelle="Niveau", format="liste", valeurs="")
        self.assertContains(rep, "a besoin de valeurs")
        S.enregistrer(self.contrib, self.c, self.cert, self.e1, "En cours", False, "")
        types = list(TypeReponse.objects.all())
        i = [x.pk for x in types].index("Certif")
        rep = self.page("types-reponse", action="enregistrer", nb=len(types), **{f"code__{j}": x.pk for j, x in enumerate(types)},
                        **{f"libelle__{i}": "Certification", f"valeurs__{i}": "Certifié\nNon engagé"})
        self.assertContains(rep, "encore utilisée dans des réponses : En cours")

    def test_renommer_reordonner_supprimer(self):
        self.page("unites", action="ajouter", symbole="GJ", libelle="gigajoule", famille="Énergie", decimales="1")
        unites = list(Unite.objects.all())
        i = [u.pk for u in unites].index("GJ")
        self.page("unites", action="enregistrer", nb=len(unites), **{f"code__{j}": u.pk for j, u in enumerate(unites)},
                  **{f"symbole__{i}": "GJ", f"libelle__{i}": "gigajoule (GJ)", f"decimales__{i}": "2"})
        u = Unite.objects.get(pk="GJ")
        self.assertEqual((u.libelle, u.decimales), ("gigajoule (GJ)", 2))
        # les unités se déplacent à l'intérieur de leur thématique : GJ passe devant la dernière unité « Énergie »
        energie = [x.pk for x in Unite.objects.filter(famille="Énergie")]
        self.page("unites", monter="GJ")
        apres = [x.pk for x in Unite.objects.filter(famille="Énergie")]
        self.assertEqual(apres, energie[:-2] + ["GJ", energie[-2]])
        # ETP est utilisée par EFF : suppression refusée ; GJ, inutilisée, se supprime
        rep = self.page("unites", supprimer="ETP")
        self.assertContains(rep, "un élément inutilisé.")
        self.page("unites", supprimer="GJ")
        self.assertFalse(Unite.objects.filter(pk="GJ").exists())
        self.assertTrue(Unite.objects.filter(pk="ETP").exists())

    def test_type_de_saisie_ajoute_avec_son_etiquette(self):
        self.page("types-saisie", action="ajouter", libelle="Estimé", abrege="Estim.", couleur="#3366CC", comportement="saisie")
        t = TypeSaisie.objects.get(libelle="Estimé")
        self.assertTrue(t.couleur_fond and t.couleur_texte)  # teintes dérivées de la couleur
        self.assertIn(PR.classe_type(t.code), PR.css())
        k = KPI.objects.create(code="EST", libelle="Estimé", type_saisie=t, granularite_id=Niveau.ENTITY, methode_agregation="Somme")
        self.assertIn("EST", {x.code for x, _ in S.cellules(self.admin)})  # comportement saisie : collecté comme un KPI saisi
        self.assertFalse(k.est_calcule)

    def test_champ_personnalise(self):
        S.enregistrer(self.contrib, self.c, self.eff, self.e1, "12", False, "")
        self.page("champs", action="ajouter", libelle="Périmètre CSRD", type="liste", valeurs="Dans le périmètre\nHors périmètre")
        self.page("champs", action="ajouter", libelle="Audité", type="case")
        res = self.enregistrer_fiche(self.eff, champ_PerimetreCSRD="Dans le périmètre", champ_Audite="on")
        self.assertTrue(res["ok"], res["html"])
        self.eff.refresh_from_db()
        self.assertEqual(self.eff.champs, {"PerimetreCSRD": "Dans le périmètre", "Audite": True})
        res = self.enregistrer_fiche(self.eff, champ_PerimetreCSRD="Inconnu")
        self.assertFalse(res["ok"])  # hors des valeurs possibles
        rep = self.page("champs", supprimer="Audite")
        self.assertContains(rep, "est utilisé (1 KPI)")
        # colonne dans l'export « base de données »
        wb = load_workbook(io.BytesIO(E.exporter(self.admin, E.Parametres.depuis({"presentation": "base"})).content))
        ws = wb["Valeurs"]
        tete = [c.value for c in ws[1]]
        self.assertIn("Périmètre CSRD", tete)
        ligne = next(r for r in ws.iter_rows(min_row=2, values_only=True) if r[tete.index("ID KPI")] == "EFF")
        self.assertEqual((ligne[tete.index("Périmètre CSRD")], ligne[tete.index("Audité")]), ("Dans le périmètre", "Oui"))


class FicheKPITests(Base):
    def test_enregistrer_sans_changement_de_calcul_ne_demande_pas_de_confirmation(self):
        S.enregistrer(self.contrib, self.c, self.eff, self.e1, "10", False, "")
        res = self.enregistrer_fiche(self.eff, nom__fr="Effectif total", desc_description__fr="Au 31/12")
        self.assertTrue(res["ok"], res["html"])
        self.assertEqual(Description.objects.get(kpi=self.eff, categorie="description").texte, "Au 31/12")

    def test_code_fige_apres_creation(self):
        res = self.enregistrer_fiche(self.eff, code="AUTRE", nom__fr="Effectif")
        self.assertTrue(res["ok"], res["html"])
        self.assertTrue(KPI.objects.filter(pk="EFF").exists())
        self.assertFalse(KPI.objects.filter(pk="AUTRE").exists())

    def test_conflit_de_code_a_la_creation(self):
        nouveau = KPI(code="eff", libelle="Doublon", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY, methode_agregation="Somme")
        res = self.enregistrer_fiche(nouveau, code="eff")
        self.assertFalse(res["ok"])
        self.assertIn("existe déjà", res["html"])
        res = self.enregistrer_fiche(nouveau, code="A B")
        self.assertFalse(res["ok"])  # espace interdit
        self.assertFalse(KPI.objects.filter(libelle="Doublon").exists())

    def test_kpi_calcule_doit_etre_numerique(self):
        k = KPI(code="X", type_saisie_id="Calculé", type_reponse=self.oui_non, formule="[EFF] * 2", granularite_id=Niveau.ENTITY,
                methode_agregation="Formule")
        self.assertIn("type_reponse", k.erreurs_regles())
        k = KPI(code="Y", type_saisie_id="Saisi", type_reponse_id="Numérique", granularite_id=Niveau.ENTITY, methode_agregation="Décompte")
        self.assertIn("methode_agregation", k.erreurs_regles())


class ReponsesTexteTests(Base):
    """Oui / non et liste de choix : saisie, validation, décompte, formules, exports, imports."""

    def test_saisie_oui_non(self):
        for brut, attendu in [("oui", "Oui"), ("NON", "Non"), ("Yes", "Oui"), ("0", "Non")]:
            r = S.enregistrer(self.contrib, self.c, self.pol, self.e1, brut, False, "")
            r = S.reponse_de(self.c, self.pol, self.e1)
            self.assertEqual((r.valeur, r.texte), (None, attendu))
        with self.assertRaisesMessage(ValidationError, "Oui"):
            S.enregistrer(self.contrib, self.c, self.pol, self.e1, "peut-être", False, "")
        S.valider(self.contrib, self.c, self.pol, self.e1)
        self.assertEqual(S.reponse_de(self.c, self.pol, self.e1).statut, Reponse.Statut.VALIDE)

    def test_saisie_liste(self):
        S.enregistrer(self.contrib, self.c, self.cert, self.e1, "en cours", False, "")
        self.assertEqual(S.reponse_de(self.c, self.cert, self.e1).texte, "En cours")  # casse du référentiel
        with self.assertRaisesMessage(ValidationError, "Choisissez une des valeurs"):
            S.enregistrer(self.contrib, self.c, self.cert, self.e1, "Bientôt", False, "")

    def test_validation_exige_une_reponse(self):
        S.enregistrer(self.contrib, self.c, self.cert, self.e1, "", False, "")
        with self.assertRaisesMessage(ValidationError, "Saisissez une valeur ou cochez N/A"):
            S.valider(self.contrib, self.c, self.cert, self.e1)

    def test_decompte_aux_niveaux_superieurs(self):
        S.enregistrer(self.admin, self.c, self.pol, self.e1, "Oui", False, "")
        S.enregistrer(self.admin, self.c, self.pol, self.e2, "Non", False, "")
        S.enregistrer(self.admin, self.c, self.cert, self.e1, "Certifié", False, "")
        S.enregistrer(self.admin, self.c, self.cert, self.e2, "Certifié", False, "")
        for k in (self.pol, self.cert):
            for o in (self.e1, self.e2):
                S.valider(self.admin, self.c, k, o)
        recalculer(self.c)
        pays = S.reponse_de(self.c, self.pol, self.p)
        self.assertEqual((pays.valeur, pays.texte, pays.origine), (D(2), "Oui : 1 · Non : 1", Reponse.Origine.AGREGATION))
        self.assertEqual(S.reponse_de(self.c, self.cert, self.g).texte, "Certifié : 2")
        # dans les exports : la réponse en texte
        lignes = E.lignes_tableau_csv(E.collecter(self.admin, E.Parametres.depuis({"presentation": "tableau"})),
                                      E.Parametres.depuis({"presentation": "tableau"}))
        texte = "\n".join(";".join(str(x) for x in l) for l in lignes)
        self.assertIn("Oui : 1 · Non : 1", texte)
        self.assertIn("Certifié", texte)

    def test_exclus_des_formules(self):
        with self.assertRaisesMessage(ValidationError, "ne peut pas entrer dans une formule"):
            verifier_formule("X", "[POL] * 2")
        verifier_formule("X", "[EFF] * 2")  # un nombre : accepté
        calc = KPI(code="TXP", libelle="Taux", type_saisie_id="Calculé", granularite_id=Niveau.ENTITY, methode_agregation="Formule")
        res = self.enregistrer_fiche(calc, code="TXP", formule="[POL] / [EFF]")
        self.assertFalse(res["ok"])
        self.assertIn("POL", res["html"])

    def test_import_de_valeurs(self):
        f = xlsx([["ID KPI", "Organisation", "Exercice", "Valeur"],
                  ["POL", "E1", 2026, "oui"], ["CERT", "E1", 2026, "non engagé"], ["CERT", "E2", 2026, "Bientôt"]])
        a = I.analyser(self.admin, f)
        actions = {(l.kpi_id, l.organisation): (l.action, l.texte, l.motif) for l in a.lignes}
        self.assertEqual(actions[("POL", "E1")][:2], ("creer", "Oui"))
        self.assertEqual(actions[("CERT", "E1")][:2], ("creer", "Non engagé"))
        self.assertEqual(actions[("CERT", "E2")][0], "rejet")
        self.assertIn("Choisissez une des valeurs", actions[("CERT", "E2")][2])
        f.seek(0)
        I.appliquer(self.admin, f, "fichier.xlsx")
        self.assertEqual(S.reponse_de(self.c, self.pol, self.e1).texte, "Oui")
        # relire le même fichier : rien ne change
        f.seek(0)
        a = I.analyser(self.admin, f)
        self.assertEqual({l.action for l in a.lignes if l.kpi_id == "POL"}, {"inchange"})

    def test_modele_d_import_propose_les_choix(self):
        wb = load_workbook(io.BytesIO(I.modele(self.contrib, self.c, I.lignes_modele(self.contrib, self.c)).content))
        listes = [dv.formula1 for dv in wb["Saisie"].data_validations.dataValidation]
        self.assertIn("Définitions", wb.sheetnames)
        self.assertTrue(any("Oui" in l and "Non" in l for l in listes), listes)
        self.assertTrue(any("En cours" in l for l in listes), listes)


class ConfigurationReferentielTests(Base):
    """Classeur de configuration : onglets Unités, Types, Catégories, Champs ; conflits de code."""

    def classeur(self, **ajouts):
        """Classeur exporté, plus des lignes ajoutées ({en-tête: valeur}) dans les onglets donnés."""
        wb = load_workbook(io.BytesIO(C.exporter().content))
        for onglet, lignes in ajouts.items():
            tete = [c.value for c in wb[onglet][1]]
            for l in lignes:
                wb[onglet].append([l.get(t, "") for t in tete])
        flux = io.BytesIO()
        wb.save(flux)
        return SimpleUploadedFile("config.xlsx", flux.getvalue())

    def test_aller_retour_sans_changement(self):
        ChampPersonnalise.objects.create(code="gri", libelle="Référence GRI", type="texte", ordre=1)
        KPI.objects.filter(pk="EFF").update(champs={"gri": "GRI 2-7"})
        a = C.analyser(self.classeur())
        self.assertFalse(a.erreur)
        self.assertEqual({c.action for cs in a.onglets.values() for c in cs}, {"inchange"})
        self.assertEqual(len(a.onglets["Types de réponse"]), 5)  # Numérique, Pourcentage, Texte rédigé (plus de « GHG » sur une base neuve), OuiNon, Certif
        self.assertEqual(len(a.onglets["Champs"]), 1)

    def test_creer_unite_type_categorie_champ_et_kpi(self):
        f = self.classeur(**{
            "Unités": [{"Code": "GJ", "Symbole (FR)": "GJ", "Libellé (FR)": "gigajoule", "Nombre entier": "Non", "Décimales": 1,
                        "Famille": "Énergie", "Ordre": 99}],
            "Types de réponse": [{"Code": "Conf", "Libellé (FR)": "Conformité", "Format": "Oui / non", "Ordre": 12}],
            "Catégories": [{"Code": "methode", "Libellé (FR)": "Méthode", "Ordre": 9, "Affichée au contributeur": "Oui", "Obligatoire": "Non"}],
            "Champs": [{"Code": "gri", "Libellé (FR)": "Référence GRI", "Type": "Texte", "Ordre": 1}],
        })
        wb = load_workbook(f)
        ws = wb["KPI"]
        for t in ("Méthode", "Référence GRI"):  # colonnes des catégories et champs créés par ce même fichier
            ws.cell(row=1, column=ws.max_column + 1, value=t)
        tete = [c.value for c in ws[1]]
        ligne = dict.fromkeys(tete, "")
        ligne.update({"ID KPI": "NRJ", "Thème": "Environnement", "Nom (FR)": "Énergie", "Type de saisie": "Saisi",
                      "Type de réponse": "Numérique", "Unité": "GJ", "Décimales": 1, "Granularité": "Entité", "Agrégation": "Somme",
                      "Actif": "Oui", "Méthode": "Relevés", "Référence GRI": "GRI 302-1"})
        wb["KPI"].append([ligne[t] for t in tete])
        ligne.update({"ID KPI": "CONF", "Nom (FR)": "Conforme", "Type de réponse": "Conformité", "Unité": "", "Agrégation": "Décompte",
                      "Méthode": "", "Référence GRI": ""})
        wb["KPI"].append([ligne[t] for t in tete])
        flux = io.BytesIO()
        wb.save(flux)
        f = SimpleUploadedFile("config.xlsx", flux.getvalue())
        a = C.analyser(f)
        self.assertFalse(a.erreur)
        actions = {nom: {c.cle: c.action for c in cs if c.action != "inchange"} for nom, cs in a.onglets.items()}
        self.assertEqual(actions["Unités"], {"GJ": "creer"})
        self.assertEqual(actions["Types de réponse"], {"Conf": "creer"})
        self.assertEqual(actions["Catégories"], {"methode": "creer"})
        self.assertEqual(actions["Champs"], {"gri": "creer"})
        self.assertEqual(actions["KPI"], {"NRJ": "creer", "CONF": "creer"}, [(c.cle, c.motif) for c in a.onglets["KPI"]])
        f.seek(0)
        C.appliquer(self.admin, f, "config.xlsx")
        nrj = KPI.objects.get(pk="NRJ")
        self.assertEqual((nrj.symbole, nrj.champs, nrj.texte_description("methode")), ("GJ", {"gri": "GRI 302-1"}, "Relevés"))
        self.assertEqual(KPI.objects.get(pk="CONF").format, "oui_non")

    def test_conflit_de_code_signale(self):
        wb = load_workbook(io.BytesIO(C.exporter().content))
        ws = wb["KPI"]
        ws.delete_rows(next(r[0].row for r in ws.iter_rows(min_row=2) if r[0].value == "EFF"))  # EFF n'existe plus qu'en base
        tete = [c.value for c in ws[1]]
        ligne = dict.fromkeys(tete, "")
        ligne.update({"ID KPI": "eff", "Thème": "Social", "Nom (FR)": "Doublon", "Type de saisie": "Saisi", "Type de réponse": "Numérique",
                      "Granularité": "Entité", "Agrégation": "Somme", "Actif": "Oui"})
        wb["KPI"].append([ligne[t] for t in tete])
        flux = io.BytesIO()
        wb.save(flux)
        a = C.analyser(SimpleUploadedFile("config.xlsx", flux.getvalue()))
        rejet = next(c for c in a.onglets["KPI"] if c.cle == "eff")
        self.assertEqual(rejet.action, "rejet")
        self.assertIn("« EFF » existe déjà", rejet.motif)
        # présent deux fois dans le même fichier, à la casse près
        wb["KPI"].append([{"ID KPI": "Eff"}.get(t, ligne[t]) for t in tete])
        flux = io.BytesIO()
        wb.save(flux)
        a = C.analyser(SimpleUploadedFile("config.xlsx", flux.getvalue()))
        self.assertIn("deux fois", next(c for c in a.onglets["KPI"] if c.cle == "Eff").motif)

    def test_formule_sur_un_oui_non_rejetee(self):
        wb = load_workbook(io.BytesIO(C.exporter().content))
        tete = [c.value for c in wb["KPI"][1]]
        ligne = dict.fromkeys(tete, "")
        ligne.update({"ID KPI": "MAUV", "Thème": "Social", "Nom (FR)": "Mauvais", "Type de saisie": "Calculé", "Type de réponse": "Numérique",
                      "Granularité": "Entité", "Agrégation": "Formule", "Formule": "[POL] * 2", "Actif": "Oui"})
        wb["KPI"].append([ligne[t] for t in tete])
        flux = io.BytesIO()
        wb.save(flux)
        a = C.analyser(SimpleUploadedFile("config.xlsx", flux.getvalue()))
        rejet = next(c for c in a.onglets["KPI"] if c.cle == "MAUV")
        self.assertEqual(rejet.action, "rejet")
        self.assertIn("ne peut pas entrer dans une formule", rejet.motif)


class JeuTroisNiveauxTests(TestCase):
    def test_jeu_trois_niveaux_referentiel(self):
        from collecte.aides_tests import jeu_trois_niveaux as J

        J.charger()
        self.assertTrue(KPI.objects.filter(type_reponse__format="oui_non").exists())
        self.assertTrue(KPI.objects.filter(type_reponse__format="liste").exists())
        self.assertTrue(ChampPersonnalise.objects.exists())
        self.assertEqual(Unite.objects.filter(symbole="m³").count(), 1)  # unités d'installation reprises, pas en double
        self.assertTrue(Unite.objects.filter(code="accidents", entier=True).exists())  # unité ajoutée par le jeu d'essai
        holding = Organisation.objects.get(nom="Essai Holding")
        c = Campagne.objects.get(exercice=2025, referentiel_id="REPORTING")
        r = Reponse.objects.get(periode=c.periode, kpi_id="ENV-01", organisation=holding)
        # décompte des choix ; lequel apparaît dépend des identifiants (graine du hasard du jeu d'essai), qui varient sous PostgreSQL
        self.assertRegex(r.texte, r"(Certifié|En cours|Non engagé) : \d")
        # langues : espagnol actif, quelques contenus traduits, comptes d'Iberia en espagnol
        from . import langues as L

        self.assertIn("es", L.codes_actifs())
        self.assertEqual(Utilisateur.objects.get(username="lucia.martin").langue, "es")
        with L.activer("es"):
            self.assertEqual(KPI.objects.get(pk="SOC-06").nom, "Política de discapacidad formalizada")
            # le choix affiché en premier varie sous PostgreSQL (voir plus haut) : on vérifie la traduction de celui-là
            choix = r.texte.split(" : ")[0]
            attendu = {"Certifié": "Certificado", "En cours": "En curso", "Non engagé": "No comprometido"}[choix]
            self.assertEqual(KPI.objects.get(pk="ENV-01").reponse_affichee(choix), attendu)


# ---------------------------------------------------------------- 6. P9 : « Code KPI », type « GHG » à la demande
class CodeKpiEtGhgTests(Arbre):
    """Avant : un en-tête propre à une installation et le type de réponse « GHG » se voyaient dans toute installation."""

    def classeur(self, dossier, entetes, lignes):
        from openpyxl import Workbook

        from referentiel.echange import CHAMPS_KPI, entete

        wb = Workbook()
        ws = wb.active
        ws.title = "KPI"
        ws.append([entetes.get(c, entete(c)) for c in CHAMPS_KPI])
        for d in lignes:
            ws.append([d.get(c, "") for c in CHAMPS_KPI])
        chemin = f"{dossier}/historique.xlsx"
        wb.save(chemin)
        return chemin

    def ligne(self, code, **autres):
        return {"code": code, "type_saisie": "Saisi", "nom_fr": code, "type_reponse": "Numérique", "granularite": Niveau.ENTITY,
                "methode_agregation": "Somme", "confidentialite": "Non sensible", "actif": "Oui", **autres}

    def test_installation_neuve_sans_ghg(self):
        from parametres import referentiel as PR
        from parametres.models import TypeReponse

        self.assertFalse(TypeReponse.objects.filter(code="GHG").exists())  # base neuve (migrations) : plus de « GHG »
        TypeReponse.objects.all().delete()
        PR.creer_par_defaut()
        self.assertEqual(list(TypeReponse.objects.values_list("code", flat=True)), ["Numérique", "Pourcentage", "TexteRedige"])

    def test_ghg_cree_a_la_demande_et_garde(self):
        import tempfile

        from parametres.models import TypeReponse
        from referentiel.echange import importer_kpi

        with tempfile.TemporaryDirectory() as d:
            r = importer_kpi(self.classeur(d, {}, [self.ligne("CO2", type_reponse="GHG"), self.ligne("NB")]))
            self.assertEqual(r.erreurs, [])
            ghg = TypeReponse.objects.get(code="GHG")
            self.assertEqual((ghg.libelle, ghg.format), ("GHG", "nombre"))
            self.assertEqual(KPI.objects.get(code="CO2").type_reponse_id, "GHG")
            r = importer_kpi(self.classeur(d, {}, [self.ligne("NB")]))  # un fichier qui ne s'en sert pas : rien n'est retiré
            self.assertEqual(r.erreurs, [])
            self.assertTrue(TypeReponse.objects.filter(code="GHG").exists())
            self.assertEqual(TypeReponse.objects.filter(code="GHG").count(), 1)

    def test_en_tete_code_kpi_et_anciens_en_tetes(self):
        import tempfile

        from openpyxl import load_workbook

        from referentiel.echange import exporter_kpi, importer_kpi

        with tempfile.TemporaryDirectory() as d:
            for i, ancien in enumerate(("Code", "ID KPI", "Code KPI")):  # en-têtes génériques des anciens fichiers : toujours lus
                r = importer_kpi(self.classeur(d, {"code": ancien}, [self.ligne(f"K{i}")]))
                self.assertEqual((r.erreurs, r.crees), ([], 1), ancien)
            exporter_kpi(f"{d}/export.xlsx")
            tete = [c.value for c in load_workbook(f"{d}/export.xlsx")["KPI"][1]]
            self.assertEqual(tete[0], "Code KPI")
            self.assertEqual(tete.count("Code KPI"), 1)
            with self.assertRaisesMessage(ValueError, "Code KPI"):  # colonne du code absente : nommée comme dans le fichier
                importer_kpi(self.classeur(d, {"code": "Autre"}, [self.ligne("K9")]))

    def test_imports_de_valeurs_et_classeur(self):
        from collecte import imports as I

        self.kpi("EFF")
        a = I.analyser(self.admin, csv_([["Code KPI", "Organisation", "Exercice", "Valeur"], ["EFF", "E1", 2026, 7]]))
        self.assertEqual([(l.kpi_id, l.action) for l in a.lignes], [("EFF", "creer")])
        a = I.analyser(self.admin, csv_([["ID", "Organisation", "Exercice", "Valeur"], ["EFF", "E2", 2026, 8]]))
        self.assertEqual([(l.kpi_id, l.action) for l in a.lignes], [("EFF", "creer")])  # ancien en-tête toujours lu


class FormatDuKpiFigeTests(BaseFiche):
    """P4 : le format (nombre, pourcentage, oui / non, liste) d'un KPI qui a des réponses ne change plus depuis la fiche :
    300 kWh deviendraient 30 000 %, toujours « Validé »."""

    def setUp(self):
        super().setUp()
        S.enregistrer(self.admin, self.c, self.eff, self.e1, "300", False, "")
        S.valider(self.admin, self.c, self.eff, self.e1)

    def test_nombre_vers_pourcentage_refuse(self):
        res = self.enregistrer_fiche(self.eff, type_reponse="Pourcentage", unite="", methode_agregation="Aucune", confirmer="on")
        self.assertFalse(res.get("ok"))
        self.assertIn("format", str(res))
        self.eff.refresh_from_db()
        self.assertEqual(self.eff.type_reponse_id, "Numérique")
        r = Reponse.objects.get(periode=self.c.periode, kpi=self.eff, organisation=self.e1)
        self.assertEqual((r.valeur, r.statut), (D(300), Reponse.Statut.VALIDE))

    def test_oui_non_vers_liste_refuse(self):
        S.enregistrer(self.admin, self.c, self.pol, self.e1, "Oui", False, "")
        res = self.enregistrer_fiche(self.pol, type_reponse="Certif", confirmer="on")
        self.assertFalse(res.get("ok"))
        self.pol.refresh_from_db()
        self.assertEqual(self.pol.type_reponse_id, "OuiNon")

    def test_meme_format_accepte(self):
        from parametres.models import TypeReponse

        TypeReponse.objects.create(code="Nombre2", libelle="Autre nombre", format="nombre", ordre=12)
        res = self.enregistrer_fiche(self.eff, type_reponse="Nombre2", confirmer="on")
        self.assertTrue(res.get("ok"), res)

    def test_sans_reponse_le_format_change(self):
        Reponse.objects.filter(kpi=self.eff).delete()
        res = self.enregistrer_fiche(self.eff, type_reponse="Pourcentage", unite="", methode_agregation="Aucune")
        self.assertTrue(res.get("ok"), res)


SECTIONS = ("unites", "types-saisie", "types-reponse", "categories", "champs")


class UnitesEtFormatsTests(BaseReferentiel):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)

    def test_navigation_avec_un_resume_par_liste(self):
        rep = self.client.get(URL)
        for resume in ("kWh, €, salariés… et leurs décimales", "Saisi, calculé ou hérité", "Nombre, pourcentage, oui / non, liste, texte, tableau",
                       "Rubriques de la définition d&#x27;un KPI", "Informations ajoutées à la fiche KPI"):
            self.assertContains(rep, f'<span class="resume">{resume}</span>')
        self.assertContains(rep, 'href="?section=unites" class="actif" aria-current="page"')
        html = rep.content.decode()
        nav = html[html.index('<nav class="sections-reglables"'):]
        self.assertEqual(nav[:nav.index("</nav>")].count('aria-current="page"'), 1)  # une seule liste courante

    def test_meme_construction_pour_chaque_liste(self):
        for section in SECTIONS:
            with self.subTest(section=section):
                html = self.client.get(f"{URL}?section={section}").content.decode()
                principal = html[html.index('<div class="colonne-identite">'):html.index('<aside class="colonne-apercu">')]
                self.assertEqual(principal.count('<section class="bloc">'), 1)  # un seul cadre : liste puis ajout
                self.assertEqual(principal.count('<details class="comportements">'), 1)  # une seule aide, repliée
                self.assertNotIn('class="comportements" open', principal)
                self.assertIn('<div class="ajout-bloc">', principal)
                self.assertLess(principal.index('name="action" value="enregistrer"') if 'value="enregistrer"' in principal else 0,
                                principal.index('<div class="ajout-bloc">'))
                self.assertIn('name="action" value="ajouter"', principal)
                self.assertIn(reverse("parametres:langues"), principal)  # traductions : dans l'aide repliée

    def test_apercu_d_une_unite_sans_consigne(self):
        rep = self.client.get(f"{URL}?section=unites")
        self.assertContains(rep, "Valeur saisie")
        self.assertContains(rep, "Valeur affichée")
        for ancien in ("Cliquez sur une unité de la liste", "1. Le contributeur saisit", "Essayez une autre valeur"):
            self.assertNotContains(rep, ancien)
        self.assertNotContains(rep, "sommaire-unites")  # plus de pastilles : une ligne par thématique

    def test_catalogue_des_autres_thematiques_replie_sous_ajouter(self):
        rep = self.client.get(f"{URL}?section=unites")
        autres = rep.context["catalogue_autres"]
        self.assertTrue(autres)  # base d'essai : presque aucune unité, donc des thématiques entières à proposer
        self.assertTrue(all(not t["unites"] and t["suggestions"] for t in autres))
        self.assertContains(rep, '<details class="comportements catalogue-autres" id="catalogue-unites">')
        # une unité du catalogue s'ajoute toujours
        t, s = autres[0], autres[0]["suggestions"][0]
        self.page("unites", action="ajouter_catalogue", catalogue=f"{t['nom']}|{s['symbole']}")
        from parametres.models import Unite
        self.assertTrue(Unite.objects.filter(symbole=s["symbole"], famille=t["nom"]).exists())


class ColonnesTableauTests(Base):
    """Page Unités et formats : un type « tableau » et ses colonnes (une par ligne : code ; nom ; type ; liste ou unité)."""

    def test_ajouter_modifier_proteger(self):
        TypeReponse.objects.create(code="POLL", libelle="Polluants", format="liste", valeurs=["Ammoniac", "Benzène"])
        rep = self.page("types-reponse", action="ajouter", libelle="Rejets", format="tableau",
                        colonnes="polluant ; Polluant ; liste ; INCONNUE\nair ; Rejets dans l'air ; nombre ; kg")
        self.assertContains(rep, "la liste « INCONNUE » n&#x27;existe pas")
        self.page("types-reponse", action="ajouter", libelle="Rejets", format="tableau",
                  colonnes="polluant ; Polluant ; liste ; POLL\nair ; Rejets dans l'air ; nombre ; kg")
        t = TypeReponse.objects.get(libelle="Rejets")
        self.assertEqual(t.colonnes, [{"code": "polluant", "libelle": {"fr": "Polluant"}, "type": "liste", "liste": "POLL"},
                                      {"code": "air", "libelle": {"fr": "Rejets dans l'air"}, "type": "nombre", "unite": "kg"}])
        self.assertEqual(t.colonnes_texte, "polluant ; Polluant ; liste ; POLL\nair ; Rejets dans l'air ; nombre ; kg")
        self.assertEqual(PR.usages()["types-reponse"]["POLL"], 1)  # liste d'une colonne : comptée, donc ni supprimable ni modifiable
        page = self.client.get(f"{URL}?section=types-reponse")
        self.assertContains(page, "Colonnes (tableau)")
        self.assertContains(page, "air ; Rejets dans l&#x27;air ; nombre ; kg")
        # traduction anglaise d'une colonne gardée quand on renomme en français
        t.colonnes[1]["libelle"]["en"] = "Emissions to air"
        t.save()
        types = list(TypeReponse.objects.all())
        i = [x.pk for x in types].index(t.pk)
        base = {"action": "enregistrer", "nb": len(types), **{f"code__{j}": x.pk for j, x in enumerate(types)}, f"libelle__{i}": "Rejets",
                f"format__{i}": "tableau"}
        self.page("types-reponse", **base, **{f"colonnes__{i}": "polluant ; Polluant ; liste ; POLL\nair ; Rejets atmosphériques ; nombre ; kg"})
        t.refresh_from_db()
        self.assertEqual(t.colonnes[1]["libelle"], {"fr": "Rejets atmosphériques", "en": "Emissions to air"})
        # des réponses existent : ni l'ordre ni les codes ne changent plus (le nom, si)
        k = KPI.objects.create(code="REJ", libelle="Rejets", type_saisie_id="Saisi", type_reponse=t, granularite_id=Niveau.ENTITY,
                               methode_agregation="Aucune")
        Reponse.objects.create(periode=self.c.periode, kpi=k, organisation=self.e1, texte="| Ammoniac | 1 |")
        rep = self.page("types-reponse", **base, **{f"colonnes__{i}": "air ; Rejets ; nombre ; kg\npolluant ; Polluant ; liste ; POLL"})
        self.assertContains(rep, "pas leurs codes, leur ordre ni leurs types")
        t.refresh_from_db()
        self.assertEqual(t.colonnes[0]["code"], "polluant")
