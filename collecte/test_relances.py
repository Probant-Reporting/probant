"""Relances par e-mail (cahier des charges, section 4.5) : un e-mail par personne avec tout ce qui lui reste, sans copie ;
périmètre du validateur ; modèle réglable ; relances automatiques aux jours d'échéance, une fois par jour ; journal."""
import datetime
import html
import io
import re

from django.core import mail
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from parametres.models import Instance
from parametres.referentiel import unite_depuis_symbole as U
from referentiel.models import KPI, Attribution, Niveau, Utilisateur

from . import dates_courtes as DC
from . import relances as R
from . import saisie as S
from . import vues_relances as VR
from .models import Campagne, Journal, Relance
from .aides_tests.saisie import Base
from .aides_tests.relances import AVEC_SMTP, JOUR, SANS_SMTP, figer_la_date
from django.test import TestCase
from decimal import Decimal
from pathlib import Path

from .models import Reponse
from referentiel.models import Organisation
from .aides_tests.aller_retour import Base as BaseEchanges


@AVEC_SMTP
class RelancesTests(Base):
    def setUp(self):
        super().setUp()
        # E2 a aussi un contributeur ; le validateur suit le pays (E1 et E2) pour l'effectif
        Attribution.objects.create(kpi=self.eff, organisation=self.e2, utilisateur=self.autre)
        self.enregistrer("12")  # brouillon EFF/E1 ; TX/E1 reste à saisir

    def test_ce_qui_reste_par_personne(self):
        liste = R.a_faire([self.c])
        self.assertEqual([(af.personne.email, af.a_saisir, af.brouillons) for af in liste],
                         [("autre@exemple.test", 1, 0), ("contrib@exemple.test", 1, 1)])
        S_valider = __import__("collecte.saisie", fromlist=["valider"]).valider
        self.enregistrer("0,5", kpi=self.taux)
        S_valider(self.contrib, self.c, self.eff, self.e1)
        S_valider(self.contrib, self.c, self.taux, self.e1)
        self.assertEqual([af.personne.email for af in R.a_faire([self.c])], ["autre@exemple.test"])  # tout validé : plus relancé

    def test_perimetre_du_validateur(self):
        Attribution.objects.create(kpi=self.taux, organisation=self.e2, utilisateur=self.autre)
        liste = R.a_faire([self.c], par=self.valid)  # le validateur ne suit que l'effectif
        self.assertEqual({(af.personne.email, af.nombre) for af in liste}, {("autre@exemple.test", 1), ("contrib@exemple.test", 1)})
        self.assertEqual(sum(af.nombre for af in R.a_faire([self.c], par=self.admin)), 4)

    def test_message_et_envoi_sans_copie(self):
        af = R.a_faire([self.c], destinataires=[self.contrib.pk])[0]
        sujet, texte = R.rediger(af)
        self.assertIn("2 KPI à compléter", sujet)
        self.assertIn("E1\n  - Effectif (EFF) : brouillon à valider", texte)
        self.assertIn("  - Taux (TX) : à saisir", texte)
        # date en toutes lettres dans la langue du destinataire (B6 : avant « jj/mm/aaaa » dans toutes les langues)
        self.assertIn(f"le {R.date_longue(self.c.date_fin_saisie)} (dans 30 jours)", texte)
        R.envoyer([af], par=self.admin)
        self.assertEqual(len(mail.outbox), 1)
        m = mail.outbox[0]
        self.assertEqual((m.to, m.cc, m.bcc), (["contrib@exemple.test"], [], []))
        r = Relance.objects.get()
        self.assertEqual((r.destinataire, r.envoyee_par, r.nb_a_saisir, r.nb_brouillons, r.statut), (self.contrib, self.admin, 1, 1, "envoyee"))
        self.assertEqual(list(r.campagnes.all()), [self.c])
        self.assertTrue(Journal.objects.filter(action="relance", objet="Utilisateur", objet_id=str(self.contrib.pk)).exists())

    def test_adresse_provisoire_jamais_relancee(self):
        """Une adresse provisoire « …@a-completer.invalid » (reprise de données) est traitée comme une adresse absente :
        aucun e-mail n'y part ni n'est noté « envoyé », et la page le dit au lieu d'annoncer une relance envoyée."""
        Utilisateur.objects.filter(pk=self.autre.pk).update(email="anne.martin@a-completer.invalid")
        liste = R.a_faire([self.c])
        self.assertEqual(R.envoyer(liste, par=self.admin), [r for r in Relance.objects.all()])
        self.assertEqual([m.to for m in mail.outbox], [["contrib@exemple.test"]])
        self.assertFalse(Relance.objects.filter(destinataire=self.autre).exists())
        self.client.force_login(self.admin)
        page = self.client.get(reverse("collecte:relances")).content.decode()
        self.assertIn("anne.martin@a-completer.invalid", page)  # visible (à corriger dans le compte), mais pas d'envoi
        mail.outbox.clear()
        r = self.client.post(reverse("collecte:relances"), {"action": "envoyer", "personnes": [self.autre.pk]}, follow=True)
        self.assertEqual(mail.outbox, [])
        self.assertIn("Pas d'adresse e-mail", html.unescape(r.content.decode()))

    def test_echec_smtp_note(self):
        af = R.a_faire([self.c], destinataires=[self.contrib.pk])[0]
        with override_settings(EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend", EMAIL_HOST="127.0.0.1", EMAIL_PORT=1,
                               EMAIL_TIMEOUT=2), self.assertLogs("reporting.relances", "WARNING"):
            sorties = R.envoyer([af], par=self.admin)
        self.assertEqual(sorties[0].statut, Relance.Statut.ECHEC)
        self.assertTrue(sorties[0].erreur)

    def test_modele_reglable_et_variables(self):
        with self.assertRaises(R.ModeleInvalide):
            R.verifier_modele("{outil}", "Bonjour {inconnue}")
        with self.assertRaises(R.ModeleInvalide):
            R.verifier_modele("{outil", "x")
        R.verifier_modele("{outil} – {nombre}", "{prenom} {liste} {lien} {{accolades}}")
        i = Instance.courante()
        i.relance_sujet, i.relance_message = "Rappel {campagne}", "Salut {prenom} : {nombre} ({a_saisir} + {brouillons}). {{ok}}"
        i.save()
        sujet, texte = R.rediger(R.a_faire([self.c], destinataires=[self.contrib.pk])[0])
        self.assertEqual((sujet, texte), (f"Rappel {self.c.titre}", "Salut contrib@exemple.test : 2 (1 + 1). {ok}"))

    def test_relances_automatiques(self):
        i = Instance.courante()
        aujourdhui = self.c.date_fin_saisie - datetime.timedelta(days=7)
        self.assertEqual(R.relancer_automatiquement(aujourdhui), [])  # désactivées par défaut
        i.relance_auto, i.relance_jours = True, "7,2"
        i.save()
        self.assertEqual(R.relancer_automatiquement(aujourdhui - datetime.timedelta(days=1)), [])  # pas un jour d'échéance
        with self.subTest("jour d'échéance"):
            liste = R.relancer_automatiquement(aujourdhui)
            self.assertEqual(len(liste), 2)
            self.assertEqual(len(mail.outbox), 2)
            self.assertTrue(all(r.automatique for r in Relance.objects.all()))
        # même jour : pas de second envoi (ici « aujourd'hui » réel, d'où le jour de la relance enregistrée)
        Relance.objects.update(date=timezone.make_aware(datetime.datetime.combine(aujourdhui, datetime.time(9))))
        self.assertEqual(R.relancer_automatiquement(aujourdhui), [])
        self.assertEqual(R.jours_echeance("7, 2;14"), [14, 7, 2])
        with self.assertRaises(R.ModeleInvalide):
            R.jours_echeance("sept")

    def test_commande(self):
        i = Instance.courante()
        i.relance_auto, i.relance_jours = True, "30"
        i.save()
        sortie = io.StringIO()
        call_command("relances", "--auto", "--simulation", stdout=sortie)
        self.assertIn("2 person(s) would be reminded", sortie.getvalue())
        self.assertEqual(len(mail.outbox), 0)
        call_command("relances", "--auto", stdout=io.StringIO())
        self.assertEqual(len(mail.outbox), 2)


    def test_derniere_relance_des_campagnes_affichees(self):
        """la dernière relance est celle qui portait sur la ou les campagnes affichées."""
        autre = Campagne.objects.create(exercice=2027, statut=Campagne.Statut.OUVERTE)
        r1 = Relance.objects.create(destinataire=self.contrib, envoyee_par=self.admin)
        r1.campagnes.set([self.c])
        r2 = Relance.objects.create(destinataire=self.contrib, envoyee_par=self.admin)  # plus récente, autre campagne
        r2.campagnes.set([autre])
        echec = Relance.objects.create(destinataire=self.contrib, statut=Relance.Statut.ECHEC)  # non partie : ignorée
        echec.campagnes.set([self.c])
        ids = [self.contrib.pk, self.autre.pk]
        self.assertEqual(R.dernieres_relances(ids, campagnes=[self.c]), {self.contrib.pk: r1})
        self.assertEqual(R.dernieres_relances(ids, campagnes=[self.c, autre]), {self.contrib.pk: r2})
        self.assertEqual(R.dernieres_relances(ids), {self.contrib.pk: r2})  # toutes campagnes confondues

    @SANS_SMTP
    def test_sans_smtp_rien_ne_part_ni_n_est_note(self):
        """sans serveur d'envoi, ni relance manuelle ni automatique ; aucune Relance ni ligne de journal."""
        af = R.a_faire([self.c], destinataires=[self.contrib.pk])[0]
        journal_avant = Journal.objects.count()
        with self.assertLogs("reporting.relances", "WARNING"):
            self.assertEqual(R.envoyer([af], par=self.admin), [])
        i = Instance.courante()
        i.relance_auto, i.relance_jours = True, "30"
        i.save()
        with self.assertLogs("reporting.relances", "WARNING"):
            self.assertEqual(R.relancer_automatiquement(self.c.date_fin_saisie - datetime.timedelta(days=30)), [])
        self.assertEqual(len(R.relancer_automatiquement(self.c.date_fin_saisie - datetime.timedelta(days=30), simulation=True)), 2)
        self.assertEqual((len(mail.outbox), Relance.objects.count(), Journal.objects.count()), (0, 0, journal_avant))
        sortie = io.StringIO()
        with self.assertLogs("reporting.relances", "WARNING"):
            call_command("relances", "--auto", stdout=sortie)
        self.assertIn("E-mails not enabled", sortie.getvalue())
        self.assertEqual((len(mail.outbox), Relance.objects.count()), (0, 0))
        sortie = io.StringIO()
        call_command("relances", "--auto", "--simulation", stdout=sortie)
        self.assertIn("2 person(s) would be reminded today. (E-mails not enabled", sortie.getvalue())


