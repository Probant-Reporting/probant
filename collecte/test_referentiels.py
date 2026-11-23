"""Référentiels multiples : catalogue unique de KPI, plusieurs référentiels qui le partagent (saisie unique), arbre de
thèmes de profondeur libre, filtre par référentiel (saisie, tableau de bord, exports, imports), page Paramètres ›
Référentiels, place du KPI dans la fiche, glisser-déposer dans l'arbre, classeur de configuration."""
import io
import json
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from openpyxl import load_workbook

from referentiel.composition import composer
from referentiel.models import KPI, ElementReferentiel, Niveau, Referentiel, Theme
from referentiel.plans import Plan

from . import configuration as C
from . import exports as E
from . import imports as I
from . import reglages as R
from . import saisie as S
from .models import Campagne, Journal, Reponse
from .outils_tests import xlsx
from .aides_tests.referentiels import Base
from .aides_tests.revue_admin import Base as BaseAdmin
from collecte.outils_tests import html_de
from .aides_tests.bibliotheque_essai import BibliothequeEssai

D = Decimal
FETCH = {"HTTP_X_REQUESTED_WITH": "fetch"}


class CatalogueEtSaisieUniqueTests(Base):
    def test_deux_referentiels_partagent_un_kpi_sans_double_saisie(self):
        S.enregistrer(self.contrib, self.c, self.elec, self.e1, "120", False, "")
        self.assertEqual(Reponse.objects.filter(periode=self.c.periode, kpi=self.elec, organisation=self.e1).count(), 1)
        self.assertEqual(self.c.periode, self.c_nrg.periode)
        for c in (self.c, self.c_nrg):
            lignes = S.lignes(self.admin, c)
            elec = [l for l in lignes if l.kpi.code == "ELEC"]
            self.assertEqual(len(elec), 1)
            self.assertEqual(elec[0].reponse.valeur, D(120))  # la même réponse, visible dans les deux campagnes
            rep = self.client.get(reverse("collecte:saisie") + f"?campagne={c.pk}&org={self.e1.pk}")
            self.assertContains(rep, "Électricité")
        self.assertEqual(sorted(l.kpi.code for l in S.lignes(self.admin, self.c_nrg)), ["ELEC", "NRJ"])
        tous = [l.kpi.code for l in S.lignes(self.admin, self.c, plan=Plan())]
        self.assertEqual(sorted(tous), ["EFF", "ELEC", "NRJ"])  # chaque KPI une fois, GAZ (hors référentiel) non collecté
        self.assertEqual(len(S.cellules(self.admin)), 3)

    def test_regle_de_collecte(self):
        self.assertNotIn("GAZ", set(S.kpis_collectes().values_list("code", flat=True)))
        KPI.objects.create(code="TOT", libelle="Total", type_saisie_id="Calculé", formule="[NRJ] + [GAZ]", granularite_id=Niveau.ENTITY)
        composer({"TOT": ["Environnement"]}, self.rse)
        self.assertIn("GAZ", set(S.kpis_collectes().values_list("code", flat=True)))  # source d'une formule d'un référentiel
        Referentiel.objects.update(actif=False)
        self.assertEqual(set(S.kpis_collectes().values_list("code", flat=True)), {"EFF", "NRJ", "ELEC", "GAZ"})  # tout le catalogue

    def test_referentiel_vide_ne_demande_rien(self):
        """Un référentiel créé mais encore vide ne demande pas tout le catalogue (avant : sa campagne réclamait tous les
        KPI, comptés au tableau de bord et dans les relances), tant qu'un autre référentiel contient des KPI."""
        vide = Referentiel.objects.create(code="VIDE", nom="Vide")
        c = Campagne.objects.create(referentiel=vide, periode=self.c.periode, statut=Campagne.Statut.OUVERTE)
        self.assertEqual(list(S.kpis_collectes(vide)), [])
        self.assertEqual(S.lignes(self.admin, c), [])

    def test_arbre_a_trois_niveaux(self):
        plan = Plan("RSE")
        self.assertEqual(plan.titres("ELEC"), ("Environnement", "Énergie › Électricité"))
        self.assertEqual(plan.titres("NRJ"), ("Environnement", "Énergie"))
        self.assertEqual([(t.nom, prof) for t, prof in plan.arbre(self.rse)],
                         [("Environnement", 0), ("Énergie", 1), ("Électricité", 2), ("Social", 0)])
        self.assertEqual(sorted(["EFF", "ELEC", "NRJ"], key=plan.position), ["NRJ", "ELEC", "EFF"])
        self.assertEqual(Plan().titres("ELEC"), ("Reporting · Environnement", "Énergie › Électricité"))  # plusieurs référentiels
        self.assertEqual(Plan("ENERGIE").decrire("ELEC"),
                         {"referentiel": "Énergie", "theme": "Consommations", "sous_theme": ""})
        self.assertEqual([r.code for r in Plan().referentiels_de("ELEC")], ["RSE", "ENERGIE"])
        t = Theme.objects.get(nom="Environnement")
        t.parent = Theme.objects.get(nom="Électricité")
        with self.assertRaises(Exception):
            t.full_clean()  # un thème ne se range pas sous un de ses sous-thèmes

    def test_tableau_de_bord_par_referentiel_et_selecteur(self):
        S.enregistrer(self.contrib, self.c, self.elec, self.e1, "120", False, "")
        S.valider(self.contrib, self.c, self.elec, self.e1)
        ElementReferentiel.objects.filter(referentiel=self.nrg, kpi=self.nrj).update(obligatoire=False)
        rep = self.client.get(reverse("collecte:tableau_de_bord"))
        taux = {c.referentiel_id: (n.valide, n.total) for c, n in rep.context["avancement"]}
        self.assertEqual(taux, {"RSE": (1, 3), "ENERGIE": (1, 1)})  # NRJ facultatif dans « Énergie » : hors du taux
        self.assertContains(rep, "Campagnes en cours")
        self.assertContains(rep, '<option value="ENERGIE" >Énergie</option>')  # sélecteur Référentiel, puis Période
        rep = self.client.get(reverse("collecte:tableau_de_bord") + f"?campagne={self.c_nrg.pk}")
        self.assertEqual(rep.context["total"].total, 1)  # NRJ facultatif : hors du taux en tête aussi 
        self.assertEqual((rep.context["facultatifs"].valide, rep.context["facultatifs"].total), (0, 1))
        self.assertContains(rep, "KPI facultatifs saisis : 0 / 1")
        self.assertEqual(self.client.session["campagne"], self.c_nrg.pk)  # mémorisée pour les autres pages
        self.assertEqual(self.client.get(reverse("collecte:pour_moi")).context["campagne"], self.c_nrg)

    def test_catalogue_des_kpi(self):
        rep = self.client.get(reverse("collecte:referentiel"))  # tous les KPI, une fois chacun
        self.assertIsNone(rep.context["ref"])
        self.assertEqual(rep.context["nb"], 4)
        rep = self.client.get(reverse("collecte:referentiel") + "?ref=ENERGIE")
        self.assertEqual((rep.context["ref"], rep.context["nb"]), (self.nrg, 2))
        self.assertContains(rep, reverse("parametres:referentiel_contenu", args=["ENERGIE"]))  # ranger : dans le contenu
        rep = self.client.get(reverse("collecte:referentiel") + "?hors=1")
        self.assertEqual([k.code for _, _, _, themes in rep.context["groupes"] for _, _, ss in themes for _, _, ks in ss for k in ks], ["GAZ"])

    def test_attributions_et_coherence_filtrees(self):
        rep = self.client.get(reverse("collecte:admin_attributions") + "?niveau=Entity&ref=ENERGIE")
        self.assertContains(rep, "Électricité")
        self.assertNotContains(rep, "Effectif")
        self.assertEqual(self.client.get(reverse("collecte:coherence") + f"?campagne={self.c_nrg.pk}").status_code, 200)


