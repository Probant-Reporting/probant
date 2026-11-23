"""Paquets référentiels : export Excel et JSON, réimportation sans différence, import dans une autre installation (niveaux,
réglages), conflits de codes (réutiliser, renommer, ignorer), nouvelle version (ajouts, modifications, retraits, thèmes),
modèle « système existant », bibliothèque fournie, composition « lego », jeu d'essai à trois niveaux dans une base vide, pages."""
import copy
import io
import json
import uuid
from decimal import Decimal
from io import StringIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from openpyxl import load_workbook

from parametres import niveaux as N
from parametres import referentiel as PR
from parametres.models import NiveauHierarchique, TypeSaisie, Unite
from referentiel.composition import copier_theme
from referentiel.models import KPI, ElementReferentiel, KPIFormule, Referentiel, Theme

from . import paquets as P
from .models import Journal, RegleCoherence
from .aides_tests.paquets import Base, fichier, kp, vider
from .aides_tests.bibliotheque_essai import BibliothequeEssai

D = Decimal
FETCH = {"HTTP_X_REQUESTED_WITH": "fetch"}


class ExportReimportTests(Base):
    def test_extraction_avec_sources_de_formules(self):
        p = P.extraire(self.r1)
        self.assertEqual([k["code"] for k in p.kpis], ["C", "A", "B", "D", "Q", "FE1"])  # ordre de l'arbre (thème, puis sous-thèmes)
        self.assertIsNone(p.kpis[-1]["element"])  # source de formule : au catalogue, sans place dans le référentiel
        a = kp(p, "A")
        self.assertEqual(a["element"], {"theme": "ELEC", "ordre": 1, "libelle": {}, "obligatoire": True})
        self.assertEqual(a["libelle"], {"fr": "Électricité", "en": "Electricity"})
        self.assertEqual(a["descriptions"], {"fr": {"description": "Électricité consommée.", "source": "Factures."}})
        self.assertEqual([t["code"] for t in p.themes], ["ENERGIE", "ELEC", "CLIMAT"])
        self.assertEqual([r["nom"] for r in p.regles], ["A ≤ B"])
        self.assertEqual(p.referentiel["identifiant"], str(self.r1.identifiant))

    def test_reimport_excel_et_json_sans_aucune_difference(self):
        p = P.extraire(self.r1)
        for relu in (P.lire(fichier(p)), P.depuis_json(P.vers_json(p))):
            a = P.analyser(relu)
            self.assertEqual(a.erreur, "")
            self.assertEqual((a.mode, a.existant), ("mise_a_jour", self.r1))
            self.assertTrue(a.aucune_difference, (a.compteurs, a.referentiel_differences, a.reglages_crees, a.themes_a_ecrire))
        avant = Journal.objects.count()
        res = P.appliquer(self.admin, a)
        self.assertEqual((res.kpis_crees, res.kpis_modifies, res.elements, res.themes, res.reglages, res.regles), (0, 0, 0, 0, 0, 0))
        self.assertEqual(list(Journal.objects.values_list("action", flat=True)[:Journal.objects.count() - avant]), ["import_paquet"])

    def test_meme_code_autre_referentiel_propose_un_nouveau_code(self):
        p = P.extraire(self.r1)
        p.referentiel.update(identifiant=str(uuid.uuid4()), nom={"fr": "Autre référentiel"})
        a = P.analyser(p)
        self.assertEqual((a.mode, a.candidat, a.reconnu), ("nouveau", self.r1, False))
        self.assertNotEqual(a.code, "R1")
        self.assertEqual(P.analyser(p, {"mode": "mise_a_jour"}).existant, self.r1)  # on peut choisir de le mettre à jour
        self.assertEqual(P.analyser(p, {"mode": "nouveau", "code": "R1"}).erreur, "Le code « R1 » existe déjà : en choisir un autre.")


