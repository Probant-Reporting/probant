"""Uniformisation de l'interface, lot 1 : une seule apparence par fonction, dans toutes les pages.
Encart en quatre teintes ({% encart %}), liste « À traiter » partagée par le Tableau de bord et l'Administration, lien
d'action de ligne souligné, création par un bouton avec l'icône « plus » dessinée, deux tailles de bouton, loupe dans
chaque recherche, croix dessinée et corbeille. Les anciens styles ne doivent pas revenir. Données inventées."""
import datetime
import re
from pathlib import Path

from django.conf import settings
from django.template import Context, Template, TemplateSyntaxError
from django.test import SimpleTestCase
from django.urls import reverse

from referentiel.models import Attribution

from .models import Campagne
from .templatetags.collecte import gras_premiere_phrase
from .aides_tests.relances import JOUR, SANS_SMTP, figer_la_date
from .aides_tests.saisie import Base
from collecte.outils_tests import html_de

RACINE = Path(settings.BASE_DIR)
GABARITS = [f for d in ("collecte/templates", "parametres/templates", "espaces/templates", "templates")
            for f in (RACINE / d).rglob("*") if f.suffix in (".html", ".js")]
CSS = (RACINE / "static/css/outil.css").read_text(encoding="utf-8")


def rendre(texte, **contexte):
    return Template("{% load collecte %}" + texte).render(Context(contexte))


class EncartTests(SimpleTestCase):
    def test_premiere_phrase_en_gras(self):
        g = gras_premiere_phrase
        self.assertEqual(g("Enregistré."), '<strong class="encart-titre">Enregistré.</strong>')  # une phrase : tout en gras
        self.assertEqual(g("Rien ne part : écrivez. Le reste marche."),
                         '<strong class="encart-titre">Rien ne part : écrivez.</strong> Le reste marche.')
        # un point dans un lien ou dans un attribut ne coupe pas la phrase ; un nombre décimal non plus
        self.assertEqual(g('Voir <a href="a.html">la page 1.2. Ici</a> puis. Fin.'),
                         '<strong class="encart-titre">Voir <a href="a.html">la page 1.2. Ici</a> puis.</strong> Fin.')
        self.assertEqual(g("<strong>Déjà en gras.</strong> Suite."), "<strong>Déjà en gras.</strong> Suite.")
        self.assertEqual(g(""), "")

    def test_balise_encart(self):
        html = rendre('{% encart "erreur" role="alert" id="e" %}{{ e }}{% endencart %}', e="Nom <déjà> pris. Changez-le.")
        self.assertEqual(html, '<p class="encart encart-erreur" role="alert" id="e"><strong class="encart-titre">'
                               "Nom &lt;déjà&gt; pris.</strong> Changez-le.</p>")
        # contenu en paragraphes : un <div>, la première phrase du premier paragraphe en gras
        html = rendre('{% encart "info" %}<p>Un. Deux.</p><ol><li>a</li></ol>{% endencart %}')
        self.assertEqual(html, '<div class="encart encart-info"><p><strong class="encart-titre">Un.</strong> Deux.</p><ol><li>a</li></ol></div>')
        # options : élément de liste, compact, classe, attribut nu selon une condition
        html = rendre('{% encart "avertissement" balise="li" compact=True classe="mt-0" hidden=h data_x=True %}A.{% endencart %}', h=True)
        self.assertEqual(html, '<li class="encart encart-avertissement compact mt-0" hidden data-x><strong class="encart-titre">A.</strong></li>')
        self.assertNotIn("hidden", rendre('{% encart "succes" hidden=h %}A.{% endencart %}', h=False))
        self.assertEqual(rendre('{% encart "succes" %} {% endencart %}'), "")  # rien à dire : rien d'affiché
        with self.assertRaises(TemplateSyntaxError):
            rendre('{% encart "jaune" %}A.{% endencart %}')  # le jaune reste réservé au brouillon

    def test_message_du_haut_de_page(self):
        self.assertEqual(rendre("{{ m|premiere_phrase_gras }}", m="Fait. <b>"), '<strong class="encart-titre">Fait.</strong> &lt;b&gt;')

    def test_quatre_teintes_avec_icone(self):
        for teinte, masque in (("avertissement", "--svg-alerte-fin"), ("erreur", "--svg-erreur"), ("succes", "--svg-coche-rond")):
            self.assertRegex(CSS, r"\.encart-%s::before[^{]*\{[^}]*mask-image: var\(%s\)" % (teinte, masque))
        self.assertIn(".encart::before, .messages li::before", CSS)  # l'icône « information » par défaut