class EchangesTests(Base):
    def test_export_filtre_par_referentiel(self):
        for k, v in ((self.elec, "120"), (self.eff, "10")):
            S.enregistrer(self.admin, self.c, k, self.e1, v, False, "")
        p = E.Parametres.depuis({"presentation": "base", "referentiel": "ENERGIE"})
        ws = load_workbook(io.BytesIO(E.exporter(self.admin, p).content))["Valeurs"]
        tete = [c.value for c in ws[1]]
        lignes = [dict(zip(tete, r)) for r in ws.iter_rows(min_row=2, values_only=True)]
        self.assertEqual({l["ID KPI"] for l in lignes}, {"ELEC"})  # EFF n'est pas dans « Énergie »
        l = lignes[0]
        self.assertEqual((l["Référentiel"], l["Thème"]), ("Énergie", "Consommations"))
        self.assertNotIn("Code dans le référentiel", l)
        self.assertEqual(E.Parametres.depuis({"referentiel": "INCONNU"}).referentiel, "")
        p = E.Parametres.depuis({"presentation": "base"})
        ws = load_workbook(io.BytesIO(E.exporter(self.admin, p).content))["Valeurs"]
        cles = [(r[tete.index("ID KPI")], r[tete.index("Organisation")]) for r in ws.iter_rows(min_row=2, values_only=True)]
        self.assertEqual({k for k, _ in cles}, {"ELEC", "EFF"})
        self.assertEqual(len(cles), len(set(cles)))  # tous les référentiels : chaque valeur une seule fois (ELEC est dans les deux)

    def test_import_controle_la_colonne_referentiel(self):
        f = xlsx(onglet=None, lignes=[["ID KPI", "Organisation", "Exercice", "Référentiel", "Valeur"],
                  ["ELEC", "E1", 2026, "Énergie", 5], ["EFF", "E1", 2026, "Énergie", 7], ["NRJ", "E1", 2026, "Bidule", 9],
                  ["EFF", "E1", 2026, "Reporting", 8]])
        a = I.analyser(self.admin, f)
        self.assertEqual([(l.kpi_id, l.action) for l in a.lignes], [("ELEC", "creer"), ("EFF", "rejet"), ("NRJ", "rejet"), ("EFF", "creer")])
        self.assertIn("pas dans le référentiel", a.lignes[1].motif)
        self.assertIn("Référentiel inconnu", a.lignes[2].motif)
        rep = self.client.get(reverse("collecte:echanges_modele") + f"?campagne={self.c_nrg.pk}")
        ws = load_workbook(io.BytesIO(rep.content))["Saisie"]
        n = next(r for r in range(1, 15) if ws.cell(r, 2).value == "ID KPI")
        tete = [c.value for c in ws[n]]
        self.assertIn("Référentiel", tete)
        self.assertEqual({r[tete.index("ID KPI")] for r in ws.iter_rows(min_row=n + 1, values_only=True) if r[1]}, {"ELEC", "NRJ"})

    def classeur(self):
        return load_workbook(io.BytesIO(C.exporter().content))

    def envoyer(self, wb):
        flux = io.BytesIO()
        wb.save(flux)
        return SimpleUploadedFile("config.xlsx", flux.getvalue())

    def test_aller_retour_du_classeur(self):
        wb = self.classeur()
        a = C.analyser(self.envoyer(wb))
        self.assertFalse(a.erreur)
        self.assertEqual({c.action for cs in a.onglets.values() for c in cs}, {"inchange"})
        self.assertEqual({n: len(a.onglets[n]) for n in ("Référentiels", "Thèmes", "Éléments")},
                         {"Référentiels": 2, "Thèmes": 5, "Éléments": 5})
        # modifier : EFF entre dans « Énergie », un nouveau thème sous « Consommations », un thème renommé
        th, el = wb["Thèmes"], wb["Éléments"]
        tt, te = [c.value for c in th[1]], [c.value for c in el[1]]
        ligne = dict.fromkeys(tt, "")
        ligne.update({"Référentiel": "ENERGIE", "Code": "Chaleur", "Parent": "Consommations", "Nom (FR)": "Chaleur", "Ordre": 1})
        th.append([ligne[t] for t in tt])
        social = next(r for r in th.iter_rows(min_row=2) if r[tt.index("Code")].value == "Social")
        social[tt.index("Nom (FR)")].value = "Social et sociétal"
        ligne = dict.fromkeys(te, "")
        ligne.update({"Référentiel": "ENERGIE", "ID KPI": "EFF", "Thème": "Chaleur", "Ordre": 3, "Obligatoire": "Non"})
        el.append([ligne[t] for t in te])
        f = self.envoyer(wb)
        a = C.analyser(f)
        changes = {(n, c.cle): c.action for n, cs in a.onglets.items() for c in cs if c.action != "inchange"}
        self.assertEqual(changes, {("Thèmes", "ENERGIE · Chaleur"): "creer", ("Thèmes", "RSE · Social"): "modifier",
                                   ("Éléments", "ENERGIE · EFF"): "creer"})
        f.seek(0)
        C.appliquer(self.admin, f, "config.xlsx")
        e = ElementReferentiel.objects.get(referentiel=self.nrg, kpi=self.eff)
        self.assertEqual((e.theme.nom, e.theme.parent.nom, e.obligatoire), ("Chaleur", "Consommations", False))
        self.assertEqual(Theme.objects.get(code="Social").nom, "Social et sociétal")
        self.assertEqual(KPI.objects.count(), 4)  # une seule fiche par KPI : le catalogue ne double pas

    def test_ancien_classeur_avec_theme_et_sous_theme(self):
        f = xlsx(onglet=None, lignes=[["Code", "Thème", "Sous-thème", "Nom (FR)", "Type de saisie", "Type de réponse", "Granularité", "Agrégation"],
                  ["EAU", "Environnement", "Eau", "Eau consommée", "Saisi", "Numérique", "Entité", "Somme"]])
        f.name = "ancien.xlsx"
        wb = load_workbook(f)
        wb.active.title = "KPI"
        C.appliquer(self.admin, self.envoyer(wb), "ancien.xlsx")
        e = KPI.objects.get(pk="EAU").elements.get()
        self.assertEqual((e.referentiel_id, e.theme.nom, e.theme.parent.nom), ("RSE", "Eau", "Environnement"))  # thème existant repris