class FichiersHarmonisesTests(Base):
    """Fichier référentiel et classeur de configuration : mêmes en-têtes, mêmes valeurs ; en anglais ; anciens fichiers."""

    def classeur(self, langue=None):
        flux = io.BytesIO()
        P.classeur(P.extraire(self.r1), langue=langue).save(flux)
        return load_workbook(io.BytesIO(flux.getvalue()))

    @staticmethod
    def relire(wb, nom="r1.xlsx"):
        flux = io.BytesIO()
        wb.save(flux)
        flux.seek(0)
        flux.name = nom
        return P.analyser(P.lire(flux))

    def test_memes_colonnes_et_memes_valeurs_que_la_configuration(self):
        from . import configuration as C

        ref = self.classeur()
        self.assertEqual(ref.sheetnames[:3], ["À lire", "Référentiel", "Thèmes"])
        conf = load_workbook(io.BytesIO(C.exporter().content))

        def table(ws):
            tete = [c.value for c in ws[1]]
            return tete, {r[0]: dict(zip(tete, r)) for r in ws.iter_rows(min_row=2, values_only=True) if r[0]}
        tr, kr = table(ref["KPI"])
        tc, kc = table(conf["KPI"])
        self.assertEqual(tr[:9], ["ID KPI", "Nom (FR)", "Thème", "Type de saisie", "Type de réponse", "Unité", "Granularité",
                                  "Agrégation", "Formule"])
        communes = [t for t in tr if t in tc]
        self.assertGreater(len(communes), 15)
        self.assertEqual({(k, t): kr[k][t] or "" for k in kr for t in communes}, {(k, t): kc[k][t] or "" for k in kr for t in communes})
        self.assertEqual(kr["FE1"]["Granularité"], "Groupe")  # le nom du niveau, jamais son code (« Group »)
        self.assertEqual(kr["FE1"]["Type de saisie"], TypeSaisie.objects.get(pk="FE").libelle)
        ws = ref["KPI"]
        self.assertEqual(ws.cell(1, 1).fill.fgColor.rgb[-6:], "BDBDBD")  # clé grise
        self.assertTrue(ws.column_dimensions[ws.cell(1, 12).column_letter].hidden)  # colonnes avancées repliées
        self.assertEqual(ref["Thèmes"].cell(1, 1).value, "Code")
        self.assertEqual(ref["Thèmes"].cell(2, 1).fill.fgColor.rgb[-6:], "EDEDED")  # code du thème en gris

    def test_en_anglais_relu_sans_difference(self):
        from . import configuration as C

        wb = self.classeur("en")
        self.assertEqual(wb.sheetnames[:4], ["Read me", "Framework", "Themes", "KPI"])
        self.assertEqual([c.value for c in wb["KPI"][1]][:3], ["KPI ID", "Name (FR)", "Theme"])
        self.assertTrue(self.relire(wb).aucune_difference)
        conf = C.exporter(langue="en")
        self.assertIn("Full-configuration_", conf["Content-Disposition"])
        a = C.analyser(SimpleUploadedFile("conf.xlsx", conf.content))
        self.assertEqual({c.action for cs in a.onglets.values() for c in cs}, {"inchange"})

    def test_anciens_en_tetes_et_codes_toujours_lus(self):
        wb = self.classeur()
        ws = wb["KPI"]
        tete = [c.value for c in ws[1]]
        ws.cell(1, tete.index("ID KPI") + 1, "Code")  # ancien en-tête
        for r in range(2, ws.max_row + 1):  # anciennes valeurs : codes des niveaux, types et unités
            k = KPI.objects.get(pk=ws.cell(r, 1).value)
            ws.cell(r, tete.index("Granularité") + 1, k.granularite_id)
            ws.cell(r, tete.index("Type de saisie") + 1, k.type_saisie_id)
            ws.cell(r, tete.index("Type de réponse") + 1, k.type_reponse_id)
        wb["Référentiel"]["B2"] = "Paquet référentiel 1"
        a = self.relire(wb)
        self.assertTrue(a.aucune_difference, (a.compteurs, [(l.code, l.statut, l.motif) for l in a.kpis]))


class AutreInstallationTests(Base):
    def test_base_vide_recree_le_referentiel_a_l_identique(self):
        p = P.extraire(self.r1)
        brut = fichier(p).getvalue()
        vider()
        relu = P.lire(SimpleUploadedFile("paquet.xlsx", brut))
        a = P.analyser(relu, source="paquet.xlsx")
        self.assertEqual((a.erreur, a.mode, a.code), ("", "nouveau", "R1"))
        self.assertEqual(a.compteurs["nouveau"], 6)
        self.assertEqual({r.code_local for r in a.reglages_crees}, {"kWh", "kgCO2e", "OuiNon"})  # types et catégories : ceux de l'installation
        res = P.appliquer(self.admin, a, "paquet.xlsx")
        r1 = res.referentiel
        self.assertEqual((r1.origine, r1.version, str(r1.identifiant)), (Referentiel.Origine.IMPORTE, "1.0", p.referentiel["identifiant"]))
        self.assertIn("paquet.xlsx", r1.provenance)
        apres = P.extraire(r1)
        for champ in ("themes", "kpis", "regles"):
            self.assertEqual(getattr(apres, champ), getattr(p, champ), champ)
        self.assertFalse(ElementReferentiel.objects.filter(kpi_id="FE1").exists())
        self.assertEqual(set(KPIFormule.objects.values_list("kpi_calcule_id", "kpi_source_id")), {("C", "A"), ("C", "B"), ("D", "A"), ("D", "FE1")})
        self.assertEqual(KPI.objects.get(pk="Q").choix_traduits("en"), [("Oui", "Yes"), ("Non", "No")])

    def test_niveaux_relies_par_code_nom_ou_position_et_choisis(self):
        p = P.extraire(self.r1)
        p.niveaux = [{"code": "Holding", "rang": 1, "nom": {"fr": "Holding"}}, {"code": "Filiale", "rang": 2, "nom": {"fr": "Pays"}},
                     {"code": "Usine", "rang": 3, "nom": {"fr": "Usine"}}]
        for k in p.kpis:
            k["granularite"] = {"Q": "Filiale", "FE1": "Holding"}.get(k["code"], "Usine")
            k["code"], k["formule"] = "N" + k["code"], k["formule"].replace("[", "[N")
        p.regles = []
        p.referentiel["identifiant"], p.referentiel["code"] = str(uuid.uuid4()), "R2"
        a = P.analyser(p)
        self.assertEqual([(n["code"], local, motif) for n, local, motif, _ in a.niveaux],
                         [("Holding", "", "automatique"), ("Filiale", "Country", "même nom"), ("Usine", "", "automatique")])
        niveaux = {l.code: l.cible.granularite_id for l in a.kpis}
        self.assertEqual((niveaux["NA"], niveaux["NFE1"], niveaux["NQ"], niveaux["NC"]), ("Site", "Group", "Country", "Site"))
        a = P.analyser(p, {"niveau:Filiale": "Entity", "niveau:Holding": "Group", "niveau:Usine": "Entity"})
        niveaux = {l.code: l.cible.granularite_id for l in a.kpis}
        self.assertEqual((niveaux["NA"], niveaux["NFE1"], niveaux["NQ"]), ("Entity", "Group", "Entity"))
        a = P.analyser(p, {"niveau:Filiale": "auto"})
        self.assertEqual(next(l for l in a.kpis if l.code == "NQ").cible.granularite_id, "Site")

    def test_reglages_repris_par_comportement_ou_crees(self):
        p = P.extraire(self.r1)
        p.types_saisie = [dict(t, code={"Saisi": "Input", "Calculé": "Calc", "FE": "Param"}[t["code"]],
                               libelle={"en": t["code"]}) for t in p.types_saisie]
        for k in p.kpis:
            k["type_saisie"] = {"Saisi": "Input", "Calculé": "Calc", "FE": "Param"}[k["type_saisie"]]
            k["code"] = "X" + k["code"]
            k["formule"] = k["formule"].replace("[", "[X")
        p.regles = []
        p.unites.append({"code": "GWhc", "symbole": {"fr": "GWhc"}, "libelle": {}, "entier": False, "decimales": 1, "famille": "Énergie"})
        kp(p, "XB")["unite"] = "GWhc"
        p.referentiel["identifiant"], p.referentiel["code"] = str(uuid.uuid4()), "R2"
        a = P.analyser(p)
        repris = {(r.genre, r.code): (r.action, r.code_local) for r in a.reglages}
        self.assertEqual(repris[("type_saisie", "Input")], ("repris", "Saisi"))
        self.assertEqual(repris[("type_saisie", "Param")], ("repris", "FE"))
        self.assertEqual(repris[("unite", "GWhc")], ("cree", "GWhc"))
        self.assertEqual(a.compteurs["rejet"], 0)
        P.appliquer(self.admin, a)
        self.assertEqual(KPI.objects.get(pk="XB").unite_id, "GWhc")
        self.assertEqual(KPI.objects.get(pk="XC").formule, "[XA] + [XB]")


