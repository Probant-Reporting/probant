"""Conservation des preuves des KPI sensibles (collecte/conservation.py) : liste, délais, suppression réelle du fichier,
journal, droits, page vide, réglage de la durée, rappel « À traiter », espaces."""
import datetime
from pathlib import Path

from django.core.files.base import ContentFile
from django.urls import reverse

from collecte import conservation as CV
from collecte.aides_tests.lecture_seule import Base
from collecte.models import Campagne, Journal, Preuve, Reponse
from parametres.models import Instance
from referentiel.models import KPI, Attribution, Utilisateur

AUJOURDHUI = datetime.date(2026, 11, 13)


class ConservationBase(Base):
    """Une réponse validée de 2025 (campagne clôturée) du KPI EFF, avec une preuve déposée par le contributeur."""

    def setUp(self):
        super().setUp()
        self.valide = Utilisateur.objects.create(username="val", email="val@exemple.test", role=Utilisateur.Role.VALIDATEUR)
        Attribution.objects.create(kpi=self.eff, organisation=self.e1, utilisateur=self.valide, role=Attribution.Role.VALIDATEUR)
        self.reponse = Reponse.objects.get(periode=self.c0.periode, kpi=self.eff, organisation=self.e1)
        self.preuve = self.deposer(self.reponse, "facture-dupont.pdf")

    def deposer(self, reponse, nom):
        return Preuve.objects.create(reponse=reponse, fichier=ContentFile(b"%PDF-1.4 essai", name=nom), nom_fichier=nom,
                                     depose_par=self.contrib)

    def sensible(self, niveau=KPI.Confidentialite.RESTREINT):
        KPI.objects.filter(code="EFF").update(confidentialite=niveau)

    def duree(self, mois):
        i = Instance.courante()
        i.preuves_sensibles_mois = mois
        i.save()

    def ids(self, **kw):
        return [l["preuve"].pk for l in CV.a_supprimer(aujourdhui=kw.pop("aujourdhui", AUJOURDHUI), **kw)]


class ListeTests(ConservationBase):
    def test_sans_duree_rien_n_est_propose(self):
        self.sensible()
        self.assertIsNone(CV.mois_reglage())
        self.assertEqual(CV.a_supprimer(), [])
        self.assertEqual(CV.nombre(), 0)

    def test_kpi_non_sensible_jamais_propose(self):
        self.assertEqual(self.ids(mois=1), [])  # « Non sensible » par défaut
        for niveau in (KPI.Confidentialite.RESTREINT, KPI.Confidentialite.CONFIDENTIEL):
            self.sensible(niveau)
            self.assertEqual(self.ids(mois=1), [self.preuve.pk], niveau)
        self.sensible(KPI.Confidentialite.NON_SENSIBLE)
        self.assertEqual(self.ids(mois=1), [])

    def test_delai_compte_depuis_la_fin_de_la_periode(self):
        self.sensible()
        # période 2025 finie le 31/12/2025 : à supprimer à partir du 01/01/2027 pour 12 mois, du 01/07/2026 pour 6 mois
        self.assertEqual(CV.echeance(self.c0.periode, 12), datetime.date(2027, 1, 1))
        self.assertEqual(self.ids(mois=12, aujourdhui=datetime.date(2026, 12, 31)), [])
        self.assertEqual(self.ids(mois=12, aujourdhui=datetime.date(2027, 1, 1)), [self.preuve.pk])
        self.assertEqual(self.ids(mois=24), [])
        ligne = CV.a_supprimer(mois=6, aujourdhui=AUJOURDHUI)[0]
        self.assertEqual((ligne["echeance"], ligne["jours"]), (datetime.date(2026, 7, 1), 135))
        self.assertEqual((ligne["kpi"], ligne["organisation"], ligne["campagne"]), (self.eff, self.e1, self.c0))

    def test_campagne_pas_cloturee_ne_propose_rien(self):
        self.sensible()
        for statut in (Campagne.Statut.OUVERTE, Campagne.Statut.REVUE, Campagne.Statut.PREPARATION):
            Campagne.objects.filter(pk=self.c0.pk).update(statut=statut)
            self.assertEqual(self.ids(mois=1), [], statut)
        Campagne.objects.filter(pk=self.c0.pk).update(statut=Campagne.Statut.CLOTUREE)
        self.assertEqual(self.ids(mois=1), [self.preuve.pk])

    def test_periode_en_cours_jamais_proposee(self):
        self.sensible()
        r = Reponse.objects.get(periode=self.c.periode, kpi=self.eff, organisation=self.e1)
        self.deposer(r, "courante.pdf")
        Campagne.objects.filter(pk=self.c.pk).update(statut=Campagne.Statut.CLOTUREE)  # clôturée, mais sa période (2026) n'est pas finie
        self.assertEqual(self.ids(mois=1, aujourdhui=datetime.date(2026, 11, 13)), [self.preuve.pk])


