"""« Je réponds à » : un seul choix de référentiel et de période, mémorisé pour toutes les pages (barre du haut,
sélecteurs Référentiel / Période des pages, pages d'administration), limité aux référentiels de la personne."""
import datetime
import io

from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from referentiel.composition import composer
from referentiel.models import KPI, Attribution, Niveau, Referentiel, Utilisateur

from . import imports as I
from . import saisie as S
from .models import Campagne, Relance
from .aides_tests.referentiels import Base


class ChoixReponseTests(Base):
    def test_panneau_et_choix_memorise_partout(self):
        rep = self.client.get(reverse("collecte:saisie"))
        self.assertContains(rep, 'data-ouvrir-choix')
        self.assertEqual(rep.context["campagne_choisie"], self.c)
        rep = self.client.get(reverse("collecte:choix_reponse") + "?suivant=/tableau-de-bord/%3Fcampagne%3D1")
        self.assertContains(rep, "Je réponds à…")
        self.assertEqual([b["ref"] for b in rep.context["blocs"]], [self.rse, self.nrg])
        self.assertEqual([c for c, _, _ in rep.context["blocs"][1]["en_cours"]], [self.c_nrg])
        # choix : mémorisé, référentiel compris, retour à la page sans l'ancien paramètre de campagne
        rep = self.client.get(reverse("collecte:choisir_campagne", args=[self.c_nrg.pk]) + "?suivant=/tableau-de-bord/%3Fcampagne%3D1%26x%3D2")
        self.assertRedirects(rep, "/tableau-de-bord/?x=2", fetch_redirect_response=False)
        self.assertEqual((self.client.session["campagne"], self.client.session["referentiel"]), (self.c_nrg.pk, "ENERGIE"))
        self.assertEqual(self.client.get(reverse("collecte:pour_moi")).context["campagne"], self.c_nrg)
        # adresse extérieure refusée
        rep = self.client.get(reverse("collecte:choisir_campagne", args=[self.c.pk]) + "?suivant=https://exemple.test/")
        self.assertRedirects(rep, reverse("collecte:accueil"), fetch_redirect_response=False)

    def test_selecteur_referentiel_puis_periode(self):
        c2025 = Campagne.objects.create(referentiel=self.nrg, exercice=2025, statut=Campagne.Statut.CLOTUREE)
        # changer de référentiel : la période suit (campagne en cours du référentiel choisi)
        rep = self.client.get(reverse("collecte:saisie") + f"?ref=ENERGIE&campagne={self.c.pk}")
        self.assertEqual(rep.context["campagne"], self.c_nrg)
        self.assertEqual(self.client.session["referentiel"], "ENERGIE")
        rep = self.client.get(reverse("collecte:saisie") + f"?ref=ENERGIE&campagne={c2025.pk}")
        self.assertEqual(rep.context["campagne"], c2025)
        self.assertContains(rep, "2025 (clôturée)")
        # même choix dans les pages d'administration : choisir un référentiel y change la campagne affichée partout
        self.client.get(reverse("collecte:referentiel") + "?ref=RSE")
        self.assertEqual(self.client.session["campagne"], self.c.pk)

    def test_contributeur_limite_a_ses_referentiels(self):
        autre = Referentiel.objects.create(code="AUTRE", nom="Autre", ordre=3)
        k = KPI.objects.create(code="X", libelle="X", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY, methode_agregation="Somme")
        composer({"X": ["Divers"]}, autre)
        fin = timezone.localdate() + datetime.timedelta(days=30)
        c_autre = Campagne.objects.create(referentiel=autre, exercice=2026, statut=Campagne.Statut.OUVERTE, date_fin_saisie=fin)
        Campagne.objects.create(referentiel=self.nrg, exercice=2027, statut=Campagne.Statut.PREPARATION)
        seul = Utilisateur.objects.create(username="seul", email="seul@exemple.test")
        Attribution.objects.create(kpi=k, organisation=self.e1, utilisateur=seul)
        self.assertEqual(S.referentiels_de(seul), [autre])
        self.assertEqual(S.campagne_par_defaut(seul), c_autre)  # arrive directement sur son référentiel
        self.assertEqual(S.referentiels_de(self.contrib), [self.rse, self.nrg])
        self.client.force_login(self.contrib)
        rep = self.client.get(reverse("collecte:choix_reponse"), HTTP_X_REQUESTED_WITH="fetch")  # panneau de la barre du haut
        self.assertNotContains(rep, "Autre")
        self.assertNotContains(rep, "en préparation")  # campagnes en préparation : admin seulement
        self.assertEqual(self.client.get(reverse("collecte:choisir_campagne", args=[c_autre.pk])).status_code, 403)