class ConflitsTests(Base):
    def paquet_r2(self):
        p = P.extraire(self.r1)
        p.referentiel.update(identifiant=str(uuid.uuid4()), code="R2", nom={"fr": "Référentiel deux"})
        return p

    def test_identique_reutilise_sans_conflit(self):
        a = P.analyser(self.paquet_r2())
        self.assertEqual(a.mode, "nouveau")
        self.assertEqual({l.statut for l in a.kpis}, {"inchange"})
        res = P.appliquer(self.admin, a)
        self.assertEqual((res.kpis_crees, res.elements), (0, 5))
        self.assertEqual(set(ElementReferentiel.objects.filter(referentiel_id="R2").values_list("kpi_id", flat=True)), {"A", "B", "C", "D", "Q"})
        self.assertEqual(RegleCoherence.objects.count(), 1)  # même règle : pas de doublon

    def test_conflit_reutiliser_renommer_ignorer(self):
        p = self.paquet_r2()
        kp(p, "B")["libelle"] = {"fr": "Gaz naturel"}  # B diffère
        kp(p, "D")["formule"] = "[A] * [FE1] / 1000"  # D aussi
        p.regles[0]["droite"] = "[B] * 2"  # règle de même nom, autre contenu
        a = P.analyser(p)
        conflits = {l.code: l for l in a.kpis_statut("conflit")}
        self.assertEqual(set(conflits), {"B", "D"})
        self.assertEqual(conflits["B"].choix, "reutiliser")
        self.assertIn(("Nom (FR)", "Gaz", "Gaz naturel"), conflits["B"].differences)
        self.assertEqual([o for o, _ in conflits["B"].options], ["reutiliser", "renommer", "ignorer"])
        a = P.analyser(p, {"kpi:B": "renommer", "code:B": "B2", "kpi:D": "ignorer"})
        self.assertEqual(a.renommages, {"B": "B2"})
        c = next(l for l in a.kpis if l.code == "C")
        self.assertEqual(c.statut, "conflit")  # sa formule pointe maintenant vers B2 : elle diffère de celle de l'installation
        res = P.appliquer(self.admin, P.analyser(p, {"kpi:B": "renommer", "code:B": "B2", "kpi:D": "ignorer", "kpi:C": "renommer",
                                                     "code:C": "C2"}))
        self.assertEqual(res.kpis_crees, 2)
        self.assertEqual(KPI.objects.get(pk="B2").libelle, "Gaz naturel")
        self.assertEqual(KPI.objects.get(pk="B").libelle, "Gaz")  # l'existant ne bouge pas
        self.assertEqual(KPI.objects.get(pk="C2").formule, "[A] + [B2]")
        r2 = set(ElementReferentiel.objects.filter(referentiel_id="R2").values_list("kpi_id", flat=True))
        self.assertEqual(r2, {"A", "B2", "C2", "Q"})  # D ignoré
        regle = RegleCoherence.objects.exclude(nom="A ≤ B").get()
        self.assertEqual((regle.nom, regle.droite), ("A ≤ B (R2)", "[B2] * 2"))

    def test_code_a_la_casse_pres(self):
        p = self.paquet_r2()
        kp(p, "A")["code"] = "a"
        kp(p, "C")["formule"] = "[a] + [B]"
        kp(p, "D")["formule"] = "[a] * [FE1]"
        p.regles = []
        a = P.analyser(p)
        l = next(x for x in a.kpis if x.code == "a")
        self.assertEqual((l.statut, l.choix, l.code_final), ("conflit", "reutiliser", "A"))
        self.assertIn("casse", l.motif)
        self.assertEqual(next(x for x in a.kpis if x.code == "C").statut, "inchange")  # [a] relu comme [A]
        P.appliquer(self.admin, a)
        self.assertTrue(ElementReferentiel.objects.filter(referentiel_id="R2", kpi_id="A").exists())
        self.assertFalse(KPI.objects.filter(code="a").exists())

    def test_formules_rejetees_en_cascade(self):
        p = self.paquet_r2()
        c = kp(p, "C")
        p.kpis.append(dict(copy.deepcopy(c), code="E", formule="[INCONNU] * 2"))
        p.kpis.append(dict(copy.deepcopy(c), code="F", formule="[E] + 1"))
        p.kpis.append(dict(copy.deepcopy(c), code="G", formule="[G] + 1"))
        a = P.analyser(p)
        motifs = {l.code: l.motif for l in a.kpis_statut("rejet")}
        self.assertIn("INCONNU", motifs["E"])
        self.assertIn("E", motifs["F"])
        self.assertIn("lui-même", motifs["G"])


