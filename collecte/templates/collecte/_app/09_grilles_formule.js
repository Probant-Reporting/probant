{% load collecte %}{# arbre des organisations repliable, grille des attributions, copier un texte, infobulle des SPOC, constructeur de formule #}
  // ---------------------------------------------------------------- arbre des organisations repliable
  function majArbre() {
    const table = document.querySelector("table.arbre-orgs");
    if (!table) return;
    const recherche = (document.getElementById("recherche")?.value || "").trim();
    const replies = new Set(Array.from(table.querySelectorAll('.replier-org[aria-expanded="false"]')).map((b) => b.closest("tr").dataset.id));
    table.querySelectorAll("tr[data-id]").forEach((tr) => {
      const cache = !recherche && tr.dataset.ancetres.split(" ").some((id) => replies.has(id));
      tr.classList.toggle("cache-arbre", cache);
    });
    const niveaux = valeursFiltre("filtre-niveau");  // champ « Niveau » de la barre de filtres : un ou plusieurs niveaux
    const sansBas = !recherche && !!document.querySelector('[data-affichage="sans-bas"][aria-pressed="true"]');
    table.querySelectorAll("tr[data-id]").forEach((tr) => {
      tr.classList.toggle("hors-filtre", niveaux.length > 0 && !niveaux.includes(tr.dataset.niveau));
      if (sansBas && tr.dataset.bas) tr.classList.add("cache-arbre");  // niveau le plus bas masqué, même rattaché plus haut
      if (niveaux.length) tr.classList.remove("cache-arbre");
    });
    recompterFiltres();
  }
  function afficher(mode) {
    document.querySelectorAll("[data-affichage]").forEach((b) => b.setAttribute("aria-pressed", b.dataset.affichage === mode ? "true" : "false"));
    document.querySelectorAll("table.arbre-orgs tr[data-id]").forEach((tr) => {
      const x = tr.querySelector(".replier-org");
      if (!x) return;
      const replier = mode === "replie" ? tr.dataset.prof === "0" : mode === "sans-bas" ? !!tr.dataset.queBas : false;
      x.setAttribute("aria-expanded", replier ? "false" : "true");
    });
    majArbre();
  }
  document.addEventListener("click", (e) => {
    const b = e.target.closest(".replier-org");
    if (b) {
      b.setAttribute("aria-expanded", b.getAttribute("aria-expanded") === "false" ? "true" : "false");
      document.querySelectorAll("[data-affichage]").forEach((x) => x.setAttribute("aria-pressed", "false"));
      majArbre(); return;
    }
    const aff = e.target.closest("[data-affichage]");
    if (aff) { afficher(aff.dataset.affichage); return; }
  });
  document.addEventListener("change", (e) => { if (e.target.id === "filtre-niveau") majArbre(); });
  document.addEventListener("input", (e) => { if (e.target.id === "recherche") majArbre(); });

  // ---------------------------------------------------------------- grille des attributions : filtres
  function majGrille() {
    const grille = document.querySelector("[data-grille]");
    if (!grille) return;
    const personne = document.getElementById("filtre-personne")?.value || "";
    const aCompleter = document.getElementById("filtre-sans-spoc")?.checked;
    const themes = valeursFiltre("filtre-theme");  // un ou plusieurs thèmes
    grille.classList.toggle("mode-personne", !!personne);
    grille.querySelectorAll("tr.ligne").forEach((tr) => {
      let trouve = false;
      tr.querySelectorAll("td[data-cle]").forEach((td) => {
        const a = personne && td.dataset.spocs.split(",").includes(personne);
        td.classList.toggle("a-la-personne", !!a);
        trouve = trouve || a;
      });
      const masquer = (personne && !trouve) || (aCompleter && !tr.querySelector("td.sans-spoc"));
      tr.classList.toggle("hors-filtre-grille", !!masquer);
    });
    grille.querySelectorAll("tbody").forEach((tb) => {
      tb.classList.toggle("hors-filtre-grille", (themes.length > 0 && !themes.includes(tb.dataset.theme))
        || !tb.querySelector("tr.ligne:not([hidden]):not(.hors-filtre-grille)"));
    });
    recompterFiltres();
  }
  document.addEventListener("change", (e) => {
    if (["filtre-personne", "filtre-sans-spoc", "filtre-theme"].includes(e.target.id)) majGrille();
    if (e.target.matches("input[data-aller]")) location.href = e.target.dataset.aller;  // « KPI calculés » : rechargée par le serveur
  });
  // thèmes repliables, un par un ou tous d'un coup
  document.addEventListener("click", (e) => {
    const b = e.target.closest(".replier-theme, [data-replier-themes]");
    if (!b) return;
    const grille = document.querySelector("[data-grille]");
    if (!grille) return;
    const ouvrir = b.getAttribute("aria-expanded") !== "true";
    const boutons = b.matches("[data-replier-themes]") ? [...grille.querySelectorAll(".replier-theme")] : [b];
    boutons.forEach((x) => {
      x.setAttribute("aria-expanded", ouvrir ? "true" : "false");
      x.closest("tbody").classList.toggle("theme-replie", !ouvrir);
    });
    const tous = document.querySelector("[data-replier-themes]");
    if (tous) {
      const ouverts = grille.querySelectorAll('.replier-theme[aria-expanded="true"]').length;
      tous.setAttribute("aria-expanded", ouverts ? "true" : "false");
      tous.textContent = lib(ouverts ? "saisie.js.tout_replier" : "saisie.js.tout_deplier");
    }
  });
  document.addEventListener("input", (e) => { if (e.target.id === "recherche") majGrille(); });

  // ---------------------------------------------------------------- grille des attributions : en-têtes visibles
  // La grille grandit avec la page et ne défile qu'en largeur dans son cadre (.grille-scroll).
  // Le CSS ne sait pas garder en haut de l'écran l'en-tête d'un tableau placé dans un cadre qui défile en largeur : tant
  // que le haut de la grille est sorti de l'écran et que sa fin est encore visible, on décale les cellules de l'en-tête
  // (translateY) pour qu'elles restent en haut de l'écran ; le reste du temps, aucun décalage. Position seulement, sans
  // animation (rien ne bouge en plus quand la personne réduit les animations). --haut-entete-grille donne aux cases leur
  // marge de défilement : une case atteinte au clavier ne passe pas sous l'en-tête.
  function placerEntetesGrille() {
    document.querySelectorAll(".grille-scroll").forEach((cadre) => {
      const thead = cadre.querySelector(":scope > table > thead");
      if (!thead) return;
      const haut = thead.offsetHeight;
      // haut de l'en-tête (non décalé : thead lui-même ne bouge pas) au-dessus de l'écran ; au plus jusqu'à ce que
      // l'en-tête touche le bas du cadre
      const decalage = Math.ceil(Math.max(0, Math.min(-thead.getBoundingClientRect().top, cadre.clientHeight - haut)));
      const valeur = decalage > 0 ? `translateY(${decalage}px)` : "";
      if (cadre.style.getPropertyValue("--haut-entete-grille") !== haut + "px") cadre.style.setProperty("--haut-entete-grille", haut + "px");
      if ((cadre.dataset.decalage || "") === valeur) return;
      cadre.dataset.decalage = valeur;
      cadre.classList.toggle("entete-flottant", decalage > 0);
      thead.querySelectorAll("th").forEach((th) => { th.style.transform = valeur; });
    });
  }
  if (document.querySelector(".grille-scroll")) {
    let imageEntetes = 0;
    const demanderEntetes = () => { if (!imageEntetes) imageEntetes = requestAnimationFrame(() => { imageEntetes = 0; placerEntetesGrille(); }); };
    window.addEventListener("scroll", demanderEntetes, { passive: true });
    window.addEventListener("resize", demanderEntetes);
    // hauteur changée sans défilement (filtres, recherche, case mise à jour) : l'en-tête ne doit pas dépasser du cadre
    if (window.ResizeObserver) document.querySelectorAll(".grille-scroll").forEach((c) => new ResizeObserver(demanderEntetes).observe(c));
    placerEntetesGrille();
  }

  // ---------------------------------------------------------------- copier un texte (message d'accès, « Écrire à … »)
  // data-copier : sélecteur du texte ; data-copier-annonce : ce que dit le toast (« Adresse copiée. »…)
  document.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-copier]");
    if (!b) return;
    const texte = document.querySelector(b.dataset.copier)?.textContent || "";
    // zone aria-live déjà dans la page (data-annonce-copie, dans un bloc data-zone-copie) : lue par les lecteurs d'écran, ce
    // que le message passager (display: none puis block) ne garantit pas ; vidée puis remplie pour qu'un second appui soit relu
    const annoncer = (message) => {
      const zone = b.closest("[data-zone-copie]")?.querySelector("[data-annonce-copie]");
      if (zone) { zone.textContent = ""; setTimeout(() => { zone.textContent = message; }, 60); }
    };
    try { await navigator.clipboard.writeText(texte); const m = b.dataset.copierAnnonce || lib("saisie.js.message_copie"); toast(m); annoncer(m); }
    catch { const r = document.createRange(); r.selectNodeContents(document.querySelector(b.dataset.copier)); getSelection().removeAllRanges(); getSelection().addRange(r); toast(lib("saisie.js.texte_selectionne")); annoncer(lib("saisie.js.texte_selectionne")); }
  });
  // bloc créé par la page (jeton d'assistant) : le focus y va à l'arrivée, sur son titre (jamais perdu sur body)
  // (après le chargement : l'adresse « …#assistants » rend le focus au document quand le navigateur défile jusqu'à l'ancre)
  const blocFocus = document.querySelector("[data-focus-initial]");
  if (blocFocus) {
    if (document.readyState === "complete") blocFocus.focus();
    else window.addEventListener("load", () => setTimeout(() => blocFocus.focus(), 0));
  }

  // ---------------------------------------------------------------- infobulle des SPOC (grille des attributions)
  const infobulle = document.createElement("div");
  infobulle.id = "infobulle-spocs";
  infobulle.setAttribute("role", "tooltip");
  document.body.appendChild(infobulle);
  document.addEventListener("mouseover", (e) => {
    const td = e.target.closest("td.cellule-attr");
    const liste = td?.querySelector(".liste-spocs");
    if (!liste || choix?.classList.contains("ouvert")) { infobulle.classList.remove("visible"); return; }
    infobulle.innerHTML = liste.innerHTML;
    infobulle.classList.add("visible");
    const r = td.getBoundingClientRect(), l = infobulle.getBoundingClientRect();
    const enBas = r.bottom + l.height + 12 < window.innerHeight;
    infobulle.style.top = (enBas ? r.bottom + 6 : r.top - l.height - 6) + "px";
    infobulle.style.left = Math.max(8, Math.min(r.left + r.width / 2 - l.width / 2, window.innerWidth - l.width - 8)) + "px";
  });
  document.addEventListener("mouseout", (e) => {
    if (e.target.closest("td.cellule-attr") && !e.relatedTarget?.closest?.("td.cellule-attr")) infobulle.classList.remove("visible");
  });
  document.addEventListener("scroll", () => infobulle.classList.remove("visible"), true);
  document.addEventListener("click", () => infobulle.classList.remove("visible"));

  // ---------------------------------------------------------------- constructeur de formule (référentiel)
  async function chargerKpis(url) {
    if (!catalogueKpi) {
      const rep = await fetch(url, { headers: entetes() });
      catalogueKpi = new Map((await rep.json()).kpis.map((k) => [k.id, k]));
    }
    return catalogueKpi;
  }
  const JETON = /\s*(?:(\[[^\[\]]+\])|(\d+(?:[.,]\d+)?)|([-+*/()]))/y;
  function decouper(texte) {
    const jetons = []; JETON.lastIndex = 0; let m;
    while (JETON.lastIndex < texte.length && (m = JETON.exec(texte))) {
      if (m[1]) { const [id, dec] = m[1].slice(1, -1).split("@").map((x) => x.trim()); jetons.push({ t: "kpi", id, dec: dec || "N" }); }
      else if (m[2]) jetons.push({ t: "nb", v: m[2].replace(",", ".") });
      else if (m[3]) jetons.push({ t: "op", v: m[3] });
    }
    return jetons;
  }
  function assembler(jetons) {
    return jetons.map((j) => j.t === "kpi" ? `[${j.id}${j.dec !== "N" ? "@" + j.dec : ""}]` : j.v).join(" ").replace(/\( /g, "(").replace(/ \)/g, ")");
  }
  const SYMBOLE = { "*": "×", "/": "÷", "-": "−" };
  // nouveau KPI calculé : « Une source N/A compte comme 0 » proposé coché pour une formule qui n'est qu'une somme (KPI,
  // nombres, + et −, parenthèses), tant que l'admin n'a pas touché la case
  function proposerNaZero(c, formule) {
    const f = c.closest("[data-form-kpi]"), caseNa = f?.querySelector("input[name=na_compte_zero]");
    if (!caseNa || caseNa.dataset.touchee || !f.querySelector("[name=code]")) return;
    caseNa.checked = /\[[^\[\]]+\]/.test(formule) && !/[*\/]/.test(formule.replace(/\[[^\[\]]*\]/g, ""));
  }
  function dessinerJetons(c) {
    const zone = c.querySelector("[data-jetons]"), texte = c.querySelector("textarea");
    proposerNaZero(c, texte.value);
    majNiveauRegle(c.closest("form"));
    const jetons = decouper(texte.value);
    zone.innerHTML = "";
    if (!jetons.length) { zone.innerHTML = `<span class="discret">${echapper(lib("saisie.js.formule_vide"))}</span>`; return; }
    jetons.forEach((j, i) => {
      const b = document.createElement("span");
      if (j.t === "kpi") {
        const k = catalogueKpi?.get(j.id);
        b.className = "jeton jeton-kpi" + (k ? "" : " inconnu");
        b.title = k ? `${k.nom}${k.unite ? " (" + k.unite + ")" : ""}` : lib("saisie.js.kpi_inconnu");
        b.innerHTML = `<b></b><span class="nom-jeton"></span>${j.dec !== "N" ? '<span class="dec-jeton"></span>' : ""}`;
        b.querySelector("b").textContent = j.id;
        b.querySelector(".nom-jeton").textContent = k ? k.nom : lib("saisie.js.inconnu");
        if (j.dec !== "N") b.querySelector(".dec-jeton").textContent = j.dec;
      } else {
        b.className = "jeton " + (j.t === "op" ? "jeton-op" : "jeton-nb");
        b.textContent = j.t === "op" ? (SYMBOLE[j.v] || j.v) : decimale(j.v);
      }
      const x = document.createElement("button");
      x.type = "button"; x.className = "retirer-jeton"; x.innerHTML = `{% icone "x" %}`; x.title = lib("saisie.js.retirer_jeton"); x.setAttribute("aria-label", x.title); x.dataset.indice = i;
      b.appendChild(x);
      zone.appendChild(b);
    });
  }
  function modifierFormule(c, f) {
    const texte = c.querySelector("textarea");
    const jetons = decouper(texte.value);
    f(jetons);
    texte.value = assembler(jetons);
    dessinerJetons(c);
  }
  // règle de cohérence : niveau de contrôle recommandé d'après la granularité des KPI des deux formules (le niveau le
  // plus fin où tous ont une valeur) ; choisi d'office tant que la personne n'a pas choisi elle-même 
  function majNiveauRegle(form) {
    const bloc = form?.querySelector("[data-niveau-regle]");
    if (!bloc || !catalogueKpi) return;
    const labels = [...bloc.querySelectorAll(".niveau-radio")];
    const ordre = labels.map((l) => l.querySelector("input").value);
    const ids = [...form.querySelectorAll("[data-constructeur] textarea")].flatMap((t) => decouper(t.value).filter((j) => j.t === "kpi").map((j) => j.id));
    const rangs = ids.map((id) => ordre.indexOf(catalogueKpi.get(id)?.niveau)).filter((i) => i >= 0);
    const rec = rangs.length ? Math.min(...rangs) : -1;
    labels.forEach((l, i) => {
      l.querySelector(".badge-recommande").hidden = i !== rec;
      l.classList.toggle("trop-fin", rec >= 0 && i > rec);
      l.title = rec >= 0 && i > rec ? bloc.dataset.tropFin : "";
    });
    const aide = bloc.querySelector("[data-aide-niveau]");
    if (!aide.dataset.origine) aide.dataset.origine = aide.textContent;
    aide.textContent = rec >= 0 ? bloc.dataset.modeleAide.replace("{niveau}", labels[rec].dataset.nom) : aide.dataset.origine;
    if (rec >= 0 && !bloc.dataset.touche) labels[rec].querySelector("input").checked = true;
  }
  document.addEventListener("change", (e) => {
    if (e.target.matches("[data-niveau-regle] input[name=niveau]") && e.isTrusted) e.target.closest("[data-niveau-regle]").dataset.touche = "1";
  });
  async function initConstructeur(c) {
    await chargerKpis(c.dataset.kpisUrl);
    dessinerJetons(c);
  }
  function suggerer(c) {
    const q = c.querySelector("[data-recherche-kpi]").value.trim().toLowerCase();
    const ul = c.querySelector("[data-suggestions]");
    ul.innerHTML = "";
    if (!q || !catalogueKpi) { ul.hidden = true; return; }
    const trouves = [...catalogueKpi.values()].filter((k) => k.numerique !== false  // oui / non, liste : pas dans une formule
      && (k.id.toLowerCase().includes(q) || k.nom.toLowerCase().includes(q))).slice(0, 12);
    trouves.forEach((k, i) => {
      const li = document.createElement("li");
      li.dataset.id = k.id;
      if (i === 0) li.classList.add("active");
      li.innerHTML = '<b></b><span></span><small></small>';
      li.querySelector("b").textContent = k.id;
      li.querySelector("span").textContent = k.nom;
      li.querySelector("small").textContent = [k.type, k.unite, k.actif ? "" : lib("saisie.js.inactif")].filter(Boolean).join(" · ");
      ul.appendChild(li);
    });
    if (!trouves.length) ul.innerHTML = `<li class="vide-sugg">${echapper(lib("saisie.js.aucun_kpi_trouve"))}</li>`;
    ul.hidden = false;
  }
  function ajouterKpi(c, id) {
    const dec = c.querySelector("[data-decalage]").value;
    modifierFormule(c, (j) => j.push({ t: "kpi", id, dec }));
    const champ = c.querySelector("[data-recherche-kpi]");
    champ.value = ""; c.querySelector("[data-suggestions]").hidden = true; champ.focus();
  }
  document.addEventListener("input", (e) => {
    const c = e.target.closest("[data-constructeur]");
    if (!c) return;
    if (e.target.matches("[data-recherche-kpi]")) suggerer(c);
    if (e.target.matches("textarea")) dessinerJetons(c);
  });
  document.addEventListener("keydown", (e) => {
    const c = e.target.closest("[data-constructeur]");
    if (!c) return;
    if (e.target.matches("[data-recherche-kpi]")) {
      const items = [...c.querySelectorAll("[data-suggestions] li[data-id]")];
      const actif = items.findIndex((li) => li.classList.contains("active"));
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        const n = Math.max(0, Math.min(items.length - 1, actif + (e.key === "ArrowDown" ? 1 : -1)));
        items.forEach((li, i) => li.classList.toggle("active", i === n));
      }
      if (e.key === "Enter") { e.preventDefault(); if (items[actif]) ajouterKpi(c, items[actif].dataset.id); }
      if (e.key === "Escape") { c.querySelector("[data-suggestions]").hidden = true; e.stopPropagation(); }
    }
    if (e.target.matches("[data-nombre]") && e.key === "Enter") { e.preventDefault(); c.querySelector("[data-ajout-nombre]").click(); }
  });
  document.addEventListener("click", (e) => {
    const c = e.target.closest("[data-constructeur]");
    if (!c) { document.querySelectorAll("[data-suggestions]").forEach((u) => { u.hidden = true; }); return; }
    const li = e.target.closest("[data-suggestions] li[data-id]");
    if (li) { ajouterKpi(c, li.dataset.id); return; }
    const op = e.target.closest("[data-op]");
    if (op) { modifierFormule(c, (j) => j.push({ t: "op", v: op.dataset.op })); return; }
    if (e.target.closest("[data-ajout-nombre]")) {
      const champ = c.querySelector("[data-nombre]"), v = String(lireNombre(champ.value.trim()));
      if (/^\d+(\.\d+)?$/.test(v)) { modifierFormule(c, (j) => j.push({ t: "nb", v })); champ.value = ""; }
      else toast(lib("saisie.js.nombre_exemple"));
      return;
    }
    if (e.target.closest("[data-retour]")) { modifierFormule(c, (j) => j.pop()); return; }
    if (e.target.closest("[data-vider]")) { modifierFormule(c, (j) => j.splice(0)); return; }
    const x = e.target.closest(".retirer-jeton");
    if (x) { modifierFormule(c, (j) => j.splice(Number(x.dataset.indice), 1)); }
  });

