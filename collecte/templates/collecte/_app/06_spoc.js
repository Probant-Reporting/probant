{# SPOC : bulles et choix de la personne, sélection multiple (attribution en masse) #}
  // ---------------------------------------------------------------- SPOC : bulles et choix de la personne
  const choix = document.getElementById("choix-spoc");
  const comptes = JSON.parse(document.getElementById("comptes")?.textContent || "[]");
  let cibles = [];      // clés des cellules visées
  let modeMasse = "";   // "", "attribuer" ou "retirer"

  function bulle(c) {
    const s = document.createElement("span");
    s.className = "avatar";
    s.style.background = c.couleur;
    s.textContent = c.initiales;
    return s;
  }

  function attribuees() {
    // personnes attribuées à toutes les cellules visées
    const listes = cibles.map((cle) => (document.querySelector(`[data-cle="${CSS.escape(cle)}"]`)?.dataset.spocs || "").split(",").filter(Boolean));
    return new Set(listes.length ? listes.reduce((a, b) => a.filter((x) => b.includes(x))) : []);
  }

  function dessinerChoix() {
    const q = choix.querySelector("input").value.trim().toLowerCase();
    const ul = choix.querySelector("ul");
    const deja = attribuees();
    ul.innerHTML = "";
    // personnes déjà choisies pour ces cases en tête de liste, puis l'ordre habituel
    const trouves = comptes.filter((c) => !q || (c.nom + " " + c.email).toLowerCase().includes(q));
    const tri = modeMasse ? trouves : [...trouves.filter((c) => deja.has(String(c.id))), ...trouves.filter((c) => !deja.has(String(c.id)))];
    tri.forEach((c) => {
      // chaque personne est un vrai bouton : Tab ou flèches pour s'y rendre, Entrée ou Espace pour attribuer ou retirer
      const li = document.createElement("li");
      const b = document.createElement("button");
      b.type = "button";
      b.dataset.id = c.id;
      const bul = bulle(c);
      bul.setAttribute("aria-hidden", "true");
      b.appendChild(bul);
      const t = document.createElement("span");
      t.innerHTML = "<span class='nom-personne'></span><span class='discret'></span>";
      t.firstChild.textContent = c.nom;
      t.lastChild.textContent = c.role + " · " + c.email;
      b.appendChild(t);
      const coche = document.createElement("span");
      coche.className = "coche";
      if (!modeMasse) b.setAttribute("aria-pressed", deja.has(String(c.id)) ? "true" : "false");
      if (!modeMasse && deja.has(String(c.id))) coche.innerHTML = '<svg class="icone-svg" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M20 6 9 17l-5-5"/></svg>';
      b.appendChild(coche);
      li.appendChild(b);
      ul.appendChild(li);
    });
  }

  let ouvreurSpoc = null;  // bouton qui a ouvert la fenêtre : il reprend le focus à la fermeture
  function ouvrirSpoc(ancre, cles, mode) {
    ouvreurSpoc = ancre;
    cibles = cles;
    modeMasse = mode || "";
    const r = ancre.getBoundingClientRect();
    choix.style.top = (window.scrollY + r.bottom + 6) + "px";
    choix.style.left = Math.max(8, Math.min(window.scrollX + r.left - 150, window.scrollX + document.documentElement.clientWidth - 316)) + "px";
    if (mode) { choix.style.position = "fixed"; choix.style.top = "auto"; choix.style.bottom = "70px"; choix.style.left = "calc(50% - 150px)"; }
    else { choix.style.position = "absolute"; choix.style.bottom = "auto"; }
    choix.querySelector("input").value = "";
    dessinerChoix();
    choix.classList.add("ouvert");
    choix.querySelector("input").focus();
  }

  function fermerSpoc() {
    if (!choix?.classList.contains("ouvert")) return;
    const revenir = choix.contains(document.activeElement);
    choix.classList.remove("ouvert");
    // le focus revient au bouton d'origine (ou à sa ligne, si la ligne a été redessinée entre-temps)
    if (revenir && ouvreurSpoc) {
      const cible = ouvreurSpoc.isConnected ? ouvreurSpoc
        : document.querySelector(`[data-cle="${CSS.escape(cibles[0] || "")}"] .bouton-spoc`) || document.querySelector("#barre-masse [data-masse=attribuer]");
      cible?.focus();
    }
  }

  async function envoyerAttribution(utilisateur, retirer) {
    const rep = await fetch("{% url 'collecte:attribuer' %}", {
      method: "POST", headers: entetes(true),
      // role : « validateur » sur le choix Validateurs de la grille des Attributions, sinon contributeur
      body: JSON.stringify({ cles: cibles, utilisateur, retirer, campagne: document.body.dataset.campagne,
                             role: document.querySelector("[data-grille]")?.dataset.roleAttr || "contributeur",
                             format: document.querySelector("[data-grille]") ? "cellule" : "ligne" }),
    });
    const res = await rep.json().catch(() => ({}));
    if (!rep.ok) { erreur(res.message || lib("saisie.js.attribution_refusee")); return; }
    remplacerLignes(res.lignes);
    toast(res.message);
    modifie = true;
    rafraichir();
  }

  if (choix) {
    choix.querySelector("input").addEventListener("input", dessinerChoix);
    choix.addEventListener("click", async (e) => {
      const li = e.target.closest("[data-id]");
      if (!li) return;
      const id = li.dataset.id;
      if (modeMasse) {
        await envoyerAttribution(id, modeMasse === "retirer");
        fermerSpoc();
        decocherTout();
        // la barre de sélection disparaît : le focus va sur la case à cocher de la première ligne visée
        if (!document.activeElement || document.activeElement === document.body)
          document.querySelector(`[data-cle="${CSS.escape(cibles[0] || "")}"] .choix-case`)?.focus();
      } else {
        await envoyerAttribution(id, attribuees().has(id));
        dessinerChoix();
        choix.querySelector(`[data-id="${CSS.escape(id)}"]`)?.focus();  // le focus reste sur la personne choisie
      }
    });
    // flèches haut / bas : de la recherche aux personnes, puis d'une personne à l'autre
    choix.addEventListener("keydown", (e) => {
      if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
      const boutons = [...choix.querySelectorAll("ul button")];
      if (!boutons.length) return;
      e.preventDefault();
      const i = boutons.indexOf(document.activeElement);
      const j = e.key === "ArrowDown" ? (i < 0 ? 0 : Math.min(i + 1, boutons.length - 1)) : i - 1;
      (j < 0 ? choix.querySelector("input") : boutons[j]).focus();
    });
    document.addEventListener("click", (e) => {
      const b = e.target.closest(".bouton-spoc");
      if (b) { ouvrirSpoc(b, [b.closest("[data-cle]").dataset.cle]); return; }
      if (!e.target.closest("#choix-spoc, [data-masse]")) fermerSpoc();
    });
  }

  // ---------------------------------------------------------------- sélection multiple (attribution en masse)
  const barre = document.getElementById("barre-masse");
  function selection() {
    return Array.from(document.querySelectorAll(".choix-case:checked"))
      .filter((c) => { const tr = c.closest("tr"); return !tr.hidden && tr.offsetParent !== null; })
      .map((c) => c.closest("[data-cle]").dataset.cle);
  }
  function decocherTout() {
    document.querySelectorAll(".choix-case:checked, .choix-tout:checked, .choix-rangee:checked, .choix-colonne:checked").forEach((c) => { c.checked = false; });
    majMasse();
  }
  function majMasse() {
    if (!barre) return;
    const n = selection().length;
    barre.querySelector(".nb").textContent = n;
    const surGrille = !!document.querySelector("[data-grille]");
    barre.querySelector(".lib-selection").textContent = lib(surGrille ? "saisie.js.cases_selectionnees" : "saisie.js.lignes_selectionnees", { n });
    barre.classList.toggle("visible", n > 0);
  }
  document.addEventListener("change", (e) => {
    if (e.target.matches(".choix-tout")) {
      e.target.closest("table").querySelectorAll("tr.ligne:not([hidden]) .choix-case").forEach((c) => { c.checked = e.target.checked; });
    }
    if (e.target.matches(".choix-rangee")) {
      e.target.closest("tr").querySelectorAll(".choix-case").forEach((c) => { c.checked = e.target.checked; });
    }
    if (e.target.matches(".choix-colonne")) {
      e.target.closest("table").querySelectorAll(`tr.ligne:not([hidden]) td[data-org="${e.target.dataset.org}"] .choix-case`)
        .forEach((c) => { if (c.closest("tr").offsetParent !== null) c.checked = e.target.checked; });
    }
    if (e.target.matches(".choix-case, .choix-tout, .choix-rangee, .choix-colonne")) majMasse();
  });
  barre?.addEventListener("click", (e) => {
    const b = e.target.closest("[data-masse]");
    if (!b) return;
    if (b.dataset.masse === "annuler") {
      decocherTout();
      fermerSpoc();
      return;
    }
    ouvrirSpoc(b, selection(), b.dataset.masse);
  });

