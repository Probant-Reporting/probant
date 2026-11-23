"""Visite guidée de la première connexion (côté serveur) : étapes de chaque rôle, clé du navigateur par espace, compte et rôle,
retrait par le réglage, aucune écriture, bouton de l'Aide, sept langues. Le script est essayé dans le navigateur
(``test_navigateur_visite_guidee.py``)."""
import json
import re
from pathlib import Path

from django.test import override_settings
from django.urls import reverse

from parametres.libelles import libelle
from referentiel.models import KPI, Attribution, Utilisateur

from . import visite_guidee as VG
from .aides_tests.lecture_seule import Base
from .models import Alerte, Campagne, Journal, Preuve, Reponse

LANGUES = ("en", "fr", "es", "de", "it", "nl", "pt")
ROLES = ("admin", "validateur", "contributeur", "lecteur", "auditeur")


def donnees_de(reponse):
    m = re.search(r'<script id="visite-donnees" type="application/json">(.*?)</script>', reponse.content.decode(), re.S)
    return json.loads(m.group(1)) if m else None


@override_settings(VISITE_GUIDEE=True)
class VisiteGuideeServeurTests(Base):
    def setUp(self):
        super().setUp()
        self.valideur = Utilisateur.objects.create(username="valideur", email="valideur@exemple.test",
                                                   role=Utilisateur.Role.VALIDATEUR)
        self.par_role = {"admin": self.admin, "validateur": self.valideur, "contributeur": self.contrib, "lecteur": self.lecteur,
                         "auditeur": self.auditeur}

    def lire(self, user, adresse="collecte:tableau_de_bord", langue="en"):
        self.client.force_login(user)
        self.client.post(reverse("langue"), {"langue": langue})
        return self.client.get(reverse(adresse))

    def test_les_etapes_de_chaque_role(self):
        attendu = {"admin": 4, "validateur": 4, "contributeur": 4, "lecteur": 3, "auditeur": 4}
        for role, user in self.par_role.items():
            with self.subTest(role=role):
                d = donnees_de(self.lire(user))
                self.assertEqual(len(d["etapes"]), attendu[role])
                for e in d["etapes"]:
                    self.assertTrue(e["titre"] and e["texte"])
                    self.assertNotIn("cadre.visite.", e["titre"] + e["texte"])
                self.assertEqual(d["textes"]["suivant"], "Next")

    def test_trois_ou_quatre_bulles_courtes(self):
        for role, etapes in VG.ETAPES.items():
            self.assertIn(len(etapes), (3, 4), role)
        for l in LANGUES:
            for role, etapes in VG.ETAPES.items():
                for i in range(1, len(etapes) + 1):
                    self.assertLessEqual(len(libelle(f"cadre.visite.{role}.{i}.texte", l)), 200, (l, role, i))
                    self.assertLessEqual(len(libelle(f"cadre.visite.{role}.{i}.titre", l)), 40, (l, role, i))

    def test_elements_montres_existent_dans_la_barre_du_haut(self):
        """Chaque étape qui montre un élément le désigne par un sélecteur qui trouve un lien de la barre du haut."""
        for role, user in self.par_role.items():
            reponse = self.lire(user)
            html = reponse.content.decode()
            d = donnees_de(reponse)
            for cible, etape in zip(VG.ETAPES[role], d["etapes"]):
                self.assertEqual(bool(cible), bool(etape["cible"]), (role, cible))
                if not cible:
                    continue
                if cible == "aide":
                    self.assertIn('class="aide-haut"', html)
                    continue
                self.assertTrue(any(f'href="{reverse(n)}"' in html for n in VG.ONGLETS[cible]), (role, cible))

    def test_cle_par_espace_compte_et_role(self):
        cles = {role: donnees_de(self.lire(user))["cle"] for role, user in self.par_role.items()}
        self.assertEqual(len(set(cles.values())), 5)
        for role, user in self.par_role.items():
            self.assertTrue(cles[role].startswith("probant.visite."))
            self.assertTrue(cles[role].endswith(f".{user.pk}.{role}"), cles[role])
        # le même compte devenu un autre rôle : une autre clé, la visite de ce rôle se montre
        self.contrib.role = Utilisateur.Role.VALIDATEUR
        self.contrib.save()
        self.assertNotEqual(donnees_de(self.lire(self.contrib))["cle"], cles["contributeur"])

    def test_retrait_par_le_reglage(self):
        with override_settings(VISITE_GUIDEE=False):
            rep = self.lire(self.admin)
            self.assertNotIn(b"visite-donnees", rep.content)
            self.assertNotIn(b'id="visite"', rep.content)
            self.assertNotContains(self.client.get(reverse("collecte:aide")), "data-visite-relancer")

    def test_pas_de_visite_sans_connexion(self):
        self.client.logout()
        self.assertNotIn(b"visite-donnees", self.client.get("/connexion/").content)

    def test_pas_de_visite_pendant_le_changement_de_mot_de_passe_force(self):
        self.admin.doit_changer_mdp = True
        self.admin.save()
        self.client.force_login(self.admin)
        self.assertNotIn(b"visite-donnees", self.client.get(reverse("collecte:mon_compte")).content)

    def test_bouton_de_relance_dans_l_aide(self):
        for role, user in self.par_role.items():
            with self.subTest(role=role):
                rep = self.lire(user, "collecte:aide")
                self.assertContains(rep, "data-visite-relancer")
                self.assertContains(rep, "Show the tour again")

    def test_aucune_ecriture(self):
        for u in self.par_role.values():
            self.lire(u)  # choisir la langue s'écrit au journal : fait avant de compter
        modeles = (Reponse, Journal, Alerte, Preuve, Campagne, Utilisateur, Attribution, KPI)
        avant = {m.__name__: m.objects.count() for m in modeles}
        for u in self.par_role.values():
            self.lire(u)
            self.lire(u, "collecte:aide")
        self.assertEqual({m.__name__: m.objects.count() for m in modeles}, avant)

    def test_aucune_migration_ni_champ_pour_la_visite(self):
        from collecte import models as M

        for modele in (Utilisateur, M.Journal, M.Campagne):
            self.assertFalse([f.name for f in modele._meta.get_fields() if "visite" in f.name.lower()], modele)

    def test_la_page_de_chaque_langue(self):
        vus = set()
        for l in LANGUES:
            with self.subTest(langue=l):
                d = donnees_de(self.lire(self.contrib, "collecte:aide", langue=l))
                self.assertNotIn("cadre.visite.", json.dumps(d))
                vus.add(d["etapes"][0]["texte"])
        self.assertEqual(len(vus), 7)

    def test_cles_presentes_dans_les_sept_langues(self):
        racine = Path(__file__).resolve().parent.parent / "libelles"
        tables = {c: json.loads((racine / f"cadre.{c}.json").read_text(encoding="utf-8")) for c in LANGUES}
        cles = {k for k in tables["en"] if k.startswith("cadre.visite.")}
        self.assertEqual(len(cles), 10 + 2 * sum(len(e) for e in VG.ETAPES.values()))
        for c, t in tables.items():
            self.assertEqual(cles - set(t), set(), c)
            for k in cles:
                self.assertTrue(t[k], (c, k))

    def test_role_inconnu_recoit_la_visite_du_contributeur(self):
        class Faux:
            role = "autre"
            est_admin = False
        self.assertEqual(VG.role_de(Faux()), "contributeur")
