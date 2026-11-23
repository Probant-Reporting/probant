"""Paramètres › Niveaux et Unités : les noms s'affichent dans la langue de l'interface de la personne (mécanisme des
traductions, repli sur la langue de référence), les champs de saisie gardent la langue de référence et le disent, et la
traduction est montrée à côté ; le catalogue d'unités propose et installe des symboles dans chaque langue."""
import re

from django.test import TestCase
from django.urls import reverse

from parametres import catalogue_unites as CU
from parametres.models import Langue, NiveauHierarchique, Unite
from referentiel.models import Niveau, Organisation, Utilisateur

URL_UNITES = reverse("parametres:referentiel")
URL_NIVEAUX = reverse("parametres:niveaux")
MOTS_FRANCAIS_NIVEAUX = ("Groupe", "Pays", "Filiale", "Entité")


def texte_visible(html):
    """Texte des pages sans les balises ni leurs attributs : ni les valeurs des champs ni les adresses n'y figurent."""
    html = re.sub(r"<(script|style)\b.*?</\1>", " ", html, flags=re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


class Base(TestCase):
    def setUp(self):
        for code, nom in (("es", "Español"), ("de", "Deutsch"), ("it", "Italiano")):  # langues des contenus (Paramètres › Langues)
            Langue.objects.get_or_create(code=code, defaults={"libelle": nom, "ordre": 9})
        self.g = Organisation.objects.create(nom="Alfa", niveau_id=Niveau.GROUP)
        self.p = Organisation.objects.create(nom="Beta", niveau_id=Niveau.COUNTRY, parent=self.g)
        self.admin = Utilisateur.objects.create(username="admin", email="admin@exemple.test", role=Utilisateur.Role.ADMIN)

    def page(self, url, langue):
        self.admin.langue = langue
        self.admin.save()
        self.client.logout()  # la langue choisie est gardée dans la session
        self.client.force_login(self.admin)
        rep = self.client.get(url)
        self.assertEqual(rep.status_code, 200)
        return rep.content.decode()


class NiveauxDansLaLangueDeLInterfaceTests(Base):
    def test_espagnol_pastilles_options_et_apercu_traduits(self):
        page = self.page(URL_NIVEAUX, "es")
        texte = texte_visible(page)
        for mot in ("Grupo", "País", "Entidad", "Centro"):
            self.assertIn(mot, texte)
        for mot in MOTS_FRANCAIS_NIVEAUX:
            self.assertNotRegex(texte, rf"\b{mot}\b", f"{mot} en clair dans la page espagnole")
        self.assertIn("«Centro»", texte)  # position proposée pour un nouveau niveau

    def test_les_champs_gardent_la_langue_de_reference_et_le_disent(self):
        page = self.page(URL_NIVEAUX, "es")
        self.assertIn('name="nom_Group" value="Groupe"', page)  # ce qui est enregistré ne change pas
        self.assertIn("Idioma de referencia: Français", texte_visible(page))
        self.assertIn("Nombre (idioma de referencia: Français)", texte_visible(page))  # étiquette du champ de l'ajout
        self.assertIn("Español: Grupo · Grupo", texte_visible(page))  # traduction montrée à côté
        self.assertIn("Español: País · Países", texte_visible(page))

    def test_langue_de_reference_sans_suffixe_ni_ligne_de_traduction(self):
        page = self.page(URL_NIVEAUX, "fr")
        self.assertNotIn("Langue de référence", texte_visible(page))
        self.assertNotIn("Français :", texte_visible(page))
        self.assertIn("Groupe", texte_visible(page))

    def test_allemand_majuscules_des_noms(self):
        texte = texte_visible(self.page(URL_NIVEAUX, "de"))
        for mot in ("Konzern", "Land", "Gesellschaft", "Standort"):
            self.assertIn(mot, texte)
        self.assertIn("Deutsch: Konzern · Konzern", texte)
        self.assertIn("Referenzsprache: Français", texte)

    def test_une_traduction_manquante_est_dite_et_ne_montre_pas_la_langue_de_reference(self):
        NiveauHierarchique.objects.filter(code="Group").update(traductions={})
        texte = texte_visible(self.page(URL_NIVEAUX, "es"))
        self.assertIn("Español: aún sin traducir", texte)
        self.assertIn("Groupe", texte)  # repli : la pastille montre alors la langue de référence

    def test_message_de_suppression_dans_la_langue_de_l_interface(self):
        NiveauHierarchique.objects.filter(code="Entity").delete()
        Organisation.objects.exclude(niveau_id__in=("Group", "Country")).delete()
        NiveauHierarchique.objects.create(code="Vide", rang=9, nom="Vide", nom_pluriel="Vides", couleur="#112233",
                                          couleur_fond="#EEEEEE", couleur_texte="#112233", couleur_pale="#FAFAFA",
                                          traductions={"es": {"nom": "Vacío"}})
        self.admin.langue = "es"
        self.admin.save()
        self.client.force_login(self.admin)
        self.client.post(URL_NIVEAUX, {"action": "supprimer", "supprimer": "Vide"})
        rep = self.client.get(URL_NIVEAUX)
        self.assertIn("Vacío", " ".join(str(m) for m in rep.context["messages"]))


class UnitesDansLaLangueDeLInterfaceTests(Base):
    def test_apercu_et_resumes_dans_la_langue_de_l_interface(self):
        Unite.objects.update_or_create(code="kWh", defaults=dict(symbole="kWh", libelle="kilowattheure", famille="Énergie", ordre=0,
                                                                 traductions={"es": {"libelle": "kilovatio hora"}}))
        page = self.page(URL_UNITES, "es")
        self.assertIn('data-ap-nom>kilovatio hora<', page)
        self.assertNotIn(">kilowattheure<", page)
        self.assertIn('name="libelle__0" value="kilowattheure"', page)  # la saisie garde la langue de référence
        self.assertIn('data-nom-ecran="kilovatio hora"', page)  # le script montre la même chose dans l'aperçu
        texte = texte_visible(page)
        self.assertIn("Idioma de referencia: Français", texte)
        self.assertIn("Español: kilovatio hora", texte)

    def test_catalogue_propose_les_symboles_en_toutes_lettres_dans_la_langue(self):
        for langue, voulus, absents in (("es", ("semanas", "meses", "años"), ("semaines", "mois", "années")),
                                        ("de", ("Wochen", "Monate", "Jahre"), ("semaines", "mois", "années")),
                                        ("it", ("settimane", "mesi", "anni"), ("semaines", "mois", "années"))):
            with self.subTest(langue=langue):
                page = self.page(URL_UNITES + "?section=unites", langue)
                symboles = re.findall(r"<strong>([^<]*)</strong><span>", page)  # puces du catalogue
                for v in voulus:
                    self.assertIn(v, symboles)
                for a in absents:
                    self.assertNotIn(a, symboles)
                self.assertIn('value="Durée|semaines"', page)  # valeur cochée : celle du catalogue

    def test_installation_depuis_le_catalogue_ajoute_les_traductions_de_depart(self):
        self.client.force_login(self.admin)
        self.client.post(URL_UNITES, {"action": "ajouter_catalogue", "catalogue": ["Durée|semaines", "Énergie|TWh"]})
        semaines, twh = Unite.objects.get(symbole="semaines"), Unite.objects.get(symbole="TWh")
        self.assertEqual((semaines.symbole, semaines.libelle), ("semaines", "semaines"))  # enregistré : le catalogue
        for langue, mot in (("en", "weeks"), ("es", "semanas"), ("de", "Wochen"), ("it", "settimane"), ("nl", "weken"),
                            ("pt", "semanas")):
            self.assertEqual(semaines.tr("symbole", langue), mot)
            self.assertEqual(semaines.tr("libelle", langue), mot)
        self.assertEqual(twh.tr("libelle", "de"), "Terawattstunde")
        self.assertEqual(twh.tr("symbole", "de"), "TWh")  # un symbole qui n'est pas un mot n'a pas de traduction
        self.assertNotIn("symbole", twh.traductions["de"])

    def test_chaque_symbole_traduit_existe_dans_le_catalogue_et_dans_les_sept_langues(self):
        from parametres import libelles as LB

        symboles = {s for _, _, unites in CU.THEMES for s, *_ in unites}
        self.assertLessEqual(set(CU.SYMBOLES_TRADUITS), symboles)
        for langue in ("en", "fr", "es", "de", "it", "nl", "pt"):
            for s in CU.SYMBOLES_TRADUITS:
                self.assertTrue(LB.table(langue).get(f"{CU.PREFIXE}.symbole.{CU.cle(s)}"), (langue, s))