@AVEC_SMTP
class PageRelancesTests(Base):
    def setUp(self):
        super().setUp()
        self.enregistrer("12")

    def test_droits(self):
        self.client.force_login(self.contrib)
        self.assertEqual(self.client.get(reverse("collecte:relances")).status_code, 403)
        self.client.force_login(self.valid)
        rep = self.client.get(reverse("collecte:relances"))
        self.assertContains(rep, "contrib@exemple.test")
        self.assertNotContains(rep, "Modèle du message")  # réglé par l'admin seulement
        rep = self.client.post(reverse("collecte:relances"), {"action": "modele", "sujet": "x", "message": "y"})
        self.assertEqual(rep.status_code, 403)

    def test_envoyer_depuis_la_page(self):
        self.client.force_login(self.admin)
        rep = self.client.get(reverse("collecte:tableau_de_bord"))
        self.assertContains(rep, "Relancer…")
        rep = self.client.get(reverse("collecte:relances"))
        self.assertContains(rep, "Aperçu – ")
        self.assertContains(rep, "brouillon à valider")
        rep = self.client.post(reverse("collecte:relances"), {"action": "envoyer", "personnes": [self.contrib.pk]}, follow=True)
        self.assertContains(rep, "1 relance envoyée à contrib@exemple.test.")  # la confirmation nomme les personnes
        self.assertContains(rep, "à l'instant")  # la nouvelle ligne de l'historique est repérée
        self.assertEqual([m.to for m in mail.outbox], [["contrib@exemple.test"]])
        self.assertContains(rep, "Historique")
        rep = self.client.post(reverse("collecte:relances"), {"action": "essai", "personnes": [self.contrib.pk]}, follow=True)
        self.assertEqual(mail.outbox[-1].to, ["admin@exemple.test"])
        self.assertTrue(mail.outbox[-1].subject.startswith("[Essai]"))
        self.assertEqual(Relance.objects.count(), 1)  # l'essai n'est pas une relance

    def test_tableau_de_bord_qui_relancer(self):
        """Jours restants, retards par rapport au rythme attendu (sur les propres cases de chaque organisation),
        « Sans SPOC » en tête, tri par taux, un lien « Relancer » par personne qui coche d'avance la bonne personne
        sur la page Relances."""
        Attribution.objects.create(kpi=self.eff, organisation=self.e2, utilisateur=self.autre)  # TX/E2 reste sans SPOC
        self.c.date_ouverture = timezone.localdate() - datetime.timedelta(days=30)  # moitié du temps de saisie écoulée
        self.c.save()
        self.client.force_login(self.admin)
        url = reverse("collecte:tableau_de_bord")
        rep = self.client.get(url)
        self.assertEqual((rep.context["jours"], rep.context["attendu"]), (30, 50))
        self.assertContains(rep, "Jours restants")
        # 0 % < 50 % − 10 points sur les sites ; Groupe et Pays n'ont pas de case propre : pas de retard à eux
        self.assertEqual(rep.context["retards"], {self.e1.pk, self.e2.pk})
        self.assertContains(rep, "en retard")
        # la tolérance se règle dans Paramètres › Seuils de suivi : à 50 points, plus personne n'est en retard
        from parametres.models import Instance

        Instance.objects.filter(pk=Instance.courante().pk).update(tolerance_retard=50)
        self.assertEqual(self.client.get(url).context["retards"], set())
        Instance.objects.filter(pk=1).update(tolerance_retard=10)
        self.assertIsNone(rep.context["par_spoc"][0][0])  # « Sans SPOC » en tête
        self.assertContains(rep, "1 case sans SPOC")
        relancer = f'{reverse("collecte:relances")}?campagne={self.c.pk}&amp;portee=campagne'
        self.assertNotContains(rep, f"{relancer}&amp;org=")  # plus de lien « Relancer » sur une organisation
        self.assertNotContains(rep, f"{relancer}&amp;personne=")  # plus de liste « À relancer » 
        S.valider(self.contrib, self.c, self.eff, self.e1)  # E1 : 1 sur 2
        orgs = [o for o, _ in self.client.get(url, {"tri": "taux"}).context["par_org"]]
        self.assertEqual(orgs[0], self.e2)
        # page Relances : présélection d'une organisation (lien encore accepté), puis d'une personne
        rep = self.client.get(reverse("collecte:relances"), {"campagne": self.c.pk, "portee": "campagne", "org": self.e2.pk})
        self.assertEqual({af.personne.email: af.coche for af in rep.context["liste"]},
                         {"autre@exemple.test": True, "contrib@exemple.test": False})
        self.assertContains(rep, "Cochées d'avance : les personnes de E2")
        rep = self.client.get(reverse("collecte:relances"), {"campagne": self.c.pk, "personne": self.contrib.pk})
        self.assertEqual((rep.context["nb_coches"], rep.context["apercu"][0].personne), (1, self.contrib))
        self.assertEqual(self.client.get(reverse("collecte:relances")).context["nb_coches"], 2)  # sans présélection : tout le monde

    def test_regler_le_modele(self):
        self.client.force_login(self.admin)
        rep = self.client.post(reverse("collecte:relances"), {"action": "modele", "sujet": "{outil}", "message": "{x}"})
        self.assertContains(rep, "Variable inconnue")
        rep = self.client.post(reverse("collecte:relances"), {"action": "modele", "sujet": "Rappel {campagne}", "message": "{liste}",
                                                              "relance_auto": "on", "relance_jours": "10, 3"}, follow=True)
        self.assertContains(rep, "Relances automatiques : 10 et 3 jours")
        i = Instance.courante()
        self.assertEqual((i.relance_sujet, i.relance_auto, i.relance_jours), ("Rappel {campagne}", True, "10,3"))
        self.client.post(reverse("collecte:relances"), {"action": "modele_defaut"})
        self.assertEqual(Instance.courante().relance_sujet, "")
        self.assertTrue(Journal.objects.filter(action="reglage_relances").exists())

    def test_campagne_fermee(self):
        self.c.statut = "cloturee"
        self.c.save()
        self.client.force_login(self.admin)
        rep = self.client.get(reverse("collecte:relances") + f"?campagne={self.c.pk}")
        self.assertContains(rep, "L'outil n'envoie de relances que pendant la saisie")
        Utilisateur.objects.filter(pk=self.contrib.pk).update(is_active=False)
        self.assertEqual(R.a_faire([]), [])

    def test_confirmation_nominative_et_sans_adresse(self):
        Attribution.objects.create(kpi=self.eff, organisation=self.e2, utilisateur=self.autre)
        sans = Utilisateur.objects.create(username="sans", email="", first_name="Sans", last_name="Adresse")
        Attribution.objects.create(kpi=self.taux, organisation=self.e2, utilisateur=sans)
        self.client.force_login(self.admin)
        rep = self.client.get(reverse("collecte:relances"))
        self.assertContains(rep, 'data-confirmer="Envoyer la relance à 3 personnes ?"')
        self.assertContains(rep, "pas d'adresse e-mail")
        rep = self.client.post(reverse("collecte:relances"), {"action": "envoyer", "personnes": [self.contrib.pk, self.autre.pk, sans.pk]},
                               follow=True)
        self.assertContains(rep, "2 relances envoyées à autre@exemple.test et contrib@exemple.test.")
        self.assertContains(rep, "Pas d&#x27;adresse e-mail, donc pas de relance : Sans Adresse.")
        self.assertEqual(len(mail.outbox), Relance.objects.count())  # autant d'e-mails que de relances notées
        self.assertEqual(VR.noms([f"P{n}" for n in range(7)]), "P0, P1, P2, P3, P4 et 2 autres")
        self.assertEqual(VR.noms(["A", "B", "C"]), "A, B et C")
        # la dernière relance s'affiche sur la ligne (colonne et, sur téléphone, sous le nom)
        rep = self.client.get(reverse("collecte:relances"))
        self.assertIsNotNone(next(af for af in rep.context["liste"] if af.personne == self.contrib).derniere)
        self.assertContains(rep, "Dernière relance : aucune")  # personne sans adresse : jamais relancée

    def test_modele_replie_depuis_une_personne(self):
        """E16 : arrivé depuis une personne (lien du tableau de bord), l'éditeur du modèle est replié."""
        self.client.force_login(self.admin)
        rep = self.client.get(reverse("collecte:relances"))
        self.assertContains(rep, '<details class="aide-repliable modele-relance" open>')
        rep = self.client.get(reverse("collecte:relances"), {"personne": self.contrib.pk})
        self.assertContains(rep, '<details class="aide-repliable modele-relance">')
        self.assertContains(rep, 'aria-label="Aperçu du message pour contrib@exemple.test">Aperçu</a>')

    def test_a_traiter_relances_auto_sans_smtp(self):
        """Relances automatiques réglées mais sautées faute de SMTP : remonté au rang d'un retard dans « À traiter »."""
        self.client.force_login(self.admin)
        url = reverse("collecte:admin_accueil")
        titres = [t["titre"] for t in self.client.get(url).context["a_traiter"]]
        self.assertNotIn("E-mails pas encore configurés", titres)  # SMTP réglé
        with SANS_SMTP:
            titres = [t["titre"] for t in self.client.get(url).context["a_traiter"]]
            self.assertEqual(titres[-1], "E-mails pas encore configurés")
            i = Instance.courante()
            i.relance_auto = True
            i.save()
            a_traiter = self.client.get(url).context["a_traiter"]
        titres = [t["titre"] for t in a_traiter]
        self.assertLess(titres.index("E-mails pas encore configurés"), titres.index("2 cases sans SPOC"))
        self.assertIn("relances automatiques sont activées, mais l'outil les saute", a_traiter[titres.index("E-mails pas encore configurés")]["detail"])


