"""Mon compte › Assistants : la page qui montre un jeton en clair n'est gardée par aucun cache (``no-store``) ; après la
création, une redirection (un rechargement ne crée pas un second jeton) ; le jeton n'est montré qu'une fois."""
from django.test import Client
from django.urls import reverse

from . import jetons as JT
from .aides_tests import BaseMCP
from .models import JetonMCP


class CreationEtRechargementTests(BaseMCP):
    def test_redirection_une_seule_fois_et_sans_cache(self):
        c = Client()
        c.force_login(self.lecteur)
        url = reverse("collecte:mon_compte")
        rep = c.post(url, {"action": "jeton_creer", "nom": "Mon assistant", "jours": "7"})
        self.assertEqual(rep.status_code, 302)  # un rechargement de la page qui suit ne renvoie pas le formulaire
        self.assertEqual(JetonMCP.objects.filter(utilisateur=self.lecteur, nom="Mon assistant").count(), 1)
        page = c.get(rep["Location"])
        self.assertIn("no-store", page["Cache-Control"])
        texte = page.content.decode()
        clair = texte.split('id="jeton-nouveau" class="code-copie">')[1].split("<")[0]
        self.assertEqual(JT.empreinte(clair), JetonMCP.objects.get(utilisateur=self.lecteur, nom="Mon assistant").empreinte)
        recharge = c.get(rep["Location"])
        self.assertNotIn(clair, recharge.content.decode())  # montré une seule fois
        self.assertIn("no-store", recharge["Cache-Control"])
        self.assertEqual(JetonMCP.objects.filter(utilisateur=self.lecteur, nom="Mon assistant").count(), 1)
        self.assertFalse(any(clair in str(v) for v in c.session.values()))  # plus rien en session

    def test_jeton_d_une_autre_personne_jamais_montre(self):
        """Le jeton gardé en session n'est montré qu'à la personne qui l'a créé (même session, même compte)."""
        c = Client()
        c.force_login(self.lecteur)
        rep = c.post(reverse("collecte:mon_compte"), {"action": "jeton_creer", "nom": "Le mien", "jours": "7"})
        c.force_login(self.auditeur)  # autre compte dans le même navigateur
        self.assertNotIn('id="jeton-nouveau"', c.get(rep["Location"]).content.decode())
