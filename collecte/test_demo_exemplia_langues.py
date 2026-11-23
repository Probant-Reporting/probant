"""Démo Exemplia dans les sept langues : la démo suit la langue de l'installation (ou ``--language``), ses contenus existent
dans les sept langues, et ses chiffres, ses statuts et ses alertes sont les mêmes quelle que soit la langue."""
import hashlib
import json
import re
from io import StringIO
from pathlib import Path

from django.core.management import CommandError, call_command
from django.db import transaction
from django.test import SimpleTestCase, TestCase, override_settings

from parametres import catalogue_unites as CU
from parametres import langues as L
from parametres import libelles as LB
from parametres.models import Instance, Langue, NiveauHierarchique, TypeReponse, Unite
from referentiel.bibliotheque import traductions as TR
from referentiel.models import KPI, Description, Organisation, Referentiel, Theme, Utilisateur

from .management.commands import _exemplia as EX
from .management.commands import _exemplia_bibliotheque as BIB
from .management.commands import _exemplia_textes as TX
from .management.commands import charger_demo as CD
from .certificat_cloture import remplissage
from .models import Alerte, Campagne, Preuve, RegleCoherence, Reponse, SelectionKPI, VueVisu

BIBLIOTHEQUE = Path(__file__).resolve().parent.parent / "referentiel" / "bibliotheque"
COMPTES_DE_BASE = ("admin", "validateur", "contributeur", "lecteur", "auditeur")
KPI_ECHANTILLON = ("NRJ-ELEC", "GES-S1", "SOC-EFFECTIF", "DEC-TOTAL", "GOV-B2-CLIMAT", "STR-ENJEUX-DESC")
SYMBOLES_MOTS = ("jours", "année", "salariés", "personnes", "cas", "accidents")  # symboles écrits en toutes lettres, donc traduits
NIVEAU_FILIALE = {"en": "Subsidiary", "fr": "Filiale", "es": "Filial", "de": "Tochtergesellschaft", "it": "Filiale", "nl": "Dochteronderneming",
                  "pt": "Filial"}


# Démo chargée avec le code d'avant les ESRS (main du 18/11/2026) : empreintes des valeurs, statuts, alertes et campagnes,
# identiques dans les sept langues. À ne changer que si la démo change vraiment (pas pour une langue, pas pour un modèle installé).
AVANT_ESRS = {
    "reponses": 3608, "alertes": 82, "preuves": 10,
    "sha_reponses": "303da5e755b88047f9729ebbfe19296cc56387d14d7c6c5fb4ca8a4b80bbcc2e",
    "sha_alertes": "8295cc4f91c6659b8bd0d66fead3baa0e51313f3c01cd99e09108a1ce281c332",
    "statuts": {'a_saisir': 0, 'brouillon': 129, 'calcule': 1225, 'erreur': 0, 'incomplet': 479, 'valide': 1775},
    "statuts_alertes": {'acceptee': 79, 'justifiee': 1, 'ouverte': 2},
    "campagnes": [('VS_BASE', 2024, 'cloturee'), ('VS_BASE', 2025, 'cloturee'), ('VS_BASE', 2026, 'ouverte'), ('VS_COMPLET', 2024, 'cloturee'), ('VS_COMPLET', 2025, 'cloturee'), ('VS_COMPLET', 2026, 'ouverte')],
    "remplissage": {'VS_BASE-2024': [438, 438, 0, 0, 14, 100.0], 'VS_BASE-2025': [438, 438, 0, 0, 14, 100.0], 'VS_BASE-2026': [438, 184, 84, 170, 7, 42.0], 'VS_COMPLET-2024': [62, 62, 0, 0, 2, 100.0], 'VS_COMPLET-2025': [62, 62, 0, 0, 5, 100.0], 'VS_COMPLET-2026': [62, 27, 15, 20, 1, 43.5]},  # cases attendues, validées, brouillons, à saisir, N/A, taux (%) : le compteur du tableau de bord
}


def _paquet(nom):
    return json.loads((BIBLIOTHEQUE / f"{nom}.json").read_text(encoding="utf-8"))


