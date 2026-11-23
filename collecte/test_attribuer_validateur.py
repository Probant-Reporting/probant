"""Attribution de validateur donnée ou retirée par Administration › Attributions (règle du projet).

Une attribution de validateur porte sur un KPI et une organisation, et vaut aussi pour les organisations en dessous
(``saisie.cellules``, ``saisie.role_sur``). Seul l'administrateur la donne ; seule une personne active dont le rôle est
validateur ou administrateur la reçoit ; chaque changement écrit une ligne d'historique."""
import json

from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse

from referentiel.models import Attribution, Utilisateur

from . import saisie as S
from .aides_tests.saisie import Base
from .models import Journal

V = Attribution.Role.VALIDATEUR


class AttribuerValidateurTests(Base):
    def setUp(self):
        super().setUp()
        self.valid2 = Utilisateur.objects.create(username="valid2", email="valid2@exemple.test", role=Utilisateur.Role.VALIDATEUR)

    def test_donne_et_retire_avec_historique(self):
        self.assertEqual(S.attribuer(self.admin, [(self.eff, self.p), (self.taux, self.p)], self.valid2, role=V), 2)
        self.assertEqual(set(Attribution.objects.filter(utilisateur=self.valid2, role=V).values_list("kpi_id", "organisation_id")),
                         {("EFF", self.p.pk), ("TX", self.p.pk)})
        # la personne valide maintenant ces KPI dans les entités du pays (héritage vers le bas)
        self.assertEqual(S.role_sur(self.valid2, self.taux, self.e2), "validateur")
        lignes = Journal.objects.filter(action="attribution_validateur")
        self.assertEqual(lignes.count(), 2)
        self.assertEqual(lignes.first().champ, "validateur")
        self.assertIn("valid2@exemple.test", lignes.first().apres)
        # deuxième fois : rien de nouveau, rien au journal
        self.assertEqual(S.attribuer(self.admin, [(self.eff, self.p)], self.valid2, role=V), 0)
        self.assertEqual(Journal.objects.filter(action="attribution_validateur").count(), 2)
        self.assertEqual(S.attribuer(self.admin, [(self.eff, self.p)], self.valid2, retirer=True, role=V), 1)
        self.assertEqual(Journal.objects.filter(action="retrait_validateur").count(), 1)
        self.assertIsNone(S.role_sur(self.valid2, self.eff, self.e1))

    def test_retirer_un_validateur_garde_le_contributeur(self):
        """Les deux rôles sont distincts : retirer le validateur ne touche pas l'attribution de contributeur, et l'inverse."""
        Attribution.objects.create(kpi=self.eff, organisation=self.e1, utilisateur=self.admin)
        S.attribuer(self.admin, [(self.eff, self.e1)], self.admin, role=V)
        S.attribuer(self.admin, [(self.eff, self.e1)], self.admin, retirer=True, role=V)
        self.assertTrue(Attribution.objects.filter(utilisateur=self.admin, role=Attribution.Role.CONTRIBUTEUR).exists())
        S.attribuer(self.admin, [(self.eff, self.p)], self.valid, retirer=True)  # contributeur : rien à retirer
        self.assertTrue(Attribution.objects.filter(utilisateur=self.valid, role=V).exists())

    def test_seul_l_administrateur_donne(self):
        with self.assertRaises(PermissionDenied):
            S.attribuer(self.valid, [(self.eff, self.p)], self.valid2, role=V)

    def test_un_administrateur_peut_recevoir(self):
        self.assertEqual(S.attribuer(self.admin, [(self.eff, self.p)], self.admin, role=V), 1)

    def test_refus_contributeur_lecteur(self):
        """Seuls un validateur ou un administrateur reçoivent une attribution de validateur."""
        for u in (self.contrib, Utilisateur.objects.create(username="lec", email="lec@exemple.test", role=Utilisateur.Role.LECTEUR),
                  Utilisateur.objects.create(username="aud", email="aud@exemple.test", role=Utilisateur.Role.AUDITEUR)):
            with self.assertRaises(ValidationError, msg=u.role):
                S.attribuer(self.admin, [(self.eff, self.p)], u, role=V)
        self.assertFalse(Attribution.objects.filter(role=V).exclude(utilisateur=self.valid).exists())

    def test_refus_organisation_sous_le_niveau_du_kpi(self):
        """Une attribution sous le niveau de saisie du KPI ne couvrirait aucune case : refusée."""
        from referentiel.models import Niveau, Organisation

        site = Organisation.objects.create(nom="S1", niveau_id=Niveau.SITE, parent=self.e1)
        with self.assertRaises(ValidationError):
            S.attribuer(self.admin, [(self.eff, site)], self.valid2, role=V)

    def test_refus_kpi_calcule(self):
        with self.assertRaises(ValidationError):
            S.attribuer(self.admin, [(self.calc, self.p)], self.valid2, role=V)

    def test_compte_relu_au_moment_d_ecrire(self):
        """Le rôle est relu en base (sous verrou) : un objet en mémoire périmé ne suffit pas."""
        perime = Utilisateur.objects.get(pk=self.valid2.pk)
        Utilisateur.objects.filter(pk=self.valid2.pk).update(role=Utilisateur.Role.LECTEUR)
        with self.assertRaises(ValidationError):
            S.attribuer(self.admin, [(self.eff, self.p)], perime, role=V)


class AttribuerValidateurVueTests(Base):
    def poster(self, cles, utilisateur, role="validateur", retirer=False):
        return self.client.post(reverse("collecte:attribuer"), json.dumps(
            {"cles": cles, "utilisateur": utilisateur.pk, "role": role, "retirer": retirer, "format": "cellule"}),
            content_type="application/json")

    def test_administrateur(self):
        self.client.force_login(self.admin)
        rep = self.poster([f"EFF|{self.e1.pk}"], self.valid, role="validateur")
        self.assertEqual(rep.status_code, 200, rep.content)
        self.assertTrue(Attribution.objects.filter(kpi_id="EFF", organisation=self.e1, utilisateur=self.valid, role=V).exists())
        corps = rep.json()
        self.assertIn(f"EFF|{self.e1.pk}", corps["lignes"])
        self.assertIn('data-spocs="%d"' % self.valid.pk, corps["lignes"][f"EFF|{self.e1.pk}"])

    def test_role_inconnu_refuse(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.poster([f"EFF|{self.e1.pk}"], self.valid, role="auditeur").status_code, 400)
        self.assertFalse(Attribution.objects.filter(organisation=self.e1, utilisateur=self.valid).exists())

    def test_contributeur_refuse_comme_validateur(self):
        self.client.force_login(self.admin)
        rep = self.poster([f"EFF|{self.e2.pk}"], self.contrib)
        self.assertEqual(rep.status_code, 400)
        self.assertFalse(Attribution.objects.filter(organisation=self.e2, utilisateur=self.contrib).exists())

    def test_autres_roles_refuses(self):
        lecteur = Utilisateur.objects.create(username="lec", email="lec@exemple.test", role=Utilisateur.Role.LECTEUR)
        for u in (self.contrib, self.valid, lecteur):
            self.client.force_login(u)
            self.assertEqual(self.poster([f"EFF|{self.e2.pk}"], self.valid).status_code, 403, u.role)
        self.assertFalse(Attribution.objects.filter(organisation=self.e2, role=V).exists())
