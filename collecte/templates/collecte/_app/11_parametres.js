{% load collecte %}{# paramètres : identité, couleurs des graphiques, niveaux, unités, types de réponse, catégories de description #}
  // ---------------------------------------------------------------- paramètres : identité (aperçu en direct)
  const identite = document.querySelector("[data-identite]");
  if (identite) {
    const champs = { principale: "#id_couleur_principale", accent: "#id_couleur_accent", fond: "#id_couleur_fond", texte: "#id_couleur_texte" };
    const valeur = (cle) => identite.querySelector(champs[cle]).value.trim().toUpperCase();
    let attente = null;
    function apercu() {
      clearTimeout(attente);
      attente = setTimeout(async () => {
        const params = new URLSearchParams(Object.fromEntries(Object.keys(champs).map((c) => [c, valeur(c)])));
        params.set("palette", identite.querySelector("input[name=palette]:checked")?.value || "");
        if (![...params.values()].slice(0, 4).every(hexValide)) return;
        const rep = await fetch(`${identite.dataset.apercuUrl}?${params}`, { headers: { "X-Requested-With": "fetch" } });
        const d = await rep.json();
        if (!d.ok) return;
        identite.querySelectorAll("[data-apercu]").forEach((z) => { z.style.cssText = d.css; });  // simulateur et aperçu clair
        const sombre = identite.querySelector("[data-apercu-sombre]");
        if (sombre && d.css_sombre) sombre.style.cssText = d.css_sombre;
        const lignes = (liste) => liste.map((c) =>
          `<li class="${c.ok ? "ok" : "ko"}"><span>${c.libelle}</span><b>${decimale(c.rapport)}</b></li>`).join("");
        identite.querySelector("[data-controles]").innerHTML = lignes(d.controles);
        const listeSombre = identite.querySelector("[data-controles-sombres]");
        if (listeSombre && d.controles_sombres) listeSombre.innerHTML = lignes(d.controles_sombres);
        identite.querySelector("[data-alerte-contraste]").hidden = d.controles.concat(d.controles_sombres || []).every((c) => c.ok);
        // pastilles du volet « Lisibilité » : contrôles conformes par apparence ; le volet s'ouvre si un contrôle échoue
        [["clair", d.controles], ["sombre", d.controles_sombres || []]].forEach(([cle, liste]) => {
          const bilan = identite.querySelector(`[data-bilan="${cle}"]`);
          if (!bilan || !liste.length) return;
          const bons = liste.filter((c) => c.ok).length;
          bilan.querySelector("[data-bilan-ok]").textContent = bons;
          bilan.classList.toggle("ok", bons === liste.length); bilan.classList.toggle("ko", bons !== liste.length);
          if (bons !== liste.length) bilan.closest("details").open = true;
        });
        const adapt = identite.querySelector("[data-adaptations]");
        if (adapt) {
          adapt.replaceChildren(...(d.adaptations || []).map((t) => Object.assign(document.createElement("li"), { textContent: t })));
          adapt.hidden = !(d.adaptations || []).length;
        }
      }, 120);
    }
    function paletteSelonCouleurs() {  // les 4 couleurs d'une palette → cette palette, sinon « Personnalisée »
      const p = [...identite.querySelectorAll("input[name=palette][data-principale]")].find((r) =>
        Object.keys(champs).every((c) => r.dataset[c].toUpperCase() === valeur(c)));
      (p || identite.querySelector("input[name=palette][value=perso]")).checked = true;
    }
    identite.addEventListener("input", (e) => {
      const t = e.target;
      if (t.dataset.pipette) { identite.querySelector(`#${t.dataset.pipette}`).value = t.value.toUpperCase(); paletteSelonCouleurs(); apercu(); }
      else if (Object.values(champs).some((sel) => t.matches(sel))) {
        const v = t.value.trim().toUpperCase();
        if (hexValide(v)) identite.querySelector(`[data-pipette=${t.id}]`).value = v;
        paletteSelonCouleurs(); apercu();
      } else if (t.id === "id_titre") identite.querySelectorAll("[data-titre-apercu]").forEach((s) => { s.textContent = t.value; });
      else if (t.id === "id_sous_titre") identite.querySelectorAll("[data-sous-titre-apercu]").forEach((s) => { s.textContent = t.value; });
      else if (t.id === "id_sigle") identite.querySelectorAll("[data-sigle-apercu]").forEach((s) => { s.textContent = t.value; });
      else if (t.id === "id_contact") identite.querySelectorAll("[data-contact-apercu]").forEach((s) => { s.textContent = t.value; });
    });
    identite.addEventListener("change", (e) => {
      if (e.target.name === "logo" && e.target.files[0]) {  // logo choisi : visible tout de suite
        const url = URL.createObjectURL(e.target.files[0]);
        identite.querySelectorAll(".logo-actuel, .ap-logo").forEach((c) => { c.innerHTML = `<img src="${url}" alt="">`; });
        return;
      }
      const r = e.target;
      if (r.name !== "palette" || !r.dataset.principale) return;
      Object.keys(champs).forEach((c) => {
        identite.querySelector(champs[c]).value = r.dataset[c].toUpperCase();
        identite.querySelector(`[data-pipette=${champs[c].slice(1)}]`).value = r.dataset[c].toUpperCase();
      });
      apercu();
    });
  }

  // ---------------------------------------------------------------- paramètres : couleurs des graphiques (aperçu, 3:1)
  // Chaque couleur est mesurée contre le fond des cartes : une couleur choisie (autre que celle de la palette fournie à
  // cette place) sous 3:1 est signalée « trop claire », et la phrase dit que les valeurs de sa série seront toujours écrites.
  const couleursViz = document.querySelector("[data-couleurs-graphiques]");
  if (couleursViz) {
    const seuil = Number(couleursViz.dataset.seuil) || 3;
    const defaut = (couleursViz.dataset.defaut || "").split(",");
    const surface = getComputedStyle(document.documentElement).getPropertyValue("--surface").trim().toUpperCase();
    const canal = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
    const luminance = (h) => { const n = parseInt(h.slice(1), 16); return 0.2126 * canal((n >> 16) & 255) + 0.7152 * canal((n >> 8) & 255) + 0.0722 * canal(n & 255); };
    const contraste = (a, b) => { const [x, y] = [luminance(a), luminance(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };
    const champsViz = [...couleursViz.querySelectorAll("[data-viz]")];
    function majViz() {
      const valeurs = champsViz.map((c) => c.value.trim().toUpperCase());
      let claires = 0;
      champsViz.forEach((c, i) => {
        const v = valeurs[i];
        if (!hexValide(v) || !hexValide(surface)) return;
        const r = contraste(v, surface);
        couleursViz.querySelector(`[data-rapport-viz="${c.id}"]`).textContent = (Math.round(r * 10) / 10).toLocaleString(document.documentElement.lang || "fr");
        const marque = couleursViz.querySelector(`[data-marque-viz="${c.id}"]`);  // ✓ à 3:1 ou plus, sinon alerte
        if (marque) { marque.classList.toggle("ok", r >= seuil); marque.classList.toggle("bas", r < seuil); }
        const trop = r < seuil && v !== defaut[i];
        couleursViz.querySelector(`[data-claire-viz="${c.id}"]`).hidden = !trop;
        const barre = couleursViz.querySelector(`[data-barre-viz="${c.id}"]`);
        if (barre) barre.style.background = v;
        if (trop) claires++;
      });
      couleursViz.querySelector("[data-alerte-viz]").hidden = !claires;
    }
    couleursViz.addEventListener("input", (e) => {
      const t = e.target;
      if (t.dataset.pipette) couleursViz.querySelector(`#${t.dataset.pipette}`).value = t.value.toUpperCase();
      else if (t.matches("[data-viz]") && hexValide(t.value.trim().toUpperCase())) couleursViz.querySelector(`[data-pipette="${t.id}"]`).value = t.value.trim().toUpperCase();
      majViz();
    });
    majViz();
  }

  // ---------------------------------------------------------------- paramètres : niveaux de l'arbre (aperçu en direct)
  const pageNiveaux = document.querySelector("[data-niveaux]");
  if (pageNiveaux) {
    function majNiveau(code) {
      const nom = pageNiveaux.querySelector(`[name="nom_${code}"]`)?.value.trim();
      const c = pageNiveaux.querySelector(`#couleur_${code}`)?.value.trim().toUpperCase();
      pageNiveaux.querySelectorAll(`[data-etiquette="${code}"]`).forEach((el) => {
        if (nom) el.textContent = nom;
        if (hexValide(c)) { el.style.background = `color-mix(in srgb, ${c} 16%, white)`; el.style.color = `color-mix(in srgb, ${c} 62%, black)`; }
      });
      if (hexValide(c)) pageNiveaux.querySelectorAll(`[data-trait="${code}"]`).forEach((el) => { el.style.background = c; });
    }
    pageNiveaux.addEventListener("input", (e) => {
      const t = e.target;
      if (t.dataset.pipette) pageNiveaux.querySelector(`#${t.dataset.pipette}`).value = t.value.toUpperCase();
      else if (t.id?.startsWith("couleur_") && hexValide(t.value.trim().toUpperCase())) pageNiveaux.querySelector(`[data-pipette="${t.id}"]`).value = t.value.trim().toUpperCase();
      const code = (t.dataset.pipette || t.name || "").replace(/^(couleur|nom|pluriel)_/, "");
      if (pageNiveaux.querySelector(`[data-code="${code}"]`)) majNiveau(code);
    });
  }
  // Paramètres › Unités et types : sélecteur de couleur ↔ champ texte
  const pageReglable = document.querySelector("[data-reglable]");
  if (pageReglable) {
    pageReglable.addEventListener("input", (e) => {
      const t = e.target;
      if (t.dataset.pipette) pageReglable.querySelector(`#${t.dataset.pipette}`).value = t.value.toUpperCase();
      else if (t.classList.contains("code") && hexValide(t.value.trim().toUpperCase())) {
        const p = pageReglable.querySelector(`[data-pipette="${t.id}"]`);
        if (p) p.value = t.value.trim().toUpperCase();
      }
    });
  }
  // Paramètres › Unités : aperçu d'une réponse (ligne et panneau de droite), mis à jour pendant la frappe
  const apUnite = document.querySelector("[data-apercu-unite]");
  if (apUnite) {
    const formatNombre = (v, d) => {  // comme le serveur : « 1 234,57 », arrondi comme Excel, pas de « -0 »
      const t = arrondiTexte(v, d), [ent, dec] = t.split(".");
      return (v < 0 && /[1-9]/.test(t) ? "-" : "") + ent.replace(/\B(?=(\d{3})+(?!\d))/g, MILLIERS) + (dec ? DECIMALE + dec : "");
    };
    // Un champ non modifié montre le nom dans la langue de l'écran (data-symbole-ecran, data-nom-ecran) ; un texte tapé, tel quel.
    const texte = (l, selecteur, ecran) => {
      const c = l.querySelector(selecteur);
      return c.value === c.defaultValue && l.dataset[ecran] ? l.dataset[ecran] : c.value.trim();
    };
    const lire = (l) => ({
      symbole: texte(l, "[data-symbole]", "symboleEcran"), nom: texte(l, "[data-nom]", "nomEcran"),
      entier: l.querySelector("[data-entier]").checked,
      decimales: Math.min(10, Math.max(0, parseInt(l.querySelector("[data-decimales]").value, 10) || 0)),
    });
    let courante = document.querySelector("[data-unite]");
    const champ = apUnite.querySelector("[data-ap-valeur]");
    // nombre entier : toujours 0 décimale (champ verrouillé)
    const verrouiller = (l) => {
      const e = l.querySelector("[data-entier]"), d = l.querySelector("[data-decimales]");
      if (e.checked) { d.value = 0; d.readOnly = true; d.title = lib("saisie.js.entier_sans_decimale"); } else { d.readOnly = false; d.title = ""; }
    };
    document.querySelectorAll("[data-unite]").forEach(verrouiller);
    const rafraichir = () => {
      if (!courante) return;
      verrouiller(courante);
      const u = lire(courante), d = u.entier ? 0 : u.decimales;
      courante.querySelector("[data-apercu]").textContent = `${formatNombre(1234.5678, d)} ${u.symbole}`.trim();
      const v = lireNombre(champ.value);
      apUnite.querySelector("[data-ap-symbole]").textContent = u.symbole || "—";
      apUnite.querySelector("[data-ap-nom]").textContent = u.nom;
      apUnite.querySelector("[data-ap-u]").textContent = u.symbole;
      apUnite.querySelector("[data-ap-affiche]").textContent = isNaN(v) ? "–" : `${formatNombre(v, d)} ${u.symbole}`.trim();
      apUnite.querySelector("[data-ap-comptage]").hidden = !u.entier;
      document.querySelectorAll("[data-unite].active").forEach((l) => l.classList.remove("active"));
      courante.classList.add("active");
    };
    document.querySelectorAll("[data-unite]").forEach((l) => {
      l.addEventListener("focusin", () => { courante = l; rafraichir(); });
      l.addEventListener("click", () => { courante = l; rafraichir(); });
      l.addEventListener("input", () => { courante = l; rafraichir(); });
    });
    champ.addEventListener("input", rafraichir);
    rafraichir();
    // choix de la thématique : bulles sous le champ (filtrées pendant la frappe ; un nom nouveau reste possible)
    const themesConnus = [...document.querySelectorAll("#familles option")].map((o) => o.value);
    const bulles = document.createElement("div");
    bulles.className = "choix-theme"; bulles.hidden = true; bulles.setAttribute("role", "group"); bulles.setAttribute("aria-label", lib("saisie.js.themes_existants"));
    (document.getElementById("contenu") || document.body).appendChild(bulles);  // dans <main> : une région de la page (axe « region »)
    let cible = null;
    const montrer = (filtrer) => {
      const q = filtrer ? cible.value.trim().toLowerCase() : "";
      const liste = themesConnus.filter((t) => !q || t.toLowerCase().includes(q) || t === cible.value);
      bulles.innerHTML = "";
      liste.forEach((t) => {
        const b = document.createElement("button");
        b.type = "button"; b.textContent = t; b.setAttribute("aria-pressed", t === cible.value ? "true" : "false");
        if (t === cible.value) b.classList.add("choisi");
        b.addEventListener("mousedown", (e) => { e.preventDefault(); cible.value = t; cible.dispatchEvent(new Event("input", { bubbles: true })); bulles.hidden = true; });
        bulles.appendChild(b);
      });
      // créer une thématique : champ en bas du cadre
      const ajout = document.createElement("div"); ajout.className = "ajout-theme";
      ajout.innerHTML = `<input type="text" placeholder="${echapper(lib("saisie.js.nouvelle_thematique_placeholder"))}" aria-label="${echapper(lib("saisie.js.nouvelle_thematique_aria"))}"><button type="button">{% icone "plus" %} ${echapper(lib("saisie.js.creer"))}</button>`;
      const [nom, creer] = ajout.children;
      const valider = () => {
        const v = nom.value.trim();
        if (!v) return;
        if (!themesConnus.includes(v)) themesConnus.push(v);
        cible.value = v; cible.dispatchEvent(new Event("input", { bubbles: true })); bulles.hidden = true;
      };
      creer.addEventListener("mousedown", (e) => { e.preventDefault(); valider(); });
      nom.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); valider(); } if (e.key === "Escape") bulles.hidden = true; });
      nom.addEventListener("blur", () => setTimeout(() => { if (!bulles.contains(document.activeElement) && document.activeElement !== cible) bulles.hidden = true; }, 0));
      if (q && !liste.length) {
        const n = document.createElement("span"); n.className = "nouveau-theme"; n.textContent = lib("saisie.js.nouvelle_thematique", { nom: cible.value.trim() });
        bulles.appendChild(n);
      } else if (q && !themesConnus.some((t) => t.toLowerCase() === q)) {
        const n = document.createElement("span"); n.className = "nouveau-theme"; n.textContent = lib("saisie.js.garder_thematique", { nom: cible.value.trim() });
        bulles.appendChild(n);
      }
      bulles.appendChild(ajout);
      const r = cible.getBoundingClientRect();
      bulles.style.top = `${r.bottom + window.scrollY + 4}px`;
      bulles.style.left = `${Math.max(8, Math.min(r.left + window.scrollX, window.innerWidth - 340))}px`;
      bulles.hidden = false;
    };
    document.querySelectorAll("[data-choix-theme]").forEach((c) => {
      c.addEventListener("focus", () => { cible = c; montrer(false); });
      c.addEventListener("input", () => { if (cible === c) montrer(true); });
      c.addEventListener("blur", () => setTimeout(() => { if (!bulles.contains(document.activeElement)) bulles.hidden = true; }, 0));
      c.addEventListener("keydown", (e) => { if (e.key === "Escape") bulles.hidden = true; });
    });
    // thématiques repliables : celles ouvertes restent ouvertes après un enregistrement (mémoire de l'onglet)
    const themes = [...document.querySelectorAll("[data-theme-unites]")];
    let ouverts = [];
    try { ouverts = JSON.parse(sessionStorage.getItem("unites-ouvertes") || "[]"); } catch (e) { /* stockage indisponible */ }
    const memoriser = () => {
      try { sessionStorage.setItem("unites-ouvertes", JSON.stringify(themes.filter((d) => d.open).map((d) => d.querySelector(".nom-theme").textContent))); } catch (e) { /* idem */ }
    };
    themes.forEach((d) => {
      if (ouverts.includes(d.querySelector(".nom-theme").textContent)) d.open = true;
      d.addEventListener("toggle", memoriser);
    });
    document.querySelectorAll("[data-deplier]").forEach((b) => b.addEventListener("click", () => {
      themes.forEach((d) => { d.open = b.dataset.deplier === "1"; });
    }));
  }
  // Paramètres › Types de réponse et champs : « Valeurs » seulement pour une liste
  document.querySelectorAll("[data-ajout-reglable]").forEach((f) => {
    const choix = f.querySelector("select[name=format], select[name=type]");
    if (!choix) return;
    const montrer = () => {
      const v = choix.value;
      f.querySelectorAll("[data-champ-ajout=valeurs]").forEach((c) => { c.hidden = v !== "liste"; });
    };
    choix.addEventListener("change", montrer);
    montrer();
  });
  // Paramètres › Catégories de description : l'aperçu (contributeur / admin) suit les cases avant l'enregistrement
  document.querySelectorAll(".ligne-reglable[data-code]").forEach((l) => {
    const code = l.dataset.code;
    l.addEventListener("change", (e) => {
      const n = e.target.name || "";
      if (n.startsWith("affichee__")) {
        document.querySelectorAll(`[data-vue-contrib="${code}"]`).forEach((x) => { x.hidden = !e.target.checked; });
        document.querySelectorAll(`[data-vue-interne="${code}"]`).forEach((x) => { x.hidden = e.target.checked; });
      } else if (n.startsWith("obligatoire__")) {
        document.querySelectorAll(`[data-vue-oblig="${code}"]`).forEach((x) => { x.hidden = !e.target.checked; });
      }
    });
  });
