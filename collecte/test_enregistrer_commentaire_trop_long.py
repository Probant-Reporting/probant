"""Commentaire d'une saisie (``saisie.enregistrer``) : au-delà de ``COMMENTAIRE_MAX`` caractères, l'enregistrement est
refusé avec un message clair (rien n'est écrit) ; un commentaire long déjà en base, renvoyé tel quel, reste accepté."""
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils.html import escape

from parametres.libelles import libelle

from . import saisie as S
from .models import Reponse
from .aides_tests.saisie import Base
from .templatetags.collecte import nombre


class CommentaireTropLongTests(Base):
    def case(self):
        return Reponse.objects.filter(periode=self.c.periode, kpi=self.eff, organisation=self.e1).first()

    def test_refus_au_dela_de_la_limite(self):
        self.enregistrer("40", com="x" * S.COMMENTAIRE_MAX)  # pile la limite : accepté
        self.assertEqual(len(self.case().commentaire), S.COMMENTAIRE_MAX)
        trop = "y" * (S.COMMENTAIRE_MAX + 1)
        with self.assertRaises(ValidationError) as cm:
            self.enregistrer("41", com=trop)
        self.assertEqual(cm.exception.messages, [libelle("saisie.msg.commentaire_trop_long", max=nombre(S.COMMENTAIRE_MAX, 0),
                                                         n=nombre(S.COMMENTAIRE_MAX + 1, 0))])
        self.assertEqual((self.case().valeur, self.case().commentaire), (40, "x" * S.COMMENTAIRE_MAX))  # rien d'écrit

    def test_commentaire_long_deja_en_base_garde(self):
        long = "z" * (S.COMMENTAIRE_MAX + 10)  # posé avant la limite (import ancien)
        self.enregistrer("40")
        Reponse.objects.filter(pk=self.case().pk).update(commentaire=long)
        self.enregistrer("42", com=long)  # renvoyé tel quel par le panneau : la valeur change, pas de refus
        self.assertEqual((self.case().valeur, self.case().commentaire), (42, long))

    def test_refus_affiche_par_le_panneau(self):
        self.client.force_login(self.contrib)
        url = reverse("collecte:cellule", args=[self.c.pk, "EFF", self.e1.pk])
        rep = self.client.post(url, {"action": "enregistrer", "valeur": "40", "commentaire": "y" * (S.COMMENTAIRE_MAX + 1)},
                               HTTP_X_REQUESTED_WITH="fetch")
        self.assertEqual(rep.status_code, 200)
        motif = libelle("saisie.msg.commentaire_trop_long", max=nombre(S.COMMENTAIRE_MAX, 0), n=nombre(S.COMMENTAIRE_MAX + 1, 0))
        self.assertIn(escape(motif), rep.json()["html"])
        self.assertIsNone(self.case())
