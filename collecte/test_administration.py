"""Espace Administration : campagnes, organisations, comptes, journal."""
import datetime
from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse

from referentiel.models import Attribution, Niveau, Organisation, OrgAlias, Utilisateur

from .models import Campagne, Journal
from .aides_tests.saisie import Base
from .aides_tests.revue_admin import Base as BaseAdmin
from collecte.outils_tests import html_de

FETCH = {"HTTP_X_REQUESTED_WITH": "fetch"}


class AdministrationTests(TestCase):
    def setUp(self):
        self.admin = Utilisateur.objects.create(username="admin", email="admin@exemple.test", role=Utilisateur.Role.ADMIN)
        self.contrib = Utilisateur.objects.create(username="contrib", email="contrib@exemple.test")
        self.g = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        self.p = Organisation.objects.create(nom="Pays", niveau_id=Niveau.COUNTRY, parent=self.g)
        self.e = Organisation.objects.create(nom="E1", niveau_id=Niveau.ENTITY, parent=self.p)
        self.c25 = Campagne.objects.create(exercice=2025, statut=Campagne.Statut.OUVERTE, seuil_ecart=Decimal("0.2"))
        self.client.force_login(self.admin)

    def post(self, vue, args=None, **donnees):
        return self.client.post(reverse(f"collecte:{vue}", args=args), donnees, **FETCH).json()

    def test_reserve_a_l_admin_et_pages(self):
        for nom in ("admin_accueil", "admin_campagnes", "admin_organisations", "admin_comptes", "admin_journal"):
            self.assertEqual(self.client.get(reverse(f"collecte:{nom}")).status_code, 200, nom)
        self.assertContains(self.client.get(reverse("collecte:admin_accueil")), "Exercice 2025 ouvert")
        self.client.force_login(self.contrib)
        for nom in ("admin_accueil", "admin_campagnes", "admin_organisations", "admin_comptes", "admin_journal"):
            self.assertEqual(self.client.get(reverse(f"collecte:{nom}")).status_code, 403, nom)
        self.assertEqual(self.client.post(reverse("collecte:admin_compte_nouveau"), {"email": "x@exemple.test"}).status_code, 403)

    # -- campagnes ---------------------------------------------------------------
    def test_preparer_l_exercice_suivant(self):
        html = self.client.get(reverse("collecte:admin_campagne_nouvelle"), **FETCH).json()["html"]
        self.assertIn('value="2026"', html)  # exercice suivant proposé
        self.assertIn('value="2027-03-31"', html)
        res = self.post("admin_campagne_nouvelle", exercice=2026, date_ouverture="2027-01-05", date_fin_saisie="2027-03-31",
                        seuil_pct="15", action="enregistrer")
        self.assertTrue(res["ok"], res["html"])
        c = Campagne.objects.get(exercice=2026)
        self.assertEqual((c.statut, c.seuil_ecart), (Campagne.Statut.PREPARATION, Decimal("0.15")))

    def test_dates_incoherentes(self):
        res = self.post("admin_campagne", [self.c25.pk], date_ouverture="2026-03-31", date_fin_saisie="2026-01-05", action="enregistrer")
        self.assertFalse(res["ok"])
        self.assertIn("avant son début", res["html"])

    def test_plusieurs_campagnes_ouvertes_cloture_et_reouverture(self):
        c26 = Campagne.objects.create(exercice=2026)
        res = self.post("admin_campagne", [c26.pk], action="ouvrir")  # 2025 encore ouverte : permis (une par période)
        self.assertTrue(res["ok"], res["html"])
        self.assertEqual(Campagne.objects.filter(statut=Campagne.Statut.OUVERTE).count(), 2)
        self.post("admin_campagne", [self.c25.pk], action="cloturer")
        self.assertEqual(Campagne.objects.get(exercice=2025).statut, Campagne.Statut.CLOTUREE)
        self.assertEqual(Campagne.objects.get(exercice=2026).statut, Campagne.Statut.OUVERTE)
        self.assertTrue(Journal.objects.filter(action="cloturer", champ="statut", apres="cloturee").exists())

    def test_prolonger_en_changeant_la_date_de_fin(self):
        res = self.post("admin_campagne", [self.c25.pk], date_ouverture="2026-01-05", date_fin_saisie="2026-04-30", seuil_pct="20",
                        action="enregistrer")
        self.assertTrue(res["ok"], res["html"])
        self.assertEqual(Campagne.objects.get(exercice=2025).date_fin_saisie, datetime.date(2026, 4, 30))
        self.assertTrue(Journal.objects.filter(action="reglage_campagne", champ="date_fin_saisie").exists())

    def test_seuil_enregistre_au_dessus_de_100_garde_s_il_est_inchange(self):
        """Seuil de 300 % enregistré avant la borne de 100 % : la campagne s'enregistre encore pour un autre réglage ;
        une nouvelle valeur au-dessus de 100 reste refusée."""
        Campagne.objects.filter(pk=self.c25.pk).update(seuil_ecart=Decimal("3"))
        html = self.client.get(reverse("collecte:admin_campagne", args=[self.c25.pk])).content.decode()
        self.assertNotIn('max="100"', html)  # le navigateur ne bloque pas l'envoi de la valeur enregistrée
        res = self.post("admin_campagne", [self.c25.pk], date_ouverture="2026-01-05", date_fin_saisie="2026-04-30",
                        seuil_pct="300", action="enregistrer")
        self.assertTrue(res["ok"], res["html"])
        c = Campagne.objects.get(pk=self.c25.pk)
        self.assertEqual((c.date_fin_saisie, c.seuil_ecart), (datetime.date(2026, 4, 30), Decimal("3")))
        res = self.post("admin_campagne", [self.c25.pk], date_ouverture="2026-01-05", date_fin_saisie="2026-04-30",
                        seuil_pct="250", action="enregistrer")
        self.assertFalse(res["ok"])
        self.assertEqual(Campagne.objects.get(pk=self.c25.pk).seuil_ecart, Decimal("3"))
        res = self.post("admin_campagne", [self.c25.pk], date_ouverture="2026-01-05", date_fin_saisie="2026-04-30",
                        seuil_pct="40", action="enregistrer")  # redescendre sous 100 : accepté
        self.assertTrue(res["ok"], res["html"])
        Campagne.objects.filter(pk=self.c25.pk).update(seuil_ecart=Decimal("0.2"))  # seuil ordinaire : borne 100 intacte
        self.assertIn('max="100"', self.client.get(reverse("collecte:admin_campagne", args=[self.c25.pk])).content.decode())
        res = self.post("admin_campagne", [self.c25.pk], date_ouverture="2026-01-05", date_fin_saisie="2026-04-30",
                        seuil_pct="300", action="enregistrer")
        self.assertFalse(res["ok"])

    def test_cloture_contributeurs_puis_cloture_definitive(self):
        from . import saisie as S
        from referentiel.models import KPI, Attribution

        kpi = KPI.objects.create(code="EFF", libelle="Effectif", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY)
        Attribution.objects.create(kpi=kpi, organisation=self.e, utilisateur=self.contrib)
        S.enregistrer(self.contrib, self.c25, kpi, self.e, "10", False, "")
        # 1. clôture contributeurs : le contributeur est bloqué, l'admin corrige
        res = self.post("admin_campagne", [self.c25.pk], action="revue")
        self.assertIn("Clôture contributeurs", res["html"])
        self.c25.refresh_from_db()
        self.assertEqual(self.c25.statut, Campagne.Statut.REVUE)
        self.assertFalse(S.droits(self.contrib, self.c25, kpi, self.e).modifier)
        self.assertIn("l'administrateur relit", S.droits(self.contrib, self.c25, kpi, self.e).motif)
        S.enregistrer(self.admin, self.c25, kpi, self.e, "12", False, "Correction")
        # 2. clôture définitive : figée pour tous, admin compris
        self.post("admin_campagne", [self.c25.pk], action="cloturer")
        self.c25.refresh_from_db()
        d = S.droits(self.admin, self.c25, kpi, self.e)
        self.assertFalse(d.modifier or d.repasser_brouillon)
        self.assertTrue(d.voir)
        from django.core.exceptions import PermissionDenied
        with self.assertRaises(PermissionDenied):
            S.enregistrer(self.admin, self.c25, kpi, self.e, "13", False, "")
        rep = self.client.get(reverse("collecte:saisie") + f"?campagne={self.c25.pk}&org={self.e.id}")
        self.assertContains(rep, "lecture seule pour tous")
        # 3. réouverture tracée : d'abord pour l'équipe responsable, puis aux contributeurs
        self.post("admin_campagne", [self.c25.pk], action="rouvrir")
        self.c25.refresh_from_db()
        self.assertEqual(self.c25.statut, Campagne.Statut.REVUE)
        self.assertTrue(S.droits(self.admin, self.c25, kpi, self.e).modifier)
        self.post("admin_campagne", [self.c25.pk], action="rouvrir_contributeurs")
        self.c25.refresh_from_db()
        self.assertEqual(self.c25.statut, Campagne.Statut.OUVERTE)
        self.assertEqual(list(Journal.objects.filter(action__in=["revue", "cloturer", "rouvrir", "rouvrir_contributeurs"])
                              .order_by("date", "id").values_list("action", flat=True)),
                         ["revue", "cloturer", "rouvrir", "rouvrir_contributeurs"])

    def test_transition_impossible(self):
        res = self.post("admin_campagne", [self.c25.pk], action="rouvrir")  # une campagne ouverte ne se « rouvre » pas
        self.assertIn("Action impossible", res["html"])

    def test_revue_ne_bloque_pas_l_ouverture_d_une_autre_campagne(self):
        self.post("admin_campagne", [self.c25.pk], action="revue")
        c26 = Campagne.objects.create(exercice=2026)
        self.assertTrue(self.post("admin_campagne", [c26.pk], action="ouvrir")["ok"])
        self.assertTrue(self.post("admin_campagne", [self.c25.pk], action="rouvrir_contributeurs")["ok"])  # deux ouvertes

    # -- organisations -----------------------------------------------------------
    def test_ajouter_un_site_rattache(self):
        html = self.client.get(reverse("collecte:admin_organisation_nouvelle") + f"?parent={self.e.id}", **FETCH).json()["html"]
        self.assertRegex(html, r'value="Site"[^>]* checked')  # niveau proposé sous une entité : le niveau juste en dessous
        res = self.post("admin_organisation_nouvelle", nom="Nouveau site", niveau="Site", parent=self.e.id, rang=0, actif="on",
                        type_site="bureau", action="enregistrer")
        self.assertTrue(res["ok"], res["html"])
        self.assertEqual(Organisation.objects.get(nom="Nouveau site").parent, self.e)

    def test_rattachement_au_mauvais_niveau_refuse(self):
        res = self.post("admin_organisation_nouvelle", nom="Pays perdu", niveau="Country", parent=self.e.id, rang=0, actif="on",
                        action="enregistrer")
        self.assertFalse(res["ok"])
        self.assertIn("niveau supérieur", res["html"])
        self.assertFalse(Organisation.objects.filter(nom="Pays perdu").exists())
        # rattachement souple : un site directement sous un pays
        res = self.post("admin_organisation_nouvelle", nom="Site direct", niveau="Site", parent=self.p.id, rang=0, actif="on",
                        action="enregistrer")
        self.assertTrue(res["ok"], res["html"])

    def test_desactiver_et_libelles_d_import(self):
        res = self.post("admin_organisation", [self.e.id], nom="E1", niveau="Entity", parent=self.p.id, rang=0, action="enregistrer")
        self.assertTrue(res["ok"], res["html"])
        self.e.refresh_from_db()
        self.assertFalse(self.e.actif)
        self.assertIsNotNone(self.e.date_desactivation)
        self.post("admin_organisation", [self.e.id], action="ajouter_alias", libelle="E1 – Usine 2", source="Fichier historique")
        self.assertTrue(OrgAlias.objects.filter(organisation=self.e, libelle="E1 – Usine 2").exists())
        res = self.post("admin_organisation", [self.p.id], action="ajouter_alias", libelle="E1 – Usine 2", source="Fichier historique")
        self.assertIn("déjà rattaché", res["html"])
        a = OrgAlias.objects.get()
        self.post("admin_organisation", [self.e.id], action="retirer_alias", alias=a.id)
        self.assertFalse(OrgAlias.objects.exists())

    # -- comptes (créés par l'équipe responsable, sans SSO) --------------------------------
    def compte(self, **champs):
        donnees = {"first_name": "Léa", "last_name": "Martin", "email": "lea.martin@exemple.test", "role": "contributeur",
                   "is_active": "on", "action": "enregistrer"}
        donnees.update(champs)
        return donnees

    def test_creer_un_compte_mot_de_passe_provisoire_puis_changement_obligatoire(self):
        res = self.post("admin_compte_nouveau", **self.compte(email="Lea.Martin@Exemple.test"))
        self.assertTrue(res["ok"], res["html"])
        self.assertIn("Message à envoyer", res["html"])
        import re
        mdp = re.search(r"Mot de passe provisoire : (\S+)", res["html"]).group(1)
        u = Utilisateur.objects.get(email="lea.martin@exemple.test")
        self.assertTrue(u.doit_changer_mdp)
        self.assertEqual(u.username, "lea.martin@exemple.test")
        # connexion par e-mail, sans tenir compte des majuscules
        self.client.logout()
        rep = self.client.post(reverse("login"), {"username": "LEA.MARTIN@exemple.test", "password": mdp})
        self.assertEqual(rep.status_code, 302)
        # tant que le mot de passe provisoire n'est pas changé, tout renvoie vers « Mon compte »
        self.assertRedirects(self.client.get(reverse("collecte:pour_moi")), reverse("collecte:mon_compte"))
        rep = self.client.post(reverse("collecte:mon_compte"), {"old_password": mdp, "new_password1": "Mon-nouveau-mdp-2026",
                                                                 "new_password2": "Mon-nouveau-mdp-2026"})
        self.assertEqual(rep.status_code, 302)
        u.refresh_from_db()
        self.assertFalse(u.doit_changer_mdp)
        self.assertEqual(self.client.get(reverse("collecte:pour_moi")).status_code, 200)
        self.assertTrue(Journal.objects.filter(action="changement_mdp").exists())

    def test_mot_de_passe_choisi_par_l_admin_et_reinitialisation(self):
        self.post("admin_compte_nouveau", **self.compte(mot_de_passe="provisoire-2026"))
        u = Utilisateur.objects.get(email="lea.martin@exemple.test")
        self.assertTrue(u.check_password("provisoire-2026"))
        u.doit_changer_mdp = False
        u.save()
        res = self.post("admin_compte", [u.id], action="reinitialiser")
        self.assertIn("Nouveau mot de passe provisoire", res["html"])
        u.refresh_from_db()
        self.assertTrue(u.doit_changer_mdp)
        self.assertFalse(u.check_password("provisoire-2026"))

    def test_role_admin_donne_le_mode_expert(self):
        self.post("admin_compte", [self.contrib.id], **self.compte(email="contrib@exemple.test", role="admin"))
        self.contrib.refresh_from_db()
        self.assertTrue(self.contrib.is_staff and self.contrib.is_superuser)
        self.post("admin_compte", [self.contrib.id], **self.compte(email="contrib@exemple.test", role="contributeur"))
        self.contrib.refresh_from_db()
        self.assertFalse(self.contrib.is_staff or self.contrib.is_superuser)

    def test_pas_d_auto_exclusion(self):
        res = self.post("admin_compte", [self.admin.id], **self.compte(email="admin@exemple.test", role="contributeur"))
        self.assertIn("propre rôle", res["html"])
        donnees = self.compte(email="admin@exemple.test", role="admin")
        del donnees["is_active"]
        res = self.post("admin_compte", [self.admin.id], **donnees)
        self.assertIn("désactiver votre propre compte", res["html"])
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active and self.admin.role == "admin")

    def test_email_en_double(self):
        res = self.post("admin_compte_nouveau", **self.compte(email="CONTRIB@exemple.test"))
        self.assertFalse(res["ok"])
        self.assertIn("existe déjà", res["html"])

    def test_suppression_seulement_si_jamais_utilise(self):
        self.post("admin_compte_nouveau", **self.compte())
        u = Utilisateur.objects.get(email="lea.martin@exemple.test")
        self.post("admin_compte", [u.id], action="supprimer")
        self.assertFalse(Utilisateur.objects.filter(pk=u.pk).exists())
        from referentiel.models import KPI, Attribution
        kpi = KPI.objects.create(code="EFF", libelle="Effectif", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY)
        Attribution.objects.create(kpi=kpi, organisation=self.e, utilisateur=self.contrib)
        res = self.post("admin_compte", [self.contrib.id], action="supprimer")
        self.assertIn("désactivez-le au lieu de le supprimer", res["html"])
        self.assertTrue(Utilisateur.objects.filter(pk=self.contrib.pk).exists())

    def test_journal_separe_saisies_et_administration(self):
        from referentiel.models import KPI, Attribution
        from . import saisie as S

        kpi = KPI.objects.create(code="EFF", libelle="Effectif", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY)
        Attribution.objects.create(kpi=kpi, organisation=self.e, utilisateur=self.contrib)
        S.enregistrer(self.contrib, self.c25, kpi, self.e, "42", False, "")
        self.post("admin_campagne", [self.c25.pk], action="revue")
        saisies = self.client.get(reverse("collecte:admin_journal"))  # vue par défaut : saisie des données
        self.assertContains(saisies, "Effectif · E1 · 2025")
        self.assertNotContains(saisies, "fermé une campagne")
        self.assertContains(self.client.get(reverse("collecte:admin_journal") + f"?exercice=2025&org={self.e.id}"), "Effectif · E1")
        self.assertNotContains(self.client.get(reverse("collecte:admin_journal") + f"?org={self.p.id}"), "Effectif · E1")
        admin = self.client.get(reverse("collecte:admin_journal") + "?vue=admin")
        self.assertContains(admin, "fermé une campagne aux contributeurs")
        self.assertNotContains(admin, "Effectif · E1")

    # -- grille des attributions ----------------------------------------------------
    def test_grille_et_synchronisation_avec_la_saisie(self):
        import json
        from referentiel.models import KPI, Attribution
        from . import saisie as S

        e2 = Organisation.objects.create(nom="E2", niveau_id=Niveau.ENTITY, parent=self.p)
        kpi = KPI.objects.create(code="EFF", libelle="Effectif", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY)
        KPI.objects.create(code="DBL", libelle="Double", type_saisie_id="Calculé", formule="[EFF] * 2", granularite_id=Niveau.ENTITY)
        Attribution.objects.create(kpi=kpi, organisation=self.e, utilisateur=self.contrib)
        rep = self.client.get(reverse("collecte:admin_attributions") + "?niveau=Entity")
        self.assertContains(rep, "Effectif")
        self.assertNotContains(rep, "Double")  # un KPI calculé ne s'attribue pas
        self.assertEqual(rep.context["onglet"]["sans"], 1)  # E2 sans SPOC
        # attribution depuis la grille : la case renvoyée est une case de grille, et la page Saisie voit le SPOC
        res = self.client.post(reverse("collecte:attribuer"), json.dumps({"cles": [f"EFF|{e2.id}"], "utilisateur": self.contrib.id,
                                                                        "format": "cellule"}), content_type="application/json").json()
        self.assertIn('class="cellule-attr', res["lignes"][f"EFF|{e2.id}"])
        self.assertEqual({o.nom for _, o in S.cellules(self.contrib)}, {"E1", "E2"})
        self.assertEqual(self.client.get(reverse("collecte:admin_attributions")).context["onglet"]["sans"], 0)

    def test_remplacer_une_personne_partout(self):
        from referentiel.models import KPI, Attribution

        kpi = KPI.objects.create(code="EFF", libelle="Effectif", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY)
        Attribution.objects.create(kpi=kpi, organisation=self.e, utilisateur=self.contrib)
        Attribution.objects.create(kpi=kpi, organisation=self.p, utilisateur=self.contrib, role=Attribution.Role.VALIDATEUR)
        relai = Utilisateur.objects.create(username="relai", email="relai@exemple.test")
        rep = self.client.post(reverse("collecte:admin_remplacer"), {"de": self.contrib.id, "par": relai.id, "desactiver": "on"})
        self.assertEqual(rep.status_code, 302)
        self.assertEqual(Attribution.objects.filter(utilisateur=relai).count(), 2)
        self.assertFalse(Attribution.objects.filter(utilisateur=self.contrib).exists())
        self.contrib.refresh_from_db()
        self.assertFalse(self.contrib.is_active)

    # -- journal ---------------------------------------------------------------------
    def test_journal_lisible_et_filtrable(self):
        self.post("admin_campagne", [self.c25.pk], action="cloturer")
        self.post("admin_compte", [self.contrib.id], first_name="Camille", last_name="C", email="contrib@exemple.test", role="validateur", is_active="on")
        rep = self.client.get(reverse("collecte:admin_journal") + "?vue=admin")
        self.assertContains(rep, "a clôturé définitivement une campagne")
        self.assertContains(rep, "Exercice 2025")
        self.assertContains(rep, "clôturée")
        rep = self.client.get(reverse("collecte:admin_journal") + "?vue=admin&famille=compte")
        self.assertContains(rep, "a modifié un compte")
        self.assertNotContains(rep, "a clôturé définitivement une campagne")


