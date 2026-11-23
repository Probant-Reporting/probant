"""Essais de résistance : adresses forgées par le
navigateur (identifiant écrit en texte), qui donnaient une erreur 500 au lieu d'un refus."""
import json

from django.urls import reverse

from .models import Campagne
from . import saisie as S
from .aides_tests.saisie import Base


class IdentifiantsForgesTests(Base):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)

    def test_retirer_une_preuve_avec_un_identifiant_en_texte(self):
        self.client.force_login(self.contrib)
        url = reverse("collecte:cellule", args=[self.c.pk, self.eff.pk, self.e1.pk])
        for v in ("abc", "", "1e3", "99999999999999999999999"):
            r = self.client.post(url, {"action": "retirer_preuve", "preuve": v})
            self.assertEqual(r.status_code, 404, v)

    def test_pages_d_administration(self):
        envois = [
            ("get", reverse("collecte:admin_organisation_nouvelle") + "?parent=abc", None),
            ("post", reverse("collecte:admin_remplacer"), {"de": "abc", "par": "x"}),
            ("post", reverse("collecte:echanges_listes"), {"action": "supprimer", "id": "abc"}),
            ("post", reverse("collecte:admin_reprise"), {"action": "supprimer_profil", "profil": "abc"}),
        ]
        for methode, url, donnees in envois:
            r = getattr(self.client, methode)(url, donnees or {})
            self.assertEqual(r.status_code, 404, url)

    def test_attributions_corps_invalide(self):
        url = reverse("collecte:attribuer")
        for corps in ("pas du json", "[]", json.dumps({"utilisateur": self.contrib.pk, "cles": 5})):
            self.assertEqual(self.client.post(url, corps, content_type="application/json").status_code, 400, corps)
        corps = json.dumps({"utilisateur": "abc", "cles": [f"EFF|{self.e1.pk}"], "campagne": self.c.pk})
        self.assertEqual(self.client.post(url, corps, content_type="application/json").status_code, 404)
        corps = json.dumps({"utilisateur": self.contrib.pk, "cles": ["EFF|abc"], "campagne": self.c.pk})
        self.assertEqual(self.client.post(url, corps, content_type="application/json").status_code, 404)
        self.assertEqual(Campagne.objects.count(), 2)

    def test_glisser_deposer_corps_invalide(self):
        """Ordre des exports, contenu d'un référentiel : un corps qui n'est pas un objet JSON donne 400."""
        for url in (reverse("collecte:echanges_ordre_modeles"), reverse("parametres:referentiel_contenu_action", args=[self.c.referentiel_id])):
            for corps in ("pas du json", "[1, 2]", "null"):
                r = self.client.post(url, corps, content_type="application/json")
                self.assertEqual(r.status_code, 400, (url, corps))


class RelanceDeuxCampagnesTests(Base):
    def test_campagne_sans_date_de_fin(self):
        """Une personne relancée pour deux campagnes dont l'une n'a pas de fin de saisie : le message s'écrit (avant :
        erreur, et la page Relances ne s'ouvrait plus)."""
        from . import relances as R

        S.enregistrer(self.contrib, self.c, self.eff, self.e1, "12", False, "")
        af = R.a_faire([self.c], destinataires=[self.contrib.pk])[0]
        sans_date = Campagne(exercice=2027, statut=Campagne.Statut.OUVERTE, periode=self.c.periode, referentiel=self.c.referentiel)
        af.campagnes.append((sans_date, af.campagnes[0][1]))
        sujet, texte = R.rediger(af)
        self.assertIn("(sans date)", texte)
