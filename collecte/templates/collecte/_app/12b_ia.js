{# assistant IA (docs/ai_socket.md) : expliquer une alerte, correspondances d'une reprise, traductions proposées #}
  // ---------------------------------------------------------------- assistant IA
  // Les boutons sont cachés sans script (aucun bouton qui ne fait rien) et n'existent que si la prise, l'usage et la clé
  // sont là (serveur). Toute réponse est une proposition : un fragment rendu et échappé par le serveur (explication), ou
  // des textes posés en textContent (correspondances, traductions) ; rien n'est repris sans un clic sur « Utiliser », et
  // rien n'est enregistré sans le bouton habituel de la page.
  function initIA(racine) {
    racine.querySelectorAll("[data-ia-expliquer][hidden], [data-ia-reprise][hidden], [data-ia-traductions][hidden]")
      .forEach((b) => { b.hidden = false; });
  }

  function occupeIA(b, oui) {
    const s = b.querySelector("span") || b;
    if (oui) {
      b.dataset.iaTexte = s.textContent;
      s.textContent = lib("saisie.js.ia.attente");
      b._avaitFocus = document.activeElement === b;
    } else if (b.dataset.iaTexte) {
      s.textContent = b.dataset.iaTexte;
    }
    b.disabled = oui;
    b.setAttribute("aria-busy", oui ? "true" : "false");
    // bouton désactivé pendant la demande : le focus retombait sur body ; il revient sur le bouton, sauf s'il est déjà
    // allé ailleurs (proposition à lire, champ à corriger) (seconde recette, B10)
    if (!oui && b._avaitFocus && (!document.activeElement || document.activeElement === document.body)) b.focus();
  }

  async function posterIA(url, donnees) {
    const corps = new FormData();
    Object.entries(donnees || {}).forEach(([k, v]) => corps.append(k, v));
    const r = await fetch(url, { method: "POST", headers: entetes(false), body: corps, credentials: "same-origin" });
    // refus et échecs : réponse JSON du format commun ({ok: false, erreur}), lue aussi quand le statut n'est pas 200
    if (r.redirected || !(r.headers.get("content-type") || "").includes("json")) throw new Error(String(r.status));
    return r.json();
  }

  // une proposition sous un champ : étiquette « IA », texte, raison, « Utiliser » (remplit le champ, n'enregistre rien)
  function suggestionIA(champ, texte, valeur, raison) {
    const d = document.createElement("div");
    d.className = "ia-suggestion";
    d.dataset.iaSuggestion = "";
    const e = document.createElement("span");
    e.className = "etiquette e-accent";
    e.textContent = lib("saisie.js.ia.etiquette");
    d.append(e);
    const t = document.createElement("span");
    t.className = "ia-suggestion-texte";
    t.textContent = texte || lib("saisie.js.ia.aucune");
    d.append(t);
    if (raison) {
      const r = document.createElement("span");
      r.className = "discret ia-suggestion-raison";
      r.textContent = raison;
      d.append(r);
    }
    if (valeur) {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "secondaire compact";
      b.textContent = lib("saisie.js.ia.utiliser");
      b.setAttribute("aria-label", lib("saisie.js.ia.utiliser_pour", { texte: texte }));
      b.addEventListener("click", () => {
        champ.value = valeur;
        champ.dispatchEvent(new Event("input", { bubbles: true }));
        champ.dispatchEvent(new Event("change", { bubbles: true }));
        b.disabled = true;
        b.textContent = lib("saisie.js.ia.repris");
      });
      d.append(b);
      d.utiliser = () => { if (!b.disabled) b.click(); };
    }
    return d;
  }

  // ligne d'état sous le bouton : nombre de propositions, « Tout utiliser », ou le motif d'un refus (reste à l'écran)
  function etatIA(zone, d, suggestions) {
    zone.replaceChildren();
    const p = document.createElement("p");
    if (d.erreur) {
      p.className = "erreur-champ";
      p.setAttribute("role", "alert");
      p.textContent = d.erreur;
      zone.append(p);
      return;
    }
    p.setAttribute("role", "status");
    p.className = "ia-etat";
    const avecValeur = suggestions.filter((s) => s.utiliser);
    p.textContent = d.message || lib("saisie.js.ia.propositions", { n: avecValeur.length, fournisseur: d.fournisseur || "" });
    zone.append(p);
    if (avecValeur.length > 1) {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "secondaire compact";
      b.textContent = lib("saisie.js.ia.tout_utiliser", { n: avecValeur.length });
      b.addEventListener("click", () => { avecValeur.forEach((s) => s.utiliser()); b.disabled = true; });
      zone.append(b);
    }
  }

  document.addEventListener("click", async (e) => {
    const expliquer = e.target.closest("[data-ia-expliquer]");
    if (expliquer) {
      e.preventDefault();
      const zone = expliquer.closest("[data-ia-zone]");
      const resultat = zone && zone.querySelector("[data-ia-resultat]");
      if (!resultat || expliquer.disabled) return;
      occupeIA(expliquer, true);
      try {
        const d = await posterIA(expliquer.dataset.iaExpliquer, { cible: expliquer.dataset.iaCible || "" });
        if (!d.html) { erreur(d.erreur || lib("saisie.js.ia.echec")); return; }
        resultat.innerHTML = d.html;  // fragment du serveur, textes échappés (collecte/_ia_explication.html)
        resultat.querySelector("[data-ia-proposition]")?.focus();
      } catch (err) {
        erreur(lib("saisie.js.ia.echec"));
      } finally {
        occupeIA(expliquer, false);
      }
      return;
    }
    const utiliser = e.target.closest("[data-ia-utiliser]");
    if (utiliser) {
      const champ = document.getElementById(utiliser.dataset.iaUtiliser);
      const texte = utiliser.closest("[data-ia-proposition]")?.querySelector("[data-ia-texte]")?.textContent || "";
      if (champ && texte) {
        champ.value = texte.trim();
        champ.dispatchEvent(new Event("input", { bubbles: true }));
        champ.focus();
      }
      return;
    }
    const fermer = e.target.closest("[data-ia-fermer]");
    if (fermer) {
      const zone = fermer.closest("[data-ia-zone]");
      zone?.querySelector("[data-ia-resultat]")?.replaceChildren();
      zone?.querySelector("[data-ia-expliquer]")?.focus();
      return;
    }
    const reprise = e.target.closest("[data-ia-reprise]");
    if (reprise) {
      e.preventDefault();
      const form = reprise.closest("form");
      const zone = document.getElementById(reprise.getAttribute("aria-controls"));
      occupeIA(reprise, true);
      try {
        const d = await posterIA(reprise.dataset.iaReprise, {});
        form.querySelectorAll("[data-ia-suggestion]").forEach((s) => s.remove());
        const suggestions = [];
        (d.propositions || []).forEach((p) => {
          const lib_ = [...form.querySelectorAll('input[type=hidden][name^="lib_kpi_"]')].find((i) => i.value === p.libelle);
          if (!lib_) return;
          const n = lib_.name.slice("lib_kpi_".length);
          const champ = form.querySelector(`input[name="kpi_${n}"]`);
          const cellule = lib_.closest("tr")?.lastElementChild;
          if (!champ || !cellule) return;
          const s = suggestionIA(champ, p.affiche, p.affiche, p.raison);
          cellule.append(s);
          suggestions.push(s);
        });
        etatIA(zone, d, suggestions);
      } catch (err) {
        erreur(lib("saisie.js.ia.echec"));
      } finally {
        occupeIA(reprise, false);
      }
      return;
    }
    const traduire = e.target.closest("[data-ia-traductions]");
    if (traduire) {
      e.preventDefault();
      const form = traduire.closest("form");
      const zone = document.getElementById(traduire.getAttribute("aria-controls"));
      occupeIA(traduire, true);
      try {
        const d = await posterIA(traduire.dataset.iaTraductions, { section: traduire.dataset.section || "" });
        form.querySelectorAll("[data-ia-suggestion]").forEach((s) => s.remove());
        const suggestions = [];
        (d.propositions || []).forEach((p) => {
          const champ = form.querySelector(`[name="${CSS.escape(p.cle)}"]`);
          if (!champ) return;
          const s = suggestionIA(champ, p.texte, p.texte, "");
          champ.insertAdjacentElement("afterend", s);
          suggestions.push(s);
        });
        etatIA(zone, d, suggestions);
      } catch (err) {
        erreur(lib("saisie.js.ia.echec"));
      } finally {
        occupeIA(traduire, false);
      }
    }
  });