def _libelle_modele(code, lg):
    """Libellé d'un KPI dans le modèle fourni (français, anglais) ou dans la table de la démo (les cinq autres langues)."""
    if lg in BIB.LANGUES:
        return BIB.KPI[code][BIB.LANGUES.index(lg)]
    for nom in ("vs_base", "vs_complet"):
        for k in _paquet(nom)["kpis"]:
            if k["code"] == code:
                return k["libelle"][lg]
    raise AssertionError(code)


def _empreinte():
    """Chiffres, statuts, alertes et attributions de la base chargée, sans rien qui dépende de la langue (noms ramenés à
    leur clé, textes réduits à « il y en a un »)."""
    reponses = sorted((str(r.periode.debut.year), r.kpi_id, EX.cle(r.organisation), str(r.valeur), r.statut, str(r.non_applicable),
                       str(bool(r.texte)), str(bool(r.commentaire)), r.saisi_par.username if r.saisi_par_id else "",
                       r.valide_par.username if r.valide_par_id else "")
                      for r in Reponse.objects.select_related("periode", "organisation", "saisi_par", "valide_par"))
    alertes = sorted((str(a.campagne.exercice), a.campagne.referentiel_id, a.kpi_id, EX.cle(a.organisation), a.statut, str(bool(a.justification)))
                     for a in Alerte.objects.select_related("campagne", "organisation"))
    return {"reponses": reponses, "alertes": alertes, "preuves": Preuve.objects.count()}


def _fuites(lg):
    """Contenus traduisibles qui n'ont aucun texte dans la langue ``lg`` : l'outil afficherait le texte français de référence."""
    fuites = []
    for modele, champs in ((KPI, ("libelle",)), (Theme, ("nom",)), (Referentiel, ("nom", "description")), (TypeReponse, ("libelle",)),
                           (Unite, ("libelle",)), (NiveauHierarchique, ("nom", "nom_pluriel"))):
        for o in modele.objects.all():
            for champ in champs:
                if getattr(o, champ) and not L.texte(o, champ, lg):  # aucun texte dans cette langue : le repli donne le français
                    fuites.append((modele.__name__, str(o.pk), champ))
    for t in TypeReponse.objects.all():
        traduites = L.valeurs_langue(t, lg)
        for i, cle in enumerate(t.choix):
            if i >= len(traduites) or not traduites[i]:
                fuites.append(("valeurs", t.pk, cle))
    en = set(Description.objects.filter(langue="en").values_list("kpi_id", "categorie_id"))
    ici = set(Description.objects.filter(langue=lg).values_list("kpi_id", "categorie_id"))
    fuites += [("description", k, c) for k, c in sorted(en - ici)]
    return fuites


def _regles(lg):
    """Règles de cohérence de la démo : ([celles de la norme VS], [celles des modèles ESRS]), noms et descriptions de la langue."""
    noms_vs = {nom if lg == "fr" else TX.REGLES[nom][lg][0] for nom in TX.REGLES}
    toutes = sorted(RegleCoherence.objects.values_list("nom", "description"))
    return [r for r in toutes if r[0] in noms_vs], [r for r in toutes if r[0] not in noms_vs]


def _recueillir(lg):
    with TX.regler(lg):
        return _recueillir_dans(lg)


