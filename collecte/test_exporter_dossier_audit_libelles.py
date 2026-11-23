"""Dossier d'audit : les personnes sont nommées comme dans l'onglet Historique (le nom, pas l'adresse e-mail) et les statuts
portent les mots de l'écran (« To fill in », pas « To fill »)."""
from unittest import mock

from parametres import langues as langues_
from parametres.libelles import libelle

from .models import Reponse
from .test_exporter_dossier_audit import AvecDossier, lignes

CODES = ["en", "fr", "es", "de", "it", "nl", "pt"]


class LibellesDuDossierTests(AvecDossier):
    def test_saisi_par_et_valide_par_donnent_le_nom(self):
        self.contrib.first_name, self.contrib.last_name = "Camille", "Durand"
        self.contrib.save()
        wb = self.classeur_de(self.auditeur)
        par = {(l["KPI ID"], l["Organisation code"]): l for l in lignes(wb["Audit"])}
        l = par[("EFF", self.e1.code)]
        self.assertEqual((l["Entered by"], l["Validated by"]), ("Camille Durand", "Camille Durand"))
        self.assertIn("Camille Durand", l["Justifications (who, when, text)"])
        self.assertNotIn("@", l["Justifications (who, when, text)"].split(" : ")[0])
        historique = lignes(wb["History"])
        self.assertIn("Camille Durand", {h["Author"] for h in historique if "Author" in h})  # même nom que l'onglet Historique

    def test_statuts_avec_les_mots_de_l_ecran(self):
        for code in CODES:
            with self.subTest(langue=code), mock.patch.object(langues_, "codes_actifs", return_value=CODES):
                wb = self.classeur_de(self.auditeur, langue=code)
                audit = wb[libelle("suivi.export.audit.onglet.cases", code)]
                colonne = [c.value for c in audit[1]].index(libelle("suivi.export.colonne.statut", code))
                vus = {r[colonne].value for r in audit.iter_rows(min_row=2)}
                ecran = {libelle(f"choix.reponse.statut.{s.value}", code) for s in Reponse.Statut}
                self.assertLessEqual(vus, ecran, (code, vus - ecran))
                self.assertIn(libelle("choix.reponse.statut.a_saisir", code), vus)
