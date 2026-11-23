{# référentiel : fiche à ouvrir, contenu d’un référentiel (éditeur), ordre des modèles d’import / export #}
  const liste = document.getElementById("liste");
  if (liste?.dataset.ouvrir) ouvrirPanneau(liste.dataset.ouvrir);

  // ---------------------------------------------------------------- contenu d'un référentiel (éditeur)
  // Thèmes et KPI du référentiel : glisser pour ranger (KPI et thèmes), renommer un thème sur place, sous-thèmes, actions en
  // lot sur les KPI cochés ; tiroir « Ajouter depuis… » (autres référentiels, modèles, catalogue) à glisser ou avec « + ».
  // Chaque action part en JSON et renvoie le contenu à jour.
  const ed = document.querySelector("[data-editeur]");
  if (ed) {
    const contenu = () => document.getElementById("contenu-referentiel");
    const replies = new Set();
    let glisse = null;
    const envoyer = async (corps, { sansMessage = false } = {}) => {
      const rep = await fetch(ed.dataset.url, { method: "POST", headers: entetes(true), body: JSON.stringify(corps) });
      const res = await rep.json().catch(() => ({ message: lib("saisie.js.erreur_enregistrement") }));
      // le serveur demande une confirmation (réponses déjà saisies) : rien n'est écrit tant qu'on n'a pas confirmé
      if (res.confirmer) return (await confirmer(res.confirmer)) ? envoyer({ ...corps, confirmer: true }, { sansMessage }) : res;
      if (!(sansMessage && res.html)) toast(res.message, (res.message || "").includes("Attention") ? 12000 : undefined);
      if (res.html) { contenu().innerHTML = res.html; apresRendu(); }
      return res;
    };
    const replier = (s, ferme) => {
      s.classList.toggle("replie", ferme);
      s.querySelector(":scope > .tete-theme .replier-theme")?.setAttribute("aria-expanded", ferme ? "false" : "true");
    };
    const coches = () => [...contenu().querySelectorAll("[data-coche]:checked")].map((c) => c.value);
    const majLot = () => {
      const barre = contenu().querySelector("[data-barre-lot]");
      if (!barre) return;
      const n = coches().length;
      barre.hidden = !n;
      barre.querySelector("[data-nb-coches]").textContent = n;
      const texte = barre.querySelector("[data-nb-coches-texte]");
      if (texte) texte.textContent = lib("saisie.js.kpi_coches", { n });
      majChoixDepuis(barre);
    };
    // « Demandé depuis » : un choix qui ferait sortir un KPI coché d'une période close, ou qui a des valeurs, est grisé
    // avec sa raison (la liste vient de la ligne : data-depuis-refus ; le serveur refuse de toute façon l'action)
    const majChoixDepuis = (barre) => {
      const choix = barre.querySelector("[data-lot-depuis]");
      if (!choix) return;
      const refus = new Set();
      contenu().querySelectorAll("[data-coche]:checked").forEach((c) => {
        (c.closest("tr[data-element]")?.dataset.depuisRefus || "").split(" ").forEach((v) => { if (v && v !== "-") refus.add(v === "_" ? "" : v); });
      });
      [...choix.options].forEach((o) => {
        if (o.dataset.base === undefined) o.dataset.base = o.textContent;
        const non = refus.has(o.value);
        o.disabled = non;
        o.textContent = non ? (choix.dataset.indisponible || "{libelle}").replace("{libelle}", o.dataset.base) : o.dataset.base;
      });
      if (choix.selectedOptions[0]?.disabled) choix.value = ([...choix.options].find((o) => !o.disabled) || choix.options[0]).value;
    };
    const filtrer = () => {
      const q = (ed.querySelector("[data-filtre-contenu]")?.value || "").trim().toLowerCase();
      contenu().querySelectorAll("tr[data-element]").forEach((tr) => { tr.hidden = !!q && !tr.dataset.texte.includes(q); });
      [...contenu().querySelectorAll(".bloc-theme")].reverse().forEach((s) => {
        s.hidden = !!q && !s.dataset.texte.includes(q) && !s.querySelector("tr[data-element]:not([hidden]), .bloc-theme:not([hidden])");
      });
      // sous la barre (DESIGN.md, « Filters ») : « 3 résultats sur 120 » et « Effacer les filtres » quand la recherche est remplie
      const lignes = contenu().querySelectorAll("tr[data-element]");
      majEtatFiltres([...lignes].filter((tr) => !tr.hidden).length, lignes.length);
    };
    function apresRendu() {
      // tiroir : les KPI déjà dans le référentiel sont grisés
      const presents = new Set((contenu().querySelector("[data-presents]")?.dataset.presents || "").split(" "));
      ed.querySelectorAll(".tiroir-ajout .puce-kpi[data-code]").forEach((p) => {
        const deja = presents.has(p.dataset.code);
        p.classList.toggle("deja", deja);
        const marque = ` (${lib("saisie.js.deja_dans_referentiel")})`;
        p.title = (p.title.endsWith(marque) ? p.title.slice(0, -marque.length) : p.title) + (deja ? marque : "");
      });
      replies.forEach((id) => { const s = contenu().querySelector(`.bloc-theme[data-zone="${id}"]`); if (s) replier(s, true); });
      majLot();
      filtrer();
      const source = contenu().querySelector("[data-lot-theme]");  // thèmes à jour : liste du « + » du tiroir
      const cible = ed.querySelector("[data-cible-ajout]");
      if (source && cible) {
        const v = cible.value;
        cible.innerHTML = `<option value="">${echapper(lib("saisie.js.premier_niveau"))}</option>` + [...source.options].filter((o) => o.value).map((o) => o.outerHTML).join("");
        cible.value = [...cible.options].some((o) => o.value === v) ? v : "";
      }
    }
    // après la fermeture d'une fiche KPI, le contenu est rechargé (data-rafraichir) : garder les thèmes repliés
    apresRendu();
    new MutationObserver(apresRendu).observe(ed.querySelector(".colonne-contenu"), { childList: true });

    // monter ou descendre une ligne KPI d'un cran dans son thème (Alt + flèche, ou boutons ▲ ▼ sur téléphone et tablette)
    const ranger = async (tr, haut, annulable = true) => {
      const lignes = [...tr.parentElement.children].filter((l) => l.matches("tr[data-element]") && !l.hidden);
      const i = lignes.indexOf(tr), j = haut ? i - 1 : i + 1;
      if (j < 0 || j >= lignes.length) return false;
      const code = tr.dataset.element;
      const nom = (tr.querySelector("td.nom")?.firstChild?.textContent || "").trim() || code;
      const avant = haut ? lignes[j].dataset.element : (lignes[j + 1]?.dataset.element || "");
      const res = await envoyer({ action: "deposer", theme: tr.closest("[data-zone]").dataset.zone, source: { type: "element", code }, avant },
        { sansMessage: annulable });
      // déplacement sans question : un message visible, avec « Annuler » (l'inverse du déplacement), comme les suppressions
      if (annulable && res.html) {
        proposerAnnulation({ texte: lib(haut ? "referentiels.js.monte" : "referentiels.js.descendu", { nom }), bouton: lib("commun.defaire") }, () => {
          const ligne = contenu().querySelector(`tr[data-element="${CSS.escape(code)}"]`);
          if (ligne) ranger(ligne, !haut, false).then(() => contenu().querySelector(`tr[data-element="${CSS.escape(code)}"]`)?.focus());
          return null;
        }, tr);
      }
      return true;
    };

    const saisirNom = (avant, libelle, valeur, valider) => {
      ed.querySelector(".saisie-nom")?.remove();
      const f = document.createElement("form");
      f.className = "saisie-nom";
      f.innerHTML = `<input type="text" maxlength="150" required aria-label="${echapper(libelle)}" placeholder="${echapper(libelle)}"><button type="submit">${echapper(lib("saisie.js.ok"))}</button><button type="button" class="lien">${echapper(lib("commun.annuler"))}</button>`;
      const champ = f.querySelector("input");
      champ.value = valeur || "";
      avant.parentNode.insertBefore(f, avant);
      champ.focus();
      champ.select();
      const fermer = () => f.remove();
      f.querySelector("button.lien").addEventListener("click", fermer);
      champ.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.stopPropagation(); fermer(); } });
      f.addEventListener("submit", (e) => { e.preventDefault(); const nom = champ.value.trim(); fermer(); if (nom && nom !== valeur) valider(nom); });
      return f;
    };

    ed.addEventListener("click", (e) => {
      const b = e.target.closest("button");
      if (!b || !ed.contains(b)) return;
      const d = b.dataset;
      if (b.matches(".replier-theme")) {
        const s = b.closest(".bloc-theme");
        const ferme = !s.classList.contains("replie");
        replier(s, ferme);
        if (ferme) replies.add(s.dataset.zone); else replies.delete(s.dataset.zone);
      } else if (b.matches("[data-tout-replier], [data-tout-deplier]")) {  // tous les thèmes d'un coup (état gardé dans « replies »)
        const ferme = b.matches("[data-tout-replier]");
        contenu().querySelectorAll(".bloc-theme").forEach((s) => {
          replier(s, ferme);
          if (ferme) replies.add(s.dataset.zone); else replies.delete(s.dataset.zone);
        });
      } else if (d.renommer) {
        const nom = contenu().querySelector(`.nom-theme[data-renommer="${d.renommer}"]`);
        b.closest("details")?.removeAttribute("open");
        saisirNom(nom, lib("saisie.js.nom_theme"), nom.textContent.trim(), (n) => envoyer({ action: "theme_renommer", id: d.renommer, nom: n }));
      } else if (d.sousTheme) {
        const corps = b.closest(".bloc-theme").querySelector(":scope > .corps-theme");
        if (b.closest(".bloc-theme").classList.contains("replie")) replier(b.closest(".bloc-theme"), false);
        saisirNom(corps.firstElementChild || corps.appendChild(document.createElement("span")), lib("saisie.js.nom_sous_theme"), "",
          (n) => envoyer({ action: "theme_ajouter", parent: d.sousTheme, nom: n }));
      } else if (b.matches("[data-nouveau-theme]")) {
        saisirNom(contenu().querySelector("[data-nouveau-ici]"), lib("saisie.js.nom_nouveau_theme"), "", (n) => envoyer({ action: "theme_ajouter", nom: n }));
      } else if (d.themeAction) {
        confirmer(d.confirmer, b).then((oui) => { if (oui) envoyer({ action: d.themeAction, id: d.id }); });
      } else if (d.retirer) {
        // état « occupé » le temps de la réponse (la ligne disparaît ensuite) ; rendu au bouton en cas d'échec
        b.disabled = true;
        b.setAttribute("aria-busy", "true");
        envoyer({ action: "lot", operation: "retirer", codes: [d.retirer] })
          .finally(() => { b.disabled = false; b.removeAttribute("aria-busy"); });
      } else if (d.ranger) {
        const tr = b.closest("tr[data-element]"), code = tr.dataset.element;
        ranger(tr, d.ranger === "haut").then((fait) => {
          if (!fait) { toast(lib(d.ranger === "haut" ? "saisie.js.deja_en_tete" : "saisie.js.deja_en_fin")); return; }
          contenu().querySelector(`tr[data-element="${CSS.escape(code)}"] [data-ranger="${d.ranger}"]`)?.focus();
        });
      } else if (d.lot) {
        confirmer(d.confirmer, b).then((oui) => {
          if (oui) envoyer({ action: "lot", operation: d.lot, codes: coches(), theme: contenu().querySelector("[data-lot-theme]").value,
            niveau: contenu().querySelector("[data-lot-niveau]")?.value, depuis: contenu().querySelector("[data-lot-depuis]")?.value });
        });
      } else if (d.depuisLigne) {
        // « Demandé depuis » d'une ligne : seule cette ligne cochée, le choix de la barre d'actions reçoit le focus
        contenu().querySelectorAll("[data-coche]").forEach((c) => { c.checked = c.value === d.depuisLigne; });
        majLot();
        contenu().querySelector("[data-lot-depuis]")?.focus();
      } else if (b.matches("[data-lot-annuler]")) {
        contenu().querySelectorAll("[data-coche]:checked").forEach((c) => { c.checked = false; });
        majLot();
      } else if (b.matches("[data-ajouter]")) {
        e.preventDefault();
        const s = b.closest("[data-glisser]").dataset;
        envoyer({ action: "deposer", theme: ed.querySelector("[data-cible-ajout]").value,
          source: { type: s.glisser, ref: s.ref, bib: s.bib, id: s.id, code: s.code } });
      } else if (b.matches("[data-ouvrir-tiroir]")) {
        if (ed.classList.contains("tiroir-ouvert")) fermerTiroir(); else ouvrirTiroir();
      } else if (b.matches("[data-fermer-tiroir]")) {
        fermerTiroir();
      }
    });
    // tiroir « Ajouter depuis… » : le focus va dans le tiroir à l'ouverture et revient au bouton à la fermeture ;
    // Échap le ferme (plein écran sur téléphone et tablette, sinon rien ne se voit après le toucher)
    function ouvrirTiroir() {
      ed.classList.add("tiroir-ouvert");
      ed.querySelector("[data-ouvrir-tiroir]").setAttribute("aria-expanded", "true");
      (ed.querySelector(".tiroir-ajout input[type=search]") || ed.querySelector(".tiroir-ajout select"))?.focus();
    }
    function fermerTiroir() {
      ed.classList.remove("tiroir-ouvert");
      const bouton = ed.querySelector("[data-ouvrir-tiroir]");
      bouton.setAttribute("aria-expanded", "false");
      bouton.focus();
    }
    ed.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && ed.classList.contains("tiroir-ouvert")) { e.preventDefault(); fermerTiroir(); }
    });
    ed.addEventListener("change", (e) => {
      if (e.target.matches("[data-coche]")) majLot();
      if (e.target.matches("[data-theme-parent]") && e.target.value) {
        envoyer({ action: "theme_deplacer", id: e.target.dataset.themeParent, parent: e.target.value === "racine" ? "" : e.target.value });
      }
    });
    // au clavier (et sans glisser) : Alt + flèche haut / bas sur une ligne KPI la monte ou la descend dans son thème
    ed.addEventListener("keydown", async (e) => {
      if (!e.altKey || (e.key !== "ArrowUp" && e.key !== "ArrowDown")) return;
      const tr = e.target.matches?.("tr[data-element]") ? e.target : null;
      if (!tr) return;
      e.preventDefault();
      const code = tr.dataset.element;
      if (await ranger(tr, e.key === "ArrowUp")) contenu().querySelector(`tr[data-element="${CSS.escape(code)}"]`)?.focus();
    });
    ed.querySelector("[data-filtre-contenu]")?.addEventListener("input", filtrer);
    // « Effacer les filtres » : la barre est vidée par le script commun (05_filtres.js, au niveau du document, après ce
    // gestionnaire) ; puis la liste est refiltrée et le focus revient dans la recherche
    ed.addEventListener("click", (e) => {
      if (!e.target.closest("[data-reinitialiser-filtres]")) return;
      setTimeout(() => { filtrer(); ed.querySelector("[data-filtre-contenu]")?.focus({ preventScroll: true }); });
    });
    ed.querySelector("[data-filtre-bibliotheque]")?.addEventListener("input", (e) => {
      const q = e.target.value.trim().toLowerCase();
      ed.querySelectorAll(".tiroir-ajout [data-texte]").forEach((el) => { el.hidden = !!q && !el.dataset.texte.includes(q); });
      ed.querySelectorAll(".tiroir-ajout details").forEach((d) => { if (q) d.open = !!d.querySelector("[data-texte]:not([hidden])"); });
    });

    // glisser-déposer : KPI (lignes), thèmes (en-têtes), éléments du tiroir
    const nettoyer = () => ed.querySelectorAll(".survol, .survol-avant").forEach((z) => z.classList.remove("survol", "survol-avant"));
    ed.addEventListener("dragstart", (e) => {
      const ligne = e.target.closest?.("tr[data-element]");
      const tete = e.target.closest?.(".tete-theme[data-theme]");
      const src = e.target.closest?.("[data-glisser]");
      if (ligne) glisse = { el: ligne, source: { type: "element", code: ligne.dataset.element } };
      else if (tete) glisse = { el: tete.closest(".bloc-theme"), theme: tete.dataset.theme };
      else if (src) { const s = src.dataset; glisse = { el: src, source: { type: s.glisser, ref: s.ref, bib: s.bib, id: s.id, code: s.code } }; }
      else return;
      glisse.el.classList.add("glisse");
      e.dataTransfer.effectAllowed = "copyMove";
      e.dataTransfer.setData("text/plain", glisse.theme || glisse.source.code || glisse.source.id || "");
    });
    // l'élément glissé reprend son aspect normal, même après un dépôt (glisse est déjà vidé par « drop »)
    ed.addEventListener("dragend", () => { ed.querySelectorAll(".glisse").forEach((x) => x.classList.remove("glisse")); glisse = null; nettoyer(); });
    const depot = (e) => {
      const zone = e.target.closest?.("#contenu-referentiel [data-zone]");
      if (!zone || !glisse) return null;
      if (glisse.theme) {
        if (glisse.el.contains(zone)) return null;  // un thème ne va pas dans lui-même
        const tete = e.target.closest(".tete-theme[data-theme]");
        return tete ? { zone, avantTheme: tete.dataset.theme, marque: tete } : { zone, marque: zone };
      }
      const tr = e.target.closest("tr[data-element]");
      const avant = tr && tr.dataset.element !== glisse.source.code && glisse.source.type !== "theme" ? tr.dataset.element : null;
      return { zone, avantKpi: avant, marque: avant ? tr : zone };
    };
    ed.addEventListener("dragover", (e) => {
      const c = depot(e);
      if (!c) return;
      e.preventDefault();
      nettoyer();
      c.marque.classList.add(c.avantTheme || c.avantKpi ? "survol-avant" : "survol");
    });
    ed.addEventListener("drop", (e) => {
      const c = depot(e);
      if (!c) return;
      e.preventDefault();
      nettoyer();
      const g = glisse;
      glisse = null;
      if (g.theme) {
        envoyer(c.avantTheme ? { action: "theme_deplacer", id: g.theme, avant: c.avantTheme }
          : { action: "theme_deplacer", id: g.theme, parent: c.zone.dataset.zone });
      } else {
        envoyer({ action: "deposer", theme: c.zone.dataset.zone, source: g.source, ...(c.avantKpi ? { avant: c.avantKpi } : {}) });
      }
    });
  }

  // Aperçu d'un paquet : « Renommer » fait apparaître le champ du nouveau code
  document.addEventListener("change", (e) => {
    if (!e.target.matches("[data-choix-kpi]")) return;
    const code = e.target.closest("td")?.querySelector(".nouveau-code");
    if (code) code.hidden = e.target.value !== "renommer";
  });

  // ---------------------------------------------------------------- import / export : ordre des modèles
  const listeModeles = document.querySelector("[data-ordre-modeles]");
  if (listeModeles) {
    let glisse = null;
    listeModeles.addEventListener("dragstart", (e) => {
      glisse = e.target.closest(".ligne-export[draggable]");
      if (!glisse) return;
      glisse.classList.add("glisse");
      e.dataTransfer.effectAllowed = "move";
    });
    listeModeles.addEventListener("dragover", (e) => {
      const cible = e.target.closest(".ligne-export[draggable]");
      if (!glisse || !cible || cible === glisse) return;
      e.preventDefault();
      const r = cible.getBoundingClientRect();
      listeModeles.insertBefore(glisse, e.clientY < r.top + r.height / 2 ? cible : cible.nextSibling);
    });
    async function enregistrerOrdre() {
      const ids = [...listeModeles.querySelectorAll(".ligne-export[data-id]")].map((m) => m.dataset.id);
      const rep = await fetch(listeModeles.dataset.ordreModeles, { method: "POST", headers: entetes(true), body: JSON.stringify({ ids }) });
      if (rep.ok) toast((await rep.json()).message); else erreur(lib("saisie.js.ordre_non_enregistre"));
    }
    // « Monter » de la première ligne et « Descendre » de la dernière : visibles mais inactifs (les boutons ne bougent pas)
    const bornerOrdre = () => {
      const lignes = [...listeModeles.querySelectorAll(".ligne-export")];
      lignes.forEach((l, i) => {
        l.querySelector("[data-monter]")?.setAttribute("aria-disabled", String(i === 0));
        l.querySelector("[data-descendre]")?.setAttribute("aria-disabled", String(i === lignes.length - 1));
      });
    };
    bornerOrdre();
    listeModeles.addEventListener("dragend", () => {
      if (!glisse) return;
      glisse.classList.remove("glisse");
      glisse = null;
      bornerOrdre();
      enregistrerOrdre();
    });
    listeModeles.addEventListener("click", (e) => {  // au clavier : Monter / Descendre, le focus reste sur le bouton
      const b = e.target.closest("[data-monter], [data-descendre]");
      if (!b) return;
      const ligne = b.closest(".ligne-export"), voisin = b.hasAttribute("data-monter") ? ligne.previousElementSibling : ligne.nextElementSibling;
      if (!voisin) return;
      if (b.hasAttribute("data-monter")) listeModeles.insertBefore(ligne, voisin);
      else listeModeles.insertBefore(voisin, ligne);
      b.focus();
      bornerOrdre();
      enregistrerOrdre();
    });
  }

  // fiche d'un nouveau KPI : « L'ajouter aussi aux exercices précédents ? » suit le référentiel choisi
  document.addEventListener("change", (e) => {
    if (!e.target.matches?.("select[name='ajout_place']")) return;
    const ref = (e.target.value || "").split("|")[0];
    const fiche = e.target.closest("form") || document;
    fiche.querySelectorAll("[data-depuis-ref]").forEach((l) => {
      const visible = l.dataset.depuisRef === ref;
      l.hidden = !visible;
      l.querySelector("select").disabled = !visible;
    });
    const aide = fiche.querySelector("[data-depuis-aide]");
    if (aide) aide.hidden = ![...fiche.querySelectorAll("[data-depuis-ref]")].some((l) => !l.hidden);
  });

