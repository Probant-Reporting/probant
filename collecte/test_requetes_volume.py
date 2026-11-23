"""Vitesse : le nombre de requêtes ne grandit pas avec le nombre de lignes (cohérence, saisie, exports, imports)."""
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from parametres.referentiel import unite_depuis_symbole as U
from referentiel.models import KPI, Attribution, ElementReferentiel, Niveau, Referentiel, Theme, Utilisateur
from referentiel.plans import Plan

from . import coherence as CO
from . import imports as I
from . import saisie as S
from .models import Alerte, Campagne, Reponse
from .aides_tests.vitesse import Base, requetes

D = Decimal


class Volume(Base):
    # -- V2 : contrôles de cohérence ------------------------------------------------------------
    def test_controles_sans_requete_par_reponse(self):
        self.ajouter_kpis(2)
        avant = len(requetes(lambda: CO.controles_automatiques(self.campagne())))
        self.ajouter_kpis(6)
        apres = len(requetes(lambda: CO.controles_automatiques(self.campagne())))
        self.assertEqual(avant, apres)

    def test_calculs_impossibles_sans_requete_par_reponse(self):
        def erreurs(n):
            for i in range(n):
                k = KPI.objects.create(code=f"C{len(self.kpis)}", libelle="Calculé", type_saisie_id="Calculé", formule="[K0] / 0",
                                       granularite_id=Niveau.ENTITY, unite=U("employees"))
                self.kpis.append(k)
                Reponse.objects.create(periode=self.c.periode, kpi=k, organisation=self.entites[0], statut=Reponse.Statut.ERREUR,
                                       origine=Reponse.Origine.CALCUL, message_calcul="Division par zéro.")
        self.ajouter_kpis(1)
        erreurs(2)
        avant = len(requetes(lambda: CO.controles_calcul(self.campagne())))
        erreurs(6)
        apres = len(requetes(lambda: CO.controles_calcul(self.campagne())))
        self.assertEqual(avant, apres)

    # -- V10 : pas d'écriture quand rien ne change ----------------------------------------------
    def test_controler_n_ecrit_rien_si_rien_ne_change(self):
        self.ajouter_kpis(3)
        CO.controler(self.c)
        self.assertTrue(Alerte.objects.filter(campagne=self.c).exists())
        sql = requetes(lambda: CO.controler(self.c))
        self.assertEqual([q for q in sql if q.startswith("UPDATE")], [])

    def test_controler_ecrit_encore_ce_qui_change(self):
        self.ajouter_kpis(1)
        CO.controler(self.c)
        a = Alerte.objects.get(campagne=self.c, kpi=self.kpis[0], organisation=self.entites[0], controle="ecart_n1")
        Reponse.objects.filter(periode=self.c.periode, kpi=self.kpis[0], organisation=self.entites[0]).update(valeur=D(400))
        CO.controler(self.c)
        a.refresh_from_db()
        self.assertIn("400", a.valeur)

    def test_page_coherence_tri_sans_requete_par_alerte(self):
        self.ajouter_kpis(2)
        CO.controler(self.c)
        self.client.force_login(self.auditeur)
        url = reverse("collecte:coherence") + f"?campagne={self.c.pk}"
        avant = len(requetes(lambda: self.client.get(url)))
        self.ajouter_kpis(5)
        CO.controler(self.c)
        apres = len(requetes(lambda: self.client.get(url)))
        self.assertEqual(avant, apres)

    # -- V3 : lignes calculées d'une organisation parente --------------------------------------
    def test_saisie_calculees_sans_requete_par_ligne(self):
        def calculees(n):
            for i in range(n):
                k = KPI.objects.create(code=f"T{len(self.kpis)}", libelle="Total", type_saisie_id="Calculé", formule="[K0] * 2",
                                       granularite_id=Niveau.ENTITY, methode_agregation="Somme", unite=U("employees"))
                self.kpis.append(k)
                Reponse.objects.create(periode=self.c.periode, kpi=k, organisation=self.p, valeur=D(1), statut=Reponse.Statut.CALCULE,
                                       origine=Reponse.Origine.AGREGATION)
        self.ajouter_kpis(1)
        calculees(2)
        self.client.force_login(self.admin)
        url = reverse("collecte:saisie") + f"?campagne={self.c.pk}&org={self.p.id}&calc=1"
        avant = len(requetes(lambda: self.client.get(url)))
        calculees(6)
        rep = self.client.get(url)
        self.assertContains(rep, "T8")
        apres = len(requetes(lambda: self.client.get(url)))
        self.assertEqual(avant, apres)

    # -- V6 : lignes d'une organisation, sans lire les réponses de toutes les autres -------------
    def test_lignes_d_une_organisation_ne_lisent_que_ses_reponses(self):
        self.ajouter_kpis(2)
        contrib = Utilisateur.objects.create(username="contrib", email="contrib@exemple.test")
        for k in self.kpis:
            Attribution.objects.create(kpi=k, organisation=self.entites[1], utilisateur=contrib)
        o = self.entites[1]
        sql = requetes(lambda: S.lignes(self.admin, self.campagne(), org=o))
        lues = [q for q in sql if q.startswith('SELECT "collecte_reponse"."id"') or 'FROM "referentiel_attribution"' in q]
        self.assertGreaterEqual(len(lues), 3)  # réponses de la période, N-1, SPOC
        for q in lues:
            self.assertIn('"organisation_id" IN', q, q)
        lignes = S.lignes(self.admin, self.campagne(), org=o)
        self.assertEqual({(l.kpi.code, l.organisation.id) for l in lignes}, {(k.code, o.id) for k in self.kpis})
        self.assertTrue(all(l.reponse and l.reponse.valeur == 300 and l.n1.valeur == 100 for l in lignes))
        self.assertTrue(all(l.spocs == [contrib] for l in lignes))