class NouvelleVersionTests(Base):
    def test_differences_puis_mise_a_jour(self):
        p = P.extraire(self.r1)
        p.referentiel["version"] = "1.1"
        kp(p, "A")["libelle"] = {"fr": "Électricité achetée", "en": "Electricity"}
        kp(p, "C")["formule"] = "[A] + [B] + [E]"
        kp(p, "C")["element"]["ordre"] = 9
        kp(p, "B")["element"] = None  # B n'est plus dans la nouvelle version (reste source de C)
        p.kpis.insert(4, dict(copy.deepcopy(kp(p, "A")), code="E", libelle={"fr": "Fioul"}, descriptions={},
                              element={"theme": "CHALEUR", "ordre": 1, "libelle": {}, "obligatoire": True}))
        p.kpis = [k for k in p.kpis if k["code"] != "Q"]  # Q retiré
        p.themes.append({"code": "CHALEUR", "parent": "ENERGIE", "nom": {"fr": "Chaleur"}, "ordre": 2})
        p.themes[2]["nom"] = {"fr": "Climat et carbone", "en": "Climate"}
        a = P.analyser(p)
        self.assertEqual((a.mode, a.comparaison_version), ("mise_a_jour", 1))
        self.assertIn(("Version", "1.0", "1.1"), a.referentiel_differences)
        statuts = {l.code: l.statut for l in a.kpis}
        self.assertEqual(statuts, {"A": "modifie", "B": "inchange", "C": "modifie", "D": "inchange", "E": "nouveau", "FE1": "inchange"})
        c = next(l for l in a.kpis if l.code == "C")
        self.assertIn(("Formule", "[A] + [B]", "[A] + [B] + [E]"), c.diff_kpi)
        self.assertIn(("Ordre dans le thème", 3, 9), c.diff_place)
        self.assertEqual([e.kpi_id for e in a.retires], ["B", "Q"])
        self.assertEqual({t["code"]: t["statut"] for t in a.themes}, {"ENERGIE": "inchange", "ELEC": "inchange", "CLIMAT": "modifie",
                                                                       "CHALEUR": "nouveau"})
        self.assertEqual(a.compteurs["ajoute"], 1)
        # sans le demander, rien n'est retiré
        res = P.appliquer(self.admin, a, "v1.1.xlsx")
        self.assertEqual((res.kpis_crees, res.kpis_modifies, res.retires), (1, 2, 0))
        self.r1.refresh_from_db()
        self.assertEqual(self.r1.version, "1.1")
        self.assertTrue(ElementReferentiel.objects.filter(referentiel=self.r1, kpi_id="Q").exists())
        self.assertEqual(KPI.objects.get(pk="A").libelle, "Électricité achetée")
        self.assertEqual(Theme.objects.get(referentiel=self.r1, code="CLIMAT").nom, "Climat et carbone")
        self.assertEqual(Theme.objects.get(referentiel=self.r1, code="CHALEUR").parent.code, "ENERGIE")
        self.assertTrue(Journal.objects.filter(action="reglage_kpi", objet_id="A", champ="Nom (FR)").exists())
        # en le demandant : retirés du référentiel, gardés au catalogue
        a = P.analyser(p, {"retirer_absents": "on"})
        self.assertEqual([e.kpi_id for e in a.retires], ["B", "Q"])
        self.assertEqual(P.appliquer(self.admin, a).retires, 2)
        self.assertFalse(ElementReferentiel.objects.filter(referentiel=self.r1, kpi_id__in=["B", "Q"]).exists())
        self.assertTrue(KPI.objects.filter(code__in=["B", "Q"]).count() == 2)

    def test_garder_l_actuel_et_version_plus_ancienne(self):
        p = P.extraire(self.r1)
        p.referentiel["version"] = "0.9"
        kp(p, "A")["libelle"] = {"fr": "Autre nom"}
        a = P.analyser(p, {"kpi:A": "garder"})
        self.assertEqual(a.comparaison_version, -1)
        P.appliquer(self.admin, a)
        self.assertEqual(KPI.objects.get(pk="A").libelle, "Électricité")
        self.assertEqual(P.comparer_versions("1.10", "1.9"), 1)
        self.assertEqual(P.comparer_versions("1", "1.0"), 0)

    def test_type_de_reponse_fige_si_des_reponses_existent(self):
        from .models import Campagne, Reponse
        from referentiel.models import Organisation

        c = Campagne.objects.create(exercice=2026, referentiel=self.r1)
        site = Organisation.objects.create(nom="Usine", niveau_id="Group")
        Reponse.objects.create(periode=c.periode, kpi_id="Q", organisation=site, texte="Oui")
        p = P.extraire(self.r1)
        q = next(k for k in p.kpis if k["code"] == "Q")
        q.update(type_reponse="Numérique", methode_agregation="Somme")
        a = P.analyser(p)
        self.assertEqual(next(l for l in a.kpis if l.code == "Q").statut, "rejet")