def _recueillir_dans(lg):
    admin = Utilisateur.objects.get(username="admin")
    instance = Instance.courante()
    leipzig = Organisation.objects.get(niveau_id="Site", nom="Werk Leipzig")
    hannover = Organisation.objects.get(niveau_id="Site", nom="Lager Hannover")
    return {
        "empreinte": _empreinte(),
        "instance": (instance.langue, instance.sous_titre, instance.contact),
        "langues": sorted(Langue.objects.filter(active=True).values_list("code", flat=True)),
        "interface": {u: L.interface_de(Utilisateur.objects.get(username=u).langue) for u in COMPTES_DE_BASE},
        "langue_des_comptes": {u: Utilisateur.objects.get(username=u).langue for u in COMPTES_DE_BASE},
        "groupe": Organisation.objects.get(niveau_id="Group").nom,
        "pays": sorted(Organisation.objects.filter(niveau_id="Country").values_list("nom", flat=True)),
        "sites": sorted(Organisation.objects.filter(niveau_id="Site").values_list("nom", flat=True)),
        "filiale": NiveauHierarchique.objects.get(code="Entity").tr("nom", lg),
        "symbole_annee": Unite.objects.get(code="année").tr("symbole", lg),
        "kpi": {c: KPI.objects.get(code=c).tr("libelle", lg) for c in KPI_ECHANTILLON},
        "theme": Theme.objects.get(code="B3").tr("nom", lg),
        "referentiel": Referentiel.objects.get(code="VS_BASE").tr("nom", lg),
        "oui_non": [t for _, t in TypeReponse.objects.get(code="OuiNon").choix_traduits(lg)],
        "commentaire": Reponse.objects.get(kpi_id="NRJ-COMB-REN", organisation=leipzig, periode__debut__year=2025).commentaire,
        "justification": Alerte.objects.filter(organisation=hannover, campagne__exercice=2025).first().justification,
        "texte": Reponse.objects.get(kpi_id="GEN-INTRO", organisation__niveau_id="Group", periode__debut__year=2026).texte,
        "vues": list(VueVisu.objects.order_by("ordre").values_list("nom", flat=True)),
        "listes": sorted(SelectionKPI.objects.values_list("nom", flat=True)),
        "preuve": Preuve.objects.get(reponse__kpi_id="NRJ-ELEC", reponse__periode__debut__year=2025).nom_fichier,
        "fuites": _fuites(lg) if lg != "fr" else [],
        "regles": _regles(lg)[0],
        "regles_esrs": _regles(lg)[1],
        "esrs": {r.code: r.tr("nom", lg) for r in Referentiel.objects.filter(code__startswith="ESRS_")},
        "esrs_description": Referentiel.objects.get(code="ESRS_E1").tr("description", lg),
        "theme_esrs": Theme.objects.filter(referentiel__code="ESRS_E1", parent=None).order_by("ordre").first().tr("nom", lg),
        "symboles_mots": {c: Unite.objects.get(code=c).tr("symbole", lg) for c in SYMBOLES_MOTS},
        "familles": sorted(set(Unite.objects.exclude(famille="").values_list("famille", flat=True))),
        "admin_langue": admin.langue,
        "statuts": {s: Reponse.objects.filter(statut=s).count() for s in Reponse.Statut.values},
        "statuts_alertes": {s: n for s in Alerte.Statut.values if (n := Alerte.objects.filter(statut=s).count())},
        "campagnes": sorted((c.referentiel_id, c.exercice, c.statut) for c in Campagne.objects.all()),
        "remplissage": {f"{c.referentiel_id}-{c.exercice}": [k.total, k.valide, k.brouillon, k.a_saisir, k.na, k.taux]
                        for c in Campagne.objects.order_by("referentiel_id", "exercice") for k in [remplissage(admin, c)]},
    }


