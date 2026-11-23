"""Textes des quatorze modèles fournis (VS, transparence des rémunérations, onze ESRS) après la relecture du 18/11 : chaque
KPI placé a son libellé et sa description en français et en anglais ; chaque règle porte son nom et son explication en
anglais dans le paquet ; une même condition porte le même nom partout ; les descriptions partagées par plusieurs modèles
ne contiennent aucune phrase propre à une seule norme ; montants dans la monnaie des états financiers ; erreurs relevées
contre le règlement délégué (UE) 2026/1563 corrigées."""
import json

from django.test import SimpleTestCase

from collecte import paquets as P
from referentiel.bibliotheque import controle as C
from referentiel.bibliotheque import socles as S
from referentiel.bibliotheque.outils import langue

QUATORZE = {"VS_BASE", "VS_COMPLET", "TRANSPARENCE_REMU", "ESRS_2", "ESRS_E1", "ESRS_E2", "ESRS_E3", "ESRS_E4", "ESRS_E5",
            "ESRS_S1", "ESRS_S2", "ESRS_S3", "ESRS_S4", "ESRS_G1"}
PROPRES_A_UNE_NORME = ("10 salariés", "10 employees", "classeur de l'EFRAG", "EFRAG's workbook", "norme volontaire ;",
                       "définition de la norme volontaire", "definition of the Voluntary Standard")


def paquet(code):
    return json.loads(P.vers_json(S.paquet(next(s for s in S.SOCLES if s["code"] == code))))


class TextesDesModelesFournisTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.paquets = {code: paquet(code) for code in QUATORZE}
        cls.places = {}
        for s in S.SOCLES:
            for code, *_ in C.elements(s):
                cls.places.setdefault(code, set()).add(s["code"])

    def test_les_quatorze_modeles(self):
        self.assertEqual({s["code"] for s in S.SOCLES}, QUATORZE)

    def test_chaque_kpi_a_libelle_et_description_en_francais_et_en_anglais(self):
        for code, p in self.paquets.items():
            for k in p["kpis"]:
                with self.subTest(modele=code, kpi=k["code"]):
                    self.assertTrue(k["libelle"].get("fr") and k["libelle"].get("en"))
                    self.assertTrue((k["descriptions"].get("fr") or {}).get("description"))
                    self.assertTrue((k["descriptions"].get("en") or {}).get("description"))
                    # les textes secondaires aussi, dans les deux langues quand ils existent
                    for cat in ("a_inclure", "a_exclure", "source"):
                        self.assertEqual(bool((k["descriptions"]["fr"]).get(cat)), bool((k["descriptions"]["en"]).get(cat)))

    def test_chaque_regle_a_son_nom_et_son_explication_en_anglais(self):
        for code, p in self.paquets.items():
            for r in p["regles"]:
                with self.subTest(modele=code, regle=r["nom"]):
                    anglais = r.get("traductions", {}).get("en", {})
                    self.assertTrue(r["nom"] and r["description"])
                    self.assertTrue(anglais.get("nom") and anglais.get("description"))
                    self.assertNotEqual(anglais["nom"], r["nom"])

    def test_une_meme_condition_porte_le_meme_nom_dans_tous_les_modeles(self):
        par_condition = {}
        for s in S.SOCLES:
            for nom in s["regles"]:
                g, op, d = S.REGLES[nom][:3]
                par_condition.setdefault((g.replace(" ", ""), op, d.replace(" ", "")), set()).add(nom)
        self.assertEqual({c: n for c, n in par_condition.items() if len(n) > 1}, {})
        # les cinq contrôles que la VS partage avec l'ESRS S1 ou l'E5 : une seule règle, mêmes textes dans les deux modèles
        for nom, modeles in (("Effectif féminin ≤ effectif total", {"VS_BASE", "ESRS_S1"}),
                             ("Effectif masculin ≤ effectif total", {"VS_BASE", "ESRS_S1"}),
                             ("Salariés couverts par une convention ≤ effectif total", {"VS_BASE", "ESRS_S1"}),
                             ("Déchets recyclés ≤ déchets générés", {"VS_BASE", "ESRS_E5"}),
                             ("Déchets préparés pour le réemploi ≤ déchets générés", {"VS_BASE", "ESRS_E5"})):
            regles = [next(r for r in self.paquets[m]["regles"] if r["nom"] == nom) for m in modeles]
            # les langues que seuls les modèles ESRS portent (traductions) s'ajoutent à la règle partagée au catalogue des
            # textes (regles_textes.catalogue) : on compare le français et l'anglais, qui sont ceux des définitions
            sans_ajouts = [{**r, "traductions": {lg: t for lg, t in r["traductions"].items() if lg in ("fr", "en")}} for r in regles]
            self.assertEqual(sans_ajouts[0], sans_ajouts[1], nom)

    def test_descriptions_partagees_sans_phrase_propre_a_une_norme(self):
        for code, modeles in self.places.items():
            if len(modeles) < 2:
                continue
            d = S.KPIS[code]["description"]
            for texte in (langue(d, "fr"), langue(d, "en")):
                for phrase in PROPRES_A_UNE_NORME:
                    with self.subTest(kpi=code, phrase=phrase):
                        self.assertNotIn(phrase, texte)

    def test_montants_dans_la_monnaie_des_etats_financiers(self):
        for code in QUATORZE - {"VS_BASE", "VS_COMPLET", "TRANSPARENCE_REMU"}:
            p = self.paquets[code]
            for k in p["kpis"]:
                for lg in ("fr", "en"):
                    texte = k["descriptions"][lg]["description"]
                    with self.subTest(modele=code, kpi=k["code"], langue=lg):
                        self.assertNotIn("en euros", texte)
                        self.assertNotIn("in euros", texte)
            for t in p["types_reponse"]:
                for c in t.get("colonnes") or []:
                    with self.subTest(modele=code, colonne=c["code"]):
                        self.assertNotIn("€", c.get("unite") or "")
        # un KPI de montant propre aux ESRS dit la règle de la monnaie (ESRS 1 AR 50)
        for code in ("CLI-CAPEX-CHARBON", "CLI-PASSIFS-POTENTIELS", "GOV-CONTRIBUTIONS-POLIT", "SOC-AMENDES-DH"):
            self.assertIn("ESRS 1 AR 50", S.KPIS[code]["description"][0])
            self.assertIn("ESRS 1 AR 50", S.KPIS[code]["description"][1])


