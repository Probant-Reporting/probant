"""Fichier de configuration (import tout ou rien), organisations à l'ancien format, organisations collées (500 lignes au plus)."""
from django.core.management import CommandError, call_command
from django.test import TestCase
from django.urls import reverse

from . import configuration as C
from .aides_tests import echanges as TE
from .models import Journal, RegleCoherence
from parametres import mise_en_place as M, niveaux as N
from referentiel.models import KPI, Niveau, OrgAlias, Organisation, Utilisateur


# ---------------------------------------------------------------- 2. fichier de configuration : tout ou rien
class ConfigurationToutOuRienTests(TE.Base):
    def setUp(self):
        super().setUp()
        RegleCoherence.objects.create(nom="Double ≥ effectif", gauche="[DBL]", operateur=">=", droite="[EFF]", niveau_id=Niveau.ENTITY)

    def fichier(self, kpi=(), orgs=(), alias=(), regles=()):
        """Classeur exporté par l'outil, avec des lignes ajoutées."""
        import io

        from django.core.files.uploadedfile import SimpleUploadedFile

        wb = TE.classeur(C.exporter())
        for onglet, lignes in (("KPI", kpi), ("Organisations", orgs), ("Alias", alias), ("Règles de cohérence", regles)):
            tete = [c.value for c in wb[onglet][1]]
            for ligne in lignes:
                wb[onglet].append([ligne.get(t, "") for t in tete])
        flux = io.BytesIO()
        wb.save(flux)
        return SimpleUploadedFile("config.xlsx", flux.getvalue())

    def kpi(self, code, type_saisie="Saisi", formule=""):
        return {"ID KPI": code, "Ordre": 9, "Nom (FR)": f"KPI {code}", "Type de saisie": type_saisie, "Type de réponse": "Numérique",
                "Unité": "t", "Décimales": 2, "Granularité": "Entité", "Agrégation": "Somme", "Formule": formule}

    def test_une_ligne_refusee_dans_chaque_onglet(self):
        bons = dict(kpi=[self.kpi("NEUF")], orgs=[{"Nom": "E9", "Niveau": "Entité", "Rattachée à": "Pays"}],
                    alias=[{"Organisation": "E1", "Source": "Paie", "Libellé": "ENT-1"}],
                    regles=[{"Nom": "Neuf positif", "Partie gauche": "[EFF]", "Opérateur": "≥", "Partie droite": "0"}])
        mauvais = {"kpi": self.kpi("CASSE", "Calculé", "[INCONNU] + 1"),
                   "orgs": {"Nom": "Perdue", "Niveau": "Pays", "Rattachée à": "E1"},
                   "alias": {"Organisation": "Inconnue", "Source": "Paie", "Libellé": "X"},
                   "regles": {"Nom": "Cassée", "Partie gauche": "[ZZZ]", "Opérateur": "=", "Partie droite": "[EFF]"}}
        for onglet, ligne in mauvais.items():
            with self.subTest(onglet=onglet):
                lignes = {k: list(v) for k, v in bons.items()}
                lignes[onglet].append(ligne)
                a, n, campagnes = C.appliquer(self.admin, self.fichier(**lignes), "config.xlsx")
                self.assertEqual((a.nb_rejets, n, campagnes), (1, 0, []))
                self.assertFalse(KPI.objects.filter(code="NEUF").exists())
                self.assertFalse(Organisation.objects.filter(nom="E9").exists())
                self.assertFalse(OrgAlias.objects.filter(libelle="ENT-1").exists())
                self.assertFalse(RegleCoherence.objects.filter(nom="Neuf positif").exists())
                self.assertFalse(Journal.objects.filter(action="import_configuration").exists())
        a, n, _ = C.appliquer(self.admin, self.fichier(**bons), "config.xlsx")  # sans la ligne refusée : tout passe
        self.assertEqual((a.nb_rejets, n), (0, 4))
        self.assertTrue(KPI.objects.filter(code="NEUF").exists())
        self.assertTrue(OrgAlias.objects.filter(libelle="ENT-1", organisation=self.e1).exists())

    def test_fichier_reimporte_sans_changement_n_ecrit_rien(self):
        avant = Journal.objects.count()
        a, n, campagnes = C.appliquer(self.admin, self.fichier(), "config.xlsx")
        self.assertEqual((a.nb_rejets, n, campagnes, a.importable), (0, 0, [], False))
        self.assertEqual(Journal.objects.count(), avant)

    def test_apercu_et_confirmation_le_disent(self):
        self.client.force_login(self.admin)
        url = reverse("collecte:admin_fichiers")
        f = self.fichier(kpi=[self.kpi("NEUF"), self.kpi("CASSE", "Calculé", "[INCONNU] + 1")])
        rep = self.client.post(url, {"action": "verifier", "fichier": f})
        self.assertContains(rep, "1 ligne refusée.</strong> L'import se fait tout ou rien : l'outil n'a donc rien enregistré. Corrigez cette ligne")
        self.assertContains(rep, 'value="confirmer" disabled')
        rep = self.client.post(url, {"action": "confirmer"})  # même forcé, rien n'est enregistré
        self.assertContains(rep, "l'outil n'a donc rien enregistré")
        self.assertFalse(KPI.objects.filter(code="NEUF").exists())

    def test_commandes_en_ligne(self):
        import os
        import tempfile

        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8") as f:
            f.write("source,libelle,organisation\nPaie,ENT-1,E1\nPaie,X,Inconnue\n")
        try:
            with self.assertRaisesMessage(CommandError, "nothing has been saved"):
                call_command("import_alias", f.name, stdout=open(os.devnull, "w"))
            self.assertFalse(OrgAlias.objects.filter(libelle="ENT-1").exists())
        finally:
            os.unlink(f.name)


