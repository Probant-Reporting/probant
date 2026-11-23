// Visualisation v2 : dessin des vues (onglets), des visuels et de leurs tableaux de données.
// Le serveur calcule tout (collecte/visuels/) : valeurs, textes, totaux, parts, écarts, tris, « Autres ». Ce script ne
// fait que dessiner (Apache ECharts, copié dans l'outil : la page marche hors ligne) et envoyer les changements de
// filtres. Aucune couleur n'est écrite ici : elles viennent des variables CSS de l'installation (--viz-1 à --viz-8…).
// Écrit en ES2019, sans outil de construction (l'IT ne développe pas).
(function () {
  "use strict";
  const racine = document.querySelector("[data-visu]");
  if (!racine || typeof echarts === "undefined") return;

  const ctx = JSON.parse(document.getElementById("visu-contexte").textContent);
  let donnees = JSON.parse(document.getElementById("visu-donnees").textContent);
  const L = ctx.libelles || {};
  const langue = ctx.langue || "fr";
  const grille = racine.querySelector("[data-grille]");
  const formFiltres = racine.querySelector("[data-filtres-vue]");
  const annonce = document.getElementById("annonce-visu");
  const modele = document.getElementById("modele-visuel");
  const telephone = window.matchMedia("(max-width: 799px)");
  const tactile = window.matchMedia("(pointer: coarse)");
  const graphiques = {};  // id du visuel → instance ECharts
  const edition = { actif: false, brouillon: { visuels: [] }, modifie: false, selection: null, catalogue: null, calcul: {}, tri: null };
  let parametres = new URLSearchParams(location.search);
  let requete = null;  // AbortController de la requête en cours
  let minuteur = null;

  // ---------------------------------------------------------------- textes (fichiers de langue)
  function t(cle, valeurs) {
    let texte = L[cle];
    valeurs = valeurs || {};
    if (texte === undefined) return cle;
    if (typeof texte === "object") {
      const n = Math.abs(Number(valeurs.n));
      const un = L["format.zero_singulier"] === "1" ? n < 2 : n === 1;
      texte = (un ? texte.one : texte.other) || texte.other || "";
    }
    return texte.replace(/\{(\w+)\}/g, (m, nom) => (Object.prototype.hasOwnProperty.call(valeurs, nom) ? String(valeurs[nom]) : m));
  }
  const mots = { provisoire: "visu.etat.provisoire", attente: "visu.etat.attente" };
  function motEtat(etat) { return mots[etat] ? ` (${t(mots[etat])})` : ""; }
  function annoncer(texte) {
    if (!annonce) return;
    annonce.textContent = "";
    window.setTimeout(() => { annonce.textContent = texte; }, 30);
  }
  function toast(texte) {
    const el = document.getElementById("toast");
    if (!el || !texte) return;
    el.textContent = texte;
    el.style.display = "block";
    clearTimeout(toast.m);
    toast.m = setTimeout(() => { el.style.display = "none"; }, 3500);
  }
  // icônes dessinées (jeu Lucide, trait de 2) : jamais le caractère « × » ou « + » (DESIGN.md)
  const TRACES = { x: "M18 6 6 18M6 6l12 12", plus: "M5 12h14m-7-7v14" };
  function icone(nom) {
    const ns = "http://www.w3.org/2000/svg", svg = document.createElementNS(ns, "svg"), trace = document.createElementNS(ns, "path");
    svg.setAttribute("class", "icone-svg"); svg.setAttribute("viewBox", "0 0 24 24"); svg.setAttribute("aria-hidden", "true"); svg.setAttribute("focusable", "false");
    trace.setAttribute("d", TRACES[nom]); trace.setAttribute("fill", "none"); trace.setAttribute("stroke", "currentColor"); trace.setAttribute("stroke-width", "2");
    trace.setAttribute("stroke-linecap", "round"); trace.setAttribute("stroke-linejoin", "round");
    svg.appendChild(trace);
    return svg;
  }
  function el(nom, attributs, enfants) {
    const e = document.createElement(nom);
    Object.keys(attributs || {}).forEach((k) => {
      if (k === "texte") e.textContent = attributs[k];
      else if (k === "classe") e.className = attributs[k];
      else if (attributs[k] !== null && attributs[k] !== undefined && attributs[k] !== false) e.setAttribute(k, attributs[k]);
    });
    (enfants || []).forEach((x) => { if (x) e.appendChild(typeof x === "string" ? document.createTextNode(x) : x); });
    return e;
  }
  const enc = (s) => echarts.format.encodeHTML(String(s === null || s === undefined ? "" : s));

  // ---------------------------------------------------------------- thème tiré des variables CSS de l'installation
  // Deux thèmes : « outil » suit l'apparence de l'écran (claire ou sombre) ; « outil-clair » reprend toujours les
  // couleurs claires (sonde .apparence-claire), pour les images exportées (PNG) et l'impression, sur fond clair.
  const police = '"Source Sans 3", system-ui, sans-serif';  // libelle-ok : nom de police
  const sonde = el("div", { classe: "apparence-claire sonde", "aria-hidden": "true" });
  document.body.appendChild(sonde);
  function lireTheme(noeud, nom) {
    const css = getComputedStyle(noeud);
    const v = (n) => css.getPropertyValue(n).trim();
    const couleurs = [1, 2, 3, 4, 5, 6, 7, 8].map((i) => v(`--viz-${i}`));
    const c = {
      autres: v("--viz-autres"), pale: v("--viz-pale"), texte: v("--texte"), doux: v("--texte-doux"), bord: v("--bord"),
      surface: v("--surface"), valide: v("--barre-valide"), brouillon: v("--barre-brouillon"), neutre: v("--contour"),
    };
    echarts.registerTheme(nom, {
      color: couleurs, backgroundColor: "transparent",
      textStyle: { fontFamily: police, color: c.texte, fontSize: 13 },
      categoryAxis: { axisLine: { lineStyle: { color: c.bord } }, axisTick: { show: false }, axisLabel: { color: c.doux, fontSize: 12 },
                      splitLine: { show: false } },
      valueAxis: { axisLine: { show: false }, axisTick: { show: false }, axisLabel: { color: c.doux, fontSize: 12 },
                   splitLine: { lineStyle: { color: c.bord } } },
      legend: { textStyle: { color: c.texte, fontSize: 12 } },
      tooltip: { backgroundColor: c.surface, borderColor: c.bord, textStyle: { color: c.texte, fontSize: 13 } },
    });
    return { nom: nom, C: c };
  }
  let ecran = lireTheme(document.documentElement, "outil");
  const clair = lireTheme(sonde, "outil-clair");
  let theme = ecran;      // thème des graphiques dessinés maintenant (clair le temps d'une impression)
  let C = theme.C;        // couleurs lues par les options de chaque forme
  function avecTheme(t, faire) { const avant = C; C = t.C; try { return faire(); } finally { C = avant; } }
  // couleurs des graphiques réglées par l'admin trop claires (sous 3:1 sur les cartes ; 0 à 7 : séries, 8 : « Autres ») :
  // les valeurs de leurs séries sont toujours écrites (la palette fournie garde son affichage)
  const claires = new Set(ctx.viz_claires || []);
  const claire = (i) => claires.has(i);
  const decal = { symbol: "rect", dashArrayX: [1, 0], dashArrayY: [3, 5], rotation: -Math.PI / 4, color: "rgba(255,255,255,0.55)" };
  const compact = new Intl.NumberFormat(langue, { notation: "compact", maximumFractionDigits: 1 });
  function graduation(unite) {
    return (x) => (unite && unite.pourcentage ? t("format.pourcent", { valeur: compact.format(x) }) : compact.format(x));
  }
  function couper(s, n) { s = String(s || ""); return s.length > n ? `${s.slice(0, n - 1)}…` : s; }

  // ---------------------------------------------------------------- options ECharts de chaque forme
  function bulleHtml(categorie, lignes) {
    return lignes.map((l) => `<div class="ligne-bulle"><b>${enc(l.texte + motEtat(l.etat))}</b><span>${enc(l.libelle)}</span></div>`).join("")
      + (categorie ? `<div class="cat-bulle">${enc(categorie)}</div>` : "");
  }
  function lignesBulle(p, i) {
    return (p.series || []).filter((s) => s.textes && s.textes[i] !== undefined)
      .map((s) => ({ texte: s.textes[i], libelle: s.libelle, etat: s.etats ? s.etats[i] : "" }));
  }
  function texteLu(p, i) {
    const c = p.categories[i];
    const vals = lignesBulle(p, i).map((l) => `${l.texte}${motEtat(l.etat)}${(p.series || []).length > 1 ? ` (${l.libelle})` : ""}`);
    return `${c ? c.libelle : ""} : ${vals.join(" ; ")}`;
  }
  function donneesSerie(s, i, horizontal) {
    const valeurs = s.parts || s.valeurs;
    return valeurs.map((x, j) => {
      const etat = s.etats ? s.etats[j] : "valide";
      const d = { value: x, texte: s.textes ? s.textes[j] : "" };
      if (etat === "provisoire") d.itemStyle = { color: i === 0 ? C.pale : undefined, opacity: i === 0 ? 1 : 0.55, decal: decal };
      return d;
    });
  }
  function etiquette(p, s, mode) {
    if (mode === "aucune") return { show: false };
    return {
      show: true, position: "top", color: C.texte, fontSize: 12, fontWeight: 700,
      formatter: (q) => {
        if (mode === "derniere" && q.dataIndex !== (s.valeurs.length - 1)) return "";
        return q.data && q.value !== null && q.value !== undefined ? q.data.texte : "";
      },
    };
  }
  function base(p) {
    const tel = telephone.matches;
    return {
      animation: false,
      aria: { enabled: true, label: { description: p.resume }, decal: { show: false } },
      grid: { left: 8, right: 16, top: 28, bottom: (p.series || []).length > 1 ? 44 : 8, containLabel: true },
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, confine: true,
                 formatter: (params) => {
                   const i = (Array.isArray(params) ? params[0] : params).dataIndex;
                   return bulleHtml(p.categories[i] ? p.categories[i].libelle : "", lignesBulle(p, i));
                 } },
      legend: (p.series || []).length > 1 ? { bottom: 0, type: "scroll", icon: "roundRect", itemWidth: 12, itemHeight: 10 } : { show: false },
      textStyle: { fontFamily: police },
      _tel: tel,
    };
  }
  function optionBarres(p, opts) {
    const o = base(p);
    const options = p.options || {};
    const horizontal = p.axe === "organisations" && (telephone.matches || options.orientation === "horizontale");
    const cats = p.categories.map((c) => c.libelle);
    const axeCat = { type: "category", data: cats, triggerEvent: true,
                     axisLabel: { interval: 0, formatter: (s) => couper(s, horizontal || telephone.matches ? 18 : 24), hideOverlap: !horizontal } };
    const axeVal = { type: "value", axisLabel: { formatter: graduation(p.unite) }, max: p.unite && p.unite.pourcentage && !opts.empile ? (x) => Math.max(100, x.max) : null };
    if (horizontal) { axeCat.inverse = true; o.xAxis = axeVal; o.yAxis = axeCat; } else { o.xAxis = axeCat; o.yAxis = axeVal; }
    const mode = options.valeurs_ecrites || (p.axe === "periodes" && !opts.empile ? "derniere" : (opts.empile ? "aucune" : "toutes"));
    o.series = p.series.map((s, i) => {
      const forcee = claire(s.autres ? 8 : i);
      const label = { ...etiquette(p, s, forcee ? "toutes" : (cats.length > 12 && mode === "toutes" ? "derniere" : mode)),
                      position: horizontal ? "right" : "top" };
      // barres empilées : la valeur d'une série trop claire s'écrit dans sa part, sur une pastille de la couleur des cartes ;
      // celles qui se chevauchent (téléphone) restent dans « Voir les données »
      const empilee = opts.empile && forcee;
      if (empilee) Object.assign(label, { position: "inside", backgroundColor: C.surface, padding: [2, 4], borderRadius: 3 });
      return {
        type: "bar", name: s.libelle, data: donneesSerie(s, i, horizontal), barMaxWidth: 28, stack: opts.empile ? "total" : undefined,
        itemStyle: { borderRadius: opts.empile ? 0 : (horizontal ? [0, 4, 4, 0] : [4, 4, 0, 0]), color: s.autres ? C.autres : undefined },
        label, labelLayout: empilee ? { hideOverlap: true } : undefined, decal: (p.series.length >= 3 && opts.empile) ? decal : undefined,
      };
    });
    if (opts.empile && p.series.length >= 3) o.aria.decal = { show: true };
    return o;
  }
  function optionCourbe(p) {
    const o = base(p);
    o.tooltip.axisPointer = { type: "line" };
    o.xAxis = { type: "category", data: p.categories.map((c) => c.libelle), boundaryGap: false };
    o.yAxis = { type: "value", axisLabel: { formatter: graduation(p.unite) }, scale: false };
    o.series = p.series.map((s, i) => ({ type: "line", name: s.libelle, data: donneesSerie(s, i), symbol: "circle", symbolSize: 7,
      connectNulls: false, lineStyle: { width: 2.5 },
      label: { show: true, position: "top", align: "right", fontSize: 12, fontWeight: 700, color: C.texte,
               formatter: (q) => ((claire(i) || q.dataIndex === s.valeurs.length - 1) && q.data ? q.data.texte : "") } }));
    o.grid.right = 24;
    return o;
  }
  function optionAnneau(p) {
    const o = base(p);
    const options = p.options || {};
    const s = p.series[0];
    o.tooltip = { trigger: "item", confine: true, formatter: (q) => bulleHtml("", [{ texte: s.textes[q.dataIndex], libelle: p.categories[q.dataIndex].libelle, etat: s.etats[q.dataIndex] }]) };
    o.legend = { show: true, bottom: 0, left: "center", type: "plain", icon: "roundRect", itemWidth: 12, itemHeight: 10, itemGap: 14,
                 formatter: (nom) => { const i = p.categories.findIndex((c) => c.libelle === nom); return i >= 0 ? `${nom}  ${s.textes[i]}` : nom; } };
    const camembert = options.forme_anneau === "camembert";
    o.series = [{ type: "pie", radius: camembert ? [0, "58%"] : ["38%", "60%"], center: ["50%", "40%"], avoidLabelOverlap: true,
      label: { show: false }, itemStyle: { borderColor: C.surface, borderWidth: 2 },
      data: p.categories.map((c, i) => ({ name: c.libelle, value: s.valeurs[i], itemStyle: c.autres ? { color: C.autres } : (s.etats[i] === "provisoire" ? { decal: decal, opacity: 0.6 } : undefined) })) }];
    if (p.categories.length >= 3) o.aria.decal = { show: true };
    if (!camembert && options.total_centre !== false) {
      o.title = { text: p.total, subtext: t("visu.visuel.total"), left: "center", top: "33%", textStyle: { fontSize: 16, fontWeight: 700, color: C.texte }, subtextStyle: { color: C.doux, fontSize: 12 } };
    }
    return o;
  }
  function optionOrganisations(p) {
    const o = base(p);
    const cats = p.categories.map((c) => c.libelle);
    o.legend = { show: p.series.length > 1, bottom: 0, data: p.series.map((s) => ({ name: s.libelle, icon: s.role === "repere" ? "rect" : "roundRect" })) };
    o.xAxis = { type: "value", axisLabel: { formatter: graduation(p.unite) } };
    o.yAxis = { type: "category", data: cats, inverse: true, triggerEvent: true, axisLabel: { interval: 0, formatter: (s) => couper(s, 18), color: C.texte } };
    const repere = p.series.find((s) => s.role === "repere");
    const ecrite = { show: true, position: "right", color: C.texte, fontWeight: 700, fontSize: 12 };
    o.series = p.series.map((s, i) => (s.role === "repere"
      ? { type: "scatter", name: s.libelle, data: s.valeurs, symbol: "rect", symbolSize: [3, 20], itemStyle: { color: C.doux }, z: 3 }
      : { type: "bar", name: s.libelle, data: donneesSerie(s, i, true), barMaxWidth: 20, itemStyle: { borderRadius: [0, 4, 4, 0] },
          label: repere ? { show: false } : { ...ecrite, formatter: (q) => (q.data ? q.data.texte : "") } }));
    // avec le repère de la période de comparaison : la valeur s'écrit après la barre ET après le repère (un repère plus
    // loin que la barre ne coupe plus son premier chiffre) ; série sans point ni infobulle, ajoutée en dernier
    const barres = p.series.find((s) => s.role !== "repere");
    if (repere && barres) {
      const nombre = (x) => (x === null || x === undefined ? null : Number(x));
      o.series.push({ type: "scatter", silent: true, symbolSize: 0, z: 4, tooltip: { show: false }, label: { ...ecrite, formatter: (q) => q.data.texte },
        data: barres.valeurs.map((x, j) => {
          const v = nombre(x), r = nombre(repere.valeurs[j]);
          return { value: v === null ? null : Math.max(v, 0, r === null ? -Infinity : r), texte: barres.textes ? barres.textes[j] : "" };
        }) });
    }
    o.grid.right = 72;
    return o;
  }
  function optionN1(p) {
    if (p.mode === "ecart") {
      const o = base(p);
      o.xAxis = { type: "category", data: p.categories.map((c) => c.libelle), axisLabel: { interval: 0, formatter: (s) => couper(s, 18) } };
      o.yAxis = { type: "value", axisLabel: { formatter: (x) => t("format.pourcent", { valeur: compact.format(x) }) } };
      o.series = [{ type: "bar", name: p.series[0].libelle, data: donneesSerie(p.series[0], 0), barMaxWidth: 28,
        label: { show: true, position: "top", color: C.texte, fontSize: 12, fontWeight: 700, formatter: (q) => (q.data ? q.data.texte : "") } }];
      return o;
    }
    const o = optionBarres(p, {});
    o.series.forEach((s, i) => { if (!claire(i === 1 ? 8 : i)) s.label = { show: false }; if (i === 1) s.itemStyle.color = C.autres; });
    return o;
  }
  function optionRemplissage(p) {
    const o = base(p);
    const tons = [C.valide, C.brouillon, C.neutre];
    o.legend = { show: true, bottom: 0, icon: "roundRect", itemWidth: 12, itemHeight: 10 };
    // l'axe compte des cases (un KPI pour une organisation), pas des pourcentages : il est nommé pour être compris
    o.xAxis = { type: "value", name: t("visu.remplissage.axe"), nameLocation: "middle", nameGap: 26,
                nameTextStyle: { color: C.texte }, splitNumber: telephone.matches ? 3 : 5,
                axisLabel: { formatter: (x) => compact.format(x) } };
    o.yAxis = { type: "category", inverse: true, data: p.categories.map((c) => `${couper(c.libelle, 18)} · ${c.taux}`), triggerEvent: true,
                axisLabel: { interval: 0, color: C.texte } };
    o.series = p.series.map((s, i) => ({ type: "bar", stack: "cases", name: s.libelle, data: s.valeurs, barMaxWidth: 22,
      itemStyle: { color: tons[i], decal: i === 1 ? decal : undefined } }));
    o.grid.bottom = 58;
    return o;
  }
  function option(p) {
    if (p.type === "barres") return optionBarres(p, {});
    if (p.type === "barres_empilees") return optionBarres(p, { empile: true });
    if (p.type === "courbe") return optionCourbe(p);
    if (p.type === "anneau") return optionAnneau(p);
    if (p.type === "organisations") return optionOrganisations(p);
    if (p.type === "comparaison_n1") return optionN1(p);
    if (p.type === "remplissage") return optionRemplissage(p);
    return null;
  }

  // ---------------------------------------------------------------- tableaux de données (clavier, lecteurs d'écran)
  function tableDonnees(p, max) {
    const tab = p.tableau;
    if (!tab || !tab.lignes || !tab.lignes.length) return null;
    const table = el("table", { classe: "table-donnees-visu" });
    table.appendChild(el("caption", { classe: "visuellement-cache", texte: p.titre }));
    const tr = el("tr");
    // en-tête d'une colonne de nombres aligné à droite, comme ses valeurs
    const numerique = (j) => j > 0 && tab.lignes.some((l) => l.cellules[j] && l.cellules[j].v !== undefined);
    tab.entetes.forEach((e, j) => tr.appendChild(el("th", { scope: "col", classe: numerique(j) ? "num" : "", texte: e })));
    table.appendChild(el("thead", {}, [tr]));
    const corps = el("tbody");
    tab.lignes.forEach((l, i) => {
      const ligne = el("tr", { classe: [l.total ? "ligne-total" : "", max && i >= max ? "en-plus" : ""].join(" ").trim() || null });
      if (max && i >= max) ligne.hidden = true;
      l.cellules.forEach((c, j) => {
        if (j === 0) {
          const th = el("th", { scope: "row" });
          if (l.lien) th.appendChild(el("a", { href: l.lien + location.search, texte: c.t }));
          else th.textContent = c.t;
          ligne.appendChild(th);
        } else {
          const td = el("td", { "data-titre": tab.entetes[j], classe: [c.v !== undefined ? "num" : "", c.e ? `etat-${c.e}` : "", c.sens ? `sens-${c.sens}` : ""].join(" ").trim() || null, texte: c.t });
          ligne.appendChild(td);
        }
      });
      corps.appendChild(ligne);
    });
    table.appendChild(corps);
    return el("div", { classe: "table-defile" }, [table]);
  }

  // ---------------------------------------------------------------- chiffre clé (HTML) et petite courbe de tendance
  function tendance(t_) {
    if (!t_) return null;
    const ns = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", "0 0 96 28");
    svg.setAttribute("class", "tendance");
    svg.setAttribute("aria-hidden", "true");
    const vals = t_.valeurs.map((x, i) => [i, x]).filter((x) => x[1] !== null);
    const lo = Math.min.apply(null, vals.map((x) => x[1])), hi = Math.max.apply(null, vals.map((x) => x[1]));
    const n = Math.max(t_.valeurs.length - 1, 1), et = (hi - lo) || 1;
    const pts = vals.map((x) => [4 + 88 * x[0] / n, 24 - 20 * (x[1] - lo) / et]);
    const ligne = document.createElementNS(ns, "polyline");
    ligne.setAttribute("points", pts.map((x) => `${x[0].toFixed(1)},${x[1].toFixed(1)}`).join(" "));
    svg.appendChild(ligne);
    const der = pts[pts.length - 1], rond = document.createElementNS(ns, "circle");
    rond.setAttribute("cx", der[0]); rond.setAttribute("cy", der[1]); rond.setAttribute("r", 3);
    svg.appendChild(rond);
    return svg;
  }
  function chiffre(p) {
    const c = p.chiffre;
    const bloc = el("div", { classe: `chiffre-visu${c.numerique ? "" : " chiffre-texte"}${c.lignes.length > 1 ? " par-sommet" : ""}` });
    c.lignes.forEach((l) => {
      const ligne = el("div", { classe: "ligne-chiffre" });
      if (c.par_sommet) ligne.appendChild(el("p", { classe: "org-chiffre", texte: l.org }));
      const val = el("p", { classe: `valeur-chiffre etat-${l.etat}` }, [l.texte]);
      if (l.etat === "provisoire") val.appendChild(el("span", { classe: "marque-provisoire" }, [el("span", { classe: "point p-brouillon", "aria-hidden": "true" }), el("span", { classe: "visuellement-cache", texte: motEtat("provisoire") })]));
      ligne.appendChild(val);
      if (l.comparaison) {
        const e = el("p", { classe: "ecart-chiffre" });
        if (l.ecart.texte) e.appendChild(el("span", { classe: "ecart-visu", texte: l.ecart.texte }));
        const cmp = t(l.ecart.texte ? "visu.chiffre.comparaison_ecart" : "visu.chiffre.comparaison", { libelle: l.comparaison.libelle, texte: l.comparaison.texte });
        e.appendChild(el("span", { classe: "discret", texte: (l.ecart.texte ? " " : "") + cmp }));
        ligne.appendChild(e);
      }
      const tr = tendance(l.tendance);
      if (tr) ligne.appendChild(tr);
      bloc.appendChild(ligne);
    });
    return bloc;
  }
  function tableauVisuel(p) {
    const n = p.total || (p.tableau ? p.tableau.lignes.length : 0);
    const max = p.affichees || 25;
    const bloc = el("div", { classe: "tableau-visuel" });
    const table = tableDonnees(p, max);
    if (table) bloc.appendChild(table);
    if (n > max) {
      const b = el("button", { type: "button", classe: "secondaire afficher-plus", texte: t("visu.visuel.afficher_autres", { n: n - max }) });
      b.addEventListener("click", () => {
        bloc.querySelectorAll("tr.en-plus").forEach((x) => { x.hidden = false; });
        b.remove();
        const premiere = bloc.querySelectorAll("tbody tr")[max];
        if (premiere) { premiere.setAttribute("tabindex", "-1"); premiere.focus(); }
      });
      bloc.appendChild(el("p", { classe: "discret", texte: t("visu.visuel.lignes_sur", { n: max, total: n }) }));
      bloc.appendChild(b);
    }
    return bloc;
  }

  // ---------------------------------------------------------------- cartes des visuels
  function nettoyer() {
    Object.keys(graphiques).forEach((id) => { graphiques[id].dispose(); delete graphiques[id]; });
  }
  const observateur = "ResizeObserver" in window ? new ResizeObserver((entrees) => {
    entrees.forEach((e) => { const g = echarts.getInstanceByDom(e.target); if (g) g.resize(); });
  }) : null;
  const visibilite = "IntersectionObserver" in window ? new IntersectionObserver((entrees) => {
    entrees.forEach((e) => { if (e.isIntersecting) { visibilite.unobserve(e.target); dessiner(e.target); } });
  }, { rootMargin: "300px" }) : null;

  function dessiner(conteneur) {
    const p = donnees.visuels[conteneur.dataset.id];
    if (!p || echarts.getInstanceByDom(conteneur)) return;
    const g = echarts.init(conteneur, theme.nom, { renderer: "canvas", locale: langue.split("-")[0] === "fr" ? "FR" : "EN" });
    g.setOption(option(p));
    graphiques[p.id] = g;
    if (observateur) observateur.observe(conteneur);
    g.on("click", (q) => {
      let i = q.dataIndex;
      if (q.componentType === "yAxis" || q.componentType === "xAxis") i = p.categories.findIndex((c, j) => (q.value || "").indexOf(couper(c.libelle, 18).replace("…", "")) === 0 || j === q.dataIndex);
      const c = p.categories[i];
      if (c && c.descend && c.org) descendre(c.org);
    });
    if (!conteneur.dataset.clavier) { conteneur.dataset.clavier = "1"; clavierGraphique(conteneur, g, p); }  // une fois par carte, même redessinée
  }
  // apparence : l'impression passe les graphiques en clair, puis les rend à l'écran ; un changement du réglage du
  // système (sombre ↔ clair) pendant la visite les redessine dans la nouvelle apparence
  function redessiner(t) {
    theme = t; C = t.C;
    Object.keys(graphiques).forEach((id) => {
      const noeud = graphiques[id].getDom();
      graphiques[id].dispose(); delete graphiques[id];
      dessiner(noeud);
    });
  }
  window.addEventListener("beforeprint", () => { if (theme !== clair) redessiner(clair); });
  window.addEventListener("afterprint", () => { if (theme !== ecran) redessiner(ecran); });
  const systemeSombre = window.matchMedia("(prefers-color-scheme: dark)");
  if (systemeSombre.addEventListener) systemeSombre.addEventListener("change", () => { ecran = lireTheme(document.documentElement, "outil"); redessiner(ecran); });
  function clavierGraphique(conteneur, g, p) {
    const actuel = () => echarts.getInstanceByDom(conteneur) || g;
    let i = -1;
    const nb = p.categories.length;
    conteneur.addEventListener("keydown", (e) => {
      const avant = i;
      if (["ArrowRight", "ArrowDown"].indexOf(e.key) >= 0) i = Math.min(nb - 1, i + 1);
      else if (["ArrowLeft", "ArrowUp"].indexOf(e.key) >= 0) i = Math.max(0, i < 0 ? 0 : i - 1);
      else if (e.key === "Home") i = 0;
      else if (e.key === "End") i = nb - 1;
      else if (e.key === "Escape") { actuel().dispatchAction({ type: "hideTip" }); return; }
      else if (e.key === "Enter" && i >= 0) {
        const c = p.categories[i];
        if (c && c.descend && c.org) { e.preventDefault(); descendre(c.org); }
        return;
      } else return;
      e.preventDefault();
      if (i === avant && avant >= 0) return;
      const serie = Math.max(0, (p.series || []).findIndex((s) => s.role !== "repere"));
      actuel().dispatchAction({ type: "showTip", seriesIndex: serie, dataIndex: i });
      annoncer(texteLu(p, i));
    });
    conteneur.addEventListener("blur", () => actuel().dispatchAction({ type: "hideTip" }));
  }
  function carte(p) {
    const n = modele.content.firstElementChild.cloneNode(true);
    const id = p.id;
    n.dataset.id = id;
    n.classList.add(`l-${p.largeur || 6}`, `h-${p.hauteur || "m"}`, `forme-${p.type}`);
    // nom de la carte (repère « section ») : titre et sous-titre, pour distinguer deux visuels d'un même KPI (nommerCartes)
    n.setAttribute("aria-labelledby", `titre-${id} sous-titre-${id}`);
    const h = n.querySelector("[data-titre]");
    h.id = `titre-${id}`;
    n.querySelector("[data-sous-titre]").id = `sous-titre-${id}`;
    if (p.fiche) h.appendChild(el("a", { href: p.fiche + location.search, texte: p.titre }));
    else h.textContent = p.titre;
    n.querySelector("[data-sous-titre]").textContent = p.sous_titre || "";
    n.querySelector("[data-resume-menu]").setAttribute("aria-label", t("visu.visuel.menu", { titre: p.titre }));
    const def = n.querySelector('[data-action="definition"]');
    if (p.fiche) def.href = `${p.fiche}${location.search}#definition`; else def.remove();
    const avert = n.querySelector("[data-avertissements]");
    (p.avertissements || []).forEach((a) => avert.appendChild(el("li", { texte: a })));
    avert.hidden = !(p.avertissements || []).length;
    const corps = n.querySelector("[data-corps]");
    const zoneDonnees = n.querySelector("[data-donnees]");
    const boutonDonnees = n.querySelector(".lien-donnees");
    zoneDonnees.id = `donnees-${id}`;
    boutonDonnees.setAttribute("aria-controls", zoneDonnees.id);
    const sansDonnees = () => { boutonDonnees.remove(); n.querySelectorAll('[data-action="donnees"]').forEach((b) => b.remove()); };
    if (p.etat !== "ok") {
      corps.appendChild(el("p", { classe: `message-visuel etat-${p.etat}`, texte: p.message }));
      if (p.etat === "erreur") {
        const b = el("button", { type: "button", classe: "secondaire", texte: t("visu.visuel.reessayer") });
        b.addEventListener("click", () => charger());
        corps.appendChild(b);
      }
      sansDonnees();
      n.querySelectorAll('[data-action="png"], [data-action="plein-ecran"]').forEach((b) => b.remove());
    } else if (p.type === "chiffre") {
      corps.appendChild(chiffre(p));
    } else if (p.type === "tableau") {
      corps.appendChild(tableauVisuel(p));
      sansDonnees();
      n.querySelectorAll('[data-action="png"]').forEach((b) => b.remove());
    } else if (p.liste) {  // oui / non : la réponse de chaque organisation, sans barre
      corps.appendChild(tableDonnees(p));
      sansDonnees();
      n.querySelectorAll('[data-action="png"]').forEach((b) => b.remove());
    } else {
      const g = el("div", { classe: "graphique", "data-id": id, tabindex: "0", "aria-describedby": "consigne-graphique" });
      corps.appendChild(g);
      if (p.autres) corps.appendChild(el("p", { classe: "discret autres-visuel", texte: t("visu.visuel.autres_orgs", { n: p.autres }) }));
    }
    if (zoneDonnees && p.etat === "ok" && p.type !== "tableau" && !p.liste) {
      const tab = tableDonnees(p);
      if (tab) zoneDonnees.appendChild(tab); else sansDonnees();
    }
    if (window.matchMedia("(forced-colors: active)").matches && boutonDonnees.isConnected) basculerDonnees(n, true);
    return n;
  }
  function basculerDonnees(n, ouvrir) {
    const zone = n.querySelector("[data-donnees]"), b = n.querySelector(".lien-donnees");
    if (!zone || !b) return;
    const ouvert = ouvrir === undefined ? !zone.classList.contains("ouvert") : ouvrir;
    zone.classList.toggle("ouvert", ouvert);
    b.setAttribute("aria-expanded", String(ouvert));
    b.textContent = t(ouvert ? "visu.visuel.masquer_donnees" : "visu.visuel.donnees");
  }
  function payloadDe(id) {
    if (donnees.visuels[id]) return donnees.visuels[id];
    const d = edition.brouillon.visuels.find((x) => x.id === id) || {};
    const charge = edition.calcul[id];
    return { id: id, type: d.type, titre: d.titre || t(`visu.type.${d.type}`), sous_titre: "", etat: charge ? "chargement" : "indisponible",
             message: charge ? t("visu.visuel.chargement") : t("visu.visuel.kpi_indisponible"), largeur: d.largeur, hauteur: d.hauteur,
             categories: [], series: [], avertissements: [], suggestions: [], compatibles: {}, definition: d };
  }
  function construireCarte(id) {
    const p = edition.actif ? payloadDe(id) : donnees.visuels[id];
    const n = carte(p);
    if (edition.actif) decorer(n, p);
    return n;
  }
  function rendre() {
    nettoyer();
    grille.replaceChildren();
    const ids = edition.actif ? edition.brouillon.visuels.map((x) => x.id) : (donnees.ordre || []);
    // vue vide en modification : glisser un KPI, sauf sur un téléphone tactile, où l'on ajoute par boutons
    const aide = (tactile.matches && telephone.matches) ? "visu.vue.vide_aide_tel" : "visu.vue.vide_aide";
    if (!ids.length) grille.appendChild(el("p", { classe: edition.actif ? "vue-vide zone-depot-vue" : "vue-vide etat-vide", texte: t(edition.actif ? aide : "visu.vue.vide") }));
    ids.forEach((id) => grille.appendChild(construireCarte(id)));
    nommerCartes();
    grille.querySelectorAll(".graphique").forEach((g) => { if (visibilite) visibilite.observe(g); else dessiner(g); });
    rendreEtat();
  }
  // deux cartes au même titre et au même sous-titre (visuel dupliqué) : la deuxième est nommée « … (2) », et ainsi de
  // suite, pour que chaque repère de la page ait un nom unique (lecteur d'écran)
  function nommerCartes() {
    const vus = new Map();
    grille.querySelectorAll(":scope > [data-visuel]").forEach((n) => {
      const id = n.dataset.id;
      n.removeAttribute("aria-label");
      n.setAttribute("aria-labelledby", `titre-${id} sous-titre-${id}`);
      const nom = [n.querySelector("[data-titre]"), n.querySelector("[data-sous-titre]")]
        .map((e) => (e ? e.textContent : "").replace(/\s+/g, " ").trim()).filter(Boolean).join(" ");
      const k = (vus.get(nom) || 0) + 1;
      vus.set(nom, k);
      if (k > 1) { n.removeAttribute("aria-labelledby"); n.setAttribute("aria-label", `${nom} (${k})`); }
    });
  }
  function remplacerCarte(id) {
    const ancienne = grille.querySelector(`[data-visuel][data-id="${id}"]`);
    if (!ancienne) { rendre(); return; }
    const g = ancienne.querySelector(".graphique");
    if (g && echarts.getInstanceByDom(g)) { echarts.getInstanceByDom(g).dispose(); delete graphiques[id]; }
    const n = construireCarte(id);
    ancienne.replaceWith(n);
    nommerCartes();
    n.querySelectorAll(".graphique").forEach((x) => dessiner(x));
    return n;
  }

  // ---------------------------------------------------------------- phrase d'état et chemin de l'organisation
  function rendreEtat() {
    const zone = racine.querySelector("[data-etat-vue]");
    if (!zone) return;
    zone.replaceChildren();
    const e = donnees.etat, f = donnees.filtres;
    // la phrase d'état est lue par le lecteur d'écran, plus affichée ; ses liens restent visibles
    const phrase = el("p", { classe: "phrase-etat", "data-phrase-etat": "" }, [el("span", { classe: "visuellement-cache", texte: e.phrase })]);
    if (f.valeurs === "validees" && e.nb_attente) {
      phrase.appendChild(document.createTextNode(" "));
      const a = el("a", { href: "#", texte: t("visu.etat.inclure_brouillons") });
      a.addEventListener("click", (ev) => { ev.preventDefault(); changer({ brouillons: "1" }); });
      phrase.appendChild(a);
      phrase.appendChild(document.createTextNode("."));
    } else if (f.valeurs === "brouillons") {
      phrase.appendChild(document.createTextNode(" "));
      const a = el("a", { href: "#", texte: t("visu.etat.validees_seulement") });
      a.addEventListener("click", (ev) => { ev.preventDefault(); changer({ brouillons: "0" }); });
      phrase.appendChild(a);
    }
    zone.appendChild(phrase);
    // en modification, le brouillon ne contient pas les visuels qui ne concernent pas la personne : ils restent dans la vue
    if (edition.actif && ctx.vue.masques) zone.appendChild(el("p", { classe: "phrase-etat", texte: t("visu.vue.masques_gardes", { n: ctx.vue.masques }) }));
    else if (e.phrase_masques) zone.appendChild(el("p", { classe: "phrase-etat", texte: e.phrase_masques }));
    (donnees.avertissements || []).forEach((a) => zone.appendChild(el("p", { classe: "avertissement-vue", texte: a })));
    if (f.chemin && f.chemin.length > 1) {
      const nav = el("nav", { classe: "chemin-org", "aria-label": t("visu.chemin") });
      f.chemin.forEach((o, i) => {
        if (i < f.chemin.length - 1) {
          const a = el("a", { href: `?org=${o.id}`, "data-org": o.id, texte: o.nom, "aria-label": t("visu.chemin.remonter", { org: o.nom }) });
          a.addEventListener("click", (ev) => { ev.preventDefault(); changer({ org: String(o.id) }); });
          nav.appendChild(a);
          nav.appendChild(el("span", { classe: "sep", "aria-hidden": "true", texte: "›" }));
        } else nav.appendChild(el("span", { "aria-current": "location", texte: o.nom }));
      });
      zone.appendChild(nav);
    }
    const retablir = racine.querySelector("[data-retablir]");
    if (retablir) retablir.hidden = !f.differents;
    // filtres de la page différents de ceux de la vue : « Enregistrer les filtres » (en lecture, pour qui peut
    // la modifier : la personne qui l'a créée, l'administrateur pour une vue partagée) ; « Garder ces filtres » (en modification)
    const sauverFiltres = racine.querySelector("[data-enregistrer-filtres]");
    if (sauverFiltres) sauverFiltres.hidden = !(f.differents && !edition.actif && ctx.vue.id && ctx.vue.modifiable);
    garderFiltres();
    compterFiltres();
  }

  // ---------------------------------------------------------------- filtres : adresse partageable, Précédent
  function lireFormulaire() {
    const p = new URLSearchParams();
    const fd = new FormData(formFiltres);
    ["periode", "cmp", "org", "ref"].forEach((k) => { if (fd.get(k)) p.set(k, fd.get(k)); });
    const themes = fd.getAll("theme");
    if (themes.length) p.set("theme", themes.join(","));
    else if (parametres.has("theme")) p.set("theme", "");
    p.set("brouillons", fd.get("brouillons") === "1" ? "1" : "0");
    if (parametres.get("modifier")) p.set("modifier", parametres.get("modifier"));
    return p;
  }
  function synchroniserFormulaire() {
    const f = donnees.filtres;
    const s = (nom, val) => { const x = formFiltres.querySelector(`[name="${nom}"]`); if (x && val !== undefined && val !== null) x.value = String(val); };
    s("periode", f.periode.demande);
    s("cmp", f.comparaison.mode);
    s("org", f.org.tout ? "tout" : f.org.id);
    formFiltres.querySelector('[name="org"]')?.dispatchEvent(new Event("selecteur:maj"));  // le sélecteur en arbre suit
    s("ref", f.referentiel.demande);
    s("brouillons", f.valeurs === "brouillons" ? "1" : "0");
    formFiltres.querySelectorAll('[name="theme"]').forEach((c) => { c.checked = f.themes.indexOf(Number(c.value)) >= 0; });
    const nb = racine.querySelector("[data-themes-choisis]");
    if (nb) nb.textContent = f.themes.length ? String(f.themes.length) : t("visu.filtres.themes_tous");
    majFiltresOptionnels();
  }
  function compterFiltres() {
    const b = racine.querySelector("[data-compte-filtres]");
    if (!b) return;
    const f = donnees.filtres.brut || {};
    let n = 0;
    if (f.periode !== "auto") n++;
    if (f.comparaison !== "n1") n++;
    if (f.org !== null && f.org !== undefined) n++;
    if (f.referentiel !== "je_reponds_a") n++;
    if ((f.themes || []).length) n++;
    if (f.valeurs !== "validees") n++;
    b.textContent = n ? t("visu.filtres.compte", { n: n }) : t("visu.filtres");
  }
  function changer(valeurs) {
    Object.keys(valeurs).forEach((k) => parametres.set(k, valeurs[k]));
    history.pushState(null, "", `${location.pathname}?${parametres}`);
    charger();
  }
  function descendre(org) { changer({ org: String(org) }); toast(t("visu.visuel.chargement")); }
  async function charger() {
    if (requete) requete.abort();
    requete = new AbortController();
    grille.setAttribute("aria-busy", "true");
    try {
      let rep;
      const q = new URLSearchParams(parametres);
      q.delete("modifier");
      if (ctx.vue.id && !edition.actif) {
        rep = await fetch(`${ctx.urls.vue.replace("{id}", ctx.vue.id)}donnees/?${q}`, { headers: window.outils.entetes(), signal: requete.signal });
      } else {
        const par = {};
        q.forEach((x, k) => { par[k] = x; });
        const def = edition.actif ? edition.brouillon : ctx.vue;
        rep = await fetch(ctx.urls.donnees, { method: "POST", signal: requete.signal, body: JSON.stringify({ vue: ctx.vue.id, filtres: def.filtres, visuels: def.visuels, parametres: par }),
          headers: window.outils.entetes(true) });
      }
      if (!rep.ok) throw new Error(String(rep.status));
      donnees = await rep.json();
      synchroniserFormulaire();
      rendre();
      annoncer(donnees.etat.phrase);
    } catch (e) {
      if (e.name !== "AbortError") toast(t("visu.erreur.reseau"));
    } finally {
      grille.setAttribute("aria-busy", "false");
    }
  }
  // filtres que l'on ajoute et que l'on retire : Période et Organisation toujours affichés ; un
  // filtre optionnel s'affiche quand il change quelque chose (valeur différente de sa valeur de départ), ou par
  // « Ajouter un filtre » ; sa croix le remet à sa valeur de départ et le cache
  function valeurFiltre(bloc) {
    if (bloc.dataset.filtreOptionnel === "theme") return Array.from(bloc.querySelectorAll('[name="theme"]:checked')).map((c) => c.value).join(",");
    return (bloc.querySelector("select") || {}).value || "";
  }
  function libelleFiltre(bloc) { return (bloc.querySelector("label, .libelle-filtre") || {}).textContent || ""; }
  function majFiltresOptionnels(forcer) {
    if (!formFiltres) return;
    const menu = formFiltres.querySelector("[data-ajouter-filtre]"), liste = formFiltres.querySelector("[data-liste-ajout-filtres]");
    const blocs = Array.from(formFiltres.querySelectorAll("[data-filtre-optionnel]"));
    blocs.forEach((bloc) => {
      if (!bloc.querySelector("[data-retirer-filtre]")) {
        const x = el("button", { type: "button", classe: "retirer-filtre", "data-retirer-filtre": "", "aria-label": t("visu.filtres.retirer", { filtre: libelleFiltre(bloc).trim() }) }, [icone("x")]);
        bloc.insertBefore(x, bloc.firstChild);
      }
      if (valeurFiltre(bloc) !== (bloc.dataset.defaut || "") || bloc.dataset.ajoute === "1" || forcer === bloc) bloc.hidden = false;
      else bloc.hidden = true;
    });
    if (menu && liste) {
      liste.replaceChildren();
      blocs.filter((b) => b.hidden).forEach((b) => liste.appendChild(el("button", { type: "button", "data-montrer-filtre": b.dataset.filtreOptionnel, texte: libelleFiltre(b).trim() })));
      menu.hidden = !liste.children.length;
    }
  }
  if (formFiltres) {
    majFiltresOptionnels();
    formFiltres.addEventListener("click", (e) => {
      const montrer = e.target.closest("[data-montrer-filtre]");
      if (montrer) {
        const bloc = formFiltres.querySelector(`[data-filtre-optionnel="${montrer.dataset.montrerFiltre}"]`);
        bloc.dataset.ajoute = "1";
        formFiltres.querySelector("[data-ajouter-filtre]").open = false;
        majFiltresOptionnels(bloc);
        (bloc.querySelector("select, summary") || bloc).focus();
        return;
      }
      const retirer = e.target.closest("[data-retirer-filtre]");
      if (retirer) {
        const bloc = retirer.closest("[data-filtre-optionnel]");
        delete bloc.dataset.ajoute;
        if (bloc.dataset.filtreOptionnel === "theme") bloc.querySelectorAll('[name="theme"]').forEach((c) => { c.checked = false; });
        else { const sel = bloc.querySelector("select"); if (sel) sel.value = bloc.dataset.defaut || ""; }
        majFiltresOptionnels();
        formFiltres.dispatchEvent(new Event("change", { bubbles: true }));
        formFiltres.querySelector("[data-ajouter-filtre] summary")?.focus();
      }
    });
  }
  if (formFiltres) {
    const sansScript = formFiltres.querySelector("[data-sans-script]");
    if (sansScript) sansScript.hidden = true;
    formFiltres.addEventListener("change", () => {
      clearTimeout(minuteur);
      minuteur = setTimeout(() => {
        parametres = lireFormulaire();
        history.pushState(null, "", `${location.pathname}?${parametres}`);
        charger();
      }, 300);
    });
    formFiltres.addEventListener("submit", (e) => { e.preventDefault(); parametres = lireFormulaire(); history.pushState(null, "", `${location.pathname}?${parametres}`); charger(); });
    const retablir = racine.querySelector("[data-retablir]");
    if (retablir) retablir.addEventListener("click", (e) => { e.preventDefault(); parametres = new URLSearchParams(); history.pushState(null, "", location.pathname); charger(); });
  }
  window.addEventListener("popstate", () => { parametres = new URLSearchParams(location.search); charger(); });

  // ---------------------------------------------------------------- fenêtres (plein écran, filtres sur téléphone)
  const voile = racine.parentElement.querySelector("[data-voile-visu]") || document.querySelector("[data-voile-visu]");
  let fenetreOuverte = null, declencheur = null, graphiqueFenetre = null;
  function focusables(f) { return Array.from(f.querySelectorAll("a[href], button:not([disabled]), select, input, [tabindex='0'], summary")).filter((x) => x.offsetParent !== null); }
  function ouvrirFenetre(f, depuis) {
    fenetreOuverte = f;
    declencheur = depuis || document.activeElement;
    f.hidden = false;
    f.classList.add("ouverte");
    if (voile) voile.hidden = false;
    document.body.classList.add("fenetre-visu-ouverte");
    (focusables(f)[0] || f).focus();
  }
  function fermerFenetre() {
    if (!fenetreOuverte) return;
    const f = fenetreOuverte;
    fenetreOuverte = null;
    f.classList.remove("ouverte");
    if (f.matches("[data-filtres-vue]")) { f.removeAttribute("role"); f.removeAttribute("aria-modal"); }
    else if (!f.matches("[data-panneau-kpi]")) f.hidden = true;
    if (graphiqueFenetre) { graphiqueFenetre.dispose(); graphiqueFenetre = null; }
    if (voile) voile.hidden = true;
    document.body.classList.remove("fenetre-visu-ouverte");
    if (declencheur && declencheur.focus) declencheur.focus();
  }
  document.addEventListener("keydown", (e) => {
    if (!fenetreOuverte) return;
    if (e.key === "Escape") { e.preventDefault(); if (fenetreOuverte === panneauReglages) fermerReglages(); else fermerFenetre(); return; }
    if (e.key !== "Tab") return;
    const liste = focusables(fenetreOuverte);
    if (!liste.length) return;
    const premier = liste[0], dernier = liste[liste.length - 1];
    if (e.shiftKey && document.activeElement === premier) { e.preventDefault(); dernier.focus(); }
    else if (!e.shiftKey && document.activeElement === dernier) { e.preventDefault(); premier.focus(); }
  });
  document.addEventListener("click", (e) => { if (e.target.closest("[data-fermer-fenetre]") || e.target === voile) fermerFenetre(); });
  const boutonFiltres = racine.querySelector("[data-ouvrir-filtres]");
  if (boutonFiltres && formFiltres) boutonFiltres.addEventListener("click", () => {
    formFiltres.setAttribute("role", "dialog");
    formFiltres.setAttribute("aria-modal", "true");
    ouvrirFenetre(formFiltres, boutonFiltres);
  });
  function pleinEcran(p, depuis) {
    const f = document.querySelector('[data-fenetre="plein-ecran"]');
    f.querySelector("[data-titre-fenetre]").textContent = p.titre;
    f.querySelector("[data-sous-titre-fenetre]").textContent = p.sous_titre || "";
    const zone = f.querySelector("[data-graphique-fenetre]"), tab = f.querySelector("[data-donnees-fenetre]");
    zone.replaceChildren(); tab.replaceChildren();
    ouvrirFenetre(f, depuis);
    const opt = option(p);
    if (opt) {
      const g = el("div", { classe: "graphique grand", tabindex: "0", "aria-describedby": "consigne-graphique" });
      zone.appendChild(g);
      graphiqueFenetre = echarts.init(g, theme.nom, { renderer: "canvas", locale: langue.split("-")[0] === "fr" ? "FR" : "EN" });
      graphiqueFenetre.setOption(opt);
      clavierGraphique(g, graphiqueFenetre, p);
    } else if (p.type === "chiffre") zone.appendChild(chiffre(p));
    const d = tableDonnees(p);
    if (d) tab.appendChild(d);
  }

  // ---------------------------------------------------------------- exports : image (PNG) et Excel
  function nomFichier(morceaux) {
    // date de l'installation donnée par le serveur (fuseau TIME_ZONE), comme les fichiers faits par le serveur
    const propres = morceaux.concat([ctx.aujourdhui.iso]).map((m) => String(m || "").normalize("NFKD")
      .replace(/[̀-ͯ]/g, "").replace(/[^A-Za-z0-9.]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 40)).filter(Boolean);
    return propres.join("_");
  }
  function ligneSource() {
    const valeurs = donnees.filtres.valeurs === "brouillons" ? t("visu.filtres.brouillons") : t("visu.etat.validees_seulement");
    return t("visu.export.source", { outil: ctx.outil, valeurs: valeurs.toLowerCase(), date: ctx.aujourdhui.texte });  // date courte de la langue (format.date_courte)
  }
  function telecharger(url, nom) {
    const a = el("a", { href: url, download: nom });
    document.body.appendChild(a); a.click(); a.remove();
  }
  // l'image garde toujours le fond et les couleurs claires (impression, documents), quelle que soit l'apparence ; la
  // bascule des couleurs ne dure que le dessin (synchrone), sans gêner les graphiques de la page
  async function exporterPng(p) {
    if (document.fonts && document.fonts.ready) await document.fonts.ready;
    avecTheme(clair, () => dessinerPng(p));
  }
  function dessinerPng(p) {
    const nom = `${nomFichier(["Visualisation", ctx.vue.nom, p.titre])}.png`;
    if (p.type === "chiffre") {  // chiffre clé : dessiné sur un canvas 2D (titre, valeur, écart)
      const cv = document.createElement("canvas"), r = 2;
      cv.width = 800 * r; cv.height = 320 * r;
      const c = cv.getContext("2d");
      c.scale(r, r);
      c.fillStyle = C.surface; c.fillRect(0, 0, 800, 320);
      c.fillStyle = C.texte; c.font = `700 22px ${police}`; c.fillText(couper(p.titre, 60), 32, 52);
      c.fillStyle = C.doux; c.font = `400 15px ${police}`; c.fillText(couper(p.sous_titre, 90), 32, 80);
      let y = 150;
      p.chiffre.lignes.slice(0, 2).forEach((l) => {
        c.fillStyle = C.texte; c.font = `700 44px ${police}`; c.fillText(l.texte + motEtat(l.etat), 32, y);
        if (l.comparaison) { c.fillStyle = C.doux; c.font = `400 17px ${police}`; c.fillText(`${l.ecart.texte} ${l.comparaison.libelle} : ${l.comparaison.texte}`.trim(), 32, y + 32); }
        y += 90;
      });
      c.fillStyle = C.doux; c.font = `400 13px ${police}`; c.fillText(ligneSource(), 32, 300);
      telecharger(cv.toDataURL("image/png"), nom);
      return;
    }
    const opt = option(p);
    if (!opt) return;
    const hors = el("div");
    hors.style.cssText = "position:fixed;left:-10000px;top:0;width:1200px;height:640px";  // pas d'attribut style (politique des contenus)
    document.body.appendChild(hors);
    const g = echarts.init(hors, clair.nom, { renderer: "canvas", width: 1200, height: 640, locale: langue.split("-")[0] === "fr" ? "FR" : "EN" });
    opt.title = [{ text: p.titre, subtext: p.sous_titre, left: 24, top: 16, textStyle: { fontSize: 20, fontWeight: 700, color: C.texte }, subtextStyle: { fontSize: 14, color: C.doux } }]
      .concat(opt.title ? [opt.title] : []);
    opt.grid = { ...opt.grid, top: 96, bottom: 72, left: 24, right: 48 };
    if (opt.legend && opt.legend.show !== false) opt.legend.bottom = 36;
    opt.graphic = [{ type: "text", left: 24, bottom: 12, style: { text: ligneSource(), fill: C.doux, font: `13px ${police}` } }];
    g.setOption(opt);
    telecharger(g.getDataURL({ type: "png", pixelRatio: 2, backgroundColor: C.surface }), nom);
    g.dispose();
    hors.remove();
  }
  async function exporterExcel(id) {
    const q = new URLSearchParams(parametres);
    q.delete("modifier");
    if (ctx.vue.id) {
      if (id) q.set("visuel", id);
      window.location.href = `${ctx.urls.vue.replace("{id}", ctx.vue.id)}excel/?${q}`;
      return;
    }
    const par = {};
    q.forEach((x, k) => { par[k] = x; });
    const rep = await fetch(ctx.urls.excel, { method: "POST", headers: window.outils.entetes(true),
      body: JSON.stringify({ nom: ctx.vue.nom, filtres: ctx.vue.filtres, visuels: ctx.vue.visuels, parametres: par, visuel: id || "" }) });
    if (!rep.ok) { toast(t("visu.erreur.reseau")); return; }
    const url = URL.createObjectURL(await rep.blob());
    telecharger(url, `${nomFichier(["Visualisation", ctx.vue.nom])}.xlsx`);
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  }

  // ---------------------------------------------------------------- actions des visuels
  grille.addEventListener("click", (e) => {
    const b = e.target.closest("[data-action]");
    if (!b) return;
    const n = b.closest("[data-visuel]"), p = n && donnees.visuels[n.dataset.id];
    if (!p) return;
    const menu = b.closest("details");
    if (menu) menu.open = false;
    const a = b.dataset.action;
    if (a === "donnees") { basculerDonnees(n); if (menu) n.querySelector(".lien-donnees").focus(); }
    else if (a === "plein-ecran") pleinEcran(p, n.querySelector("summary"));
    else if (a === "png") exporterPng(p);
    else if (a === "excel") exporterExcel(p.id);
  });

  // ---------------------------------------------------------------- actions de la vue (menu « Vue … »)
  // « signaler » : comment montrer le refus (message bref par défaut ; erreur qui reste à l'écran pour « Enregistrer et quitter »)
  async function envoyer(url, corps, signaler) {
    signaler = signaler || toast;
    let rep = null;
    try {
      rep = await fetch(url, { method: "POST", headers: window.outils.entetes(true), body: JSON.stringify(corps || {}) });
    } catch (err) { signaler(t("visu.erreur.reseau")); return null; }  // réseau coupé
    let d = {};
    try { d = await rep.json(); } catch (err) { d = {}; }
    if (!rep.ok) { signaler(d.erreurs && d.erreurs.length ? d.erreurs[0].message : d.erreur || t("visu.erreur.reseau")); return null; }  // refus 403 : « erreur »
    return d;
  }
  function urlVue(suffixe) { return `${ctx.urls.vue.replace("{id}", ctx.vue.id)}${suffixe}`; }
  async function deplacerVue(sens) {
    const ids = ctx.vues.map((x) => x.id), i = ids.indexOf(ctx.vue.id), j = i + sens;
    if (i < 0 || j < 0 || j >= ids.length) return;
    ids.splice(j, 0, ids.splice(i, 1)[0]);
    const d = await envoyer(ctx.urls.ordre, { ordre: ids, partagees: ctx.droits.admin && ctx.vue.partage });
    if (!d) return;
    ctx.vues.splice(j, 0, ctx.vues.splice(i, 1)[0]);
    const liste = racine.querySelector("[data-onglets-vues] ul"), li = liste && liste.querySelector(`[data-vue-id="${ctx.vue.id}"]`);
    if (li) {
      const voisins = Array.from(liste.querySelectorAll("[data-vue-id]"));
      voisins.splice(voisins.indexOf(li), 1);
      liste.insertBefore(li, voisins[j] || null);
    }
    toast(t("visu.vue.deplacee", { nom: ctx.vue.nom, position: j + 1, total: ids.length }));
    annoncer(t("visu.vue.deplacee", { nom: ctx.vue.nom, position: j + 1, total: ids.length }));
  }
  racine.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-action-vue]");
    if (!b) return;
    const menu = b.closest("details");
    if (menu) menu.open = false;
    const a = b.dataset.actionVue;
    let d = null;
    if (a === "excel") exporterExcel("");
    else if (a === "defaut") { d = await envoyer(urlVue("preferee/"), { defaut: true }); if (d) toast(d.message); }
    else if (a === "accueil") { const f = document.querySelector('[data-fenetre="accueil"]'); if (f) ouvrirFenetre(f, racine.querySelector(".menu-vue summary")); }
    else if (a === "dupliquer") { d = await envoyer(urlVue("dupliquer/")); if (d) { memoriser(d.message); window.location.href = d.url; } }
    else if (a === "partager" || a === "ne-plus-partager") { d = await envoyer(urlVue("partage/"), { partage: a === "partager" }); if (d) window.location.reload(); }
    else if (a === "gauche") deplacerVue(-1);
    else if (a === "droite") deplacerVue(1);
    else if (a === "enregistrer-comme") {
      d = await envoyer(ctx.urls.creer, { nom: ctx.vue.nom, description: "", filtres: ctx.vue.filtres, visuels: ctx.vue.visuels });
      if (d) window.location.href = d.vue.url;
    }
  });

  // ---------------------------------------------------------------- mode modification
  // Le brouillon (nom, filtres, visuels) reste dans la page jusqu'à « Enregistrer la vue ». Chaque visuel changé est
  // recalculé seul par le serveur (forme « auto » résolue là-bas, avec ses suggestions et ses compatibilités).
  const panneauKpi = racine.querySelector("[data-panneau-kpi]");
  const panneauReglages = racine.querySelector("[data-panneau-reglages]");
  const formReglages = racine.querySelector("[data-form-reglages]");
  const barre = racine.querySelector("[data-barre-modification]");
  const barreHaut = racine.querySelector("[data-barre-haut]");
  // Ctrl + S, ou Cmd + S sur Mac : écrit à côté du bouton et lu avec lui (aria-describedby, aria-keyshortcuts)
  const mac = /Mac|iPhone|iPad|iPod/.test(navigator.platform || navigator.userAgent || "");
  const touches = t(mac ? "visu.vue.touches_mac" : "visu.vue.touches");
  const espace = racine.querySelector("[data-espace-vue]");
  const modeleEdition = document.getElementById("modele-edition");
  const glisserPermis = () => !(tactile.matches && telephone.matches);
  const copie = (x) => JSON.parse(JSON.stringify(x));
  const definitionDe = (id) => edition.brouillon.visuels.find((x) => x.id === id);
  const sansAccents = window.outils.sansAccents;  // script des pages (collecte/_app/01_socle.js)
  function nouvelId() {
    let id;
    do { id = `v${Math.random().toString(36).slice(2, 9)}`; } while (definitionDe(id));
    return id;
  }
  function etatBrouillon(texte) { racine.querySelectorAll("[data-etat-brouillon]").forEach((e) => { e.textContent = texte; }); }
  function marquer() {
    edition.modifie = true;
    etatBrouillon(t("visu.vue.non_enregistree"));
  }
  function kpiCat(code) { return edition.catalogue ? edition.catalogue.parCode[code] : null; }
  function nomKpi(code) { const k = kpiCat(code); return k ? k.nom : code; }
  function paramsObjet() { const par = {}; parametres.forEach((x, k) => { if (k !== "modifier") par[k] = x; }); return par; }

  async function actualiser(id) {
    const def = definitionDe(id);
    if (!def) return;
    edition.calcul[id] = true;
    delete donnees.visuels[id];
    remplacerCarte(id);
    try {
      const rep = await fetch(ctx.urls.donnees, { method: "POST", headers: window.outils.entetes(true),
        body: JSON.stringify({ vue: ctx.vue.id, filtres: edition.brouillon.filtres, visuels: [def], parametres: paramsObjet() }) });
      const d = await rep.json();
      if (!rep.ok) {
        donnees.visuels[id] = { ...payloadDe(id), etat: "erreur", message: d.erreurs && d.erreurs.length ? d.erreurs[0].message : d.erreur || t("visu.visuel.erreur") };
      } else if (d.visuels[id]) {
        const p = d.visuels[id];
        donnees.visuels[id] = p;
        if (def.type === "auto" && p.definition) Object.assign(def, p.definition, { id: id });
      }
    } catch (e) {
      donnees.visuels[id] = { ...payloadDe(id), etat: "erreur", message: t("visu.erreur.reseau") };
    } finally {
      delete edition.calcul[id];
    }
    const n = remplacerCarte(id);
    if (edition.selection === id) { if (n) n.classList.add("selectionne"); remplirReglages(); }
  }

  // -- cartes en modification : poignée, sélection, dépôt d'un KPI, autres formes
  function decorer(n, p) {
    const id = p.id, ids = edition.brouillon.visuels.map((x) => x.id), position = ids.indexOf(id) + 1;
    const ed = modeleEdition.content.cloneNode(true);
    const barreCarte = ed.querySelector(".barre-edition-visuel");
    const poignee = ed.querySelector(".poignee-visuel");
    poignee.setAttribute("aria-label", t("visu.visuel.deplacer_aria", { titre: p.titre, position: position, total: ids.length }));
    const choisir = ed.querySelector(".selection-visuel");
    choisir.setAttribute("aria-label", t("visu.visuel.selectionner", { titre: p.titre }));
    n.insertBefore(barreCarte, n.firstChild);
    const depot = ed.querySelector(".depot-visuel");
    n.appendChild(depot);
    const sugg = ed.querySelector(".suggestions-visuel");
    (p.suggestions || []).forEach((code) => {
      const f = ctx.formes.find((x) => x.code === code);
      const b = el("button", { type: "button", classe: "puce-forme", "data-forme": code, texte: f ? f.nom : code });
      sugg.appendChild(b);
    });
    sugg.hidden = !(p.suggestions || []).length;
    n.appendChild(sugg);
    n.setAttribute("tabindex", "0");
    n.classList.add("modifiable");
    if (edition.selection === id) n.classList.add("selectionne");
    if (window.Sortable && glisserPermis()) {
      Sortable.create(depot, { group: { name: "kpi", pull: false, put: true }, sort: false, animation: 0, fallbackOnBody: true, swapThreshold: 0.65,
        onAdd: (evt) => { const code = evt.item.dataset.code; evt.item.remove(); if (code) ajouterAuVisuel(code, id); } });
    }
  }
  grille.addEventListener("click", (e) => {
    if (!edition.actif) return;
    const n = e.target.closest("[data-visuel]");
    if (!n) return;
    const puce = e.target.closest(".puce-forme");
    if (puce) { changerForme(n.dataset.id, puce.dataset.forme); return; }
    if (e.target.closest(".selection-visuel") || (!e.target.closest("a, button, summary, details, input, select, .graphique") )) selectionner(n.dataset.id, true);
  });
  grille.addEventListener("keydown", (e) => {
    if (!edition.actif) return;
    const poignee = e.target.closest(".poignee-visuel");
    if (poignee) { deplacerAuClavier(e, poignee.closest("[data-visuel]").dataset.id); return; }
    if (e.key === "Enter" && e.target.matches("[data-visuel]")) { e.preventDefault(); selectionner(e.target.dataset.id, true); }
  });
  function deplacerAuClavier(e, id) {
    const liste = edition.brouillon.visuels, i = liste.findIndex((x) => x.id === id);
    let j = i;
    if (e.key === "ArrowLeft" || e.key === "ArrowUp") j = i - 1;
    else if (e.key === "ArrowRight" || e.key === "ArrowDown") j = i + 1;
    else if (e.key === "Home") j = 0;
    else if (e.key === "End") j = liste.length - 1;
    else return;
    e.preventDefault();
    if (j < 0 || j >= liste.length || j === i) return;
    liste.splice(j, 0, liste.splice(i, 1)[0]);
    marquer();
    rendre();
    const p = payloadDe(id);
    const poignee = grille.querySelector(`[data-visuel][data-id="${id}"] .poignee-visuel`);
    if (poignee) poignee.focus();
    toast(t("visu.deplace", { titre: p.titre, position: j + 1, total: liste.length }));
  }

  // -- ajouter : un KPI à la vue (forme choisie par le serveur), un KPI à un visuel, un autre visuel
  function textePlafond() {  // une vue convertie d'un ancien tableau peut avoir plus de visuels que permis : elle en perd, pas plus
    const l = ctx.limites;
    return l.plafond > l.max_visuels ? t("visu.vue.trop_de_visuels_ancienne", { n: l.plafond, max: l.max_visuels })
      : t("visu.vue.trop_de_visuels", { max: l.max_visuels });
  }
  function ajouterVisuel(def, position) {
    const v = { id: nouvelId(), titre: "", kpis: [], source: "", axe: "", series: "", largeur: 6, hauteur: "m", filtres: {}, options: {}, ...def };
    const liste = edition.brouillon.visuels;
    if (liste.length >= ctx.limites.visuels) { toast(textePlafond()); return null; }
    liste.splice(position === undefined || position === null ? liste.length : position, 0, v);
    marquer();
    rendre();
    actualiser(v.id).then(() => { const p = donnees.visuels[v.id]; toast(t("visu.visuel.ajoute", { titre: p ? p.titre : v.id })); });
    return v.id;
  }
  function ajouterKpi(code, position) { return ajouterVisuel({ type: "auto", kpis: [code] }, position); }
  function ajouterAuVisuel(code, id) {
    const def = definitionDe(id);
    if (!def) return;
    if (def.kpis.indexOf(code) >= 0) return;
    const k = kpiCat(code), premier = kpiCat(def.kpis[0]);
    const max = def.type === "tableau" ? 300 : (def.type === "comparaison_n1" ? 20 : ctx.limites.kpis);
    const compatible = !def.kpis.length || def.type === "tableau" || (k && premier && k.unite === premier.unite && k.format === premier.format);
    if (def.type === "remplissage" || !compatible || def.kpis.length >= max) {
      const i = edition.brouillon.visuels.indexOf(def);
      ajouterKpi(code, i + 1);
      toast(t(def.kpis.length >= max ? "visu.visuel.trop_de_kpis" : "visu.visuel.unites_differentes", { max: max }));
      return;
    }
    def.kpis.push(code);
    if (["chiffre", "organisations", "anneau"].indexOf(def.type) >= 0 && def.kpis.length > 1) def.type = "auto";
    marquer();
    actualiser(id).then(() => toast(t("visu.visuel.serie_ajoutee", { kpi: nomKpi(code), titre: payloadDe(id).titre })));
  }
  function changerForme(id, forme) {
    const def = definitionDe(id);
    if (!def) return;
    def.type = forme;
    if (forme === "remplissage") def.kpis = [];
    def.largeur = (ctx.formes.find((f) => f.code === forme) || {}).largeur || def.largeur;
    marquer();
    actualiser(id);
    annoncer(t("visu.reglages.forme_changee", { forme: (ctx.formes.find((f) => f.code === forme) || {}).nom || forme }));
  }

  // -- panneau des KPI (catalogue chargé à l'entrée en modification)
  async function chargerCatalogue() {
    if (edition.catalogue) return;
    const rep = await fetch(ctx.urls.catalogue, { headers: window.outils.entetes() });
    if (!rep.ok) { toast(t("visu.erreur.reseau")); return; }
    const c = await rep.json();
    c.parCode = {};
    c.kpis.forEach((k) => { c.parCode[k.code] = k; k.cherche = sansAccents(`${k.code} ${k.nom}`); });
    edition.catalogue = c;
    const rediges = panneauKpi.querySelector("[data-kpi-rediges]");  // réponses rédigées : pas proposées (pas de graphique)
    if (rediges) rediges.hidden = !c.rediges;
    const sel = panneauKpi.querySelector("[data-ref-kpi]");
    sel.replaceChildren();
    c.referentiels.forEach((r) => sel.appendChild(el("option", { value: r.code, texte: r.nom })));
    sel.appendChild(el("option", { value: "", texte: t("visu.filtres.tous") }));
    const voulu = donnees.filtres.referentiel.code;
    if (voulu && c.referentiels.some((r) => r.code === voulu)) sel.value = voulu;
    construireListeKpi();
  }
  function ligneKpi(k) {
    const li = el("li", { classe: "kpi-liste", "data-code": k.code });
    li.appendChild(el("span", { classe: "nom-kpi", texte: k.nom }));
    li.appendChild(el("span", { classe: "unite-kpi", texte: k.unite || t("visu.kpi.unite_aucune") }));
    li.appendChild(el("button", { type: "button", classe: "ajouter-kpi", "data-ajouter-kpi": k.code, "aria-label": t("visu.kpi.ajouter_aria", { kpi: k.nom }), title: t("visu.kpi.ajouter") }, [icone("plus")]));
    const sel = edition.selection ? payloadDe(edition.selection) : null;
    const b = el("button", { type: "button", classe: "ajouter-kpi-visuel", "data-ajouter-au-visuel": k.code, title: t("visu.kpi.ajouter_visuel"), texte: "→" });
    if (sel) b.setAttribute("aria-label", t("visu.kpi.ajouter_visuel_aria", { kpi: k.nom, titre: sel.titre })); else b.hidden = true;
    li.appendChild(b);
    return li;
  }
  function construireListeKpi() {
    const c = edition.catalogue;
    if (!c) return;
    const zone = panneauKpi.querySelector("[data-liste-kpi]");
    const ref = panneauKpi.querySelector("[data-ref-kpi]").value;
    const q = sansAccents(panneauKpi.querySelector("[data-chercher-kpi]").value.trim());
    const themesVue = donnees.filtres.themes || [];
    const ouverts = new Set(Array.from(zone.querySelectorAll("details[open]")).map((d) => d.dataset.cle));
    zone.replaceChildren();
    const arbres = ref ? c.referentiels.filter((r) => r.code === ref) : c.referentiels;
    const vus = new Set();
    let total = 0;
    arbres.forEach((r) => {
      const racines = r.themes.filter((x) => x.prof === 0);
      racines.forEach((th) => {
        const kpis = c.kpis.filter((k) => k.places.some((pl) => pl.ref === r.code && pl.themes[0] === th.id
          && (!themesVue.length || pl.themes.some((x) => themesVue.indexOf(x) >= 0))) && (!q || k.cherche.indexOf(q) >= 0));
        if (!kpis.length || (ref === "" && kpis.every((k) => vus.has(k.code)))) return;
        const d = el("details", { classe: "groupe-theme", "data-cle": `${r.code}-${th.id}` });
        if (q || ouverts.has(`${r.code}-${th.id}`)) d.open = true;
        d.appendChild(el("summary", { texte: `${ref ? "" : r.nom + " · "}${th.nom} (${kpis.length})` }));
        d.appendChild(el("button", { type: "button", classe: "lien-donnees ajouter-theme", "data-ajouter-theme": th.id, texte: `+ ${t("visu.kpi.theme")}` }));
        const ul = el("ul", { classe: "groupe-kpi" });
        kpis.forEach((k) => { if (!vus.has(k.code)) { vus.add(k.code); ul.appendChild(ligneKpi(k)); total++; } });
        d.appendChild(ul);
        zone.appendChild(d);
      });
    });
    if (!ref) {
      const hors = c.kpis.filter((k) => !vus.has(k.code) && (!q || k.cherche.indexOf(q) >= 0));
      if (hors.length) {
        const d = el("details", { classe: "groupe-theme", "data-cle": "hors" }, [el("summary", { texte: `${t("visu.kpi.hors_referentiel")} (${hors.length})` })]);
        if (q || ouverts.has("hors")) d.open = true;
        const ul = el("ul", { classe: "groupe-kpi" });
        hors.forEach((k) => { ul.appendChild(ligneKpi(k)); total++; });
        d.appendChild(ul);
        zone.appendChild(d);
      }
    }
    // listes de KPI, puis autres visuels : mêmes groupes repliables que les thèmes 
    c.listes.forEach((x) => {
      const kpis = x.kpis.map((code) => c.parCode[code]).filter((k) => k && (!q || k.cherche.indexOf(q) >= 0));
      if (q && !kpis.length) return;
      const cle = `liste-${x.id}`;
      const d = el("details", { classe: "groupe-theme groupe-liste", "data-cle": cle });
      if ((q && kpis.length) || ouverts.has(cle)) d.open = true;
      d.appendChild(el("summary", { texte: `${t("visu.kpi.liste_groupe", { nom: x.nom })} (${x.kpis.length})` }));
      d.appendChild(el("button", { type: "button", classe: "lien-donnees ajouter-theme", "data-ajouter-liste": x.id, texte: `+ ${t("visu.kpi.liste_tableau")}` }));
      const ul = el("ul", { classe: "groupe-kpi" });
      kpis.forEach((k) => ul.appendChild(ligneKpi(k)));
      d.appendChild(ul);
      zone.appendChild(d);
    });
    if (!q) {
      const d = el("details", { classe: "groupe-theme groupe-autres", "data-cle": "autres" });
      if (ouverts.has("autres")) d.open = true;
      d.appendChild(el("summary", { texte: t("visu.kpi.autres_visuels") }));
      const b = el("button", { type: "button", classe: "lien-donnees ajouter-theme", "data-ajouter-autre": "remplissage" });
      const modele = panneauKpi.querySelector("[data-modele-remplissage]");
      if (modele) b.appendChild(modele.content.cloneNode(true));
      b.appendChild(document.createTextNode(` + ${t("visu.type.remplissage")}`));
      d.appendChild(b);
      zone.appendChild(d);
    }
    if (!total) zone.appendChild(el("p", { classe: "discret", texte: t("visu.kpi.aucun") }));
    if (window.Sortable && glisserPermis()) {
      zone.querySelectorAll(".groupe-kpi").forEach((ul) => Sortable.create(ul, {
        group: { name: "kpi", pull: "clone", put: false }, sort: false, animation: 0, delayOnTouchOnly: true, delay: 120,
        filter: "button", preventOnFilter: false }));
    }
  }
  if (panneauKpi) {
    panneauKpi.querySelector("[data-ref-kpi]").addEventListener("change", construireListeKpi);
    let attente = null;
    panneauKpi.querySelector("[data-chercher-kpi]").addEventListener("input", () => { clearTimeout(attente); attente = setTimeout(construireListeKpi, 200); });
    panneauKpi.addEventListener("click", (e) => {
      const b = e.target.closest("button");
      if (!b) return;
      if (b.dataset.ajouterKpi) ajouterKpi(b.dataset.ajouterKpi);
      else if (b.dataset.ajouterAuVisuel && edition.selection) ajouterAuVisuel(b.dataset.ajouterAuVisuel, edition.selection);
      else if (b.dataset.ajouterTheme) ajouterVisuel({ type: "tableau", source: `theme:${b.dataset.ajouterTheme}`, largeur: 12 });
      else if (b.dataset.ajouterListe) ajouterVisuel({ type: "tableau", source: `liste:${b.dataset.ajouterListe}`, largeur: 12 });
      else if (b.dataset.ajouterAutre) ajouterVisuel({ type: b.dataset.ajouterAutre, largeur: 6 });
    });
  }

  // -- panneau des réglages du visuel sélectionné
  const SI = { axe: ["barres", "barres_empilees"], series: ["courbe"], valeurs_ecrites: ["barres", "courbe"],
               tri: ["organisations"], max: ["organisations"], repere: ["organisations"], remplissage_par: ["remplissage"],
               colonnes: ["tableau"], cent_pour_cent: ["barres_empilees"], forme_anneau: ["anneau"], total_centre: ["anneau"] };
  function selectionner(id, focus) {
    edition.selection = id;
    grille.querySelectorAll("[data-visuel].selectionne").forEach((x) => x.classList.remove("selectionne"));
    const n = grille.querySelector(`[data-visuel][data-id="${id}"]`);
    if (n) n.classList.add("selectionne");
    panneauReglages.hidden = false;
    panneauReglages.classList.add("ouvert");
    espace.classList.add("avec-reglages");
    remplirReglages();
    construireListeKpi();
    Object.values(graphiques).forEach((g) => g.resize());
    if (focus) {
      if (telephone.matches || window.matchMedia("(max-width: 1099px)").matches) ouvrirFenetre(panneauReglages, n);
      panneauReglages.querySelector("#titre-reglages").focus();
      annoncer(t("visu.reglages.selectionne", { titre: payloadDe(id).titre }));
    }
  }
  function fermerReglages() {
    const id = edition.selection;
    edition.selection = null;
    panneauReglages.hidden = true;
    panneauReglages.classList.remove("ouvert");
    espace.classList.remove("avec-reglages");
    grille.querySelectorAll("[data-visuel].selectionne").forEach((x) => x.classList.remove("selectionne"));
    if (fenetreOuverte === panneauReglages) fermerFenetre();
    construireListeKpi();
    Object.values(graphiques).forEach((g) => g.resize());
    const n = id && grille.querySelector(`[data-visuel][data-id="${id}"]`);
    if (n) n.focus();
  }
  function remplirReglages() {
    const def = edition.selection && definitionDe(edition.selection);
    racine.querySelector("[data-sans-selection]").hidden = !!def;
    formReglages.hidden = !def;
    if (!def) return;
    const p = payloadDe(def.id);
    const f = formReglages;
    f.querySelectorAll('input[name="type"]').forEach((r) => {
      const ok = !p.compatibles || p.compatibles[r.value] === undefined || p.compatibles[r.value] === true;
      r.checked = r.value === def.type;
      r.disabled = !ok && r.value !== def.type;
      const raison = f.querySelector(`#raison-${r.value}`);
      raison.textContent = ok ? "" : p.compatibles[r.value];
      r.closest(".choix-forme").classList.toggle("grisee", !ok);
    });
    const liste = f.querySelector("[data-kpis-visuel]");
    liste.replaceChildren();
    def.kpis.forEach((code, i) => {
      const nom = nomKpi(code);
      liste.appendChild(el("li", { "data-code": code }, [
        el("span", { classe: "nom-kpi", texte: nom }),
        el("button", { type: "button", classe: "icone", "data-kpi-action": "monter", "aria-label": t("visu.reglages.monter", { kpi: nom }), disabled: i === 0 ? "disabled" : null, texte: "↑" }),
        el("button", { type: "button", classe: "icone", "data-kpi-action": "descendre", "aria-label": t("visu.reglages.descendre", { kpi: nom }), disabled: i === def.kpis.length - 1 ? "disabled" : null, texte: "↓" }),
        el("button", { type: "button", classe: "icone", "data-kpi-action": "retirer", "aria-label": t("visu.reglages.retirer", { kpi: nom }) }, [icone("x")])]));
    });
    if (!def.kpis.length && def.type !== "remplissage" && !def.source) liste.appendChild(el("li", { classe: "discret", texte: t("visu.reglages.aucun_kpi") }));
    const src = f.querySelector("[data-source-visuel]");
    src.hidden = !def.source;
    src.textContent = def.source ? p.titre : "";
    const fi = def.filtres || {}, op = def.options || {};
    const val = (nom, x) => { const c = f.elements[nom]; if (c) c.value = x === undefined || x === null ? "" : String(x); };
    val("axe", def.axe); val("series", def.series); val("titre", def.titre); val("largeur", def.largeur); val("hauteur", def.hauteur);
    val("f_periode", typeof fi.periode === "number" ? fi.periode : ""); val("f_comparaison", fi.comparaison); val("f_org", typeof fi.org === "number" ? fi.org : "");
    const oc = fi.orgs_comparees || {};
    val("f_orgs_mode", oc.mode); val("f_niveau", oc.niveau || (ctx.niveaux[1] || ctx.niveaux[0] || {}).code);
    f.querySelectorAll('input[name="f_ids"]').forEach((c) => { c.checked = (oc.ids || []).indexOf(Number(c.value)) >= 0; });
    val("f_valeurs", fi.valeurs); val("f_nb_periodes", fi.nb_periodes);
    val("o_valeurs_ecrites", op.valeurs_ecrites); val("o_tri", op.tri || "valeur"); val("o_max", op.max);
    val("o_remplissage_par", op.remplissage_par || "organisations"); val("o_colonnes", op.colonnes || "periodes");
    f.elements.o_repere.checked = op.repere !== false;
    f.elements.o_cent_pour_cent.checked = !!op.cent_pour_cent;
    f.elements.o_camembert.checked = op.forme_anneau === "camembert";
    f.elements.o_total_centre.checked = op.total_centre !== false;
    f.querySelectorAll("[data-si]").forEach((x) => { x.hidden = (SI[x.dataset.si] || []).indexOf(def.type) < 0; });
    f.querySelectorAll("[data-si-mode]").forEach((x) => { x.hidden = x.dataset.siMode !== oc.mode; });
  }
  function lireReglages(def) {
    const f = formReglages, e = f.elements;
    const type = (f.querySelector('input[name="type"]:checked') || {}).value || def.type;
    def.axe = e.axe.value; def.series = e.series.value; def.titre = e.titre.value.trim().slice(0, 150);
    def.largeur = Number(e.largeur.value) || def.largeur; def.hauteur = e.hauteur.value || "m";
    const fi = {};
    if (e.f_periode.value) fi.periode = Number(e.f_periode.value);
    if (e.f_comparaison.value) fi.comparaison = e.f_comparaison.value;
    if (e.f_org.value) fi.org = Number(e.f_org.value);
    if (e.f_orgs_mode.value) {
      fi.orgs_comparees = { mode: e.f_orgs_mode.value };
      if (e.f_orgs_mode.value === "niveau") fi.orgs_comparees.niveau = e.f_niveau.value;
      if (e.f_orgs_mode.value === "choisies") fi.orgs_comparees.ids = Array.from(f.querySelectorAll('input[name="f_ids"]:checked')).map((c) => Number(c.value)).slice(0, 100);
    }
    if (e.f_valeurs.value) fi.valeurs = e.f_valeurs.value;
    const nb = Number(e.f_nb_periodes.value);
    if (nb >= 2 && nb <= 24) fi.nb_periodes = nb;
    def.filtres = fi;
    const op = {}, vis = (cle) => (SI[cle] || []).indexOf(type) >= 0;
    if (vis("valeurs_ecrites") && e.o_valeurs_ecrites.value) op.valeurs_ecrites = e.o_valeurs_ecrites.value;
    if (vis("tri") && e.o_tri.value !== "valeur") op.tri = e.o_tri.value;
    if (vis("max") && Number(e.o_max.value) >= 1 && Number(e.o_max.value) <= 30) op.max = Number(e.o_max.value);
    if (vis("repere") && !e.o_repere.checked) op.repere = false;
    if (vis("cent_pour_cent") && e.o_cent_pour_cent.checked) op.cent_pour_cent = true;
    if (vis("forme_anneau") && e.o_camembert.checked) op.forme_anneau = "camembert";
    if (vis("total_centre") && !e.o_total_centre.checked) op.total_centre = false;
    if (vis("remplissage_par") && e.o_remplissage_par.value !== "organisations") op.remplissage_par = e.o_remplissage_par.value;
    if (vis("colonnes") && e.o_colonnes.value !== "periodes") op.colonnes = e.o_colonnes.value;
    def.options = op;
    return type;
  }
  if (formReglages) {
    let attente = null;
    const appliquer = (immediat) => {
      const def = definitionDe(edition.selection);
      if (!def) return;
      clearTimeout(attente);
      attente = setTimeout(() => {
        const type = lireReglages(def);
        if (type !== def.type) { changerForme(def.id, type); return; }
        marquer();
        actualiser(def.id);
      }, immediat ? 0 : 450);
    };
    formReglages.addEventListener("change", (e) => {
      if (e.target.name === "f_orgs_mode") formReglages.querySelectorAll("[data-si-mode]").forEach((x) => { x.hidden = x.dataset.siMode !== e.target.value; });
      appliquer(e.target.name === "type");
    });
    formReglages.addEventListener("input", (e) => { if (e.target.name === "titre") appliquer(false); });
    formReglages.addEventListener("submit", (e) => e.preventDefault());
    formReglages.addEventListener("click", (e) => {
      const b = e.target.closest("[data-kpi-action]");
      const def = definitionDe(edition.selection);
      if (b && def) {
        const code = b.closest("li").dataset.code, i = def.kpis.indexOf(code), action = b.dataset.kpiAction;
        if (action === "retirer") { def.kpis.splice(i, 1); annoncer(t("visu.reglages.kpi_retire", { kpi: nomKpi(code) })); }
        else {
          const j = action === "monter" ? i - 1 : i + 1;
          if (j < 0 || j >= def.kpis.length) return;
          def.kpis.splice(j, 0, def.kpis.splice(i, 1)[0]);
          annoncer(t("visu.reglages.kpi_deplace", { kpi: nomKpi(code), position: j + 1, total: def.kpis.length }));
        }
        marquer();
        remplirReglages();
        const meme = formReglages.querySelector(`[data-kpis-visuel] li[data-code="${code}"] [data-kpi-action="${action}"]`);
        (meme && !meme.disabled ? meme : formReglages.querySelector("[data-kpis-visuel] button:not([disabled])") || panneauReglages.querySelector("#titre-reglages")).focus();
        actualiser(def.id);
      } else if (e.target.closest("[data-dupliquer-visuel]") && def) {
        const i = edition.brouillon.visuels.indexOf(def);
        const id = ajouterVisuel({ ...copie(def), id: undefined }, i + 1);
        if (id) toast(t("visu.visuel.duplique", { titre: payloadDe(def.id).titre }));
      } else if (e.target.closest("[data-supprimer-visuel]") && def) {
        const titre = payloadDe(def.id).titre, i = edition.brouillon.visuels.indexOf(def), donnee = donnees.visuels[def.id];
        edition.brouillon.visuels.splice(i, 1);
        delete donnees.visuels[def.id];
        marquer();
        edition.selection = null;
        fermerReglages();
        rendre();
        const suivant = grille.querySelectorAll("[data-visuel]")[Math.min(i, edition.brouillon.visuels.length - 1)];
        // « Supprimé : X. Annuler » : le visuel revient à sa place dans la vue en cours de modification (rien n'est
        // enregistré tant que la vue ne l'est pas) ; sans le message (page ancienne), un simple avis
        const remettre = () => {
          if (!edition.actif || edition.brouillon.visuels.some((x) => x.id === def.id)) return null;
          edition.brouillon.visuels.splice(Math.min(i, edition.brouillon.visuels.length), 0, def);
          if (donnee) donnees.visuels[def.id] = donnee;
          marquer();
          rendre();
          if (!donnee) actualiser(def.id);
          annoncer(t("visu.visuel.remis", { titre: titre }));
          return grille.querySelector(`[data-visuel][data-id="${def.id}"]`);
        };
        if (window.proposerAnnulation) {
          window.proposerAnnulation({ texte: t("visu.visuel.supprime", { titre: titre }) }, remettre, suivant || grille);
        } else {
          toast(t("visu.visuel.supprime", { titre: titre }));
          (suivant || grille).focus();
        }
      }
    });
  }
  racine.addEventListener("click", (e) => {
    const f = e.target.closest("[data-fermer-panneau]");
    if (!f) return;
    if (f.closest("[data-panneau-reglages]")) fermerReglages();
    else { if (fenetreOuverte === panneauKpi) fermerFenetre(); else if (telephone.matches || window.matchMedia("(max-width: 1099px)").matches) panneauKpi.classList.remove("ouvert"); }
  });
  if (panneauReglages) panneauReglages.addEventListener("keydown", (e) => { if (e.key === "Escape" && fenetreOuverte !== panneauReglages) { e.preventDefault(); fermerReglages(); } });
  racine.addEventListener("click", (e) => {
    const b = e.target.closest("[data-ouvrir-panneau]");
    if (!b) return;
    if (b.dataset.ouvrirPanneau === "kpi") { panneauKpi.hidden = false; ouvrirFenetre(panneauKpi, b); }
    else if (edition.selection) { selectionner(edition.selection, true); }
    else { const premier = edition.brouillon.visuels[0]; if (premier) selectionner(premier.id, true); }
  });

  // -- entrer, enregistrer, annuler
  // hauteur de la barre du haut, collée en haut de l'écran : les panneaux KPI et réglages se collent en dessous
  function mesurerBarre() {
    if (!barreHaut || barreHaut.hidden) return;
    racine.style.setProperty("--haut-barre-visu", `${barreHaut.offsetHeight}px`);
    // un élément qui reçoit le focus (Tab) n'est jamais caché sous la barre : le navigateur défile en en tenant compte
    document.documentElement.style.scrollPaddingTop = `${barreHaut.offsetHeight + 12}px`;
  }
  async function entrerEdition(depuisBouton) {
    edition.actif = true;
    edition.brouillon = copie({ nom: ctx.vue.nom, description: ctx.vue.description || "", filtres: ctx.vue.filtres || {}, visuels: ctx.vue.visuels || [] });
    racine.classList.add("en-modification");
    panneauKpi.hidden = false;
    barre.hidden = false;
    if (barreHaut) {
      barreHaut.hidden = false;
      barreHaut.querySelector("[data-aide-raccourci]").textContent = t("visu.vue.raccourci", { touches: touches });
      mesurerBarre();
      // « Modifier la vue » disparaît : le focus passe à la barre du haut, et le lecteur d'écran dit où enregistrer
      if (depuisBouton) barreHaut.focus();
      annoncer(t("visu.vue.mode_annonce", { touches: touches }));
    }
    racine.querySelector("[data-outils-modification]").hidden = false;
    const nom = racine.querySelector("[data-nom-vue]");
    if (nom) nom.value = edition.brouillon.nom;
    const bouton = racine.querySelector("[data-modifier-vue]");
    if (bouton) bouton.hidden = true;
    if (!parametres.get("modifier")) { parametres.set("modifier", "1"); history.replaceState(null, "", `${location.pathname}?${parametres}`); }
    rendre();
    garderFiltres();
    if (window.Sortable && glisserPermis() && !edition.tri) {
      edition.tri = Sortable.create(grille, { group: { name: "kpi", pull: false, put: true }, handle: ".poignee-visuel", draggable: ".visuel",
        animation: 0, fallbackOnBody: true, swapThreshold: 0.65,
        onAdd: (evt) => { const code = evt.item.dataset.code; const pos = evt.newDraggableIndex; evt.item.remove(); if (code) ajouterKpi(code, pos); },
        onEnd: (evt) => {
          if (evt.from !== grille || evt.to !== grille || evt.oldIndex === evt.newIndex) return;
          const ordre = Array.from(grille.querySelectorAll(":scope > [data-visuel]")).map((x) => x.dataset.id);
          edition.brouillon.visuels.sort((a, b) => ordre.indexOf(a.id) - ordre.indexOf(b.id));
          marquer();
          rendre();
        } });
    }
    await chargerCatalogue();
  }
  function garderFiltres() {
    const b = racine.querySelector("[data-garder-filtres]");
    if (b) b.hidden = !(edition.actif && donnees.filtres.differents);
  }
  async function attendreCalculs() {
    for (let i = 0; i < 50 && Object.keys(edition.calcul).length; i++) await new Promise((r) => setTimeout(r, 100));
    const autos = edition.brouillon.visuels.filter((x) => x.type === "auto");
    for (const v of autos) await actualiser(v.id);
  }
  // « destination » : lien suivi une fois la vue enregistrée (« Enregistrer et quitter ») ; vrai si la vue est enregistrée
  async function enregistrerVue(destination) {
    if (edition.enregistrement) return false;
    edition.enregistrement = true;
    const boutons = racine.querySelectorAll("[data-enregistrer-vue]");
    boutons.forEach((b) => { b.disabled = true; });
    etatBrouillon(t("visu.vue.enregistrement"));
    try {
      await attendreCalculs();
      const nomChamp = racine.querySelector("[data-nom-vue]");
      if (nomChamp) edition.brouillon.nom = nomChamp.value.trim() || edition.brouillon.nom;
      const corps = { nom: edition.brouillon.nom, description: edition.brouillon.description, filtres: edition.brouillon.filtres,
                      visuels: edition.brouillon.visuels.filter((x) => x.type !== "auto") };
      let d;
      // en quittant la page, le refus reste à l'écran jusqu'à ce que la personne le ferme (DESIGN.md, Error-Stays)
      const signaler = destination ? (window.erreur || toast) : toast;
      // « garde » : empreintes opaques de ce que la page n'a pas reçu (hors périmètre), que le serveur garde tel quel
      if (ctx.vue.id) d = await envoyer(urlVue("enregistrer/"), { ...corps, version: ctx.vue.version, garde: ctx.vue.garde || [] }, signaler);
      else d = await envoyer(ctx.urls.creer, corps, signaler);
      if (!d) { etatBrouillon(t("visu.vue.non_enregistree")); return false; }
      edition.modifie = false;
      if (!destination) memoriser(d.message || "");  // message montré au retour sur la vue, pas sur une autre page
      window.location.href = destination || d.vue.url;
      return true;
    } finally {
      boutons.forEach((b) => { b.disabled = false; });
      edition.enregistrement = false;
    }
  }
  if (barre) {
    racine.querySelectorAll("[data-enregistrer-vue]").forEach((b) => b.addEventListener("click", () => enregistrerVue()));
    racine.querySelectorAll("[data-annuler-vue]").forEach((b) => b.addEventListener("click", async () => {
      // modifications non enregistrées : question de l'outil d'abord (bouton « Abandonner les modifications », style danger)
      if (edition.modifie && window.confirmer) {
        const source = { dataset: { confirmerBouton: t("visu.vue.annuler") }, classList: { contains: (c) => c === "danger" }, focus: () => b.focus() };
        if (!(await window.confirmer(t("visu.vue.annuler_confirmer"), source))) return;
      }
      edition.modifie = false;
      // après le rechargement, le focus va sur « Modifier la vue » (sinon il serait perdu sur la page)
      try { sessionStorage.setItem("visu-focus", "modifier"); } catch (e) { /* stockage indisponible */ }
      window.location.href = ctx.vue.id ? ctx.vue.url : ctx.urls.visu;
    }));
    const nom = racine.querySelector("[data-nom-vue]");
    if (nom) nom.addEventListener("input", () => { edition.brouillon.nom = nom.value; marquer(); });
  }
  const enregistrerFiltres = racine.querySelector("[data-enregistrer-filtres]");
  if (enregistrerFiltres) enregistrerFiltres.addEventListener("click", async () => {
    enregistrerFiltres.disabled = true;
    try {
      // seulement les filtres : les visuels de la vue ne changent pas ; « garde » : ce que la page n'a pas reçu reste tel quel
      const d = await envoyer(urlVue("enregistrer/"), { version: ctx.vue.version, filtres: donnees.filtres.brut, garde: ctx.vue.garde || [] });
      if (!d) return;
      memoriser(t("visu.filtres.enregistres", { nom: ctx.vue.nom }));
      window.location.href = ctx.vue.url;
    } finally {
      enregistrerFiltres.disabled = false;
    }
  });
  const garder = racine.querySelector("[data-garder-filtres]");
  if (garder) garder.addEventListener("click", () => {
    edition.brouillon.filtres = copie(donnees.filtres.brut);
    parametres = new URLSearchParams("modifier=1");
    history.replaceState(null, "", `${location.pathname}?${parametres}`);
    marquer();
    garder.hidden = true;
    toast(t("visu.vue.filtres_gardes"));
  });
  // Fermer l'onglet ou la fenêtre : seule la question du navigateur est possible. Un lien de l'outil (onglets des vues,
  // onglets du bandeau, tout lien interne) pose la question de l'outil à trois choix, comme le panneau de saisie.
  window.addEventListener("beforeunload", (e) => { if (edition.actif && edition.modifie) { e.preventDefault(); e.returnValue = ""; } });
  const fenetreQuitter = document.querySelector('[data-fenetre="quitter"]');
  let destinationQuitter = null;
  document.addEventListener("click", (e) => {
    if (!fenetreQuitter || !edition.actif || !edition.modifie || e.defaultPrevented) return;
    if (e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;  // nouvel onglet : la page reste
    const a = e.target.closest("a[href]");
    if (!a || (a.target && a.target !== "_self") || a.hasAttribute("download") || fenetreQuitter.contains(a)) return;
    const url = new URL(a.href, location.href);
    if (url.origin !== location.origin) return;
    if (url.hash && url.pathname === location.pathname && url.search === location.search) return;  // ancre de la page
    e.preventDefault();
    destinationQuitter = url.href;
    ouvrirFenetre(fenetreQuitter, a);
    fenetreQuitter.querySelector('[data-quitter="continuer"]').focus();
  });
  if (fenetreQuitter) fenetreQuitter.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-quitter]");
    if (!b || b.disabled) return;
    const destination = destinationQuitter;
    if (b.dataset.quitter === "continuer" || !destination) { fermerFenetre(); return; }  // retour au lien, rien ne change
    if (b.dataset.quitter === "sans") { edition.modifie = false; window.location.href = destination; return; }
    // « Enregistrer et quitter » : le lien n'est suivi qu'une fois la vue enregistrée ; refusée, on reste en modification
    const texte = b.textContent, boutons = fenetreQuitter.querySelectorAll("[data-quitter]");
    boutons.forEach((x) => { x.disabled = true; });
    b.setAttribute("aria-busy", "true");
    b.textContent = t("visu.vue.enregistrement");
    let ok = false;
    try { ok = await enregistrerVue(destination); } finally {
      if (!ok) {
        boutons.forEach((x) => { x.disabled = false; });
        b.removeAttribute("aria-busy");
        b.textContent = texte;
        fermerFenetre();
      }
    }
  });
  racine.addEventListener("click", (e) => { if (e.target.closest("[data-modifier-vue]")) entrerEdition(true); });
  // Ctrl + S (Cmd + S sur Mac) : en mode modification seulement, enregistre la vue au lieu d'enregistrer la page dans le
  // navigateur ; rien pendant qu'une fenêtre (renommer, confirmer…) est ouverte
  document.addEventListener("keydown", (e) => {
    if (!edition.actif || !(e.ctrlKey || e.metaKey) || e.altKey || e.shiftKey || String(e.key).toLowerCase() !== "s") return;
    e.preventDefault();
    if (fenetreOuverte && fenetreOuverte.matches(".fenetre-visu")) return;
    enregistrerVue();
  });
  if (barreHaut && window.ResizeObserver) new ResizeObserver(mesurerBarre).observe(barreHaut);

  // -- vues : renommer, supprimer, onglets à glisser
  function memoriser(message) { try { sessionStorage.setItem("visu-message", message); } catch (e) { /* stockage indisponible */ } }
  const fenetreRenommer = document.querySelector('[data-fenetre="renommer"]');
  function renommer(depuis) {
    const f = fenetreRenommer.querySelector("form");
    f.elements.nom.value = edition.actif ? edition.brouillon.nom : ctx.vue.nom;
    f.elements.description.value = edition.actif ? edition.brouillon.description : (ctx.vue.description || "");
    ouvrirFenetre(fenetreRenommer, depuis);
    f.elements.nom.select();
  }
  if (fenetreRenommer) fenetreRenommer.querySelector("form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = e.target, nom = f.elements.nom.value.trim(), description = f.elements.description.value.trim();
    if (!nom) { f.elements.nom.focus(); return; }
    if (edition.actif || !ctx.vue.id) {
      edition.brouillon.nom = nom; edition.brouillon.description = description;
      const champ = racine.querySelector("[data-nom-vue]");
      if (champ) champ.value = nom;
      marquer();
      fermerFenetre();
      return;
    }
    const d = await envoyer(urlVue("enregistrer/"), { version: ctx.vue.version, nom: nom, description: description });
    if (d) { fermerFenetre(); memoriser(d.message); window.location.reload(); }
  });
  // vue d'accueil par rôle (administrateur, vue partagée) : une seule par rôle, cocher un rôle remplace sa vue d'accueil
  const fenetreAccueil = document.querySelector('[data-fenetre="accueil"]');
  if (fenetreAccueil) fenetreAccueil.querySelector("form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const coches = Array.from(e.target.querySelectorAll('input[name="role"]:checked'));
    const d = await envoyer(urlVue("preferee/"), { accueil: coches.map((c) => c.value) });
    if (!d) return;
    coches.forEach((c) => { const ailleurs = c.closest("label").querySelector(".discret"); if (ailleurs) ailleurs.remove(); });
    fermerFenetre();
    toast(d.message);
    annoncer(d.message);
  });
  // supprimer la vue : sans question (corbeille) ; la page suivante propose « Annuler » (message gardé par le serveur)
  async function supprimerVue() {
    const d = await envoyer(urlVue("supprimer/"));
    if (d) { edition.modifie = false; window.location.href = d.url; }
  }
  racine.addEventListener("click", (e) => {
    const b = e.target.closest("[data-action-vue]");
    if (!b) return;
    if (b.dataset.actionVue === "renommer") renommer(racine.querySelector(".menu-vue summary"));
    else if (b.dataset.actionVue === "supprimer") supprimerVue();
  });
  const ongletsListe = racine.querySelector("[data-onglets-vues] ul");
  if (ongletsListe && window.Sortable && !tactile.matches) {
    Sortable.create(ongletsListe, { draggable: "li[data-vue-id]", animation: 0, onEnd: async (evt) => {
      if (evt.oldIndex === evt.newIndex) return;
      const ids = Array.from(ongletsListe.querySelectorAll("li[data-vue-id]")).map((x) => Number(x.dataset.vueId));
      const d = await envoyer(ctx.urls.ordre, { ordre: ids, partagees: ctx.droits.admin });
      if (d) toast(d.message);
    } });
  }
  try { const m = sessionStorage.getItem("visu-message"); if (m) { toast(m); sessionStorage.removeItem("visu-message"); } } catch (e) { /* stockage indisponible */ }
  try {
    if (sessionStorage.getItem("visu-focus") === "modifier") {
      sessionStorage.removeItem("visu-focus");
      racine.querySelector("[data-modifier-vue]")?.focus();
    }
  } catch (e) { /* stockage indisponible */ }
  // une seule fois (mémorisé dans ce navigateur) : les anciens tableaux sont devenus des vues
  try {
    if (ctx.tableaux_convertis && !localStorage.getItem("visu-tableaux-vues")) {
      localStorage.setItem("visu-tableaux-vues", "1");
      setTimeout(() => toast(t("visu.vue.tableaux_devenus_vues")), 600);
    }
  } catch (e) { /* stockage indisponible : rien à mémoriser */ }

  // ---------------------------------------------------------------- départ
  const consigne = el("p", { id: "consigne-graphique", classe: "visuellement-cache", texte: t("visu.visuel.points_aria") });
  racine.appendChild(consigne);
  telephone.addEventListener("change", () => rendre());
  racine.classList.toggle("tactile", tactile.matches);
  rendre();
  if (ctx.droits.modifier) entrerEdition();
  window.visualisation = { ctx: ctx, donnees: () => donnees, graphiques: graphiques, t: t, recharger: charger };
})();