class ModeleSystemeExistantTests(Base):
    def test_modele_rempli_a_la_main(self):
        rep = self.client.get(reverse("parametres:paquet_modele"))
        wb = load_workbook(io.BytesIO(rep.content))
        self.assertIn("Exemple – KPI", wb.sheetnames)
        ws = wb["Référentiel"]
        lignes = {ws.cell(r, 1).value: r for r in range(1, ws.max_row + 1)}
        ws.cell(lignes["Code"], 2, "MAISON")
        ws.cell(lignes["Nom (FR)"], 2, "Reporting maison")
        self.assertEqual(wb.sheetnames, ["À lire", "Référentiel", "KPI", "Exemple – KPI", "Listes"])
        ws = wb["KPI"]
        entetes = [c.value for c in ws[1]]
        self.assertEqual(entetes, ["ID KPI", "Nom (FR)", "Thème", "Unité", "Type de réponse", "Granularité", "Agrégation",
                                   "Description (FR)"])  # 8 colonnes utiles
        ws.cell(1, 9, "Formule")  # toute colonne du fichier complet est aussi lue

        def ligne(**v):
            ws.append([v.get(e, "") for e in entetes + ["Formule"]])
        ligne(**{"ID KPI": "M-1", "Nom (FR)": "Électricité", "Thème": "Énergie", "Unité": "kWhc", "Granularité": "Site",
                 "Description (FR)": "Toute l'électricité."})
        ligne(**{"ID KPI": "M-2", "Nom (FR)": "Électricité x 2", "Thème": "Énergie", "Unité": "kWhc", "Granularité": "Site",
                 "Formule": "[M-1] * 2", "Agrégation": "Somme"})  # formule sans type de saisie : calculé
        ligne(**{"ID KPI": "M-3", "Nom (FR)": "Sans niveau"})
        ligne(**{"ID KPI": "M-4", "Nom (FR)": "Niveau inconnu", "Granularité": "Usine"})
        flux = io.BytesIO()
        wb.save(flux)
        p = P.lire(SimpleUploadedFile("maison.xlsx", flux.getvalue()))
        a = P.analyser(p)
        self.assertEqual((a.erreur, a.mode, a.code), ("", "nouveau", "MAISON"))
        self.assertEqual({l.code: l.statut for l in a.kpis}, {"M-1": "nouveau", "M-2": "nouveau", "M-3": "nouveau", "M-4": "rejet"})
        m3 = next(l for l in a.kpis if l.code == "M-3")
        self.assertEqual((m3.cible.granularite_id, m3.niveau_auto), ("Site", True))  # sans granularité : le niveau le plus bas
        self.assertIn("Granularité « Usine » inconnu(e)", next(l for l in a.kpis if l.code == "M-4").motif)
        self.assertIn(("unite", "kWhc"), [(r.genre, r.code_local) for r in a.reglages_crees])  # unité citée : créée
        P.appliquer(self.admin, a)
        ref = Referentiel.objects.get(code="MAISON")
        self.assertEqual(list(ref.themes.values_list("nom", flat=True)), ["Énergie"])  # thème cité dans l'onglet KPI : créé
        self.assertEqual(KPI.objects.get(pk="M-1").texte_description("description"), "Toute l'électricité.")
        self.assertEqual(KPI.objects.get(pk="M-2").type_saisie_id, "Calculé")
        self.assertFalse(KPI.objects.filter(code__startswith="EX-").exists())  # les exemples ne sont pas importés

    def test_unite_anglaise_citee_creee_traduite(self):
        """Unité anglaise citée seulement dans l'onglet KPI d'un fichier référentiel : créée traduite, comme à l'import
        d'un référentiel (parametres.referentiel.nouvelle_unite) ; son code reste le texte du fichier.
        (« employees » ne sert plus d'exemple : depuis parametres/0036, c'est la traduction anglaise fournie de l'unité
        « salariés », retrouvée au lieu d'être créée en double.)"""
        wb = load_workbook(io.BytesIO(self.client.get(reverse("parametres:paquet_modele")).content))
        ws = wb["Référentiel"]
        lignes = {ws.cell(r, 1).value: r for r in range(1, ws.max_row + 1)}
        ws.cell(lignes["Code"], 2, "MAISON")
        ws.cell(lignes["Nom (FR)"], 2, "Reporting maison")
        ws = wb["KPI"]
        entetes = [c.value for c in ws[1]]
        ws.append([{"ID KPI": "M-1", "Nom (FR)": "Effectif", "Thème": "Social", "Unité": "interns", "Granularité": "Site"}.get(e, "")
                   for e in entetes])
        flux = io.BytesIO()
        wb.save(flux)
        a = P.analyser(P.lire(SimpleUploadedFile("maison.xlsx", flux.getvalue())))
        self.assertIn(("unite", "interns"), [(r.genre, r.code_local) for r in a.reglages_crees])
        P.appliquer(self.admin, a)
        u = Unite.objects.get(code="interns")
        self.assertEqual((u.symbole, u.tr("symbole", "en"), u.tr("symbole", "es")), ("stagiaires", "interns", "becarios"))
        self.assertEqual(KPI.objects.get(pk="M-1").unite_id, "interns")

    def test_classeur_de_configuration_refuse_avec_un_message(self):
        from . import configuration as C

        flux = io.BytesIO()
        C.classeur().save(flux)
        with self.assertRaisesMessage(P.PaquetInvalide, "classeur de configuration"):
            P.lire(SimpleUploadedFile("configuration.xlsx", flux.getvalue()))