class DemoExempliaSeptLanguesTests(TestCase):
    """La démo est chargée sept fois, une fois par langue, chaque chargement défait ensuite (retour au point de sauvegarde)."""

    @classmethod
    def setUpTestData(cls):
        cls.faits = {}
        for lg in TX.LANGUES:
            with transaction.atomic():
                call_command("load_demo", "--language", lg, stdout=StringIO())
                cls.faits[lg] = _recueillir(lg)
                transaction.set_rollback(True)

    def test_instance_et_comptes_s_ouvrent_dans_la_langue_choisie(self):
        for lg, f in self.faits.items():
            with self.subTest(lg=lg):
                self.assertEqual(f["instance"], (lg, TX.T["SOUS_TITRE"][lg], TX.T["CONTACT"][lg]))
                self.assertEqual(f["interface"], {u: lg for u in COMPTES_DE_BASE})  # langue de l'interface de chacun des cinq comptes
                self.assertEqual(f["langue_des_comptes"], {u: "" for u in COMPTES_DE_BASE})  # ils suivent la langue de l'installation

    def test_les_sept_langues_sont_actives(self):
        for lg, f in self.faits.items():
            self.assertEqual(f["langues"], sorted(TX.LANGUES), lg)

    def test_libelles_des_kpi_themes_referentiels_et_listes(self):
        for lg, f in self.faits.items():
            with self.subTest(lg=lg):
                self.assertEqual(f["kpi"], {c: _libelle_modele(c, lg) for c in KPI_ECHANTILLON})
                self.assertEqual(f["theme"], dict(zip(("fr", "en", *BIB.LANGUES), ("B3 – Énergie et émissions de gaz à effet de serre",
                                                                                      "B3 – Energy and greenhouse gas emissions",
                                                                                      *BIB.THEMES["B3"])))[lg])
                self.assertTrue(f["referentiel"].startswith(("Norme volontaire VS", "Voluntary Standard VS", "Norma voluntaria VS", "Freiwilliger Standard VS",
                                                              "Norma volontaria VS", "Vrijwillige standaard VS", "Norma voluntária VS")), f["referentiel"])
                self.assertEqual(f["oui_non"], {"fr": ["Oui", "Non"], "en": ["Yes", "No"], "es": ["Sí", "No"], "de": ["Ja", "Nein"],
                                                "it": ["Sì", "No"], "nl": ["Ja", "Nee"], "pt": ["Sim", "Não"]}[lg])
                self.assertEqual(f["filiale"], NIVEAU_FILIALE[lg])
                self.assertEqual(f["symbole_annee"], {"fr": "année", "en": "year", **dict(zip(BIB.LANGUES, BIB.UNITES["année"]))}[lg])

    def test_organisations_nommees_dans_la_langue_et_noms_propres_gardes(self):
        for lg, f in self.faits.items():
            with self.subTest(lg=lg):
                with TX.regler(lg):
                    attendus = sorted(TX.nom_organisation(c) for c in EX.cles_organisations() if c in EX.SITES)
                    self.assertEqual(f["sites"], attendus)
                    self.assertEqual(f["groupe"], TX.nom_organisation(EX.GROUPE))
                    self.assertEqual(f["pays"], sorted(TX.nom_organisation(p) for p in EX.PAYS))
                self.assertIn("Werk Leipzig", f["sites"])  # noms propres fictifs : jamais traduits
                self.assertIn("Fábrica de Zaragoza", f["sites"])

    def test_textes_ecrits_par_les_personnes_fictives_dans_la_langue_choisie(self):
        for lg, f in self.faits.items():
            with self.subTest(lg=lg):
                self.assertEqual(f["commentaire"], TX.T["BIOMASSE"][lg])
                self.assertEqual(f["justification"], TX.T["J_HANNOVER"][lg])
                self.assertEqual(f["texte"], TX.T["GEN-INTRO"][lg].format(sites=10))  # Hannover, fermé, ne compte plus en 2026
                self.assertEqual(f["vues"], [TX.T["VUE1_NOM"][lg], TX.T["VUE2_NOM"][lg], TX.T["VUE3_NOM"][lg]])
                self.assertEqual(len(f["listes"]), 2)
                self.assertTrue(all(n.endswith(TX.T["ESSENTIELS"][lg].split("}")[1]) for n in f["listes"]), f["listes"])
                attendu = "facture-electricite-2025-villefranche" if lg == "fr" else "electricity-summary-2025-villefranche"
                self.assertTrue(Path(f["preuve"]).stem.startswith(attendu), f["preuve"])  # le stockage ajoute un suffixe si le nom existe

    def test_regles_de_coherence_nommees_et_decrites_dans_la_langue(self):
        for lg, f in self.faits.items():
            with self.subTest(lg=lg):
                self.assertEqual(len(f["regles"]), len(TX.REGLES))
                attendu = sorted(({"fr": (nom, desc)}.get(lg) or TX.REGLES[nom][lg]) for nom, desc in self.faits["fr"]["regles"])
                self.assertEqual(f["regles"], attendu)
                if lg != "fr":  # aucun nom ni aucune description en français (« ≤ effectif total »…)
                    francais = {t for nom, desc in self.faits["fr"]["regles"] for t in (nom, desc)}
                    self.assertEqual({t for r in f["regles"] for t in r} & francais, set())

    def test_regles_de_coherence_des_modeles_esrs_dans_la_langue_de_la_demo(self):
        reference = self.faits["fr"]["regles_esrs"]
        self.assertGreater(len(reference), 20)
        for lg, f in self.faits.items():
            with self.subTest(lg=lg):
                self.assertEqual(len(f["regles_esrs"]), len(reference))
                if lg != "fr":  # un seul texte par règle, dans la langue de la démo : jamais le français
                    francais = {t for r in reference for t in r}
                    self.assertEqual({t for r in f["regles_esrs"] for t in r} & francais, set())

    def test_noms_des_modeles_et_des_themes_esrs_dans_la_langue(self):
        codes = sorted(f[:-5].upper() for f in EX.ESRS)
        for lg, f in self.faits.items():
            with self.subTest(lg=lg):
                self.assertEqual(sorted(f["esrs"]), codes)
                for code, nom in f["esrs"].items():  # les libellés des onze modèles existent dans les sept langues
                    self.assertEqual(nom, LB.libelle(f"referentiels.socle.{code.lower()}.nom", lg), code)
                self.assertEqual(f["esrs_description"], LB.libelle("referentiels.socle.esrs_e1.description", lg))
                # les thèmes sont en français et en anglais dans les définitions, et dans les cinq autres langues dans les
                # traductions des modèles ESRS (referentiel/bibliotheque/traductions)
                if lg in ("fr", "en"):
                    self.assertEqual(f["theme_esrs"], self.faits[lg]["theme_esrs"])
                else:
                    self.assertEqual(f["theme_esrs"], TR.traduire_nom("esrs", lg, self.faits["en"]["theme_esrs"]))
                    self.assertNotEqual(f["theme_esrs"], self.faits["en"]["theme_esrs"])
        self.assertNotEqual(self.faits["fr"]["theme_esrs"], self.faits["en"]["theme_esrs"])

    def test_unites_themes_et_symboles_en_toutes_lettres_traduits(self):
        for lg, f in self.faits.items():
            if lg == "fr":
                continue
            with self.subTest(lg=lg):
                for code, symbole in f["symboles_mots"].items():
                    if (lg, code) != ("en", "accidents"):  # « accidents » s'écrit pareil en anglais
                        self.assertNotEqual(symbole, code, code)
                for famille in f["familles"]:  # chaque thématique se range dans une thématique du catalogue, donc se traduit
                    officiel = CU.theme_du_catalogue(famille)
                    self.assertIsNotNone(officiel, famille)
                    self.assertEqual(CU.nom_theme(famille, lg), LB.libelle(f"{CU.PREFIXE}.theme.{CU.cle(officiel)}", lg), famille)

    def test_aucun_contenu_ne_retombe_sur_le_francais_dans_une_autre_langue(self):
        for lg, f in self.faits.items():
            self.assertEqual(f["fuites"], [], lg)

    def test_chiffres_statuts_et_alertes_identiques_dans_les_sept_langues(self):
        reference = self.faits["fr"]["empreinte"]
        self.assertGreater(len(reference["reponses"]), 3000)
        self.assertGreater(len(reference["alertes"]), 50)
        for lg, f in self.faits.items():
            with self.subTest(lg=lg):
                self.assertEqual(f["empreinte"]["reponses"], reference["reponses"])
                self.assertEqual(f["empreinte"]["alertes"], reference["alertes"])
                self.assertEqual(f["empreinte"]["preuves"], reference["preuves"])


    def test_valeurs_statuts_alertes_et_campagnes_comme_avant_l_ajout_des_esrs(self):
        """Compteurs et empreintes figés d'une démo chargée avec le code d'avant les ESRS (18/11/2026) : les onze modèles ESRS
        n'ajoutent ni valeur, ni changement de statut, ni alerte, ni campagne, ni case à remplir dans la démo."""
        for lg, f in self.faits.items():
            with self.subTest(lg=lg):
                e = f["empreinte"]
                self.assertEqual((len(e["reponses"]), len(e["alertes"]), e["preuves"]),
                                 (AVANT_ESRS["reponses"], AVANT_ESRS["alertes"], AVANT_ESRS["preuves"]))
                self.assertEqual(hashlib.sha256(json.dumps(e["reponses"]).encode()).hexdigest(), AVANT_ESRS["sha_reponses"])
                self.assertEqual(hashlib.sha256(json.dumps(e["alertes"]).encode()).hexdigest(), AVANT_ESRS["sha_alertes"])
                self.assertEqual(f["statuts"], AVANT_ESRS["statuts"])
                self.assertEqual(f["statuts_alertes"], AVANT_ESRS["statuts_alertes"])
                self.assertEqual(f["campagnes"], AVANT_ESRS["campagnes"])
                self.assertEqual(f["remplissage"], AVANT_ESRS["remplissage"])


