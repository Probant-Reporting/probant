"""Aides des tests aller-retour des échanges : base enrichie (oui / non, liste, décimales, N/A) et fichier Excel."""
import io

from django.core.files.uploadedfile import SimpleUploadedFile
from openpyxl import Workbook

from collecte import saisie as S
from collecte.models import Reponse
from collecte.aides_tests.echanges import Base as BaseEchanges
from parametres.models import TypeReponse
from referentiel.models import Attribution, KPI, Niveau


def fichier(lignes, nom="valeurs.xlsx", onglet="Saisie", formats=None):
    wb = Workbook()
    ws = wb.active
    ws.title = onglet
    for l in lignes:
        ws.append(l)
    for (ligne, colonne), fmt in (formats or {}).items():
        ws.cell(ligne, colonne).number_format = fmt
    flux = io.BytesIO()
    wb.save(flux)
    return SimpleUploadedFile(nom, flux.getvalue())


class Base(BaseEchanges):
    """En plus de la base des échanges : un oui / non (POL), une liste (CERT), un nombre à décimales (NRJ), un N/A
    commenté (TX de E2) et une valeur négative (NRJ de E2)."""

    def setUp(self):
        super().setUp()
        self.ouinon = TypeReponse.objects.create(code="OuiNon", libelle="Oui / non", format="oui_non",
                                                 traductions={"en": {"valeurs": ["Yes", "No"]}})
        self.certif = TypeReponse.objects.create(code="Certif", libelle="Certification", format="liste",
                                                 valeurs=["ISO 14001", "ISO 50001", "Aucune"])

        def kpi(code, **autres):
            return KPI.objects.create(code=code, libelle=code, type_saisie_id="Saisi", granularite_id=Niveau.ENTITY, **autres)
        self.pol = kpi("POL", type_reponse=self.ouinon, methode_agregation="Décompte")
        self.cert = kpi("CERT", type_reponse=self.certif, methode_agregation="Décompte")
        self.nrj = kpi("NRJ", methode_agregation="Somme", decimales=3)
        for k in (self.pol, self.cert, self.nrj):
            Attribution.objects.create(kpi=k, organisation=self.e1, utilisateur=self.contrib)
        S.enregistrer(self.admin, self.c, self.pol, self.e1, "Oui", False, "")
        S.enregistrer(self.admin, self.c, self.pol, self.e2, "Non", False, "")
        S.enregistrer(self.admin, self.c, self.cert, self.e1, "ISO 50001", False, "")
        S.enregistrer(self.admin, self.c, self.nrj, self.e1, "1234,5678", False, "Relevé")
        S.enregistrer(self.admin, self.c, self.nrj, self.e2, "-12,5", False, "Revente")
        S.enregistrer(self.admin, self.c, self.taux, self.e2, "", True, "Pas de salariés")
        S.enregistrer(self.admin, self.c, self.taux, self.e1, "12,345", False, "")

    def valeur(self, kpi, org, campagne=None):
        return Reponse.objects.get(periode=(campagne or self.c).periode, kpi=kpi, organisation=org)

    def actions(self, a):
        return sorted({l.action for l in a.lignes})