class BibliothequeTests(BibliothequeEssai, TestCase):
    def test_fichiers_a_jour(self):
        err = StringIO()
        try:
            call_command("bibliotheque", verifier=True, stdout=StringIO(), stderr=err)
        except SystemExit:
            self.fail(err.getvalue())

    def test_socles_installes_dans_une_base_neuve_puis_a_jour(self):
        fournis = P.bibliotheque()
        self.assertEqual([f.paquet.code for f in fournis], [
            "ESRS_2",
            "ESRS_E1",
            "ESRS_E2",
            "ESRS_E3",
            "ESRS_E4",
            "ESRS_E5",
            "ESRS_G1",
            "ESRS_S1",
            "ESRS_S2",
            "ESRS_S3",
            "ESRS_S4",
            "SOCLE_ENERGIE",
            "SOCLE_ESRS",
            "SOCLE_GES",
            "SOCLE_SOCIAL",
            "TRANSPARENCE_REMU",
            "VS_BASE",
            "VS_COMPLET",
        ])
        for f in fournis:
            a = P.analyser(f.paquet, source=f.nom_fichier, fourni=True)
            self.assertEqual(a.erreur, "")
            self.assertEqual((a.compteurs["rejet"], a.compteurs["conflit"]), (0, 0), f.nom_fichier)
            P.appliquer(None, a)
        self.assertEqual({f.etat for f in P.bibliotheque()}, {"a_jour"})
        ges = Referentiel.objects.get(code="SOCLE_GES")
        self.assertEqual((ges.origine, ges.version), (Referentiel.Origine.FOURNI, "1.0"))
        # Énergie, GES, ESRS simplifié, VS, ESRS E1 : un seul KPI
        self.assertEqual(ElementReferentiel.objects.filter(kpi_id="NRJ-ELEC").count(), 5)
        for f in P.bibliotheque():
            self.assertTrue(P.analyser(f.paquet, fourni=True).aucune_difference)
        # modèles sans niveau (arbre par défaut : Groupe › Pays › Entité › Site) : saisis en bas, facteurs en haut (électricité : Pays), calculés
        # au niveau de leurs sources
        niveaux = dict(KPI.objects.values_list("code", "granularite_id"))
        for code, attendu in (("NRJ-GAZ", "Site"), ("FE-GAZ", "Group"), ("FE-ELEC", "Country"), ("CONV-FIOUL", "Group"),
                              ("GES-S1-FIXE", "Site"), ("GES-TOTAL", "Group"),  # scope 3 : les quinze catégories pour l'entreprise
                              ("NRJ-MANAGEMENT", "Site"), ("SOC-EFFECTIF", "Site"),
                              ("SOC-TF", "Site"), ("SOC-REMU-NB-F", "Entity"), ("SOC-ECART-MOY-HOR", "Entity"),
                              ("SOC-ECART-DECL-SOUMIS", "Entity")):  # transparence des rémunérations : une réponse par employeur
            self.assertEqual(niveaux[code], attendu, code)
        self.assertEqual(set(RegleCoherence.objects.values_list("niveau_id", flat=True)), {
            "Site",
            "Entity",
            "Group",  # ESRS E1 : parts hors du groupe consolidé, saisies pour l'entreprise
        })

    def test_fichiers_sans_niveaux(self):
        for f in P.bibliotheque():
            d = json.loads((P.BIBLIOTHEQUE / f.nom_fichier).read_text(encoding="utf-8"))
            self.assertEqual(d.get("niveaux") or [], [], f.nom_fichier)
            self.assertFalse(any("granularite" in k for k in d["kpis"]), f.nom_fichier)
            self.assertFalse(any(r.get("niveau") for r in d.get("regles") or []), f.nom_fichier)

    def test_arbre_a_deux_niveaux(self):
        """Holding › Filiale : les KPI saisis à la filiale, les facteurs d'émission à la holding."""
        NiveauHierarchique.objects.all().delete()
        NiveauHierarchique.objects.create(code="Holding", rang=1, nom="Holding", nom_pluriel="Holding")
        NiveauHierarchique.objects.create(code="Filiale", rang=2, nom="Filiale", nom_pluriel="Filiales")
        a = P.analyser(P.fourni("socle_ges.json").paquet, fourni=True)
        self.assertEqual((a.erreur, a.compteurs["rejet"]), ("", 0))
        P.appliquer(None, a)
        niveaux = dict(KPI.objects.values_list("code", "granularite_id"))
        self.assertEqual((niveaux["NRJ-GAZ"], niveaux["FE-GAZ"], niveaux["GES-S1"]), ("Filiale", "Holding", "Filiale"))

    def test_calcule_au_niveau_d_une_source_existante(self):
        """Une source déjà dans l'installation garde son niveau (Entité) : le calculé qui la cite s'y place."""
        P.appliquer(None, P.analyser(P.sous_paquet(P.fourni("socle_ges.json").paquet, codes_kpi=["GES-GAZOLE"])[0], catalogue=True))
        KPI.objects.filter(pk="GES-GAZOLE").update(granularite_id="Entity")
        a = P.analyser(P.fourni("socle_ges.json").paquet, fourni=True)
        lignes = {l.code: l for l in a.kpis}
        self.assertEqual(lignes["GES-GAZOLE"].statut, "inchange")
        self.assertEqual(lignes["GES-S1-MOBILE"].cible.granularite_id, "Entity")
        self.assertEqual(lignes["GES-S1"].cible.granularite_id, "Entity")
        self.assertEqual(lignes["GES-S1-FIXE"].cible.granularite_id, "Site")

    def test_mise_a_jour_disponible(self):
        f = P.fourni("socle_social.json")
        P.appliquer(None, P.analyser(f.paquet, fourni=True))
        Referentiel.objects.filter(code="SOCLE_SOCIAL").update(version="0.9")
        self.assertEqual(P.fourni("socle_social.json").etat, "mise_a_jour")


