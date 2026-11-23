"""Textes des onze modèles ESRS dans les cinq langues de l'interface que les définitions ne portent pas (espagnol, allemand,
italien, néerlandais, portugais) : ``referentiel/bibliotheque/traductions/esrs.<langue>.json``, ajoutés aux paquets par
``socles.paquet``. Un test par langue : aucun nom identique à l'anglais sans raison, aucun libellé en double dans un modèle,
les nombres, les codes, les références de paragraphes, les gabarits ``{…}`` et le Markdown de l'anglais se retrouvent dans la
traduction, et chaque description est complète (toutes ses phrases) ou absente."""
import collections
import json
import re

from django.test import SimpleTestCase

from collecte import paquets as P
from referentiel.bibliotheque import socles as S
from referentiel.bibliotheque import traductions as T

LANGUES = T.LANGUES
FAMILLE = "esrs"
# Modèles dont les descriptions ne sont pas encore toutes traduites (elles restent en anglais) : à vider au fil des lots.
MODELES_A_FINIR = set()
# Un nom qui s'écrit pareil en anglais et dans la langue : sigles, noms propres, mots internationaux (liste courte, par langue).
IDENTIQUES = {
    "es": {"DDT", "Dicofol", "Mirex", "No"},
    "de": {"Alachlor", "Aldrin", "Chlorfenvinphos", "Chlorpyrifos", "DDT", "Dicofol", "Dieldrin", "Diuron", "Endrin", "Heptachlor",
           "Isodrin", "Isoproturon", "Mirex", "Scope 1", "Scope 3", "Status", "Trifluralin"},
    "it": {"Aldrin", "Benzene", "DDT", "Dicofol", "Dieldrin", "Diuron", "Endrin", "Isodrin", "Isoproturon", "Mirex", "No", "Toluene",
           "Trifluralin"},
    "nl": {"Aldrin", "Atrazine", "DDT", "Dicofol", "Dieldrin", "Diuron", "Endrin", "Isodrin", "Isoproturon", "Mirex", "Percentage",
           "Project", "Scope 1", "Scope 3", "Scope 3 – franchises (cat. 14)", "Simazine", "Status", "Water (E3)"},
    "pt": {"DDT", "Dicofol", "Halons", "Mirex"},
}
# Gabarits et Markdown : un texte des modèles ESRS n'en porte pas aujourd'hui ; si un jour il en porte, la traduction doit
# les garder tels quels.
GABARIT = re.compile(r"\{[a-z_0-9]+\}")
NOMBRE = re.compile(r"\d+(?:[.,]\d+)?")
CODE = re.compile(r"\b[A-Z]{1,5}\d?-\d+[A-Z]?\b|\bAR \d+\b|§\s?\d+")


def paquets_anglais():
    """Paquets des modèles ESRS tels que les définitions les écrivent (sans les langues ajoutées)."""
    paquets = []
    for s in S.SOCLES:
        if s.get("traductions") == FAMILLE:
            p = S.paquet({**s, "traductions": ""})
            paquets.append((s["code"], p))
    return paquets


def textes_et_traductions(langue):
    """[(anglais, traduction)] de la table d'une langue."""
    return sorted(T.table(FAMILLE, langue).items())


FORMULE = re.compile(r"(?<![\d.,])[A-Za-z]+\d+[A-Za-z]*")  # CO2, CH4, N2O, tCO2e, E1 : le chiffre fait partie du symbole


def nombres(texte):
    """Nombres d'un texte, virgule ou point décimal confondus (« 1.5 » en anglais, « 1,5 » dans les autres langues)."""
    texte = re.sub(r"(?<=\d)[   ,.](?=\d{3}(?!\d))", "", FORMULE.sub("", texte))  # séparateur de milliers
    return sorted(n.replace(",", ".") for n in NOMBRE.findall(texte))


