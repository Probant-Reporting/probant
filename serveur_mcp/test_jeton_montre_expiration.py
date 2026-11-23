"""Jeton créé dans Mon compte (``action_jeton`` puis ``jeton_montre``) : le temps de la redirection, la session ne garde
jamais le jeton en clair (seulement sa moitié chiffrée ; l'autre moitié, la clé, est dans un cookie de 5 minutes du
navigateur), et il n'est plus montré passé 5 minutes, même si la page suivante n'a jamais été ouverte."""
from unittest import mock

from django.test import Client
from django.urls import reverse

from . import vues as V
from .aides_tests import BaseMCP
from .models import JetonMCP


class JetonMontreExpirationTests(BaseMCP):
    def creer(self):
        self.c = Client()
        self.c.force_login(self.lecteur)
        self.rep = self.c.post(reverse("collecte:mon_compte"), {"action": "jeton_creer", "nom": "Mon assistant", "jours": "7"})
        self.assertEqual(self.rep.status_code, 302)
        return JetonMCP.objects.get(utilisateur=self.lecteur, nom="Mon assistant")

    def montre(self):
        return 'id="jeton-nouveau"' in self.c.get(self.rep["Location"]).content.decode()

    def test_jamais_en_clair_dans_la_session(self):
        self.creer()
        brut = self.c.session.load() if hasattr(self.c.session, "load") else {}
        self.assertFalse(any("prb_" in str(v) for v in dict(brut).values()), brut)
        self.assertTrue(self.montre())

    def test_plus_montre_passe_cinq_minutes(self):
        self.creer()
        maintenant = V._maintenant()
        with mock.patch.object(V, "_maintenant", lambda: maintenant + 6 * 60):
            self.assertFalse(self.montre())
        self.assertNotIn(V.SESSION_NOUVEAU, self.c.session)  # effacé
        self.assertFalse(self.montre())

    def test_sans_le_cookie_de_cinq_minutes_rien(self):
        self.creer()
        cookie = self.rep.cookies[V.COOKIE_NOUVEAU]
        self.assertEqual(int(cookie["max-age"]), V.DUREE_NOUVEAU)
        self.assertTrue(cookie["httponly"])
        del self.c.cookies[V.COOKIE_NOUVEAU]  # le navigateur l'a oublié (5 minutes passées)
        self.assertFalse(self.montre())