class PourMoiEtKpiCommunsTests(Base):
    def test_onglets_et_tous_mes_referentiels(self):
        self.client.force_login(self.contrib)
        rep = self.client.get(reverse("collecte:pour_moi"))
        self.assertEqual([o["campagne"] for o in rep.context["onglets"]], [self.c, self.c_nrg])
        self.assertEqual([o["etat"].valeurs for o in rep.context["onglets"]], [3, 2])
        self.assertContains(rep, "Tous mes référentiels")
        # vue d'ensemble : NRJ et ELEC, communs aux deux référentiels de la même année, ne sont comptés qu'une fois
        rep = self.client.get(reverse("collecte:pour_moi") + "?tous=1")
        self.assertTrue(rep.context["tous"])
        self.assertEqual(rep.context["compteur"].total, 3)
        self.assertEqual([b["campagne"] for b in rep.context["blocs"]], [self.c])
        self.assertTrue(self.client.get(reverse("collecte:pour_moi")).context["tous"])  # mémorisé
        rep = self.client.get(reverse("collecte:pour_moi") + f"?campagne={self.c_nrg.pk}")
        self.assertFalse(rep.context["tous"])  # choisir une campagne revient à son onglet
        self.assertEqual(rep.context["compteur"].total, 2)

    def test_alerte_sur_une_valeur_commune_comptee_une_fois(self):
        """chaque campagne a son alerte, mais la vue d'ensemble compte la case une seule fois."""
        from .models import Alerte

        for c in (self.c, self.c_nrg):
            Alerte.objects.create(campagne=c, kpi=self.nrj, organisation=self.e1, controle=Alerte.Controle.FORMAT, message="Valeur négative.")
        self.client.force_login(self.contrib)
        rep = self.client.get(reverse("collecte:pour_moi") + "?tous=1")
        self.assertEqual([o["etat"].alertes for o in rep.context["onglets"]], [1, 1])
        self.assertEqual(rep.context["reste_tous"].alertes, 1)
        self.assertEqual(rep.context["reste_tous"].valeurs, 3)
        self.assertContains(rep, "1 alerte à traiter", count=5)  # deux onglets, la vue d'ensemble, le titre du bloc et le sélecteur d'organisation
        rep = self.client.get(reverse("collecte:choix_reponse"))
        self.assertEqual([r.alertes for b in rep.context["blocs"] for _, r, _ in b["en_cours"]], [1, 1])

    def test_vue_d_ensemble_avec_une_campagne_dont_la_saisie_est_fermee(self):
        """La vue d'ensemble ne compte « à faire » que ce qui peut encore être saisi (une valeur commune revient à la
        campagne ouverte) ; les alertes d'une campagne fermée restent à justifier."""
        from .models import Alerte

        Campagne.objects.filter(pk=self.c.pk).update(statut=Campagne.Statut.REVUE)
        Alerte.objects.create(campagne=self.c, kpi=self.eff, organisation=self.e1, controle=Alerte.Controle.FORMAT, message="Valeur négative.")
        self.client.force_login(self.contrib)
        rep = self.client.get(reverse("collecte:pour_moi") + "?tous=1")
        onglets = rep.context["onglets"]
        self.assertEqual([o["campagne"] for o in onglets], [self.c, self.c_nrg])  # ordre d'affichage inchangé
        self.assertEqual([o["lecture_seule"] for o in onglets], [True, False])
        self.assertEqual([(o["reste"].valeurs, o["reste"].alertes) for o in onglets], [(1, 1), (2, 0)])
        tous = rep.context["reste_tous"]
        self.assertEqual((tous.valeurs, tous.alertes, rep.context["tous_fermes"]), (2, 1, False))
        self.assertContains(rep, '<span class="etat-a-faire">2 à faire</span>')
        self.assertContains(rep, "· 1 non validée · 1 alerte à traiter")  # titre du bloc de la campagne fermée

    def test_pastille_aussi_dans(self):
        rep = self.client.get(reverse("collecte:saisie") + f"?campagne={self.c.pk}&org={self.e1.pk}")
        self.assertContains(rep, "aussi dans Énergie", count=2)  # NRJ et ELEC
        self.assertContains(rep, "Valeur commune avec « Énergie » : saisie une seule fois")
        self.assertContains(rep, "data-option-autres-refs hidden")  # case pour masquer / afficher ces étiquettes

    def test_pas_de_pastille_si_l_autre_referentiel_ne_collecte_pas_cette_periode(self):
        """Référentiel historique (campagnes jusqu'à N-1) et nouvelle version (campagne N) : en N, le KPI commun n'est
        pas « aussi dans » l'historique, qui ne collecte pas N (constat d'essai)."""
        from .models import Periode

        autre = Periode.objects.create(type=self.c_nrg.periode.type, debut=self.c_nrg.periode.debut.replace(year=self.c_nrg.periode.debut.year - 1),
                                       fin=self.c_nrg.periode.fin.replace(year=self.c_nrg.periode.fin.year - 1), libelle="précédente")
        Campagne.objects.filter(pk=self.c_nrg.pk).update(periode=autre, exercice=self.c_nrg.exercice - 1)
        rep = self.client.get(reverse("collecte:saisie") + f"?campagne={self.c.pk}&org={self.e1.pk}")
        self.assertNotContains(rep, "aussi dans Énergie")