class AnciensStylesTests(SimpleTestCase):
    """Les styles remplacés ne reviennent ni dans un gabarit ni dans la feuille de style."""

    def test_gabarits(self):
        interdits = {
            "encart jaune ou ancien encart": re.compile(r'class="(?:[^"]* )?(?:alerte|succes|encart-avertissement-court|encart-au-dessus|alerte-comptage|bandeau-traduction)(?: [^"]*)?"'),
            "encart sans la classe de base": re.compile(r'class="encart-(?:info|avertissement|erreur|succes)\b'),
            "gros bouton": re.compile(r"gros-bouton|petit-bouton"),
            "croix en caractère": re.compile(r">\s*[×✕]\s*</button>|textContent = \"×\"|texte: \"[×+]\""),
            "plus en caractère sur un bouton": re.compile(r'class="bouton[^"]*"[^>]*>\s*\+ '),
            "loupe écrite dans le gabarit": re.compile(r'recherche-icone">\s*\{% icone "rechercher"'),
        }
        fautes = []
        for f in GABARITS + [RACINE / "static/js/visualisation.js"]:
            texte = f.read_text(encoding="utf-8")
            for nom, motif in interdits.items():
                for m in motif.finditer(texte):
                    if 'data-op="*"' in texte[max(0, m.start() - 80):m.end()]:  # touche « multiplier » du clavier de formule
                        continue
                    fautes.append(f"{f.relative_to(RACINE)} : {nom} ({m.group(0)[:60]})")
        self.assertEqual(fautes, [])

    def test_feuille_de_style(self):
        for ancien in (".gros-bouton", ".petit-bouton", ".alerte {", ".alerte.erreur", ".succes {", ".encart-au-dessus", ".encart-avertissement-court",
                       ".alerte-comptage", ".bandeau-traduction", ".a-faire-tdb", ".alerte-sans-spoc", ".a-traiter-admin"):
            self.assertNotIn(ancien, CSS, ancien)
        # lien d'action : souligné dans la règle de base, plus resouligné page par page
        self.assertRegex(CSS, r"(?m)^\.lien-action \{[^}]*text-decoration: underline")
        self.assertEqual(re.findall(r"(?m)^[^\n{]*\.lien-action[^{]*\{[^}]*text-decoration: underline", CSS).__len__(), 1)
        self.assertRegex(CSS, r"(?m)^input\[type=search\] \{[^}]*background-image: var\(--svg-loupe\)")  # la loupe, partout
        self.assertIn(".bouton.compact, button.compact", CSS)

    def test_libelles_de_creation_sans_plus(self):
        import json

        for f in (RACINE / "libelles").glob("*.json"):
            for cle, texte in json.loads(f.read_text(encoding="utf-8")).items():
                if cle in ("admin.comptes.nouveau", "admin.comptes.plusieurs", "admin.organisations.nouvelle", "admin.organisations.plusieurs",
                           "admin.accueil.ajouter_referentiel", "admin.langues.ajouter_titre", "referentiels.accueil.ajouter",
                           "referentiels.contenu.nouveau_kpi", "saisie.coherence.regles.nouvelle", "visu.vue.ajouter"):
                    self.assertFalse(texte.startswith("+"), f"{f.name} {cle}")