class OutilsTests(SimpleTestCase):
    def test_une_description_se_decoupe_et_se_recolle_a_l_identique(self):
        for _, p in paquets_anglais():
            for k in p.kpis:
                for anglais in (k["descriptions"].get("en") or {}).values():
                    self.assertEqual(" ".join(T.phrases(anglais)), anglais, k["code"])

    def test_les_onze_modeles_ont_leurs_traductions(self):
        self.assertEqual(len(paquets_anglais()), 11)

    def test_paquet_sans_traduction_inchange(self):
        for code, p in paquets_anglais():
            self.assertEqual({lg["code"] for lg in p.langues}, {"fr", "en"}, code)
            self.assertTrue(all(set(k["libelle"]) == {"fr", "en"} for k in p.kpis), code)


class TraductionsParLangueTests(SimpleTestCase):
    """Un test par langue (méthodes créées plus bas)."""


def _tests_pour(langue):
    def table(self):
        return T.table(FAMILLE, langue)

    def test_chaque_nom_est_traduit(self):
        """Tous les noms (thèmes, KPI, types, valeurs de listes, colonnes, règles) des onze modèles ont une traduction, et la
        table ne garde aucun texte qui n'existe plus."""
        noms, phrases = set(), set()
        for _, p in paquets_anglais():
            n, f = T.textes_a_traduire(p)
            noms.update(n)
            phrases.update(f)
        tab = table(self)
        manquants_noms = sorted(n for n in noms if n not in tab)
        self.assertEqual(manquants_noms, [], f"{langue} : {len(manquants_noms)} noms sans traduction")
        self.assertEqual(sorted(set(tab) - noms - phrases), [], f"{langue} : traductions de textes qui n'existent plus")

    def test_aucun_nom_identique_a_l_anglais_sans_raison(self):
        tab = table(self)
        noms = set()
        for _, p in paquets_anglais():
            noms.update(T.textes_a_traduire(p)[0])
        identiques = sorted(n for n in noms if tab.get(n) == n and n not in IDENTIQUES[langue])
        self.assertEqual(identiques, [], f"{langue} : noms restés identiques à l'anglais")

    def test_aucun_libelle_en_double_dans_un_modele(self):
        for code, p in paquets_anglais():
            for genre, textes in (("KPI", [k["libelle"]["en"] for k in p.kpis]), ("thèmes", [t["nom"]["en"] for t in p.themes])):
                traduits = collections.Counter(table(self).get(t, t) for t in textes)
                doubles = sorted(t for t, n in traduits.items() if n > 1)
                anglais = collections.Counter(textes)
                doubles_anglais = {t for t, n in anglais.items() if n > 1}
                traduits_anglais = {table(self).get(t, t) for t in doubles_anglais}
                self.assertEqual([d for d in doubles if d not in traduits_anglais], [], f"{langue} {code} : {genre} en double")

    def test_nombres_codes_gabarits_et_markdown_conserves(self):
        for anglais, traduit in textes_et_traductions(langue):
            self.assertEqual(sorted(GABARIT.findall(anglais)), sorted(GABARIT.findall(traduit)), anglais)
            self.assertEqual(anglais.count("`"), traduit.count("`"), anglais)
            self.assertEqual(anglais.count("**"), traduit.count("**"), anglais)
            self.assertEqual(anglais.count("\n"), traduit.count("\n"), anglais)
            self.assertEqual(nombres(anglais), nombres(traduit), f"{langue} : nombres de « {anglais} »")
            self.assertEqual(sorted(CODE.findall(anglais)), sorted(CODE.findall(traduit)), f"{langue} : codes de « {anglais} »")
            self.assertEqual(anglais.rstrip().endswith("."), traduit.rstrip().endswith("."), f"{langue} : point final de « {anglais} »")
            self.assertEqual(traduit, traduit.strip(), anglais)
            self.assertNotIn("  ", traduit, anglais)

    def test_paquet_porte_la_langue_complete_ou_rien(self):
        """Dans les paquets de la bibliothèque : la langue est déclarée, chaque nom a sa traduction, une description n'existe
        que complète (aucun paragraphe mêlant deux langues)."""
        for s in S.SOCLES:
            if s.get("traductions") != FAMILLE:
                continue
            d = json.loads((P.BIBLIOTHEQUE / s["fichier"]).read_text(encoding="utf-8"))
            self.assertIn(langue, {x["code"] for x in d["langues"]}, s["code"])
            for k in d["kpis"]:
                self.assertTrue(k["libelle"].get(langue), (s["code"], k["code"]))
                en = (k["descriptions"].get("en") or {})
                self.assertLessEqual(set((k["descriptions"].get(langue) or {})), set(en), (s["code"], k["code"]))
            for t in d["themes"]:
                self.assertTrue(t["nom"].get(langue), (s["code"], t["code"]))
            for r in d["regles"]:
                self.assertTrue((r["traductions"].get(langue) or {}).get("nom"), (s["code"], r["nom"]))
            for t in d["types_reponse"]:
                if t["format"] == "liste" and (t["valeurs"] or {}).get("en"):
                    self.assertEqual(len(t["valeurs"][langue]), len(t["valeurs"]["en"]), (s["code"], t["code"]))
                if t["format"] == "tableau":
                    for c in t["colonnes"]:
                        self.assertTrue(c["libelle"].get(langue), (s["code"], t["code"], c["code"]))

    def test_descriptions_des_modeles_finis_entierement_traduites(self):
        """Un modèle fini a toutes ses descriptions et consignes (KPI et règles) dans la langue ; les modèles de
        ``MODELES_A_FINIR`` ne l'ont pas encore (une description non traduite reste en anglais, entière)."""
        for s in S.SOCLES:
            if s.get("traductions") != FAMILLE or s["code"] in MODELES_A_FINIR:
                continue
            d = json.loads((P.BIBLIOTHEQUE / s["fichier"]).read_text(encoding="utf-8"))
            for k in d["kpis"]:
                en = k["descriptions"].get("en") or {}
                self.assertEqual(set(k["descriptions"].get(langue) or {}), set(en), (langue, s["code"], k["code"]))
            for r in d["regles"]:
                if (r["traductions"].get("en") or {}).get("description"):
                    self.assertTrue((r["traductions"].get(langue) or {}).get("description"), (langue, s["code"], r["nom"]))

    def test_longueurs_des_champs_de_la_base(self):
        """PostgreSQL refuse un texte plus long que son champ (SQLite non) : libellé d'un type de réponse 60, nom d'un KPI 300,
        nom d'un thème 150."""
        for code, p in paquets_anglais():
            for texte in [t["libelle"]["en"] for t in p.types_reponse]:
                self.assertLessEqual(len(table(self).get(texte, texte)), 60, (langue, code, texte))
            for texte in [k["libelle"]["en"] for k in p.kpis]:
                self.assertLessEqual(len(table(self).get(texte, texte)), 300, (langue, code, texte))
            for texte in [t["nom"]["en"] for t in p.themes]:
                self.assertLessEqual(len(table(self).get(texte, texte)), 150, (langue, code, texte))

    return {"test_longueurs_des_champs_de_la_base": test_longueurs_des_champs_de_la_base,
            "test_descriptions_des_modeles_finis_entierement_traduites": test_descriptions_des_modeles_finis_entierement_traduites,
            "test_chaque_nom_est_traduit": test_chaque_nom_est_traduit,
            "test_aucun_nom_identique_a_l_anglais_sans_raison": test_aucun_nom_identique_a_l_anglais_sans_raison,
            "test_aucun_libelle_en_double_dans_un_modele": test_aucun_libelle_en_double_dans_un_modele,
            "test_nombres_codes_gabarits_et_markdown_conserves": test_nombres_codes_gabarits_et_markdown_conserves,
            "test_paquet_porte_la_langue_complete_ou_rien": test_paquet_porte_la_langue_complete_ou_rien}


def _classe(langue):
    return type(f"Traductions_{langue}_Tests", (SimpleTestCase,), _tests_pour(langue))


Traductions_es_Tests = _classe("es")
Traductions_de_Tests = _classe("de")
Traductions_it_Tests = _classe("it")
Traductions_nl_Tests = _classe("nl")
Traductions_pt_Tests = _classe("pt")