@SANS_SMTP
class RelancesSansSmtpTests(Base):
    """E8 : sans serveur d'envoi, la page Relances ne propose pas d'envoyer ; un encart orange le dit et l'on
    écrit à chaque personne à la main ; un envoi forgé est refusé sans rien noter."""

    def setUp(self):
        super().setUp()
        self.enregistrer("12")
        Attribution.objects.create(kpi=self.eff, organisation=self.e2, utilisateur=self.autre)

    def test_page_sans_envoi(self):
        self.client.force_login(self.admin)
        rep = self.client.get(reverse("collecte:relances"), {"personne": self.contrib.pk})
        self.assertContains(rep, '<div class="encart encart-avertissement" role="status">')
        self.assertContains(rep, "Les e-mails ne sont pas encore configurés : rien ne part de cette page.")
        self.assertContains(rep, reverse("parametres:hebergement"))  # l'admin sait où le régler
        for absent in ('value="envoyer"', 'value="essai"', 'name="personnes"', "Cochées d'avance"):
            self.assertNotContains(rep, absent)
        # « Écrire à … » : adresse, objet et texte du modèle réglable, à copier, et lien vers la messagerie
        sujet, texte = R.rediger(rep.context["apercu"][0], rep.wsgi_request)
        self.assertContains(rep, "<h2 id=\"titre-apercu\">Écrire à contrib@exemple.test</h2>", html=False)
        self.assertContains(rep, 'data-copier="#ecrire-adresse"')
        self.assertContains(rep, 'data-copier="#ecrire-message" data-copier-annonce="Message copié')
        self.assertContains(rep, 'aria-label="Écrire à autre@exemple.test">Écrire</a>')
        self.assertTrue(rep.context["messagerie"].startswith("mailto:contrib@exemple.test?subject="))
        self.assertIn("Effectif", rep.context["apercu"][2])
        self.assertEqual(rep.context["apercu"][1], sujet)
        self.assertEqual(rep.context["apercu"][2], texte)

    def test_marquer_relance_faite_a_la_main(self):
        """Relance faite hors de l'outil : « Marquer relancé » la note (historique, « Dernière relance », journal) ;
        seule une relance notée à la main s'annule, par son auteur ou l'admin."""
        url = reverse("collecte:relances")
        self.client.force_login(self.valid)
        rep = self.client.post(url, {"action": "marquer", "personne": self.contrib.pk}, follow=True)
        self.assertContains(rep, "Relance de contrib@exemple.test notée dans l&#x27;historique.")
        r = Relance.objects.get()
        self.assertEqual((r.statut, r.envoyee_par, r.destinataire, r.nombre), (Relance.Statut.MANUELLE, self.valid, self.contrib, 1))  # périmètre du validateur
        self.assertEqual(list(r.campagnes.all()), [self.c])
        self.assertEqual(R.dernieres_relances([self.contrib.pk], [self.c])[self.contrib.pk], r)
        self.assertEqual(len(mail.outbox), 0)  # rien n'est envoyé
        self.assertTrue(Journal.objects.filter(action="relance_manuelle", utilisateur=self.valid).exists())
        self.assertContains(rep, "notée à la main")
        self.assertContains(rep, 'value="annuler_marque"')
        # personne sans rien à relancer : refusé, rien de noté
        self.client.post(url, {"action": "marquer", "personne": self.admin.pk})
        self.assertEqual(Relance.objects.count(), 1)
        # une relance envoyée par e-mail ne s'annule pas ; celle d'un autre non plus (sauf admin)
        envoyee = Relance.objects.create(destinataire=self.autre, envoyee_par=self.valid)
        self.assertEqual(self.client.post(url, {"action": "annuler_marque", "relance": envoyee.pk}).status_code, 403)
        self.client.force_login(self.contrib)
        self.assertEqual(self.client.post(url, {"action": "annuler_marque", "relance": r.pk}).status_code, 403)
        self.client.force_login(self.admin)
        self.client.post(url, {"action": "annuler_marque", "relance": r.pk})
        self.assertFalse(Relance.objects.filter(pk=r.pk).exists())

    def test_periode_fermee_choisie_avec_plusieurs_ouvertes(self):
        """Plusieurs campagnes ouvertes (portée « toutes » par défaut) : choisir 2025, clôturée, montre 2025 et non les
        campagnes ouvertes ; pas de choix « Relancer pour » ; un lien vers chaque campagne ouverte."""
        from referentiel.models import Referentiel
        autre = Referentiel.objects.create(code="AUT", nom="Autre")
        c2 = Campagne.objects.create(referentiel=autre, periode=self.c.periode, statut=Campagne.Statut.OUVERTE)
        self.client.force_login(self.admin)
        url = reverse("collecte:relances")
        rep = self.client.get(url, {"campagne": self.c.pk})
        self.assertEqual((rep.context["portee"], len(rep.context["cibles"])), ("toutes", 2))
        rep = self.client.get(url, {"campagne": self.c0.pk})
        self.assertEqual((rep.context["portee"], rep.context["cibles"], rep.context["liste"]), ("campagne", [], []))
        self.assertNotContains(rep, "Relancer pour")
        self.assertContains(rep, f'href="?campagne={c2.pk}"')
        rep = self.client.get(url, {"portee": "toutes"})  # la période mémorisée (2025) reste celle affichée
        self.assertEqual(rep.context["cibles"], [])

    def test_historique_de_la_periode_affichee(self):
        """Changer d'année change aussi l'historique : 2025 (clôturée) ne montre pas les relances de 2026."""
        self.client.force_login(self.admin)
        url = reverse("collecte:relances")
        self.client.post(url, {"action": "marquer", "personne": self.contrib.pk})
        self.assertEqual(len(self.client.get(url, {"campagne": self.c.pk}).context["historique"]), 1)
        rep = self.client.get(url, {"campagne": self.c0.pk})
        self.assertEqual(len(rep.context["historique"]), 0)
        self.assertContains(rep, "Aucune relance envoyée ni notée pour cette période.")

    def test_lien_messagerie_trop_long(self):
        self.assertIsNone(VR.lien_messagerie("a@exemple.test", "Objet", "x" * 2000))
        self.assertIsNone(VR.lien_messagerie("", "Objet", "court"))
        self.assertEqual(VR.lien_messagerie("a@exemple.test", "Un objet", "L1\nL2"), "mailto:a@exemple.test?subject=Un%20objet&body=L1%0AL2")

    def test_validateur_sans_lien_hebergement(self):
        self.client.force_login(self.valid)
        rep = self.client.get(reverse("collecte:relances"))
        self.assertContains(rep, "encart-avertissement")
        self.assertNotContains(rep, reverse("parametres:hebergement"))

    def test_envoi_force_refuse(self):
        """Un POST forgé (envoyer ou essai) est refusé avant tout calcul : 0 Relance, 0 ligne de journal, 0 e-mail."""
        for qui in (self.admin, self.valid):
            self.client.force_login(qui)
            journal_avant = Journal.objects.count()
            for action in ("envoyer", "essai"):
                rep = self.client.post(reverse("collecte:relances"), {"action": action, "portee": "campagne",
                                                                      "personnes": [self.contrib.pk, self.autre.pk]})
                self.assertRedirects(rep, reverse("collecte:relances") + "?portee=campagne", fetch_redirect_response=False)
            rep = self.client.get(rep.url)
            self.assertContains(rep, "Les e-mails ne sont pas configurés, donc rien n&#x27;est parti.")
            self.assertEqual((Relance.objects.count(), Journal.objects.count() - journal_avant, len(mail.outbox)), (0, 0, 0))
        self.assertContains(rep, "Aucune relance envoyée ni notée pour cette période.")

    def test_relances_auto_sautees_annoncees(self):
        i = Instance.courante()
        i.relance_auto, i.relance_jours = True, "7"
        i.save()
        self.client.force_login(self.admin)
        rep = self.client.get(reverse("collecte:relances"))
        self.assertContains(rep, "Les relances automatiques sont sautées.")
        self.assertContains(rep, "Sautées tant que les e-mails ne sont pas configurés")

    def test_tableau_de_bord_bouton_honnete(self):
        """E8 : sans SMTP, le bouton d'en-tête devient secondaire, « Préparer la relance… », avec la mention orange."""
        self.client.force_login(self.admin)
        rep = self.client.get(reverse("collecte:tableau_de_bord"))
        self.assertContains(rep, "Préparer la relance…")
        self.assertContains(rep, "E-mails pas encore configurés")
        self.assertNotContains(rep, ">Relancer…</a>")
        with AVEC_SMTP:
            rep = self.client.get(reverse("collecte:tableau_de_bord"))
        self.assertContains(rep, ">Relancer…</a>")
        self.assertNotContains(rep, "Préparer la relance…")

    def test_ligne_choisie_et_textes_sans_envoi(self):
        """La ligne de la personne choisie le dit (aria-current), pas seulement par la couleur ; sans SMTP, aucune
        phrase ne promet un e-mail envoyé par l'outil."""
        self.client.force_login(self.admin)
        rep = self.client.get(reverse("collecte:relances"), {"personne": self.contrib.pk, "apercu": self.contrib.pk})
        self.assertContains(rep, 'aria-current="true"', count=1)
        self.assertContains(rep, "Un seul message par personne")
        self.assertNotContains(rep, "Un seul e-mail par personne")
        self.assertContains(rep, "Elles partent quand les e-mails sont configurés.")
        rep = self.client.post(reverse("collecte:relances"), {"action": "envoyer", "portee": "campagne"}, follow=True)
        self.assertContains(rep, "Écrivez à chaque personne avec votre messagerie (lien « Écrire » dans la liste).")

    def test_page_sans_campagne(self):
        """Base sans aucune campagne : la page Relances s'affiche (plus d'erreur 500 sur le titre)."""
        Campagne.objects.all().delete()
        self.client.force_login(self.admin)
        rep = self.client.get(reverse("collecte:relances"))
        self.assertEqual(rep.status_code, 200)


