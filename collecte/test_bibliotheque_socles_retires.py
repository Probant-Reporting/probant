"""Bibliothèque réduite à la norme VS (règle du projet) : les socles Énergie, Gaz à effet de serre, Social
et ESRS simplifié sortent de l'offre. Une installation qui en avait installé un garde son référentiel entier et
utilisable (KPI, valeurs, formules, historique) ; rien ne plante et rien ne propose une mise à jour vers un modèle absent :
pages, installation, composition, import et export, commande ``paquet``, calculs."""
import datetime
import types
import uuid
from decimal import Decimal
from io import StringIO
from unittest import mock

from django.core.management import CommandError, call_command
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from parametres import niveaux as N
from referentiel.bibliotheque import socles as S
from referentiel.models import KPI, ElementReferentiel, Niveau, Organisation, Referentiel, Utilisateur

from . import paquets as P
from . import periodes as PE
from .aides_tests.bibliotheque_essai import avec_socles_retires, paquet_retire
from .aides_tests.paquets import vider
from .calcul import recalculer
from .models import Campagne, Journal, Reponse

FETCH = {"HTTP_X_REQUESTED_WITH": "fetch"}
RETIRES = ("SOCLE_ENERGIE", "SOCLE_ESRS", "SOCLE_GES", "SOCLE_SOCIAL")
# Les onze modèles des ESRS révisées, triés comme la bibliothèque (ordre des codes)
ESRS = (
    "ESRS_2",
    "ESRS_E1",
    "ESRS_E2",
    "ESRS_E3",
    "ESRS_E4",
    "ESRS_E5",
    "ESRS_G1",
    "ESRS_S1",
    "ESRS_S2",
    "ESRS_S3",
    "ESRS_S4",
)
# Ordre de la liste des modèles (champ « ordre » : ESRS 2, E1 à E5, S1 à S4, G1)
ESRS_ORDRE = (
    "ESRS_2",
    "ESRS_E1",
    "ESRS_E2",
    "ESRS_E3",
    "ESRS_E4",
    "ESRS_E5",
    "ESRS_S1",
    "ESRS_S2",
    "ESRS_S3",
    "ESRS_S4",
    "ESRS_G1",
)


class BibliothequeFournieTests(TestCase):
    def test_norme_vs_et_transparence_des_remunerations(self):
        """Bibliothèque : la norme VS, la transparence des rémunérations et les onze modèles des ESRS révisées."""
        self.assertEqual([f.paquet.code for f in P.bibliotheque()], [*ESRS, "TRANSPARENCE_REMU", "VS_BASE", "VS_COMPLET"])
        self.assertEqual(sorted(c.name for c in P.BIBLIOTHEQUE.glob("*.json")), [
            *(f"{c.lower()}.json" for c in ESRS),
            "transparence_remunerations.json",
            "vs_base.json",
            "vs_complet.json",
        ])
        self.assertEqual([s["code"] for s in S.SOCLES], ["VS_BASE", "VS_COMPLET", "TRANSPARENCE_REMU", *ESRS_ORDRE])

    def test_les_socles_retires_restent_des_jeux_d_essai(self):
        """Hors de la bibliothèque, leurs paquets se construisent toujours, à l'identique (identifiant, version, date)."""
        with avec_socles_retires():
            codes = [f.paquet.code for f in P.bibliotheque()]
        self.assertEqual(codes, [*ESRS, *RETIRES, "TRANSPARENCE_REMU", "VS_BASE", "VS_COMPLET"])
        p = paquet_retire("SOCLE_GES")
        self.assertEqual((p.version, p.date_version), ("1.0", datetime.date(2026, 11, 12)))
        self.assertEqual(p.referentiel["identifiant"], str(uuid.uuid5(S.ESPACE, "SOCLE_GES")))


class CodeRetireReserveTests(SimpleTestCase):
    def test_code_ou_fichier_d_un_socle_retire_refuse(self):
        """Même code = même identifiant : un nouveau modèle qui reprendrait un code retiré serait vu comme une mise à jour
        par les installations qui avaient ce socle. Le contrôle le refuse (conflit : rien n'est généré)."""
        from referentiel.bibliotheque import definitions as D

        for champs in ({"code": "SOCLE_GES", "fichier": "ges.json"}, {"code": "GES_NOUVEAU", "fichier": "socle_ges.json"}):
            faux = types.SimpleNamespace(__name__="referentiel.bibliotheque.definitions.faux",
                                         SOCLE={"arbre": [], "regles": [], **champs})
            with self.subTest(**champs), mock.patch.object(D, "charger", return_value=[faux]):
                self.assertTrue(any("déjà pris" in c for c in S._fusionner()))
        self.assertEqual([s["code"] for s in S.SOCLES], ["VS_BASE", "VS_COMPLET", "TRANSPARENCE_REMU", *ESRS_ORDRE])


