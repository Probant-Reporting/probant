"""Filet de tests des imports et exports aller-retour : figent le comportement actuel.

Un export (Excel, CSV français ou international, en français ou en anglais) relu tel quel ne change rien ; pourcentages
écrits de 0 à 100 et stockés en fraction ; N/A ; oui / non et listes (dans les deux langues) ; nombres négatifs et
décimaux ; commentaire vide = commentaire gardé ; historique d'un exercice clôturé ; rejets nommés."""
import csv
import io
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from openpyxl import load_workbook


from . import exports as E
from . import imports as I
from .models import Reponse
from .aides_tests.aller_retour import Base, fichier

D = Decimal


class AllerRetourTests(Base):
    def test_export_excel_relu_tel_quel(self):
        for exercices in (["courant"], ["tous"]):
            p = E.Parametres.depuis({"presentation": "base", "exercices": exercices, "n1": True})
            a = I.analyser(self.admin, SimpleUploadedFile("base.xlsx", E.exporter(self.admin, p).content))
            self.assertFalse(a.erreur)
            self.assertEqual(self.actions(a), ["ignore", "inchange"], exercices)
            self.assertEqual({l.org.nom for l in a.lignes if l.action == "ignore" and l.kpi_id != "DBL"}, {"Groupe", "Pays"})
            self.assertEqual({(l.kpi_id, l.org.nom) for l in a.lignes if l.action == "inchange" and l.exercice == 2026},
                             {(k, o) for k in ("EFF", "TX", "POL", "CERT", "NRJ") for o in ("E1", "E2")} - {("CERT", "E2")})
            self.assertTrue(all(l.motif in ("KPI calculé : l'outil le calcule.", "Total agrégé : l'outil le calcule à ce niveau.",
                                            "Valeur vide.") for l in a.lignes if l.action == "ignore"))

    def test_valeurs_ecrites_dans_l_export(self):
        p = E.Parametres.depuis({"presentation": "base", "exercices": ["courant"]})
        lignes = list(load_workbook(io.BytesIO(E.exporter(self.admin, p).content))["Valeurs"].iter_rows(values_only=True))
        t = lignes[0]
        par = {(l[t.index("ID KPI")], l[t.index("Organisation")]): l for l in lignes[1:]}
        v, na, com = t.index("Valeur"), t.index("N/A"), t.index("Commentaire")
        self.assertEqual(par[("TX", "E1")][v], 12.345)  # fraction 0,12345 écrite de 0 à 100
        self.assertEqual((par[("TX", "E2")][v], par[("TX", "E2")][na], par[("TX", "E2")][com]), (None, "Oui", "Pas de salariés"))
        self.assertEqual(par[("NRJ", "E1")][v], 1234.5678)
        self.assertEqual(par[("NRJ", "E2")][v], -12.5)
        self.assertEqual(par[("NRJ", "Pays")][v], 1222.0678)  # agrégat (somme avec une valeur négative)
        self.assertEqual(par[("POL", "E1")][v], "Oui")
        self.assertEqual(par[("POL", "Pays")][v], "Oui : 1 · Non : 1")  # décompte
        self.assertEqual(par[("CERT", "E1")][v], "ISO 50001")
        self.assertEqual(par[("CERT", "Pays")][v], None)  # E2 sans réponse : décompte incomplet

    def test_csv_francais_et_international_relus_tels_quels(self):
        for style, separateur in (("fr", ";"), ("intl", ",")):
            p = E.Parametres.depuis({"presentation": "base", "format": "csv", "csv": style, "exercices": ["2026"]})
            contenu = E.exporter(self.admin, p).content
            texte = contenu.decode("utf-8-sig")
            lignes = list(csv.reader(io.StringIO(texte), delimiter=separateur))
            t = lignes[0]
            nrj = next(l for l in lignes if l[t.index("ID KPI")] == "NRJ" and l[t.index("Organisation")] == "E1")
            self.assertEqual(nrj[t.index("Valeur")], "1234,5678" if style == "fr" else "1234.5678")
            a = I.analyser(self.admin, SimpleUploadedFile(f"base-{style}.csv", contenu))
            self.assertFalse(a.erreur, style)
            self.assertEqual(self.actions(a), ["ignore", "inchange"], style)

    def test_export_en_anglais_relu_tel_quel(self):
        p = E.Parametres.depuis({"presentation": "base", "exercices": ["courant"], "langue": "en"})
        contenu = E.exporter(self.admin, p).content
        ws = load_workbook(io.BytesIO(contenu))["Values"] if "Values" in load_workbook(io.BytesIO(contenu)).sheetnames else None
        self.assertIsNotNone(ws)
        lignes = list(ws.iter_rows(values_only=True))
        t = lignes[0]
        pol = next(l for l in lignes if l[t.index("KPI ID")] == "POL" and l[t.index("Organisation")] == "E1")
        self.assertEqual(pol[t.index("Value")], "Yes")
        a = I.analyser(self.admin, SimpleUploadedFile("base-en.xlsx", contenu))
        self.assertEqual(self.actions(a), ["ignore", "inchange"])

    def test_fichier_a_remplir_modifie_puis_applique(self):
        wb = load_workbook(io.BytesIO(I.modele(self.contrib, self.c, I.lignes_modele(self.contrib, self.c)).content))
        ws = wb["Saisie"]
        n = next(r for r in range(1, 15) if ws.cell(r, 2).value == "ID KPI")
        tete = [c.value for c in ws[n]]
        col = {nom: tete.index(nom) + 1 for nom in ("Valeur", "Commentaire")}
        rangs = {ws.cell(r, 2).value: r for r in range(n + 1, ws.max_row + 1) if ws.cell(r, 2).value}
        self.assertEqual(set(rangs), {"EFF", "TX", "POL", "CERT", "NRJ"})
        ws.cell(rangs["TX"], col["Valeur"]).value = 40
        ws.cell(rangs["POL"], col["Valeur"]).value = "Non"
        ws.cell(rangs["CERT"], col["Valeur"]).value = "iso 14001"
        ws.cell(rangs["NRJ"], col["Valeur"]).value = "1 000,25"
        ws.cell(rangs["NRJ"], col["Commentaire"]).value = None  # vide : le commentaire existant est gardé
        flux = io.BytesIO()
        wb.save(flux)
        a, n_ecrites, avertissements = I.appliquer(self.contrib, SimpleUploadedFile("rempli.xlsx", flux.getvalue()), "rempli.xlsx")
        self.assertEqual((n_ecrites, avertissements), (4, []))
        self.assertEqual(self.valeur(self.taux, self.e1).valeur, D("0.4"))
        self.assertEqual(self.valeur(self.pol, self.e1).texte, "Non")
        self.assertEqual(self.valeur(self.cert, self.e1).texte, "ISO 14001")
        r = self.valeur(self.nrj, self.e1)
        self.assertEqual((r.valeur, r.commentaire, r.statut, r.saisi_par), (D("1000.25"), "Relevé", Reponse.Statut.BROUILLON, self.contrib))
        self.assertEqual(self.valeur(self.nrj, self.p).valeur, D("987.75"))  # agrégat recalculé à la fin du lot
        self.assertEqual(self.valeur(self.pol, self.p).texte, "Non : 2")


