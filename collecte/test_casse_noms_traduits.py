"""Un nom qui vient d'un réglage ou d'une traduction (statut, rôle, fréquence, nom de niveau…) n'est jamais passé en
minuscules au milieu d'une phrase : en allemand, « Erfassung offen », « Standort » ou « Administrator » perdraient leur
majuscule. Quand une langue veut la minuscule, son libellé la porte (clés « choix.phrase.* »)."""
import re
from pathlib import Path

from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from parametres import libelles as LB
from parametres.models import Langue
from referentiel.models import Niveau, Organisation, Referentiel, Utilisateur

from .models import Campagne

RACINE = Path(__file__).resolve().parent.parent
IGNORES = ("references/", "/migrations/", "aides_tests/", "qa/", "publication/", "portable/", "/test_")
# un passage en minuscules appliqué à un libellé de liste de choix ou à un nom de niveau
MOTIFS = (
    re.compile(r"\|choix:\"[a-z_]+\"\|lower"),
    re.compile(r"(niveau|libelle_un|bas\.libelle|\bn\.libelle)\s*\|lower"),
    re.compile(r"choix(_valeur)?\([^()]*(\([^()]*\))?[^()]*\)\s*\)?\.lower\(\)"),
    re.compile(r"\.tr\([^)]*\)\.lower\(\)"),
)


def fichiers():
    for p in sorted(RACINE.rglob("*")):
        r = str(p.relative_to(RACINE))
        if p.suffix in (".html", ".py") and not any(m in "/" + r for m in IGNORES) and ".claude" not in r:
            yield r, p


class AucunPassageEnMinusculesTests(SimpleTestCase):
    def test_aucun_gabarit_ni_module_ne_met_un_nom_traduit_en_minuscules(self):
        trouves = []
        for r, p in fichiers():
            for i, ligne in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1):
                if "data-texte" not in ligne and any(m.search(ligne) for m in MOTIFS):  # data-texte : texte de recherche
                    trouves.append(f"{r}:{i}")
        self.assertEqual(trouves, [])


class ChoixAuMilieuDUnePhraseTests(SimpleTestCase):
    def test_statuts_par_langue(self):
        attendu = {
            "en": ("closed", "open for data entry", "in preparation", "review"),
            "fr": ("clôturée", "saisie ouverte", "en préparation", "revue"),
            "es": ("cerrada", "captura abierta", "en preparación", "revisión"),
            "de": ("abgeschlossen", "Erfassung offen", "in Vorbereitung", "Prüfung"),  # noms : majuscule
            "it": ("chiusa", "inserimento aperto", "in preparazione", "revisione"),
            "nl": ("afgesloten", "invoer open", "in voorbereiding", "review"),
            "pt": ("encerrada", "aberta à introdução de dados", "em preparação", "revisão"),
        }
        for langue, textes in attendu.items():
            obtenus = tuple(LB.choix_valeur_phrase(Campagne, "statut", v, langue) for v in ("cloturee", "ouverte", "preparation", "revue"))
            with self.subTest(langue=langue):
                self.assertEqual(obtenus, textes)

    def test_roles_allemands_gardent_leur_majuscule(self):
        for valeur, texte in (("admin", "Administrator"), ("contributeur", "Mitwirkender"), ("lecteur", "Leser"),
                              ("validateur", "Validator"), ("auditeur", "Auditor")):
            self.assertEqual(LB.choix_valeur_phrase(Utilisateur, "role", valeur, "de"), texte)
            self.assertEqual(LB.choix_valeur_phrase(Utilisateur, "role", valeur, "fr"), LB.choix_valeur(Utilisateur, "role", valeur, "fr").lower())

    def test_frequences_allemandes_adjectifs_en_minuscules(self):
        self.assertEqual([LB.choix_valeur_phrase(Referentiel, "frequence", v, "de") for v in ("annee", "mois", "semestre", "trimestre")],
                         ["jährlich", "monatlich", "halbjährlich", "vierteljährlich"])

    def test_valeur_sans_forme_de_phrase_garde_son_libelle_tel_quel(self):
        self.assertEqual(LB.choix_valeur_phrase(Campagne, "statut", "inconnue", "de"), "inconnue")
        self.assertEqual(LB.choix_valeur_phrase("alerte", "statut", "ouverte", "de"), LB.choix_valeur("alerte", "statut", "ouverte", "de"))


class PagesAllemandesTests(TestCase):
    def setUp(self):
        Langue.objects.get_or_create(code="de", defaults={"libelle": "Deutsch", "ordre": 9})
        Organisation.objects.create(nom="Alfa", niveau_id=Niveau.GROUP)
        self.admin = Utilisateur.objects.create(username="admin", email="admin@exemple.test", role=Utilisateur.Role.ADMIN, langue="de")
        self.lecteur = Utilisateur.objects.create(username="lecteur", email="lecteur@exemple.test", role=Utilisateur.Role.LECTEUR, langue="de")

    def test_liste_des_organisations_noms_de_niveau_avec_majuscule(self):
        self.client.force_login(self.admin)
        page = self.client.get(reverse("collecte:admin_organisations")).content.decode()
        self.assertRegex(page, r"<strong>1</strong> Konzern")
        self.assertNotIn("konzern</span>", page)

    def test_motif_de_refus_cite_le_role_avec_sa_majuscule(self):
        from .lecture_seule import motif_refus_page

        from parametres import langues as L

        with L.activer("de"):
            motif = motif_refus_page(self.lecteur, "parametres", "identite", "GET")
        self.assertIn("(Leser)", motif)