class PageReferentielsTests(Base):
    URL = reverse("parametres:referentiels")

    def test_reserve_a_l_admin(self):
        self.client.force_login(self.contrib)
        self.assertEqual(self.client.get(self.URL).status_code, 403)

    def test_creer_renommer_reordonner_desactiver_supprimer(self):
        rep = self.client.get(self.URL)  # accueil : une carte par référentiel
        self.assertContains(rep, "Reporting")
        self.assertContains(rep, reverse("parametres:referentiel_contenu", args=["ENERGIE"]))
        self.assertRedirects(self.client.get(self.URL + "?ref=ENERGIE"), reverse("parametres:referentiel_contenu", args=["ENERGIE"]))
        for nom in ("referentiel_contenu", "referentiel_reglages", "referentiel_partage"):
            self.assertContains(self.client.get(reverse(f"parametres:{nom}", args=["ENERGIE"])), "Énergie")
        self.assertContains(self.client.get(reverse("parametres:referentiel_nouveau")), "Importer un fichier")
        self.client.post(self.URL, {"action": "ajouter", "nom": "Indicateurs GRI", "couleur": "#228833"})
        gri = Referentiel.objects.get(nom="Indicateurs GRI")
        self.assertEqual((gri.code, gri.ordre), ("INDICATEURS_GRI", 3))
        self.assertContains(self.client.post(self.URL, {"action": "ajouter", "nom": "Doublon", "code": "rse"}, follow=True), "existe déjà")
        self.client.post(self.URL, {"monter": "INDICATEURS_GRI"})
        self.assertEqual(list(Referentiel.objects.values_list("code", flat=True)), ["RSE", "INDICATEURS_GRI", "ENERGIE"])
        donnees = {"action": "enregistrer"}
        for r in Referentiel.objects.all():
            donnees |= {f"nom__{r.code}": r.nom, f"couleur__{r.code}": r.couleur, f"description__{r.code}": r.description,
                        f"actif__{r.code}": "on"}
        donnees |= {"nom__ENERGIE": "Énergie et climat", "description__ENERGIE": "Suivi mensuel"}
        donnees.pop("actif__INDICATEURS_GRI")
        self.client.post(self.URL, donnees)
        self.nrg.refresh_from_db()
        self.assertEqual((self.nrg.nom, self.nrg.description), ("Énergie et climat", "Suivi mensuel"))
        self.assertFalse(Referentiel.objects.get(pk="INDICATEURS_GRI").actif)
        self.assertContains(self.client.post(self.URL, {"supprimer": "ENERGIE"}, follow=True), "contient des KPI")
        self.client.post(self.URL, {"supprimer": "INDICATEURS_GRI"})
        self.assertFalse(Referentiel.objects.filter(pk="INDICATEURS_GRI").exists())
        self.assertTrue(Journal.objects.filter(action="reglage_referentiels", champ="nom", apres="Énergie et climat").exists())

    def test_arbre_des_themes(self):
        url = self.URL + "?ref=ENERGIE"
        conso = Theme.objects.get(referentiel=self.nrg, nom="Consommations")
        self.client.post(url, {"action": "ajouter_theme", "nom_theme": "Électricité", "parent": conso.pk})
        self.client.post(url, {"action": "ajouter_theme", "nom_theme": "Sites", "parent": ""})
        elec = Theme.objects.get(referentiel=self.nrg, nom="Électricité")
        sites = Theme.objects.get(referentiel=self.nrg, nom="Sites")
        self.assertEqual((elec.parent, elec.code), (conso, "Electricite"))
        self.client.post(url, {"monter_theme": sites.pk})
        self.assertEqual([t.nom for t, _ in Plan("ENERGIE").arbre(self.nrg)], ["Sites", "Consommations", "Électricité"])
        donnees = {"action": "enregistrer_themes", f"theme_nom__{conso.pk}": "Consommations d'énergie", f"theme_parent__{conso.pk}": "",
                   f"theme_nom__{sites.pk}": "Sites", f"theme_parent__{sites.pk}": "",
                   f"theme_nom__{elec.pk}": "Électricité", f"theme_parent__{elec.pk}": sites.pk}
        self.client.post(url, donnees)
        elec.refresh_from_db()
        self.assertEqual((elec.parent, Theme.objects.get(pk=conso.pk).nom), (sites, "Consommations d'énergie"))
        donnees[f"theme_parent__{sites.pk}"] = elec.pk  # « Sites » sous son propre sous-thème : refusé
        self.assertContains(self.client.post(url, donnees, follow=True), "sous lui-même")
        self.assertContains(self.client.post(url, {"supprimer_theme": conso.pk}, follow=True), "pas vide")
        self.client.post(url, {"supprimer_theme": elec.pk})
        self.assertFalse(Theme.objects.filter(pk=elec.pk).exists())

    def test_ajouter_deplacer_retirer_des_kpi(self):
        url = self.URL + "?ref=ENERGIE"
        conso = Theme.objects.get(referentiel=self.nrg, nom="Consommations")
        self.client.post(url, {"action": "ajouter_kpi", "kpi": ["GAZ"], "kpi_texte": "EFF, NRJ", "theme_cible": conso.pk})
        self.assertEqual(list(ElementReferentiel.objects.filter(referentiel=self.nrg, theme=conso).values_list("kpi_id", flat=True)),
                         ["ELEC", "NRJ", "GAZ", "EFF"])
        self.assertContains(self.client.post(url, {"action": "ajouter_kpi", "kpi_texte": "ZZZ"}, follow=True), "Absents du catalogue : ZZZ")
        self.client.post(url, {"action": "deplacer", "element": ["GAZ", "EFF"], "theme_destination": ""})
        self.assertEqual(set(ElementReferentiel.objects.filter(referentiel=self.nrg, theme=None).values_list("kpi_id", flat=True)), {"GAZ", "EFF"})
        self.client.post(url, {"action": "facultatif", "element": ["GAZ"]})
        self.assertFalse(ElementReferentiel.objects.get(referentiel=self.nrg, kpi_id="GAZ").obligatoire)
        self.client.post(url, {"action": "retirer", "element": ["GAZ"]})
        self.assertFalse(ElementReferentiel.objects.filter(kpi_id="GAZ").exists())
        self.assertTrue(KPI.objects.filter(pk="GAZ").exists())  # retiré de tous les référentiels : reste au catalogue
        self.assertEqual(Journal.objects.filter(action="reglage_referentiels", objet="KPI", objet_id="GAZ").count(), 4)


