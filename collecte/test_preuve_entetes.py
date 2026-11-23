"""Preuve servie : jamais gardée en cache (Cache-Control: private, no-store) et inerte (reponse_inerte : type forcé,
nosniff, CSP sans aucun chargement), comme le logo. Image : CSP « sandbox » en plus. PDF : sans « sandbox », que certains
navigateurs refusent pour un PDF (affichage vide ou téléchargement forcé) : une preuve doit s'ouvrir partout."""
from django.urls import reverse

from .models import Preuve
from .aides_tests.saisie import Base, fichier


class EntetesPreuveTests(Base):
    FETCH = {"HTTP_X_REQUESTED_WITH": "fetch"}

    def setUp(self):
        super().setUp()
        self.client.force_login(self.contrib)
        self.url = reverse("collecte:cellule", args=[self.c.pk, "EFF", self.e1.id])

    def test_entetes(self):
        for nom, type_ in (("preuve.pdf", "application/pdf"), ("photo.png", "image/png")):
            contenu = b"%PDF-1.4 test" if nom.endswith(".pdf") else b"\x89PNG\r\n\x1a\n" + b"\0" * 32
            self.client.post(self.url, {"action": "preuve", "fichier": fichier(nom, contenu, type_)}, **self.FETCH)
            p = Preuve.objects.latest("pk")
            rep = self.client.get(reverse("collecte:preuve", args=[p.pk]))
            self.assertEqual(rep.status_code, 200)
            self.assertEqual(rep["Content-Type"], type_)
            self.assertEqual(rep["Cache-Control"], "private, no-store")
            self.assertIn("default-src 'none'", rep["Content-Security-Policy"])
            if type_ == "application/pdf":
                self.assertNotIn("sandbox", rep["Content-Security-Policy"])
            else:
                self.assertIn("sandbox", rep["Content-Security-Policy"])
            self.assertEqual(rep["X-Content-Type-Options"], "nosniff")
            self.assertTrue(rep["Content-Disposition"].startswith("inline"))
