"""Téléphone (390 px) : la page Relances (carte « Relancer pour », deux campagnes ouvertes) et la page Attributions en allemand
(cartes de niveau, noms longs) ne défilent pas à l'horizontale."""
import datetime

from django.utils import timezone

from parametres.models import Langue, NiveauHierarchique
from referentiel.models import KPI, Attribution, Niveau, Organisation, Referentiel, Utilisateur

from .aides_tests.navigateur import NavigateurBase, _hors_boucle
from .models import Campagne

DEBORDE = """() => {
  const w = document.documentElement.clientWidth;
  const hors = [...document.querySelectorAll('main *, .barre-filtres *')].filter(e => {
    const r = e.getBoundingClientRect();
    if (r.width <= 0 || r.right <= w + 0.5) return false;
    for (let a = e.parentElement; a && a !== document.body; a = a.parentElement) if (/auto|scroll/.test(getComputedStyle(a).overflowX)) return false;
    return true;
  }).map(e => e.tagName + '.' + e.className);
  return { defile: document.documentElement.scrollWidth > w, hors: hors.slice(0, 5) };
}"""


class DefilementTelephoneTests(NavigateurBase):
    def test_relances_avec_deux_campagnes_ouvertes(self):
        with _hors_boucle():
            Referentiel.objects.update(nom="Norme volontaire VS (anciennement VSME) – module de base et indicateurs")
            autre = Referentiel.objects.create(code="VS_COMPLET", nom="Norme volontaire VS (anciennement VSME) – module complet et indicateurs", ordre=2,
                                               couleur="#E07A1F")
            Campagne.objects.create(referentiel=autre, exercice=2026, statut=Campagne.Statut.OUVERTE,
                                    date_fin_saisie=timezone.localdate() + datetime.timedelta(days=30))
        page = self.page(self.admin, largeur=390, tactile=True)
        self.aller(page, "/tableau-de-bord/relances/")
        self.assertEqual(page.locator("form.portee-relances").count(), 1)
        self.assertEqual(page.evaluate(DEBORDE), {"defile": False, "hors": []})

    def test_attributions_en_allemand(self):
        with _hors_boucle():
            Langue.objects.get_or_create(code="de", defaults={"libelle": "Deutsch", "ordre": 4})
            self.admin.langue = "de"
            self.admin.save()
            NiveauHierarchique.objects.filter(code=Niveau.COUNTRY).update(traductions={"de": {"nom": "Land", "nom_pluriel": "Länder"}})
            NiveauHierarchique.objects.filter(code=Niveau.ENTITY).update(traductions={"de": {"nom": "Produktionsstandort", "nom_pluriel": "Produktionsstandorte"}})
            kpi = KPI.objects.get(code="EFF")  # tous les sites attribués : la carte porte son badge « vollständig »
            spoc = Utilisateur.objects.create(username="spoc", email="spoc@exemple.test")
            for o in Organisation.objects.filter(niveau_id=Niveau.ENTITY):
                Attribution.objects.create(kpi=kpi, organisation=o, utilisateur=spoc)
        page = self.page(self.admin, largeur=390, tactile=True)
        self.aller(page, "/administration/attributions/")
        self.assertGreaterEqual(page.locator(".onglet-niveau").count(), 2)
        self.assertEqual(page.evaluate(DEBORDE), {"defile": False, "hors": []})
