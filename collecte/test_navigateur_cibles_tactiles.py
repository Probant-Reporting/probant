"""Navigateur (Chromium) : cibles tactiles (DESIGN.md « Touch targets ») : toute cible cliquable (lien, bouton,
case à cocher, bouton radio, résumé) a une zone d'au moins 24 × 24 px, sur ordinateur (1 440 px) comme sur téléphone (390 px).

- La zone d'une case à cocher ou d'un bouton radio est celle de son libellé (``label``) ou, dans la grille de saisie, celle de la
  cellule (``td.choix`` : un clic dessus coche la case) ; le dessin de la case peut rester plus petit.
- Les liens au milieu d'une phrase sont exemptés, comme le veut le critère 2.5.8 des WCAG 2.2.
- Pages relevées : celles où des cibles de 18 à 22 px avaient été trouvées (Cohérence, Attributions, Relances, Import, choix
  des colonnes, référentiels, Hébergement, Visualisation…), avec le jeu d'essai des tests du navigateur."""
from referentiel.models import Attribution, Utilisateur

from .aides_tests.navigateur import NavigateurBase, _hors_boucle

PAGES = ["/saisie/", "/pour-moi/", "/tableau-de-bord/", "/tableau-de-bord/consolidation/", "/tableau-de-bord/relances/",
         "/visualisation/", "/coherence/", "/coherence/regles/", "/administration/attributions/", "/import-export/",
         "/import-export/exporter/", "/import-export/importer/", "/import-export/listes-kpi/", "/import-export/formats-officiels/",
         "/administration/referentiels/", "/administration/referentiels/modeles/", "/administration/parametres/hebergement/",
         "/administration/parametres/", "/administration/parametres/niveaux/", "/administration/parametres/langues/",
         "/administration/comptes/", "/administration/organisations/", "/administration/campagnes/", "/administration/",
         "/administration/fichiers/", "/mon-compte/", "/referentiel/", "/referentiel/kpi/nouveau/", "/administration/espaces/"]

MESURE = """() => {
  const visible = (e) => { const s = getComputedStyle(e), r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const selecteur = 'a[href], button, input:not([type=hidden]), select, textarea, summary, [role=button], [role=tab], [role=menuitem]';
  const zone = (e) => {
    let r = e.getBoundingClientRect();
    if (e.matches('input[type=checkbox], input[type=radio]')) {
      const l = e.closest('td.choix, th.choix') || e.closest('label') || (e.id && document.querySelector('label[for="' + CSS.escape(e.id) + '"]'));
      if (l && visible(l)) { const q = l.getBoundingClientRect(); return {w: Math.max(r.right, q.right) - Math.min(r.left, q.left), h: Math.max(r.bottom, q.bottom) - Math.min(r.top, q.top)}; }
    }
    return {w: r.width, h: r.height};
  };
  const dansUnePhrase = (e) => {
    if (!e.matches('a') || getComputedStyle(e).display !== 'inline') return false;
    const p = e.parentElement;
    return !!p && !p.closest('nav, thead, [role=tablist]') && [...p.childNodes].some(n => n.nodeType === 3 && n.textContent.trim().length > 3);
  };
  const trop_petites = [];
  for (const e of document.querySelectorAll(selecteur)) {
    if (!visible(e) || e.closest('[hidden], [inert]') || e.disabled || e.matches('.visually-hidden, .visuellement-cache, .evitement')) continue;
    const z = zone(e);
    if (z.w + 0.5 >= 24 && z.h + 0.5 >= 24) continue;
    if (dansUnePhrase(e)) continue;
    trop_petites.push(e.tagName.toLowerCase() + (e.type ? '[' + e.type + ']' : '') + '.' + String(e.className).trim().split(/\\s+/).slice(0, 2).join('.') + ' "' +
      (e.getAttribute('aria-label') || e.textContent || e.value || '').trim().slice(0, 25) + '" ' + Math.round(z.w) + 'x' + Math.round(z.h));
  }
  return trop_petites;
}"""


class CiblesTactilesNavigateurTests(NavigateurBase):
    def setUp(self):
        super().setUp()
        with _hors_boucle():
            contrib = Utilisateur.objects.create(username="contrib", email="contrib@exemple.test")
            for o in (self.e1, self.e2):
                Attribution.objects.create(kpi=self.eff, organisation=o, utilisateur=contrib)

    def _mesurer(self, largeur):
        page = self.page(largeur=largeur, hauteur=900, tactile=largeur < 500)
        trouvees = {}
        for chemin in PAGES:
            rep = page.goto(self.live_server_url + chemin)
            page.wait_for_load_state("networkidle")
            if rep.status != 200:
                continue
            petites = page.evaluate(MESURE)
            if petites:
                trouvees[chemin] = petites[:6]
        self.assertEqual(page.erreurs, [])
        return trouvees

    def test_cibles_d_au_moins_24_px_sur_ordinateur(self):
        self.assertEqual(self._mesurer(1440), {}, "cibles de moins de 24 px sur ordinateur")

    def test_cibles_d_au_moins_24_px_sur_telephone(self):
        self.assertEqual(self._mesurer(390), {}, "cibles de moins de 24 px sur téléphone")

    def test_hebergement_sans_champ_qui_depasse_a_320_px(self):
        """Le champ « fichier de sauvegarde » de la page Hébergement dépassait de l'écran à 320 px de large."""
        page = self.page(largeur=320, hauteur=700, tactile=True)
        self.aller(page, "/administration/parametres/hebergement/")
        depasse = page.evaluate("""() => [...document.querySelectorAll('input, select, textarea, button')].filter(e => {
            const r = e.getBoundingClientRect(); return r.width > 0 && r.right > innerWidth + 1; }).map(e => e.name || e.id)""")
        self.assertEqual(depasse, [])
        self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), 320)