class ImportOrganisationsAncienFormatTests(TestCase):
    def test_tout_ou_rien(self):
        import io
        import os

        from openpyxl import Workbook

        from referentiel.echange import importer_organisations

        wb = Workbook()
        ws = wb.active
        ws.title = "Organizational structure"
        for l in (["Level", "Country", "Entity", "Site", "Unit (display)", "Status"], ["Group", "", "", "", "Groupe", ""],
                  ["Country", "FR", "", "", "France", ""], ["Entity", "XX", "E", "", "Orpheline", ""]):
            ws.append(l)
        flux = io.BytesIO()
        wb.save(flux)
        flux.seek(0)
        rapport = importer_organisations(flux)
        self.assertEqual((len(rapport.erreurs), rapport.crees), (1, 0))
        self.assertFalse(Organisation.objects.exists())
        flux.seek(0)
        with self.assertRaisesMessage(CommandError, "nothing has been saved"):
            import tempfile

            with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
                f.write(flux.getvalue())
            try:
                call_command("import_organisations", f.name, stdout=open(os.devnull, "w"))
            finally:
                os.unlink(f.name)


# ---------------------------------------------------------------- 4. coller des organisations : 500 lignes au plus
class CollerOrganisationsTests(TestCase):
    def setUp(self):
        self.admin = Utilisateur.objects.create(username="admin", email="admin@exemple.test", role=Utilisateur.Role.ADMIN)

    def texte(self, n):
        return "Groupe\n" + "\n".join(f"  Pays {i}" for i in range(1, n))

    def test_limite(self):
        self.assertEqual(M.MAX_ORGANISATIONS_COLLEES, 500)
        noeuds, erreurs = M.lire_arbre(self.texte(500), N.tous())
        self.assertEqual((len(noeuds), erreurs), (500, []))
        noeuds, erreurs = M.lire_arbre(self.texte(501), N.tous())
        self.assertEqual((noeuds, erreurs),
                         ([], ["La liste compte 501 organisations. Collez-en au plus 500 à la fois : découpez la liste."]))
        # collage depuis Excel : la ligne d'en-têtes ne compte pas
        colle = "Groupe\tPays\n" + "\n".join(f"Groupe\tPays {i}" for i in range(500))
        noeuds, erreurs = M.lire_arbre(colle, N.tous())
        self.assertEqual((len(noeuds), erreurs), (501, []))

    def test_page_plusieurs_organisations(self):
        self.client.force_login(self.admin)
        url = reverse("collecte:admin_organisations_plusieurs")
        rep = self.client.get(url)
        self.assertContains(rep, "Au plus 500 lignes à la fois")
        rep = self.client.post(url, {"action": "creer", "arbre": self.texte(501)})
        self.assertContains(rep, "La liste compte 501 organisations.</strong> Collez-en au plus 500 à la fois")
        self.assertFalse(Organisation.objects.exists())