class SuppressionTests(ConservationBase):
    def setUp(self):
        super().setUp()
        self.sensible()
        self.duree(1)
        self.chemin = Path(self.preuve.fichier.path)
        self.client.force_login(self.admin)

    def test_suppression_reelle_fichier_compris_et_journal(self):
        self.assertTrue(self.chemin.is_file())
        avant = (self.reponse.statut, self.reponse.valeur)
        with self.captureOnCommitCallbacks(execute=True):
            rep = self.client.post(reverse("collecte:admin_preuves"), {"preuves": [self.preuve.pk]})
        self.assertEqual(rep.status_code, 302)
        self.assertFalse(Preuve.objects.filter(pk=self.preuve.pk).exists())
        self.assertFalse(self.chemin.exists())  # le fichier est détruit, pas mis en corbeille
        self.reponse.refresh_from_db()
        self.assertEqual((self.reponse.statut, self.reponse.valeur), avant)  # la valeur d'une campagne clôturée n'est pas touchée
        e = Journal.objects.get(action="purge_preuve")
        self.assertEqual((e.utilisateur, e.objet, e.objet_id, e.champ, e.avant), (self.admin, "Reponse", str(self.reponse.pk), "preuve", "facture-dupont.pdf"))
        self.assertIn("1 mois", e.apres)
        for texte in (self.contrib.email, self.contrib.first_name, self.contrib.username):  # pas la personne qui l'avait déposée
            self.assertNotIn(texte, e.apres + e.avant)

    def test_fichier_efface_seulement_apres_l_enregistrement(self):
        CV.supprimer(self.admin, [self.preuve.pk])  # transaction du test : le commit n'a pas eu lieu
        self.assertTrue(self.chemin.is_file())

    def test_groupe_et_une_par_une(self):
        autre = self.deposer(self.reponse, "bilan.pdf")
        pas_due = self.deposer(Reponse.objects.get(periode=self.c.periode, kpi=self.eff, organisation=self.e1), "courante.pdf")
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(CV.supprimer(self.admin, [self.preuve.pk, autre.pk, autre.pk, pas_due.pk, 999999]), (2, 2))
        self.assertEqual(list(Preuve.objects.values_list("pk", flat=True)), [pas_due.pk])  # ce qui n'est pas dû reste
        self.assertEqual(Journal.objects.filter(action="purge_preuve").count(), 2)

    def test_preuve_plus_due_au_moment_du_clic_est_ignoree(self):
        Campagne.objects.filter(pk=self.c0.pk).update(statut=Campagne.Statut.REVUE)  # campagne rouverte entre la liste et le clic
        self.assertEqual(CV.supprimer(self.admin, [self.preuve.pk]), (0, 1))
        self.assertTrue(Preuve.objects.filter(pk=self.preuve.pk).exists() and self.chemin.is_file())
        self.duree(None)
        Campagne.objects.filter(pk=self.c0.pk).update(statut=Campagne.Statut.CLOTUREE)
        self.assertEqual(CV.supprimer(self.admin, [self.preuve.pk]), (0, 1))  # sans durée : rien ne part

    def test_identifiants_pieges_ignores(self):
        rep = self.client.post(reverse("collecte:admin_preuves"), {"preuves": ["abc", "", "-1", "1e3", "99999999999999999999"]})
        self.assertEqual(rep.status_code, 302)
        self.assertTrue(Preuve.objects.filter(pk=self.preuve.pk).exists())

    def test_message_et_journal_lisible(self):
        with self.captureOnCommitCallbacks(execute=True):
            rep = self.client.post(reverse("collecte:admin_preuves"), {"preuves": [self.preuve.pk]}, follow=True)
        self.assertContains(rep, "1 preuve supprimée")
        j = self.client.get(reverse("collecte:admin_journal") + "?famille=preuve")
        self.assertContains(j, "a supprimé une preuve (durée de conservation)")
        self.assertContains(j, "facture-dupont.pdf")


