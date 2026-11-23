"""Seconde recette (B9) : un appel répété ne doit rien refaire en silence.
- ``send_reminder`` envoyé deux fois à la même personne en quelques secondes : un seul e-mail ; le second appel dit que la
  personne vient d'être relancée.
- ``validate_value`` sur une valeur déjà validée : la réponse dit que rien n'a changé (plus « saved: true »)."""
from django.core import mail
from django.test import override_settings

from collecte import saisie as S
from collecte.models import Journal, Relance, Reponse

from .aides_tests import BaseMCP


@override_settings(EMAIL_HOST="smtp.exemple.test", EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class RelanceRepeteeTests(BaseMCP):
    def envoyer(self):
        return self.outil("admin", "send_reminder", {"send": True, "person_ids": [self.contrib.pk]})

    def test_deux_envois_rapproches_un_seul_e_mail(self):
        _, res, d = self.envoyer()
        self.assertFalse(res["isError"], d)
        self.assertEqual([p["id"] for p in d["delivered"]], [self.contrib.pk])
        _, res, d = self.envoyer()
        self.assertFalse(res["isError"], d)
        self.assertEqual(d["delivered"], [])
        self.assertEqual([x["person"]["id"] for x in d["recently_reminded"]], [self.contrib.pk])
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(Relance.objects.filter(destinataire=self.contrib).count(), 1)

    def test_apres_l_intervalle_l_envoi_repart(self):
        self.envoyer()
        from datetime import timedelta

        Relance.objects.update(date=Relance.objects.get().date - timedelta(minutes=6))
        _, res, d = self.envoyer()
        self.assertEqual([p["id"] for p in d["delivered"]], [self.contrib.pk])
        self.assertEqual(len(mail.outbox), 2)


class ValiderDejaValideeTests(BaseMCP):
    def test_valeur_deja_validee_rien_n_a_change(self):
        S.valider(self.contrib, self.c, self.eff, self.e1)
        r = Reponse.objects.get(periode=self.c.periode, kpi=self.eff, organisation=self.e1)
        avant = (r.statut, r.date_validation, Journal.objects.count())
        _, res, d = self.outil("contributeur", "validate_value", self.case())
        self.assertFalse(res["isError"], d)
        self.assertFalse(d["saved"])
        self.assertFalse(d["changed"])
        self.assertIn("déjà validée", d["message"])
        r.refresh_from_db()
        self.assertEqual((r.statut, r.date_validation), avant[:2])

    def test_hors_perimetre_toujours_refuse(self):
        S.valider(self.admin, self.c, self.eff, self.e2)
        _, res, d = self.outil("contributeur", "validate_value", self.case(org=self.e2))
        self.assertEqual(d["error"]["type"], "permission_denied")