class PlusieursTests(TestCase):
    """Administration › Organisations et Comptes : création de plusieurs éléments d'un coup."""

    def setUp(self):
        from referentiel.models import Utilisateur

        self.admin = Utilisateur.objects.create_user("admin", email="admin@exemple.test", password="x", role=Utilisateur.Role.ADMIN)
        self.client.force_login(self.admin)

    def test_plusieurs_organisations(self):
        from django.urls import reverse

        from parametres import niveaux as N
        from referentiel.models import Organisation

        n1, n2 = N.tous()[:2]
        texte = "Mon groupe\n  France\n  Espagne"
        rep = self.client.post(reverse("collecte:admin_organisations_plusieurs"), {"arbre": texte, "action": "apercu"})
        self.assertContains(rep, "3 organisations lues")
        self.assertFalse(Organisation.objects.exists())
        rep = self.client.post(reverse("collecte:admin_organisations_plusieurs"), {"arbre": texte, "action": "creer"})
        self.assertRedirects(rep, reverse("collecte:admin_organisations"))
        self.assertEqual(Organisation.objects.get(nom="France").parent.nom, "Mon groupe")
        self.assertEqual(Organisation.objects.get(nom="France").niveau_id, n2.code)

    def test_plusieurs_comptes(self):
        from django.urls import reverse

        from referentiel.models import Utilisateur

        rep = self.client.post(reverse("collecte:admin_comptes_plusieurs"), {
            "first_name_0": "Ana", "last_name_0": "Lima", "email_0": "ana@exemple.test", "role_0": "contributeur",
            "first_name_1": "Bob", "email_1": "pas-un-email", "role_1": "contributeur"})
        self.assertContains(rep, "Message à envoyer à Ana")
        self.assertContains(rep, "Ligne 2")
        self.assertTrue(Utilisateur.objects.filter(email="ana@exemple.test", doit_changer_mdp=True).exists())


