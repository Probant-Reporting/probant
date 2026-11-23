{# filtres : champ avec libellé et panneau à cocher, recherche, statut, type, SPOC, sections repliables #}
  // ---------------------------------------------------------------- filtres : champ avec libellé et panneau à cocher
  // Modèle retenu (DESIGN.md, « Filters »). Dans le gabarit : .champ-filtre > label + select[data-panneau-filtre]
  // (sans JavaScript, la liste du navigateur reste). Ici, la liste devient un bouton qui ouvre un panneau : recherche
  // (plus de 8 choix), cases à cocher (data-multiple : plusieurs valeurs) ou choix unique, nombre de lignes de chaque
  // choix (option[data-nb]). Le filtre s'applique dès qu'on coche (événement « change » sur la liste) ; data-envoyer :
  // le formulaire part à la fermeture du panneau (pages filtrées par le serveur). data-valeurs : valeurs cochées au
  // chargement ; data-defaut : valeur qui ne compte pas comme un filtre actif.
  function valeursFiltre(id) {
    const s = typeof id === "string" ? document.getElementById(id) : id;
    return s ? [...s.selectedOptions].map((o) => o.value).filter(Boolean) : [];
  }
  function filtreActif(sel) {
    const v = valeursFiltre(sel).join(",");
    return !!v && v !== (sel.dataset.defaut || "");
  }
  // page rechargée par un filtre (filtré par le serveur) : le focus revient sur le bouton du champ, comme sans rechargement
  // (DESIGN.md, « Filters » : Échap ferme et rend le focus)
  const CLE_FOCUS = "focus-filtre";
  function focusApresRechargement(id) {
    try { sessionStorage.setItem(CLE_FOCUS, id); } catch (e) { /* stockage indisponible : focus en haut de page */ }
  }
  function rendreFocusApresRechargement() {
    let id = null;
    try { id = sessionStorage.getItem(CLE_FOCUS); sessionStorage.removeItem(CLE_FOCUS); } catch (e) { return; }
    if (id) document.getElementById(id)?.focus({ preventScroll: true });
  }
  function initChampsFiltre(racine) {
    racine.querySelectorAll("select[data-panneau-filtre]").forEach((sel) => {
      if (sel.dataset.pret) return;
      sel.dataset.pret = "1";
      const multiple = sel.hasAttribute("data-multiple"), serveur = sel.hasAttribute("data-envoyer");
      const etiquette = sel.labels && sel.labels[0];
      const optTous = [...sel.options].find((o) => o.value === "");
      const tous = optTous ? optTous.textContent.trim() : lib("commun.tous");
      if (multiple) {
        const initiales = sel.dataset.valeurs !== undefined ? sel.dataset.valeurs.split(",").filter(Boolean) : (sel.value ? [sel.value] : []);
        if (optTous) optTous.remove();
        sel.multiple = true;
        [...sel.options].forEach((o) => { o.selected = initiales.includes(o.value); });
      }
      const ancre = document.createElement("span");
      ancre.className = "ancre-filtre";
      const bouton = document.createElement("button");
      bouton.type = "button";
      bouton.className = "liste-filtre";
      bouton.id = (sel.id || "filtre") + "-bouton";
      bouton.setAttribute("aria-haspopup", "dialog");
      bouton.setAttribute("aria-expanded", "false");
      sel.after(ancre);
      ancre.append(bouton);
      sel.hidden = true;
      if (etiquette) {
        if (!etiquette.id) etiquette.id = bouton.id + "-libelle";
        etiquette.htmlFor = bouton.id;
        bouton.setAttribute("aria-labelledby", etiquette.id + " " + bouton.id);
      } else if (sel.getAttribute("aria-label")) bouton.setAttribute("aria-label", sel.getAttribute("aria-label"));
      const nomFiltre = etiquette ? etiquette.textContent.trim() : (sel.getAttribute("aria-label") || "");
      let panneau = null, modifie = false;
      const choisies = () => [...sel.selectedOptions].filter((o) => o.value);
      function maj() {
        const ch = choisies();
        bouton.textContent = "";
        const texte = document.createElement("span");
        texte.className = "texte-filtre";
        texte.textContent = ch.length ? ch[0].textContent.trim() : tous;
        bouton.append(texte);
        if (ch.length > 1) {
          const plus = document.createElement("span");
          plus.className = "plus-filtre";
          plus.textContent = "+" + (ch.length - 1);
          bouton.append(plus);
        }
        bouton.classList.toggle("actif", filtreActif(sel));
      }
      sel._majFiltre = maj;
      function envoyer() { if (sel.form) { if (sel.form.requestSubmit) sel.form.requestSubmit(); else sel.form.submit(); } }
      function fermer(rendreFocus) {
        if (!panneau) return;
        panneau.remove();
        panneau = null;
        bouton.setAttribute("aria-expanded", "false");
        if (rendreFocus) bouton.focus();
        if (serveur && modifie) { modifie = false; if (rendreFocus) focusApresRechargement(bouton.id); envoyer(); }
      }
      sel._fermerFiltre = fermer;
      function changer() {
        maj();
        if (serveur) modifie = true;
        else sel.dispatchEvent(new Event("change", { bubbles: true }));
      }
      function ouvrir() {
        document.querySelectorAll("select[data-panneau-filtre]").forEach((x) => { if (x !== sel && x._fermerFiltre) x._fermerFiltre(false); });
        document.querySelectorAll("details.menu-deroulant[open]").forEach((d) => { d.open = false; });
        const opts = [...sel.options].filter((o) => (multiple ? o.value : true));
        panneau = document.createElement("div");
        panneau.className = "panneau-filtre";
        panneau.setAttribute("role", "dialog");
        if (nomFiltre) panneau.setAttribute("aria-label", nomFiltre);
        let champ = null;
        if (opts.length > 8) {
          champ = document.createElement("input");
          champ.type = "search";
          champ.placeholder = lib("commun.rechercher");
          champ.setAttribute("aria-label", lib("commun.filtres.chercher_dans", { filtre: nomFiltre }));
          panneau.append(champ);
        }
        const liste = document.createElement("div");
        liste.className = "choix-panneau";
        let caseTout = null;
        if (multiple && opts.length > 1) {
          const l = document.createElement("label");
          l.className = "tout-panneau";
          caseTout = document.createElement("input");
          caseTout.type = "checkbox";
          l.append(caseTout, document.createTextNode(lib("commun.filtres.tout_selectionner")));
          liste.append(l);
        }
        const lignes = opts.map((o) => {
          const l = document.createElement("label");
          const c = document.createElement("input");
          c.type = multiple ? "checkbox" : "radio";
          c.name = bouton.id + "-choix";
          c.checked = o.selected;
          const nom = document.createElement("span");
          nom.className = "nom-choix";
          nom.textContent = o.textContent.trim();
          l.append(c, nom);
          if (o.dataset.nb !== undefined) {
            const nb = document.createElement("span");
            nb.className = "nb-choix";
            nb.textContent = Number(o.dataset.nb).toLocaleString(LANGUE);
            l.append(nb);
            if (o.dataset.nb === "0") l.classList.add("zero");
          }
          c.addEventListener("change", () => {
            if (multiple) o.selected = c.checked; else sel.value = o.value;
            etat();
            changer();
            if (!multiple) fermer(true);
          });
          liste.append(l);
          return { l, c, o, texte: nom.textContent.toLowerCase() };
        });
        const aucun = document.createElement("p");
        aucun.className = "aucun-choix";
        aucun.textContent = lib("commun.filtres.aucun_choix");
        aucun.hidden = true;
        liste.append(aucun);
        panneau.append(liste);
        const pied = document.createElement("div");
        pied.className = "pied-panneau";
        const compte = document.createElement("span");
        const effacer = document.createElement("button");
        effacer.type = "button";
        effacer.className = "lien";
        effacer.textContent = lib("commun.filtres.effacer");
        pied.append(compte, effacer);
        if (serveur && multiple) {
          const appliquer = document.createElement("button");
          appliquer.type = "button";
          appliquer.className = "compact";
          appliquer.textContent = lib("commun.filtres.appliquer");
          appliquer.addEventListener("click", () => fermer(true));
          pied.append(appliquer);
        }
        if (multiple || optTous) panneau.append(pied);
        function etat() {
          const n = choisies().length;
          compte.textContent = multiple ? lib("commun.filtres.selection", { n }) : "";
          effacer.hidden = !n;
          if (caseTout) {
            const visibles = lignes.filter((x) => !x.l.hidden);
            const coches = visibles.filter((x) => x.c.checked).length;
            caseTout.checked = !!visibles.length && coches === visibles.length;
            caseTout.indeterminate = coches > 0 && coches < visibles.length;
          }
        }
        if (caseTout) caseTout.addEventListener("change", () => {
          lignes.forEach((x) => { if (!x.l.hidden) { x.c.checked = caseTout.checked; x.o.selected = caseTout.checked; } });
          etat();
          changer();
        });
        effacer.addEventListener("click", () => {
          if (multiple) lignes.forEach((x) => { x.c.checked = false; x.o.selected = false; });
          else { sel.value = ""; lignes.forEach((x) => { x.c.checked = x.o.value === ""; }); }
          etat();
          changer();
          if (!multiple) fermer(true); else (champ || lignes[0]?.c || bouton).focus();
        });
        if (champ) champ.addEventListener("input", () => {
          const q = champ.value.trim().toLowerCase();
          let n = 0;
          lignes.forEach((x) => { x.l.hidden = !!q && !x.texte.includes(q); if (!x.l.hidden) n++; });
          aucun.hidden = n > 0;
          if (caseTout) caseTout.parentNode.hidden = !n;
          etat();
        });
        // flèches : d'un choix à l'autre ; Échap : ferme et rend le focus au bouton (sans fermer le panneau de saisie)
        panneau.addEventListener("keydown", (e) => {
          if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); fermer(true); return; }
          if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
          const cases = [...panneau.querySelectorAll("label:not([hidden]) input")];
          const i = cases.indexOf(document.activeElement);
          if (i < 0 && document.activeElement !== champ) return;
          e.preventDefault();
          const j = e.key === "ArrowDown" ? Math.min(cases.length - 1, i + 1) : i - 1;
          if (j < 0) (champ || cases[0]).focus(); else cases[j].focus();
        });
        etat();
        ancre.append(panneau);
        bouton.setAttribute("aria-expanded", "true");
        // le panneau reste dans l'écran : aligné à droite du bouton s'il dépasse
        panneau.classList.toggle("a-droite", panneau.getBoundingClientRect().right > document.documentElement.clientWidth - 8);
        (champ || (lignes.find((x) => x.c.checked) || lignes[0])?.c || bouton).focus({ preventScroll: true });
      }
      bouton.addEventListener("click", () => { if (panneau) fermer(true); else ouvrir(); });
      bouton.addEventListener("keydown", (e) => {
        if (e.key === "ArrowDown" && !panneau) { e.preventDefault(); ouvrir(); }
        // panneau sans aucun choix : le focus reste sur le bouton, Échap doit fermer quand même
        if (e.key === "Escape" && panneau) { e.preventDefault(); e.stopPropagation(); fermer(true); }
      });
      ancre.addEventListener("focusout", (e) => { if (panneau && e.relatedTarget && !ancre.contains(e.relatedTarget)) fermer(false); });
      document.addEventListener("click", (e) => { if (panneau && !ancre.contains(e.target)) fermer(false); });
      maj();
    });
  }
  // Sous la barre de filtres : « 37 résultats sur 1 823 » et « Effacer les filtres », seulement quand un filtre est actif.
  // actif : ce que la page sait en plus (pastilles de statut…) ; la recherche et les champs de la barre sont lus ici.
  function majEtatFiltres(visibles, total, actif) {
    const etat = document.querySelector(".etat-filtres");
    if (!etat) return;
    const barre = etat.closest(".barre-filtres") || document;
    const filtre = !!actif || [...barre.querySelectorAll("select[data-panneau-filtre]")].some(filtreActif)
      || [...barre.querySelectorAll("input[type=search]")].some((i) => i.value.trim())
      || [...barre.querySelectorAll("input[type=checkbox][data-filtre-case]")].some((c) => c.checked);
    const compte = etat.querySelector("[data-compte-filtres]");
    if (compte) {
      // annoncé aux lecteurs d'écran, sauf là où la page annonce déjà le nombre de KPI affichés (#annonce-filtres)
      if (!document.getElementById("annonce-filtres")) compte.setAttribute("role", "status");
      compte.hidden = !filtre || total === undefined;
      if (total !== undefined) compte.textContent = lib("commun.filtres.compte", { n: visibles, nombre: visibles.toLocaleString(LANGUE), total: total.toLocaleString(LANGUE) });
    }
    const effacer = etat.querySelector("[data-reinitialiser-filtres]");
    if (effacer) effacer.hidden = !filtre;
  }
  function viderFiltres(barre) {
    barre.querySelectorAll("select[data-panneau-filtre]").forEach((sel) => {
      const defaut = (sel.dataset.defaut || "").split(",").filter(Boolean);
      if (sel.multiple) [...sel.options].forEach((o) => { o.selected = defaut.includes(o.value); }); else sel.value = defaut[0] || "";
      if (sel._majFiltre) sel._majFiltre();
    });
    barre.querySelectorAll("input[type=search]").forEach((i) => { i.value = ""; });
    barre.querySelectorAll("input[type=checkbox][data-filtre-case]").forEach((c) => { c.checked = false; });
  }

  // ---------------------------------------------------------------- filtres (recherche, statut, type)
  // pastilles de statut cumulables (Validé + Brouillon…) ; « Total » les retire toutes ; filtre « Personne (SPOC) »,
  // combiné à la recherche et aux pastilles 
  const filtresStatut = new Set();
  // annoncer : la personne vient de filtrer (pastille, recherche, type) ; le nombre de lignes affichées est lu par le
  // lecteur d'écran (#annonce-filtres). Jamais après un enregistrement ou un rafraîchissement du bandeau.
  let minuteurAnnonce = null;
  function annoncerFiltres(visibles, delai) {
    const zone = document.getElementById("annonce-filtres");
    if (!zone) return;
    const texte = visibles ? lib("saisie.js.kpi_affiches", { n: visibles }) : lib("saisie.js.aucun_resultat");
    clearTimeout(minuteurAnnonce);
    // la zone est vidée puis réécrite un peu après : un même nombre, deux fois de suite, est relu
    minuteurAnnonce = setTimeout(() => {
      zone.textContent = "";
      minuteurAnnonce = setTimeout(() => { zone.textContent = texte; }, 50);
    }, delai || 0);
  }
  function appliquerFiltres(annoncer, delai) {
    const q = (document.getElementById("recherche")?.value || "").trim().toLowerCase();
    const types = valeursFiltre("filtre-type");  // catalogue : un ou plusieurs types de saisie
    const spocs_choisis = valeursFiltre("filtre-spoc");  // plusieurs personnes à la fois
    // champs de filtre déclarés dans le gabarit : data-attribut="role" compare à tr.dataset.role ; data-liste : la ligne
    // porte plusieurs valeurs séparées par un espace ou une virgule
    const declares = [...document.querySelectorAll("select[data-panneau-filtre][data-attribut]")]
      .map((sel) => ({ attr: sel.dataset.attribut, vals: valeursFiltre(sel), liste: sel.hasAttribute("data-liste") })).filter((f) => f.vals.length);
    const traduire = document.getElementById("filtre-traduction")?.value || "";  // référentiel : KPI à traduire dans une langue
    const liste = document.getElementById("liste");
    if (liste) liste.dataset.traduction = traduire;  // les pastilles « à traduire » ne s'affichent qu'avec ce filtre
    let visibles = 0;
    document.querySelectorAll("#liste tr.ligne").forEach((tr) => {
      const spocs = (tr.dataset.spocs || "").split(",").filter(Boolean);
      const ok = (!q || tr.dataset.texte.includes(q))
        && (!filtresStatut.size || [...filtresStatut].some((f) => (f === "alerte" ? tr.dataset.alerte === "1" : tr.dataset.statut === f)))
        && (!types.length || types.includes(tr.dataset.type))
        && (!spocs_choisis.length || spocs_choisis.some((s) => (s === "aucun" ? !spocs.length && !tr.classList.contains("calculee") : spocs.includes(s))))
        && declares.every((f) => { const v = tr.dataset[f.attr] || ""; return f.liste ? v.split(/[ ,]+/).some((x) => f.vals.includes(x)) : f.vals.includes(v); })
        && (!traduire || (tr.dataset.aTraduire || "").split(" ").includes(traduire));
      tr.hidden = !ok;
      if (ok) visibles++;
    });
    document.querySelectorAll("#liste tbody").forEach((tb) => { tb.hidden = !tb.querySelector("tr.ligne:not([hidden])"); });
    document.querySelectorAll("#liste details.section:not(:has(> .chargement-section))").forEach((d) => {  // (section pas encore chargée : laissée telle quelle)
      const n = d.querySelectorAll("tr.ligne:not([hidden])").length;
      d.hidden = n === 0;
      const c = d.querySelector(".compte-section");
      if (c) c.textContent = n + " KPI";
    });
    document.querySelectorAll("#liste [data-groupe-ref]").forEach((g) => {  // catalogue : en-tête d'un référentiel au-dessus de ses thèmes
      const n = g.querySelectorAll("tr.ligne:not([hidden])").length;
      g.hidden = n === 0 && !!document.querySelector("#liste tr.ligne");
      const c = g.querySelector(".compte-groupe");
      if (c) c.textContent = n + " KPI";
    });
    const aucun = document.getElementById("aucun-resultat");
    if (aucun) aucun.hidden = !!(visibles || !document.querySelector("#liste tr.ligne"));
    document.querySelectorAll("[data-filtre-statut]").forEach((b) => {
      const choisi = b.dataset.filtreStatut ? filtresStatut.has(b.dataset.filtreStatut) : !filtresStatut.size;
      b.classList.toggle("actif", choisi);
      b.setAttribute("aria-pressed", choisi ? "true" : "false");
    });
    recompterFiltres();
    if (annoncer === true) annoncerFiltres(visibles, delai);
  }
  // nombre de lignes affichées, toutes pages : une ligne est hors filtre si la recherche (hidden) ou un champ de la barre
  // (hors-filtre, hors-filtre-grille) l'écarte ; une branche repliée de l'arbre (cache-arbre) n'est pas un filtre
  function recompterFiltres() {
    if (!document.querySelector(".etat-filtres")) return;
    const lignes = [...document.querySelectorAll("#liste tr.ligne, [data-grille] tr.ligne")];
    const visibles = lignes.filter((tr) => !tr.hidden && !tr.classList.contains("hors-filtre") && !tr.classList.contains("hors-filtre-grille")
      && !tr.closest("tbody.hors-filtre-grille")).length;
    // page déjà filtrée par le serveur : le total avant filtre est écrit dans le gabarit (data-total)
    const etat = document.querySelector(".etat-filtres");
    majEtatFiltres(visibles, etat.dataset.total !== undefined ? Number(etat.dataset.total) : lignes.length, filtresStatut.size > 0);
  }
  // filtre « Personne (SPOC) » : la liste est faite à partir des lignes de la page (cachée s'il n'y a qu'une personne)
  const choixSpoc = document.getElementById("filtre-spoc");
  if (choixSpoc) {
    const noms = new Map();
    document.querySelectorAll("#liste tr.ligne[data-spocs]").forEach((tr) => {
      const ids = (tr.dataset.spocs || "").split(",").filter(Boolean);
      const ns = (tr.dataset.spocsNoms || "").split("|");
      ids.forEach((id, i) => { if (!noms.has(id) && ns[i]) noms.set(id, ns[i]); });
    });
    // nombre de KPI de chaque personne, affiché dans le panneau du filtre
    const nbPar = new Map();
    let nbSans = 0;
    document.querySelectorAll("#liste tr.ligne[data-spocs]").forEach((tr) => {
      const ids = (tr.dataset.spocs || "").split(",").filter(Boolean);
      ids.forEach((id) => nbPar.set(id, (nbPar.get(id) || 0) + 1));
      if (!ids.length && !tr.classList.contains("calculee")) nbSans++;
    });
    [...noms].sort((a, b) => a[1].localeCompare(b[1])).forEach(([id, nom]) => { const o = new Option(nom, id); o.dataset.nb = nbPar.get(id) || 0; choixSpoc.add(o); });
    const sans = [...choixSpoc.options].find((o) => o.value === "aucun");
    if (sans) sans.dataset.nb = nbSans;
    choixSpoc.closest("[data-bloc-filtre-spoc]").hidden = noms.size < 2;
  }
  initChampsFiltre(document);  // après la liste des personnes : le panneau lit les choix de la liste
  rendreFocusApresRechargement();
  // champ de filtre rechargé par le serveur : chaque choix porte son adresse (catalogue : référentiel, état)
  document.addEventListener("change", async (e) => {
    if (!e.target.matches("select[data-aller-option]")) return;
    const sel = e.target, u = sel.selectedOptions[0]?.dataset.url;
    if (!u) return;
    // cases cochées (Attributions : sélection pour « Attribuer à… ») : le rechargement les perdrait. On le dit d'abord ;
    // « Annuler » remet le choix d'avant et garde la sélection (seconde recette, B8)
    const cochees = document.querySelectorAll(".choix-case:checked").length;
    if (cochees && !(await confirmer(lib("saisie.js.selection_perdue", { n: cochees }), sel))) {
      const avant = [...sel.options].find((o) => o.defaultSelected);
      if (avant) avant.selected = true;
      sel._majFiltre?.();
      document.getElementById((sel.id || "filtre") + "-bouton")?.focus();
      return;
    }
    focusApresRechargement((sel.id || "filtre") + "-bouton"); location.href = u;
  });
  document.addEventListener("change", (e) => {  // sélecteur de référentiel : mémorisé côté serveur, la page se recharge
    if (!e.target.matches("[data-choix-referentiel]")) return;
    const params = new URLSearchParams(location.search);
    params.set("ref", e.target.value);
    location.search = params.toString();
  });
  // recherche : annonce une fois la frappe arrêtée (pas à chaque lettre)
  document.addEventListener("input", (e) => { if (e.target.id === "recherche") appliquerFiltres(true, 700); });
  document.addEventListener("change", (e) => {
    if (["filtre-type", "filtre-traduction", "filtre-spoc"].includes(e.target.id) || e.target.matches?.("select[data-panneau-filtre][data-attribut]")) appliquerFiltres(true);
  });
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-filtre-statut]");
    if (b) {
      const f = b.dataset.filtreStatut;
      if (!f) filtresStatut.clear(); else if (filtresStatut.has(f)) filtresStatut.delete(f); else filtresStatut.add(f);
      appliquerFiltres(true);
    }
    const effacer = e.target.closest("[data-reinitialiser-filtres]");
    if (effacer && effacer.dataset.url) { location.href = effacer.dataset.url; return; }  // filtres appliqués par le serveur
    // champ rechargé par le serveur (data-aller-option, ex. « Actifs et inactifs » du catalogue) hors de sa valeur par
    // défaut : la page repart de l'adresse de la valeur par défaut (sinon le champ dirait « Actifs » sur une liste qui
    // montre aussi les inactifs)
    const parDefaut = (sel) => [...sel.options].find((o) => o.value === (sel.dataset.defaut || "") && o.dataset.url);
    const recharge = effacer && [...(effacer.closest(".barre-filtres") || document).querySelectorAll("select[data-aller-option]")]
      .find((sel) => filtreActif(sel) && parDefaut(sel));
    if (recharge) { location.href = parDefaut(recharge).dataset.url; return; }
    if (effacer) {  // « Effacer les filtres » : la recherche, les champs de la barre et les pastilles de statut
      filtresStatut.clear();
      viderFiltres(effacer.closest(".barre-filtres") || document);
      appliquerFiltres(true);
      majGrille();
      majArbre();
      (document.getElementById("recherche") || effacer).focus({ preventScroll: true });
    }
    const r = e.target.closest("[data-replier]");
    if (r) {  // une section repliée (longue liste de la vue « Tout ce qui m'est attribué », ou repliée à la main) : « Tout déplier », sinon « Tout replier »
      const sections = Array.from(document.querySelectorAll("#liste details.section:not([hidden])"));
      const ouvrir = sections.some((d) => !d.open);
      sections.forEach((d) => { d.open = ouvrir; });
      libelleReplier();
    }
  });
  function libelleReplier() {
    const r = document.querySelector("[data-replier]");
    if (!r) return;
    const ferme = Array.from(document.querySelectorAll("#liste details.section:not([hidden])")).some((d) => !d.open);
    r.textContent = ferme ? lib("saisie.js.deplier_tout") : lib("saisie.js.replier_tout");
  }
  // une section ouverte ou repliée à la main : le bouton dit ce qu'il fera (« toggle » ne remonte pas : capture)
  // (une seule mise à jour par image : « Tout déplier » ouvre des centaines de sections d'un coup)
  let libelleEnAttente = false;
  document.addEventListener("toggle", (e) => {
    if (libelleEnAttente || !e.target.matches?.("#liste details.section")) return;
    libelleEnAttente = true;
    requestAnimationFrame(() => { libelleEnAttente = false; libelleReplier(); });
  }, true);
  document.getElementById("recherche")?.addEventListener("keydown", (e) => { if (e.key === "Enter") e.preventDefault(); });
  // « aussi dans… » (KPI commun à un autre référentiel qui collecte la même période) : masqué par défaut, une case
  // l'affiche ; le choix est retenu sur ce navigateur. Sans JavaScript, les étiquettes restent visibles.
  (function () {
    const option = document.querySelector("[data-option-autres-refs]");
    const caseAutres = option?.querySelector("[data-voir-autres-refs]");
    let voir = false;
    try { voir = localStorage.getItem("saisie.autres_refs") === "1"; } catch (err) { voir = false; }
    const appliquer = () => document.documentElement.classList.toggle("masquer-autres-refs", !voir);
    appliquer();
    if (option && caseAutres && document.querySelector(".aussi-dans")) {
      option.hidden = false;
      caseAutres.checked = voir;
      caseAutres.addEventListener("change", () => {
        voir = caseAutres.checked;
        try { localStorage.setItem("saisie.autres_refs", voir ? "1" : "0"); } catch (err) { /* navigation privée */ }
        appliquer();
      });
    }
  })();

