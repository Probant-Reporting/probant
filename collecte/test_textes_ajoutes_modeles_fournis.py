"""Modèles de la bibliothèque qui partagent des KPI et des types de réponse (norme VS, ESRS) dans une installation dont la
langue de référence est l'une des cinq langues ajoutées (``textes_ajoutes``) : quand le KPI déjà installé n'a pas de texte
propre dans la langue de référence (son champ porte le texte d'une autre langue), le texte que le modèle apporte est un
ajout, pas un conflit, dans les deux sens d'installation ; un texte saisi dans l'installation n'est jamais remplacé. Un même KPI a un seul libellé par langue (démo comprise)."""
from django.test import SimpleTestCase, TestCase

from parametres import langues as L
from parametres.models import Instance, TypeReponse
from referentiel.bibliotheque.traductions import LANGUES
from referentiel.models import KPI, Referentiel

from . import paquets as P
from .aides_tests.paquets import vider


def _en(langue):
    i = Instance.courante()
    i.langue_reference, i.langue = langue, langue
    i.save()
    vider()


def _installer(test, *fichiers):
    for fichier in fichiers:
        a = P.analyser(P.fourni(fichier).paquet, source=fichier, fourni=True)
        test.assertEqual((a.erreur, a.compteurs["rejet"], a.compteurs["conflit"]), ("", 0, 0), (fichier, L.reference()))
        P.appliquer(None, a, sans_recalcul=True)


def _libelle(fichier, code, lg):
    return next(k for k in P.fourni(fichier).paquet.kpis if k["code"] == code)["libelle"][lg]


class EnchainementTests(TestCase):
    def test_norme_vs_puis_esrs_dans_les_cinq_langues(self):
        for lg in LANGUES:
            with self.subTest(langue=lg):
                _en(lg)
                _installer(self, "vs_base.json", "esrs_e1.json", "esrs_s1.json")
                k = KPI.objects.get(code="NRJ-CHALEUR")
                self.assertEqual(k.libelle, _libelle("esrs_e1.json", "NRJ-CHALEUR", lg))
                self.assertEqual(k.traductions["fr"]["libelle"], "Chaleur et vapeur achetées")
                self.assertEqual(KPI.objects.get(code="SOC-EFFECTIF").libelle, _libelle("esrs_s1.json", "SOC-EFFECTIF", lg))

    def test_meme_resultat_dans_les_deux_sens(self):
        etats = []
        for ordre in (("vs_base.json", "esrs_e1.json", "esrs_e2.json"), ("esrs_e1.json", "esrs_e2.json", "vs_base.json")):
            _en("de")
            _installer(self, *ordre)
            # textes de la langue de référence (les autres langues d'un KPI repris restent celles du premier modèle)
            kpis = {k.code: k.libelle for k in KPI.objects.filter(elements__referentiel__code="ESRS_E1").distinct()}
            types = {t.code: (t.libelle, ((t.traductions or {}).get("de") or {}).get("valeurs"),
                              [c["libelle"].get("de") for c in t.colonnes or []])
                     for t in TypeReponse.objects.filter(code__startswith="VS-")}
            etats.append((kpis, types))
        self.assertEqual(etats[0][0], etats[1][0])
        self.assertEqual(etats[0][1], etats[1][1])
        # type de réponse repris (tableau de la norme VS, code abrégé à 20 caractères) : nom et colonnes en allemand
        t = TypeReponse.objects.get(code="VS-TAB-POLLUANTS-AUT")
        self.assertEqual(t.libelle, "Emissionen sonstiger Schadstoffe")
        self.assertTrue(all(c["libelle"].get("de") for c in t.colonnes))

    def test_mise_a_jour_a_l_identique_sans_difference(self):
        _en("it")
        _installer(self, "vs_base.json", "esrs_e1.json")
        for fichier in ("vs_base.json", "esrs_e1.json"):
            pq = P.fourni(fichier).paquet
            ref = Referentiel.objects.get(identifiant=pq.referentiel["identifiant"])
            a, _ = P.analyser_installation(pq, [k["code"] for k in pq.kpis], existant=ref, nouvelle_version=True)
            self.assertTrue(a.aucune_difference, fichier)

    def test_un_texte_saisi_dans_l_installation_reste_un_conflit(self):
        _en("es")
        _installer(self, "vs_base.json")
        KPI.objects.filter(code="NRJ-CHALEUR").update(libelle="Calor comprado (nuestro texto)")
        a = P.analyser(P.fourni("esrs_e1.json").paquet, source="esrs_e1.json", fourni=True)
        ligne = next(l for l in a.kpis if l.code == "NRJ-CHALEUR")
        self.assertEqual((ligne.statut, ligne.choix), ("conflit", "reutiliser"))
        self.assertEqual(a.compteurs["conflit"], 1)
        P.appliquer(None, a, sans_recalcul=True)
        self.assertEqual(KPI.objects.get(code="NRJ-CHALEUR").libelle, "Calor comprado (nuestro texto)")


class LibelleUniqueDemoTests(SimpleTestCase):
    def test_libelles_de_la_demo_identiques_a_ceux_des_esrs(self):
        """Un KPI de la norme VS repris par un modèle ESRS : la démo lui donne le libellé du modèle ESRS dans chaque langue."""
        import json

        from collecte.management.commands import _exemplia_bibliotheque as BIB
        from referentiel.bibliotheque import socles as S

        esrs = {}
        for s in S.SOCLES:
            if s.get("traductions") == "esrs":
                d = json.loads((P.BIBLIOTHEQUE / s["fichier"]).read_text(encoding="utf-8"))
                esrs.update({k["code"]: k["libelle"] for k in d["kpis"]})
        ecarts = [(code, lg, nom, esrs[code][lg]) for code, noms in BIB.KPI.items() if code in esrs
                  for lg, nom in zip(BIB.LANGUES, noms) if esrs[code].get(lg) and esrs[code][lg] != nom]
        self.assertEqual(ecarts, [])