class ATraiterPartageTests(Base):
    """Le même bloc « À traiter » dans le Tableau de bord et l'Administration : mêmes titres, mêmes mots dans les liens."""

    def setUp(self):
        super().setUp()
        figer_la_date(self)
        Campagne.objects.filter(pk=self.c.pk).update(date_ouverture=JOUR - datetime.timedelta(days=30),
                                                     date_fin_saisie=JOUR + datetime.timedelta(days=30))
        self.c.refresh_from_db()
        Attribution.objects.create(kpi=self.eff, organisation=self.e2, utilisateur=self.autre)  # TX/E2 reste sans SPOC

    def bloc(self, url):
        html = html_de(self.client, url)
        self.assertEqual(html.count('<section class="carte a-traiter"'), 1)
        debut = html.index('<section class="carte a-traiter"')
        return html[debut:html.index("</section>", debut)]

    def test_meme_bloc_memes_mots(self):
        self.client.force_login(self.admin)
        with SANS_SMTP:
            tdb, adm = self.bloc(reverse("collecte:tableau_de_bord")), self.bloc(reverse("collecte:admin_accueil"))
        for bloc in (tdb, adm):
            self.assertIn("À traiter", bloc)
            self.assertIn('class="compteur-titre"', bloc)
            for mot in ("Attribuer</a>", "Voir et relancer</a>", "Hébergement</a>"):
                self.assertIn(mot, bloc)
            for titre in ("sans SPOC</b>", "en retard</b>", "E-mails pas encore configurés</b>"):
                self.assertIn(titre, bloc)
        self.assertNotIn("À faire maintenant", tdb)
        self.assertIn("data-voir-retards", tdb)       # tableau de bord : les organisations en retard, dans la page
        self.assertNotIn("data-voir-retards", adm)    # Administration : le lien mène au tableau de bord
        self.assertIn(reverse("collecte:relances"), tdb)  # « Préparer la relance… » dans la ligne du titre

    def test_liens_reserves_a_l_administrateur(self):
        self.client.force_login(self.valid)
        with SANS_SMTP:
            rep = self.client.get(reverse("collecte:tableau_de_bord"))
        sujets = {x["code"]: x for x in rep.context["a_faire"]}
        self.assertEqual(sujets["emails"]["action"], "")      # le validateur ne règle pas l'hébergement
        if "sans_spoc" in sujets:
            self.assertEqual(sujets["sans_spoc"]["action"], "")
        self.assertNotContains(rep, "Hébergement</a>")


class PagesTests(Base):
    def test_campagnes_gerer_lien_souligne_en_derniere_colonne(self):
        self.client.force_login(self.admin)
        html = html_de(self.client, reverse("collecte:admin_campagnes"))
        self.assertIn('<td class="action-ligne"><a class="lien-action"', html)

    def test_creation_bouton_avec_icone_plus(self):
        self.client.force_login(self.admin)
        for url, texte in ((reverse("collecte:admin_comptes"), "Nouveau compte"), (reverse("collecte:admin_comptes"), "Plusieurs comptes"),
                           (reverse("collecte:admin_organisations"), "Nouvelle organisation"), (reverse("collecte:echanges"), "Nouvel export"),
                           (reverse("collecte:admin_accueil"), "Ajouter un référentiel"), (reverse("parametres:langues"), "Ajouter une langue"),
                           (reverse("collecte:admin_campagnes"), "Nouvelle campagne"), (reverse("collecte:regles"), "Nouvelle règle")):
            html = html_de(self.client, url)
            self.assertRegex(html, r'class="bouton[^"]*"[^>]*><svg class="icone-svg"[^>]*>.*?</svg> %s<' % re.escape(texte), f"{url} {texte}")
            self.assertNotIn(f"+ {texte}", html)

    def test_recherche_en_premier_dans_l_historique(self):
        self.client.force_login(self.admin)
        html = html_de(self.client, reverse("collecte:admin_journal"))
        barre = html[html.index('<form method="get" class="barre-filtres">'):]  # barre de filtres
        self.assertLess(barre.index('type="search"'), barre.index("<select"))