class AccueilATraiterTests(Base):
    """Vue d'ensemble de l'administration : ce qui attend l'équipe responsable, le plus urgent d'abord, puis les rubriques."""

    @override_settings(EMAIL_HOST="")  # sans dépendre de la configuration SMTP de l'environnement
    def test_a_traiter(self):
        from django.utils import timezone

        from .models import Alerte

        self.client.force_login(self.admin)
        url = reverse("collecte:admin_accueil")
        self.c.date_fin_saisie = timezone.localdate() - datetime.timedelta(days=2)
        self.c.save()
        Alerte.objects.create(campagne=self.c, kpi=self.eff, organisation=self.e1, controle=Alerte.Controle.ECART_N1,
                              message="Écart", statut=Alerte.Statut.JUSTIFIEE)
        titres = [t["titre"] for t in self.client.get(url).context["a_traiter"]]
        self.assertEqual(titres, ["Fin de saisie dépassée", "1 justification à trancher", "2 cases sans SPOC",
                                  "E-mails pas encore configurés"])  # E2 : EFF et TX sans SPOC
        rep = self.client.get(url)
        self.assertContains(rep, f'{reverse("collecte:coherence")}?campagne={self.c.pk}&amp;statut=justifiee')
        self.assertContains(rep, "À quoi sert chaque rubrique")
        # tout est en ordre : rien à traiter
        for k in (self.eff, self.taux):
            Attribution.objects.create(kpi=k, organisation=self.e2, utilisateur=self.autre)
        self.c.date_fin_saisie = timezone.localdate() + datetime.timedelta(days=10)
        self.c.save()
        Alerte.objects.update(statut=Alerte.Statut.ACCEPTEE)
        with override_settings(EMAIL_HOST="smtp.exemple.test"):
            rep = self.client.get(url)
        self.assertEqual(rep.context["a_traiter"], [])
        self.assertContains(rep, "Rien à traiter")