class InstallationQuiAvaitUnSocleRetireTests(TestCase):
    """Base d'une installation existante : Gaz à effet de serre et Social installés depuis l'ancienne bibliothèque, VS de
    base aussi, une campagne 2025 saisie et calculée. Puis le code nouveau : la bibliothèque n'a plus que la VS."""

    @classmethod
    def setUpTestData(cls):
        N.creer_par_defaut()
        cls.admin = Utilisateur.objects.create_user("admin", "admin@exemple.test", "x", role=Utilisateur.Role.ADMIN)
        groupe = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        pays = Organisation.objects.create(nom="France", niveau_id=Niveau.COUNTRY, parent=groupe)
        entite = Organisation.objects.create(nom="Entité", niveau_id=Niveau.ENTITY, parent=pays)
        cls.site = Organisation.objects.create(nom="Site", niveau_id=Niveau.SITE, parent=entite)
        with avec_socles_retires():
            for f in ("socle_ges.json", "socle_social.json", "vs_base.json"):
                a = P.analyser(P.fourni(f).paquet, source=f, fourni=True)
                assert a.erreur == "", a.erreur
                P.appliquer(cls.admin, a)
        cls.social = Referentiel.objects.get(code="SOCLE_SOCIAL")
        cls.campagne, _ = PE.campagne(cls.social, datetime.date(2025, 1, 1), statut=Campagne.Statut.OUVERTE)
        for code, v in (("SOC-EFFECTIF", 200), ("SOC-EFF-FEMMES", 80)):
            Reponse.objects.create(periode=cls.campagne.periode, kpi_id=code, organisation=cls.site, valeur=Decimal(v),
                                   statut=Reponse.Statut.VALIDE, saisi_par=cls.admin)
        recalculer(cls.campagne)

    def setUp(self):
        self.client.force_login(self.admin)

    def part_femmes(self):
        return Reponse.objects.get(periode=self.campagne.periode, kpi_id="SOC-PART-FEMMES", organisation=self.site).valeur

    def test_referentiels_entiers_et_calculables(self):
        for code in ("SOCLE_GES", "SOCLE_SOCIAL"):
            ref = Referentiel.objects.get(code=code)
            p = paquet_retire(code)
            self.assertEqual((ref.origine, ref.version, ref.date_version), (Referentiel.Origine.FOURNI, "1.0", datetime.date(2026, 11, 12)))
            self.assertEqual(set(ElementReferentiel.objects.filter(referentiel=ref).values_list("kpi_id", flat=True)),
                             {k["code"] for k in p.kpis})
        self.assertEqual(KPI.objects.get(pk="SOC-PART-FEMMES").formule, "[SOC-EFF-FEMMES] / [SOC-EFFECTIF]")
        self.assertEqual(self.part_femmes(), Decimal("0.4"))
        recalculer(self.campagne)  # code nouveau : même résultat
        self.assertEqual(self.part_femmes(), Decimal("0.4"))
        self.assertTrue(Journal.objects.filter(objet_id="SOCLE_GES", action="import_paquet").exists())  # historique gardé

    def test_aucune_mise_a_jour_proposee_vers_un_modele_absent(self):
        fournis = P.bibliotheque()
        self.assertEqual([f.paquet.code for f in fournis], [*ESRS, "TRANSPARENCE_REMU", "VS_BASE", "VS_COMPLET"])
        installes = {f.installe.code for f in fournis if f.installe is not None}
        self.assertEqual(installes, {"VS_BASE"})
        self.assertEqual({f.etat for f in fournis}, {"a_jour", "absent"})
        html = self.client.get(reverse("parametres:referentiels")).content.decode()
        for code in ("SOCLE_GES", "SOCLE_SOCIAL"):
            self.assertNotIn(reverse("parametres:installer_kpi", args=[code]), html)
        self.assertNotIn("maj-dispo", html)  # aucune étiquette « Mise à jour » sur la page Référentiels

    def test_pages_du_referentiel_et_de_la_bibliotheque(self):
        for nom in ("referentiel_contenu", "referentiel_partage", "referentiel_reglages", "referentiel_liste", "referentiel_choisir"):
            with self.subTest(page=nom):
                self.assertEqual(self.client.get(reverse(f"parametres:{nom}", args=["SOCLE_GES"])).status_code, 200)
        html = self.client.get(reverse("parametres:referentiel_contenu", args=["SOCLE_GES"])).content.decode()
        self.assertIn("version 1.0 du 12/11/2026", html)
        self.assertNotIn("socle_ges.json", html)  # le tiroir « Ajouter depuis… » ne propose plus le modèle retiré
        for nom in ("installer_modeles", "referentiel_nouveau"):
            with self.subTest(page=nom):
                rep = self.client.get(reverse(f"parametres:{nom}"))
                self.assertEqual(rep.status_code, 200)
                self.assertNotContains(rep, "Gaz à effet de serre – scopes")
        self.assertEqual(self.client.get(reverse("collecte:referentiel") + "?ref=SOCLE_GES").status_code, 200)
        self.assertEqual(self.client.get(reverse("collecte:saisie")).status_code, 200)

    def test_liens_et_formulaires_d_avant_la_mise_a_jour(self):
        """Page ouverte avant la mise à jour, signet, session en cours : jamais d'erreur 500."""
        for nom in ("installer_kpi", "installer_resume"):
            self.assertEqual(self.client.get(reverse(f"parametres:{nom}", args=["SOCLE_GES"])).status_code, 404)
        self.assertRedirects(self.client.get(reverse("parametres:paquet_fourni", args=["socle_ges.json"])),
                             reverse("parametres:referentiel_nouveau"), fetch_redirect_response=False)
        rep = self.client.post(reverse("parametres:paquet_importer"), {"action": "verifier", "bibliotheque": "socle_ges.json"})
        self.assertRedirects(rep, reverse("parametres:referentiel_nouveau"), fetch_redirect_response=False)
        session = self.client.session
        session["import_paquet"] = {"bibliotheque": "socle_social.json"}
        session.save()
        self.assertRedirects(self.client.get(reverse("parametres:paquet_importer")), reverse("parametres:referentiel_nouveau"),
                             fetch_redirect_response=False)
        rep = self.client.post(reverse("parametres:referentiel_contenu_action", args=["SOCLE_SOCIAL"]),
                               {"action": "deposer", "source": {"type": "kpi", "bib": "socle_energie.json", "code": "NRJ-GAZ"}},
                               content_type="application/json", **FETCH)
        self.assertLess(rep.status_code, 500)
        self.assertFalse(rep.json()["ok"])
        with self.assertRaises(CommandError):
            call_command("paquet", "import", "socle_ges.json", "--library", stdout=StringIO())

    def test_export_puis_import_du_referentiel(self):
        """Le fichier exporté cite le code du socle : il se relit ici (rien à changer) et s'installe dans une base vide."""
        rep = self.client.get(reverse("parametres:paquet_exporter", args=["SOCLE_GES"]))
        self.assertEqual(rep.status_code, 200)
        brut = rep.content
        p = P.lire(_fichier(brut))
        self.assertEqual((p.code, p.referentiel.get("origine")), ("SOCLE_GES", "fourni"))
        self.assertIn("Gaz à effet de serre", p.nom())
        a = P.analyser(p)
        self.assertEqual((a.erreur, a.mode), ("", "mise_a_jour"))
        self.assertTrue(a.aucune_difference)
        Reponse.objects.all().delete()
        Campagne.objects.all().delete()
        for niveau in (Niveau.SITE, Niveau.ENTITY, Niveau.COUNTRY, Niveau.GROUP):
            Organisation.objects.filter(niveau_id=niveau).delete()
        vider()
        a = P.analyser(P.lire(_fichier(brut)))
        self.assertEqual((a.erreur, a.mode, a.compteurs["rejet"]), ("", "nouveau", 0))
        ref = P.appliquer(None, a).referentiel
        self.assertEqual((ref.code, ref.origine), ("SOCLE_GES", Referentiel.Origine.IMPORTE))
        self.assertEqual(KPI.objects.get(pk="GES-S1").formule, "[GES-S1-FIXE] + [GES-S1-MOBILE] + [GES-FUGITIVES]")