class PlanVitesse(TestCase):
    """V7 : le référentiel de chaque élément du plan n'est pas relu en base."""

    def setUp(self):
        self.refs = [Referentiel.objects.create(code=f"R{i}", nom=f"Réf {i}", ordre=10 + i) for i in range(2)]
        self.n = 0

    def ajouter(self, n):
        for _ in range(n):
            k = KPI.objects.create(code=f"P{self.n}", libelle="KPI", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY)
            self.n += 1
            for r in self.refs:
                t = Theme.objects.create(referentiel=r, code=f"T{self.n}", nom=f"Thème {self.n}")
                ElementReferentiel.objects.create(referentiel=r, kpi=k, theme=t, ordre=self.n)

    def lire(self):
        plan = Plan()
        return [(plan.decrire(f"P{i}"), plan.titres(f"P{i}")) for i in range(self.n)]

    def test_decrire_et_titres_sans_requete_par_element(self):
        self.ajouter(2)
        avant = len(requetes(self.lire))
        self.ajouter(6)
        apres = len(requetes(self.lire))
        self.assertEqual(avant, apres)
        decrit, (titre, _) = self.lire()[3]
        self.assertTrue(decrit["referentiel"] and titre.startswith(f"{decrit['referentiel']} · "))


class ImportVitesse(Base):
    """V8 : les périodes ne sont pas relues pour chaque ligne du fichier."""

    def analyse(self, n):
        lignes = [["ID KPI", "Organisation", "Période", "Valeur"]]
        lignes += [[k.code, o.nom, "2026", 5] for k in self.kpis for o in self.entites][:n]
        return requetes(lambda: self.__dict__.__setitem__("a", I.analyser(self.admin, None, onglets={"Données": lignes})))

    def test_periodes_lues_une_fois(self):
        self.ajouter_kpis(4)
        avant = len(self.analyse(3))
        apres = len(self.analyse(12))
        self.assertEqual(len([l for l in self.a.lignes if l.campagne == self.c]), 12)
        self.assertEqual(avant, apres)


