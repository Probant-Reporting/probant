"""Page Unités : la liste des unités dans une autre monnaie que la monnaie de référence (``admin.monnaies.autres_kpi``) est
échappée une seule fois. Un symbole piégé s'affiche tel qu'il est écrit, jamais interprété ni échappé deux fois (avant :
« &amp;lt; » à l'écran)."""
from django.test import TestCase
from django.urls import reverse

from parametres.models import Unite
from referentiel.models import KPI, Niveau, Utilisateur

URL = reverse("parametres:referentiel") + "?section=unites"
PIEGE = '$/<img src=x onerror=alert(1)>&"'


class EchappementTests(TestCase):
    def test_symbole_piege_echappe_une_fois(self):
        admin = Utilisateur.objects.create_user("admin", "admin@exemple.test", "x", role=Utilisateur.Role.ADMIN)
        u = Unite.objects.create(code="piege", symbole=PIEGE, libelle="piège", famille="Monnaie")
        KPI.objects.create(code="ACHATS", libelle="Achats", type_saisie_id="Saisi", granularite_id=Niveau.SITE, unite=u)
        self.client.force_login(admin)
        html = self.client.get(URL).content.decode()
        debut = html.index('class="aide-champ autre-monnaie"')
        phrase = html[debut:html.index("</span>", debut)]
        self.assertIn("$/&lt;img src=x onerror=alert(1)&gt;&amp;&quot;", phrase)
        self.assertNotIn("&amp;lt;", phrase)
        self.assertNotIn("<img", phrase)


class JoindreTests(TestCase):
    def test_liste_dans_un_libelle_et_seule(self):
        """Écran de l'installation (``admin.monnaies.gardees``) : même règle ; affichée seule, la liste reste échappée."""
        from django.template import Context, Template

        t = Template('{% load collecte %}{% libelle "admin.monnaies.gardees" n=2 liste=l|joindre:", " %}|{{ l|joindre }}')
        rendu = t.render(Context({"l": ["A<b>", 'B&"']}))
        dans_libelle, seule = rendu.split("|")
        self.assertIn("A&lt;b&gt;, B&amp;&quot;", dans_libelle)
        self.assertNotIn("&amp;lt;", dans_libelle)
        self.assertEqual(seule, "A&lt;b&gt;, B&amp;&quot;")
