{# sélecteur d’organisation, fiches organisation et KPI, erreurs des formulaires, fonction initialiser et son appel #}
  // ---------------------------------------------------------------- sélecteur d'organisation
  const selOrg = document.getElementById("choix-org");
  if (selOrg) {
    const champ = selOrg.querySelector("[data-recherche-org]");
    selOrg.addEventListener("toggle", () => {
      if (selOrg.open) { champ.value = ""; champ.dispatchEvent(new Event("input")); champ.focus();
        selOrg.querySelector("a.actuelle")?.scrollIntoView({ block: "nearest" }); }
    });
    champ.addEventListener("input", () => {
      const q = champ.value.trim().toLowerCase();
      selOrg.querySelectorAll("li[data-texte]").forEach((li) => { li.hidden = q && !li.dataset.texte.includes(q); });
    });
    champ.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); selOrg.querySelector("li:not([hidden]) a")?.click(); }
    });
    document.addEventListener("click", (e) => { if (selOrg.open && !selOrg.contains(e.target)) selOrg.open = false; });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") selOrg.open = false; });
  }

  // ---------------------------------------------------------------- fiche organisation : niveau et rattachement
  // fiche organisation : rattachement à une organisation de n'importe quel niveau supérieur (rang plus petit)
  function majFicheOrg(form) {
    const choisi = form.querySelector("input[name=niveau]:checked");
    const rang = Number(choisi?.dataset.rang || 0);
    const select = form.querySelector("select[name=parent]");
    form.querySelector("[data-si-site]").hidden = !choisi || choisi.dataset.bas !== "1";
    form.querySelector("[data-si-parent]").hidden = rang <= 1;
    // date de fermeture : seulement pour une organisation désactivée (« Organisation collectée » décochée)
    const fermee = form.querySelector("[data-si-fermee]"), collectee = form.querySelector("input[name=actif]");
    if (fermee && collectee) {
      fermee.hidden = collectee.checked;
      fermee.querySelectorAll("input").forEach((i) => { i.disabled = collectee.checked; });
    }
    if (!select) return;
    if (rang <= 1) { select.value = ""; return; }
    select.querySelectorAll("option[data-rang]").forEach((o) => { o.hidden = o.disabled = Number(o.dataset.rang) >= rang; });
    if (select.selectedOptions[0]?.disabled) select.value = "";
    form.querySelector("[data-aide-parent]").textContent =
      lib("saisie.js.niveau_parent", { nom: choisi.dataset.nom, dessus: choisi.dataset.dessus });
  }
  // fiche KPI : formule seulement pour un calcul ; « Formule » d'agrégation réservée aux calculs ; paramètre hérité sans
  // agrégation ; somme pour un nombre, décompte pour un oui / non ou une liste (comportement et format réglés dans Paramètres) ;
  // texte rédigé : ni unité, ni décimales, ni agrégation (« Aucune » imposée, aussi dans le temps), ni saisie au-dessus
  function majFicheKpi(form) {
    const comportement = form.querySelector("input[name=type_saisie]:checked")?.dataset.comportement;
    const format = form.querySelector("select[name=type_reponse]")?.selectedOptions[0]?.dataset.format;
    const redige = format === "texte";
    const texte = format === "oui_non" || format === "liste" || redige;
    form.querySelectorAll("[data-si-agregeable]").forEach((c) => { c.hidden = redige; });
    form.querySelectorAll("[data-aide-redige]").forEach((c) => { c.hidden = !redige; });
    form.querySelectorAll("[data-agregation-temps]").forEach((c) => {
      const interdit = redige && c.dataset.agregationTemps !== "aucune";
      c.classList.toggle("indisponible", interdit);
      c.querySelector("input").disabled = interdit;
      if (interdit && c.querySelector("input").checked) form.querySelector('[data-agregation-temps="aucune"] input').checked = true;
    });
    const formule = form.querySelector("[data-si-calcule]");
    if (formule) formule.hidden = comportement !== "calcul";
    form.querySelectorAll("[data-si-nombre]").forEach((c) => { c.hidden = texte; });
    form.querySelectorAll("[data-agregation]").forEach((c) => {
      const a = c.dataset.agregation;
      const interdit = (a === "Formule" && comportement !== "calcul") || (comportement === "herite" && a !== "Aucune")
        || (c.dataset.pour === "numerique" && texte) || (c.dataset.pour === "texte" && !texte) || (redige && a !== "Aucune");
      c.classList.toggle("indisponible", interdit);
      c.querySelector("input").disabled = interdit;
      if (interdit && c.querySelector("input").checked) form.querySelector('[data-agregation="Aucune"] input').checked = true;
    });
  }
  // erreurs des formulaires (ul.errorlist de Django) reliées à leur champ : aria-describedby et aria-invalid, pour que le
  // lecteur d'écran lise l'erreur avec le champ. Le champ est celui qui précède la liste (ou les boutons radio du bloc).
  let nbErreurs = 0;
  function relierErreurs(racine) {
    const sel = "input:not([type=hidden]):not([type=submit]):not([type=button]), select, textarea";
    racine.querySelectorAll("ul.errorlist:not(.nonfield)").forEach((ul) => {
      let p = ul.previousElementSibling;
      while (p && !(p.matches(sel) || p.querySelector(sel))) p = p.previousElementSibling;
      if (!p) return;
      const champs = p.matches(sel) ? [p] : [...p.querySelectorAll(sel)];
      if (!ul.id) ul.id = `erreur-champ-${++nbErreurs}`;
      champs.forEach((c) => {
        const liste = (c.getAttribute("aria-describedby") || "").split(" ").filter(Boolean);
        if (!liste.includes(ul.id)) c.setAttribute("aria-describedby", [...liste, ul.id].join(" "));
        c.setAttribute("aria-invalid", "true");
      });
    });
  }
  // Blocs repliables dont le choix est gardé d'une visite à l'autre (<details data-pli-memoire="clé">, Campagnes) :
  // le serveur décide de l'état par défaut, la personne le change, l'outil s'en souvient sur ce navigateur
  function restaurerReplis(racine) {
    racine.querySelectorAll("details[data-pli-memoire]").forEach((d) => {
      const cle = `pli.${d.dataset.pliMemoire}`;
      let v = null;
      try { v = localStorage.getItem(cle); } catch (err) { /* stockage indisponible */ }
      if (v !== null) d.open = v === "1";
      d.addEventListener("toggle", () => {
        try { localStorage.setItem(cle, d.open ? "1" : "0"); } catch (err) { /* pour cette page seulement */ }
      });
    });
  }

  function initialiser(racine) {
    restaurerReplis(racine);
    racine.querySelectorAll("[data-perimetre]").forEach(perimetre);  // organisations consultées (fiche d'un compte)
    relierErreurs(racine);
    racine.querySelectorAll("[data-form-org]").forEach(majFicheOrg);
    racine.querySelectorAll("[data-form-kpi]").forEach(majFicheKpi);
    racine.querySelectorAll("[data-constructeur]").forEach(initConstructeur);
    racine.querySelectorAll("[data-onglets-langue]").forEach(ongletsLangue);
    racine.querySelectorAll("[data-form-campagne]").forEach(formCampagne);
    initEditeursMd(racine);
    initEditeursTableau(racine);
    initAuto(racine);
    initIA(racine);  // boutons de l'assistant IA (12b_ia.js), aussi dans le panneau
    // sauvegarde juste créée : téléchargée une seule fois. L'adresse perd « ?telecharger=… » aussitôt, pour qu'un retour
    // arrière ou un rechargement de la page ne relance pas le téléchargement.
    // message lié à l'adresse (« ?restauree=… ») : affiché une fois, retiré de l'adresse (pas de retour au rechargement)
    racine.querySelectorAll("[data-param-unique]").forEach((m) => {
      const url = new URL(window.location.href);
      if (!url.searchParams.has(m.dataset.paramUnique)) return;
      url.searchParams.delete(m.dataset.paramUnique);
      history.replaceState(null, "", url.pathname + url.search + url.hash);
    });
    racine.querySelectorAll("[data-telecharger-auto]").forEach((a) => {
      const url = new URL(window.location.href);
      if (!url.searchParams.has("telecharger")) return;
      url.searchParams.delete("telecharger");
      history.replaceState(null, "", url.pathname + url.search + url.hash);
      a.click();
    });
  }

  // nouvelle campagne : les périodes proposées (mois, trimestres, semestres) suivent la fréquence du référentiel choisi
  function formCampagne(form) {
    const donnees = form.querySelector("#frequences-referentiels");
    const ref = form.querySelector("select[name=referentiel]");
    if (!donnees || !ref) return;
    const frequences = JSON.parse(donnees.textContent);
    const maj = () => {
      const f = frequences[ref.value] || "annee";
      form.querySelectorAll("[data-choix-rang]").forEach((b) => { b.hidden = f === "annee"; });
      const rang = form.querySelector("select[name=rang]");
      let premier = null, garde = false;
      rang.querySelectorAll("option").forEach((o) => {
        o.hidden = o.disabled = o.dataset.frequence !== f;
        if (!o.hidden && !premier) premier = o;
        if (!o.hidden && o.selected) garde = true;
      });
      if (!garde && premier) premier.selected = true;
    };
    ref.addEventListener("change", maj);
    maj();
  }

  // fiche KPI : textes par langue en onglets ; la langue choisie reste d'une fiche à l'autre
  let langueFiche = null;
  function ongletsLangue(bloc, langue) {
    if (langue) langueFiche = langue;
    const codes = [...bloc.querySelectorAll("[data-onglet-langue]")].map((b) => b.dataset.ongletLangue);
    const choisie = codes.includes(langueFiche) ? langueFiche : bloc.dataset.reference;
    bloc.querySelectorAll("[data-onglet-langue]").forEach((b) => b.setAttribute("aria-selected", b.dataset.ongletLangue === choisie ? "true" : "false"));
    bloc.closest("form").querySelectorAll("[data-langue]").forEach((el) => { el.hidden = el.dataset.langue !== choisie; });
  }
  document.addEventListener("click", (e) => {
    const o = e.target.closest("[data-onglet-langue]");
    if (o) ongletsLangue(o.closest("[data-onglets-langue]"), o.dataset.ongletLangue);
  });
  document.addEventListener("invalid", (e) => {  // champ obligatoire dans un onglet caché : afficher sa langue
    const cache = e.target.closest("[data-langue][hidden]");
    const bloc = cache?.closest("form")?.querySelector("[data-onglets-langue]");
    if (bloc) ongletsLangue(bloc, cache.dataset.langue);
  }, true);
  document.addEventListener("change", (e) => {
    const f = e.target.closest("[data-form-kpi]");
    if (f && ["type_saisie", "type_reponse"].includes(e.target.name)) majFicheKpi(f);
    if (f && e.target.name === "unite") {
      // unité « nombre entier » (comptage) : 0 décimale, champ verrouillé ; nouveau KPI : décimales par défaut de l'unité
      const o = e.target.selectedOptions[0], champ = f.querySelector("[name=decimales]"), aide = f.querySelector("#aide-decimales-entier");
      const entier = o?.dataset.entier === "1";
      if (entier) champ.value = 0;
      else if (f.querySelector("[name=code]") && o?.dataset.decimales !== undefined) champ.value = o.dataset.decimales;
      champ.readOnly = entier;
      const decrit = (champ.getAttribute("aria-describedby") || "").split(" ").filter((x) => x && x !== "aide-decimales-entier");
      if (entier) decrit.push("aide-decimales-entier");
      if (decrit.length) champ.setAttribute("aria-describedby", decrit.join(" ")); else champ.removeAttribute("aria-describedby");
      if (aide) aide.hidden = !entier;
    }
    if (f && e.target.name === "na_compte_zero") e.target.dataset.touchee = "1";  // choix de l'admin : plus proposé
  });
  // fiche KPI tout juste créée : « Traduire en … » ouvre l'onglet de la langue et place le curseur dans le nom ;
  // « Plus tard » retire la proposition (rien n'est traduit tout seul)
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-traduire-en], [data-traduire-plus-tard]");
    if (!b) return;
    const encart = b.closest("[data-proposer-traduction]"), racine = encart.parentElement;
    const bloc = racine.querySelector("[data-onglets-langue]");
    encart.hidden = true;
    if (!b.dataset.traduireEn || !bloc) { (bloc?.querySelector("[aria-selected=true]") || racine.querySelector("input:not([type=hidden])"))?.focus(); return; }
    ongletsLangue(bloc, b.dataset.traduireEn);
    const champ = bloc.closest("form").querySelector(`[data-langue="${b.dataset.traduireEn}"] :is(input, textarea)`);
    if (champ) { champ.scrollIntoView({ block: "center" }); champ.focus(); }
  });
  // catalogue des KPI : « + » d'une ligne, menu « Ajouter un KPI au-dessus / en dessous ». Un seul menu, posé sur la page
  // sous le bouton (les cases du tableau coupent ce qui dépasse) ; il se ferme au clic ailleurs, à Échap, au défilement
  // et quand le clavier en sort.
  let boutonAjout = null, defilementAjout = 0;
  function fermerMenuAjout(rendreFocus) {
    const m = document.querySelector("body > .menu-ajout-kpi");
    if (!m) return;
    m.remove();
    if (boutonAjout) { boutonAjout.setAttribute("aria-expanded", "false"); if (rendreFocus) boutonAjout.focus(); }
    boutonAjout = null;
  }
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-ajout-kpi]");
    const ouvert = b && b === boutonAjout;
    if (e.target.closest(".menu-ajout-kpi a")) { setTimeout(() => fermerMenuAjout(false)); return; }  // le lien ouvre la fiche (data-panneau)
    fermerMenuAjout(false);
    const modele = document.getElementById("menu-ajout-kpi");
    if (!b || ouvert || !modele) return;
    const menu = modele.content.firstElementChild.cloneNode(true);
    menu.querySelectorAll("a").forEach((a) => { a.href = `${b.dataset.ajoutKpi}&position=${a.dataset.position}`; });
    const r = b.getBoundingClientRect();
    document.body.append(menu);
    const dessous = r.bottom + 4 + menu.offsetHeight <= window.innerHeight;
    menu.style.top = `${dessous ? r.bottom + 4 : r.top - 4 - menu.offsetHeight}px`;
    menu.style.right = `${Math.max(8, window.innerWidth - r.right)}px`;
    boutonAjout = b;
    defilementAjout = window.scrollY;
    b.setAttribute("aria-expanded", "true");
    menu.querySelector("a").focus();
    menu.addEventListener("focusout", (ev) => { if (!menu.contains(ev.relatedTarget) && ev.relatedTarget) fermerMenuAjout(false); });
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && boutonAjout) { e.stopPropagation(); fermerMenuAjout(true); }
  }, true);
  window.addEventListener("scroll", () => { if (Math.abs(window.scrollY - defilementAjout) > 4) fermerMenuAjout(false); }, { passive: true });
  window.addEventListener("resize", () => fermerMenuAjout(false));
  // référentiel : filtre de type en boutons, sommaire des thèmes
  document.addEventListener("click", (e) => {
    const th = e.target.closest("[data-aller-theme]");
    if (th) { const d = document.getElementById("theme-" + th.dataset.allerTheme); if (d) d.open = true; }
  });
  document.addEventListener("change", (e) => {
    const f = e.target.closest("[data-form-org]");
    if (f && (e.target.name === "niveau" || e.target.name === "actif")) majFicheOrg(f);
  });
  initialiser(document);

