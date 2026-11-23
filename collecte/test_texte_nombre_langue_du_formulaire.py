"""Nombres tapés relus dans la langue où le formulaire a été affiché (``saisie.texte_nombre``, ``langues.saisie``).

Scénario : le panneau de saisie s'affiche en français (« 2,125 ») ; la langue de la session passe à l'anglais depuis un autre
onglet (ou dans Mon compte) ; le panneau resté ouvert est enregistré. Avant : le serveur lisait « 2,125 » en anglais, soit
2125, en silence. Le formulaire porte désormais la langue de son affichage (champ caché ``langue_saisie``), et le serveur lit
les nombres avec elle (une langue de l'interface, sinon la langue courante)."""
import re
from decimal import Decimal

from django.test import RequestFactory
from django.urls import reverse

from parametres import langues as L

from . import saisie as S
from . import tableaux as TB
from .aides_tests.saisie import Base
from .models import Reponse

D = Decimal


class LangueDuFormulaireTests(Base):
    def setUp(self):
        super().setUp()
        self.r = S.enregistrer(self.contrib, self.c, self.eff, self.e1, "2.125", False, "")
        self.url = reverse("collecte:cellule", args=[self.c.pk, self.eff.pk, self.e1.pk])
        self.client.force_login(self.contrib)

    def langue_session(self, code):
        s = self.client.session
        s[L.CLE_SESSION] = code
        s.save()

    def panneau(self):
        html = self.client.get(self.url).content.decode()
        valeur = re.search(r'id="valeur" name="valeur" value="([^"]*)"', html).group(1)
        langue = re.search(r'name="langue_saisie" value="([^"]*)"', html)
        version = re.search(r'name="version" value="([^"]*)"', html).group(1)
        return valeur, langue and langue.group(1), version

    def valeur(self):
        return Reponse.objects.get(pk=self.r.pk).valeur

    def test_panneau_ouvert_en_francais_enregistre_apres_passage_a_l_anglais(self):
        self.langue_session("fr")
        valeur, langue, version = self.panneau()
        self.assertEqual((valeur, langue), ("2,125", "fr"))
        self.langue_session("en")  # autre onglet, ou Mon compte
        for auto in ("", "1"):  # « Enregistrer le brouillon », puis l'enregistrement automatique
            with self.subTest(auto=auto):
                rep = self.client.post(self.url, {"action": "enregistrer", "valeur": valeur, "langue_saisie": langue,
                                                  "version": S.version(Reponse.objects.get(pk=self.r.pk)), "commentaire": "",
                                                  "auto": auto}, HTTP_X_REQUESTED_WITH="fetch")
                self.assertLess(rep.status_code, 400)
                self.assertEqual(self.valeur(), D("2.125"))
        self.assertEqual(version, S.version(self.r))  # rien n'a changé : pas de nouvelle version

    def test_nombre_tape_dans_la_langue_du_formulaire(self):
        self.langue_session("en")
        self.client.post(self.url, {"action": "enregistrer", "valeur": "3,5", "langue_saisie": "fr",
                                    "version": S.version(self.r), "commentaire": ""})
        self.assertEqual(self.valeur(), D("3.5"))
        self.langue_session("fr")
        self.client.post(self.url, {"action": "enregistrer", "valeur": "1,234", "langue_saisie": "en",
                                    "version": S.version(Reponse.objects.get(pk=self.r.pk)), "commentaire": ""})
        self.assertEqual(self.valeur(), D("1234"))  # affiché en anglais : virgule des milliers

    def test_sans_langue_ou_langue_inconnue_langue_courante(self):
        self.langue_session("en")
        for langue in (None, "xx", ""):
            with self.subTest(langue=langue):
                donnees = {"action": "enregistrer", "valeur": "4,125", "version": S.version(Reponse.objects.get(pk=self.r.pk)),
                           "commentaire": ""}
                if langue is not None:
                    donnees["langue_saisie"] = langue
                self.client.post(self.url, donnees)
                self.assertEqual(self.valeur(), D("4125"))
                Reponse.objects.filter(pk=self.r.pk).update(valeur=D("2.125"))

    def test_formulaire_de_forcage_porte_sa_langue(self):
        self.client.force_login(self.admin)
        self.langue_session("fr")
        url = reverse("collecte:cellule", args=[self.c.pk, self.calc.pk, self.e1.pk])
        html = self.client.get(url).content.decode()
        forcage = html[html.index('name="valeur_forcee"') - 600:html.index('name="valeur_forcee"')]
        self.assertIn('name="langue_saisie" value="fr"', forcage)

    def test_tableau_et_requete_hors_formulaire(self):
        requete = RequestFactory().post("/", {"langue_saisie": "fr"})
        with L.activer_interface("en"):
            self.assertEqual(TB._nombre("2,125"), D("2125"))  # hors requête : langue courante
            with L.formulaire(requete):
                self.assertEqual(L.saisie(), "fr")
                self.assertEqual(TB._nombre("2,125"), D("2.125"))
                self.assertEqual(S.lire_nombre("2,125", self.eff), D("2.125"))
            with L.formulaire(RequestFactory().get("/", {"langue_saisie": "fr"})):  # jamais lu d'un GET
                self.assertEqual(L.saisie(), "en")
