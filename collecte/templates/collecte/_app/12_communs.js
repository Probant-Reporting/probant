{# comportements communs : boutons d’attente, menus déroulants, traductions, cases en lot, bibliothèque, Je réponds à #}
  // bouton d'une opération longue (restauration…) : désactivé et texte d'attente à l'envoi
  document.querySelectorAll("button[data-attente]").forEach((b) => b.form && b.form.addEventListener("submit", () => {
    setTimeout(() => { b.disabled = true; b.textContent = b.dataset.attente; }, 0);
  }));
  // envoi automatique d'un formulaire dès qu'un fichier est choisi (Importer)
  document.querySelectorAll("input[type=file][data-envoi-auto]").forEach((i) => i.addEventListener("change", () => { if (i.files.length) i.form.submit(); }));
  // champ refusé qui demande le focus (Mon compte, mot de passe) : un fragment dans l'adresse (« #mot-de-passe ») fait
  // ignorer l'attribut autofocus par le navigateur ; le focus est donné ici, sans faire défiler la page
  window.addEventListener("load", () => {
    const c = document.querySelector("[autofocus][aria-invalid=true]");
    if (c && document.activeElement !== c) c.focus({ preventScroll: true });
  });
  // menus déroulants : un seul ouvert, fermé par un clic ailleurs ou Échap
  document.addEventListener("click", (e) => {
    document.querySelectorAll("details.menu-deroulant[open]").forEach((d) => { if (!d.contains(e.target)) d.open = false; });
  });
  // Échap ferme et rend le focus au bouton du menu quand il était dans le menu (ou perdu)
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    document.querySelectorAll("details.menu-deroulant[open]").forEach((d) => {
      const actif = document.activeElement;
      const dedans = d.contains(actif) || actif === document.body || !actif;
      d.open = false;
      if (dedans) d.querySelector(":scope > summary")?.focus();
    });
  });
  // menus d'actions ouverts : les flèches (et Début, Fin) passent d'un choix à l'autre, en boucle ; pas dans un menu
  // de cases à cocher (choix des thèmes), où les flèches gardent leur rôle
  document.addEventListener("keydown", (e) => {
    if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(e.key) || e.altKey || e.ctrlKey || e.metaKey) return;
    const menu = e.target.closest?.("details.menu-deroulant[open]");
    if (!menu || menu.matches(".choix-themes") || e.target.matches("input, select, textarea")) return;
    const items = [...menu.querySelectorAll(".menu-liste button:not([disabled]), .menu-liste a[href]")].filter((x) => x.offsetParent);
    if (!items.length) return;
    e.preventDefault();
    const i = items.indexOf(document.activeElement);
    const j = e.key === "Home" ? 0 : e.key === "End" ? items.length - 1
      : e.key === "ArrowDown" ? (i + 1) % items.length : (i <= 0 ? items.length - 1 : i - 1);
    items[j].focus();
  });
  // menus déroulants (« Exporter », « ⋯ » d'un thème) : sur téléphone ou au zoom 200 %, le menu est ramené dans l'écran
  document.addEventListener("toggle", (e) => {
    const d = e.target;
    if (!d.matches?.("details.menu-deroulant")) return;
    const m = d.querySelector(":scope > .menu-liste");
    if (!m) return;
    m.style.left = ""; m.style.right = "";
    if (!d.open) return;
    const r = m.getBoundingClientRect(), largeur = document.documentElement.clientWidth, marge = 8;
    const decalage = r.left < marge ? marge - r.left : (r.right > largeur - marge ? largeur - marge - r.right : 0);
    if (decalage) { const gauche = m.offsetLeft + decalage; m.style.right = "auto"; m.style.left = `${gauche}px`; }
  }, true);
  // page Traductions : hauteur des zones de texte, champs modifiés, avertissement avant de quitter sans enregistrer
  document.querySelectorAll("form[data-traductions]").forEach((f) => {
    const ajuster = (t) => { t.style.height = "auto"; t.style.height = `${t.scrollHeight + 2}px`; };
    f.querySelectorAll("textarea[data-auto-hauteur]").forEach(ajuster);
    const compteur = f.querySelector("[data-compte-modifs]");
    let modifs = 0, envoi = false;
    f.addEventListener("input", (e) => {
      const c = e.target;
      if (c.matches("textarea[data-auto-hauteur]")) ajuster(c);
      const l = c.closest(".ligne-traduction");
      if (l) l.classList.toggle("modifiee", c.value !== c.defaultValue);
      modifs = f.querySelectorAll(".ligne-traduction.modifiee").length;
      if (compteur) compteur.textContent = modifs ? lib("saisie.js.traductions_modifiees", { n: modifs }) : lib("saisie.js.champ_vide_a_traduire");
    });
    f.addEventListener("submit", () => { envoi = true; });
    window.addEventListener("beforeunload", (e) => { if (modifs && !envoi) { e.preventDefault(); e.returnValue = ""; } });
  });
  // Paramètres › Référentiels : cases à cocher en lot (« tout cocher », nombre de cases cochées)
  document.querySelectorAll("form[data-cases]").forEach((f) => {
    const compter = () => {
      const n = f.querySelectorAll("[data-case]:checked").length;
      const c = f.querySelector("[data-compte-cases]");
      if (c) c.textContent = lib("saisie.js.coches", { n });
      // Relances : la confirmation dit à combien de personnes l'e-mail part
      f.querySelectorAll("[data-confirmer-nombre]").forEach((b) => { b.dataset.confirmer = lib("saisie.js.confirmer_relance", { n }); });
      // Preuves à supprimer : la confirmation dit combien de fichiers partent ; rien de coché, pas d'envoi
      f.querySelectorAll("[data-confirmer-un]").forEach((b) => {
        b.dataset.confirmer = n === 1 ? b.dataset.confirmerUn : b.dataset.confirmerPlusieurs.replace("{n}", n);
        b.disabled = n === 0;
      });
    };
    f.addEventListener("change", (e) => {
      if (e.target.matches("[data-tout-cocher]")) f.querySelectorAll("[data-case]").forEach((c) => { c.checked = e.target.checked; });
      compter();
    });
  });
  // Page Référentiels : recherche discrète dans la bibliothèque (nom, description, thématique) ; un groupe sans
  // résultat disparaît avec son titre. Sans script, le champ reste caché et tout est affiché.
  document.querySelectorAll("[data-bibliotheque]").forEach((bib) => {
    const zone = bib.querySelector("[data-recherche-bib]"), champ = zone?.querySelector("input"), aucun = bib.querySelector("[data-aucun-bib]");
    if (!champ) return;
    zone.hidden = false;
    champ.addEventListener("input", () => {
      const q = sansAccents(champ.value.trim());
      let n = 0;
      bib.querySelectorAll("[data-groupe-bib]").forEach((g) => {
        let dans = 0;
        g.querySelectorAll("[data-modele-bib]").forEach((m) => { m.hidden = !!q && !sansAccents(m.dataset.modeleBib).includes(q); if (!m.hidden) dans++; });
        g.hidden = !dans;
        n += dans;
      });
      aucun.hidden = n > 0;
    });
  });
  // lien vers un bloc repliable (« …/ajouter/#porte-importer ») : le bloc visé s'ouvre, ses voisins se replient
  const ouvrirCible = () => { const d = location.hash.length > 1 && document.getElementById(location.hash.slice(1)); if (d && d.tagName === "DETAILS") { d.parentNode.querySelectorAll(":scope > details").forEach((x) => { x.open = x === d; }); d.scrollIntoView({ block: "start" }); } };
  ouvrirCible();
  window.addEventListener("hashchange", ouvrirCible);
  // groupe de cases avec « Tout » en tête (reprise : colonnes de valeurs) : la case de tête coche ou décoche tout, et
  // montre un état intermédiaire quand une partie seulement est cochée. Sans script, elle reste cachée.
  document.querySelectorAll("[data-groupe-cases]").forEach((g) => {
    const tete = g.querySelector("[data-toutes-cases]");
    const cases = () => [...g.querySelectorAll("input[type=checkbox]:not([data-toutes-cases])")];
    const refleter = () => {
      const n = cases().filter((c) => c.checked).length;
      tete.checked = n > 0 && n === cases().length;
      tete.indeterminate = n > 0 && n < cases().length;
    };
    tete.hidden = false;
    g.addEventListener("change", (e) => {
      if (e.target === tete) cases().forEach((c) => { c.checked = tete.checked; });
      refleter();
    });
    refleter();
  });
  // confirmation des boutons sensibles hors panneau (ex. supprimer un niveau)
  document.addEventListener("submit", (e) => {
    // question portée par le bouton, ou par le formulaire (supprimer un export, une liste…)
    const f = e.target, b = e.submitter, message = b?.dataset.confirmer || f.dataset.confirmer;
    if (f.matches("form[data-ajax]") || !message) return;
    if (f.dataset.confirme) { delete f.dataset.confirme; return; }  // déjà confirmé : l'envoi part
    e.preventDefault(); e.stopImmediatePropagation();
    confirmer(message, b).then((oui) => {
      if (!oui) return;
      f.dataset.confirme = "1";
      f.requestSubmit(b || undefined);
    });
  }, true);

  // fichier à remplir : la liste des périodes suit le référentiel choisi (« tous » : pas de période à choisir)
  document.querySelectorAll("[data-ref-fichier]").forEach((ref) => {
    const periode = ref.form.querySelector("[data-periode-fichier]");
    const suivre = (changement) => {
      const tous = ref.value === "tous";
      periode.disabled = tous;
      periode.querySelectorAll("optgroup").forEach((g) => {
        const visible = !tous && g.dataset.ref === ref.value;
        g.hidden = !visible;
        g.querySelectorAll("option").forEach((o) => { o.disabled = !visible; o.hidden = !visible; });
      });
      const choisie = periode.selectedOptions[0];
      if (changement && !tous && (!choisie || choisie.disabled)) {
        const premiere = periode.querySelector(`optgroup[data-ref="${CSS.escape(ref.value)}"] option`);
        if (premiere) premiere.selected = true;
      }
    };
    ref.addEventListener("change", () => suivre(true));
    suivre(false);
  });

  // sélecteur d'organisation en arbre dans un formulaire (fichier à remplir) : remplace la liste
  // déroulante, qui reste le champ envoyé (sa valeur suit le choix) ; recherche, Échap et clic dehors ferment
  document.querySelectorAll("[data-selecteur-champ]").forEach((sel) => {
    const repli = sel.parentElement.querySelector("[data-selecteur-repli]");
    if (!repli) return;
    sel.hidden = false; repli.hidden = true;
    const champ = sel.querySelector("[data-recherche-org-champ]");
    sel.addEventListener("toggle", () => { if (sel.open) { champ.value = ""; champ.dispatchEvent(new Event("input")); champ.focus(); } });
    champ.addEventListener("input", () => { const q = champ.value.trim().toLowerCase(); sel.querySelectorAll("li[data-texte]").forEach((li) => { li.hidden = q && !li.dataset.texte.includes(q); }); });
    champ.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); sel.querySelector("li:not([hidden]) button")?.click(); } });
    const montrer = (b) => {
      sel.querySelector("[data-selecteur-nom]").textContent = b.querySelector(".nom-org").textContent;
      sel.querySelectorAll("button[data-valeur]").forEach((x) => x.classList.toggle("actuelle", x === b));
    };
    sel.addEventListener("click", (e) => {
      const b = e.target.closest("button[data-valeur]");
      if (!b) return;
      repli.value = b.dataset.valeur;
      repli.dispatchEvent(new Event("change", { bubbles: true }));
      montrer(b);
      sel.open = false;
    });
    // un script a changé la valeur de la liste (Visualisation : descendre dans une organisation, rétablir les filtres)
    repli.addEventListener("selecteur:maj", () => {
      const b = [...sel.querySelectorAll("button[data-valeur]")].find((x) => x.dataset.valeur === repli.value);
      if (b) montrer(b);
    });
    document.addEventListener("click", (e) => { if (sel.open && !sel.contains(e.target)) sel.open = false; });
    sel.addEventListener("keydown", (e) => { if (e.key === "Escape") sel.open = false; });
  });
  // fichier à remplir : « Un onglet par organisation » n'existe qu'en Excel (un CSV n'a qu'un onglet)
  document.querySelectorAll("[data-onglets-excel]").forEach((l) => {
    const form = l.closest("form"), cb = l.querySelector("input");
    const maj = () => { const csv = form.querySelector("input[name=format][value=csv]")?.checked; cb.disabled = !!csv; if (csv) cb.checked = false; l.classList.toggle("desactive", !!csv); };
    form.addEventListener("change", (e) => { if (e.target.name === "format") maj(); });
    maj();
  });

  // Consolidation › thèmes : recherche dans la liste des thèmes à cocher 
  document.addEventListener("input", (e) => {
    if (!e.target.matches("[data-recherche-themes]")) return;
    const q = e.target.value.trim().toLowerCase();
    e.target.closest(".si-theme").querySelectorAll("[data-liste-themes] label").forEach((l) => { l.hidden = q && !l.dataset.texte.includes(q); });
  });

  // « Afficher les codes » (Saisie, Cohérence) : codes des KPI cachés par défaut, choix gardé dans
  // ce navigateur (une préférence d'affichage, rien dans la base)
  const casesCodes = document.querySelectorAll("[data-montrer-codes]");
  if (casesCodes.length) {
    let montrer = false;
    try { montrer = localStorage.getItem("montrer-codes") === "1"; } catch (e) { /* stockage indisponible : codes cachés */ }
    const appliquer = (oui) => { document.body.classList.toggle("montrer-codes", oui); casesCodes.forEach((c) => { c.checked = oui; }); };
    appliquer(montrer);
    document.addEventListener("change", (e) => {
      if (!e.target.matches("[data-montrer-codes]")) return;
      appliquer(e.target.checked);
      try { localStorage.setItem("montrer-codes", e.target.checked ? "1" : "0"); } catch (err) { /* sans stockage : pour cette page seulement */ }
    });
  }

  // Mon compte › Apparence : appliquée aussitôt, sans recharger la page (la page restait en haut et clignotait) ;
  // le choix est enregistré par le même formulaire (cookie). Sans JavaScript : envoi normal du formulaire.
  document.querySelectorAll("[data-apparence-direct]").forEach((form) => {
    form.addEventListener("click", async (e) => {
      const b = e.target.closest("button[name=apparence]");
      if (!b) return;
      e.preventDefault();
      const corps = new FormData(form); corps.set("apparence", b.value);
      const rep = await fetch(form.getAttribute("action") || location.pathname, { method: "POST", body: corps, headers: entetes(), redirect: "manual" });
      if (!(rep.ok || rep.type === "opaqueredirect" || (rep.status >= 300 && rep.status < 400))) { erreur(lib("saisie.js.erreur_chargement")); return; }
      const racine = document.documentElement;
      if (b.value === "systeme") delete racine.dataset.apparence; else racine.dataset.apparence = b.value;
      document.querySelector('meta[name="color-scheme"]')?.setAttribute("content", b.value === "clair" ? "light" : b.value === "sombre" ? "dark" : "light dark");
      form.querySelectorAll("button[name=apparence]").forEach((x) => x.setAttribute("aria-pressed", x === b ? "true" : "false"));
      const st = form.querySelector("[data-apparence-statut]"); if (st) { st.hidden = false; }
    });
  });

  // « Je réponds à » : panneau de choix du référentiel et de la période (barre du haut, titres des pages)
  const panneauChoix = document.getElementById("choix-reponse");
  const boutonChoix = document.querySelector("[data-ouvrir-choix]");
  if (panneauChoix && boutonChoix) {
    let declencheur = boutonChoix;
    const fermerChoix = (rendreFocus) => {
      if (panneauChoix.hidden) return;
      panneauChoix.hidden = true;
      boutonChoix.setAttribute("aria-expanded", "false");
      if (rendreFocus) declencheur.focus();
    };
    // contenu chargé d'avance (au survol ou au focus du bouton, sinon peu après l'affichage de la page) : le panneau
    // s'ouvre aussitôt au clic ; s'il n'est pas encore là, le panneau s'ouvre avec « Chargement… » 
    let chargement = null;
    const charger = () => {
      if (!chargement) {
        const suivant = encodeURIComponent(location.pathname + location.search);
        chargement = fetch(`${panneauChoix.dataset.url}?suivant=${suivant}`, { headers: entetes() })
          .then((rep) => (rep.ok ? rep.text() : Promise.reject(rep)))
          .then((html) => { panneauChoix.innerHTML = html; panneauChoix.dataset.charge = "1"; })
          .catch(() => { chargement = null; return Promise.reject(); });
      }
      return chargement;
    };
    ["pointerenter", "focus"].forEach((ev) => boutonChoix.addEventListener(ev, () => charger().catch(() => {}), { once: true }));
    setTimeout(() => charger().catch(() => {}), 1500);
    const ouvrirChoix = async (source) => {
      declencheur = source || boutonChoix;
      if (!panneauChoix.dataset.charge) {
        panneauChoix.innerHTML = `<p class="discret chargement-choix" role="status">${lib("commun.chargement")}</p>`;
        panneauChoix.hidden = false;
        boutonChoix.setAttribute("aria-expanded", "true");
        try { await charger(); } catch (e) { fermerChoix(false); erreur(lib("saisie.js.erreur_chargement")); return; }
        if (panneauChoix.hidden) return;  // refermé pendant le chargement
      }
      panneauChoix.hidden = false;
      boutonChoix.setAttribute("aria-expanded", "true");
      (panneauChoix.querySelector(".choix-campagne.actuelle") || panneauChoix.querySelector("a, button"))?.focus();
    };
    document.addEventListener("click", (e) => {
      const ouvrir = e.target.closest("[data-ouvrir-choix]");
      if (ouvrir) { e.preventDefault(); panneauChoix.hidden ? ouvrirChoix(ouvrir) : fermerChoix(true); return; }
      if (e.target.closest("[data-fermer-choix]")) { fermerChoix(true); return; }
      if (!panneauChoix.hidden && !panneauChoix.contains(e.target)) fermerChoix(false);
    });
    panneauChoix.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.stopPropagation(); fermerChoix(true); } });
    // recherche du panneau (plus de 6 périodes ouvertes) : par période ou par nom de référentiel
    panneauChoix.addEventListener("input", (e) => {
      if (!e.target.matches("[data-filtre-choix]")) return;
      const q = e.target.value.trim().toLowerCase();
      let visibles = 0;
      panneauChoix.querySelectorAll(".choix-bloc").forEach((bloc) => {
        const refOk = !q || (bloc.dataset.texteRef || "").includes(q);
        let n = 0;
        bloc.querySelectorAll("li").forEach((li) => { const ok = refOk || li.textContent.toLowerCase().includes(q); li.hidden = !ok; if (ok) n++; });
        bloc.querySelectorAll("details").forEach((d) => { if (q) d.open = true; });
        bloc.hidden = !n; visibles += n;
      });
      const vide = panneauChoix.querySelector("[data-choix-vide]"); if (vide) vide.hidden = visibles > 0;
    });
  }

