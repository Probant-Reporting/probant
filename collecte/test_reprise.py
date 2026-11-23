"""Assistant de reprise d'un ancien système : détection (ligne d'en-têtes, forme, colonnes), correspondances mémorisées,
conversions d'unités et pourcentages, import dans des campagnes passées clôturées, profils, rapport des rejets."""
import datetime
import io
from decimal import Decimal as D

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from openpyxl import Workbook, load_workbook

from . import reprise as R
from .models import Campagne, CorrespondanceReprise, Journal, ProfilReprise, Reponse
from .aides_tests.echanges import Base

URL = "collecte:admin_reprise"


def classeur(lignes, nom="ancien.xlsx"):
    wb = Workbook()
    for l in lignes:
        wb.active.append(l)
    flux = io.BytesIO()
    wb.save(flux)
    return SimpleUploadedFile(nom, flux.getvalue())


def lu(lignes):
    return [list(l) for l in lignes]


class DetectionTests(Base):
    def test_ligne_d_en_tetes_et_formes(self):
        ctx = R.Contexte("Essai")
        longue = lu([["Export d'un fichier historique"], ["généré le 12/01"], [], ["Site", "Code", "Année", "Valeur", "Unité"],
                     ["E1", "EFF", 2023, 12, "ETP"]])
        self.assertEqual(R.detecter_entete(longue), 3)
        self.assertEqual(R.detecter(longue, 3, ctx), ("longue", {"kpi_code": "Code", "organisation": "Site", "periode": "Année",
                                                               "valeur": "Valeur", "unite": "Unité"}))
        annees = lu([["Indicateur", "Entité", 2022, 2023], ["Effectif", "E1", 10, 11]])
        self.assertEqual(R.detecter(annees, 0, ctx)[0], "annees")
        orgs = lu([["ID", "Exercice", "E1", "E2"], ["EFF", "2023", 3, 4]])
        self.assertEqual(R.detecter(orgs, 0, ctx), ("organisations", {"kpi_code": "ID", "periode": "Exercice"}))
        kpis = lu([["Site", "Année", "Effectif (ETP)", "Taux (%)"], ["E1", 2023, 3, 0.4]])
        forme, colonnes = R.detecter(kpis, 0, ctx)
        self.assertEqual((forme, colonnes), ("kpis", {"organisation": "Site", "periode": "Année"}))
        r = R.Reglages(forme=forme, colonnes=colonnes)
        e = R.extraire(kpis, r)
        self.assertEqual([(x.kpi, x.unite, x.valeur) for x in e], [("Effectif", "ETP", 3), ("Taux", "%", 0.4)])

    def test_unites_et_pourcentages(self):
        self.assertEqual(R.facteur("MWh", "kWh"), 1000)
        self.assertEqual(R.facteur("kg", "t"), D("0.001"))
        self.assertEqual(R.facteur("teqCO2", "kgCO2eq"), 1000)
        self.assertEqual(R.facteur("k€", "€"), 1000)
        self.assertEqual(R.facteur("m3", "m³"), 1)
        self.assertIsNone(R.facteur("kWh", "kg"))
        self.assertEqual(R.lecture_pourcentage([D("0.35"), D("0.4")]), "fraction")
        self.assertEqual(R.lecture_pourcentage([D(35), D(40)]), "cent")
        self.assertEqual(R.lecture_pourcentage([D("0.35")], "%"), "cent")


