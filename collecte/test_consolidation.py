"""Tableau de bord › Consolidation : valeurs de chaque niveau de l'arbre, du plus bas au plus haut (demande)."""
from decimal import Decimal
from io import BytesIO

from django.urls import reverse
from openpyxl import load_workbook

from referentiel.composition import composer
from referentiel.models import Organisation, Utilisateur

from . import saisie as S
from .models import Reponse, SelectionKPI
from .aides_tests.saisie import Base

D = Decimal


class ConsolidationTests(Base):
    def setUp(self):
        super().setUp()
        composer({"EFF": ["Social"], "TX": ["Social"], "DBL": ["Social"]})
        self.url = reverse("collecte:consolidation")

    def valider(self, org, v, user=None):
        S.enregistrer(user or self.admin, self.c, self.eff, org, v, False, "")
        S.valider(user or self.admin, self.c, self.eff, org)

    def page(self, user=None, **params):
        self.client.force_login(user or self.admin)
        return self.client.get(self.url, params)

    def cases(self, rep, nom):
        """Cases de la ligne d'une organisation : {code du KPI : Case}."""
        ligne = next(l for l in rep.context["lignes"] if l.org.nom == nom)
        return {c.kpi.code: c for c in ligne.cases}

    def test_totaux_de_chaque_niveau(self):
        self.valider(self.e1, "10")
        self.valider(self.e2, "20")
        rep = self.page()
        self.assertEqual(rep.status_code, 200)
        self.assertEqual([l.org.nom for l in rep.context["lignes"]], ["Groupe", "Pays", "E1", "E2"])
        self.assertEqual([l.prof for l in rep.context["lignes"]], [0, 1, 2, 2])
        self.assertEqual(rep.context["theme"].nom, "Social")
        # les KPI sans valeur sont montrés par défaut ; « Masquer les KPI vides » les met de côté
        self.assertEqual([k.code for k in rep.context["kpis"]], ["EFF", "TX", "DBL"])
        self.assertContains(rep, "Masquer les KPI vides")
        cache = self.page(theme="", masquer_vides="1")
        self.assertEqual([k.code for k in cache.context["kpis"]], ["EFF", "DBL"])
        self.assertEqual([k.code for k in cache.context["vides"]], ["TX"])
        rep = self.page(theme="", vides="1")
        self.assertEqual([k.code for k in rep.context["kpis"]], ["EFF", "TX", "DBL"])
        self.assertEqual(self.cases(rep, "Pays")["EFF"].point.valeur, D(30))
        self.assertEqual(self.cases(rep, "Groupe")["EFF"].point.valeur, D(30))
        self.assertEqual(self.cases(rep, "Groupe")["DBL"].point.valeur, D(60))  # calculé, puis agrégé
        self.assertTrue(self.cases(rep, "Pays")["TX"].absente)  # taux sans agrégation : rien au-dessus de l'entité
        self.assertContains(rep, ">30,00<")
        self.assertContains(rep, 'data-parent="%d"' % self.p.id)
        self.assertContains(rep, 'aria-expanded="true" data-deplier="%d"' % self.g.id)
        self.assertContains(rep, reverse("collecte:cellule", args=[self.c.pk, "EFF", self.p.id]))  # détail au clic
        # le tableau de bord mène à la consolidation, et inversement
        self.assertContains(rep, f'href="{reverse("collecte:tableau_de_bord")}"')
        self.assertContains(self.client.get(reverse("collecte:tableau_de_bord")), f'href="{self.url}"')

    def test_total_partiel_valeur_non_saisie_et_brouillons(self):
        """Un total incomplet en Somme montre ce qui est connu, marqué « partiel », avec le nombre d'organisations qui
        manquent ; la valeur pas encore saisie est « — » ; aucune alerte orange (réservée aux erreurs de calcul)."""
        self.valider(self.e1, "10")
        rep = self.page(brouillons="0")
        self.assertTrue(self.cases(rep, "E2")["EFF"].non_saisie)
        pays = self.cases(rep, "Pays")["EFF"]
        self.assertIsNone(pays.point.valeur)  # le moteur, lui, n'a pas de total
        self.assertIn("E2", pays.incomplet)
        self.assertEqual((pays.partiel, pays.manquants), (D(10), 1))
        self.assertEqual((self.cases(rep, "Groupe")["EFF"].partiel, self.cases(rep, "Groupe")["EFF"].manquants), (D(10), 1))
        self.assertContains(rep, "partiel · 1 manque")
        self.assertNotContains(rep, 'class="erreur-conso"')
        # un brouillon : « en attente » (validées seulement), compté avec « Inclure les brouillons » (◐)
        S.enregistrer(self.admin, self.c, self.eff, self.e2, "5", False, "")
        rep = self.page(brouillons="0")
        self.assertTrue(self.cases(rep, "E2")["EFF"].point.en_attente)
        self.assertEqual(self.cases(rep, "Pays")["EFF"].partiel, D(10))
        rep = self.page(brouillons="1")
        pays = self.cases(rep, "Pays")["EFF"]
        self.assertEqual((pays.point.valeur, pays.point.provisoire, pays.partiel), (D(15), True, None))
        self.assertContains(rep, 'class="marque-provisoire"')
        # le choix est gardé pour la visite suivante
        self.assertTrue(self.client.get(self.url).context["reglages"]["brouillons"])

    def test_brouillons_par_defaut_pendant_la_saisie(self):
        """Sans choix mémorisé : les brouillons comptent pendant la saisie (campagne ouverte), pas une fois clôturée."""
        self.client.force_login(self.admin)
        self.assertTrue(self.client.get(self.url).context["reglages"]["brouillons"])
        self.c.statut = self.c.Statut.CLOTUREE
        self.c.save()
        self.client.force_login(self.valid)
        self.assertFalse(self.client.get(self.url, {"campagne": self.c.pk}).context["reglages"]["brouillons"])

    def test_erreur_de_calcul_seule_alerte(self):
        from referentiel.models import KPI

        KPI.objects.filter(code="DBL").update(formule="[EFF] / 0")
        self.valider(self.e1, "10")
        rep = self.page(brouillons="0")
        self.assertTrue(self.cases(rep, "E1")["DBL"].erreur)
        self.assertContains(rep, 'class="erreur-conso"')

    def test_comparaison_n1(self):
        for org, v in ((self.e1, 8), (self.e2, 12)):
            Reponse.objects.create(periode=self.c0.periode, kpi=self.eff, organisation=org, valeur=D(v),
                                   statut=Reponse.Statut.VALIDE, origine=Reponse.Origine.IMPORT)
        self.valider(self.e1, "10")
        self.valider(self.e2, "20")
        rep = self.page(n1="1")
        pays = self.cases(rep, "Pays")["EFF"]
        self.assertEqual(pays.n1.valeur, D(20))
        self.assertEqual(pays.ecart, D("0.5"))
        self.assertContains(rep, "N-1 : 20,00")

    def test_perimetre_du_contributeur(self):
        """Le contributeur ne voit que ses cases (E1) et l'arbre au-dessus ; jamais les valeurs de E2."""
        self.valider(self.e1, "10")
        self.valider(self.e2, "20")
        rep = self.page(self.contrib)
        noms = [l.org.nom for l in rep.context["lignes"]]
        self.assertIn("E1", noms)
        self.assertNotIn("E2", noms)
        self.assertNotIn("DBL", [k.code for k in rep.context["kpis"]])  # pas un KPI de ses cases
        self.assertNotContains(rep, ">20,00<")

    def test_lecteur_et_auditeur_en_lecture_seule(self):
        lecteur = Utilisateur.objects.create(username="lect", email="lect@exemple.test", role=Utilisateur.Role.LECTEUR)
        auditeur = Utilisateur.objects.create(username="aud", email="aud@exemple.test", role=Utilisateur.Role.AUDITEUR)
        self.valider(self.e1, "10")
        rep = self.page(lecteur)
        self.assertEqual(rep.status_code, 200)
        self.assertContains(rep, ">10,00<")
        self.assertNotContains(rep, "data-panneau>")  # pas de détail de saisie pour le lecteur
        self.assertEqual(self.client.get(reverse("collecte:consolidation_excel")).status_code, 200)
        rep = self.page(auditeur)
        self.assertContains(rep, reverse("collecte:cellule", args=[self.c.pk, "EFF", self.e1.id]))

    def test_liste_de_kpi_et_export_excel(self):
        Organisation.objects.filter(pk=self.e2.pk).update(nom="=HYPERLINK(1)")  # jamais une formule dans le fichier
        self.valider(self.e1, "10")
        liste = SelectionKPI.objects.create(nom="Effectifs", proprietaire=self.admin)
        liste.kpis.set([self.eff])
        rep = self.page(liste=str(liste.pk), theme="")
        self.assertEqual([k.code for k in rep.context["kpis"]], ["EFF"])
        rep = self.client.get(reverse("collecte:consolidation_excel"), {"liste": liste.pk, "n1": "1", "brouillons": "0"})
        self.assertEqual(rep["Content-Type"], "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        ws = load_workbook(BytesIO(rep.content)).active
        lignes = {r[0]: r for r in ws.iter_rows(min_row=4, values_only=True)}
        self.assertEqual(lignes["E1"][2], 10)
        self.assertEqual(lignes["Pays"][2], 10)  # total partiel : le nombre connu, en italique avec une note
        partiel = next(c for c in ws["C"] if c.row > 3 and ws.cell(c.row, 1).value == "Pays")
        self.assertTrue(partiel.font.italic)
        self.assertIn("1 organisation", partiel.comment.text)
        self.assertIn("=HYPERLINK(1)", lignes)
        self.assertEqual(ws.cell(3, 4).value, "EFF – N-1")
        self.assertTrue(ws.cell(next(c.row for c in ws["A"] if c.value == "Pays"), 3).font.italic)
        cellule = next(c for c in ws["A"] if c.value == "=HYPERLINK(1)")
        self.assertEqual(cellule.data_type, "s")
        # liste d'une autre personne, non partagée : ignorée (le thème par défaut reprend la main)
        autre = SelectionKPI.objects.create(nom="Privée", proprietaire=self.contrib)
        self.assertIsNone(self.page(liste=str(autre.pk), theme="").context["liste"])

    def test_kpi_choisis_un_par_un(self):
        """« Choisir les KPI » (même sélecteur qu'Import / Export) : les KPI cochés, dans l'ordre du référentiel ; le choix
        est gardé ; un choix vide revient au thème."""
        self.valider(self.e1, "10")
        rep = self.page(choix_kpi="choix", kpis=["DBL", "EFF"])
        self.assertEqual(rep.context["mode"], "choix")
        self.assertEqual([k.code for k in rep.context["kpis"]], ["EFF", "DBL"])
        self.assertContains(rep, 'name="kpis" value="EFF" checked')
        self.assertContains(rep, "2 KPI choisis")
        self.assertEqual(self.client.get(self.url).context["mode"], "choix")  # gardé pour la visite suivante
        rep = self.page(choix_kpi="choix")
        self.assertEqual((rep.context["mode"], rep.context["theme"].nom), ("theme", "Social"))
        # le sélecteur propose « Un thème du référentiel » à la place de « Tous les KPI »
        self.assertContains(rep, 'value="theme"')
        self.assertNotContains(rep, 'name="choix_kpi" value="tous"')

    def test_lignes_et_colonnes_interverties(self):
        """KPI en lignes, organisations en colonnes jusqu'à la profondeur choisie ; l'export Excel suit le même sens."""
        self.valider(self.e1, "10")
        self.valider(self.e2, "20")
        rep = self.page(sens="kpis", niveaux="1")
        self.assertTrue(rep.context["en_lignes"])
        self.assertEqual([l.org.nom for l in rep.context["colonnes_orgs"]], ["Groupe", "Pays"])
        rangs = dict((k.code, cases) for k, cases in rep.context["rangs_kpi"])
        self.assertEqual([c.point.valeur for c in rangs["EFF"]], [D(30), D(30)])
        self.assertContains(rep, 'class="table-conso table-conso-kpis')
        self.assertNotContains(rep, "data-deplier=")
        rep = self.page(sens="kpis", niveaux="2")
        self.assertEqual([l.org.nom for l in rep.context["colonnes_orgs"]], ["Groupe", "Pays", "E1", "E2"])
        self.assertEqual([p for p, _ in rep.context["profondeurs"]], [0, 1, 2])
        rep = self.client.get(reverse("collecte:consolidation_excel"), {"sens": "kpis", "niveaux": "2", "brouillons": "0"})
        ws = load_workbook(BytesIO(rep.content)).active
        self.assertEqual([c.value for c in ws[3]][:3], ["KPI", "Groupe (Groupe)", "Pays (Pays)"])
        ligne = next(r for r in ws.iter_rows(min_row=4, values_only=True) if str(r[0]).startswith("EFF"))
        self.assertEqual(list(ligne[1:5]), [30, 30, 10, 20])
        # retour au sens habituel : gardé dans la session
        self.assertTrue(self.client.get(self.url).context["en_lignes"])
        self.assertFalse(self.page(sens="orgs").context["en_lignes"])

    def test_lecteur_ne_sauvegarde_pas_de_liste(self):
        lecteur = Utilisateur.objects.create(username="lect2", email="lect2@exemple.test", role=Utilisateur.Role.LECTEUR)
        rep = self.page(lecteur)
        self.assertContains(rep, '<div class="garder-liste" hidden>')

    def test_le_mode_coche_decide(self):
        """Capture : « Une liste sauvegardée » puis « Un thème du référentiel » restait sur la liste (le
        formulaire envoie aussi la liste encore choisie dans l'autre menu)."""
        liste = SelectionKPI.objects.create(nom="Effectifs", proprietaire=self.admin)
        liste.kpis.set([self.eff])
        rep = self.page(choix_kpi="liste", selection=str(liste.pk))
        self.assertEqual((rep.context["mode"], rep.context["liste"]), ("liste", liste))
        rep = self.page(choix_kpi="theme", selection=str(liste.pk), theme="")
        self.assertEqual((rep.context["mode"], rep.context["liste"], rep.context["theme"].nom), ("theme", None, "Social"))
        self.assertEqual(self.client.get(self.url).context["mode"], "theme")  # gardé ainsi

