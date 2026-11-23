"""Import d'une valeur annuelle cumulée à partir des mois (``imports.analyser`` / ``_comparer``).

L'export « Base de données » se réimporte tel quel (README, « Exports ») : une ligne cumulée dont la valeur est celle
déjà en base est « inchangée » (pas de refus, rien d'écrit, rien au journal). Une valeur différente reste refusée : elle
se saisit dans les mois (règle de produit à confirmer, voir le rapport de la vie du groupe).
"""
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile

from collecte import exports as E
from collecte import imports as I
from collecte.calcul import recalculer
from collecte.models import Journal, Reponse
from collecte.test_periodes import Base
from parametres.libelles import libelle
from referentiel.models import Attribution, Utilisateur

D = Decimal


class ValeurCumuleeTests(Base):
    def setUp(self):
        super().setUp()
        for m in range(1, 13):
            self.saisir_mois(2026, m, self.e1, 10)
        recalculer(self.annee)
        self.cumul = Reponse.objects.get(periode=self.annee.periode, kpi=self.elec, organisation=self.e1)
        self.assertEqual(self.cumul.valeur, D(120))

    def fichier(self, valeur):
        lignes = [["ID KPI", "Organisation", "Exercice", "Valeur"], ["ELEC", "E1", 2026, valeur]]
        return SimpleUploadedFile("valeurs.csv", "\n".join(";".join(map(str, l)) for l in lignes).encode())

    def test_identique_inchangee_sans_ecriture_ni_journal(self):
        avant_journal, avant_maj = Journal.objects.count(), self.cumul.date_maj
        a = I.analyser(self.admin, self.fichier("120"), campagne_defaut=self.annee)
        self.assertEqual([(l.kpi_id, l.action) for l in a.lignes], [("ELEC", "inchange")])
        a, ecrites, avert = I.appliquer(self.admin, self.fichier("120"), "valeurs.csv", campagne_defaut=self.annee)
        self.assertEqual((ecrites, avert, a.rejets), (0, [], []))
        self.assertEqual(Journal.objects.count(), avant_journal)
        self.cumul.refresh_from_db()
        self.assertEqual((self.cumul.valeur, self.cumul.date_maj, self.cumul.origine), (D(120), avant_maj, Reponse.Origine.CUMUL))

    def test_differente_toujours_refusee(self):
        a = I.analyser(self.admin, self.fichier("121"), campagne_defaut=self.annee)
        self.assertEqual([(l.action, l.motif) for l in a.lignes], [("rejet", libelle("suivi.importer.motif.cumulee"))])

    def test_qui_ne_voit_pas_le_cumul_reste_refuse(self):
        # le contributeur ne voit pas la valeur cumulée à l'écran : l'aperçu ne doit pas lui dire qu'un chiffre est le bon
        for v in ("120", "121"):
            a = I.analyser(self.contrib, self.fichier(v), campagne_defaut=self.annee)
            self.assertEqual([l.action for l in a.lignes], ["rejet"])

    def test_validateur_qui_voit_le_cumul_inchangee(self):
        val = Utilisateur.objects.create(username="val", email="val@exemple.test", role=Utilisateur.Role.VALIDATEUR)
        Attribution.objects.create(kpi=self.elec, organisation=self.e1, utilisateur=val, role=Attribution.Role.VALIDATEUR)
        a = I.analyser(val, self.fichier("120"), campagne_defaut=self.annee)
        self.assertEqual([l.action for l in a.lignes], ["inchange"])

    def test_export_base_aller_retour_zero_changement(self):
        self.saisir_mois(2026, 5, self.e2, 7)
        recalculer(self.annee)
        p = E.Parametres.depuis({"presentation": "base", "format": "xlsx", "exercices": ["2026"], "periodes": ["annee"],
                                 "referentiel": "RSE"})
        rep = E.exporter(self.admin, p)
        contenu = b"".join(rep.streaming_content) if rep.streaming else rep.content
        avant = Journal.objects.count()
        a, ecrites, avert = I.appliquer(self.admin, SimpleUploadedFile("export.xlsx", contenu), "export.xlsx",
                                        campagne_defaut=self.annee)
        self.assertEqual((ecrites, avert, [l.motif for l in a.rejets]), (0, [], []))
        self.assertIn("inchange", {l.action for l in a.lignes})
        self.assertEqual(Journal.objects.count(), avant)
