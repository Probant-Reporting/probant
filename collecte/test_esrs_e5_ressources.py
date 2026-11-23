"""Modèle « ESRS E5 – Utilisation des ressources et économie circulaire » : contrôle et couverture, KPI de la norme volontaire
VS repris sans conflit (déchets totaux, dangereux, recyclés, préparés pour le réemploi), installation avec la VS et avec
E3 dans une base neuve, niveaux, cas chiffré des déchets sur deux sites (déchets détournés et éliminés calculés, treize
parts recalculées à chaque niveau de l'arbre, jamais moyennées), ressources secondaires, règles de cohérence."""
import datetime
from decimal import Decimal

from django.test import SimpleTestCase, TestCase

from referentiel.bibliotheque import controle as C
from referentiel.bibliotheque import socles as S
from referentiel.bibliotheque.definitions import couverture, esrs_e5
from referentiel.models import KPI, ElementReferentiel, Organisation, Referentiel

from . import coherence as CO
from . import paquets as P
from .aides_tests.paquets import vider
from .calcul import Calculateur, recalculer
from .models import Campagne, Periode, RegleCoherence, Reponse

D = Decimal
REPRIS = {"DEC-TOTAL", "DEC-DANGEREUX", "DEC-RECYCLES", "DEC-REEMPLOI"}
PARTS = ("DETOURNES", "DET-DANG", "DET-NON-DANG", "REEMPLOI", "RECYCLAGE", "AUTRE-VALO", "ELIMINES", "ELIM-DANG",
         "ELIM-NON-DANG", "INCINERATION", "DECHARGE", "AUTRE-ELIM", "INCONNUE")


def installer(fichier):
    a = P.analyser(P.fourni(fichier).paquet, source=fichier, fourni=True)
    assert a.erreur == "" and a.compteurs["rejet"] == 0 and a.compteurs["conflit"] == 0, (a.erreur, a.compteurs)
    P.appliquer(None, a)


class ModeleRessourcesTests(SimpleTestCase):
    def test_controle_et_couverture(self):
        socle = next(s for s in S.SOCLES if s["code"] == "ESRS_E5")
        r = C.controler(socle, couverture=couverture(esrs_e5), propres=set(esrs_e5.KPIS), regles_propres=set(esrs_e5.REGLES))
        self.assertEqual(r.erreurs, [])
        self.assertEqual((r.chiffres["couverture"]["total"], r.chiffres["couverture"]["taux"]), (19, 100))
        self.assertEqual((r.chiffres["kpi"], r.chiffres["calcules"], r.chiffres["regles"]), (51, 16, 7))

    def test_kpi_repris_non_redefinis_et_kpi_distincts_non_repris(self):
        self.assertFalse(REPRIS & set(esrs_e5.KPIS))
        codes = {c for c, *_ in C.elements(esrs_e5.SOCLE)}
        self.assertTrue(REPRIS <= codes)
        # autres définitions : la valorisation du catalogue compte toute incinération avec énergie, la matière de la VS est
        # un tableau en toute unité, l'économie circulaire de la VS décrit des pratiques générales
        self.assertFalse({"DEC-VALORISES", "DEC-PART-VALO", "ECO-MATIERES", "ECO-CIRCULAIRE", "ECO-CIRCULAIRE-DESC",
                          "DEC-PAR-CODE"} & codes)

    def test_les_parts_sont_calculees_avec_l_agregation_formule(self):
        for suffixe in PARTS + ("INCONNUE",):
            d = esrs_e5.KPIS[f"DEC-PART-{suffixe}"]
            with self.subTest(suffixe):
                self.assertEqual((d["type"], d["agregation"], d["reponse"]), ("Calculé", "Formule", "Pourcentage"))
                self.assertTrue(d["formule"].endswith("/ [DEC-TOTAL]"))
        for code in ("DEC-DETOURNES", "DEC-ELIMINES"):
            self.assertEqual((esrs_e5.KPIS[code]["type"], esrs_e5.KPIS[code]["agregation"]), ("Calculé", "Somme"))

    def test_poids_dans_l_etat_d_origine_et_incineration_r1(self):
        for code in ("DEC-AUTRE-VALO", "DEC-INCINERATION", "DEC-DECHARGE", "DEC-AUTRE-ELIM", "DEC-INCONNUE", "DEC-RADIOACTIFS"):
            self.assertIn("E5 AR 5", esrs_e5.KPIS[code]["description"][1], code)
        self.assertIn("R1", esrs_e5.KPIS["DEC-AUTRE-VALO"]["description"][1])
        self.assertIn("R1", esrs_e5.KPIS["DEC-INCINERATION"]["description"][1])

    def test_une_description_cite_le_paragraphe_en_francais_et_en_anglais(self):
        bloc = {c for c, _ in esrs_e5.C.bloc_gdr(esrs_e5.PREFIXE, ("x", "x"))}  # les textes communs citent l'ESRS 2
        for code, d in esrs_e5.KPIS.items():
            fr, en = d["description"]
            with self.subTest(code):
                self.assertIn("§", fr)
                self.assertIn("§", en)
                if code not in bloc:
                    self.assertIn("E5-", en)
                    self.assertIn("E5-", fr)


