"""Administration › Attributions, choix « Validateurs » (règle du projet) : un onglet par niveau
d'organisation, une ligne par KPI saisi à ce niveau ou en dessous ; une case est couverte par un validateur donné sur
elle ou sur une organisation au-dessus (``saisie.cellules`` : l'attribution vaut aussi pour les organisations en dessous)."""
import json
import re

from django.urls import reverse

from referentiel.models import Attribution, Niveau, Utilisateur

from .aides_tests.saisie import Base

URL = reverse("collecte:admin_attributions")


class PageValidateursTests(Base):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)

    def page(self, **params):
        rep = self.client.get(URL, params)
        self.assertEqual(rep.status_code, 200)
        return rep

    def onglet(self, rep, code):
        return next(o for o in rep.context["onglets"] if o["code"] == code)

    def test_onglets_par_niveau_d_organisation_et_couverture_heritee(self):
        rep = self.page(role="validateur", niveau=Niveau.COUNTRY)
        self.assertEqual(rep.context["role_attr"], "validateur")
        pays = self.onglet(rep, Niveau.COUNTRY)
        self.assertEqual((pays["nb_kpi"], pays["nb_orgs"], pays["total"], pays["sans"]), (2, 1, 2, 1))  # EFF couvert, TX non
        entites = self.onglet(rep, Niveau.ENTITY)
        self.assertEqual((entites["total"], entites["sans"]), (4, 2))  # EFF couvert par le pays dans E1 et E2
        groupe = self.onglet(rep, Niveau.GROUP)
        self.assertEqual((groupe["total"], groupe["sans"]), (2, 2))
        html = rep.content.decode()
        self.assertIn(f'data-cle="EFF|{self.p.pk}"', html)
        self.assertRegex(html, r'<td class="cellule-attr" data-cle="EFF\|%d" data-org="%d" data-spocs="%d"' % (self.p.pk, self.p.pk, self.valid.pk))
        self.assertRegex(html, r'<td class="cellule-attr sans-spoc" data-cle="TX\|%d"' % self.p.pk)

    def test_case_couverte_depuis_le_dessus(self):
        html = self.page(role="validateur", niveau=Niveau.ENTITY).content.decode()
        case = re.search(r'<td class="cellule-attr par-dessus" data-cle="EFF\|%d"[^>]*data-spocs=""' % self.e1.pk, html)
        self.assertIsNotNone(case, html[:3000])
        self.assertIn("Pays", html[case.start():case.start() + 1500])
        self.assertRegex(html, r'<td class="cellule-attr sans-spoc" data-cle="TX\|%d"' % self.e1.pk)

    def test_personnes_proposees(self):
        """Seuls les validateurs et administrateurs actifs ; jamais un contributeur, un lecteur, un auditeur, un inactif."""
        Utilisateur.objects.create(username="lec", email="lec@exemple.test", role=Utilisateur.Role.LECTEUR)
        Utilisateur.objects.create(username="vieux", email="vieux@exemple.test", role=Utilisateur.Role.VALIDATEUR, is_active=False)
        rep = self.page(role="validateur")
        ids = {c["id"] for c in rep.context["comptes_json"]}
        self.assertEqual(ids, {self.valid.pk, self.admin.pk})
        self.assertEqual({p.pk for p in rep.context["personnes"]}, {self.valid.pk, self.admin.pk})
        # choix Contributeurs : inchangé (tous les comptes qui écrivent)
        rep = self.page(role="contributeur")
        self.assertEqual({c["id"] for c in rep.context["comptes_json"]}, {self.contrib.pk, self.autre.pk, self.valid.pk, self.admin.pk})

    def test_choix_memorise_et_contributeurs_par_defaut(self):
        self.assertEqual(self.page().context["role_attr"], "contributeur")
        self.page(role="validateur")
        self.assertEqual(self.page().context["role_attr"], "validateur")
        self.assertEqual(self.page(role="n_importe_quoi").context["role_attr"], "contributeur")

    def test_contributeurs_sans_changement(self):
        html = self.page(role="contributeur", niveau=Niveau.ENTITY).content.decode()
        self.assertNotIn("par-dessus", html)
        self.assertIn(f'data-cle="EFF|{self.e1.pk}" data-org="{self.e1.pk}" data-spocs="{self.contrib.pk}"', html)

    def test_validateur_inactif_ne_couvre_pas(self):
        Utilisateur.objects.filter(pk=self.valid.pk).update(is_active=False)
        rep = self.page(role="validateur", niveau=Niveau.COUNTRY)
        self.assertEqual(self.onglet(rep, Niveau.COUNTRY)["sans"], 2)

    def test_grille_dit_le_role(self):
        html = self.page(role="validateur").content.decode()
        self.assertIn('data-role-attr="validateur"', html)
        self.assertIn('id="filtre-role"', html)

    def test_attribuer_puis_page(self):
        """Une attribution donnée par la page couvre les cases du dessous dans l'onglet de leur niveau."""
        rep = self.client.post(reverse("collecte:attribuer"), json.dumps(
            {"cles": [f"TX|{self.p.pk}"], "utilisateur": self.valid.pk, "role": "validateur", "format": "cellule"}),
            content_type="application/json")
        self.assertEqual(rep.status_code, 200)
        self.assertEqual(self.onglet(self.page(role="validateur"), Niveau.ENTITY)["sans"], 0)

    def test_reserve_a_l_administrateur(self):
        lec = Utilisateur.objects.create(username="lec", email="lec@exemple.test", role=Utilisateur.Role.LECTEUR)
        aud = Utilisateur.objects.create(username="aud", email="aud@exemple.test", role=Utilisateur.Role.AUDITEUR)
        for u in (self.contrib, self.valid, lec, aud):
            self.client.force_login(u)
            self.assertEqual(self.client.get(URL, {"role": "validateur"}).status_code, 403, u.role)
        self.assertEqual(Attribution.objects.filter(role=Attribution.Role.VALIDATEUR).count(), 1)
