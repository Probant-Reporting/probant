"""Un KPI pas demandé dans une période (« demandé depuis » plus tard, ou hors du périmètre gelé d'un exercice clos ou
rouvert) n'apparaît dans AUCUN écran ni export de cette période ; un KPI demandé apparaît partout (la Consolidation de 2025, rouvert en « garder », montrait une colonne « — Incomplet » pour un KPI demandé depuis 2026).

Inventaire des portes qui listent les KPI d'une période, et la fonction qui les borne :
- Saisie, Pour moi, Tableau de bord, Relances, serveur MCP (``list_kpis``, ``list_values``, ``get_completion``) :
  ``saisie.lignes`` / ``saisie.cellules`` (``kpis_collectes`` + ``calcul.perimetre_gele``) ;
- Fichier à remplir, exports (trois présentations), imports, Cohérence (contrôles et règles) : ``saisie.codes_campagne`` ;
- Consolidation et son Excel : ``saisie.codes_campagne`` (thème, KPI cochés, liste des KPI à cocher) et
  ``visualisation.Source.demande`` (liste enregistrée) ;
- Visualisation (tableau d'un thème, tableau de KPI choisis, chiffre, organisations…) : ``Source.demande``
  (``calcul.perimetre_calcul``, la règle des cases écrites).
Les listes de choix des KPI d'un visuel (catalogue) ne dépendent d'aucune période : une vue se lit sur plusieurs
périodes, la période est un filtre ; le KPI y reste proposé, et le visuel n'a aucune ligne pour la période où il n'est
pas demandé.

Données inventées uniquement."""
import datetime
import io
from types import SimpleNamespace

from django.urls import reverse
from openpyxl import load_workbook

from parametres import niveaux as N
from referentiel.models import KPI, ElementReferentiel, Theme
from serveur_mcp import outils as O

from . import calcul as C
from . import coherence as CH
from . import periodes as P
from . import saisie as S
from .administration import changer_statut
from .models import Alerte, Campagne, RegleCoherence, Reponse, SelectionKPI
from .test_demande_depuis_perimetre import Base
from .visuels.assemblage import donnees

CODE = "ZQNEW"


def texte(rep):
    """Tout le texte d'une réponse : page HTML, ou toutes les cellules d'un classeur."""
    if "spreadsheet" in rep.get("Content-Type", ""):
        wb = load_workbook(io.BytesIO(rep.content))
        return "\n".join(str(c.value) for ws in wb for row in ws.iter_rows() for c in row if c.value is not None)
    return rep.content.decode("utf-8", "replace")