class RelancesEtTableauDeBordTests(Base):
    def test_relances_tous_les_referentiels_ouverts(self):
        rep = self.client.get(reverse("collecte:relances"))
        self.assertEqual(rep.context["portee"], "toutes")  # deux campagnes ouvertes : tout par défaut
        af = rep.context["liste"][0]
        self.assertEqual(af.personne, self.contrib)
        self.assertEqual(af.nombre, 3)  # NRJ et ELEC, communs aux deux référentiels de 2026, comptés une fois
        self.assertEqual(af.referentiels, [self.rse])
        rep = self.client.get(reverse("collecte:relances") + f"?portee=campagne&campagne={self.c_nrg.pk}")
        self.assertEqual(rep.context["cibles"], [self.c_nrg])
        self.assertEqual(rep.context["liste"][0].nombre, 2)
        with override_settings(EMAIL_HOST="smtp.exemple.test"):  # serveur d'envoi réglé (sans lui, rien ne part)
            rep = self.client.post(reverse("collecte:relances"), {"action": "envoyer", "portee": "toutes", "personnes": [self.contrib.pk]})
        self.assertRedirects(rep, reverse("collecte:relances") + "?portee=toutes", fetch_redirect_response=False)
        # un seul e-mail pour les deux référentiels ouverts, et la relance porte sur les deux campagnes
        self.assertEqual([m.to for m in mail.outbox], [[self.contrib.email]])
        r = Relance.objects.get()
        self.assertEqual(set(r.campagnes.all()), {self.c, self.c_nrg})

    def test_a_relancer_deux_campagnes_ouvertes(self):
        """la relance couvre tous les référentiels ouverts (portée proposée d'abord par la page Relances) ; le
        nombre affiché est celui de l'e-mail. Désormais, la liste est sur la page Relances seulement."""
        from . import relances as RL

        attendu = RL.a_faire([self.c, self.c_nrg], par=self.admin)
        page = self.client.get(reverse("collecte:relances"), {"campagne": self.c.pk})
        self.assertEqual(sorted((af.personne.pk, af.nombre) for af in page.context["liste"]),
                         sorted((af.personne.pk, af.nombre) for af in attendu))
        with override_settings(EMAIL_HOST="smtp.exemple.test"):
            self.client.post(reverse("collecte:relances"), {"action": "envoyer", "portee": "toutes", "personnes": [self.contrib.pk]})
        self.assertIn("3 KPI à compléter", mail.outbox[0].subject)
        self.assertNotIn("a_relancer", self.client.get(reverse("collecte:tableau_de_bord")).context)

    def test_deux_taux_nommes(self):
        """CALC-13 : le bilan (verdict, « N % validé ») et « Campagnes en cours » comptent
        les mêmes cases, sans les KPI facultatifs du référentiel."""
        rep = self.client.get(reverse("collecte:tableau_de_bord"))
        from .templatetags.collecte import pct  # « 0,0 % » : espace fine insécable avant « % » 

        self.assertContains(rep, f'{pct(rep.context["total"].taux)} validé')
        for nom in ("Validées", "À saisir", "Taux"):
            self.assertContains(rep, f'<th class="nombre{" mq-s" if nom == "À saisir" else ""}">{nom}</th>')
        self.assertNotContains(rep, "(obligatoires)")
        self.assertContains(rep, "Mêmes cases que le taux en tête de page : les KPI facultatifs ne comptent pas.")
        self.assertContains(rep, '<h3 class="titre-panneau-tdb">Campagnes en cours</h3>')  # le sous-titre est sorti du titre

    def test_tableau_de_bord_limite_aux_referentiels_de_la_personne(self):
        autre = Referentiel.objects.create(code="AUTRE", nom="Autre", ordre=3)
        Campagne.objects.create(referentiel=autre, exercice=2026, statut=Campagne.Statut.OUVERTE)
        self.client.force_login(self.contrib)
        rep = self.client.get(reverse("collecte:tableau_de_bord"))
        self.assertEqual([c.referentiel_id for c, _ in rep.context["avancement"]], ["RSE", "ENERGIE"])