def _fichier(octets):
    from django.core.files.uploadedfile import SimpleUploadedFile

    return SimpleUploadedFile("socle_ges.xlsx", octets)


class UnitesMalRangeesSocleRetireTests(TestCase):
    """Contrôle des unités mal rangées par l'ancien rapprochement (``unites_mal_rapprochees``) : les KPI d'un socle
    retiré, encore présents dans une installation, restent couverts (détectés, puis corrigés sans toucher aux valeurs)."""

    def test_kpi_d_un_socle_retire_detecte_et_corrige(self):
        from parametres.models import Unite

        from . import unites_mal_rapprochees as UM

        N.creer_par_defaut()
        with avec_socles_retires():
            P.appliquer(None, P.analyser(P.fourni("socle_energie.json").paquet, fourni=True))
        self.assertIn("SOCLE_ENERGIE", {d[0] for d in UM._definitions()["NRJ-INTENSITE"]})  # KPI du seul socle retiré
        fautive = Unite.objects.create(code="kWh.m2", symbole="kWh.m2", libelle="ancienne unité", ordre=99)
        KPI.objects.filter(pk="NRJ-INTENSITE").update(unite=fautive)  # ce que l'ancien rapprochement pouvait laisser
        self.assertEqual([c.kpi.code for c in UM.a_corriger()], ["NRJ-INTENSITE"])
        self.assertEqual(UM.corriger(), 1)
        self.assertEqual(KPI.objects.select_related("unite").get(pk="NRJ-INTENSITE").unite.symbole, "kWh/m²")
        self.assertEqual(UM.douteux(), [])
