{# export : périmètre, modèles, choix des KPI, résumé ; reprise, écart avec N-1, preuves #}
  // Export : périmètre. Les niveaux et l'arbre des organisations restent d'accord ; une organisation entraîne
  // celles qui lui sont rattachées. À l'envoi, si tout ce qui est coché = tous les niveaux cochés, on n'envoie
  // que les niveaux : un réglage enregistré suivra alors les nouvelles organisations.
  function perimetre(bloc) {
    const orgs = [...bloc.querySelectorAll("[data-org]")];
    bloc.querySelectorAll("[data-niveau]").forEach((n) => {
      const du = orgs.filter((o) => o.dataset.orgNiveau === n.value);
      const nb = du.filter((o) => o.checked).length;
      n.checked = du.length > 0 && nb === du.length;
      n.indeterminate = nb > 0 && nb < du.length;
    });
    const nb = orgs.filter((o) => o.checked).length;
    bloc.querySelector("[data-compte]").textContent = nb === orgs.length ? lib("saisie.js.perimetre_toutes", { nombre: nb }) : lib("saisie.js.perimetre_partie", { nombre: nb, total: orgs.length });
  }
  document.querySelectorAll("[data-perimetre]").forEach(perimetre);
  document.addEventListener("change", (e) => {
    const bloc = e.target.closest("[data-perimetre]");
    if (!bloc) return;
    const orgs = [...bloc.querySelectorAll("[data-org]")];
    if (e.target.dataset.niveau) orgs.filter((o) => o.dataset.orgNiveau === e.target.value).forEach((o) => { o.checked = e.target.checked; });
    if (e.target.dataset.org) orgs.filter((o) => o.dataset.ancetres.includes(` ${e.target.value} `)).forEach((o) => { o.checked = e.target.checked; });
    perimetre(bloc);
  });
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-tout]");
    if (!b) return;
    const bloc = b.closest("[data-perimetre]");
    bloc.querySelectorAll("[data-org]").forEach((o) => { o.checked = b.dataset.tout === "1"; });
    perimetre(bloc);
    bloc.dispatchEvent(new Event("change", { bubbles: true }));  // résumé et « modifications non enregistrées » suivent
  });
  document.addEventListener("submit", (e) => {
    const bloc = e.target.querySelector("[data-perimetre]");
    if (!bloc) return;
    const orgs = [...bloc.querySelectorAll("[data-org]")];
    const niveaux = [...bloc.querySelectorAll("[data-niveau]")];
    niveaux.forEach((n) => { n.checked = orgs.some((o) => o.checked && o.dataset.orgNiveau === n.value); n.indeterminate = false; });
    const complet = orgs.every((o) => o.checked === niveaux.find((n) => n.value === o.dataset.orgNiveau).checked);
    orgs.forEach((o) => { o.disabled = complet; });
    setTimeout(() => { orgs.forEach((o) => { o.disabled = false; }); perimetre(bloc); }, 0);  // téléchargement : la page reste
  });

  // Export : enregistrer un modèle demande un nom ; on reste sur place et on montre le champ
  document.addEventListener("submit", (e) => {
    const action = e.submitter?.value;
    const nom = e.target.querySelector("#nom-modele");
    if (!nom || !["copier", "enregistrer"].includes(action) || nom.value.trim()) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    nom.closest(".champ").classList.add("champ-erreur");
    // message lu avec le champ par les lecteurs d'écran 
    nom.setAttribute("aria-invalid", "true");
    nom.setAttribute("aria-describedby", "nom-modele-erreur");
    nom.scrollIntoView({ behavior: "smooth", block: "center" });
    nom.focus({ preventScroll: true });
  }, true);
  document.addEventListener("input", (e) => {
    if (e.target.id !== "nom-modele") return;
    e.target.closest(".champ").classList.remove("champ-erreur");
    e.target.removeAttribute("aria-invalid");
    e.target.removeAttribute("aria-describedby");
    document.querySelectorAll("[data-nom-brouillon]").forEach((n) => {  // carte et en-tête reprennent le nom tapé
      n.textContent = e.target.value.trim() || lib("saisie.js.nouvel_export");
    });
  });

  // Choix des KPI (export, fichier à remplir) : « Tous », « Une liste sauvegardée » ou « Choisir les KPI » (recherche, cases
  // par thème, limitées au référentiel choisi) ; « Sauvegarder cette liste », la modifier ou la supprimer sans quitter la page
  document.querySelectorAll("[data-choix-kpi]").forEach((bloc) => {
    const form = bloc.closest("form");
    const cases = () => [...bloc.querySelectorAll('input[name="kpis"]')];
    const recherche = bloc.querySelector("[data-recherche-kpi]"), compte = bloc.querySelector("[data-compte-kpi]");
    const liste = bloc.querySelector("[data-liste-kpi]"), nomListe = bloc.querySelector("[data-nom-liste]");
    const signaler = () => bloc.dispatchEvent(new Event("change", { bubbles: true }));  // résumé, modifications non enregistrées
    function refCourant() {
      const r = form && form.querySelector('[data-ref-export] input[name="referentiel"]:checked');
      if (r) return r.value;
      const sel = form && form.querySelector("[data-ref-fichier]");
      return sel && sel.value !== "tous" ? sel.value : "";
    }
    function compter() {
      bloc.querySelectorAll("[data-groupe-kpi]").forEach((g) => {
        const vus = [...g.querySelectorAll('.kpi-choix:not([hidden]) input[name="kpis"]')];
        const nb = vus.filter((c) => c.checked).length, tout = g.querySelector("[data-tout-groupe]");
        tout.checked = vus.length > 0 && nb === vus.length;
        tout.indeterminate = nb > 0 && nb < vus.length;
      });
      const n = cases().filter((c) => c.checked).length;
      compte.textContent = n ? `${n} ${lib("saisie.js.kpi_coches", { n })}` : lib("saisie.js.aucun_kpi_coche");
    }
    bloc.querySelectorAll(".kpi-choix").forEach((l) => { l.dataset.texte = sansAccents(l.dataset.texte); });
    function filtrer() {
      const q = sansAccents(recherche.value.trim()), ref = refCourant();
      let vus = 0;
      bloc.querySelectorAll("[data-groupe-kpi]").forEach((g) => {
        let n = 0;
        g.querySelectorAll(".kpi-choix").forEach((l) => {
          l.hidden = !((!q || l.dataset.texte.includes(q)) && (!ref || l.dataset.refs.includes(` ${ref} `)));
          if (!l.hidden) n += 1;
        });
        g.hidden = n === 0;
        vus += n;
      });
      bloc.querySelector("[data-aucun-kpi]").hidden = vus > 0;
      compter();
    }
    function majListe() {
      const o = liste.selectedOptions[0];
      bloc.querySelector("[data-modifier-liste]").hidden = !o;
      // l'option reste visible : sans liste, un message dit comment en créer une (cocher des KPI puis « Sauvegarder »)
      liste.hidden = !liste.options.length;
      bloc.querySelector("[data-aucune-liste]").hidden = !!liste.options.length;
      const toutes = bloc.querySelector("[data-toutes-listes]"); if (toutes) toutes.hidden = !liste.options.length;
    }
    async function garder() {
      const codes = cases().filter((c) => c.checked).map((c) => c.value), nom = nomListe.value.trim();
      if (!nom) { toast(lib("saisie.js.nom_liste_requis")); nomListe.focus(); return; }
      if (!codes.length) { toast(lib("saisie.js.cocher_un_kpi")); return; }
      const d = new FormData();
      d.append("action", "garder");
      d.append("nom", nom);
      codes.forEach((c) => d.append("kpis", c));
      if (bloc.querySelector("[data-partage-liste]")?.checked) d.append("partage", "on");
      const rep = await fetch(bloc.dataset.urlListes, { method: "POST", body: d, headers: entetes() });
      const j = await rep.json().catch(() => ({}));
      toast(j.message || lib("saisie.js.liste_non_sauvegardee"));
      if (!rep.ok || !j.ok) return;
      let o = [...liste.options].find((x) => x.value === String(j.id));
      if (!o) { o = new Option(); liste.add(o); }
      Object.assign(o.dataset, { nom: j.nom, kpis: j.kpis.join(" "), modifiable: "1" });
      o.value = String(j.id);
      o.textContent = lib(j.partage ? "saisie.js.liste_option_partagee" : "saisie.js.liste_option", { nom: j.nom, n: j.kpis.length });
      liste.value = o.value;
      bloc.querySelector('input[name="choix_kpi"][value="liste"]').checked = true;  // l'export suivra la liste
      majListe();
      signaler();
    }
    recherche.addEventListener("input", filtrer);
    [recherche, nomListe].forEach((c) => c.addEventListener("keydown", (e) => {
      if (e.key !== "Enter") return;
      e.preventDefault();  // Entrée ne télécharge pas l'export
      if (c === nomListe) garder();
    }));
    if (form) form.addEventListener("change", (e) => { if (e.target.matches('[data-ref-export] input, [data-ref-fichier]')) filtrer(); });
    liste.addEventListener("change", majListe);
    bloc.addEventListener("change", (e) => {
      if (e.target.matches("[data-tout-groupe]")) {
        e.target.closest("[data-groupe-kpi]").querySelectorAll('.kpi-choix:not([hidden]) input[name="kpis"]').forEach((c) => { c.checked = e.target.checked; });
      }
      if (e.target.matches('input[name="kpis"], [data-tout-groupe]')) compter();
    });
    bloc.addEventListener("click", async (e) => {
      const b = e.target.closest("button");
      if (!b) return;
      if (b.dataset.cocherKpi) {
        bloc.querySelectorAll('.kpi-choix:not([hidden]) input[name="kpis"]').forEach((c) => {
          if (!c.closest("[data-groupe-kpi]").hidden) c.checked = b.dataset.cocherKpi === "1";
        });
        compter();
        signaler();
      } else if (b.hasAttribute("data-modifier-liste")) {  // la liste dans les cases, son nom prêt à « Sauvegarder »
        const o = liste.selectedOptions[0];
        if (!o) return;
        const codes = new Set(o.dataset.kpis.split(" "));
        cases().forEach((c) => { c.checked = codes.has(c.value); });
        bloc.querySelector('input[name="choix_kpi"][value="choix"]').checked = true;
        nomListe.value = o.dataset.nom;
        recherche.value = "";
        filtrer();
        signaler();
        nomListe.focus();
      } else if (b.hasAttribute("data-cocher-codes")) {
        // codes collés (ligne, virgule, point-virgule, tabulation ou espace) : coche les KPI trouvés, garde les autres cochés
        const zone = bloc.querySelector("[data-codes-colles]"), sortie = bloc.querySelector("[data-codes-resultat]");
        const codes = [...new Set(zone.value.split(/[\s,;]+/).map((c) => c.trim()).filter(Boolean))];
        if (!codes.length) { sortie.textContent = lib("saisie.js.aucun_code"); zone.focus(); return; }
        const parCode = new Map(cases().map((c) => [c.value.toLowerCase(), c]));
        const inconnus = [];
        let n = 0;
        codes.forEach((code) => {
          const c = parCode.get(code.toLowerCase());
          if (c) { c.checked = true; n += 1; } else inconnus.push(code);
        });
        recherche.value = "";
        filtrer();
        signaler();
        sortie.textContent = [lib("saisie.js.codes_coches", { n }), inconnus.length ? lib("saisie.js.codes_inconnus", { codes: inconnus.join(", ") }) : ""].filter(Boolean).join(" ");
        if (!inconnus.length) zone.value = "";
      } else if (b.hasAttribute("data-copier-codes")) {
        const codes = cases().filter((c) => c.checked).map((c) => c.value);
        if (!codes.length) { toast(lib("saisie.js.cocher_un_kpi")); return; }
        try { await navigator.clipboard.writeText(codes.join("\n")); toast(lib("saisie.js.codes_copies", { n: codes.length })); }
        catch (err) { const zone = bloc.querySelector("[data-codes-colles]"); zone.value = codes.join("\n"); zone.select(); }
      } else if (b.hasAttribute("data-garder-liste")) {
        garder();
      }
    });
    filtrer();
    majListe();
  });

  // Export : signale les modifications non enregistrées du modèle ouvert
  document.querySelectorAll("[data-suivi-modifs]").forEach((f) => {
    const marque = f.querySelector(".non-enregistre");
    const signaler = () => { if (marque) marque.hidden = false; };
    f.addEventListener("change", signaler);
    f.addEventListener("input", signaler);
  });

  // Constructeur d'export : la phrase de résumé suit les réponses ; l'aperçu des 10 premières lignes se charge à l'ouverture
  document.querySelectorAll("[data-resume]").forEach((bloc) => {
    const form = bloc.closest("form"), phrase = bloc.querySelector("[data-phrase]");
    const details = bloc.querySelector("[data-apercu]"), zone = bloc.querySelector("[data-contenu-apercu]");
    let minuteur = null, numero = 0;
    function donnees(avecApercu) {
      const d = new FormData(form);
      d.delete("action");
      const bloc = form.querySelector("[data-perimetre]");  // même règle qu'à l'envoi : tout un niveau coché = le niveau
      if (bloc) {
        const orgs = [...bloc.querySelectorAll("[data-org]")];
        const niveaux = [...bloc.querySelectorAll("[data-niveau]")].map((n) => n.value);
        const choisis = new Set(orgs.filter((o) => o.checked).map((o) => o.dataset.orgNiveau));
        const complet = orgs.every((o) => o.checked === choisis.has(o.dataset.orgNiveau));
        d.delete("niveaux");
        niveaux.filter((n) => choisis.has(n)).forEach((n) => d.append("niveaux", n));
        if (complet) d.delete("organisations");
      }
      if (avecApercu) d.append("apercu", "1");
      return d;
    }
    async function rafraichir() {
      const avecApercu = details.open, n = ++numero;
      if (avecApercu) zone.innerHTML = `<p class="discret">${echapper(lib("saisie.js.apercu_preparation"))}</p>`;
      try {
        const r = await fetch(bloc.dataset.resume, { method: "POST", body: donnees(avecApercu), headers: { "X-Requested-With": "fetch" } });
        const j = await r.json();
        if (n !== numero) return;  // une réponse plus récente arrive
        phrase.textContent = j.phrase;
        if (!avecApercu) return;
        if (!j.apercu) { zone.innerHTML = `<p class="discret">${echapper(j.phrase)}</p>`; return; }
        const a = j.apercu;
        const gros = a.gros ? `<p class="encart encart-avertissement compact"><strong class="encart-titre">${echapper(lib("saisie.js.gros_fichier_titre", { nombre: a.total.toLocaleString(document.documentElement.lang || "fr") }))}</strong>
          ${echapper(lib("saisie.js.gros_fichier_aide"))}</p>` : "";
        zone.innerHTML = gros + (a.lignes.length ? `<p class="discret">${echapper(lib("saisie.js.apercu_lignes", { n: a.lignes.length, total: a.total.toLocaleString(document.documentElement.lang || "fr") }))}${a.note ? " " + echapper(a.note) : ""}</p>
          <div class="defile-x" tabindex="0" role="region" aria-label="${echapper(lib("saisie.js.apercu_export"))}"><table class="carte-table table-apercu-export"><thead><tr>${a.entetes.map((e) => `<th scope="col">${echapper(e)}</th>`).join("")}</tr></thead>
          <tbody>${a.lignes.map((l) => `<tr>${l.map((v) => `<td>${echapper(v)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`
          : `<p class="discret">${echapper(lib("saisie.js.apercu_vide"))}</p>`);
      } catch (err) {
        if (avecApercu) zone.innerHTML = `<p class="discret">${echapper(lib("saisie.js.apercu_indisponible"))}</p>`;
      }
    }
    const plusTard = () => { clearTimeout(minuteur); minuteur = setTimeout(rafraichir, 400); };
    form.addEventListener("change", plusTard);
    form.addEventListener("input", (e) => { if (!e.target.matches("#nom-modele, #desc-modele")) plusTard(); });
    details.addEventListener("toggle", () => { if (details.open) rafraichir(); });
  });

  // Reprise : changer d'onglet, de ligne d'en-têtes ou de forme à la souris repropose aussitôt les colonnes ; au clavier,
  // rien ne bouge pendant qu'on parcourt les choix : le bouton « Actualiser » est mis en avant
  document.querySelectorAll("[data-actualiser-auto]").forEach((form) => {
    let clavier = 0;
    form.addEventListener("keydown", () => { clavier = Date.now(); });
    form.addEventListener("change", (e) => {
      if (!e.target.matches("[data-auto]")) return;
      const b = form.querySelector("button[value=actualiser]");
      if (!b) return;
      if (Date.now() - clavier < 800 || e.target.type === "number") { b.classList.remove("secondaire"); return; }
      form.requestSubmit(b);
    });
  });

  // Écart avec N-1 recalculé pendant la frappe
  const nombreFr = lireNombre;
  document.addEventListener("input", (e) => {
    if (!e.target.matches("input[data-n1]")) return;
    const sortie = e.target.form.querySelector("[data-ecart]");
    const n1 = nombreFr(e.target.dataset.n1), v = nombreFr(e.target.value);
    if (!sortie || isNaN(n1) || !n1 || isNaN(v)) { if (sortie) sortie.textContent = ""; return; }
    const ecart = (v - n1) / Math.abs(n1), seuil = parseFloat(e.target.dataset.seuil);
    const fort = !isNaN(seuil) && Math.abs(ecart) > seuil;
    sortie.innerHTML = `<span class="${fort ? "ecart-fort" : ""}"><span class="ecart-fleche">${ecart > 0 ? "▲" : ecart < 0 ? "▼" : "="}</span>${echapper(lib("saisie.js.pourcentage", { n: `${ecart > 0 ? "+" : ecart < 0 && arrondiTexte(ecart * 100, 1) !== (0).toFixed(1) ? "-" : ""}${decimale(arrondiTexte(ecart * 100, 1))}` }))}</span>`;
  });

  // Preuve : nom du fichier choisi affiché dans la zone de dépôt, bouton « Déposer » révélé. Un fichier d'un autre
  // format, ou trop gros, est refusé tout de suite : le motif (celui du serveur) s'affiche sous la zone, le fichier est
  // retiré du champ et la zone garde son texte d'origine.
  document.addEventListener("change", (e) => {
    if (!e.target.matches("[data-depot]")) return;
    const champ = e.target, zone = champ.closest(".depot-preuve"), f = champ.files[0];
    const texte = zone.querySelector(".zone-depot-texte"), refus = zone.querySelector("#erreur-preuve");
    texte.dataset.origine ??= texte.innerHTML;
    const max = Number(champ.dataset.tailleMax) || 0;
    const motif = !f ? "" : !/\.(pdf|jpe?g|png)$/i.test(f.name) ? champ.dataset.refusFormat
      : max && f.size > max ? champ.dataset.refusTaille : "";
    if (refus) {
      refus.textContent = motif || "";
      refus.hidden = !motif;
    }
    if (motif) {
      champ.value = "";
      champ.setAttribute("aria-invalid", "true");
      champ.setAttribute("aria-describedby", "erreur-preuve");
    } else {
      champ.removeAttribute("aria-invalid");
      champ.removeAttribute("aria-describedby");
    }
    const ok = f && !motif;
    texte.innerHTML = ok ? `<strong>${f.name.replace(/</g, "&lt;")}</strong><br><span class="discret">${echapper(lib("saisie.js.taille_mo", { taille: decimale((f.size / 1048576).toFixed(1)) }))}</span>` : texte.dataset.origine;
    const deposer = zone.querySelector("button[value=preuve]");
    if (deposer) deposer.hidden = !ok;
  });

