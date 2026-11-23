"""Compte qui passe en lecture seule : ses attributions sont retirées (règle du projet, « N4 »).

Un validateur (ou un contributeur) qui devient lecteur ou auditeur gardait ses attributions : la page Attributions le
nommait encore validateur de son pays, alors qu'il ne peut plus rien valider. Désormais, à l'enregistrement de la fiche
du compte, ses attributions (contributeur et validateur) sont retirées dans la même transaction, avec une ligne
d'historique qui dit combien et lesquelles ; la fiche demande d'abord une confirmation qui annonce leur nombre, dit que
les cases apparaîtront « Sans SPOC » ou sans validateur et que revenir au rôle d'avant ne les rétablit pas. Rien n'est
retiré en silence à la mise à jour : les comptes en lecture seule qui ont encore des attributions sont signalés dans
« À traiter », avec une page pour les retirer."""
from django.urls import reverse

from parametres import langues as L
from referentiel.models import Attribution, Utilisateur

from . import relances as RL
from .administration import CompteForm
from .aides_tests.saisie import Base
from .models import Journal

FETCH = {"HTTP_X_REQUESTED_WITH": "fetch"}


class RetraitAuPassageEnLectureSeuleTests(Base):
    def setUp(self):
        super().setUp()
        self.valid.first_name, self.valid.last_name = "Val", "Idateur"  # save : le registre des comptes suit
        self.valid.save()
        # le validateur est aussi SPOC d'une case : deux attributions, une de chaque rôle
        Attribution.objects.create(kpi=self.taux, organisation=self.e2, utilisateur=self.valid)
        self.client.force_login(self.admin)

    def donnees(self, role, **autres):
        return {"first_name": "Val", "last_name": "Idateur", "email": "valid@exemple.test", "role": role,
                "is_active": "on", "action": "enregistrer", **autres}

    def test_confirmation_demandee_avec_le_nombre(self):
        form = CompteForm(self.donnees(Utilisateur.Role.LECTEUR), instance=self.valid, moi=self.admin)
        self.assertFalse(form.is_valid())
        message = " ".join(form.non_field_errors())
        self.assertIn("2 attributions", message)
        self.assertIn("1 comme contributeur, 1 comme validateur", message)
        self.assertIn("Sans SPOC", message)
        self.assertIn("ne les rétablit pas", message)
        self.assertEqual(form.retrait_a_confirmer, 2)
        form = CompteForm(self.donnees(Utilisateur.Role.LECTEUR, confirmer_retrait="on"), instance=self.valid, moi=self.admin)
        self.assertTrue(form.is_valid(), form.errors)

    def test_sans_confirmation_rien_ne_change(self):
        rep = self.client.post(reverse("collecte:admin_compte", args=[self.valid.pk]), self.donnees(Utilisateur.Role.LECTEUR), **FETCH)
        self.assertFalse(rep.json()["ok"])
        self.assertIn('name="confirmer_retrait"', rep.json()["html"])
        self.assertEqual(Utilisateur.objects.get(pk=self.valid.pk).role, Utilisateur.Role.VALIDATEUR)
        self.assertEqual(Attribution.objects.filter(utilisateur=self.valid).count(), 2)

    def test_case_de_confirmation_ne_promet_pas_l_enregistrement(self):
        """La case confirme le retrait ; l'enregistrement est un autre clic (« Enregistrer les modifications »)."""
        rep = self.client.post(reverse("collecte:admin_compte", args=[self.valid.pk]), self.donnees(Utilisateur.Role.LECTEUR), **FETCH)
        html = rep.json()["html"]
        self.assertIn("Je confirme : retirer les 2 attributions", html)
        self.assertNotIn("attributions et enregistrer", html)

    def test_retrait_journalise_et_pas_retabli(self):
        url = reverse("collecte:admin_compte", args=[self.valid.pk])
        rep = self.client.post(url, self.donnees(Utilisateur.Role.LECTEUR, confirmer_retrait="on"), **FETCH)
        self.assertTrue(rep.json()["ok"], rep.json()["html"][:2000])
        self.assertIn("2 attributions retirées", rep.json()["html"])
        self.assertEqual(Utilisateur.objects.get(pk=self.valid.pk).role, Utilisateur.Role.LECTEUR)
        self.assertFalse(Attribution.objects.filter(utilisateur=self.valid).exists())
        lignes = Journal.objects.filter(action="retrait_attributions_role", objet_id=str(self.valid.pk))
        self.assertEqual(lignes.count(), 1)
        j = lignes.get()
        self.assertEqual((j.utilisateur, j.champ), (self.admin, "attributions"))
        self.assertEqual(j.avant, "contributeur (1) : [TX] E2 ; validateur (1) : [EFF] Pays")
        self.assertFalse(Journal.objects.filter(action="reglage_compte", champ="confirmer_retrait").exists())
        self.assertTrue(Journal.objects.filter(action="reglage_compte", champ="role", objet_id=str(self.valid.pk)).exists())
        # retour au rôle d'avant : les attributions ne reviennent pas
        rep = self.client.post(url, self.donnees(Utilisateur.Role.VALIDATEUR), **FETCH)
        self.assertTrue(rep.json()["ok"])
        self.assertFalse(Attribution.objects.filter(utilisateur=self.valid).exists())
        self.assertEqual(lignes.count(), 1)

    def test_ligne_d_historique_lisible_dans_les_langues(self):
        from .administration import libeller_journal

        self.client.post(reverse("collecte:admin_compte", args=[self.valid.pk]),
                         self.donnees(Utilisateur.Role.AUDITEUR, confirmer_retrait="on"), **FETCH)
        j = Journal.objects.get(action="retrait_attributions_role")
        for langue, action, avant in (
                ("en", "removed the assignments (read-only role)", "contributor (1): [TX] E2; validator (1): [EFF] Pays"),
                ("de", "Zuweisungen entfernt (schreibgeschützte Rolle)", "Mitwirkender (1): [TX] E2; Validator (1): [EFF] Pays")):
            with L.activer_interface(langue):
                e = Journal.objects.get(pk=j.pk)
                libeller_journal([e])
                self.assertEqual((e.libelle_action, e.avant_lisible), (action, avant))

    def test_contributeur_devenu_auditeur(self):
        self.contrib.first_name, self.contrib.last_name = "Con", "Tributeur"
        self.contrib.save()
        donnees = {**self.donnees(Utilisateur.Role.AUDITEUR, confirmer_retrait="on"), "first_name": "Con", "last_name": "Tributeur",
                   "email": "contrib@exemple.test"}
        avant = RL.restes_sans_spoc([self.c])
        self.client.post(reverse("collecte:admin_compte", args=[self.contrib.pk]), donnees, **FETCH)
        self.assertFalse(Attribution.objects.filter(utilisateur=self.contrib).exists())
        self.assertGreater(RL.restes_sans_spoc([self.c]), avant)  # ses cases : à attribuer, comptées « Sans SPOC »
        self.assertNotIn(self.contrib.pk, {af.personne.pk for af in RL.a_faire([self.c])})

    def test_autres_changements_de_role_sans_effet(self):
        form = CompteForm(self.donnees(Utilisateur.Role.CONTRIBUTEUR), instance=self.valid, moi=self.admin)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.retrait_a_confirmer, 0)
        self.client.post(reverse("collecte:admin_compte", args=[self.valid.pk]), self.donnees(Utilisateur.Role.CONTRIBUTEUR), **FETCH)
        self.assertEqual(Attribution.objects.filter(utilisateur=self.valid).count(), 2)
        self.assertFalse(Journal.objects.filter(action="retrait_attributions_role").exists())

    def test_sans_attribution_pas_de_confirmation(self):
        Attribution.objects.filter(utilisateur=self.valid).delete()
        form = CompteForm(self.donnees(Utilisateur.Role.LECTEUR), instance=self.valid, moi=self.admin)
        self.assertTrue(form.is_valid(), form.errors)
        self.client.post(reverse("collecte:admin_compte", args=[self.valid.pk]), self.donnees(Utilisateur.Role.LECTEUR), **FETCH)
        self.assertFalse(Journal.objects.filter(action="retrait_attributions_role").exists())

    def test_desactivation_inchangee(self):
        """Comportement existant gardé : un compte désactivé garde ses attributions (« Remplacer une personne… » les
        transfère) ; elles ne comptent plus (cases « Sans SPOC »)."""
        self.client.post(reverse("collecte:admin_compte", args=[self.valid.pk]),
                         {k: v for k, v in self.donnees(Utilisateur.Role.VALIDATEUR).items() if k != "is_active"}, **FETCH)
        self.assertFalse(Utilisateur.objects.get(pk=self.valid.pk).is_active)
        self.assertEqual(Attribution.objects.filter(utilisateur=self.valid).count(), 2)


