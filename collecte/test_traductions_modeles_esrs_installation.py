"""Installation des onze modèles ESRS dans une installation dont la langue de référence est l'une des cinq langues ajoutées
(espagnol, allemand, italien, néerlandais, portugais) : les noms des KPI, des thèmes, des types de réponse, des colonnes de
tableau et des règles, et les descriptions complètes, sont ceux de cette langue ; dans une installation en français, les cinq
langues sont dans les traductions des contenus (rien de plus en base que ce que l'installation d'un paquet y met déjà)."""
import json

from django.test import TestCase

from parametres import langues as L
from parametres.models import Instance, Langue, TypeReponse
from referentiel.bibliotheque import socles as S
from referentiel.bibliotheque import traductions as T
from referentiel.models import KPI, Description, Referentiel, Theme

from . import paquets as P
from .aides_tests.paquets import vider
from .models import RegleCoherence
from .regles_textes import traduire

FICHIERS = [s["fichier"] for s in S.SOCLES if s.get("traductions") == "esrs"]
LANGUES = T.LANGUES


def paquets():
    return [json.loads((P.BIBLIOTHEQUE / f).read_text(encoding="utf-8")) for f in FICHIERS]


def installer_les_onze():
    for fichier in FICHIERS:
        a = P.analyser(P.fourni(fichier).paquet, source=fichier, fourni=True)
        assert a.erreur == "" and a.compteurs["rejet"] == 0 and a.compteurs["conflit"] == 0, (fichier, a.erreur, a.compteurs)
        P.appliquer(None, a, sans_recalcul=True)


def _installation_en(langue):
    i = Instance.courante()
    i.langue_reference = langue
    i.langue = langue
    i.save()
    vider()


class ApresLaNormeVsTests(TestCase):
    def test_un_kpi_repris_de_la_norme_vs_n_est_pas_un_conflit(self):
        """Les traductions que le modèle ESRS apporte à un KPI déjà installé par la norme VS sont un ajout, pas un désaccord."""
        vider()
        for fichier in ("vs_base.json", "esrs_e3.json"):
            a = P.analyser(P.fourni(fichier).paquet, source=fichier, fourni=True)
            self.assertEqual((a.erreur, a.compteurs["rejet"], a.compteurs["conflit"]), ("", 0, 0), fichier)
            P.appliquer(None, a, sans_recalcul=True)


class InstallationEnFrancaisTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        vider()
        installer_les_onze()

    def test_les_cinq_langues_sont_dans_les_traductions_des_contenus(self):
        for d in paquets():
            for k in d["kpis"]:
                kpi = KPI.objects.get(code=k["code"])
                for lg in LANGUES:
                    attendu = k["libelle"][lg]
                    # un KPI repris d'un autre modèle (norme VS) garde le texte déjà installé : seulement présent
                    self.assertTrue((kpi.traductions.get(lg) or {}).get("libelle"), (k["code"], lg))
                    if k["code"].split("-")[0] not in ("GES", "NRJ", "CONV"):
                        self.assertEqual(kpi.traductions[lg]["libelle"], attendu, (k["code"], lg))

    def test_langues_creees_inactives_avec_leur_nom(self):
        for lg in LANGUES:
            langue = Langue.objects.get(code=lg)
            self.assertFalse(langue.active, lg)
            self.assertEqual(langue.libelle, T.LIBELLES_LANGUES[lg])

    def test_themes_et_descriptions_dans_les_cinq_langues(self):
        for d in paquets():
            ref = Referentiel.objects.get(code=d["referentiel"]["code"])
            for t in d["themes"]:
                theme = Theme.objects.get(referentiel=ref, code=t["code"])
                for lg in LANGUES:
                    self.assertEqual(theme.traductions[lg]["nom"], t["nom"][lg], (t["code"], lg))
            for k in d["kpis"]:
                for lg in LANGUES:
                    for cat, texte in (k["descriptions"].get(lg) or {}).items():
                        self.assertTrue(Description.objects.filter(kpi__code=k["code"], categorie__code=cat, langue=lg).exists(),
                                        (k["code"], cat, lg))

    def test_regle_lue_dans_la_langue_de_la_personne(self):
        d = next(d for d in paquets() if d["referentiel"]["code"] == "ESRS_E1")
        regle = d["regles"][0]
        enregistre = RegleCoherence.objects.get(nom=regle["nom"])
        for lg in LANGUES:
            self.assertEqual(traduire(enregistre.nom, "nom", lg), regle["traductions"][lg]["nom"], lg)


def _classe_installation(langue):
    class InstallationDansLaLangue(TestCase):
        @classmethod
        def setUpTestData(cls):
            _installation_en(langue)
            installer_les_onze()

        def test_noms_dans_la_langue_de_l_installation(self):
            self.assertEqual(L.reference(), langue)
            for d in paquets():
                ref = Referentiel.objects.get(code=d["referentiel"]["code"])
                self.assertEqual(ref.nom, d["referentiel"]["nom"][langue])
                for t in d["themes"]:
                    self.assertEqual(Theme.objects.get(referentiel=ref, code=t["code"]).nom, t["nom"][langue], t["code"])
                for k in d["kpis"]:
                    if k["code"].split("-")[0] not in ("GES", "NRJ", "CONV"):  # repris de la norme VS : texte déjà installé
                        self.assertEqual(KPI.objects.get(code=k["code"]).libelle, k["libelle"][langue], k["code"])

        def test_types_colonnes_et_listes_dans_la_langue(self):
            for d in paquets():
                for t in d["types_reponse"]:
                    if t["format"] == "tableau":
                        installe = TypeReponse.objects.get(code=t["code"][:20])  # l'installation coupe les codes à 20 caractères
                        for c, colonne in zip(installe.colonnes, t["colonnes"]):
                            self.assertEqual(c["libelle"].get(langue), colonne["libelle"][langue], (t["code"], c["code"]))
                    if t["format"] == "liste" and (t["valeurs"] or {}).get("en") and t["code"].startswith("ESRS"):
                        installe = TypeReponse.objects.get(code=t["code"][:20])
                        self.assertEqual((installe.traductions.get(langue) or {}).get("valeurs"), t["valeurs"][langue], t["code"])

        def test_regles_enregistrees_dans_la_langue(self):
            for d in paquets():
                for r in d["regles"]:
                    attendu = r["traductions"][langue]["nom"]
                    self.assertTrue(RegleCoherence.objects.filter(nom=attendu).exists(), (d["referentiel"]["code"], attendu))

    return type(f"Installation_{langue}_Tests", (InstallationDansLaLangue,), {})


Installation_es_Tests = _classe_installation("es")
Installation_de_Tests = _classe_installation("de")
Installation_it_Tests = _classe_installation("it")
Installation_nl_Tests = _classe_installation("nl")
Installation_pt_Tests = _classe_installation("pt")