class AdministrationD1D2Tests(BaseAdmin):
    """Ordre des rubriques, aide, campagnes repliables, un seul bouton."""

    def test_ordre_des_rubriques(self):
        html = html_de(self.client, reverse("collecte:admin_accueil"))
        nav = html.split('id="rubriques-admin"')[1].split("</nav>")[0]
        ordre = [nav.index(reverse(f"collecte:admin_{n}")) for n in ("organisations", "comptes")]
        ordre += [nav.index(reverse("parametres:referentiels")), nav.index(reverse("collecte:admin_attributions")),
                  nav.index(reverse("collecte:admin_campagnes")), nav.index(reverse("parametres:identite"))]
        self.assertEqual(ordre, sorted(ordre))
        self.assertIn("L'arbre des organisations.", html)  # sans les noms des niveaux

    def test_campagnes_repliables_et_bouton_unique(self):
        Campagne.objects.filter(pk=self.c.pk).update(statut=Campagne.Statut.CLOTUREE)
        html = html_de(self.client, reverse("collecte:admin_campagnes"))
        self.assertIn('data-pli-memoire="campagnes.', html)
        self.assertNotIn("Préparer l'exercice suivant", html)
        self.assertIn("</svg> Nouvelle campagne</a>", html)  # icône « plus » dessinée
        self.assertNotRegex(html, r'<details class="pli-campagnes"[^>]* open>\s*<summary[^>]*>\s*<h2>[^\n]*1 campagne')
        Campagne.objects.filter(pk=self.c.pk).update(statut=Campagne.Statut.OUVERTE)
        html = html_de(self.client, reverse("collecte:admin_campagnes"))
        self.assertRegex(html, r'<details class="pli-campagnes"[^>]* open>')

    def test_fiche_sans_phrase_saisie_ouverte_et_calculs_replies(self):
        rep = self.client.get(reverse("collecte:admin_campagne", args=[self.c.pk]), HTTP_X_REQUESTED_WITH="fetch")
        self.assertEqual(rep.status_code, 200)
        html = rep.json()["html"] if rep["Content-Type"].startswith("application/json") else rep.content.decode()
        self.assertNotIn("Pour <strong>prolonger</strong>", html)
        self.assertIn('<details class="pli-calculs">', html)