class InstallationRessourcesTests(TestCase):
    """Base neuve : la VS de base d'abord, puis ESRS E5 ; Groupe › Pays › Entité › Site, deux sites."""

    @classmethod
    def setUpTestData(cls):
        vider()
        installer("vs_base.json")
        cls.avant = {c: KPI.objects.filter(code=c).values().get() for c in REPRIS}
        installer("esrs_e5.json")
        cls.g = Organisation.objects.create(nom="Groupe", niveau_id="Group")
        fr = Organisation.objects.create(nom="France", niveau_id="Country", parent=cls.g)
        e = Organisation.objects.create(nom="Entité", niveau_id="Entity", parent=fr)
        cls.a = Organisation.objects.create(nom="Usine A", niveau_id="Site", parent=e)
        cls.b = Organisation.objects.create(nom="Usine B", niveau_id="Site", parent=e)
        cls.p = Periode.objects.create(type="annee", debut=datetime.date(2026, 1, 1), fin=datetime.date(2026, 12, 31),
                                       libelle="2026")
        cls.c = Campagne.objects.create(referentiel=Referentiel.objects.get(code="ESRS_E5"), periode=cls.p, exercice=2026,
                                        statut=Campagne.Statut.OUVERTE)
        # (total, réemploi, recyclés, autres valorisations, incinération, décharge, autres éliminations, inconnue, dangereux,
        #  dangereux détournés, dangereux éliminés, radioactifs, matières clés, ressources secondaires)
        cls.donnees = {
            cls.a: dict(total=100, reemploi=5, recycles=30, autre_valo=10, incineration=20, decharge=25, autre_elim=5, inconnue=5,
                        dangereux=12, det_dang=4, elim_dang=6, radioactifs="0.012", matieres=100, secondaires=20),
            cls.b: dict(total=50, reemploi=0, recycles=10, autre_valo=5, incineration=10, decharge=15, autre_elim=0, inconnue=10,
                        dangereux=3, det_dang=1, elim_dang=2, radioactifs=0, matieres=50, secondaires=5),
        }
        cls.codes = {"total": "DEC-TOTAL", "reemploi": "DEC-REEMPLOI", "recycles": "DEC-RECYCLES", "autre_valo": "DEC-AUTRE-VALO",
                     "incineration": "DEC-INCINERATION", "decharge": "DEC-DECHARGE", "autre_elim": "DEC-AUTRE-ELIM",
                     "inconnue": "DEC-INCONNUE", "dangereux": "DEC-DANGEREUX", "det_dang": "DEC-DETOURNES-DANG",
                     "elim_dang": "DEC-ELIMINES-DANG", "radioactifs": "DEC-RADIOACTIFS", "matieres": "ECO-CIRC-MATIERES-POIDS",
                     "secondaires": "ECO-CIRC-SECONDAIRES"}
        for org, valeurs in cls.donnees.items():
            for cle, v in valeurs.items():
                Reponse.objects.create(periode=cls.p, kpi_id=cls.codes[cle], organisation=org, valeur=D(str(v)),
                                       statut=Reponse.Statut.VALIDE)
        recalculer(cls.c)

    def val(self, code, org):
        return Calculateur(self.c).valeur(code, org.id)

    def test_kpi_repris_inchanges_par_l_installation(self):
        for code, avant in self.avant.items():
            with self.subTest(code):
                self.assertEqual(KPI.objects.filter(code=code).values().get(), avant)
                self.assertEqual(set(ElementReferentiel.objects.filter(kpi_id=code).values_list("referentiel__code", flat=True)),
                                 {"VS_BASE", "ESRS_E5"})

    def test_niveaux_choisis_par_l_outil(self):
        for code in ("ECO-CIRC-MATIERES-DESC", "DEC-FLUX-DESC", "ECO-CIRC-RECYCLABILITE", "ECO-CIRC-DURABILITE"):
            self.assertEqual(KPI.objects.get(code=code).granularite_id, "Group", code)  # une réponse pour l'entreprise
        for code in ("DEC-INCINERATION", "DEC-INCONNUE", "ECO-CIRC-MATIERES-POIDS", "ECO-CIRC-MATIERES-TAB"):
            self.assertEqual(KPI.objects.get(code=code).granularite_id, "Site", code)  # mesuré au site
        self.assertEqual(KPI.objects.get(code="DEC-PART-DETOURNES").granularite_id, "Site")  # niveau de ses sources

    def test_dechets_detournes_et_elimines_calcules_et_additionnes(self):
        self.assertEqual(self.val("DEC-DETOURNES", self.a), D(45))
        self.assertEqual(self.val("DEC-DETOURNES", self.b), D(15))
        self.assertEqual(self.val("DEC-DETOURNES", self.g), D(60))
        self.assertEqual(self.val("DEC-ELIMINES", self.a), D(50))
        self.assertEqual(self.val("DEC-ELIMINES", self.b), D(25))
        self.assertEqual(self.val("DEC-ELIMINES", self.g), D(75))
        self.assertEqual(self.val("DEC-TOTAL", self.g), D(150))
        self.assertEqual(self.val("DEC-RADIOACTIFS", self.g), D("0.012"))

    def test_parts_d_un_site(self):
        attendu = {"DETOURNES": "0.45", "DET-DANG": "0.04", "DET-NON-DANG": "0.41", "REEMPLOI": "0.05", "RECYCLAGE": "0.3",
                   "AUTRE-VALO": "0.1", "ELIMINES": "0.5", "ELIM-DANG": "0.06", "ELIM-NON-DANG": "0.44", "INCINERATION": "0.2",
                   "DECHARGE": "0.25", "AUTRE-ELIM": "0.05", "INCONNUE": "0.05"}
        self.assertEqual(set(attendu), set(PARTS))
        for suffixe, v in attendu.items():
            with self.subTest(suffixe):
                self.assertEqual(self.val(f"DEC-PART-{suffixe}", self.a), D(v))

    def test_parts_du_groupe_recalculees_et_non_moyennees(self):
        # détournés : 60 / 150 = 40 %, alors que la moyenne des deux sites (45 % et 30 %) donnerait 37,5 %
        self.assertEqual(self.val("DEC-PART-DETOURNES", self.g), D("0.4"))
        self.assertEqual(self.val("DEC-PART-ELIMINES", self.g), D("0.5"))
        self.assertEqual(self.val("DEC-PART-INCONNUE", self.g), D("0.1"))
        self.assertEqual(self.val("DEC-PART-DET-NON-DANG", self.g), D(55) / D(150))  # (60 − 5) / 150
        self.assertEqual(self.val("DEC-PART-ELIM-NON-DANG", self.g), D(67) / D(150))  # (75 − 8) / 150
        # tout le tonnage est rangé : détournés + éliminés + destination inconnue = 100 %
        somme = sum(self.val(f"DEC-PART-{s}", self.g) for s in ("DETOURNES", "ELIMINES", "INCONNUE"))
        self.assertEqual(somme, D(1))

    def test_ressources_secondaires(self):
        self.assertEqual(self.val("ECO-CIRC-PART-SECONDAIRES", self.a), D("0.2"))
        self.assertEqual(self.val("ECO-CIRC-PART-SECONDAIRES", self.b), D("0.1"))
        self.assertEqual(self.val("ECO-CIRC-PART-SECONDAIRES", self.g), D(25) / D(150))

    def alertes(self):
        return {(a["regle"].nom, a["org"].id) for a in CO.controles_regles(self.c)}

    def test_regles_respectees_sur_les_donnees_justes(self):
        self.assertEqual(set(esrs_e5.REGLES) - set(RegleCoherence.objects.values_list("nom", flat=True)), set())  # les sept
        self.assertEqual(self.alertes(), set())

    def test_regles_non_respectees(self):
        Reponse.objects.filter(kpi_id="DEC-INCONNUE", organisation=self.b).update(valeur=D(15))  # 15 + 25 + 15 > 50
        Reponse.objects.filter(kpi_id="DEC-DETOURNES-DANG", organisation=self.a).update(valeur=D(8))  # 8 + 6 > 12
        Reponse.objects.filter(kpi_id="ECO-CIRC-SECONDAIRES", organisation=self.a).update(valeur=D(120))
        recalculer(self.c)
        self.assertEqual(self.alertes(), {("Déchets détournés + éliminés + destination inconnue ≤ déchets générés", self.b.id),
                                          ("Déchets dangereux détournés + éliminés ≤ déchets dangereux", self.a.id),
                                          ("Ressources secondaires ≤ poids des matières clés", self.a.id)})

    def test_dechets_encore_stockes_sans_fausse_alerte(self):
        """Un déchet généré dans la période et encore stocké sur le site à la clôture n'a pas de destination : 15 + 25 + 5
        < 50, sans alerte (l'ancienne règle « = » en donnait une)."""
        Reponse.objects.filter(kpi_id="DEC-INCONNUE", organisation=self.b).update(valeur=D(5))
        recalculer(self.c)
        self.assertNotIn(self.b.id, {org for nom, org in self.alertes() if nom.startswith("Déchets détournés + éliminés")})

    def test_tableaux_de_produits_et_de_matieres(self):
        from parametres.models import TypeReponse

        t = TypeReponse.objects.get(code=KPI.objects.get(code="ECO-CIRC-RECYCLABILITE").type_reponse_id)
        self.assertEqual((t.format, [c["code"] for c in t.colonnes]), (TypeReponse.Format.TABLEAU, ["produit", "taux_produit",
                                                                                                    "taux_emballage"]))
        t = TypeReponse.objects.get(code=KPI.objects.get(code="ECO-CIRC-MATIERES-TAB").type_reponse_id)
        self.assertEqual([(c["code"], c.get("unite")) for c in t.colonnes], [("matiere", None), ("poids", "t")])