class DemoExempliaGenerateurTests(SimpleTestCase):
    """Les valeurs fictives sortent du même générateur dans toutes les langues : seuls les textes changent."""

    def valeurs(self, lg):
        with TX.regler(lg):
            sites = {(nom, an): EX.valeurs_site(nom, an) for nom in EX.SITES for an in (2024, 2025, 2026)}
            groupe = {an: EX.valeurs_groupe(an) for an in (2024, 2025, 2026)}
        nombres = lambda d: {c: (v[0] if isinstance(v, tuple) else v) for c, v in d.items() if not isinstance(v[0] if isinstance(v, tuple) else v, str)}  # noqa: E731
        return ({k: nombres(v) for k, v in sites.items()}, {k: nombres(v) for k, v in groupe.items()},
                {k: sorted(v) for k, v in sites.items()}, {k: sorted(v) for k, v in groupe.items()})

    def test_memes_nombres_et_memes_cases_dans_chaque_langue(self):
        reference = self.valeurs("fr")
        self.assertTrue(reference[0] and reference[1])
        for lg in TX.LANGUES:
            self.assertEqual(self.valeurs(lg), reference, lg)

    def test_langue_de_l_installation_par_defaut(self):
        for reglage, attendu in (("en", "en"), ("fr", "fr"), ("de", "de"), ("pt", "pt"), ("pt-br", "pt"), ("DE", "de"), ("ja", "en"), ("", "en")):
            with override_settings(LANGUE_PAR_DEFAUT=reglage):
                self.assertEqual(CD.langue_installation(), attendu, reglage)

    def test_option_language_refuse_une_langue_inconnue(self):
        with self.assertRaises(CommandError):
            call_command("load_demo", "--language", "ja", stdout=StringIO())