class EditeurContenuTests(BibliothequeEssai, Base):
    """Administration › Référentiels › le référentiel › Contenu : actions de l'éditeur (JSON)."""

    def action(self, **corps):
        rep = self.client.post(reverse("parametres:referentiel_contenu_action", args=["ENERGIE"]), json.dumps(corps),
                               content_type="application/json")
        return rep.status_code, rep.json() if rep.headers["Content-Type"] == "application/json" else {}

    def test_themes(self):
        conso = Theme.objects.get(referentiel=self.nrg, nom="Consommations")
        code, r = self.action(action="theme_ajouter", nom="Électricité", parent=conso.pk)
        self.assertEqual(code, 200, r)
        elec = Theme.objects.get(referentiel=self.nrg, nom="Électricité")
        self.assertEqual(elec.parent, conso)
        self.assertIn('data-zone="%d"' % elec.pk, r["html"])
        self.action(action="theme_ajouter", nom="Sites")
        sites = Theme.objects.get(referentiel=self.nrg, nom="Sites")
        self.action(action="theme_renommer", id=conso.pk, nom="Consommations d'énergie")
        self.assertEqual(Theme.objects.get(pk=conso.pk).nom, "Consommations d'énergie")
        self.action(action="theme_deplacer", id=sites.pk, avant=conso.pk)  # « Sites » avant « Consommations »
        self.assertEqual([t.nom for t, _ in Plan("ENERGIE").arbre(self.nrg)], ["Sites", "Consommations d'énergie", "Électricité"])
        self.action(action="theme_deplacer", id=elec.pk, parent=sites.pk)
        self.assertEqual(Theme.objects.get(pk=elec.pk).parent, sites)
        code, r = self.action(action="theme_deplacer", id=sites.pk, parent=elec.pk)
        self.assertEqual(code, 400)
        self.assertIn("dans lui-même", r["message"])
        self.action(action="theme_descendre", id=sites.pk)
        self.assertEqual([t.nom for t, _ in Plan("ENERGIE").arbre(self.nrg)][0], "Consommations d'énergie")
        code, r = self.action(action="theme_supprimer", id=conso.pk)
        self.assertIn("pas vide", r["message"])
        self.action(action="theme_supprimer", id=elec.pk)
        self.assertFalse(Theme.objects.filter(pk=elec.pk).exists())
        autre = Theme.objects.filter(referentiel=self.rse).first()
        self.assertEqual(self.action(action="theme_renommer", id=autre.pk, nom="x")[0], 400)  # thème d'un autre référentiel

    def test_kpi_deposer_ranger_et_lot(self):
        conso = Theme.objects.get(referentiel=self.nrg, nom="Consommations")
        self.action(action="deposer", theme=conso.pk, source={"type": "kpi", "code": "GAZ"})  # depuis le catalogue
        self.action(action="deposer", theme=conso.pk, source={"type": "element", "code": "GAZ"}, avant="ELEC")
        self.assertEqual(list(ElementReferentiel.objects.filter(referentiel=self.nrg, theme=conso).order_by("ordre")
                              .values_list("kpi_id", flat=True)), ["GAZ", "ELEC", "NRJ"])
        self.action(action="deposer", theme=conso.pk, source={"type": "kpi", "bib": "socle_energie.json", "code": "NRJ-GAZ"}, avant="ELEC")
        self.assertEqual(list(ElementReferentiel.objects.filter(referentiel=self.nrg, theme=conso).order_by("ordre")
                              .values_list("kpi_id", flat=True))[:3], ["GAZ", "NRJ-GAZ", "ELEC"])  # modèle : à l'endroit du dépôt
        social = Theme.objects.get(referentiel=self.rse, nom="Social")
        code, r = self.action(action="deposer", theme="", source={"type": "theme", "ref": "RSE", "id": social.pk})
        self.assertTrue(r["ok"], r)
        self.assertTrue(ElementReferentiel.objects.filter(referentiel=self.nrg, kpi_id="EFF").exists())
        self.action(action="lot", operation="facultatif", codes=["GAZ", "EFF"])
        self.assertEqual(ElementReferentiel.objects.filter(referentiel=self.nrg, obligatoire=False).count(), 2)
        self.action(action="lot", operation="deplacer", codes=["EFF"], theme="")
        self.assertIsNone(ElementReferentiel.objects.get(referentiel=self.nrg, kpi_id="EFF").theme)
        code, r = self.action(action="lot", operation="retirer", codes=["GAZ"])
        self.assertIn("il reste dans le catalogue", r["message"])
        self.assertTrue(KPI.objects.filter(pk="GAZ").exists())
        self.assertEqual(self.action(action="lot", operation="retirer", codes=[])[0], 400)

    def test_page(self):
        rep = self.client.get(reverse("parametres:referentiel_contenu", args=["ENERGIE"]) + "?ajouter=1")
        self.assertContains(rep, "tiroir-ouvert")
        self.assertContains(rep, "Reporting")  # autre référentiel, dans le tiroir
        self.assertContains(rep, "GAZ")  # catalogue hors référentiel
        self.client.force_login(self.contrib)
        self.assertEqual(self.client.get(reverse("parametres:referentiel_contenu", args=["ENERGIE"])).status_code, 403)
        self.assertEqual(self.action(action="theme_ajouter", nom="x")[0], 403)