class Portes:
    """``verifier(campagne, attendu)`` : le KPI ``CODE`` est (attendu vrai) ou n'est pas (faux) dans chaque porte."""

    def preparer_kpi(self, depuis=None):
        self.nouveau(CODE)
        theme = Theme.objects.filter(referentiel=self.ref).first()
        e = ElementReferentiel(referentiel=self.ref, kpi_id=CODE, ordre=9, theme=theme, demande_depuis=depuis)
        e.depuis_choisi = depuis is not None
        e.save()
        self.theme = theme
        self.liste = SelectionKPI.objects.create(nom="Liste essai", proprietaire=self.admin)
        self.liste.kpis.set(KPI.objects.filter(code__in=["EFF", CODE]))
        RegleCoherence.objects.create(nom="Plafond essai", gauche=f"[{CODE}]", operateur=">=", droite="1000",
                                      niveau_id=self.e1.niveau_id)

    def valeur(self, campagne):
        S.enregistrer(self.admin, campagne, KPI.objects.get(pk=CODE), self.e1, "4", False, "")
        r = Reponse.objects.get(periode=campagne.periode, kpi_id=CODE, organisation=self.e1)
        r.statut = Reponse.Statut.VALIDE
        r.save()
        C.recalculer(campagne)

    def portes_http(self, c):
        q = f"?campagne={c.pk}"
        conso = reverse("collecte:consolidation") + q
        return {
            "saisie": reverse("collecte:saisie") + q + f"&org={self.e1.pk}",
            "consolidation (thème)": conso + "&vides=1",
            "consolidation (KPI cochés)": conso + f"&choix_kpi=choix&kpis=EFF&kpis={CODE}&vides=1",
            "consolidation (liste)": conso + f"&choix_kpi=liste&selection={self.liste.pk}&vides=1",
            "consolidation Excel": reverse("collecte:consolidation_excel") + q + "&vides=1",
            "consolidation Excel (liste)": reverse("collecte:consolidation_excel") + q + f"&choix_kpi=liste&selection={self.liste.pk}&vides=1",
            "fichier à remplir": reverse("collecte:echanges_modele") + q + "&choix_kpi=tous",
        }

    def verifier(self, c, attendu):
        c = Campagne.objects.select_related("periode", "referentiel").get(pk=c.pk)
        self.client.force_login(self.admin)
        for nom, url in self.portes_http(c).items():
            with self.subTest(porte=nom, periode=str(c.periode)):
                rep = self.client.get(url)
                self.assertEqual(rep.status_code, 200)
                if nom.startswith("consolidation ("):
                    # colonnes et KPI à cocher (le sélecteur des listes enregistrées montre leur contenu, sans période)
                    self.assertEqual(CODE in [k.code for k in rep.context["kpis"]], attendu)
                    self.assertEqual(CODE in [k.code for _, ks in rep.context["ck"]["groupes"] for k in ks], attendu)
                else:
                    self.assertEqual(CODE in texte(rep), attendu)
        for pres in ("base", "tableau", "revue"):
            with self.subTest(porte=f"export {pres}", periode=str(c.periode)):
                rep = self.client.post(reverse("collecte:echanges_exporter"), {
                    "action": "telecharger", "presentation": pres, "exercices": [str(c.exercice)], "choix_kpi": "tous",
                    "referentiel": self.ref.code, "niveaux": N.codes(), "contenus": ["valide", "brouillon", "calcule"],
                    "types": ["saisie", "herite", "calcul"]})
                self.assertIn("spreadsheet", rep.get("Content-Type", ""))
                self.assertEqual(CODE in texte(rep), attendu)
        lignes = S.lignes(self.admin, c)
        with self.subTest(porte="Saisie, Pour moi, Relances (lignes)", periode=str(c.periode)):
            self.assertEqual(CODE in {l.kpi.code for l in lignes}, attendu)
        with self.subTest(porte="Tableau de bord", periode=str(c.periode)):
            from referentiel.plans import Plan

            tdb = S.tableau_de_bord(lignes, Plan(c.referentiel))
            self.assertEqual(tdb["total"].total, 4 if attendu else 2)  # EFF (et le nouveau KPI) × deux entités
        ctx = SimpleNamespace(utilisateur=self.admin, sensibles=lambda: frozenset(), validees_seulement=lambda: False)
        with self.subTest(porte="MCP list_kpis", periode=str(c.periode)):
            self.assertEqual(CODE in [k["code"] for k in O.list_kpis(ctx, {"campaign_id": c.pk})["kpis"]], attendu)
        with self.subTest(porte="MCP list_values", periode=str(c.periode)):
            vals = O.list_values(ctx, {"campaign_id": c.pk, "organisation_id": self.g.pk, "include_calculated": True})
            self.assertEqual(CODE in {v["kpi"]["code"] for v in vals["values"]}, attendu)
        with self.subTest(porte="MCP get_completion", periode=str(c.periode)):
            self.assertEqual(O.get_completion(ctx, {"campaign_id": c.pk})["total"]["expected"], 4 if attendu else 2)
        with self.subTest(porte="Cohérence (règles)", periode=str(c.periode)):
            CH.controler(c)
            self.assertEqual(Alerte.objects.filter(campagne=c, kpi_id=CODE).exists(), attendu)
        for forme, source, kpis in (("tableau", f"theme:{self.theme.pk}", []), ("tableau", "", ["EFF", CODE]),
                                    ("chiffre", "", [CODE]), ("organisations", "", [CODE])):
            with self.subTest(porte=f"Visualisation {forme} {source}", periode=str(c.periode)):
                d = donnees(self.admin, {"periode": c.periode.pk, "referentiel": self.ref.pk},
                            [{"id": "v", "type": forme, "titre": "", "kpis": kpis, "source": source, "axe": "", "series": "",
                              "largeur": 12, "hauteur": "m", "filtres": {}, "options": {}}], {}, c)["visuels"]["v"]
                if forme == "tableau":
                    self.assertEqual(CODE in {l["kpi"] for l in d.get("tableau", {}).get("lignes", [])}, attendu)
                else:
                    self.assertEqual(d["etat"] != "vide", attendu, d)


class ExerciceRouvertGarderTests(Portes, Base):
    """2025 clos puis rouvert « garder » (périmètre gelé) ; le KPI, ajouté ensuite, est demandé depuis 2026."""

    def setUp(self):
        super().setUp()
        self.preparer_kpi()
        changer_statut(self.admin, self.camp(2025), "rouvrir", garder=True)
        self.valeur(self.camp(2026))

    def test_absent_de_2025_present_en_2026(self):
        self.assertEqual(self.element(CODE).demande_depuis, datetime.date(2026, 1, 1))
        self.verifier(self.camp(2025), False)
        self.verifier(self.camp(2026), True)


class PeriodeJamaisCloseTests(Portes, Base):
    """2026 jamais clos (aucun périmètre gelé) ; le KPI est demandé depuis 2027, campagne 2027 ouverte."""

    def setUp(self):
        super().setUp()
        self.c[2027] = P.campagne(self.ref, datetime.date(2027, 1, 1), statut=Campagne.Statut.OUVERTE)[0]
        for org in (self.e1, self.e2):
            Reponse.objects.create(periode=self.c[2027].periode, kpi_id="EFF", organisation=org, valeur=10,
                                   statut=Reponse.Statut.VALIDE, origine=Reponse.Origine.SAISIE)
        self.preparer_kpi(datetime.date(2027, 1, 1))
        self.valeur(self.camp(2027))

    def test_absent_de_2026_present_en_2027(self):
        self.assertIsNone(C.perimetre_gele(self.camp(2026).periode))
        self.verifier(self.camp(2026), False)
        self.verifier(self.camp(2027), True)