class DemoExempliaTextesCompletsTests(SimpleTestCase):
    def test_chaque_texte_existe_dans_les_sept_langues_avec_les_memes_parametres(self):
        for cle, par_langue in TX.T.items():
            self.assertEqual(sorted(par_langue), sorted(TX.LANGUES), cle)
            parametres = {lg: sorted(re.findall(r"\{(\w+)\}", t)) for lg, t in par_langue.items()}
            for lg, t in par_langue.items():
                self.assertTrue(t.strip(), (cle, lg))
                self.assertEqual(parametres[lg], parametres["en"], (cle, lg))

    def test_noms_d_organisations_dans_les_six_autres_langues(self):
        for cle, noms in TX.NOMS_ORGANISATIONS.items():
            self.assertEqual(sorted(noms), sorted(lg for lg in TX.LANGUES if lg != "fr"), cle)
            self.assertIn(cle, EX.cles_organisations())

    def test_noms_des_kpi_themes_et_listes_de_la_norme_vs_dans_les_cinq_autres_langues(self):
        for nom in ("vs_base", "vs_complet"):
            paquet = _paquet(nom)
            for k in paquet["kpis"]:
                self.assertIn(k["code"], BIB.KPI, k["code"])
            for t in paquet["themes"]:
                self.assertIn(t["code"], BIB.THEMES, t["code"])
            self.assertIn(paquet["referentiel"]["code"], BIB.REFERENTIELS)
            for t in paquet["types_reponse"]:
                code = t["code"][:20]  # le code d'un type tient en 20 caractères dans l'outil
                if code in BIB.VALEURS:
                    self.assertEqual({len(v) for v in BIB.VALEURS[code]}, {len(t["valeurs"].get("fr") or ["Oui", "Non"])}, code)
                if t["format"] in ("tableau",):
                    self.assertTrue(code in BIB.TYPES or code in BIB.TYPE_COMME_KPI, code)
                for c in t.get("colonnes") or []:
                    self.assertIn(c["libelle"]["en"], BIB.COLONNES)
        for noms in (*BIB.KPI.values(), *BIB.THEMES.values(), *BIB.TYPES.values(), *BIB.COLONNES.values(), *BIB.UNITES.values()):
            self.assertEqual(len(noms), len(BIB.LANGUES))
            self.assertTrue(all(n.strip() for n in noms))
