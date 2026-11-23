"""Reprise des données, étape « Correspondances » : contrastes (axe-core si AXE_JS) de l'étiquette « à choisir », en clair
et en sombre, à 1 440 et 390 px."""
import io
import os

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from openpyxl import Workbook

from .aides_tests.navigateur import AXE, NavigateurBase


class RepriseCorrespondancesNavigateurTests(NavigateurBase):
    def vers_correspondances(self):
        """Dépose un fichier dont un indicateur n'a aucun équivalent sûr, puis arrive sur l'étape (état gardé en session)."""
        wb = Workbook()
        for ligne in (["Indicateur", "Entité", "Unité", 2022, 2023], ["Effectif", "Lille", "ETP", 100, 104],
                      ["Indicateur sans équivalent", "Lille", "", 5, 6], ["Autre indicateur inconnu", "Lyon", "", 1, 2],
                      ["Encore un indicateur inconnu", "Lyon", "", 3, 4]):
            wb.active.append(ligne)
        flux = io.BytesIO()
        wb.save(flux)
        self.client.force_login(self.admin)
        url = reverse("collecte:admin_reprise")
        rep = self.client.post(url + "?etape=fichier", {"action": "deposer", "source": "Essai",
                                                        "fichier": SimpleUploadedFile("ancien.xlsx", flux.getvalue())}, follow=True)
        r = rep.context["r"]
        donnees = {"action": "suivant", "entete": r.entete + 1, "forme": r.forme, "valeurs": ["2022", "2023"]}
        donnees.update({f"role_{role}": t for role, t in r.colonnes.items()})
        rep = self.client.post(url + "?etape=colonnes", donnees, follow=True)
        rep = self.client.get(url + "?etape=correspondances")
        self.assertTrue(any(not p.sur for p in rep.context["kpis"]), "au moins une ligne « à choisir »")
        return url + "?etape=correspondances"

    def test_accessibilite_axe(self):
        if not AXE or not os.path.exists(AXE):
            self.skipTest("axe-core absent (variable AXE_JS)")
        with open(AXE, encoding="utf-8") as f:
            axe = f.read()
        chemin = self.vers_correspondances()
        for schema in ("light", "dark"):
            for largeur in (1440, 390):
                page = self.page(self.admin, largeur=largeur)
                page.emulate_media(color_scheme=schema)
                self.aller(page, chemin)
                self.assertGreater(page.locator(".etiquette-proposition.a-verifier").count(), 0)
                page.add_script_tag(content=axe)
                violations = page.evaluate("""async () => { const r = await axe.run(document, {runOnly: {type: 'tag', values:
                    ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']}});
                    return r.violations.map(v => v.id + ' ' + v.nodes.map(n => n.target).join(','))}""")
                self.assertEqual(violations, [], (schema, largeur))