class ImportExportParReferentielTests(Base):
    def test_fichier_a_remplir_tous_mes_referentiels(self):
        composer({"GAZ": ["Consommations"]}, self.nrg)  # propre au référentiel « Énergie »
        Attribution.objects.create(kpi=self.gaz, organisation=self.e1, utilisateur=self.contrib)
        self.client.force_login(self.contrib)
        rep = self.client.get(reverse("collecte:echanges_importer"))
        self.assertContains(rep, "Tous mes référentiels en cours (un onglet chacun)")
        rep = self.client.get(reverse("collecte:echanges_modele") + "?ref=tous&format=xlsx")
        wb = load_workbook(io.BytesIO(rep.content))
        self.assertEqual(wb.sheetnames[:3], ["À lire", "Reporting · 2026", "Énergie · 2026"])
        lus = {ws.title: [r for r in ws.iter_rows(values_only=True) if r[1] in ("EFF", "NRJ", "ELEC")] for ws in wb.worksheets[1:3]}
        self.assertEqual(sorted(r[1] for r in lus["Reporting · 2026"]), ["EFF", "ELEC", "NRJ"])
        self.assertEqual([r[1] for r in lus["Énergie · 2026"]], [])  # KPI communs à la même année : une seule fois, dans le premier
        self.assertIn("GAZ", [r[1] for r in wb["Énergie · 2026"].iter_rows(values_only=True)])
        # le fichier se réimporte tel quel (chaque ligne porte sa période)
        a = I.analyser(self.contrib, SimpleUploadedFile("tous.xlsx", rep.content))
        self.assertFalse(a.erreur)
        self.assertEqual({l.action for l in a.lignes}, {"ignore"})  # rien de rempli : valeurs vides
        # un référentiel et une période : la période suit le référentiel choisi
        rep = self.client.get(reverse("collecte:echanges_modele") + f"?ref=ENERGIE&campagne={self.c.pk}")
        self.assertIn("Energie", rep["Content-Disposition"])

    def test_nouvel_export_preregle_sur_le_referentiel_choisi(self):
        self.client.get(reverse("collecte:saisie") + f"?campagne={self.c_nrg.pk}")
        rep = self.client.get(reverse("collecte:echanges_exporter") + "?nouveau=1")
        self.assertEqual(rep.context["p"].referentiel, "ENERGIE")