class PageTests(ConservationBase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)
        self.url = reverse("collecte:admin_preuves")

    def test_sans_duree_page_vide_qui_mene_au_reglage(self):
        rep = self.client.get(self.url)
        self.assertContains(rep, "Aucune durée de conservation réglée")
        self.assertContains(rep, "page-vide")
        self.assertContains(rep, reverse("parametres:hebergement") + "#reglage-conservation")

    def test_rien_a_supprimer_page_vide(self):
        self.duree(1)
        rep = self.client.get(self.url)  # KPI pas sensible
        self.assertContains(rep, "Rien à supprimer")
        self.assertContains(rep, "page-vide")
        self.assertNotContains(rep, "table-preuves")

    def test_liste_colonnes_filtres_et_confirmation(self):
        self.sensible()
        self.duree(1)
        rep = self.client.get(self.url)
        for texte in ("Effectif", "EFF", "E1", "facture-dupont.pdf", "Déposée le", "À supprimer depuis", "01/02/2026", "barre-filtres", "data-envoyer"):
            self.assertContains(rep, texte)
        self.assertContains(rep, "ne va pas dans la corbeille")  # la confirmation dit ce qui sera supprimé
        self.assertContains(rep, "sauvegardes déjà faites")
        self.assertContains(rep, "facture-dupont.pdf</a>")
        self.assertContains(rep, f'name="preuves" value="{self.preuve.pk}"')
        # filtres côté serveur : une autre organisation ne montre rien, avec « Effacer les filtres »
        vide = self.client.get(self.url, {"org": self.e2.pk})
        self.assertNotContains(vide, "facture-dupont.pdf</a>")
        self.assertContains(vide, "Aucune preuve ne correspond")
        self.assertContains(self.client.get(self.url, {"q": "dupont"}), "facture-dupont.pdf</a>")
        self.assertContains(self.client.get(self.url, {"kpi": "EFF", "campagne": self.c0.pk}), "facture-dupont.pdf</a>")
        self.assertNotContains(self.client.get(self.url, {"q": "zzz"}), "facture-dupont.pdf</a>")

    def test_rappel_a_traiter_de_l_accueil_de_l_administration(self):
        accueil = reverse("collecte:admin_accueil")
        self.assertNotContains(self.client.get(accueil), "preuve à supprimer")
        self.sensible()
        self.duree(1)
        rep = self.client.get(accueil)
        self.assertContains(rep, "1 preuve à supprimer")
        self.assertContains(rep, self.url)
        self.client.post(self.url, {"preuves": [self.preuve.pk]})
        self.assertNotContains(self.client.get(accueil), "1 preuve à supprimer")

    def test_lien_depuis_l_historique_de_l_administrateur_seulement(self):
        self.assertContains(self.client.get(reverse("collecte:admin_journal")), self.url)
        self.client.force_login(self.auditeur)
        self.assertNotContains(self.client.get(reverse("collecte:historique")), self.url)

    def test_fiche_kpi_dit_ce_que_la_mention_declenche(self):
        rep = self.client.get(reverse("collecte:referentiel_kpi", args=["EFF"]))
        self.assertContains(rep, "proposées à la suppression")

    def test_anglais_et_espagnol(self):
        self.sensible()
        self.duree(1)
        for langue, texte in (("en", "Evidence to delete"), ("es", "Justificantes por eliminar")):
            self.admin.langue = langue
            self.admin.save()
            self.assertContains(self.client.get(self.url), texte)