class FicheEtRangementTests(Base):
    def fiche(self, kpi, **changes):
        form = R.KPIForm(instance=kpi)
        donnees = {}
        for nom, champ in form.fields.items():
            v = form[nom].value()
            if v not in (None, False, ""):
                donnees[nom] = v
        donnees.update(changes)
        return {c: v for c, v in donnees.items() if v is not False and v is not None}

    def test_place_du_kpi_dans_la_fiche(self):
        url = reverse("collecte:referentiel_kpi", args=["EFF"])
        html = self.client.get(url, **FETCH).json()["html"]
        self.assertIn('name="place_theme__RSE"', html)  # thème en lecture (champ caché), rangement dans le contenu
        self.assertIn(reverse("parametres:referentiel_contenu", args=["RSE"]), html)
        self.assertNotIn('name="ajout_place"', html)  # un KPI existant s'ajoute à un référentiel depuis son contenu
        self.assertIn('name="ajout_place"', self.client.get(reverse("collecte:referentiel_kpi_nouveau"), **FETCH).json()["html"])
        conso = Theme.objects.get(referentiel=self.nrg, nom="Consommations")
        res = self.client.post(url, self.fiche(self.eff, ajout_place=f"ENERGIE|{conso.pk}"), **FETCH).json()
        self.assertTrue(res["ok"], res["html"])
        self.assertEqual(ElementReferentiel.objects.get(referentiel=self.nrg, kpi=self.eff).theme, conso)
        res = self.client.post(url, self.fiche(self.eff, place_theme__RSE="", place_obligatoire__ENERGIE="", place_retirer__RSE="on"),
                               **FETCH).json()
        self.assertTrue(res["ok"], res["html"])
        self.assertFalse(ElementReferentiel.objects.filter(referentiel=self.rse, kpi=self.eff).exists())
        self.assertFalse(ElementReferentiel.objects.get(referentiel=self.nrg, kpi=self.eff).obligatoire)
        html = self.client.get(reverse("collecte:cellule", args=[self.c.pk, "ELEC", self.e1.id]), **FETCH).json()["html"]
        self.assertIn("Énergie", html)  # le panneau de saisie liste les référentiels du KPI
        self.assertIn("Reporting", html)

    def test_ranger_dans_l_arbre(self):
        """``reglages.ranger`` (placement d'un KPI créé près de son voisin) : déplace et numérote dans un seul référentiel."""
        from django.core.exceptions import ValidationError

        from . import reglages as R

        energie = Theme.objects.get(referentiel=self.rse, nom="Énergie")
        self.assertEqual(R.ranger(self.admin, "RSE", energie.pk, ["EFF", "NRJ"]), (2, 1))
        e = {x.kpi_id: x for x in ElementReferentiel.objects.filter(referentiel=self.rse)}
        self.assertEqual((e["EFF"].theme, e["EFF"].ordre, e["NRJ"].ordre), (energie, 1, 2))  # EFF déplacé dans « Énergie »
        self.assertEqual(ElementReferentiel.objects.get(referentiel=self.nrg, kpi=self.nrj).theme.nom,
                         "Consommations")  # l'autre référentiel ne bouge pas
        with self.assertRaises(ValidationError):  # thème d'un autre référentiel
            R.ranger(self.admin, "RSE", Theme.objects.get(referentiel=self.nrg, nom="Consommations").pk, ["EFF", "NRJ"])
        rep = self.client.get(reverse("parametres:referentiel_contenu", args=["RSE"]))
        self.assertContains(rep, 'data-zone="%d"' % energie.pk)
        self.assertContains(rep, "Électricité")