class AssistantTests(Base):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)

    def fichier(self):
        return classeur([
            ["Historique RH (ancien SIRH)"], [],
            ["Indicateur", "Entité", "Unité", 2022, 2023],
            ["Effectif", "E1", "ETP", 100, 104],
            ["Effectif", "Entite deux", "ETP", 40, 41],
            ["Taux", "E1", "", 0.35, 0.4],
            ["Indicateur abandonné", "E1", "", 5, 6],
        ], "sirh.xlsx")

    def parcourir(self, profil=None, kpis=None, orgs=None):
        url = reverse(URL)
        rep = self.client.post(url + "?etape=fichier", {"action": "deposer", "fichier": self.fichier(), "source": "SIRH",
                                                         "profil": profil or ""}, follow=True)
        self.assertContains(rep, "Années en colonnes")
        r = rep.context["r"]
        donnees = {"action": "suivant", "entete": r.entete + 1, "forme": r.forme, "valeurs": ["2022", "2023"]}
        donnees.update({f"role_{role}": t for role, t in r.colonnes.items()})
        rep = self.client.post(url + "?etape=colonnes", donnees, follow=True)
        self.etape_apres_colonnes = rep.context["etape"]
        if rep.context["etape"] != "correspondances":  # tout est déjà relié : l'étape est sautée, on y revient
            rep = self.client.get(url + "?etape=correspondances")
        props, porgs = rep.context["kpis"], rep.context["orgs_prop"]
        donnees = {"action": "suivant", "nb_kpi": len(props), "nb_org": len(porgs)}
        for i, p in enumerate(props):
            donnees[f"lib_kpi_{i}"] = p.libelle
            choix = (kpis or {}).get(p.libelle, "ignorer" if p.ignorer else p.affiche)  # case cochée : renvoyée cochée
            if choix == "ignorer":
                donnees[f"ignorer_kpi_{i}"] = "on"
            else:
                donnees[f"kpi_{i}"] = choix
        for i, p in enumerate(porgs):
            donnees[f"lib_org_{i}"] = p.libelle
            donnees[f"org_{i}"] = (orgs or {}).get(p.libelle, p.cible)
        rep = self.client.post(url + "?etape=correspondances", donnees, follow=True)
        return rep, props, porgs

    def test_reprise_complete_puis_profil(self):
        rep, props, porgs = self.parcourir(kpis={"Indicateur abandonné": "ignorer"}, orgs={"Entite deux": str(self.e2.pk)})
        self.assertEqual({p.libelle: p.cible for p in props}, {"Effectif": "EFF", "Taux": "TX", "Indicateur abandonné": ""})
        self.assertEqual(rep.context["etape"], "unites")
        self.assertEqual([(k.code, lecture) for k, lecture, _ in rep.context["pourcents"]], [("TX", "fraction")])
        rep = self.client.post(reverse(URL) + "?etape=unites", {"action": "suivant", "nb_unites": 0, "pct_TX": "fraction"}, follow=True)
        a = rep.context["analyse"]
        self.assertEqual(a.comptes[0][2], 6)  # 6 créations ; « Indicateur abandonné » écarté
        self.assertEqual(rep.context["transformation"].ignorees, 2)
        self.assertEqual([c.rsplit(" · ", 1)[1] for c in sorted(a.campagnes_a_creer)], ["2022", "2023"])
        self.client.post(reverse(URL) + "?etape=apercu", {"action": "profil", "nom_profil": "SIRH annuel"})
        rep = self.client.post(reverse(URL) + "?etape=apercu", {"action": "importer"}, follow=True)
        self.assertEqual(rep.context["resultat"]["ecrites"], 6)
        self.assertContains(rep, "Reprise terminée")
        c = Campagne.objects.get(exercice=2022)
        self.assertEqual(c.statut, Campagne.Statut.CLOTUREE)
        r = Reponse.objects.get(periode=c.periode, kpi_id="TX", organisation=self.e1)
        self.assertEqual((r.valeur, r.origine), (D("0.35"), Reponse.Origine.IMPORT))  # 0,35 = 35 %, stocké en fraction
        self.assertEqual(Reponse.objects.get(periode=c.periode, kpi_id="EFF", organisation=self.e2).valeur, 40)
        self.assertTrue(Journal.objects.filter(action="reprise").exists())
        memoire = {(m.libelle, m.kpi_id, m.organisation_id, m.ignorer) for m in CorrespondanceReprise.objects.filter(source="SIRH")}
        self.assertIn(("Indicateur abandonné", None, None, True), memoire)
        self.assertIn(("Entite deux", None, self.e2.pk, False), memoire)
        # même système, avec le profil : tout est reconnu, rien ne change
        profil = ProfilReprise.objects.get(nom="SIRH annuel")
        self.assertEqual(profil.reglages["pourcentages"], {"TX": "fraction"})
        rep, props, porgs = self.parcourir(profil=profil.pk)
        self.assertEqual({p.comment for p in props + porgs}, {"mémorisé"})
        self.assertEqual(self.etape_apres_colonnes, "apercu")  # rien à relier ni à convertir : droit à l'aperçu
        rep = self.client.post(reverse(URL) + "?etape=unites", {"action": "suivant", "nb_unites": 0}, follow=True)
        self.assertEqual({l.action for l in rep.context["analyse"].lignes}, {"inchange"},
                         [(l.repere, l.kpi_id, l.organisation, l.periode, l.motif) for l in rep.context["analyse"].lignes if l.action != "inchange"])

    def test_valeur_saisie_dans_l_outil_jamais_remplacee_et_rapport_des_rejets(self):
        c = Campagne.objects.create(exercice=2023, statut=Campagne.Statut.CLOTUREE)
        Reponse.objects.create(periode=c.periode, kpi_id="EFF", organisation=self.e1, valeur=D(99), statut="valide",
                               origine=Reponse.Origine.SAISIE)
        self.parcourir(orgs={"Entite deux": ""})  # « Entite deux » laissé à choisir : ses lignes sont rejetées
        rep = self.client.post(reverse(URL) + "?etape=unites", {"action": "suivant", "nb_unites": 0}, follow=True)
        motifs = {(l.repere, l.motif) for l in rep.context["analyse"].lignes if l.action == "rejet"}
        self.assertIn(("ligne 4 · 2023", "Valeur saisie dans l'outil. Pour la modifier, rouvrez la campagne."), motifs)
        self.assertTrue(any("non reliée : « Entite deux »" in m for _, m in motifs), motifs)
        self.assertTrue(any("non relié à un KPI de l'outil : « Indicateur abandonné »" in m for _, m in motifs), motifs)
        wb = load_workbook(io.BytesIO(self.client.get(reverse(URL) + "?etape=apercu&rejets=1").content))
        ws = wb[wb.sheetnames[1]]
        textes = [str(c.value) for row in ws.iter_rows() for c in row if c.value]
        self.assertTrue(any(t.startswith("ligne 5 · 2022 : ") for t in textes), textes)  # repère dans le fichier d'origine
        self.client.post(reverse(URL) + "?etape=apercu", {"action": "importer"})
        self.assertEqual(Reponse.objects.get(periode=c.periode, kpi_id="EFF", organisation=self.e1).valeur, 99)

    def test_mois_et_valeurs_fixes(self):
        f = classeur([["Date", "Indicateur", "Valeur"]] + [[datetime.datetime(2023, m, 28), "Effectif", m] for m in (1, 2)])
        rep = self.client.post(reverse(URL) + "?etape=fichier", {"action": "deposer", "fichier": f, "source": "Relevés"}, follow=True)
        r = rep.context["r"]
        self.assertEqual((r.forme, r.dates, r.colonnes.get("periode")), ("longue", "mois", "Date"))
        rep = self.client.post(reverse(URL) + "?etape=colonnes", {"action": "suivant", "entete": 1, "forme": "longue",
                                                                  "role_kpi_nom": "Indicateur", "role_periode": "Date",
                                                                  "role_valeur": "Valeur", "dates": "mois"}, follow=True)
        self.assertContains(rep, "Choisir la colonne des organisations, ou une organisation pour tout le fichier.")
        self.client.post(reverse(URL) + "?etape=colonnes", {"action": "suivant", "entete": 1, "forme": "longue",
                                                            "role_kpi_nom": "Indicateur", "role_periode": "Date",
                                                            "role_valeur": "Valeur", "dates": "mois", "org_fixe": self.e1.pk})
        lignes = [["Date", "Indicateur", "Valeur"], [datetime.datetime(2023, 1, 28), "Effectif", 1]]
        t = R.transformer(R.extraire(lignes, R.Reglages(forme="longue", colonnes={"periode": "Date", "kpi_nom": "Indicateur",
                                                                                   "valeur": "Valeur"},
                                                         fixes={"organisation": self.e1.pk}, dates="mois")),
                          R.Reglages(dates="mois"), R.Contexte("Relevés"))
        self.assertEqual(t.onglets["Reprise"][1][:3], ["EFF", "E1", "01/2023"])

    def test_reserve_a_l_admin(self):
        self.client.force_login(self.contrib)
        self.assertEqual(self.client.get(reverse(URL)).status_code, 403)


