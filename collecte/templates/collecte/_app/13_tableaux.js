{# tableaux en arbre et tableaux triables, filtres demandés par l’adresse, fermeture de la fonction englobante #}
  // ---------------------------------------------------------------- tableaux en arbre (Tableau de bord, Consolidation)
  // lignes tr[data-org], tr[data-parent] ; bouton [data-deplier] ; une ligne fermée cache toute sa descendance. À
  // l'ouverture : ouvert jusqu'au niveau data-arbre-ouvert (le sommet et le niveau juste en dessous). Sans JavaScript :
  // toutes les lignes sont visibles.
  function preparerArbre(table) {
    const lignes = [...table.querySelectorAll("tbody tr[data-org]")];
    const enfants = (id) => lignes.filter((tr) => tr.dataset.parent === id);
    const montrer = (tr, visible) => {
      tr.hidden = !visible;
      const b = tr.querySelector("[data-deplier]");
      if (b) enfants(tr.dataset.org).forEach((e) => montrer(e, visible && b.getAttribute("aria-expanded") === "true"));
    };
    const basculer = (b, ouvert) => {
      b.setAttribute("aria-expanded", ouvert ? "true" : "false");
      const tr = b.closest("tr");
      enfants(tr.dataset.org).forEach((e) => montrer(e, ouvert && !tr.hidden));
    };
    const toutes = (ouvert) => {
      lignes.forEach((tr) => tr.querySelector("[data-deplier]")?.setAttribute("aria-expanded", ouvert ? "true" : "false"));
      lignes.filter((tr) => !tr.dataset.parent).forEach((tr) => montrer(tr, true));
    };
    const initial = () => {
      const jusqua = +(table.dataset.arbreOuvert || 1);
      toutes(true);
      lignes.forEach((tr) => { const b = tr.querySelector("[data-deplier]"); if (b && +tr.dataset.prof >= jusqua) basculer(b, false); });
    };
    initial();
    table.addEventListener("click", (e) => {
      const b = e.target.closest("[data-deplier]");
      if (b) basculer(b, b.getAttribute("aria-expanded") !== "true");
    });
    document.querySelectorAll(`[data-arbre-tout][data-cible="${table.id}"]`).forEach((bouton) => {
      bouton.hidden = !table.querySelector("[data-deplier]");
      bouton.addEventListener("click", () => toutes(bouton.dataset.arbreTout === "ouvrir"));
    });
    return { lignes, toutes, initial };
  }
  const arbres = {};
  document.querySelectorAll("table[data-arbre-table]").forEach((t) => { arbres[t.id] = preparerArbre(t); });

  // Tableau de bord : « Seulement en retard » (les organisations en retard et celles qui en ont en dessous, tout déplié)
  const filtreRetard = document.querySelector("[data-filtre-retard]");
  if (filtreRetard && arbres["table-orgs"]) {
    const a = arbres["table-orgs"];
    filtreRetard.closest("label").hidden = false;
    const vide = document.querySelector("[data-vide-retard]");
    const appliquer = () => {
      if (filtreRetard.checked) {
        a.lignes.forEach((tr) => {
          tr.querySelector("[data-deplier]")?.setAttribute("aria-expanded", "true");
          tr.hidden = !(tr.dataset.retard === "1" || +(tr.dataset.dessous || 0) > 0);
        });
      } else a.initial();
      if (vide) vide.hidden = !filtreRetard.checked || a.lignes.some((tr) => !tr.hidden);
    };
    filtreRetard.addEventListener("change", appliquer);
    document.addEventListener("click", (e) => {
      if (!e.target.closest("[data-voir-retards]")) return;
      e.preventDefault();
      document.getElementById("onglet-organisations")?.click();
      filtreRetard.checked = true;
      appliquer();
      const carte = document.getElementById("detail-tdb");
      carte?.scrollIntoView({ behavior: "smooth", block: "start" });
      filtreRetard.focus({ preventScroll: true });
    });
  }

  // Tableau de bord : onglets du détail (Organisations, SPOC, Thèmes, Campagnes) ; l'onglet choisi est gardé dans
  // l'adresse (#spoc…) et suit le changement d'ordre des lignes. Sans JavaScript : toutes les parties l'une sous l'autre.
  const blocOnglets = document.querySelector("[data-onglets-tdb]");
  if (blocOnglets) {
    const liste = blocOnglets.querySelector('[role="tablist"]');
    const onglets = [...liste.querySelectorAll('[role="tab"]')];
    liste.hidden = false;
    blocOnglets.classList.add("avec-onglets");
    const choisir = (onglet, focus) => {
      onglets.forEach((o) => {
        const actif = o === onglet;
        o.setAttribute("aria-selected", actif ? "true" : "false");
        o.tabIndex = actif ? 0 : -1;
        document.getElementById(o.getAttribute("aria-controls")).hidden = !actif;
      });
      const nom = onglet.id.replace("onglet-", "");
      history.replaceState(null, "", nom === "organisations" ? location.pathname + location.search : "#" + nom);
      blocOnglets.querySelectorAll("[data-garder-onglet]").forEach((l) => { l.hash = nom === "organisations" ? "" : nom; });
      if (focus) onglet.focus();
    };
    onglets.forEach((o) => o.addEventListener("click", () => choisir(o, false)));
    liste.addEventListener("keydown", (e) => {
      const i = onglets.indexOf(document.activeElement);
      if (i < 0) return;
      const j = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: onglets.length - 1 }[e.key];
      if (j === undefined) return;
      e.preventDefault();
      choisir(onglets[(j + onglets.length) % onglets.length], true);
    });
    choisir(onglets.find((o) => "#" + o.id.replace("onglet-", "") === location.hash) || onglets[0], false);
  }

  // ---------------------------------------------------------------- tableaux triables (DESIGN.md, Sortable-Columns)
  // table[data-triable][id] ; th[data-tri="texte|nombre|date"] (data-tri-col : nom de la colonne dans l'adresse, sinon
  // son rang). Le titre devient un bouton (clic : tri croissant, nouveau clic : décroissant), aria-sort sur le th, flèche
  // visible ; un th qui contient déjà des boutons [data-tri-col] trie selon plusieurs clés (« KPI · organisation »).
  // Valeur d'une case : data-tri-<col>, sinon data-tri, sinon son texte ; vide toujours en dernier ; nombres comme
  // nombres, textes selon la langue. Tri gardé dans l'adresse (?tri-<id>=col ou -col). data-tri-arbre : lignes
  // tr[data-org][data-parent], triées à l'intérieur de chaque niveau (la hiérarchie reste). data-tri-serveur : la page
  // ne montre qu'une partie des lignes, le tri se fait en rechargeant la page (le serveur trie avant de couper).
  const COLLATION = new Intl.Collator(LANGUE, { numeric: true, sensitivity: "base" });
  const iconeTri = (rang) => document.getElementById("icones-tri")?.content.children[rang]?.cloneNode(true);
  let annonceTri = null;
  function annoncerTri(texte) {
    if (!annonceTri) {
      annonceTri = document.createElement("div");
      annonceTri.className = "visuellement-cache";
      annonceTri.setAttribute("role", "status");
      document.body.appendChild(annonceTri);
    }
    annonceTri.textContent = "";
    setTimeout(() => { annonceTri.textContent = texte; }, 50);
  }
  function preparerTri(table) {
    if (!table.id || table.dataset.triPret) return;
    table.dataset.triPret = "1";
    const param = "tri-" + table.id;
    const boutons = [];
    [...(table.tHead?.rows[0]?.cells || [])].forEach((th, rang) => {
      if (!th.dataset.tri) return;
      let liste = [...th.querySelectorAll("button[data-tri-col]")];
      if (!liste.length) {
        const b = document.createElement("button");
        b.type = "button";
        b.dataset.triCol = th.dataset.triCol || String(rang);
        b.append(...th.childNodes);
        th.appendChild(b);
        liste = [b];
      }
      liste.forEach((b) => {
        b.type = "button";
        b.classList.add("tri-entete");
        b.dataset.triType = b.dataset.triType || th.dataset.tri;
        const i = iconeTri(0);
        if (i) b.appendChild(i);
        boutons.push({ b, th, rang });
      });
    });
    if (!boutons.length) return;
    [...table.tBodies].forEach((tb) => [...tb.rows].forEach((tr, i) => { tr.dataset.triRang = i; }));
    const valeur = (tr, x) => {
      const td = tr.cells[x.rang];
      if (!td) return null;
      let v = td.getAttribute("data-tri-" + x.b.dataset.triCol) ?? td.getAttribute("data-tri");
      const brut = v === null;
      v = (brut ? td.textContent : v).trim();
      if (!v || (brut && /^[—–-]$/.test(v))) return null;
      if (x.b.dataset.triType === "nombre") { const n = brut ? lireNombre(v) : parseFloat(v); return Number.isNaN(n) ? null : n; }
      return v;
    };
    const comparer = (x, sens) => (a, b) => {
      const va = valeur(a, x), vb = valeur(b, x);
      if (va === null || vb === null) return va === vb ? +a.dataset.triRang - +b.dataset.triRang : va === null ? 1 : -1;
      const r = typeof va === "number" ? va - vb : x.b.dataset.triType === "date" ? (va < vb ? -1 : va > vb ? 1 : 0) : COLLATION.compare(va, vb);
      return r * sens || +a.dataset.triRang - +b.dataset.triRang;
    };
    const marquer = (x, sens) => {
      boutons.forEach((y) => {
        y.th.removeAttribute("aria-sort");
        y.b.classList.remove("trie");
        y.b.querySelector(".icone-tri")?.replaceWith(iconeTri(0));
      });
      x.th.setAttribute("aria-sort", sens > 0 ? "ascending" : "descending");
      x.b.classList.add("trie");
      x.b.querySelector(".icone-tri")?.replaceWith(iconeTri(sens > 0 ? 1 : 2));
      table.dataset.triActif = (sens < 0 ? "-" : "") + x.b.dataset.triCol;
    };
    const trier = (x, sens) => {
      const cmp = comparer(x, sens);
      [...table.tBodies].forEach((tb) => {
        const lignes = [...tb.rows];
        if (table.hasAttribute("data-tri-arbre")) {  // à l'intérieur de chaque niveau : la hiérarchie reste
          const ids = new Set(lignes.map((tr) => tr.dataset.org));
          const enfants = new Map();
          lignes.forEach((tr) => {
            const p = ids.has(tr.dataset.parent) ? tr.dataset.parent : "";
            if (!enfants.has(p)) enfants.set(p, []);
            enfants.get(p).push(tr);
          });
          const ordre = [];
          const visiter = (p) => (enfants.get(p) || []).sort(cmp).forEach((tr) => { ordre.push(tr); visiter(tr.dataset.org); });
          visiter("");
          tb.append(...ordre);
        } else tb.append(...lignes.sort(cmp));
      });
      marquer(x, sens);
    };
    const nomColonne = (x) => (x.b.textContent || "").trim();
    boutons.forEach((x) => x.b.addEventListener("click", () => {
      const col = x.b.dataset.triCol;
      const sens = table.dataset.triActif === col ? -1 : 1;
      const u = new URL(location.href);
      u.searchParams.set(param, (sens < 0 ? "-" : "") + col);
      if (table.hasAttribute("data-tri-serveur")) { location.assign(u.toString()); return; }
      history.replaceState(history.state, "", u.toString());
      trier(x, sens);
      annoncerTri(lib(sens > 0 ? "saisie.js.tri.croissant" : "saisie.js.tri.decroissant", { colonne: nomColonne(x) }));
    }));
    const demande = new URLSearchParams(location.search).get(param) || "";
    const x = boutons.find((y) => y.b.dataset.triCol === demande.replace(/^-/, ""));
    if (x) trier(x, demande.startsWith("-") ? -1 : 1);
  }
  function preparerTris(racine) { racine.querySelectorAll("table[data-triable]").forEach(preparerTri); }
  preparerTris(document);

  // Saisie : « ?statut=a_saisir » (chiffres cliquables du tableau de bord) choisit la pastille de ce statut
  const statutDemande = new URLSearchParams(location.search).get("statut");
  if (statutDemande && document.querySelector(`[data-filtre-statut="${CSS.escape(statutDemande)}"]`)) filtresStatut.add(statutDemande);

  // Saisie : « ?q=… » (lien vers la Saisie filtrée sur un KPI) remplit la recherche de la
  // page ; les sections qui contiennent un résultat s'ouvrent (longue liste repliée de « Tout ce qui m'est attribué »)
  const rechercheDemandee = new URLSearchParams(location.search).get("q");
  const champRecherche = document.getElementById("recherche");
  if (rechercheDemandee && champRecherche) {
    champRecherche.value = rechercheDemandee.slice(0, 100);
    champRecherche.dispatchEvent(new Event("input", { bubbles: true }));
  }

  majGrille();
  appliquerFiltres(!!(rechercheDemandee && champRecherche));
  if (rechercheDemandee && champRecherche) {
    document.querySelectorAll("#liste details.section:not([hidden])").forEach((d) => {
      if (d.querySelector("tr.ligne:not([hidden])")) d.open = true;
    });
    libelleReplier();
  }

  // ---------------------------------------------------------------- longue liste « Tout ce qui m'est attribué » : sections chargées après la page
  // (échelle, P-A9) La page part avec ses premières sections ; les autres arrivent sans leurs lignes (.chargement-section
  // [data-a-charger] à la place du tableau) et
  // sont remplies d'une seule demande, aussitôt la page affichée. Jusque-là, recherche et filtres portent sur les lignes
  // déjà là ; à l'arrivée, ils s'appliquent à toute la liste, comme avant. Une section dont le titre ne correspond plus
  // (liste changée entre-temps), ou une demande qui échoue : la section garde son lien vers la liste entière (?complet=1).
  const listeReste = document.querySelector("#liste[data-url-reste]");
  if (listeReste && listeReste.querySelector("[data-a-charger]")) {
    const attentes = [...listeReste.querySelectorAll(".chargement-section[data-a-charger]")];
    attentes.forEach((p) => { p.dataset.lien = p.innerHTML; p.textContent = lib("saisie.js.chargement_sections"); });
    const remettreLiens = () => listeReste.querySelectorAll(".chargement-section[data-a-charger][data-lien]")
      .forEach((p) => { p.innerHTML = p.dataset.lien; });
    fetch(listeReste.dataset.urlReste, { credentials: "same-origin" })
      .then((rep) => { if (!rep.ok) throw new Error(String(rep.status)); return rep.text(); })
      .then((html) => {
        const modele = document.createElement("template");
        modele.innerHTML = html;
        const titre = (d) => d.querySelector(":scope > summary .titre-section")?.textContent;
        modele.content.querySelectorAll("details[data-section]").forEach((neuve) => {
          const vide = listeReste.querySelector(`.chargement-section[data-a-charger="${CSS.escape(neuve.dataset.section)}"]`)?.closest("details");
          if (!vide || titre(vide) !== titre(neuve)) return;
          neuve.open = vide.open;  // ouverte entre-temps : elle le reste
          vide.replaceWith(neuve);
        });
        remettreLiens();
        const recherche = document.getElementById("recherche");
        const filtre = !!(recherche && recherche.value.trim()) || filtresStatut.size > 0
          || [...document.querySelectorAll("select[data-panneau-filtre]")].some(filtreActif);
        appliquerFiltres(filtre);  // le nombre de lignes affichées n'est relu que si la personne a filtré
        if (rechercheDemandee && champRecherche) {
          listeReste.querySelectorAll("details.section:not([hidden])").forEach((d) => {
            if (d.querySelector("tr.ligne:not([hidden])")) d.open = true;
          });
        }
        libelleReplier();
      })
      .catch(remettreLiens);
  }
})();