class LectureSeuleAvecAttributionsTests(Base):
    """Installations existantes : un lecteur ou un auditeur peut déjà avoir des attributions (avant la mise à jour). La
    mise à jour ne retire rien ; « À traiter » les signale, avec une page pour les retirer."""

    def setUp(self):
        super().setUp()
        Utilisateur.objects.filter(pk=self.valid.pk).update(role=Utilisateur.Role.LECTEUR)  # comme avant la décision
        self.url = reverse("collecte:admin_attributions_lecture_seule")

    def test_signale_dans_a_traiter(self):
        self.client.force_login(self.admin)
        rep = self.client.get(reverse("collecte:admin_accueil"))
        self.assertContains(rep, "1 compte en lecture seule a encore des attributions")
        self.assertContains(rep, f'href="{self.url}"')
        Attribution.objects.filter(utilisateur=self.valid).delete()
        rep = self.client.get(reverse("collecte:admin_accueil"))
        self.assertNotContains(rep, "en lecture seule a encore des attributions")

    def test_page_et_retrait(self):
        self.client.force_login(self.admin)
        rep = self.client.get(self.url)
        self.assertContains(rep, "valid@exemple.test")
        self.assertEqual(Attribution.objects.filter(utilisateur=self.valid).count(), 1)  # rien retiré à l'ouverture
        rep = self.client.post(self.url, {"compte": "tous"})
        self.assertEqual(rep.status_code, 302)
        self.assertFalse(Attribution.objects.filter(utilisateur=self.valid).exists())
        self.assertEqual(Journal.objects.get(action="retrait_attributions_role").avant, "contributeur (0) : — ; validateur (1) : [EFF] Pays")
        self.assertEqual(Attribution.objects.filter(utilisateur=self.contrib).count(), 2)  # les autres comptes : intacts

    def test_retrait_d_un_seul_compte(self):
        Utilisateur.objects.filter(pk=self.contrib.pk).update(role=Utilisateur.Role.AUDITEUR)
        self.client.force_login(self.admin)
        self.client.post(self.url, {"compte": str(self.contrib.pk)})
        self.assertFalse(Attribution.objects.filter(utilisateur=self.contrib).exists())
        self.assertTrue(Attribution.objects.filter(utilisateur=self.valid).exists())

    def test_reserve_a_l_administrateur(self):
        for u in (self.contrib, self.autre):
            self.client.force_login(u)
            self.assertEqual(self.client.get(self.url).status_code, 403)
            self.assertEqual(self.client.post(self.url, {"compte": "tous"}).status_code, 403)
        self.client.force_login(self.valid)  # lecteur
        self.assertEqual(self.client.post(self.url, {"compte": "tous"}).status_code, 403)
        self.assertTrue(Attribution.objects.filter(utilisateur=self.valid).exists())

    def test_remplacer_une_personne_propose_le_lecteur(self):
        """Les attributions de validateur ne se donnent que par « Remplacer une personne… » : un lecteur qui en a encore
        y est proposé, pour les donner à quelqu'un avant de les retirer."""
        nouveau = Utilisateur.objects.create(username="vera", email="vera@exemple.test", role=Utilisateur.Role.VALIDATEUR)
        self.client.force_login(self.admin)
        url = reverse("collecte:admin_remplacer")
        self.assertContains(self.client.get(url), f'<option value="{self.valid.pk}">')
        self.client.post(url, {"de": str(self.valid.pk), "par": str(nouveau.pk)})
        self.assertEqual(Attribution.objects.filter(utilisateur=nouveau, role=Attribution.Role.VALIDATEUR).count(), 1)
        self.assertFalse(Attribution.objects.filter(utilisateur=self.valid).exists())
