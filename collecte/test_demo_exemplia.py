"""Démo Exemplia, la seule démo : entreprise fictive, 4 niveaux, la norme
volontaire VS (et les onze modèles ESRS, installés sans valeur ni campagne), exercices 2024 et 2025 clôturés et complets (le classeur officiel de l'EFRAG s'exporte sans valeur
manquante), exercice 2026 ouvert et en partie saisi pour essayer la saisie, les validations et les relances."""
import datetime
from io import StringIO

from django.core.management import CommandError, call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from parametres.models import Instance, NiveauHierarchique
from parametres import niveaux as N
from referentiel.models import KPI, Attribution, Organisation, Referentiel, Utilisateur

from . import export_officiel as X
from . import paquets as PQ
from . import relances as R
from . import saisie as S
from .management.commands import _exemplia as EX
from .models import Alerte, Campagne, Journal, Preuve, Relance, Reponse


class DemoExempliaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("load_demo", "--language", "fr", stdout=StringIO())
        cls.admin = Utilisateur.objects.get(username="admin")
        cls.groupe = Organisation.objects.get(nom=EX.GROUPE)

    def test_installation_neutre(self):
        self.assertEqual(Instance.courante().nom, "Exemplia")
        self.assertEqual([n.nom for n in N.tous()], ["Groupe", "Pays", "Filiale", "Site"])
        self.assertEqual(Organisation.objects.filter(niveau_id="Site").count(), 11)
        self.assertFalse(Organisation.objects.get(nom="Lager Hannover").actif)
        self.assertEqual(set(Referentiel.objects.values_list("code", flat=True)),
                         {"VS_BASE", "VS_COMPLET", *(f[:-5].upper() for f in EX.ESRS)})  # la norme VS, plus les ESRS installées sans valeur
        self.assertFalse(KPI.objects.filter(elements__isnull=True).exists())

    def test_les_onze_modeles_esrs_sont_installes_sans_aucune_valeur_ni_campagne(self):
        self.client.force_login(self.admin)
        esrs = Referentiel.objects.filter(code__startswith="ESRS_")
        self.assertEqual(sorted(esrs.values_list("code", flat=True)), sorted(f[:-5].upper() for f in EX.ESRS))
        self.assertEqual(esrs.count(), 11)
        for ref in esrs:  # chaque modèle est entier : tous ses KPI sont installés
            paquet = next(f.paquet for f in PQ.bibliotheque() if f.paquet.code == ref.code)
            self.assertEqual(ref.elements.count(), len(paquet.kpis), ref.code)
            self.assertEqual(ref.version, paquet.version)
        self.assertFalse(Campagne.objects.filter(referentiel__in=esrs).exists(), "aucune campagne ne demande les ESRS")
        propres = KPI.objects.filter(elements__referentiel__in=esrs).exclude(elements__referentiel__code__in=["VS_BASE", "VS_COMPLET"])
        self.assertGreater(propres.count(), 400)
        self.assertFalse(Reponse.objects.filter(kpi__in=propres).exists(), "aucune valeur sur un KPI propre aux ESRS")
        self.assertFalse(Attribution.objects.filter(kpi__in=propres).exists(), "aucune attribution non plus")
        for ref in esrs:  # prêts à être mis dans une campagne : l'outil le propose
            self.assertEqual(self.client.get(reverse("parametres:referentiel_contenu", args=[ref.code])).status_code, 200)

    def test_niveaux_nommes_dans_les_sept_langues(self):
        """Pays et Filiale ont un nom dans chacune des sept langues (la démo ne laisse plus « Pays » en français partout)."""
        attendu = {"Country": {"en": "Country", "es": "País", "de": "Land", "it": "Paese", "nl": "Land", "pt": "País"},
                   "Entity": {"en": "Subsidiary", "es": "Filial", "de": "Tochtergesellschaft", "it": "Filiale",
                              "nl": "Dochteronderneming", "pt": "Filial"}}
        for code, noms in attendu.items():
            niveau = NiveauHierarchique.objects.get(code=code)
            self.assertEqual({lg: niveau.traductions[lg]["nom"] for lg in noms}, noms, code)
            self.assertTrue(all(niveau.traductions[lg]["nom_pluriel"] for lg in noms), code)

    def test_deux_exercices_clotures_et_complets(self):
        self.assertEqual(sorted(set(Campagne.objects.values_list("exercice", "statut"))),
                         [(2024, "cloturee"), (2025, "cloturee"), (2026, "ouverte")])
        self.assertEqual(Campagne.objects.count(), 6)  # deux référentiels × trois exercices
        clos = Reponse.objects.filter(periode__debut__year__in=[2024, 2025])
        self.assertFalse(clos.exclude(statut__in=[Reponse.Statut.VALIDE, Reponse.Statut.CALCULE]).exists())
        self.assertFalse(Alerte.objects.filter(campagne__exercice__in=[2024, 2025]).exclude(statut=Alerte.Statut.ACCEPTEE).exists())
        self.assertEqual(Preuve.objects.filter(reponse__periode__debut__year__in=[2024, 2025]).count(), len(EX.PREUVES))
        # Hannover, fermé le 30/06/2025, a encore ses valeurs de 2025 (ouvert pendant l'exercice)
        hannover = Organisation.objects.get(nom="Lager Hannover")
        self.assertTrue(Reponse.objects.filter(organisation=hannover, periode__debut__year=2025, kpi_id="NRJ-ELEC").exists())

    def test_exercice_2026_ouvert_et_en_cours(self):
        aujourd_hui = timezone.localdate()
        en_cours = Campagne.objects.filter(exercice=2026)
        self.assertEqual({c.statut for c in en_cours}, {Campagne.Statut.OUVERTE})
        for c in en_cours:  # date limite proche (31 jours après l'ouverture : vrai même si la suite passe minuit)
            self.assertEqual(c.date_fin_saisie - c.date_ouverture, datetime.timedelta(days=31))
            self.assertIn((c.date_fin_saisie - aujourd_hui).days, (9, 10))
            self.assertLess(c.date_ouverture, aujourd_hui)
        r2026 = Reponse.objects.filter(periode__debut__year=2026)
        saisies = r2026.exclude(statut__in=[Reponse.Statut.CALCULE, Reponse.Statut.INCOMPLET, Reponse.Statut.ERREUR])
        self.assertTrue(saisies.filter(statut=Reponse.Statut.VALIDE).exists())
        self.assertTrue(saisies.filter(statut=Reponse.Statut.BROUILLON).exists())
        # Hannover, fermé en 2025, n'a rien en 2026 ; Roanne, Valencia et Dortmund n'ont pas commencé
        hannover = Organisation.objects.get(nom="Lager Hannover")
        self.assertFalse(r2026.filter(organisation=hannover).exists())
        for nom in ("Usine de Roanne", "Almacén de Valencia", "Lager Dortmund"):
            self.assertFalse(saisies.filter(organisation__nom=nom).exists(), nom)
        for nom in ("Siège de Lyon", "Centre de tri de Vénissieux", "Werk Leipzig"):  # complets et validés
            self.assertTrue(saisies.filter(organisation__nom=nom).exists(), nom)
            self.assertFalse(saisies.filter(organisation__nom=nom, statut=Reponse.Statut.BROUILLON).exists(), nom)
        # brouillon sans valideur ni date de validation ; validé par son SPOC, avec sa ligne d'historique
        b = saisies.filter(statut=Reponse.Statut.BROUILLON).first()
        self.assertEqual((b.valide_par, b.date_validation), (None, None))
        v = saisies.filter(statut=Reponse.Statut.VALIDE).exclude(organisation__niveau_id="Group").first()
        self.assertTrue(Attribution.objects.filter(kpi=v.kpi, organisation=v.organisation, utilisateur=v.saisi_par).exists())
        self.assertTrue(Journal.objects.filter(objet="Reponse", objet_id=str(v.pk), champ="statut", apres="valide").exists())
        self.assertLessEqual(v.date_validation, timezone.now())
        # écart marqué sans commentaire : resté en brouillon, alerte à traiter
        eau = Reponse.objects.get(periode__debut__year=2026, kpi_id="EAU-PRELEVEMENT", organisation__nom="Usine de Villefranche")
        self.assertEqual((eau.statut, eau.commentaire), (Reponse.Statut.BROUILLON, ""))
        self.assertTrue(Alerte.objects.filter(campagne__exercice=2026, statut=Alerte.Statut.OUVERTE, kpi_id="EAU-PRELEVEMENT",
                                              organisation=eau.organisation).exists())
        # brouillon : « mis à jour le » = date de sa saisie dans le journal, pas l'heure du chargement
        j = Journal.objects.filter(objet="Reponse", objet_id=str(eau.pk), champ="statut", apres="brouillon").get()
        self.assertEqual(eau.date_maj, j.date)
        self.assertLess(eau.date_maj, timezone.now() - datetime.timedelta(hours=12))
        self.assertEqual(Preuve.objects.filter(reponse__periode__debut__year=2026).count(), len(EX.PREUVES_2026))

    def test_valeurs_validees_2026_acceptees_par_l_outil(self):
        """Aucune valeur validée de la démo que l'outil refuserait de valider (écart avec N-1 sans commentaire, règle
        bloquante…) ; les seuls écarts marqués sont ceux de ECARTS_2026 ; alertes à traiter : celles documentées."""
        en_cours = list(Campagne.objects.filter(exercice=2026))
        saisies = Reponse.objects.filter(periode__debut__year=2026, statut__in=[Reponse.Statut.VALIDE, Reponse.Statut.BROUILLON])
        refus, ecarts = [], set()
        for r in saisies.select_related("kpi", "organisation"):
            c = next(c for c in en_cours if S.dans_la_campagne(c, r.kpi))
            motifs = S.controles_validation(r, c)
            if motifs and r.statut == Reponse.Statut.VALIDE:
                refus.append((r.kpi_id, r.organisation.nom, motifs))
            r1 = S.reponse_n1(c, r.kpi, r.organisation)
            if r.kpi.est_numerique and r1 and not r1.non_applicable and S.depasse_seuil(S.ecart(r.valeur, r1.valeur), c.seuil_ecart):
                ecarts.add((r.organisation.nom, r.kpi_id))
        self.assertEqual(refus, [])
        self.assertEqual(ecarts, set(EX.ECARTS_2026))
        alertes = Alerte.objects.filter(campagne__exercice=2026)
        self.assertEqual(alertes.filter(statut__in=Alerte.A_TRAITER).count(), EX.ALERTES_A_TRAITER_2026)
        self.assertEqual(set(alertes.filter(statut=Alerte.Statut.JUSTIFIEE).values_list("kpi_id", "organisation__nom")),
                         set(EX.JUSTIFIEES_2026))
        valides = {(r.kpi_id, r.organisation_id) for r in saisies.filter(statut=Reponse.Statut.VALIDE)}
        self.assertFalse([a for a in alertes.filter(statut__in=Alerte.A_TRAITER) if (a.kpi_id, a.organisation_id) in valides])

    def test_contributrice_a_encore_a_saisir_et_relance(self):
        camille = Utilisateur.objects.get(username="contributeur")
        en_cours = list(Campagne.objects.filter(exercice=2026))
        af = {a.personne.username: a for a in R.a_faire(en_cours)}
        self.assertGreater(af["contributeur"].a_saisir, 0)
        self.assertGreater(af["contributeur"].brouillons, 0)
        self.assertIn("anna.schmidt", af)
        relance = Relance.objects.get(destinataire__username=EX.RELANCEE_2026)
        self.assertEqual((relance.statut, relance.envoyee_par), (Relance.Statut.MANUELLE, self.admin))
        self.assertGreater(relance.nb_a_saisir, 0)
        self.assertEqual(set(relance.campagnes.all()), set(en_cours))
        self.assertLess(relance.date, timezone.now() - datetime.timedelta(days=2))
        self.assertEqual(S.campagne_par_defaut(camille).exercice, 2026)  # la saisie s'ouvre sur l'exercice en cours

    def test_valeurs_2026_dans_le_prolongement(self):
        """Mêmes valeurs fictives prolongées d'un an : l'électricité d'un site varie de moins de 20 % ; effectif cohérent."""
        lyon = Organisation.objects.get(nom="Siège de Lyon")

        def valeur(code, an):
            return Reponse.objects.get(kpi_id=code, organisation=lyon, periode__debut__year=an).valeur
        self.assertLess(abs(valeur("NRJ-ELEC", 2026) / valeur("NRJ-ELEC", 2025) - 1), 0.2)
        self.assertLessEqual(valeur("SOC-EFF-FEMMES", 2026), valeur("SOC-EFFECTIF", 2026))

    def test_classeur_officiel_complet(self):
        for an in (2024, 2025):
            periode = Campagne.objects.filter(exercice=an).first().periode
            donnees, rapport = X.exporter("vs_efrag", self.groupe, periode, "fr", self.admin)
            self.assertEqual((rapport.manquantes, rapport.non_validees, rapport.messages), ([], [], []), an)
            self.assertTrue(rapport.option_b)

    def test_pages_principales(self):
        saisie = ("collecte:saisie", "collecte:tableau_de_bord", "collecte:pour_moi", "collecte:coherence")
        pages = {"admin": saisie, "contributeur": saisie, "validateur": saisie, "lecteur": ("collecte:tableau_de_bord",),
                 "auditeur": ("collecte:saisie", "collecte:tableau_de_bord", "collecte:coherence")}
        for ident, noms in pages.items():
            self.client.force_login(Utilisateur.objects.get(username=ident))
            for nom in noms:
                with self.subTest(compte=ident, page=nom):
                    self.assertLess(self.client.get(reverse(nom)).status_code, 400)
        self.client.force_login(self.admin)
        for nom in ("collecte:export_officiel", "collecte:relances"):
            self.assertEqual(self.client.get(reverse(nom)).status_code, 200, nom)

    def test_rechargement(self):
        sortie = StringIO()
        call_command("load_demo", "--language", "fr", stdout=sortie)
        self.assertIn("already present", sortie.getvalue())
        self.assertEqual(Organisation.objects.filter(nom=EX.GROUPE).count(), 1)
        self.assertEqual(Campagne.objects.count(), 6)

    def test_plus_d_autre_demo(self):
        with self.assertRaisesMessage(CommandError, "invalid choice"):
            call_command("load_demo", "--language", "fr", "--client", "acme", stdout=StringIO())
