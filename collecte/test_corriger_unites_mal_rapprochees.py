"""Réparation des KPI rangés dans une mauvaise unité par l'ancien rapprochement (``collecte.unites_mal_rapprochees``,
migration ``collecte/0044``) : seuls les cas prouvés sont corrigés (modèle de la bibliothèque installé dans la version
livrée, rejeu de l'ancienne règle), sans changer aucune valeur, avec une ligne d'historique ; les autres cas douteux sont
signalés (« À traiter », ``check_data``) ; un choix de l'administrateur n'est jamais touché. Données inventées."""
from decimal import Decimal

from django.urls import reverse

from parametres.models import Unite
from referentiel.models import KPI, ElementReferentiel, Referentiel, TravailApresMiseAJour

from . import controle_donnees as CD
from . import mise_a_jour as MAJ
from . import paquets as P
from . import unites_mal_rapprochees as UM
from .aides_tests.arbre_france import Arbre
from .models import Journal, Reponse

HORAIRES = ("SOC-REMU-H-HOMMES", "SOC-REMU-H-FEMMES")


class ReparationTests(Arbre):
    """Le modèle VS de base installé, puis remis dans l'état laissé par l'ancien rapprochement : rémunérations horaires
    rangées en « h », unité « €/h » absente, une valeur validée de 23,80 (euros par heure)."""

    def setUp(self):
        super().setUp()
        P.appliquer(None, P.analyser(P.fourni("vs_base.json").paquet, fourni=True))
        self.ref = Referentiel.objects.get(code="VS_BASE")
        heure = Unite.objects.get(code="h")
        KPI.objects.filter(code__in=HORAIRES).update(unite=heure)
        Unite.objects.filter(symbole="€/h").delete()
        self.saisir(HORAIRES[0], self.e1, "23.80", camp=self.c0)

    def unite(self, code):
        return KPI.objects.select_related("unite").get(pk=code).unite.symbole

    def test_correction_sans_toucher_aux_valeurs(self):
        valeurs = list(Reponse.objects.order_by("pk").values_list("pk", "valeur", "statut"))
        self.assertEqual([c.kpi.code for c in UM.a_corriger()], sorted(HORAIRES))
        self.assertEqual(UM.corriger(), 2)
        self.assertEqual({self.unite(c) for c in HORAIRES}, {"€/h"})
        u = Unite.objects.get(symbole="€/h")
        self.assertEqual((u.libelle, u.decimales, u.traductions.get("en", {}).get("libelle")), ("euro par heure", 2, "euro per hour"))
        self.assertEqual(list(Reponse.objects.order_by("pk").values_list("pk", "valeur", "statut")), valeurs)
        self.assertEqual(Reponse.objects.get(kpi_id=HORAIRES[0]).valeur, Decimal("23.80"))
        lignes = Journal.objects.filter(action="reglage_kpi", champ=UM.CHAMP_JOURNAL).order_by("objet_id")
        self.assertEqual([(j.objet_id, j.avant) for j in lignes], [(HORAIRES[1], "h"), (HORAIRES[0], "h")])
        self.assertIn("€/h", lignes[0].apres)
        self.assertEqual((UM.corriger(), UM.douteux()), (0, []))  # une seule fois ; plus rien à signaler

    def test_unite_juste_deja_creee_reprise(self):
        u = Unite.objects.create(code="eur-h", symbole="€/h", libelle="euros par heure", ordre=90)
        UM.corriger()
        self.assertEqual(KPI.objects.get(pk=HORAIRES[0]).unite_id, u.pk)

    def test_choix_de_l_administrateur_jamais_touche(self):
        KPI.objects.filter(pk=HORAIRES[1]).update(unite=Unite.objects.get(code="€"))  # « € » : pas une erreur de l'outil
        self.assertEqual([c.kpi.code for c in UM.a_corriger()], [HORAIRES[0]])
        self.assertEqual([c.kpi.code for c in UM.douteux()], [HORAIRES[0]])
        UM.corriger()
        self.assertEqual(self.unite(HORAIRES[1]), "€")

    def test_autre_version_ou_hors_du_referentiel_seulement_signale(self):
        Referentiel.objects.filter(pk=self.ref.pk).update(version="0.9")
        ElementReferentiel.objects.filter(referentiel=self.ref, kpi_id=HORAIRES[1]).delete()
        self.assertEqual(UM.a_corriger(), [])
        self.assertEqual([c.kpi.code for c in UM.douteux()], sorted(HORAIRES))
        self.assertEqual(UM.corriger(), 0)
        self.assertEqual({self.unite(c) for c in HORAIRES}, {"h"})
        r = CD.controler()
        constat = next(c for c in r["problems"] if c["check"] == "units_suspect")
        self.assertEqual((constat["severity"], constat["count"]), (CD.AVERTISSEMENT, 2))
        self.assertNotIn("units_suspect", [c["check"] for c in CD.a_signaler(r)])  # ligne à part dans « À traiter »
        self.client.force_login(self.admin)
        page = self.client.get(reverse("collecte:admin_accueil")).content.decode()
        self.assertIn("2 unités de KPI à vérifier", page)
        self.assertIn(HORAIRES[0], page)

    def test_travail_apres_mise_a_jour(self):
        TravailApresMiseAJour.objects.update_or_create(code="corriger_unites", defaults={"motif": "essai"})
        self.assertEqual(MAJ.faire_les_travaux(), ["corriger_unites"])
        self.assertEqual({self.unite(c) for c in HORAIRES}, {"€/h"})
        self.assertFalse(TravailApresMiseAJour.objects.filter(code="corriger_unites").exists())

    def test_ancienne_regle_rejouee(self):
        u = {"code": "€/h", "symbole": {"fr": "€/h", "en": "€/h"}}
        self.assertTrue(UM.ancienne_regle(u, Unite.objects.get(code="h"), "fr"))
        self.assertFalse(UM.ancienne_regle(u, Unite.objects.get(code="€"), "fr"))
        self.assertTrue(UM.ancienne_regle({"code": "m", "symbole": {"fr": "m"}}, Unite.objects.get(code="M€"), "fr"))
        self.assertFalse(UM.mal_rapprochee(u, Unite(code="x", symbole="€ / h"), "fr"))  # même symbole : rien à corriger