class DroitsTests(ConservationBase):
    def setUp(self):
        super().setUp()
        self.sensible()
        self.duree(1)
        self.url = reverse("collecte:admin_preuves")

    def test_administrateur_seulement(self):
        for u in (self.contrib, self.valide, self.lecteur, self.auditeur):
            self.client.force_login(u)
            self.assertEqual(self.client.get(self.url).status_code, 403, u.role)
            rep = self.client.post(self.url, {"preuves": [self.preuve.pk]})
            self.assertEqual(rep.status_code, 403, u.role)
        self.assertTrue(Preuve.objects.filter(pk=self.preuve.pk).exists())
        self.assertFalse(Journal.objects.filter(action="purge_preuve").exists())

    def test_sans_connexion(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.assertEqual(self.client.post(self.url, {"preuves": [self.preuve.pk]}).status_code, 302)
        self.assertTrue(Preuve.objects.filter(pk=self.preuve.pk).exists())

    def test_la_route_est_dans_le_balayage_des_acces(self):
        from collecte.test_droits_balayage import routes

        self.assertIn(("collecte", "admin_preuves", "administration/preuves/"), routes())


class ReglageTests(ConservationBase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)
        self.url = reverse("parametres:hebergement")

    def enregistrer(self, valeur):
        return self.client.post(self.url, {"action": "reglage_conservation", "preuves_sensibles_mois": valeur}, follow=True)

    def test_defaut_vide_puis_enregistre_et_journal(self):
        self.assertIsNone(Instance.courante().preuves_sensibles_mois)
        self.assertContains(self.client.get(self.url), "Mois avant de proposer la suppression")
        self.assertContains(self.enregistrer("24"), "24 mois après la fin de la période")
        self.assertEqual(Instance.courante().preuves_sensibles_mois, 24)
        e = Journal.objects.get(action="reglage_conservation")
        self.assertEqual((e.champ, e.avant, e.apres, e.utilisateur), ("preuves_sensibles_mois", "", "24", self.admin))
        self.enregistrer("24")
        self.assertEqual(Journal.objects.filter(action="reglage_conservation").count(), 1)  # rien au journal sans changement
        self.assertContains(self.enregistrer(""), "Aucune durée")
        self.assertIsNone(Instance.courante().preuves_sensibles_mois)

    def test_valeurs_refusees(self):
        self.enregistrer("24")
        for v in ("0", "241", "-3", "abc", "1.5"):
            rep = self.enregistrer(v)
            self.assertContains(rep, "entre 1 et 240", msg_prefix=v)
            self.assertEqual(Instance.courante().preuves_sensibles_mois, 24, v)

    def test_lecteur_et_auditeur_ne_reglent_rien(self):
        for u in (self.lecteur, self.auditeur, self.contrib):
            self.client.force_login(u)
            self.assertEqual(self.client.post(self.url, {"action": "reglage_conservation", "preuves_sensibles_mois": "6"}).status_code, 403)
        self.assertIsNone(Instance.courante().preuves_sensibles_mois)

    def test_page_donnees_et_confidentialite_dit_la_duree(self):
        self.assertNotContains(self.client.get(reverse("collecte:confidentialite")), "propose de supprimer le fichier")
        self.duree(18)
        self.assertContains(self.client.get(reverse("collecte:confidentialite")), "18 mois après la fin de la période")