class FormatEtVerificationTests(Base):
    """Le format attendu d'abord, le modèle d'adaptation, puis le verdict de la vérification."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)

    def test_ecran_du_format_attendu(self):
        rep = self.client.get(reverse(URL))
        for texte in ("Votre fichier peut-il être repris tel quel ?", "Ce qui est accepté", "Ce qui ne passe pas",
                      "Mon fichier ressemble à", "Mon fichier est différent, ou je ne sais pas"):
            self.assertContains(rep, texte)
        self.assertEqual(rep.content.decode().count('class="exemple-format"'), 3)

    def test_modele_d_adaptation_reconnu_sans_reglage(self):
        rep = self.client.get(reverse(URL) + "?modele=1&annees=2022-2023")
        self.assertIn("attachment;", rep["Content-Disposition"])
        wb = load_workbook(io.BytesIO(rep.content))
        ws = wb.worksheets[0]
        tetes = [c.value for c in ws[1]]
        self.assertEqual(tetes, ["Code KPI", "KPI", "Unité", "Code organisation", "Organisation", "2022", "2023"])
        lignes = [[c.value for c in r] for r in ws.iter_rows(min_row=2)]
        self.assertIn(["EFF", "Effectif", "ETP", self.e1.code, "E1", None, None], lignes)
        self.assertFalse(any(l[0] == "DBL" for l in lignes))  # un KPI calculé n'est pas à reprendre
        for l in ws.iter_rows(min_row=2):
            if l[0].value == "EFF":
                l[5].value, l[6].value = 100, 104
        flux = io.BytesIO()
        wb.save(flux)
        rep = self.client.post(reverse(URL), {"action": "deposer", "fichier": SimpleUploadedFile("modele.xlsx", flux.getvalue()),
                                              "source": "Modèle"}, follow=True)
        v = rep.context["verification"]
        self.assertEqual((v.verdict, v.nb_kpi, v.nb_kpi_reconnus, v.nb_org_reconnues, v.nb_valeurs), ("ok", 1, 1, 2, 4))
        self.assertContains(rep, "Ce fichier peut être repris tel quel.")
        r = rep.context["r"]
        donnees = {"action": "suivant", "entete": r.entete + 1, "forme": r.forme, "valeurs": ["2022", "2023"]}
        donnees.update({f"role_{role}": t for role, t in r.colonnes.items()})
        rep = self.client.post(reverse(URL) + "?etape=colonnes", donnees, follow=True)
        self.assertEqual(rep.context["etape"], "apercu")  # rien à relier ni à convertir
        self.assertEqual(rep.context["analyse"].comptes[0][2], 4)

    def test_colonnes_ecartees_et_annee_de_l_onglet(self):
        wb = Workbook()
        ws = wb.active
        ws.title = "2023 Data"
        for l in (["ID", "Thème", "E1", "E2"], ["EFF", "Social", 10, 11]):
            ws.append(l)
        flux = io.BytesIO()
        wb.save(flux)
        rep = self.client.post(reverse(URL), {"action": "deposer", "fichier": SimpleUploadedFile("ancien.xlsx", flux.getvalue()),
                                              "source": "Essai"}, follow=True)
        r, v = rep.context["r"], rep.context["verification"]
        self.assertEqual((r.forme, r.exclues, r.fixes.get("periode")), ("organisations", ["Thème"], "2023"))
        self.assertEqual((v.verdict, v.nb_valeurs), ("points", 2))  # « Thème » écarté n'est pas lu comme une valeur
        self.assertContains(rep, "1 colonne écartée")
        self.assertEqual([e.organisation for e in R.extraire(ws_lignes(ws), r)], ["E1", "E2"])

    def test_fichier_non_reconnu(self):
        f = classeur([["Notes diverses", "Autre"], ["bla", "bla"]])
        rep = self.client.post(reverse(URL), {"action": "deposer", "fichier": f, "source": "Essai"}, follow=True)
        self.assertEqual(rep.context["verification"].verdict, "non")
        self.assertContains(rep, "outil ne reconnaît pas ce fichier.")
        self.assertContains(rep, 'value="suivant" disabled')


def ws_lignes(ws):
    return [[c.value for c in r] for r in ws.iter_rows()]


class VitesseTests(Base):
    """Le fichier déposé est lu une seule fois, puis relu depuis sa copie gardée."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)

    def test_fichier_lu_une_seule_fois(self):
        from unittest import mock

        from django.core.files.storage import default_storage

        from . import fichiers as X
        from .vues_echanges import LU, lecture_gardee

        date = datetime.date(2023, 5, 1)
        f = classeur([["Indicateur", "Entité", "Année", "Valeur", "Depuis"], ["Effectif", "E1", 2023, 12.5, date]])
        with mock.patch.object(X, "lire", wraps=X.lire) as lire:
            self.client.post(reverse(URL), {"action": "deposer", "fichier": f, "source": "Essai"})
            for _ in range(3):
                self.assertEqual(self.client.get(reverse(URL) + "?etape=colonnes").status_code, 200)
            self.assertEqual(lire.call_count, 1)
        chemin = self.client.session["reprise"]["chemin"]
        garde = lecture_gardee(chemin)
        ligne = next(iter(garde.values()))[1]
        self.assertEqual(ligne[:4], ["Effectif", "E1", 2023, 12.5])
        self.assertEqual(ligne[4].date() if isinstance(ligne[4], datetime.datetime) else ligne[4], date)  # les dates restent des dates
        self.client.post(reverse(URL), {"action": "recommencer"})
        self.assertFalse(default_storage.exists(chemin + LU))  # la copie part avec le fichier

    def test_copie_abimee_ou_piegee_ignoree(self):
        import pickle

        from django.core.files.base import ContentFile
        from django.core.files.storage import default_storage

        from .vues_echanges import LU, lecture_gardee

        class Piege:
            def __reduce__(self):
                return (print, ("piège",))

        for contenu in (b"n'importe quoi", pickle.dumps({"A": [[Piege()]]})):
            nom = default_storage.save("pending-imports/essai.xlsx" + LU, ContentFile(contenu))
            try:
                self.assertIsNone(lecture_gardee(nom[:-len(LU)]))  # seules des valeurs de cellule sont relues
            finally:
                default_storage.delete(nom)