class SymboleRenommeTests(Arbre):
    """L'administrateur a renommé le symbole « h » en « heure » avant la mise à jour : le
    rejeu de l'ancienne règle sur le symbole ne voit plus rien. Les deux KPI sont signalés, par le code de l'unité que
    l'ancienne règle aurait choisie (« h ») ; rien n'est corrigé seul (le renommage est un geste de l'administrateur)."""

    def setUp(self):
        super().setUp()
        P.appliquer(None, P.analyser(P.fourni("vs_base.json").paquet, fourni=True))
        heure = Unite.objects.get(code="h")
        KPI.objects.filter(code__in=HORAIRES).update(unite=heure)
        Unite.objects.filter(symbole="€/h").delete()
        heure.symbole = "heure"
        heure.traductions = {lg: {**d, "symbole": "heure"} for lg, d in (heure.traductions or {}).items() if isinstance(d, dict)}
        heure.save()

    def test_signale_pas_corrige(self):
        self.assertEqual(UM.a_corriger(), [])
        self.assertEqual([c.kpi.code for c in UM.douteux()], sorted(HORAIRES))
        self.assertEqual(UM.corriger(), 0)
        self.assertEqual(set(KPI.objects.filter(code__in=HORAIRES).values_list("unite__symbole", flat=True)), {"heure"})
        constat = next(c for c in CD.controler()["problems"] if c["check"] == "units_suspect")
        self.assertEqual(constat["count"], 2)

    def test_autre_unite_choisie_pas_signalee(self):
        """Un KPI rangé par l'administrateur dans une unité d'un autre code (« € ») n'est pas signalé."""
        KPI.objects.filter(code__in=HORAIRES).update(unite=Unite.objects.get(code="€"))
        self.assertEqual(UM.douteux(), [])
