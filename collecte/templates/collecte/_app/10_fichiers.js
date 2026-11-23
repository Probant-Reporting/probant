{# import / export : fenêtre de chargement, téléchargements, import en arrière-plan #}
  // ---------------------------------------------------------------- import / export : fenêtre de chargement
  // Téléchargements : le fichier est demandé en arrière-plan (préparation, puis transfert avec pourcentage),
  // puis enregistré comme d'habitude. Envois de fichiers : la fenêtre reste affichée jusqu'à la page suivante.
  const chargement = (() => {
    let boite = null, minuteur = null, retour = null, inerte = false;
    // annuler (téléchargements) : bouton « Arrêter » et touche Échap ; l'envoi d'un import, lui, ne s'arrête pas
    function ouvrir(titre, etape, annuler) {
      fermer();
      retour = document.activeElement;  // avant de rendre la page inerte (le focus en serait retiré)
      boite = document.createElement("div");
      boite.className = "chargement";
      // le compteur de secondes n'est pas lu à voix haute (il serait annoncé chaque seconde)
      boite.innerHTML = `<div class="chargement-carte"><strong class="chargement-titre" id="chargement-titre"></strong>
        <div class="chargement-barre indeterminee" aria-hidden="true"><span></span></div>
        <div class="chargement-pied"><span class="chargement-etape"></span><span class="chargement-temps" aria-hidden="true">0 s</span></div>
        <p class="chargement-conseil" hidden></p></div>`;
      boite.querySelector(".chargement-titre").textContent = titre;
      if (annuler) {
        // fenêtre modale : le reste de la page devient inerte, le clavier reste sur « Arrêter », Échap arrête
        boite.setAttribute("role", "dialog");
        boite.setAttribute("aria-modal", "true");
        boite.setAttribute("aria-labelledby", "chargement-titre");
        boite.querySelectorAll(".chargement-etape, .chargement-conseil").forEach((el) => el.setAttribute("role", "status"));
        const b = document.createElement("button");
        b.type = "button";
        b.className = "bouton secondaire chargement-arreter";
        b.textContent = lib("saisie.js.arreter");
        b.addEventListener("click", annuler);
        boite.querySelector(".chargement-carte").appendChild(b);
        boite.addEventListener("keydown", (e) => {
          if (e.key === "Escape") { e.preventDefault(); annuler(); }
          else if (e.key === "Tab") { e.preventDefault(); b.focus(); }
        });
        horsPanneau().forEach((el) => { el.inert = true; });
        inerte = true;
      } else boite.setAttribute("role", "status");  // envoi d'un import : la page suivante remplace la fenêtre
      document.body.appendChild(boite);
      boite.querySelector(".chargement-arreter")?.focus();
      etapeChargement(etape);
      const debut = Date.now();
      minuteur = setInterval(() => {
        const s = Math.round((Date.now() - debut) / 1000);
        boite.querySelector(".chargement-temps").textContent = `${s} s`;
        const conseil = boite.querySelector(".chargement-conseil");
        if (annuler && s >= 10 && conseil.hidden) { conseil.textContent = lib("saisie.js.export_long"); conseil.hidden = false; }
      }, 500);
    }
    function etapeChargement(texte, pct) {
      if (!boite) return;
      boite.querySelector(".chargement-etape").textContent = texte;
      const barre = boite.querySelector(".chargement-barre");
      barre.classList.toggle("indeterminee", pct == null);
      barre.querySelector("span").style.width = pct == null ? "" : `${pct}%`;
    }
    function fermer() {
      clearInterval(minuteur);
      const avait = !!boite?.querySelector(".chargement-arreter");
      boite?.remove(); boite = null;
      if (inerte && !document.body.classList.contains("panneau-ouvert")) horsPanneau().forEach((el) => { el.inert = false; });
      inerte = false;
      if (avait && retour?.isConnected) retour.focus();  // le clavier revient sur le bouton d'export
      retour = null;
    }
    return { ouvrir, etape: etapeChargement, fermer };
  })();

  async function telecharger(url, options) {
    const arret = new AbortController();
    chargement.ouvrir(lib("saisie.js.export_en_cours"), lib("saisie.js.preparation_fichier"), () => arret.abort());
    try {
      const rep = await fetch(url, { ...options, signal: arret.signal });
      const type = rep.headers.get("Content-Type") || "";
      if (!rep.ok || type.startsWith("text/html")) {  // erreur ou message (ex. aucun exercice) : on affiche la page
        const html = await rep.text();
        // renvoi (gros export préparé en arrière-plan : Mes exports ; rien à remplir) : l'adresse suit la page affichée
        if (rep.redirected) history.replaceState(null, "", rep.url);
        document.open(); document.write(avecJetonPage(html, rep)); document.close();
        return;
      }
      const total = +rep.headers.get("Content-Length") || 0;
      const lecteur = rep.body.getReader();
      const morceaux = [];
      let recu = 0;
      for (;;) {
        const { done, value } = await lecteur.read();
        if (done) break;
        morceaux.push(value);
        recu += value.length;
        chargement.etape(lib("saisie.js.telechargement", { taille: decimale((recu / 1048576).toFixed(1)) }), total ? Math.round(100 * recu / total) : null);
      }
      chargement.etape(lib("saisie.js.fichier_pret"), 100);
      const nom = /filename="([^"]+)"/.exec(rep.headers.get("Content-Disposition") || "")?.[1] || "export";
      const lien = document.createElement("a");
      lien.href = URL.createObjectURL(new Blob(morceaux, { type }));
      lien.download = nom;
      document.body.appendChild(lien);
      lien.click();
      setTimeout(() => { URL.revokeObjectURL(lien.href); lien.remove(); chargement.fermer(); toast(lib("saisie.js.telecharge", { nom })); }, 400);
    } catch (err) {
      chargement.fermer();
      if (arret.signal.aborted) toast(lib("saisie.js.export_arrete")); else erreur(lib("saisie.js.telechargement_interrompu"));
    }
  }

  document.addEventListener("click", (e) => {
    const lien = e.target.closest("a[data-telechargement]");
    if (!lien || e.ctrlKey || e.metaKey) return;
    e.preventDefault();
    telecharger(lien.href, { headers: { "X-Requested-With": "telechargement" } });
  });
  document.addEventListener("submit", (e) => {
    if (e.defaultPrevented) return;
    const f = e.target;
    if (f.matches("form[data-telechargement]")) {  // fichier à remplir (envoyé en POST : les KPI cochés peuvent être nombreux)
      e.preventDefault();
      telecharger(f.action, f.method === "post" ? { method: "POST", body: new FormData(f) } : {});
    } else if (f.dataset.telechargementAction && e.submitter?.value === f.dataset.telechargementAction) {  // export
      e.preventDefault();
      const donnees = new FormData(f);  // construit maintenant : le périmètre a déjà retiré les cases inutiles
      donnees.append("action", e.submitter.value);
      telecharger(f.getAttribute("action") || window.location.href, { method: "POST", body: donnees });
    } else if (f.matches("form[data-chargement]") && ["verifier", "confirmer"].includes(e.submitter?.value)) {
      const verifier = e.submitter.value === "verifier";
      chargement.ouvrir(lib(verifier ? "saisie.js.verification_fichier" : "saisie.js.import_en_cours"),
        lib(verifier ? "saisie.js.envoi_lecture" : "saisie.js.enregistrement_recalcul"));
    }
  });
  window.addEventListener("pageshow", () => chargement.fermer());

  // ---------------------------------------------------------------- gros exports en arrière-plan (Mes exports)
  // Chaque fichier en préparation relit son état toutes les 3 s ; fini, sa ligne est remplacée sur place (bouton
  // « Télécharger » ou motif) et le lecteur d'écran l'entend une fois.
  const annonceExports = document.querySelector("[data-annonce-exports]");
  document.querySelectorAll("[data-suivi-export]").forEach((ligne) => {
    let echecs = 0;
    const relire = async () => {
      let d = null;
      try {
        const rep = await fetch(ligne.dataset.suiviExport, { headers: { Accept: "application/json" }, cache: "no-store" });
        if (repJson(rep)) d = await rep.json();
      } catch (err) { d = null; }
      if (!d) { echecs += 1; setTimeout(relire, Math.min(30000, 3000 * (echecs + 1))); return; }  // serveur occupé : on espace
      echecs = 0;
      if (!d.fini) { setTimeout(relire, 3000); return; }
      ligne.outerHTML = d.html;
      if (annonceExports) annonceExports.textContent = d.annonce;
    };
    setTimeout(relire, 3000);
  });  // retour arrière : pas de fenêtre figée

  // ---------------------------------------------------------------- import en arrière-plan : barre d'avancement
  // Une requête légère toutes les 3 s (pas de WebSocket) ; la barre suit, le lecteur d'écran n'entend qu'un quart sur
  // quatre et chaque changement d'étape (pas chaque relecture). Fini : la page du résultat s'affiche.
  const suiviImport = document.querySelector("[data-suivi-import]");
  if (suiviImport) {
    const barre = suiviImport.querySelector("[role=progressbar]");
    const texte = suiviImport.querySelector("[data-avancement]");
    const pct = suiviImport.querySelector("[data-pct]");
    const annonce = suiviImport.querySelector("[data-annonce]");
    let quart = Math.floor(Number(barre.getAttribute("aria-valuenow")) / 25), etape = null, echecs = 0;
    const relire = async () => {
      let d = null;
      try {
        const rep = await fetch(suiviImport.dataset.suiviImport, { headers: { Accept: "application/json" }, cache: "no-store" });
        if (repJson(rep)) d = await rep.json();
      } catch (err) { d = null; }
      if (!d) { echecs += 1; setTimeout(relire, Math.min(30000, 3000 * (echecs + 1))); return; }  // serveur occupé : on espace
      echecs = 0;
      if (d.fini) { window.location.assign(d.url); return; }
      barre.classList.toggle("indeterminee", d.statut === "attente");
      barre.setAttribute("aria-valuenow", d.pct);
      barre.setAttribute("aria-valuetext", d.texte);
      barre.querySelector("span").style.width = `${d.pct}%`;
      texte.textContent = d.texte;
      pct.textContent = lib("saisie.js.pourcentage", { n: d.pct });
      const q = Math.floor(d.pct / 25), cle = `${d.statut}/${d.etape}/${d.arret_demande}`;
      if (q !== quart || (etape !== null && cle !== etape)) annonce.textContent = d.texte;
      quart = q; etape = cle;
      if (d.arret_demande) suiviImport.querySelector("[data-arreter]")?.setAttribute("disabled", "");
      setTimeout(relire, 3000);
    };
    setTimeout(relire, 1500);
  }

