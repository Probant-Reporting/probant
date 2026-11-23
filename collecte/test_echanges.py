"""Page Import / Export : exports (base, tableau, format historique), préréglages, import de valeurs, configuration."""
import csv
import json
import io
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone

from parametres.models import Unite
from referentiel.models import KPI, Attribution, Niveau, Organisation

from . import configuration as C
from . import fichiers as X
from . import exports as E
from . import imports as I
from . import saisie as S
from .models import Campagne, Journal, RegleCoherence, ReglageExport, Reponse
from .outils_tests import xlsx
from .aides_tests.echanges import Base, classeur, entete

D = Decimal


class ExportTests(Base):
    def test_base_de_donnees_excel(self):
        p = E.Parametres.depuis({"presentation": "base", "exercices": ["courant"], "n1": True})
        wb = classeur(E.exporter(self.admin, p))
        self.assertEqual(wb.sheetnames, ["À lire", "Valeurs", "KPI", "Organisations"])
        self.assertEqual(set(wb["Valeurs"].tables), {"Valeurs"})  # table Excel reconnue par Power BI
        self.assertEqual(set(wb["Organisations"].tables), {"Organisations"})
        lignes = list(wb["Valeurs"].iter_rows(values_only=True))
        tete = lignes[0]
        par_cle = {(l[tete.index("ID KPI")], l[tete.index("Organisation")]): l for l in lignes[1:]}
        l = par_cle[("EFF", "E1")]
        self.assertEqual((l[tete.index("Valeur")], l[tete.index("Valeur N-1")], l[tete.index("Pays")]), (110, 100, "Pays"))
        self.assertEqual(l[tete.index("Commentaire")], "Embauches")
        self.assertEqual(par_cle[("TX", "E1")][tete.index("Valeur")], 35)  # pourcentage de 0 à 100, comme à l'écran
        self.assertEqual(par_cle[("EFF", "Pays")][tete.index("Valeur")], 150)  # agrégat
        self.assertEqual(par_cle[("DBL", "E1")][tete.index("Valeur")], 220)  # calcul
        self.assertEqual(l[tete.index("Code organisation")], "E1")  # code stable, tiré du nom
        ws = wb["Valeurs"]
        self.assertEqual(ws.cell(1, tete.index("ID KPI") + 1).fill.fgColor.rgb[-6:], X.GRIS_ENTETE)  # clé grise
        self.assertEqual(ws.cell(1, tete.index("Valeur") + 1).fill.fgColor.rgb[-6:], X.JAUNE_ENTETE)
        n = 2 + lignes[1:].index(l)
        self.assertEqual(ws.cell(n, tete.index("Valeur") + 1).number_format, "#,##0")  # décimales de l'unité
        self.assertTrue(ws.cell(n, tete.index("Début de période") + 1).is_date)
        self.assertEqual(ws.cell(n, tete.index("Début de période") + 1).number_format, X.FORMAT_DATE)
        # renommer l'organisation ne change pas son code ; le fichier se réimporte tel quel
        self.e1.nom = "Entité 1 renommée"
        self.e1.save()
        self.assertEqual(Organisation.objects.get(pk=self.e1.pk).code, "E1")
        flux = io.BytesIO()
        wb.save(flux)
        a = I.analyser(self.admin, SimpleUploadedFile("base.xlsx", flux.getvalue()))
        self.assertFalse(a.erreur)
        self.assertEqual({l.org for l in a.lignes if l.kpi_id == "EFF" and l.action == "inchange"} >= {self.e1}, True)
        self.assertIn("Base-de-donnees_Exercice-2026_", E.exporter(self.admin, p)["Content-Disposition"])
        self.assertIn('filename="Mon-export_', E.exporter(self.admin, p, titre="Mon export")["Content-Disposition"])
    def test_perimetre_contributeur(self):
        p = E.Parametres.depuis({"exercices": ["tous"], "contenus": ["valide", "brouillon", "a_saisir", "calcule"]})
        lignes = E.collecter(self.contrib, p)
        self.assertEqual({(l.kpi.code, l.org.nom) for l in lignes}, {("EFF", "E1"), ("TX", "E1")})
        tout = {(l.kpi.code, l.org.nom) for l in E.collecter(self.admin, p)}
        self.assertIn(("TX", "E2"), tout)  # case vide attendue
        self.assertIn(("EFF", "Groupe"), tout)

    def test_csv_et_formats(self):
        p = E.Parametres.depuis({"presentation": "base", "format": "csv", "csv": "fr", "exercices": ["2026"]})
        texte = E.exporter(self.admin, p).content.decode("utf-8-sig")
        self.assertIn(";", texte.splitlines()[0])
        p.csv = "intl"
        lignes = list(csv.reader(io.StringIO(E.exporter(self.admin, p).content.decode("utf-8-sig"))))
        self.assertEqual(lignes[0][:5], ["Exercice", "Période", "Début de période", "ID KPI", "Indicateur"])
        revue = E.Parametres.depuis({"presentation": "revue", "exercices": ["courant"], "contenus": ["valide", "brouillon", "a_saisir"]})
        wb = classeur(E.exporter(self.admin, revue))
        self.assertEqual(wb.sheetnames, ["À lire", "Synthèse", "2026"])
        ws = wb["2026"]
        n = entete(ws, "ID KPI")
        lignes = [r for r in ws.iter_rows(min_row=n, values_only=True)]
        self.assertEqual(lignes[0][:6], ("ID KPI", "Indicateur", "Valeur 2026", "Unité", "N-1 (2025)", "Écart"))
        self.assertTrue(lignes[1][0].startswith("E1  ·  Entité"))  # bandeau d'organisation, puis thème, puis KPI
        eff = next(r for r in lignes if r[0] == "EFF")
        self.assertEqual((eff[2], eff[4], round(eff[5], 2), eff[7]), (110, 100, 0.1, "Embauches"))
        tx = next(ws.cell(r, 3) for r in range(n, ws.max_row + 1) if ws.cell(r, 1).value == "TX")
        self.assertEqual((tx.value, tx.number_format), (35, '#,##0.00" %"'))  # pourcentage lisible, de 0 à 100
        self.assertIn("Avancement : 0 / 4 cases validées (0 %) · 3 brouillons · 1 à saisir", ws.cell(2, 1).value)  # synthèse en tête
        self.assertEqual(ws.print_title_rows, f"${n}:${n}")
        synthese = wb["Synthèse"]
        m = entete(synthese, "Période")
        synthese = {r[1]: r for r in synthese.iter_rows(min_row=m + 1, values_only=True)}
        self.assertEqual(synthese["E1"][3:8], (2, 0, 2, 0, 0))
        tableau = E.Parametres.depuis({"presentation": "tableau", "exercices": ["tous"], "n1": True})
        self.assertEqual(classeur(E.exporter(self.admin, tableau)).sheetnames, ["À lire", "2025", "2026"])
        p = E.Parametres.depuis({"presentation": "base", "format": "csv", "csv": "intl", "exercices": ["2026"], "langue": "en"})
        rep = E.exporter(self.admin, p)
        lignes = list(csv.reader(io.StringIO(rep.content.decode("utf-8-sig"))))
        self.assertEqual(lignes[0][:5], ["Year", "Period", "Period start", "KPI ID", "Indicator"])
        self.assertIn("Organisation code", lignes[0])
        self.assertIn("Database_Year-2026_", rep["Content-Disposition"])

    def test_export_de_tous_les_exercices_relu_tel_quel(self):
        """Exercice clôturé : une valeur saisie dans l'outil, relue identique, est inchangée (pas rejetée)."""
        Reponse.objects.create(periode=self.c0.periode, kpi=self.taux, organisation=self.e1, valeur=D("0.3"), statut="valide",
                               origine=Reponse.Origine.SAISIE)  # saisie dans l'outil, campagne clôturée depuis
        p = E.Parametres.depuis({"presentation": "base", "exercices": ["tous"]})
        a = I.analyser(self.admin, SimpleUploadedFile("base.xlsx", E.exporter(self.admin, p).content))
        self.assertEqual({l.action for l in a.lignes} - {"ignore"}, {"inchange"})

    def test_tableau_lisible_une_ligne_d_en_tetes_et_ecarts(self):
        self.c.seuil_ecart = D("0.05")
        self.c.save()
        p = E.Parametres.depuis({"presentation": "tableau", "exercices": ["2026"], "n1": True})
        wb = classeur(E.exporter(self.admin, p))
        self.assertEqual(wb.sheetnames, ["À lire", "2026"])
        ws = wb["2026"]
        n = entete(ws, "ID KPI")
        tete = [c.value for c in ws[n]]
        self.assertEqual(tete[:5], ["ID KPI", "Indicateur", "Type", "Unité", "Groupe"])
        self.assertIn("E1 – N-1", tete)
        self.assertFalse([r for r in ws.merged_cells.ranges if r.min_row >= n])  # aucune cellule fusionnée dans le tableau
        self.assertEqual((ws.freeze_panes, ws.print_title_rows), (f"E{n + 1}", f"${n}:${n}"))
        self.assertEqual(ws.page_setup.orientation, "landscape")
        eff = next(r for r in range(n, ws.max_row + 1) if ws.cell(r, 1).value == "EFF")
        e1 = ws.cell(eff, tete.index("E1") + 1)
        self.assertEqual(e1.value, 110)
        self.assertEqual(e1.fill.fgColor.rgb[-6:], X.ORANGE_ALERTE)  # +10 % avec N-1 > seuil de 5 %
        # type de saisie (étiquette courte réglée dans l'outil) ; case sans objet à ce niveau : hachurée
        self.assertEqual(ws.cell(eff, 3).value, self.eff.type_saisie.abrege or self.eff.type_saisie.libelle)
        tx = next((r for r in range(n, ws.max_row + 1) if ws.cell(r, 1).value == "TX"), None)
        if tx is not None:  # taux sans agrégation, saisi à l'entité : rien au niveau du Groupe
            self.assertEqual(ws.cell(tx, tete.index("Groupe") + 1).fill.fill_type, "lightUp")
            self.assertNotEqual(ws.cell(tx, tete.index("E1") + 1).fill.fill_type, "lightUp")
        theme = ws.cell(n + 1, 1)
        self.assertTrue(theme.value)  # ligne de groupe du thème, avant ses KPI

    def test_rapport_de_revue_liens_vers_les_cases(self):
        p = E.Parametres.depuis({"presentation": "revue", "exercices": ["2026"], "contenus": ["valide", "brouillon", "a_saisir"]})
        wb = classeur(E.exporter(self.admin, p, adresse="https://kpi.exemple.test/"))
        ws = wb["2026"]
        cell = next(ws.cell(r, 2) for r in range(1, ws.max_row + 1) if ws.cell(r, 1).value == "EFF")
        self.assertEqual(cell.hyperlink.target, f"https://kpi.exemple.test/saisie/{self.c.pk}/EFF/{self.e1.pk}/")
        self.assertTrue(wb["À lire"].cell(1, 1).value.startswith("Rapport de revue"))

    def test_modeles_fournis_modifiables_et_supprimables(self):
        url = reverse("collecte:echanges_exporter")
        fourni = ReglageExport.objects.get(nom="Tableau de l'exercice avec N-1")  # créé par la migration, partagé
        self.client.force_login(self.contrib)
        rep = self.client.get(f"{url}?modele={fourni.pk}&telecharger=1")
        self.assertEqual(rep["Content-Type"], "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.assertContains(self.client.get(f"{url}?modele={fourni.pk}"), "Enregistrer une copie")  # partagé : lecture seule
        self.assertEqual(self.client.post(reverse("collecte:echanges_supprimer_reglage", args=[fourni.pk])).status_code, 403)
        # copie personnelle, modifiée puis supprimée par sa propriétaire
        rep = self.client.post(url, {"action": "copier", "modele": fourni.pk, "nom": fourni.nom, "presentation": "tableau",
                                     "exercices": ["courant"], "partage": "on"})
        copie = ReglageExport.objects.get(proprietaire=self.contrib)
        self.assertEqual((copie.nom, copie.partage), ("Tableau de l'exercice avec N-1 (copie)", False))  # seul l'admin partage
        self.client.post(url, {"action": "enregistrer", "modele": copie.pk, "nom": "Mon tableau", "presentation": "revue",
                               "exercices": ["2025"]})
        copie.refresh_from_db()
        self.assertEqual((copie.nom, copie.parametres["presentation"], copie.parametres["exercices"]), ("Mon tableau", "revue", ["2025"]))
        liste = reverse("collecte:echanges")  # Mes exports
        self.assertContains(self.client.get(liste), "Mon tableau")  # affiche (et vide) le message de confirmation, gardé dans un cookie
        self.client.force_login(self.autre)
        self.assertNotContains(self.client.get(liste), "Mon tableau")
        self.assertEqual(self.client.post(reverse("collecte:echanges_supprimer_reglage", args=[copie.pk])).status_code, 403)
        # l'admin modifie et supprime un modèle partagé, puis le recrée
        self.client.force_login(self.admin)
        self.client.post(url, {"action": "enregistrer", "modele": fourni.pk, "nom": "Tableau N-1", "presentation": "tableau",
                               "exercices": ["tous"], "partage": "on", "n1": "on"})
        fourni.refresh_from_db()
        self.assertEqual((fourni.nom, fourni.parametres["exercices"]), ("Tableau N-1", ["tous"]))
        self.client.post(reverse("collecte:echanges_supprimer_reglage", args=[fourni.pk]))
        self.assertFalse(ReglageExport.objects.filter(pk=fourni.pk).exists())
        self.client.post(reverse("collecte:echanges_restaurer_modeles"))
        self.assertTrue(ReglageExport.objects.filter(nom="Tableau de l'exercice avec N-1", partage=True).exists())
        # ordre par glisser-déposer (admin) : celui de la liste « Mes exports » ; « Nouvel export » part de zéro
        ids = list(ReglageExport.objects.order_by("-nom").values_list("pk", flat=True))
        self.client.post(reverse("collecte:echanges_ordre_modeles"), json.dumps({"ids": ids}), content_type="application/json")
        premier = ReglageExport.objects.get(pk=ids[0])
        self.assertEqual(ReglageExport.objects.first(), premier)
        self.assertEqual(self.client.get(reverse("collecte:echanges")).context["modeles"][0], premier)
        self.assertIsNone(self.client.get(url + "?nouveau=1").context["modele"])
        rep = self.client.post(url, {"action": "telecharger", "format": "csv", "exercices": ["2026"]})  # rien de coché
        self.assertContains(rep, "Cochez au moins une organisation.")  # plus un fichier vide sans un mot
        rep = self.client.post(url, {"action": "telecharger", "format": "csv", "exercices": ["2026"], "niveaux": E.N.codes()})
        self.assertEqual(rep["Content-Type"], "text/csv; charset=utf-8")


class LegendesRevueTests(Base):
    def test_revue_legende_complete_et_synthese_sans_roles(self):
        # « Calculé » et « Incomplet » expliqués, écart défini, « Validé » = saisie déclarée
        # complète ; synthèse sans la légende « à remplir / clé » ; « Cases attendues » distinct de « À saisir »
        self.c.seuil_ecart = Decimal("0.2")
        self.c.save()
        p = E.Parametres.depuis({"presentation": "revue", "exercices": ["2026"],
                                 "contenus": ["valide", "brouillon", "a_saisir", "calcule"]})
        wb = classeur(E.exporter(self.admin, p))
        lire = [c.value for row in wb["À lire"].iter_rows() for c in row if isinstance(c.value, str)]
        for attendu in ("Calculé", "Incomplet", "KPI calculé dont au moins une source manque encore.",
                        "Le contributeur a déclaré sa saisie complète (ce n'est pas une vérification de l'exactitude)."):
            self.assertIn(attendu, lire)
        self.assertTrue(any("(valeur − N-1) / N-1" in t for t in lire))
        synthese = [c.value for row in wb["Synthèse"].iter_rows() for c in row]
        self.assertIn("Cases attendues", synthese)
        self.assertNotIn("À remplir", synthese)
        ws = wb["2026"]
        valeurs = [c for row in ws.iter_rows() if row[0].value in ("EFF", "TX") for c in row if c.value is not None]
        self.assertTrue(valeurs and all(c.alignment.vertical == "top" for c in valeurs))  # lignes calées en haut


class ImportTests(Base):
    def test_fichier_a_remplir_rempli_dans_excel_puis_reimporte(self):
        wb = classeur(I.modele(self.contrib, self.c, I.lignes_modele(self.contrib, self.c)))
        self.assertEqual(wb.sheetnames, ["À lire", "Saisie", "Définitions"])
        ws = wb["Saisie"]
        self.assertTrue(ws.protection.sheet)
        n = next(r for r in range(1, 15) if ws.cell(r, 2).value == "ID KPI")
        tete = [c.value for c in ws[n]]
        self.assertEqual(ws.freeze_panes, f"D{n + 1}")  # organisation, ID et indicateur restent visibles
        # contrôles de saisie actifs : alerte (avertissement) et aide sur la cellule Valeur 
        regles = ws.data_validations.dataValidation
        self.assertTrue(regles)
        self.assertTrue(all(dv.showErrorMessage and dv.errorStyle == "warning" and dv.showInputMessage and dv.prompt for dv in regles))
        lignes = {ws.cell(r, 2).value: r for r in range(n + 1, ws.max_row + 1) if ws.cell(r, 2).value}
        self.assertEqual(set(lignes), {"EFF", "TX"})
        valeur = tete.index("Valeur") + 1
        self.assertFalse(ws.cell(lignes["EFF"], valeur).protection.locked)  # cellule jaune
        self.assertTrue(ws.cell(lignes["EFF"], 2).protection.locked)  # clé grise
        self.assertTrue(str(ws.cell(lignes["EFF"], tete.index("État") + 1).value).startswith("=IF("))
        ws.cell(lignes["EFF"], valeur).value = 130
        flux = io.BytesIO()
        wb.save(flux)
        a = I.analyser(self.contrib, SimpleUploadedFile("rempli.xlsx", flux.getvalue()))
        self.assertEqual([(l.kpi_id, l.action) for l in a.lignes], [("EFF", "modifier"), ("TX", "inchange")])

    def test_a_verifier_na_sans_commentaire_et_preuve_deja_jointe(self):
        # « À vérifier » prévient de ce que « Valider » refusera (N/A sans commentaire) et ne
        # demande plus une preuve déjà jointe dans l'outil
        from .models import Preuve

        for k in (self.eff, self.taux):
            k.preuve_obligatoire = True
            k.save()
        Preuve.objects.create(reponse=Reponse.objects.get(periode=self.c.periode, kpi=self.taux, organisation=self.e1),
                              fichier=SimpleUploadedFile("facture.pdf", b"%PDF-1.4 essai"))
        Reponse.objects.filter(periode=self.c.periode, kpi=self.eff, organisation=self.e1).update(
            valeur=None, non_applicable=True, commentaire="")
        rep = I.modele(self.contrib, self.c, I.lignes_modele(self.contrib, self.c), "csv")
        lignes = list(csv.reader(io.StringIO(rep.content.decode("utf-8-sig")), delimiter=";"))
        tete = lignes[0]
        verifier = {l[tete.index("ID KPI")]: l[tete.index("À vérifier")] for l in lignes[1:]}
        self.assertEqual(verifier, {"EFF": "N/A : commentaire obligatoire.", "TX": ""})
        wb = classeur(I.modele(self.contrib, self.c, I.lignes_modele(self.contrib, self.c)))
        ws = wb["Saisie"]
        n = next(r for r in range(1, 15) if ws.cell(r, 2).value == "ID KPI")
        tete = [c.value for c in ws[n]]
        formules = {ws.cell(r, 2).value: ws.cell(r, tete.index("À vérifier") + 1).value for r in range(n + 1, ws.max_row + 1)}
        self.assertIn("N/A : commentaire obligatoire.", formules["EFF"])
        self.assertIn("Preuve à ajouter", formules["EFF"])  # aucune preuve : demandée (sauf N/A)
        self.assertNotIn("Preuve à ajouter", formules["TX"])  # déjà jointe

    def test_un_onglet_par_organisation(self):
        Attribution.objects.create(kpi=self.eff, utilisateur=self.contrib, organisation=self.e2)
        rep = I.modele(self.contrib, self.c, I.lignes_modele(self.contrib, self.c), par_organisation=True)
        wb = classeur(rep)
        self.assertEqual(wb.sheetnames[0], "À lire")
        self.assertIn("E2", wb.sheetnames)
        a = I.analyser(self.contrib, SimpleUploadedFile("orgs.xlsx", rep.content))
        self.assertFalse(a.erreur)
        self.assertEqual({l.org.nom for l in a.lignes}, {"E1", "E2"})

    def test_fichier_a_remplir_csv_et_nom_explicite(self):
        rep = I.modele(self.contrib, self.c, I.lignes_modele(self.contrib, self.c), "csv")
        self.assertIn("A-remplir_", rep["Content-Disposition"])
        self.assertIn(timezone.localdate().isoformat(), rep["Content-Disposition"])
        a = I.analyser(self.contrib, SimpleUploadedFile("modele.csv", rep.content))
        self.assertEqual({l.action for l in a.lignes}, {"inchange"})

    def test_rapport_des_lignes_rejetees(self):
        f = xlsx([["ID", "Organisation", "Exercice", "Résultat"], ["EFF", "E1", 2026, 7], ["EFF", "Nulle part", 2026, 3],
                  ["TX", "E1", 2026, "beaucoup"]])
        self.client.force_login(self.contrib)
        url = reverse("collecte:echanges_importer")
        rep = self.client.post(url, {"action": "verifier", "fichier": f})
        self.assertContains(rep, "Télécharger les lignes rejetées (2)")
        wb = classeur(self.client.get(reverse("collecte:echanges_rejets")))
        ws = wb[wb.sheetnames[1]]
        n = next(r for r in range(1, 15) if ws.cell(r, 1).value == "Organisation")
        tete = [c.value for c in ws[n]]
        modele = classeur(I.modele(self.contrib, self.c, I.lignes_modele(self.contrib, self.c))).worksheets[1]
        m = next(r for r in range(1, 15) if modele.cell(r, 1).value == "Organisation")
        self.assertEqual(tete, [c.value for c in modele[m]])  # mêmes colonnes que le fichier à remplir
        rejets = [list(r) for r in ws.iter_rows(min_row=n + 1, values_only=True) if r[0]]
        self.assertEqual([(r[tete.index("Organisation")], r[tete.index("État")]) for r in rejets], [("Nulle part", "Rejetée"), ("E1", "Rejetée")])
        self.assertTrue(rejets[0][tete.index("À vérifier")].startswith("Ligne 3 : Organisation inconnue"))
        # légende juste : rien n'est gris (clé) ici, l'organisation et l'ID KPI se corrigent aussi
        for feuille in wb.worksheets:
            self.assertNotIn("Clé : ne pas modifier", [c.value for row in feuille.iter_rows() for c in row])
        self.assertEqual(rejets[1][tete.index("Indicateur")], I.nom_kpi(KPI.objects.get(code="TX"), "fr"))
        # corrigé puis réimporté : les colonnes État et À vérifier sont ignorées
        ws.cell(n + 1, tete.index("Organisation") + 1).value = "E1"
        ws.cell(n + 2, tete.index("Valeur") + 1).value = 12
        flux = io.BytesIO()
        wb.save(flux)
        a = I.analyser(self.contrib, SimpleUploadedFile("corrige.xlsx", flux.getvalue()))
        self.assertEqual([l.action for l in a.lignes], ["modifier", "modifier"])
        self.client.post(url, {"action": "annuler"})

    def test_corriger_les_rejets_dans_l_apercu(self):
        f = xlsx([["ID", "Organisation", "Exercice", "Résultat"], ["EFF", "E1", 2026, 7], ["EFF", "Nulle part", 2026, 3],
                  ["TX", "E1", 2026, "beaucoup"]])
        self.client.force_login(self.contrib)
        url = reverse("collecte:echanges_importer")
        rep = self.client.post(url, {"action": "verifier", "fichier": f})
        self.assertContains(rep, "À corriger ici")
        rejets = rep.context["rejets"]
        donnees = {"action": "corriger", "nb_rejets": len(rejets)}
        for i, r in enumerate(rejets):
            donnees.update({f"cle_{i}": r["cle"], f"kpi_{i}": r["kpi"], f"organisation_{i}": r["organisation"],
                            f"periode_{i}": r["exercice"], f"valeur_{i}": "12" if r["kpi"] == "TX" else r["valeur"],
                            f"commentaire_{i}": ""})
        rep = self.client.post(url, donnees)  # la valeur de TX est corrigée ; « Nulle part » reste rejetée
        self.assertContains(rep, "Il reste 1 ligne rejetée")
        self.assertContains(rep, "Corrigée dans l'aperçu")
        self.assertEqual([l.action for l in rep.context["analyse"].lignes], ["modifier", "rejet", "modifier"])
        donnees["organisation_0"] = "E1"  # devient un doublon de la ligne 2 : toujours rejetée, avec le nouveau motif
        rep = self.client.post(url, donnees)
        self.assertEqual(rep.context["rejets"][0]["motif"], "Doublon de la ligne 2.")
        rep = self.client.post(url, {"action": "confirmer"})
        self.assertContains(rep, "Import terminé")
        self.assertEqual(Reponse.objects.get(periode=self.c.periode, kpi_id="TX", organisation=self.e1).valeur, D("0.12"))

    def test_modele_puis_import(self):
        """Ancien format du fichier à remplir (en-têtes en ligne 1, sans bandeau) : toujours accepté."""
        wb = classeur(I.modele(self.contrib, self.c, I.lignes_modele(self.contrib, self.c)))
        ws = wb["Saisie"]
        n = next(r for r in range(1, 15) if ws.cell(r, 2).value == "ID KPI")
        tete = [c.value for c in ws[n]]
        lignes = {r[1]: list(r) for r in ws.iter_rows(min_row=n + 1, values_only=True) if r[1]}
        self.assertEqual(set(lignes), {"EFF", "TX"})
        self.assertEqual(lignes["EFF"][tete.index("Valeur N-1")], 100)
        lignes["EFF"][tete.index("Valeur")] = 120
        lignes["TX"][tete.index("Valeur")] = "40,5"
        lignes["TX"][tete.index("Commentaire")] = "Nouveau calcul"
        f = xlsx([tete] + list(lignes.values()))
        a = I.analyser(self.contrib, f)
        self.assertEqual([(l.kpi_id, l.action) for l in a.lignes], [("EFF", "modifier"), ("TX", "modifier")])
        f.seek(0)
        _, n, _ = I.appliquer(self.contrib, f, "fichier.xlsx", valider=True)
        self.assertEqual(n, 2)
        eff, tx = S.reponse_de(self.c, self.eff, self.e1), S.reponse_de(self.c, self.taux, self.e1)
        self.assertEqual((eff.valeur, eff.commentaire, eff.statut), (D(120), "Embauches", Reponse.Statut.VALIDE))  # commentaire gardé
        self.assertEqual((tx.valeur, tx.commentaire), (D("0.405"), "Nouveau calcul"))
        self.assertEqual(S.reponse_de(self.c, self.calc, self.e1).valeur, D(240))  # recalcul en fin d'import
        self.assertTrue(Journal.objects.filter(action="import_valeurs").exists())

    def test_rejets_et_lignes_ignorees(self):
        f = xlsx([
            ["ID", "Organisation", "Exercice", "Résultat", "N/A"],
            ["INCONNU", "E1", 2026, 3, ""],
            ["EFF", "Nulle part", 2026, 3, ""],
            ["EFF", "Pays", 2026, 3, ""],  # total agrégé : ignoré
            ["DBL", "E1", 2026, 3, ""],  # calculé : refusé (le contributeur ne peut pas forcer un calcul)
            ["EFF", "Entité numéro 1", "Exercice 2026", "beaucoup", ""],  # alias reconnu, valeur invalide
            ["TX", "E1", 2026, 150, ""],
            ["EFF", "E2", 2026, 5, ""],  # hors périmètre du contributeur
            ["TX", "E1", 2026, "", "Oui"],
            ["TX", "E1", 2026, "", "Oui"],
            ["EFF", "E1", 2025, 1, ""],  # campagne clôturée
            ["EFF", "E1", 2026, "", ""],  # vide : ignorée
            ["EFF", "Entité numéro 1", 2026, "1e30", ""],  # trop grand : rejet clair (plus d'erreur à l'enregistrement)
        ])
        a = I.analyser(self.contrib, f)
        actions = [(l.action, l.motif.split(" :")[0].split(" (")[0]) for l in a.lignes]
        self.assertEqual(actions, [
            ("rejet", "KPI inconnu"), ("rejet", "Organisation inconnue"), ("ignore", "Total agrégé"),
            ("rejet", "KPI calculé"), ("rejet", "« beaucoup » n'est pas un nombre. Saisissez le nombre seul, sans unité ni texte."), ("rejet", "Saisissez un pourcentage de 0 à 100."),
            ("rejet", "Cette cellule n'est pas dans votre périmètre."),
            ("modifier", "N/A sans commentaire"),  # importée, avec la remarque : « Valider » la refusera
            ("rejet", "Doublon de la ligne 9."),
            ("rejet", "Campagne clôturée"), ("ignore", "Valeur vide."), ("rejet", "Ce nombre est trop grand"),
        ])

    def test_historique_par_l_admin(self):
        f = xlsx([["ID KPI", "Organisation", "Exercice", "Valeur"], ["EFF", "E2", 2025, 30], ["EFF", "E1", 2024, 90],
                  ["EFF", "E1", 2025, 101]])
        a = I.analyser(self.admin, f)
        self.assertEqual([l.action for l in a.lignes], ["creer", "rejet", "modifier"])  # 2024 : pas de campagne
        f.seek(0)
        a = I.analyser(self.admin, f, creer_campagnes=True)
        self.assertEqual(a.campagnes_a_creer, ["Reporting Ma structure · 2024"])  # référentiel annuel, période 2024
        f.seek(0)
        I.appliquer(self.admin, f, "histo.xlsx", creer_campagnes=True)
        r = S.reponse_de(Campagne.objects.get(exercice=2024), self.eff, self.e1)
        self.assertEqual((r.valeur, r.origine, r.statut), (D(90), Reponse.Origine.IMPORT, Reponse.Statut.VALIDE))
        self.assertEqual(S.reponse_de(self.c0, self.eff, self.e1).valeur, D(101))
        self.assertEqual(S.reponse_de(self.c0, self.eff, self.p).valeur, D(131))  # agrégat de l'historique recalculé

    def test_pages_apercu_puis_confirmation(self):
        self.client.force_login(self.contrib)
        rep = self.client.get(reverse("collecte:echanges_modele") + "?format=csv")
        self.assertIn("EFF", rep.content.decode("utf-8-sig"))
        f = xlsx([["ID KPI", "Organisation", "Valeur"], ["EFF", "E1", 130]])
        rep = self.client.post(reverse("collecte:echanges_importer"), {"action": "verifier", "fichier": f, "campagne": self.c.pk})
        self.assertContains(rep, "Aperçu avant import")
        self.assertContains(rep, "Importer 1 ligne")
        self.assertEqual(S.reponse_de(self.c, self.eff, self.e1).valeur, D(110))  # rien n'est écrit avant confirmation
        rep = self.client.post(reverse("collecte:echanges_importer"), {"action": "confirmer"})
        self.assertContains(rep, "Import terminé")
        self.assertEqual(S.reponse_de(self.c, self.eff, self.e1).valeur, D(130))
        rep = self.client.post(reverse("collecte:echanges_importer"), {"action": "confirmer"})
        self.assertEqual(rep.status_code, 302)  # fichier déjà utilisé


class FinImportTests(Base):
    """Importer des valeurs : l'aperçu signale les écarts avec N-1, la fin d'import dit ce qui reste à valider et le fait."""

    def test_ecart_signale_puis_valider_ces_valeurs(self):
        Campagne.objects.filter(pk=self.c.pk).update(seuil_ecart=D("0.2"))
        self.client.force_login(self.contrib)
        url = reverse("collecte:echanges_importer")
        f = xlsx([["ID KPI", "Organisation", "Valeur", "Commentaire"], ["EFF", "E1", 130, "Deux sites ouverts"]])
        rep = self.client.post(url, {"action": "verifier", "fichier": f, "campagne": self.c.pk})
        self.assertContains(rep, "de N-1 au-delà du seuil de la campagne (20\u202f%)")  # N-1 = 100 : +30 %
        self.assertContains(rep, "+30,0\u202f% vs N-1")
        rep = self.client.post(url, {"action": "confirmer"})
        self.assertContains(rep, "valeur enregistrée en brouillon")
        self.assertContains(rep, "à valider")
        self.assertContains(rep, "Valider cette valeur")
        self.assertEqual(S.reponse_de(self.c, self.eff, self.e1).statut, Reponse.Statut.BROUILLON)
        rep = self.client.post(url, {"action": "valider_import"})
        self.assertContains(rep, "1 valeur validée")
        self.assertEqual(S.reponse_de(self.c, self.eff, self.e1).statut, Reponse.Statut.VALIDE)
        rep = self.client.post(url, {"action": "valider_import"})  # plus rien en attente : rien à valider
        self.assertContains(rep, "Rien à valider")

    def test_ce_qui_ne_passera_pas_la_validation_est_dit_tout_de_suite(self):
        Campagne.objects.filter(pk=self.c.pk).update(seuil_ecart=D("0.2"))
        self.client.force_login(self.contrib)
        url = reverse("collecte:echanges_importer")
        Reponse.objects.filter(periode=self.c.periode, kpi=self.eff, organisation=self.e1).update(commentaire="")
        f = xlsx([["ID KPI", "Organisation", "Valeur"], ["EFF", "E1", 130]])  # +30 % sans commentaire
        self.client.post(url, {"action": "verifier", "fichier": f, "campagne": self.c.pk})
        rep = self.client.post(url, {"action": "confirmer"})
        self.assertContains(rep, "à compléter avant de valider")
        self.assertContains(rep, "avec N-1 dépasse 20 %")
        self.assertNotContains(rep, 'value="valider_import"')  # pas de bouton qui échouerait
        self.assertContains(rep, "Compléter dans la page Saisie")

    def test_fichier_a_remplir_par_defaut_ce_qui_reste_et_raccourci_depuis_saisie(self):
        self.client.force_login(self.contrib)
        for k in (self.eff, self.taux):  # tout est validé : pas de fichier vide, un message
            S.enregistrer(self.contrib, self.c, k, self.e1, "12", False, "")
            S.valider(self.contrib, self.c, k, self.e1)
        rep = self.client.post(reverse("collecte:echanges_modele"), {"campagne": self.c.pk, "a_faire": "on"}, follow=True)
        self.assertContains(rep, "Rien à remplir : tout est déjà validé")
        rep = self.client.post(reverse("collecte:echanges_modele"), {"campagne": self.c.pk})
        self.assertEqual(rep["Content-Type"], "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.assertContains(self.client.get(reverse("collecte:echanges_importer")), 'name="a_faire" checked')
        rep = self.client.get(reverse("collecte:saisie"))
        self.assertContains(rep, "Importer des valeurs")
        self.assertContains(rep, reverse("collecte:echanges_importer"))


class ConfigurationTests(Base):
    def setUp(self):
        super().setUp()
        RegleCoherence.objects.create(nom="Double ≥ effectif", gauche="[DBL]", operateur=">=", droite="[EFF]", niveau_id=Niveau.ENTITY)

    def exporter(self, **modifs):
        wb = classeur(C.exporter())
        for onglet, cellules in modifs.items():
            for ref, v in cellules.items():
                if ref == "+":
                    tete = [c.value for c in wb[onglet][1]]
                    for ligne in v:  # {en-tête: valeur}, ou valeurs dans l'ordre des colonnes
                        wb[onglet].append([ligne.get(t, "") for t in tete] if isinstance(ligne, dict) else ligne)
                else:
                    wb[onglet][ref] = v
        flux = io.BytesIO()
        wb.save(flux)
        return SimpleUploadedFile("config.xlsx", flux.getvalue())

    def test_aller_retour_sans_changement(self):
        a = C.analyser(self.exporter())
        self.assertFalse(a.erreur)
        self.assertEqual({c.action for cs in a.onglets.values() for c in cs}, {"inchange"})  # tout relu à l'identique
        self.assertEqual({nom: len(cs) for nom, cs in a.onglets.items() if nom in ("Niveaux", "Types de saisie", "Types de réponse",
                                                                              "Catégories", "Organisations", "Alias", "KPI", "Règles de cohérence")},
                         {"Niveaux": 4, "Types de saisie": 3, "Types de réponse": 3, "Catégories": 4, "Organisations": 4, "Alias": 1,
                          "KPI": 3, "Règles de cohérence": 1})
        self.assertEqual(len(a.onglets["Unités"]), Unite.objects.count())

    def test_modifications_creations_et_rejets(self):
        ws = classeur(C.exporter())["KPI"]
        tete = [c.value for c in ws[1]]
        ligne_tx = next(r[0].row for r in ws.iter_rows(min_row=2) if r[0].value == "TX")
        col = {t: chr(65 + i) for i, t in enumerate(tete)}

        def kpi(code, ordre, nom, type_saisie, formule=""):
            return {"ID KPI": code, "Ordre": ordre, "Nom (FR)": nom, "Type de saisie": type_saisie, "Type de réponse": "Numérique",
                    "Unité": "t", "Décimales": 2, "Granularité": "Entité", "Agrégation": "Somme", "Formule": formule}
        f = self.exporter(
            KPI={f"{col['Nom (FR)']}{ligne_tx}": "Taux de formation", f"{col['Décimales']}{ligne_tx}": 1,
                 "+": [kpi("NEW", 5, "Nouveau", "Saisi"), kpi("NEW2", 6, "Calcul", "Calculé", "[NEW] + [ABSENT]"),
                       kpi("NEW3", 7, "Boucle", "Calculé", "[NEW3@N-1] + [DBL]"), kpi("NEW4", 8, "Mauvais", "Bidule")]},
            Organisations={"+": [["E3", "", "", "Entité", "Pays", "", 9, "Oui"], ["S1", "", "", "Pays", "E3", "", 9, "Oui"],
                                 ["S2", "S-2", "", "Site", "Pays", "", 9, "Oui"]]},
        )
        a = C.analyser(f)
        lus = {c.cle: c for c in a.onglets["KPI"]}
        self.assertEqual(lus["TX"].action, "modifier")
        self.assertEqual(lus["TX"].champs, [("Nom (FR)", "Taux", "Taux de formation"), ("Décimales", 2, 1)])
        self.assertEqual((lus["NEW"].action, lus["NEW3"].action), ("creer", "creer"))  # [ID@N-1] sur soi-même : permis
        self.assertIn("ABSENT", lus["NEW2"].motif)
        self.assertIn("Bidule", lus["NEW4"].motif)
        orgs = {c.cle: c for c in a.onglets["Organisations"]}
        self.assertEqual(orgs["E3"].action, "creer")
        self.assertIn("se rattache à une organisation d'un niveau supérieur", orgs["S1"].motif)
        self.assertEqual(orgs["S2"].action, "creer")  # rattachement souple : site directement sous le pays
        f.seek(0)
        # tout ou rien : des lignes refusées, et rien n'est enregistré
        a, n, _ = C.appliquer(self.admin, f, "config.xlsx")
        self.assertEqual((n, a.nb_rejets, a.importable), (0, 3, False))
        self.assertEqual(KPI.objects.get(pk="TX").libelle, "Taux")
        self.assertFalse(KPI.objects.filter(pk__in=["NEW", "NEW3"]).exists())
        self.assertFalse(Organisation.objects.filter(nom__in=["E3", "S2"]).exists())
        self.assertFalse(Journal.objects.filter(action__in=["reglage_kpi", "import_configuration"]).exists())
        # les lignes refusées retirées : tout est enregistré
        f = self.exporter(
            KPI={f"{col['Nom (FR)']}{ligne_tx}": "Taux de formation", f"{col['Décimales']}{ligne_tx}": 1,
                 "+": [kpi("NEW", 5, "Nouveau", "Saisi"), kpi("NEW3", 7, "Boucle", "Calculé", "[NEW3@N-1] + [DBL]")]},
            Organisations={"+": [["E3", "", "", "Entité", "Pays", "", 9, "Oui"], ["S2", "S-2", "", "Site", "Pays", "", 9, "Oui"]]},
        )
        a, n, _ = C.appliquer(self.admin, f, "config.xlsx")
        self.assertEqual((a.nb_rejets, n), (0, 5))
        self.assertEqual(KPI.objects.get(pk="TX").libelle, "Taux de formation")
        self.assertTrue(KPI.objects.filter(pk="NEW3").exists())
        self.assertFalse(KPI.objects.filter(pk__in=["NEW2", "NEW4"]).exists())
        self.assertEqual(Organisation.objects.get(nom="E3").parent, self.p)
        self.assertEqual((Organisation.objects.get(nom="E3").code, Organisation.objects.get(nom="S2").code), ("E3", "S-2"))
        self.assertTrue(Journal.objects.filter(action="reglage_kpi", champ="Nom (FR)").exists())

    def test_desactiver_les_absents_et_ancien_format(self):
        f = xlsx([["code", "nom_fr", "type_saisie", "granularite", "actif"], ["EFF", "Effectif total", "Saisi", "Entity", "Oui"]],
                 onglet="KPI")
        a = C.analyser(f, desactiver_absents=True)
        actions = {c.cle: c.action for c in a.onglets["KPI"]}
        self.assertEqual(actions, {"EFF": "modifier", "TX": "desactiver", "DBL": "desactiver"})
        f.seek(0)
        C.appliquer(self.admin, f, "ancien.xlsx", desactiver_absents=True)
        self.assertFalse(KPI.objects.get(pk="TX").actif)
        self.assertEqual(KPI.objects.get(pk="EFF").libelle, "Effectif total")

    def test_regles_et_droits(self):
        f = xlsx([["Nom", "Partie gauche", "Opérateur", "Partie droite", "Tolérance (%)"],
                  ["Taux ≤ 100", "[TX]", "≤", "1", 0], ["Cassée", "[ZZZ]", "=", "[EFF]", 1]], onglet="Règles de cohérence")
        a = C.analyser(f)
        self.assertEqual([c.action for c in a.onglets["Règles de cohérence"]], ["creer", "rejet"])
        f.seek(0)
        C.appliquer(self.admin, f, "regles.xlsx")  # une ligne refusée : rien (tout ou rien)
        self.assertFalse(RegleCoherence.objects.filter(nom="Taux ≤ 100").exists())
        C.appliquer(self.admin, xlsx([["Nom", "Partie gauche", "Opérateur", "Partie droite", "Tolérance (%)"],
                                      ["Taux ≤ 100", "[TX]", "≤", "1", 0]], onglet="Règles de cohérence"), "regles.xlsx")
        regle = RegleCoherence.objects.get(nom="Taux ≤ 100")
        self.assertEqual((regle.operateur, regle.niveau_id), ("<=", Niveau.ENTITY))  # sans colonne Niveau : celui du KPI cité
        self.client.force_login(self.contrib)
        self.assertEqual(self.client.get(reverse("collecte:admin_fichiers")).status_code, 403)
        self.client.force_login(self.admin)
        rep = self.client.get(reverse("collecte:admin_fichiers") + "?telecharger=vierge")
        self.assertEqual(classeur(rep).sheetnames, ["À lire", "Langues", "Réglages", "Niveaux", "Unités", "Types de saisie", "Types de réponse", "Catégories",
                                                    "Champs", "Référentiels", "Thèmes", "KPI", "Éléments", "Organisations", "Alias",
                                                    "Règles de cohérence", "Listes"])
        rep = self.client.post(reverse("collecte:admin_fichiers"), {"action": "verifier", "fichier": self.exporter()})
        self.assertContains(rep, "Rien à importer")