class JeuTroisNiveauxTests(TestCase):
    def test_deux_referentiels_qui_partagent_des_kpi(self):
        from .aides_tests import jeu_trois_niveaux as J

        J.charger()
        self.assertEqual(list(Referentiel.objects.values_list("code", flat=True)), ["REPORTING", "ENERGIE", "DIRECTION"])  # le 3e composé
        communs = set(ElementReferentiel.objects.filter(referentiel_id="REPORTING").values_list("kpi_id", flat=True)) & set(
            ElementReferentiel.objects.filter(referentiel_id="ENERGIE").values_list("kpi_id", flat=True))
        self.assertTrue(communs)
        self.assertTrue(any(prof == 2 for _, prof in Plan("REPORTING").arbre(Referentiel.objects.get(pk="REPORTING"))))  # 3 niveaux de thèmes
        c = Campagne.objects.get(exercice=2025, referentiel_id="REPORTING")
        k = sorted(communs)[0]
        self.assertEqual(Reponse.objects.filter(periode=c.periode, kpi_id=k).values("organisation").distinct().count(),
                         Reponse.objects.filter(periode=c.periode, kpi_id=k).count())  # une valeur par KPI × organisation


class ReferentielsTests(BibliothequeEssai, TestCase):
    """(5) facteur d'émission de l'électricité au niveau Pays ; (6) niveaux confirmés avant l'étape suivante de
    l'assistant ; (7) composer ou importer depuis l'assistant y ramène ; (8) nouvelle version d'un modèle : nom gardé ;
    (9) raccourci « Ajouter un référentiel » (Mon compte, administrateur)."""

    def setUp(self):
        from parametres import niveaux as N
        from referentiel.models import Utilisateur

        N.creer_par_defaut()
        self.admin = Utilisateur.objects.create(username="admin", email="admin@exemple.test", role=Utilisateur.Role.ADMIN)
        self.client.force_login(self.admin)

    def test_facteur_electricite_au_niveau_pays(self):
        from referentiel.models import KPI

        from . import paquets as P

        P.appliquer(None, P.analyser_installation(P.fourni("socle_ges.json").paquet, ["GES-S2-LB"])[0])
        self.assertEqual(KPI.objects.get(pk="FE-ELEC").granularite_id, "Country")
        self.assertEqual(KPI.objects.get(pk="FE-CHALEUR").granularite_id, "Group")  # les autres facteurs : en haut

    def test_facteur_electricite_sans_niveau_pays(self):
        """Arbre Holding › Filiale › Site : le deuxième niveau ; arbre à deux niveaux : le plus haut."""
        from parametres.models import NiveauHierarchique as NH
        from referentiel.models import KPI

        from . import paquets as P

        NH.objects.all().delete()
        for code, rang in (("Holding", 1), ("Filiale", 2), ("Site", 3)):
            NH.objects.create(code=code, rang=rang, nom=code, nom_pluriel=code + "s", couleur="#123456", couleur_fond="#EEEEEE",
                              couleur_texte="#123456", couleur_pale="#F5F5F5")
        P.appliquer(None, P.analyser_installation(P.fourni("socle_ges.json").paquet, ["GES-S2-LB"])[0])
        self.assertEqual(KPI.objects.get(pk="FE-ELEC").granularite_id, "Filiale")

    def test_nouvelle_version_garde_le_nom(self):
        from referentiel.models import Referentiel

        from . import paquets as P

        p = P.fourni("socle_social.json").paquet
        P.appliquer(None, P.analyser_installation(p, ["SOC-EFFECTIF"])[0])
        Referentiel.objects.filter(code="SOCLE_SOCIAL").update(nom="Mon social", version="0.9")
        ref = Referentiel.objects.get(code="SOCLE_SOCIAL")
        a, _ = P.analyser_installation(p, [], existant=ref, nouvelle_version=True)
        self.assertNotIn("Nom", [d[0] for d in a.referentiel_differences])
        P.appliquer(None, a)
        ref.refresh_from_db()
        self.assertEqual((ref.nom, ref.version), ("Mon social", "1.0"))

    def mep(self):
        from parametres.models import Instance

        Instance.objects.filter(pk=Instance.courante().pk).update(mise_en_place_etape=4, mise_en_place_terminee=False)

    def test_niveaux_a_confirmer_avant_l_etape_suivante(self):
        from django.urls import reverse

        from parametres.models import Instance

        self.mep()
        url = reverse("parametres:mise_en_place_etape", args=[4])
        rep = self.client.get(url)
        self.assertContains(rep, "Confirmer ces niveaux")
        self.assertContains(rep, 'id="niveaux-a-confirmer"')
        for action in ("passer", "suivant", "creer"):
            rep = self.client.post(url, {"action": action, "arbre": "Groupe\n  France"}, follow=True)
            self.assertContains(rep, "Confirmez d&#x27;abord les niveaux", msg_prefix=action)
        self.assertEqual(Instance.courante().mise_en_place_etape, 4)
        self.client.post(url, {"action": "niveaux", "modele": "perso", "niveaux_libres": "Groupe\nPays\nEntité\nSite"})
        self.assertNotContains(self.client.get(url), 'id="niveaux-a-confirmer"')
        self.client.post(url, {"action": "suivant", "arbre": "Groupe\n  France"})
        self.assertEqual(Instance.courante().mise_en_place_etape, 5)

    def test_composer_et_importer_depuis_l_assistant(self):
        from django.urls import reverse

        self.mep()
        rep = self.client.post(reverse("parametres:referentiel_nouveau"), {"nom": "Direction", "frequence": "annee", "composer": "1",
                                                                         "depuis": "mise_en_place"})
        rep = self.client.get(rep["Location"])
        self.assertContains(rep, "mise en place (étape 5)")
        self.assertContains(rep, reverse("parametres:mise_en_place_etape", args=[5]))
        rep = self.client.post(reverse("parametres:paquet_importer"), {"action": "annuler", "depuis": "mise_en_place"})
        self.assertRedirects(rep, reverse("parametres:mise_en_place_etape", args=[5]), fetch_redirect_response=False)

    def test_raccourci_dans_mon_compte(self):
        from django.urls import reverse

        rep = self.client.get(reverse("collecte:mon_compte"))
        self.assertContains(rep, "</svg> Ajouter un référentiel</a>")  # icône « plus » dessinée 
        self.assertContains(rep, reverse("parametres:referentiel_nouveau"))


class ReferentielsD6D7Tests(BibliothequeEssai, BaseAdmin):
    """Cartes des référentiels et « Ajouter un référentiel »."""

    def test_cartes_et_portes(self):
        html = html_de(self.client, reverse("parametres:referentiels"))
        # lignes compactes, actions secondaires dans le menu « … », bibliothèque visible par thématique
        self.assertIn('class="lignes-referentiels"', html)
        self.assertIn('class="menu-deroulant"', html)
        self.assertIn("Bibliothèque : ajoutez un ensemble de KPI", html)
        for thematique in ("Climat et énergie", "Normes de reporting", "Social"):
            self.assertIn(f'<h3 class="titre-thematique">{thematique}</h3>', html)
        self.assertIn('id="recherche-bibliotheque"', html)
        self.assertIn(reverse("parametres:referentiel_nouveau") + "#porte-composer", html)
        self.assertNotIn("origine-ref", html)
        self.assertNotIn("(par exemple un rapport annuel", html)
        html = html_de(self.client, reverse("parametres:referentiel_nouveau"))
        self.assertIn('<details class="carte porte" id="porte-bibliotheque" open>', html)
        self.assertIn('<details class="carte porte" id="porte-composer">', html)
        self.assertNotIn("{#", html)