class CompositionTests(BibliothequeEssai, Base):
    def test_copier_un_theme_sans_recopier_les_kpi(self):
        cible = Referentiel.objects.create(code="TB", nom="Tableau de bord")
        theme, ajoutes, presents = copier_theme(Theme.objects.get(referentiel=self.r1, code="ENERGIE"), cible)
        self.assertEqual((theme.nom, ajoutes, presents), ("Énergie", 3, 0))
        self.assertEqual([t.nom for t in theme.enfants.all()], ["Électricité"])
        self.assertEqual(KPI.objects.count(), 6)
        self.assertEqual(ElementReferentiel.objects.get(referentiel=cible, kpi_id="A").theme.nom, "Électricité")
        _, ajoutes, presents = copier_theme(Theme.objects.get(referentiel=self.r1, code="ELEC"), cible)
        self.assertEqual((ajoutes, presents), (0, 2))  # déjà dans le référentiel cible : pas de doublon

    def test_composer_depuis_un_socle_fourni(self):
        cible = Referentiel.objects.create(code="TB", nom="Tableau de bord")
        f = P.fourni("socle_ges.json")
        ajoutes, presents, crees, rejets = P.composer_depuis_paquet(self.admin, f.paquet, cible, code_theme="SCOPE2")
        self.assertEqual((ajoutes, presents, rejets), (4, 0, []))
        self.assertEqual(crees, 7)  # les 4 KPI et les 3 facteurs d'émission, sources de la formule du scope 2
        self.assertEqual(Theme.objects.get(referentiel=cible).nom, "Scope 2 – énergie achetée")
        self.assertFalse(Referentiel.objects.filter(code="SOCLE_GES").exists())  # le socle lui-même n'est pas installé
        ajoutes, *_ = P.composer_depuis_paquet(self.admin, f.paquet, cible, code_kpi="NRJ-ELEC")
        self.assertEqual(ajoutes, 0)


class JeuTroisNiveauxTests(TestCase):
    """Jeu d'essai à trois niveaux (ancienne seconde démo) : « Tableau de bord direction » composé à partir des deux autres
    référentiels, exporté puis réimporté dans une base vide."""

    def test_composer_exporter_reimporter_dans_une_base_vide(self):
        from .aides_tests import jeu_trois_niveaux as J

        PR.creer_par_defaut()
        J.langues()
        J.niveaux()
        J.referentiel()
        J.kpis()
        J.referentiels()
        J.traductions()
        J.regles()
        direction = J.composer()
        self.assertEqual([t.nom for t in Theme.objects.filter(referentiel=direction, parent=None)],
                         ["Consommations", "Émissions", "Social", "Économie"])
        nb = direction.elements.count()
        self.assertEqual(KPI.objects.count(), len(J.KPIS))  # aucun KPI recopié
        p = P.extraire(direction)
        brut = fichier(p).getvalue()
        vider()
        a = P.analyser(P.lire(SimpleUploadedFile("direction.xlsx", brut)))
        self.assertEqual((a.erreur, a.mode, a.compteurs["rejet"]), ("", "nouveau", 0))
        # Holding et Filiale ne se relient que par la position : rattachement automatique ; Site : même code
        self.assertEqual({n["code"]: local for n, local, _, u in a.niveaux if u}, {"Holding": "", "Filiale": "", "Site": "Site"})
        self.assertEqual(P.analyser(P.lire(SimpleUploadedFile("direction.xlsx", brut)), {"niveau:Filiale": "Entity"}).compteurs["rejet"], 0)
        res = P.appliquer(None, P.analyser(P.lire(SimpleUploadedFile("direction.xlsx", brut)), {"niveau:Filiale": "Entity"}))
        self.assertEqual(res.referentiel.elements.count(), nb)
        self.assertEqual(res.referentiel.tr("nom", "es"), "Cuadro de mando de la dirección")
        self.assertEqual(KPI.objects.get(pk="ENR-01").tr("libelle", "es"), "Electricidad consumida")
        self.assertEqual(KPI.objects.get(pk="ENR-01").granularite_id, "Site")
        self.assertEqual(KPI.objects.get(pk="SOC-01").granularite_id, "Entity")
        self.assertEqual(KPI.objects.get(pk="GES-01").formule, "[ENR-01] * [FE-ELEC]")