class TableauDeBordRetardsTests(Base):
    """chaque organisation est jugée sur ses propres cases ; la ligne d'un parent nomme ses deux chiffres et compte
    les organisations rattachées en retard ; même nombre dans « À traiter » ; le contributeur ne voit aucun retard."""

    def setUp(self):
        super().setUp()
        figer_la_date(self)
        # moitié du temps de saisie écoulée : rythme attendu 50 %, retard sous 40 %
        Campagne.objects.filter(pk=self.c.pk).update(date_ouverture=JOUR - datetime.timedelta(days=30),
                                                     date_fin_saisie=JOUR + datetime.timedelta(days=30))
        self.c.refresh_from_db()
        # organisation intermédiaire avec une case propre (KPI saisi au niveau pays)
        self.kpi_pays = KPI.objects.create(code="PAYS", libelle="Politique pays", type_saisie_id="Saisi",
                                           granularite_id=Niveau.COUNTRY, methode_agregation="Somme", unite=U("ETP"))

    def tdb(self, user, **params):
        self.client.force_login(user)
        return self.client.get(reverse("collecte:tableau_de_bord"), params)

    def test_parent_juge_sur_ses_propres_kpi(self):
        rep = self.tdb(self.admin)
        self.assertEqual(rep.context["attendu"], 50)
        self.assertEqual(rep.context["retards"], {self.p.pk, self.e1.pk, self.e2.pk})  # pas le Groupe : aucune case propre
        lignes = {o: x for o, _, x in rep.context["arbre"]}
        self.assertEqual((lignes[self.g]["parent"], lignes[self.g]["propre"], lignes[self.g]["dessous"]), (True, None, 3))
        self.assertEqual((lignes[self.p]["parent"], lignes[self.p]["propre"].total, lignes[self.p]["retard"], lignes[self.p]["dessous"]),
                         (True, 1, True, 2))
        self.assertEqual((lignes[self.e1]["parent"], lignes[self.e1]["dessous"]), (False, 0))
        self.assertContains(rep, "en retard sur ses propres KPI", count=1)  # le Pays seulement
        self.assertContains(rep, "ses propres KPI : 0 sur 1 validé")
        self.assertContains(rep, "Taux de l'ensemble : 0,0 %", count=2)  # Groupe et Pays
        self.assertContains(rep, "dont 3 en retard")
        self.assertContains(rep, "dont 2 en retard")
        self.client.force_login(self.admin)
        titres = [t["titre"] for t in self.client.get(reverse("collecte:admin_accueil")).context["a_traiter"]]
        self.assertIn("3 organisations en retard", titres)  # même nombre que le tableau de bord
        # le Pays saisit et valide sa propre case : il n'est plus en retard, ses sites le restent
        S.enregistrer(self.admin, self.c, self.kpi_pays, self.p, "3", False, "")
        S.valider(self.admin, self.c, self.kpi_pays, self.p)
        rep = self.tdb(self.admin)
        self.assertEqual(rep.context["retards"], {self.e1.pk, self.e2.pk})
        self.assertNotContains(rep, "sur ses propres KPI")
        self.assertContains(rep, "ses propres KPI : 1 sur 1 validé")
        self.assertContains(rep, "dont 2 en retard", count=2)  # Groupe et Pays
        self.assertContains(rep, '<li class="tuile-tdb a-surveiller"><a href="#detail-tdb" data-voir-retards>', count=1)  # chiffre cliquable
        self.assertEqual(re.findall(r'Organisations en retard</span><span class="grand">(\d+)', rep.content.decode()), ["2"])
        titres = [t["titre"] for t in self.client.get(reverse("collecte:admin_accueil")).context["a_traiter"]]
        self.assertIn("2 organisations en retard", titres)

    def test_aucune_ligne_calculee_ni_saisie_au_dessus_comptee(self):
        lignes = list(S.lignes(self.admin, self.c))
        lignes.append(S.Ligne(self.calc, self.p, None, None, "a_saisir", calculee=True))  # total calculé au pays
        lignes.append(S.Ligne(self.eff, self.p, None, None, "a_saisir", au_dessus=True))  # saisie possible au-dessus
        tdb = S.tableau_de_bord(lignes)
        self.assertEqual(tdb["par_org_propre"][self.p].total, 1)  # la seule case PAYS
        self.assertNotIn(self.g, tdb["par_org_propre"])
        from .views import suivi

        _, retards, _ = suivi(self.c, tdb)
        self.assertEqual(retards, {self.p.pk, self.e1.pk, self.e2.pk})
        S.enregistrer(self.admin, self.c, self.kpi_pays, self.p, "3", False, "")
        S.valider(self.admin, self.c, self.kpi_pays, self.p)
        lignes = list(S.lignes(self.admin, self.c)) + [S.Ligne(self.calc, self.p, None, None, "a_saisir", calculee=True)]
        self.assertEqual(suivi(self.c, S.tableau_de_bord(lignes))[1], {self.e1.pk, self.e2.pk})

    def test_contributeur_ne_voit_pas_les_retards(self):
        rep = self.tdb(self.contrib)
        self.assertEqual((rep.context["retards"], rep.context["voit_retards"]), (set(), False))
        html = rep.content.decode()
        self.assertNotIn("Organisations en retard", html)  # compteur
        self.assertNotIn('class="en-retard"', html)  # ligne
        self.assertNotIn('class="badge-alerte"', html)  # badge
        self.assertNotIn("retard-dessous", html)  # « dont N en retard »
        self.assertNotIn("Une organisation est en retard", html)  # phrase de la note
        self.assertNotIn('id="titre-a-relancer"', html)  # pas de liste « À relancer »
        # le validateur, lui, voit les retards de son périmètre
        rep = self.tdb(self.valid)
        self.assertEqual(rep.context["retards"], {self.e1.pk, self.e2.pk})
        self.assertContains(rep, "Organisations en retard")
        self.assertContains(rep, "Une organisation est en retard quand le taux de ses propres KPI")