class ReferentielsVitesse(TestCase):
    """V9 : nombres de KPI, de thèmes et de campagnes sans jointures multipliées."""

    def test_comptages_justes_sans_jointures_multipliees(self):
        from parametres.vues_referentiels import referentiels_annotes

        r = Referentiel.objects.create(code="RX", nom="Réf X", ordre=50)
        Referentiel.objects.create(code="RV", nom="Réf vide", ordre=51)
        themes = [Theme.objects.create(referentiel=r, code=f"T{i}", nom=f"T{i}") for i in range(3)]
        for i in range(4):
            k = KPI.objects.create(code=f"X{i}", libelle="KPI", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY)
            ElementReferentiel.objects.create(referentiel=r, kpi=k, theme=themes[i % 3])
        for ex in (2025, 2026):
            Campagne.objects.create(referentiel=r, exercice=ex)
        sql = requetes(lambda: self.__dict__.__setitem__("refs", referentiels_annotes()))
        par_code = {x.code: x for x in self.refs}
        self.assertEqual((par_code["RX"].nb_kpi, par_code["RX"].nb_themes, par_code["RX"].nb_campagnes), (4, 3, 2))
        self.assertEqual((par_code["RV"].nb_kpi, par_code["RV"].nb_themes, par_code["RV"].nb_campagnes), (0, 0, 0))
        self.assertEqual([x.code for x in self.refs], list(Referentiel.objects.order_by("ordre", "code").values_list("code", flat=True)))
        self.assertTrue(all(q.count("JOIN") <= 1 for q in sql), sql)
        self.client.force_login(Utilisateur.objects.create(username="adm", email="adm@exemple.test", role=Utilisateur.Role.ADMIN))
        self.assertContains(self.client.get(reverse("parametres:referentiel_contenu", args=["RX"])), "<b>4</b> KPI")


class FinImportVitesse(Base):
    """V11 : fin d'import, le périmètre de chaque campagne n'est calculé qu'une fois, quel que soit le nombre de KPI."""

    def appels(self, kpi_ids):
        from unittest import mock

        from . import signals

        with mock.patch.object(S, "codes_perimetre", wraps=S.codes_perimetre) as espion:
            signals.apres_modification(self.c.periode, kpi_ids)
        return espion.call_count

    def test_perimetre_calcule_une_fois_par_campagne(self):
        self.ajouter_kpis(6)
        ids = [k.code for k in self.kpis]
        self.assertEqual(self.appels(ids[:1]), self.appels(ids))
        # même résultat : les alertes des KPI touchés sont à jour dans la campagne en cours
        self.assertEqual(set(Alerte.objects.filter(campagne=self.c).values_list("kpi_id", flat=True)), set(ids))

    def test_campagnes_contenant_les_kpi(self):
        r = Referentiel.objects.create(code="AUTRE", nom="Autre", ordre=60)
        autre = Campagne.objects.create(referentiel=r, exercice=2026, statut=Campagne.Statut.OUVERTE)
        self.ajouter_kpis(2)
        k_autre = KPI.objects.create(code="KA", libelle="Autre", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY)
        ElementReferentiel.objects.create(referentiel=r, kpi=k_autre)
        for ids in (["K0"], ["KA"], ["K0", "KA"], ["K1", "K0"]):
            attendu = {c.pk for k in ids for c in S.campagnes_de(self.c.periode, k, en_cours=True)}
            self.assertEqual({c.pk for c in S.campagnes_des(self.c.periode, ids, en_cours=True)}, attendu, ids)
        self.assertEqual({c.pk for c in S.campagnes_des(self.c.periode, ["KA"], en_cours=True)}, {autre.pk})


class FichierARemplirVitesse(Base):
    """V5 : chaque ligne du fichier à remplir n'est préparée qu'une fois (et non une fois par colonne)."""

    def test_une_preparation_par_ligne(self):
        from unittest import mock

        self.ajouter_kpis(3)
        ls = S.lignes(self.admin, self.campagne())
        for format in ("xlsx", "csv"):
            with mock.patch.object(Plan, "decrire", autospec=True, side_effect=Plan.decrire) as espion:
                rep = I.modele(self.admin, self.campagne(), ls, format=format)
            self.assertEqual(rep.status_code, 200)
            self.assertEqual(espion.call_count, len(ls), format)


class StylesExcelVitesse(TestCase):
    """V4 : chaque style Excel n'est créé qu'une fois (et non pour chaque cellule)."""

    def test_styles_partages(self):
        from openpyxl import styles as O

        from . import exports, fichiers, imports
        from . import styles_excel as SE

        self.assertIs(SE.Font(bold=True, color="FF0000"), SE.Font(bold=True, color="FF0000"))
        self.assertIsNot(SE.Font(bold=True), SE.Font(bold=False))
        self.assertIsInstance(SE.PatternFill("solid", fgColor="FFFFFF"), O.PatternFill)
        cote = SE.Side(style="thin", color="D0D0D0")
        self.assertIs(SE.Border(*(cote,) * 4), SE.Border(*(SE.Side(style="thin", color="D0D0D0"),) * 4))
        for module, noms in ((exports, ("Alignment", "Font", "PatternFill")), (imports, ("Font", "PatternFill")),
                             (fichiers, ("Alignment", "Font", "PatternFill", "Border", "Protection", "Side"))):
            for nom in noms:
                self.assertIs(getattr(module, nom), getattr(SE, nom), f"{module.__name__}.{nom}")


