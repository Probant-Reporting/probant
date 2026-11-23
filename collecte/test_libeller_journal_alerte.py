"""Historique : une ligne d'alerte (``objet`` « Alerte », champ « statut ») s'affiche dans la langue de qui lit — « Alert 82 »,
« Justified → Accepted » — et non avec le mot français et les codes bruts des états ; le journal enregistré ne change pas."""
from django.urls import reverse

from parametres import langues as L
from parametres import libelles as LB
from parametres.libelles import libelle

from . import administration as A
from . import coherence as CO
from .aides_tests.echanges import Base
from .models import Alerte, Journal

LANGUES = ("en", "fr", "es", "de", "it", "nl", "pt")


class LibellerJournalAlerteTests(Base):
    def setUp(self):
        super().setUp()
        self.alerte = Alerte.objects.create(campagne=self.c, kpi=self.eff, organisation=self.e1, controle=Alerte.Controle.ECART_N1,
                                            message="Écart", statut=Alerte.Statut.JUSTIFIEE, justification="Embauches",
                                            justifie_par=self.contrib)
        CO.traiter(self.admin, self.alerte, "accepter", "Vu le contrat")
        self.entree = Journal.objects.get(objet="Alerte", objet_id=str(self.alerte.pk))

    def test_enregistrement_inchange(self):
        self.assertEqual((self.entree.avant, self.entree.apres), ("justifiee", "acceptee : Vu le contrat"))

    def test_sept_langues(self):
        for lg in LANGUES:
            with self.subTest(langue=lg), L.activer(lg):
                e = Journal.objects.get(pk=self.entree.pk)
                A.libeller_journal([e])
                self.assertEqual(e.libelle_objet, libelle("admin.journal.objet.alerte", lg, id=self.alerte.pk))
                self.assertEqual(e.avant_lisible, LB.choix_valeur(Alerte, "statut", "justifiee", lg))
                self.assertEqual(e.apres_lisible, LB.choix_valeur(Alerte, "statut", "acceptee", lg) + " · Vu le contrat")
                self.assertNotIn("justifiee", e.avant_lisible)
        with L.activer("en"):
            e = Journal.objects.get(pk=self.entree.pk)
            A.libeller_journal([e])
            self.assertEqual((e.libelle_objet, e.avant_lisible, e.apres_lisible),
                             (f"Alert {self.alerte.pk}", "Justified", "Accepted · Vu le contrat"))

    def test_page_historique_en_anglais(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("langue"), {"langue": "en"})
        t = self.client.get(reverse("collecte:historique") + "?vue=saisies").content.decode()
        if f"Alert {self.alerte.pk}" not in t:  # l'action « accepter » peut être rangée dans l'autre vue
            t = self.client.get(reverse("collecte:historique") + "?vue=admin").content.decode()
        self.assertIn(f"Alert {self.alerte.pk}", t)
        self.assertNotIn(f"Alerte {self.alerte.pk}", t)
        self.assertNotIn("justifiee", t)
        self.assertNotIn("acceptee", t)