class ListeARelancerTests(Base):
    """la liste « À relancer » en tête du tableau de bord montre ce que l'e-mail contiendra, un seul lien
    « Relancer » par personne ; l'arbre et « Par SPOC » n'en ont plus ; mots courants (E18) ; « Sans SPOC » en orange."""

    def setUp(self):
        super().setUp()
        figer_la_date(self)
        Campagne.objects.filter(pk=self.c.pk).update(date_ouverture=JOUR - datetime.timedelta(days=30),
                                                     date_fin_saisie=JOUR + datetime.timedelta(days=30))
        self.c.refresh_from_db()
        Attribution.objects.create(kpi=self.eff, organisation=self.e2, utilisateur=self.autre)  # TX/E2 reste sans SPOC
        self.enregistrer("12")

    def tdb(self, user, **params):
        self.client.force_login(user)
        return self.client.get(reverse("collecte:tableau_de_bord"), params)

    def test_plus_de_liste_a_relancer(self):
        """Plus de colonne « À relancer » ; « Préparer la relance… » est dans « À faire maintenant »,
        et la tête de page n'a plus que la bascule Avancement / Consolidation (elle ne bouge plus d'une page à l'autre)."""
        rep = self.tdb(self.admin)
        html = rep.content.decode()
        self.assertNotIn('id="titre-a-relancer"', html)
        self.assertNotIn(">Relancer</a>", html)
        self.assertNotIn("a_relancer", rep.context)
        a_faire = html[html.index('id="titre-a-faire"'):html.index("</section>", html.index('id="titre-a-faire"'))]
        self.assertIn(reverse("collecte:relances"), a_faire)
        tete = html[html.index('class="entete-page"'):html.index('id="titre-bilan"')]
        self.assertNotIn(reverse("collecte:relances"), tete)

    def test_refonte_du_tableau_de_bord(self):
        """Refonte : un verdict en tête (même tolérance que les organisations en retard), des
        chiffres qui mènent à l'action, « À faire maintenant » (seulement ce qui demande une action), le détail en
        onglets avec l'arbre dépliable et le repère « attendu » dans chaque barre."""
        with SANS_SMTP:
            rep = self.tdb(self.admin)
        self.assertEqual(rep.context["attendu"], 50)
        self.assertEqual(rep.context["verdict"], {"code": "retard", "points": 50})  # 0 % validé, 50 % attendu
        self.assertContains(rep, "En retard de 50 points")
        # chiffres cliquables : la Saisie filtrée sur le statut (admin : une organisation à la fois)
        self.assertContains(rep, f'href="{reverse("collecte:saisie")}?campagne={self.c.pk}&amp;statut=a_saisir"')
        self.assertContains(rep, f'href="{reverse("collecte:saisie")}?campagne={self.c.pk}&amp;statut=brouillon"')
        # À faire maintenant : sans SPOC, retards, e-mails (l'alerte e-mails n'est plus dans l'en-tête)
        self.assertEqual([x["code"] for x in rep.context["a_faire"]], ["sans_spoc", "retards", "emails"])
        self.assertContains(rep, "<b>2 organisations en retard</b>")  # mêmes mots que l'Administration 
        self.assertContains(rep, reverse("parametres:hebergement"))
        html = rep.content.decode()
        self.assertNotIn("mention-avertissement", html[:html.index('id="titre-bilan"')])
        # détail : onglets (sans JavaScript, toutes les parties visibles), arbre dépliable, repère attendu
        for nom in ("organisations", "spoc", "themes"):
            self.assertContains(rep, f'role="tab" id="onglet-{nom}"')
            self.assertContains(rep, f'role="tabpanel" id="panneau-{nom}"')
        self.assertContains(rep, f'data-parent="{self.p.pk}"')
        self.assertContains(rep, f'aria-expanded="true" data-deplier="{self.g.pk}"')
        self.assertContains(rep, 'data-filtre-retard')
        self.assertContains(rep, '<span class="repere-attendu" style="left:50%" aria-hidden="true"></span>')
        # tri par taux : liste à plat, sans bouton pour déplier
        self.assertNotContains(self.tdb(self.admin, tri="taux"), "data-deplier=")
        # dans les temps : tout validé
        for k, o in ((self.eff, self.e1), (self.taux, self.e1)):
            S.enregistrer(self.contrib, self.c, k, o, "5", False, "")
            S.valider(self.contrib, self.c, k, o)
        rep = self.tdb(self.valid)
        self.assertEqual(rep.context["verdict"]["code"], "a_temps")
        self.assertContains(rep, "Dans les temps")

    def test_contributeur_lecteur_sans_verdict_ni_actions(self):
        """le contributeur ne voit ni retard ni verdict ; le lecteur n'a ni « À faire » ni lien vers la Saisie."""
        rep = self.tdb(self.contrib)
        self.assertIsNone(rep.context["verdict"])
        self.assertNotContains(rep, "Dans les temps")
        self.assertNotContains(rep, "En retard de")
        self.assertNotContains(rep, 'id="titre-a-faire"')
        self.assertNotContains(rep, 'id="onglet-spoc"')
        self.assertContains(rep, f'href="{reverse("collecte:pour_moi")}?campagne={self.c.pk}&amp;statut=a_saisir"')
        self.assertContains(rep, "Les organisations où des KPI vous sont attribués.")
        lecteur = Utilisateur.objects.create(username="lect", email="lect@exemple.test", role=Utilisateur.Role.LECTEUR)
        rep = self.tdb(lecteur)
        self.assertEqual(rep.status_code, 200)
        self.assertEqual(rep.context["a_faire"], [])
        self.assertNotContains(rep, "&amp;statut=a_saisir")

    @AVEC_SMTP
    def test_meme_derniere_relance_et_memes_nombres_que_l_e_mail(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("collecte:relances"), {"action": "envoyer", "personnes": [self.contrib.pk]})
        self.assertEqual(len(mail.outbox), 1)
        page = self.client.get(reverse("collecte:relances"))
        af_page = next(x for x in page.context["liste"] if x.personne == self.contrib)
        self.assertIn(f"{af_page.nombre} KPI à compléter", mail.outbox[0].subject)  # le nombre affiché est celui de l'e-mail
        date = DC.date_heure_courte(af_page.derniere.date)
        self.assertContains(page, f"Dernière relance : {date}")

    def test_validateur_son_perimetre_contributeur_et_campagne_fermee_sans_liste(self):
        relances = reverse("collecte:relances")
        self.assertContains(self.tdb(self.valid), relances)  # « Préparer la relance… » pour le validateur
        self.assertNotContains(self.tdb(self.contrib), relances)
        Campagne.objects.filter(pk=self.c.pk).update(statut=Campagne.Statut.REVUE)
        self.assertNotContains(self.tdb(self.admin, campagne=self.c.pk), f'{relances}?campagne={self.c.pk}"')

    def test_mots_courants_et_sans_spoc_en_orange(self):
        for user in (self.admin, self.valid, self.contrib):
            with self.subTest(user=user.email):
                html = self.tdb(user).content.decode().lower()
                texte = re.sub(r"<(script|style)\b.*?</\1>", "", html, flags=re.S)  # ce qui s'affiche, sans le code de la page
                for mot in ("cellule", "granularité", "arbre et plan"):
                    self.assertNotIn(mot, texte)
                self.assertIn("ordre de l'arbre", texte)
                # note de méthode repliée (fermée), légende visible
                self.assertIn('<details class="aide-repliable note-methode"><summary>comment ces chiffres sont calculés</summary>', html)
                self.assertIn('<p class="legende discret">', html)
        rep = self.tdb(self.admin)
        self.assertContains(rep, '<strong class="texte-sans-spoc">')
        self.assertNotContains(rep, "texte-erreur")