class ImportValeursTests(Base):
    ENTETE = ["ID KPI", "Organisation", "Exercice", "Valeur", "N/A", "Commentaire"]

    def analyser(self, *lignes, utilisateur=None, **kw):
        return I.analyser(utilisateur or self.admin, fichier([self.ENTETE, *lignes], **kw))

    def test_formes_d_ecriture_des_nombres_et_pourcentages(self):
        a = self.analyser(["NRJ", "E1", 2026, "1 234,5", "", ""], ["NRJ", "E2", 2026, "1,234.5", "", ""],
                          ["TX", "E1", 2026, "35 %", "", ""], ["TX", "E2", 2026, 35, "", ""], ["EFF", "E2", 2026, 40.0, "", ""])
        self.assertEqual([(l.kpi_id, l.action, l.valeur) for l in a.lignes],
                         [("NRJ", "modifier", D("1234.5")), ("NRJ", "modifier", D("1234.5")), ("TX", "modifier", D("0.35")),
                          ("TX", "modifier", D("0.35")), ("EFF", "inchange", D(40))])

    def test_pourcentage_hors_bornes_et_valeurs_non_numeriques_rejetees(self):
        a = self.analyser(["TX", "E1", 2026, 101, "", ""], ["TX", "E2", 2026, -1, "", ""], ["NRJ", "E1", 2026, "12 kWh", "", ""],
                          ["NRJ", "E2", 2026, "1000000000000000", "", ""])
        self.assertEqual([l.action for l in a.lignes], ["rejet"] * 4)
        self.assertEqual([l.motif for l in a.lignes], ["Saisissez un pourcentage de 0 à 100."] * 2 + [
            "« 12 kWh » n'est pas un nombre. Saisissez le nombre seul, sans unité ni texte.", "Ce nombre est trop grand : 15 chiffres au plus avant la virgule."])

    def test_pourcentage_tape_avec_le_signe_dans_excel(self):
        # « 35 % » tapé dans une cellule Excel est rangé par Excel en 0,35 (format pourcentage) : lu 35 %
        a = self.analyser(["TX", "E1", 2026, 0.35, "", ""], formats={(2, 4): "0%"})
        self.assertEqual(a.lignes[0].valeur, D("0.35"))

    def test_na_par_la_colonne_ou_par_la_valeur(self):
        a = self.analyser(["NRJ", "E1", 2026, "", "Oui", "Compteur absent"], ["NRJ", "E2", 2026, "N/A", "", ""],
                          ["EFF", "E2", 2026, 40, "x", ""], ["TX", "E2", 2026, "", "Oui", ""])
        self.assertEqual([(l.na, l.action) for l in a.lignes], [(True, "modifier"), (True, "modifier"), (True, "modifier"),
                                                                (True, "inchange")])  # TX de E2 : déjà N/A, commentaire gardé

    def test_oui_non_et_liste_dans_les_deux_langues(self):
        a = self.analyser(["POL", "E1", 2026, "Yes", "", ""], ["POL", "E2", 2026, "yes", "", ""], ["CERT", "E1", 2026, "ISO 50001", "", ""],
                          ["CERT", "E2", 2026, "ISO 9001", "", ""], ["POL", "E1", 2025, "", "", ""])
        self.assertEqual([(l.action, l.texte) for l in a.lignes[:4]], [("inchange", "Oui"), ("modifier", "Oui"), ("inchange", "ISO 50001"),
                                                                       ("rejet", "")])
        self.assertEqual(a.lignes[3].motif, "Choisissez une des valeurs : ISO 14001, ISO 50001, Aucune.")
        self.assertEqual((a.lignes[4].action, a.lignes[4].motif), ("ignore", "Valeur vide."))

    def test_lignes_ignorees_et_rejetees_nommees(self):
        a = self.analyser(["DBL", "E1", 2026, 5, "", ""], ["EFF", "Pays", 2026, 5, "", ""], ["XXX", "E1", 2026, 5, "", ""],
                          ["EFF", "Inconnue", 2026, 5, "", ""], ["EFF", "E1", 2030, 5, "", ""], ["EFF", "E2", 2026, 41, "", ""],
                          ["EFF", "E2", 2026, 42, "", ""], ["", "", "", "", "", ""])
        self.assertEqual([(l.action, l.motif) for l in a.lignes], [
            # KPI calculé d'une période ouverte, importé par l'administrateur : valeur forcée, après confirmation
            ("forcer", "KPI calculé : la valeur importée remplacera le résultat du calcul, comme valeur forcée."),
            ("ignore", "Total agrégé : l'outil le calcule à ce niveau."),
            ("rejet", "KPI inconnu : « XXX »."),
            ("rejet", "Organisation inconnue : « Inconnue ». Un administrateur peut ajouter ce libellé dans Administration › Organisations."),
            ("rejet", "Aucune campagne pour 2030."),
            ("modifier", ""),
            ("rejet", "Doublon de la ligne 7."),
        ])  # la ligne vide n'est pas comptée

    def test_alias_d_organisation(self):
        a = self.analyser(["EFF", "Entité numéro 1", 2026, 110, "", ""])
        self.assertEqual((a.lignes[0].org, a.lignes[0].action), (self.e1, "inchange"))

    def test_contributeur_limite_a_ses_cases_et_aux_campagnes_ouvertes(self):
        a = self.analyser(["EFF", "E1", 2026, 111, "", ""], ["EFF", "E2", 2026, 41, "", ""], ["EFF", "E1", 2025, 99, "", ""],
                          utilisateur=self.contrib)
        self.assertEqual([l.action for l in a.lignes], ["modifier", "rejet", "rejet"])
        self.assertEqual(a.lignes[1].motif, "Cette cellule n'est pas dans votre périmètre.")

    def test_historique_d_un_exercice_cloture_par_l_admin(self):
        a, n, _ = I.appliquer(self.admin, fichier([self.ENTETE, ["EFF", "E2", 2025, "38", "", "Reprise"], ["TX", "E1", 2025, 30, "", ""]]))
        self.assertEqual(n, 2)
        r = self.valeur(self.eff, self.e2, self.c0)
        self.assertEqual((r.valeur, r.statut, r.origine, r.commentaire), (D(38), Reponse.Statut.VALIDE, Reponse.Origine.IMPORT, "Reprise"))
        self.assertEqual(self.valeur(self.taux, self.e1, self.c0).valeur, D("0.3"))
        self.assertEqual(self.valeur(self.eff, self.p, self.c0).valeur, D(138))  # agrégat de l'historique recalculé
        # une valeur saisie dans l'outil sur l'exercice clôturé ne s'écrase pas par import
        Reponse.objects.filter(pk=r.pk).update(origine=Reponse.Origine.SAISIE)
        a = self.analyser(["EFF", "E2", 2025, 39, "", ""])
        self.assertEqual((a.lignes[0].action, a.lignes[0].motif), ("rejet", "Valeur saisie dans l'outil. Pour la modifier, rouvrez la campagne."))

    def test_import_valide_d_un_coup_et_signale_les_refus(self):
        a, n, avertissements = I.appliquer(self.admin, fichier([self.ENTETE, ["NRJ", "E1", 2026, 5, "", ""], ["TX", "E2", 2026, "", "Oui", ""]]),
                                           valider=True)
        self.assertEqual(self.valeur(self.nrj, self.e1).statut, Reponse.Statut.VALIDE)
        self.assertEqual(n, 1)  # TX de E2 : inchangé (déjà N/A)
        self.assertEqual(avertissements, [])

    def test_en_tetes_manquants(self):
        a = I.analyser(self.admin, fichier([["Code", "Nom"], ["EFF", "E1"]]))
        self.assertTrue(a.erreur.startswith("Colonnes introuvables"))
        a = I.analyser(self.admin, SimpleUploadedFile("x.pdf", b"%PDF-1.4"))
        self.assertEqual(a.erreur, "Formats acceptés : Excel (.xlsx) ou CSV (.csv).")
        a = I.analyser(self.admin, SimpleUploadedFile("x.xlsx", b"pas un classeur"))
        self.assertEqual(a.erreur, "L'outil ne peut pas lire ce fichier Excel. Enregistrez-le au format .xlsx, puis réessayez.")
        a = I.analyser(self.admin, SimpleUploadedFile("x.txt", "ID KPI;Organisation;Exercice;Valeur\nEFF;E2;2026;40".encode("cp1252")))
        self.assertEqual((a.erreur, [l.action for l in a.lignes]), ("", ["inchange"]))  # .txt lu comme un CSV

    def test_csv_d_encodage_inconnu(self):
        # un .csv qui n'est ni en UTF-8 ni en Windows-1252 (octets 0x81, 0x8D…) donne « fichier illisible », sans planter
        a = I.analyser(self.admin, SimpleUploadedFile("x.csv", b"\x81\x8d\x8f;\x90"))
        self.assertTrue(a.erreur)