class PagesTests(BibliothequeEssai, Base):
    def test_bibliotheque_export_import_et_confirmation(self):
        page = self.client.get(reverse("parametres:bibliotheque"), follow=True)  # ancienne page : « Nouveau référentiel »
        self.assertContains(page, "Gaz à effet de serre")
        self.assertContains(self.client.get(reverse("parametres:referentiel_partage", args=["R1"])),
                            reverse("parametres:paquet_exporter", args=["R1"]))
        rep = self.client.get(reverse("parametres:paquet_exporter", args=["R1"]))
        self.assertEqual(rep["Content-Type"], "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        p = P.lire(SimpleUploadedFile("p.xlsx", rep.content))
        p.referentiel.update(version="2.0")
        kp(p, "A")["libelle"]["fr"] = "Électricité totale"
        flux = fichier(p)
        rep = self.client.post(reverse("parametres:paquet_importer"), {"action": "verifier",
                                                                         "fichier": SimpleUploadedFile("p.xlsx", flux.getvalue())})
        self.assertContains(rep, "Mettre à jour « Référentiel un »")
        self.assertContains(rep, "Version plus récente")
        self.assertContains(rep, "Électricité totale")
        rep = self.client.post(reverse("parametres:paquet_importer"), {"action": "confirmer", "kpi:A": "mettre_a_jour"})
        self.assertContains(rep, "mis à jour, version 2.0")
        self.assertEqual(KPI.objects.get(pk="A").libelle, "Électricité totale")

    def test_niveaux_du_fichier_repris_ou_automatiques(self):
        """Fichier d'une autre installation : niveaux reliés par le code, repris en une ligne ; arbre différent (relié
        seulement par la position) : rattachement automatique, détail replié ; modèle de la bibliothèque : rien sur les niveaux."""
        p = P.extraire(self.r1)
        p.referentiel["code"], p.referentiel["identifiant"] = "R9", str(uuid.uuid4())
        for k in p.kpis:
            k["code"], k["formule"] = "Z" + k["code"], k["formule"].replace("[", "[Z")
        p.regles = []

        def apercu(paquet):
            rep = self.client.post(reverse("parametres:paquet_importer"), {"action": "verifier", "fichier": SimpleUploadedFile(
                "r9.json", P.vers_json(paquet).encode())})
            self.assertEqual(rep.status_code, 200)
            return rep
        rep = apercu(p)
        self.assertContains(rep, "Niveaux de saisie repris du fichier")
        self.assertNotContains(rep, "rattache automatiquement")
        p2 = copy.deepcopy(p)
        p2.niveaux = [{"code": "Holding", "rang": 1, "nom": {"fr": "Holding"}}, {"code": "Usine", "rang": 2, "nom": {"fr": "Usine"}}]
        for k in p2.kpis:
            k["granularite"] = "Holding" if k["code"] == "ZFE1" else "Usine"
        rep = apercu(p2)
        self.assertContains(rep, "Le fichier utilise d'autres niveaux (Holding, Usine)")
        self.assertContains(rep, '<option value="auto" selected>Automatique</option>', html=False)
        rep = self.client.post(reverse("parametres:paquet_importer"), {"action": "apercu", "niveau:Usine": "Entity"})
        self.assertContains(rep, "<details class=\"niveaux-paquet\" open>", html=False)
        rep = self.client.post(reverse("parametres:paquet_importer"), {"action": "confirmer", "niveau:Usine": "Entity"})
        self.assertEqual(KPI.objects.get(pk="ZA").granularite_id, "Entity")
        self.assertEqual(KPI.objects.get(pk="ZFE1").granularite_id, "Group")  # Holding : automatique, paramètre hérité en haut
        rep = self.client.post(reverse("parametres:paquet_importer"), {"action": "verifier", "bibliotheque": "socle_social.json"}, follow=True)
        self.assertNotContains(rep, "Niveaux de saisie")

    def test_fichier_sans_colonne_granularite(self):
        p = P.extraire(self.r1)
        vider()
        for k in p.kpis:
            k.pop("granularite")
        p.niveaux, p.regles = [], []
        a = P.analyser(P.depuis_json(P.vers_json(p)))
        self.assertEqual((a.erreur, a.compteurs["rejet"]), ("", 0))
        self.assertEqual({l.code: l.cible.granularite_id for l in a.kpis},
                         {"A": "Site", "B": "Site", "C": "Site", "D": "Site", "Q": "Site", "FE1": "Group"})

    def test_modele_fourni_en_excel_avec_les_niveaux_de_l_installation(self):
        rep = self.client.get(reverse("parametres:paquet_fourni", args=["socle_ges.json"]))
        p = P.lire(SimpleUploadedFile("ges.xlsx", rep.content))
        self.assertEqual([n["code"] for n in p.niveaux], [n.code for n in N.tous()])
        self.assertFalse(any(k.get("granularite") for k in p.kpis))

    def test_installer_un_socle_depuis_la_bibliotheque(self):
        """Ancien formulaire « Installer… » : mène aux trois écrans (cocher les KPI, résumé, installer)."""
        rep = self.client.post(reverse("parametres:paquet_importer"), {"action": "verifier", "bibliotheque": "socle_social.json"}, follow=True)
        self.assertContains(rep, "Social (modèle)")
        self.assertNotContains(rep, "Niveaux de saisie")
        codes = [k["code"] for k in P.fourni("socle_social.json").paquet.kpis]
        rep = self.client.post(reverse("parametres:installer_kpi", args=["SOCLE_SOCIAL"]), {"action": "continuer", "kpi": codes}, follow=True)
        self.assertNotContains(rep, "Niveaux de saisie")
        rep = self.client.post(reverse("parametres:installer_resume", args=["SOCLE_SOCIAL"]), {"action": "installer", "nom": "Social (modèle)",
                                                                                               "frequence": "annee"})
        self.assertEqual(rep.status_code, 302)
        self.assertEqual(Referentiel.objects.get(code="SOCLE_SOCIAL").origine, Referentiel.Origine.FOURNI)

    def test_composer_par_glisser_deposer(self):
        cible = Referentiel.objects.create(code="TB", nom="Tableau de bord")
        page = self.client.get(reverse("parametres:composer") + "?ref=TB", follow=True)  # ancienne page : contenu du référentiel
        self.assertContains(page, "Référentiel un")
        self.assertContains(page, "Gaz à effet de serre")
        url = reverse("parametres:referentiel_contenu_action", args=["TB"])  # éditeur « Contenu » (glisser-déposer)

        def deposer(**corps):
            return self.client.post(url, json.dumps({"action": "deposer", **corps}), content_type="application/json", **FETCH).json()
        r = deposer(theme="", source={"type": "theme", "ref": "R1", "id": Theme.objects.get(referentiel=self.r1, code="CLIMAT").pk})
        self.assertTrue(r["ok"], r)
        climat = Theme.objects.get(referentiel=cible, code="CLIMAT")
        r = deposer(theme=climat.pk, source={"type": "kpi", "code": "A"})
        self.assertIn("ajouté", r["message"])
        self.assertEqual(ElementReferentiel.objects.get(referentiel=cible, kpi_id="A").theme, climat)
        r = deposer(theme=climat.pk, source={"type": "element", "code": "A"}, avant="D")
        self.assertEqual(list(ElementReferentiel.objects.filter(referentiel=cible, theme=climat).order_by("ordre")
                              .values_list("kpi_id", flat=True)), ["A", "D", "Q"])
        r = deposer(theme="", source={"type": "theme", "bib": "socle_social.json", "id": "FORMATION"})
        self.assertTrue(r["ok"], r)
        self.assertTrue(ElementReferentiel.objects.filter(referentiel=cible, kpi_id="SOC-HEURES-FORM").exists())
        r = deposer(source={"type": "retirer", "code": "A"})
        self.assertFalse(ElementReferentiel.objects.filter(referentiel=cible, kpi_id="A").exists())
        self.assertIn("html", r)