class LangueRelanceTests(TestCase):
    def test_nom_de_la_langue_de_la_personne(self):
        from referentiel.models import Utilisateur

        p = Utilisateur.objects.create(username="p", email="p@exemple.test", langue="en")
        self.assertEqual(R.langue_de(p), "anglais")
        p.langue = ""
        self.assertEqual(R.langue_de(p), "français")


D = Decimal
SMTP_REFUSE = dict(EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend", EMAIL_HOST="127.0.0.1", EMAIL_PORT=1, EMAIL_TIMEOUT=2)
class BaseTextes(TestCase):
    def setUp(self):
        self.g = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        self.p = Organisation.objects.create(nom="Pays", niveau_id=Niveau.COUNTRY, parent=self.g)
        self.e1 = Organisation.objects.create(nom="E1", niveau_id=Niveau.ENTITY, parent=self.p)
        self.c0 = Campagne.objects.create(exercice=2025, statut=Campagne.Statut.CLOTUREE)
        self.c = Campagne.objects.create(exercice=2026, statut=Campagne.Statut.OUVERTE, seuil_ecart=D("0.2"))
        self.eff = KPI.objects.create(code="EFF", libelle="Effectif", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY,
                                      unite=U("employees"), methode_agregation="Somme")
        self.form = KPI.objects.create(code="FORM", libelle="Formés", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY,
                                       unite=U("employees"), methode_agregation="Somme")
        self.contrib = Utilisateur.objects.create(username="contrib", email="contrib@exemple.test", first_name="Lucas",
                                                  last_name="Bernard")
        self.valid = Utilisateur.objects.create(username="valid", email="valid@exemple.test", role=Utilisateur.Role.VALIDATEUR)
        self.admin = Utilisateur.objects.create(username="admin", email="admin@exemple.test", role=Utilisateur.Role.ADMIN)
        for k in (self.eff, self.form):
            Attribution.objects.create(kpi=k, organisation=self.e1, utilisateur=self.contrib)
        Reponse.objects.create(periode=self.c0.periode, kpi=self.eff, organisation=self.e1, valeur=D(100),
                               statut=Reponse.Statut.VALIDE, origine=Reponse.Origine.IMPORT)

    def page(self, nom, user=None, *args):
        self.client.force_login(user or self.admin)
        rep = self.client.get(reverse(f"collecte:{nom}", args=args))
        self.assertEqual(rep.status_code, 200, nom)
        return rep.content.decode()


class TextesALEcranTests(BaseTextes):
    """T1 : messages en clair (serveur d'e-mails injoignable, e-mail invalide), nombres des règles avec séparateur de
    milliers, noms accessibles des unités, aperçu de l'assistant sans jargon."""

    def test_cause_d_un_echec_en_clair(self):
        from . import relances as R

        self.assertEqual(R.cause_echec("ConnectionRefusedError : [Errno 111] Connection refused"), "le serveur d'e-mails ne répond pas")
        self.assertEqual(R.cause_echec(ConnectionRefusedError(111, "refused")), "le serveur d'e-mails ne répond pas")
        self.assertEqual(R.cause_echec("SMTPAuthenticationError : (535, b'bad')"),
                         "le serveur d'e-mails refuse l'identifiant ou le mot de passe de l'outil")
        self.assertEqual(R.cause_echec("ValueError : x"), "le serveur d'e-mails a refusé l'envoi")
        self.assertEqual(R.cause_echec(""), "le serveur d'e-mails a refusé l'envoi")

    def test_relances_serveur_injoignable(self):
        from django.test import override_settings

        self.client.force_login(self.admin)
        with override_settings(**SMTP_REFUSE), self.assertLogs("reporting.relances", "WARNING"):
            rep = self.client.post(reverse("collecte:relances"), {"action": "essai", "personnes": [self.contrib.pk]}, follow=True)
            html = rep.content.decode()
            self.assertIn("L&#x27;essai n&#x27;est pas parti : le serveur d&#x27;e-mails ne répond pas.</strong> Contactez l&#x27;IT", html)
            self.assertNotIn("Errno", html.split("<main", 1)[1])
            rep = self.client.post(reverse("collecte:relances"), {"action": "envoyer", "personnes": [self.contrib.pk]}, follow=True)
            html = rep.content.decode().split("<main", 1)[1]
        self.assertIn("1 relance n&#x27;est pas partie (Lucas Bernard) : le serveur d&#x27;e-mails ne répond pas.</strong> Contactez l&#x27;IT.", html)
        self.assertIn('title="Pas partie : le serveur d&#x27;e-mails ne répond pas. Contactez l\'IT."', html)
        self.assertNotIn("Errno", html)
        self.assertIn("Errno", Relance.objects.get().erreur)  # le détail technique reste noté pour l'IT

    def test_email_invalide(self):
        self.client.force_login(self.admin)
        rep = self.client.post(reverse("collecte:admin_compte_nouveau"), {"first_name": "A", "last_name": "B", "email": "pas-un-email",
                                                                          "role": "contributeur", "is_active": "on"})
        html = rep.content.decode()
        self.assertIn("Saisissez une adresse comme prenom.nom@example.com.", html)
        self.assertNotIn("courriel", html)

    def test_regle_avec_separateur_de_milliers(self):
        from . import coherence as CO

        self.assertEqual(CO.afficher(D("1131"), self.eff), "1 131,00")
        self.assertEqual(CO.afficher(D("-1234.567"), None), "-1 234,57")

    def test_unites_et_assistant(self):
        racine = Path(__file__).resolve().parent.parent / "parametres/templates/parametres"
        unites = (racine / "_unites.html").read_text(encoding="utf-8")
        # libellés accessibles de chaque champ d'unité : clés de libellé (texte français dans libelles/admin.fr.json)
        self.assertIn('aria-label="{% libelle "admin.unites.thematique_de" symbole=e|tr:"symbole" %}"', unites)
        self.assertIn('aria-label="{% libelle "admin.unites.decimales_de" symbole=e|tr:"symbole" %}"', unites)
        from parametres.libelles import libelle

        self.assertEqual(libelle("admin.unites.thematique_de", "fr", symbole="kWh"), "Thématique de l'unité « kWh »")
        self.assertEqual(libelle("admin.unites.decimales_de", "fr", symbole="kWh"), "Décimales de l'unité « kWh »")
        self.assertNotIn("SSO", (racine / "mise_en_place/compte.html").read_text(encoding="utf-8"))


class PersonneARelancerTests(BaseEchanges):
    """P7 : sans SPOC, « Personne n'a de saisie en attente : tout est validé » ne s'affiche plus quand rien n'est validé."""

    def setUp(self):
        super().setUp()
        from referentiel.models import Attribution

        Attribution.objects.all().delete()
        self.client.force_login(self.admin)

    def test_tableau_de_bord(self):
        from django.urls import reverse

        rep = self.client.get(reverse("collecte:tableau_de_bord"))  # plus de liste « À relancer » ici 
        self.assertNotContains(rep, "tout est validé")
        self.assertNotContains(rep, 'id="titre-a-relancer"')

    def test_page_relances(self):
        from django.urls import reverse

        rep = self.client.get(reverse("collecte:relances"))
        self.assertNotContains(rep, "tout est validé")
        self.assertContains(rep, "cases restantes n'ont pas de SPOC")

    def test_tout_valide(self):
        from django.urls import reverse

        Reponse.objects.filter(periode=self.c.periode).update(statut=Reponse.Statut.VALIDE)
        for k in KPI.objects.filter(type_saisie_id="Saisi"):
            for o in (self.e1, self.e2):
                Reponse.objects.update_or_create(periode=self.c.periode, kpi=k, organisation=o,
                                                 defaults={"valeur": D(1), "statut": Reponse.Statut.VALIDE, "texte": ""})
        rep = self.client.get(reverse("collecte:relances"))  # la liste « À relancer » est sur la page Relances
        self.assertContains(rep, "tout est validé")
        self.assertNotContains(rep, "pas de SPOC, donc personne")