class ErreursCorrigeesTests(SimpleTestCase):
    def test_incidents_droits_humains_sans_restriction_de_gravite(self):  # S1-16 §43(b)
        self.assertNotIn("grave", S.KPIS["SOC-INCIDENTS-DH"]["fr"])

    def test_polluants_seulement_les_rejets_importants(self):  # E2-4 §15, E2 AR 2
        fr, en = S.KPIS["POL-EMISSIONS-AUTRES"]["description"]
        self.assertNotIn("ou que l'entreprise mesure ou suit :", fr)
        self.assertNotIn("or that the company measures or monitors:", en)
        self.assertIn("E2 AR 2", fr)

    def test_accidents_et_deces_des_salaries(self):  # VS B9 §41 « regarding its employees », S1-13 §37
        for code in ("SOC-ACCIDENTS-ENREG", "SOC-DECES"):
            fr, en = S.KPIS[code]["description"]
            self.assertIn("salariés", fr)
            self.assertIn("employees", en)
        self.assertNotIn("maladie professionnelle", S.KPIS["SOC-DECES"]["description"][0])

    def test_sous_total_du_scope_1_dans_les_donnees_de_calcul(self):
        from referentiel.bibliotheque.definitions import esrs_e1

        themes = {code: theme for code, theme, _, _ in C.elements(esrs_e1.SOCLE)}
        self.assertEqual(themes["GES-S1"], "E1_DONNEES_GES")
        self.assertEqual(themes["GES-S1-BRUT"], "E1_8")
        self.assertIn("sous-total", S.KPIS["GES-S1"]["fr"])

    def test_version_des_esrs_article_2(self):
        valeurs = dict((t[0], t[3]) for t in S.TYPES_REPONSE)["ESRS-VERSION"]
        self.assertEqual(len(valeurs["fr"]), 4)
        self.assertTrue(any("2(1)(b)" in v for v in valeurs["en"]))

    def test_credits_carbone_achetes_et_pas_encore_annules(self):  # E1 §34(b) d'abord, AR 28(c) ensuite
        fr, en = S.KPIS["GES-CREDITS-A-ANNULER"]["description"]
        self.assertLess(en.index("§34(b)"), en.index("AR 28(c)"))
        self.assertIn("not cancelled yet at the reporting date", en)

    def test_pas_de_regle_eau_en_stress_contre_consommation(self):
        from referentiel.bibliotheque.definitions import esrs_e3

        # la règle revient sur le KPI propre à l'ESRS (mêmes rejets déduits), jamais sur EAU-STRESS (VS)
        self.assertEqual([r[0] for r in esrs_e3.REGLES.values()], ["[EAU-CONSO-STRESS]"])
        self.assertIn("B6 §37", S.KPIS["EAU-STRESS"]["description"][0])  # méthode dite (rejets déduits)

    def test_taux_d_accidents_par_million_d_heures(self):
        for code in ("SOC-TAUX-ACC-SALARIES", "SOC-TAUX-ACC-NON-SAL", "SOC-TAUX-ACCIDENTS"):
            self.assertIn("par million d'heures travaillées", S.KPIS[code]["fr"])
            self.assertIn("per million hours worked", S.KPIS[code]["en"])

    def test_part_couverte_par_une_convention_consigne_hors_eee(self):
        fr, en = S.KPIS["SOC-PART-CONVENTION"]["description"]
        self.assertIn("une réponse N/A sortirait", fr)
        self.assertIn("an N/A answer would take", en)
