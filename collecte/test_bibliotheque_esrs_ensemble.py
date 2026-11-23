"""Les onze modèles ESRS révisées réunis (construits séparément, un par norme) : un KPI défini une seule fois, aucun
libellé partagé par deux KPI différents, unités et types de réponse sans double, conventions de code suivies par tous.
Règle des doublons : un KPI = une définition, saisie une fois, placée dans autant de modèles que nécessaire."""
import collections
import re
import unicodedata

from django.test import SimpleTestCase

from referentiel.bibliotheque import definitions as D
from referentiel.bibliotheque import socles as S
from referentiel.bibliotheque.definitions import _esrs_communs as EC

# Familles de codes des KPI (note de conception : les données, pas la norme ; aucune famille nouvelle)
FAMILLES = ("GEN-", "STR-", "GOV-", "CLI-", "GES-", "NRJ-", "POL-", "EAU-", "BIO-", "ECO-", "DEC-", "SOC-", "CONV-", "FE-")
# Même libellé, deux KPI : cas hérités des modèles existants (norme VS et transparence des rémunérations, non modifiés ici),
# notés dans la revue des doublons pour une prochaine version de ces modèles.
LIBELLES_HERITES = {frozenset({"SOC-REMU-H-FEMMES", "SOC-REMU-MOY-HOR-F"}), frozenset({"SOC-REMU-H-HOMMES", "SOC-REMU-MOY-HOR-H"})}


def _norme(texte):
    texte = unicodedata.normalize("NFKD", texte.lower())
    texte = "".join(c for c in texte if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", texte).strip()


def places():
    """Code de KPI -> modèles de la bibliothèque qui le placent."""
    sortie = collections.defaultdict(set)

    def parcourir(noeuds, modele):
        for n in noeuds:
            if S.est_theme(n):
                parcourir(n[3], modele)
            else:
                sortie[n if isinstance(n, str) else n[0]].add(modele)
    for s in S.SOCLES:
        parcourir(s["arbre"], s["code"])
    return sortie


class EnsembleEsrsTests(SimpleTestCase):
    def setUp(self):
        self.places = places()
        self.esrs = {c for c, m in self.places.items() if m & set(EC.MODELES)}

    def test_aucun_conflit_et_un_kpi_defini_dans_un_seul_fichier(self):
        self.assertEqual(S.CONFLITS, [])
        definis = collections.defaultdict(list)
        for m in D.charger():
            for code in getattr(m, "KPIS", {}):
                definis[code].append(m.__name__.rsplit(".", 1)[-1])
        self.assertEqual({c: f for c, f in definis.items() if len(f) > 1}, {})

    def test_deux_kpi_differents_n_ont_jamais_le_meme_libelle(self):
        for langue in ("fr", "en"):
            par_libelle = collections.defaultdict(set)
            for code, d in S.KPIS.items():
                par_libelle[_norme(d[langue])].add(code)
            doubles = [sorted(codes) for codes in par_libelle.values()
                       if len(codes) > 1 and codes & self.esrs and frozenset(codes) not in LIBELLES_HERITES]
            with self.subTest(langue=langue):
                self.assertEqual(doubles, [])

    def test_unites_et_types_de_reponse_sans_double(self):
        libelles = collections.Counter(_norme(u[2][1]) for u in S.UNITES)
        self.assertEqual([lib for lib, n in libelles.items() if n > 1], [])
        contenus = collections.defaultdict(list)
        for code, _lib, fmt, valeurs in S.TYPES_REPONSE:
            if fmt == "liste":
                contenus[(fmt, tuple(_norme(v) for v in valeurs.get("fr", [])))].append(code)
            elif fmt == "tableau":
                contenus[(fmt, tuple((c["code"], c["type"], c.get("liste")) for c in valeurs))].append(code)
        self.assertEqual([codes for codes in contenus.values() if len(codes) > 1], [])
        utilises = {S.KPIS[c]["reponse"] for c in self.esrs}
        self.assertTrue(utilises <= {t[0] for t in S.TYPES_REPONSE})
        self.assertTrue(all(len(t[0]) <= 20 for t in EC.TYPES_REPONSE))  # codes de type : 20 caractères au plus

    def test_conventions_de_code(self):
        for code in sorted(self.esrs):
            with self.subTest(code=code):
                self.assertLessEqual(len(code), 30)
                self.assertTrue(code.startswith(FAMILLES))
                self.assertRegex(code, r"^[A-Z0-9]+(-[A-Z0-9]+)*$")

    def test_chaque_modele_a_ses_kpi_et_les_onze_ensemble(self):
        """Nombre de KPI placés par modèle après la réunion des lots (réutilisations comprises)."""
        par_modele = {m: {c for c, ms in self.places.items() if m in ms} for m in EC.MODELES}
        self.assertEqual({m: len(c) for m, c in par_modele.items()}, {
            "ESRS_2": 104,  # + parts des femmes et des hommes au conseil, liens avec les états financiers (ESRS 1 §114-116) ;
            # + membres d'un autre genre, tous les membres et leur part
            "ESRS_E1": 152,  # + statut du plan (VS, fusionné) et cibles absolues de la VS, − CLI-PLAN-STATUT
            "ESRS_E2": 30,
            "ESRS_E3": 21,
            "ESRS_E4": 27,
            "ESRS_E5": 51,
            "ESRS_S1": 100,  # + personnel (salariés et non-salariés) et heures du personnel
            "ESRS_S2": 30,  # + indicateurs propres facultatifs (ESRS 2 AR 42)
            "ESRS_S3": 30,
            "ESRS_S4": 25,
            "ESRS_G1": 42,  # GOV-AMENDES (VS) au lieu de GOV-AMENDES-ANTICORRUPTION ; + paiements en valeur
        })
