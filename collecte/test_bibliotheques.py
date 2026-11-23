"""Bibliothèques copiées dans static/vendor (docs/third_party_libraries.md) : fichiers intacts, licences présentes,
aucun script chargé depuis un autre site (pas de CDN : l'outil marche hors ligne)."""
import hashlib
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

VENDOR = Path(settings.BASE_DIR) / "static" / "vendor"
EMPREINTES = {
    "echarts-6.1.0/echarts.min.js": "b66b25aeb4df84e33199dc21694014d336d222cbd9deb0e5a7c14bd6aa0d0fd0",
    "echarts-6.1.0/langFR.js": "b754ab555ef9c5df6afe4baa8eb78274249c395165ae49b4a71e084919711ec2",
    "echarts-6.1.0/langEN.js": "58c4e62edd59e39e730deb563b88a6f47a10cc23bce3190f350a5ff34d9ef32e",
    "echarts-6.1.0/LICENSE": "634293835b43a6dd2094fa39182a3d9a6b9ca43b7fdb9ac354e8037af2a3093a",
    "echarts-6.1.0/NOTICE": "d491d358344f842685c1b1585970999db65fe30ecf7ef3867af8814f4016c016",
    "echarts-6.1.0/LICENSE-d3": "e1211892da0b0e0585b7aebe8f98c1274fba15bafe47fa1f4ee8a7a502c06304",
    "echarts-6.1.0/LICENSE-zrender": "a681e9d183c72b4af4856935893805eb48c08f0f5a3f260203db7444c20fb98a",
    "sortablejs-1.15.7/Sortable.min.js": "bf4241bc73fef7f11c59a283a69fe8051cdd31c6d8ff5a2b9ba219e7831fcf76",
    "sortablejs-1.15.7/LICENSE": "e94dfc31e800d169257569db270457c9f028440c9ccae41e7eb78b2db18f1298",
}
SCRIPT_EXTERNE = re.compile(r"""<script[^>]*\ssrc\s*=\s*["']?\s*(https?:)?//""", re.I)
IMPORT_EXTERNE = re.compile(r"""(import\s*\(?\s*["']|importScripts\s*\(\s*["']|fetch\s*\(\s*["'])(https?:)?//""", re.I)


class BibliothequesTests(SimpleTestCase):
    def test_empreintes(self):
        for chemin, attendue in EMPREINTES.items():
            with self.subTest(fichier=chemin):
                self.assertEqual(hashlib.sha256((VENDOR / chemin).read_bytes()).hexdigest(), attendue)

    def test_rien_d_autre_dans_vendor(self):
        """Un fichier ajouté sans empreinte (ou une ancienne version oubliée) est signalé."""
        presents = {str(p.relative_to(VENDOR)) for p in VENDOR.rglob("*") if p.is_file()}
        self.assertEqual(presents, set(EMPREINTES))

    def test_licences(self):
        for chemin in ("echarts-6.1.0/LICENSE", "echarts-6.1.0/NOTICE", "echarts-6.1.0/LICENSE-d3",
                       "echarts-6.1.0/LICENSE-zrender", "sortablejs-1.15.7/LICENSE"):
            self.assertGreater((VENDOR / chemin).stat().st_size, 100, chemin)
        self.assertIn("Apache License", (VENDOR / "echarts-6.1.0/LICENSE").read_text())
        self.assertIn("MIT", (VENDOR / "sortablejs-1.15.7/LICENSE").read_text())

    def test_aucun_script_externe(self):
        base = Path(settings.BASE_DIR)
        fichiers = [p for d in ("templates", "collecte/templates", "parametres/templates", "referentiel")
                    for p in (base / d).rglob("*.html")]
        fichiers += list((base / "static" / "js").rglob("*.js")) if (base / "static" / "js").exists() else []
        fichiers += list((base / "collecte" / "templates").rglob("*.js"))
        self.assertTrue(fichiers)
        for p in fichiers:
            texte = p.read_text(encoding="utf-8")
            with self.subTest(fichier=str(p.relative_to(base))):
                self.assertIsNone(SCRIPT_EXTERNE.search(texte))
                self.assertIsNone(IMPORT_EXTERNE.search(texte))
