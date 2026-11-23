"""Grille des attributions (échelle, P-A4) : les cases sont écrites en Python (``html_cellule_attr``, ``html_sans_case``)
au lieu d'un gabarit inclus par case. Preuve d'équivalence : sur des cas tirés au hasard (graine fixe), dans les trois
langues, le HTML est identique, octet pour octet, à celui des anciens gabarits recopiés ci-dessous tels qu'ils étaient
(``_cellule_attr.html`` et la boucle des cases de ``attributions.html`` au commit 539519f)."""
import random

from django.template import Context, Template
from django.test import TestCase

from parametres import langues as L
from referentiel.models import KPI, Niveau, Organisation, Utilisateur

from .administration import _TextesGrille, cellule_html, html_cellule_attr, html_sans_case

ANCIENNE_CASE = (
    '{% load collecte %}<td class="cellule-attr{% if not spocs %} sans-spoc{% endif %}" data-cle="{{ kpi.pk }}|{{ org.pk }}" data-org="{{ org.pk }}" data-spocs="{% for u in spocs %}{{ u.id }}{% if not forloop.last %},{% endif %}{% endfor %}"><div class="contenu-cellule">\n'
    '  <input type="checkbox" class="choix-case" aria-label="{% libelle "admin.attributions.selectionner" kpi=kpi.code organisation=org.nom %}">\n'
    '  <button type="button" class="bouton-spoc">{% if spocs %}<span class="etiquette-spoc">{% avatar spocs.0 %}<span class="nom-spoc">{{ spocs.0|prenom_initiale }}</span>{% if spocs|length > 1 %}<span class="plus">+{{ spocs|length|add:"-1" }}</span>{% endif %}</span>{% else %}<span class="a-attribuer">{% libelle "admin.attributions.attribuer" %}</span>{% endif %}<span class="visually-hidden"> – {% for u in spocs %}{{ u }}{% if not forloop.last %}, {% endif %}{% empty %}{% libelle "admin.attributions.aucun_spoc" %}{% endfor %}</span></button>\n'
    '  {% if spocs %}<div class="liste-spocs" hidden>\n'
    '    <div class="titre-infobulle">{% libelle "admin.attributions.infobulle_titre" n=spocs|length organisation=org.nom %}</div>\n'
    '    {% for u in spocs %}<div class="ligne-infobulle">{% avatar u %}<span><b>{{ u }}</b><span>{{ u.email }}</span></span></div>{% endfor %}\n'
    '    <div class="pied-infobulle">{% libelle "admin.attributions.cliquer_modifier" %}</div>\n'
    '  </div>{% endif %}\n'
    '</div></td>')
ANCIENNE_SANS_CASE = (
    '{% load collecte %}{% libelle "admin.attributions.sans_case_titre" kpi=kpi.code niveau=kpi.granularite organisation=o.nom as t_sc %}'
    '{% libelle "admin.attributions.sans_case" kpi=kpi.code niveau=kpi.granularite as t_sc2 %}<td class="sans-case" title="{{ t_sc }}">'
    '<span aria-hidden="true">·</span><span class="visually-hidden">{{ t_sc2 }}</span></td>')

# noms piégeux : caractères à échapper, apostrophes, accents, prénom absent, nom absent
PRENOMS = ["", "Camille", "Zoé", "Jean-Marc", "O'Neil", "<b>Eve</b>", "A&B", 'Dan "D"']
NOMS = ["", "Martin", "Dupont-Moretti", "Ñúñez", "<i>x</i>", "L'Été"]
ORGS = ["Site 1", "Usine & Co", "Dépôt <Nord>", 'Entrepôt "Sud"', "L'Atelier", "工場"]
CODES = ["EFF", "E&C", "GHG-1", "X<2>", "K'1", "Énergie"]


class CaseIdentiqueAuGabaritTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        alea = random.Random(20261113)
        groupe = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        cls.orgs = [Organisation.objects.create(nom=n, niveau_id=Niveau.SITE, parent=groupe) for n in ORGS]
        cls.kpis = [KPI.objects.create(code=c, libelle=f"KPI {c}", type_saisie_id=alea.choice(["Saisi", "FE"]),
                                       granularite_id=alea.choice([Niveau.SITE, Niveau.ENTITY])) for c in CODES]
        cls.personnes = []
        for i in range(12):
            u = Utilisateur.objects.create(username=f"u{i}", email=f"u{i}.{alea.choice(['a', 'b&c', 'd'])}@exemple.test",
                                           first_name=alea.choice(PRENOMS), last_name=alea.choice(NOMS))
            cls.personnes.append(u)

    def cas(self, n=250):
        alea = random.Random(1113)
        for _ in range(n):
            spocs = sorted(alea.sample(self.personnes, alea.choice([0, 0, 1, 1, 1, 2, 3, 5])), key=str)
            yield alea.choice(self.kpis), alea.choice(self.orgs), spocs

    def test_case_identique_dans_les_trois_langues(self):
        ancienne = Template(ANCIENNE_CASE)
        for langue in ("en", "fr", "es"):
            with L.activer_interface(langue):
                textes = _TextesGrille()  # partagé entre les cases, comme dans la page
                for i, (kpi, org, spocs) in enumerate(self.cas()):
                    attendu = ancienne.render(Context({"kpi": kpi, "org": org, "spocs": spocs}))
                    with self.subTest(langue=langue, cas=i):
                        self.assertEqual(html_cellule_attr(kpi, org, spocs, textes), attendu)
                        self.assertEqual(html_cellule_attr(kpi, org, spocs), attendu)  # sans textes partagés

    def test_sans_case_identique_dans_les_trois_langues(self):
        ancienne = Template(ANCIENNE_SANS_CASE)
        for langue in ("en", "fr", "es"):
            with L.activer_interface(langue):
                textes = _TextesGrille()
                for kpi in self.kpis:
                    for org in self.orgs:
                        with self.subTest(langue=langue, kpi=kpi.code, org=org.nom):
                            self.assertEqual(html_sans_case(kpi, org, textes), ancienne.render(Context({"kpi": kpi, "o": org})))

    def test_case_renvoyee_apres_une_attribution(self):
        """La case renvoyée par « attribuer » (format cellule) est celle de la page : mêmes SPOC, triés par nom."""
        from referentiel.models import Attribution

        kpi, org = self.kpis[0], self.orgs[1]
        for u in self.personnes[:3]:
            Attribution.objects.create(kpi=kpi, organisation=org, utilisateur=u)
        Attribution.objects.create(kpi=kpi, organisation=org, utilisateur=self.personnes[3], role=Attribution.Role.VALIDATEUR)
        self.personnes[2].is_active = False
        self.personnes[2].save()
        attendu = Template(ANCIENNE_CASE).render(Context({"kpi": kpi, "org": org, "spocs": sorted(self.personnes[:2], key=str)}))
        self.assertEqual(cellule_html(None, kpi, org), attendu)