class ComptesD4Tests(BaseAdmin):
    def test_liste_sans_pastilles_ni_legende(self):
        html = html_de(self.client, reverse("collecte:admin_comptes"))
        self.assertIn('class="resume-comptes"', html)
        self.assertNotIn("bandeau-comptes", html)
        self.assertNotIn("L'administrateur crée les comptes ici", html)

    def test_perimetre_en_arbre_et_tout_coche_vaut_toutes(self):
        lecteur = Utilisateur.objects.create(username="lec", email="lec@exemple.test", first_name="L", last_name="L",
                                             role=Utilisateur.Role.LECTEUR)
        rep = self.client.get(reverse("collecte:admin_compte", args=[lecteur.pk]), HTTP_X_REQUESTED_WITH="fetch")
        self.assertEqual(rep.status_code, 200)
        html = rep.json()["html"] if rep["Content-Type"].startswith("application/json") else rep.content.decode()
        self.assertIn("data-perimetre", html)
        self.assertRegex(html, rf'name="perimetre_lecture" value="{self.e1.id}"[^>]*checked')
        base = {"first_name": "L", "last_name": "L", "email": lecteur.email, "equipe": "", "role": "lecteur", "is_active": "on",
                "action": "enregistrer"}
        tous = [self.g.id, self.e1.id, self.e2.id]
        self.client.post(reverse("collecte:admin_compte", args=[lecteur.pk]), {**base, "perimetre_lecture": tous}, HTTP_X_REQUESTED_WITH="fetch")
        self.assertEqual(lecteur.perimetre_lecture.count(), 0)  # toutes : rien d'enregistré
        self.client.post(reverse("collecte:admin_compte", args=[lecteur.pk]), {**base, "perimetre_lecture": [self.e1.id]}, HTTP_X_REQUESTED_WITH="fetch")
        self.assertEqual(list(lecteur.perimetre_lecture.values_list("id", flat=True)), [self.e1.id])


class AttributionsD5Tests(BaseAdmin):
    """Barre de filtres (thème), thèmes repliables, aide du choix lue seulement à l'écran."""

    def test_barre_et_themes(self):
        html = html_de(self.client, reverse("collecte:admin_attributions"))
        self.assertIn('class="tete-attributions"', html)
        self.assertIn('data-aller="?niveau=', html)  # « KPI calculés » en case à cocher
        if 'class="replier-theme"' in html:
            self.assertIn('<tbody data-theme="1">', html)
        self.assertNotIn('<p class="discret m-0 mt-8">Choisissez une personne', html)
