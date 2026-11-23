"""Aides des tests des paquets référentiels : base (référentiel « R1 »), fichier, KPI d'un paquet, base vidée."""
import io

from django.test import TestCase

from collecte import paquets as P
from collecte.models import RegleCoherence
from parametres import niveaux as N, referentiel as PR
from parametres.models import CategorieDescription, ChampPersonnalise, NiveauHierarchique, TypeReponse, TypeSaisie, Unite
from referentiel.echange import enregistrer_descriptions
from referentiel.models import Description, ElementReferentiel, KPI, KPIFormule, Referentiel, Theme, Utilisateur


def fichier(p, nom="paquet.xlsx"):
    flux = io.BytesIO()
    P.classeur(p).save(flux)
    flux.seek(0)
    flux.name = nom
    return flux


def kp(p, code):
    return next(k for k in p.kpis if k["code"] == code)


def vider():
    """Base vide : ni référentiel, ni KPI, ni règle ; réglages et niveaux d'installation."""
    RegleCoherence.objects.all().delete()
    ElementReferentiel.objects.all().delete()
    Theme.objects.all().delete()
    Referentiel.objects.all().delete()
    KPIFormule.objects.all().delete()
    Description.objects.all().delete()
    KPI.objects.all().delete()
    for m in (ChampPersonnalise, CategorieDescription, TypeReponse, TypeSaisie, Unite, NiveauHierarchique):
        m.objects.all().delete()
    N.creer_par_defaut()
    PR.creer_par_defaut()


class Base(TestCase):
    """Référentiel « R1 » : Énergie › Électricité (A, B, C = A + B), Climat (D = A × FE1) ; FE1 (facteur d'émission) n'est
    que la source d'une formule ; une règle A ≤ B ; un KPI oui / non ; traductions et descriptions."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = Utilisateur.objects.create_user("admin", "admin@exemple.test", "x", role=Utilisateur.Role.ADMIN)
        Unite.objects.get_or_create(code="kWh", defaults={"symbole": "kWh"})
        Unite.objects.get_or_create(code="kgCO2e", defaults={"symbole": "kgCO2e"})
        cls.ouinon = TypeReponse.objects.create(code="OuiNon", libelle="Oui / non", format="oui_non", traductions={"en": {"valeurs": ["Yes", "No"]}})

        def kpi(code, nom, t="Saisi", f="", unite="kWh", niveau="Site", agg="Somme", reponse="Numérique"):
            return KPI.objects.create(code=code, libelle=nom, type_saisie_id=t, formule=f, unite_id=unite or None, granularite_id=niveau,
                                      methode_agregation=agg, type_reponse_id=reponse)
        cls.a = kpi("A", "Électricité")
        cls.a.traductions = {"en": {"libelle": "Electricity"}}
        cls.a.save()
        enregistrer_descriptions(cls.a, {"description": "Électricité consommée.", "source": "Factures."})
        kpi("B", "Gaz")
        kpi("C", "Énergie totale", "Calculé", "[A] + [B]")
        kpi("FE1", "Facteur d'émission", "FE", unite="", niveau="Group", agg="Aucune")
        kpi("D", "Émissions", "Calculé", "[A] * [FE1]", unite="kgCO2e")
        kpi("Q", "Audit réalisé", unite="", niveau="Entity", agg="Décompte", reponse="OuiNon")
        cls.r1 = Referentiel.objects.create(code="R1", nom="Référentiel un", traductions={"en": {"nom": "Framework one"}}, version="1.0")
        energie = Theme.objects.create(referentiel=cls.r1, code="ENERGIE", nom="Énergie", ordre=1)
        elec = Theme.objects.create(referentiel=cls.r1, code="ELEC", nom="Électricité", parent=energie, ordre=1)
        climat = Theme.objects.create(referentiel=cls.r1, code="CLIMAT", nom="Climat", ordre=2, traductions={"en": {"nom": "Climate"}})
        for i, (code, theme) in enumerate([("A", elec), ("B", elec), ("C", energie), ("D", climat), ("Q", climat)], start=1):
            ElementReferentiel.objects.create(referentiel=cls.r1, kpi_id=code, theme=theme, ordre=i, obligatoire=code != "Q")
        RegleCoherence.objects.create(nom="A ≤ B", gauche="[A]", operateur="<=", droite="[B]", niveau_id="Site")

    def setUp(self):
        self.client.force_login(self.admin)