class ExportBaseVitesse(Base):
    """V1 : l'export « Base de données » s'écrit au fil de l'eau (mémoire bornée), sans rien perdre du fichier."""

    def test_base_ecrite_au_fil_de_l_eau(self):
        import io

        from openpyxl import load_workbook

        from . import exports as E
        from . import fichiers as X

        self.ajouter_kpis(2)
        Reponse.objects.filter(kpi=self.kpis[0], organisation=self.entites[0], periode=self.c.periode).update(commentaire="=SOMME(A1:A9)")
        p = E.Parametres.depuis({"presentation": "base", "exercices": ["tous"], "n1": True})
        p.langue = "fr"
        lignes = E.collecter(self.admin, p)
        wb = E.classeur_base(lignes, p, self.admin)
        self.assertTrue(wb.write_only)  # quelques dizaines de Mo au lieu de plus d'un Go pour toutes les années
        flux = io.BytesIO()
        wb.save(flux)
        wb = load_workbook(io.BytesIO(flux.getvalue()))
        self.assertEqual(wb.sheetnames, ["À lire", "Valeurs", "KPI", "Organisations"])
        ws = wb["Valeurs"]
        tete = [c.value for c in ws[1]]
        self.assertEqual(ws.max_row, len(lignes) + 1)
        self.assertEqual(ws.freeze_panes, "E2")
        self.assertEqual(ws.row_dimensions[1].height, 32)
        self.assertEqual(ws.print_title_rows, "$1:$1")
        self.assertEqual(ws.page_setup.orientation, "landscape")
        t = ws.tables["Valeurs"]
        self.assertEqual([c.name for c in t.tableColumns], tete)  # noms des colonnes du tableau = en-têtes (sinon Excel répare)
        self.assertEqual(t.ref, f"A1:{ws.cell(1, len(tete)).column_letter}{len(lignes) + 1}")
        self.assertIn("Nombre exact", ws.cell(1, tete.index("Valeur") + 1).comment.text)
        self.assertEqual(ws.cell(1, tete.index("ID KPI") + 1).fill.fgColor.rgb[-6:], X.GRIS_ENTETE)
        self.assertEqual(ws.cell(1, tete.index("Valeur") + 1).fill.fgColor.rgb[-6:], X.JAUNE_ENTETE)
        rangee = next(r for r in ws.iter_rows(min_row=2) if r[tete.index("Commentaire")].value == "=SOMME(A1:A9)")
        self.assertEqual(rangee[tete.index("Commentaire")].data_type, "s")  # un texte reste du texte, jamais une formule
        # unité « employees » : un comptage, donc 0 décimale 
        self.assertEqual(rangee[tete.index("Valeur")].number_format, "#,##0")
        self.assertEqual(rangee[tete.index("Valeur N-1")].number_format, "#,##0")
        self.assertEqual(rangee[tete.index("Début de période")].number_format, X.FORMAT_DATE)
        self.assertTrue(rangee[tete.index("Début de période")].is_date)
        for nom, table, figer in (("KPI", "Indicateurs", "C2"), ("Organisations", "Organisations", "C2")):
            o = wb[nom]
            self.assertEqual(o.freeze_panes, figer)
            self.assertEqual([c.name for c in o.tables[table].tableColumns], [c.value for c in o[1]])
        lire = wb["À lire"]
        self.assertEqual(lire["A3"].value, "Couleurs des cellules")
        self.assertEqual([lire.cell(i, 1).value for i in (4, 5, 6)], ["À remplir", "Clé : ne pas modifier", "Pour information"])
        self.assertEqual(lire["A8"].value, "Contenu")
        self.assertFalse(lire.sheet_view.showGridLines)
        self.assertEqual(lire.page_setup.orientation, "portrait")
