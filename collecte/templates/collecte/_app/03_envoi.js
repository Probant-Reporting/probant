{# séparateur ambigu, envoi des formulaires du panneau, case N/A, réponse rédigée (Markdown), années de l’export #}
  // ---------------------------------------------------------------- séparateur ambigu 
  // « 1,234 », « 12.500 » : un seul séparateur, suivi d'exactement 3 chiffres, partie entière de 1 à 3 chiffres non nulle
  // (même règle que saisie.separateur_ambigu). Avant d'enregistrer, le panneau (et la pleine page) demande « 1 234 ou
  // 1,234 ? », les deux lectures écrites comme la langue affiche les nombres. Le choix réécrit la saisie sous une forme que
  // le serveur lit de la même façon (« 1234 », ou la décimale de la langue : texte_nombre, inchangé), puis l'envoi reprend.
  // Échap, ou un retour dans le formulaire, laisse corriger la saisie sans rien envoyer. La valeur affichée à l'ouverture
  // (déjà enregistrée) et une lecture déjà choisie ne sont pas redemandées.
  const AMBIGU = /^([-+]?)([1-9]\d{0,2})([.,])(\d{3})$/;
  const separateurAmbigu = (texte) => AMBIGU.exec(String(texte ?? "").trim());
  let questionSeparateur = null;  // { boite, fin } de la question affichée
  function finirQuestionSeparateur(resultat) {
    const q = questionSeparateur;
    if (!q) return;
    questionSeparateur = null;
    q.boite.remove();
    q.fin(resultat);
  }
  function confirmerSeparateur(form) {
    finirQuestionSeparateur(false);
    const champ = form.querySelector("input[type=text][name=valeur]:not([disabled])");
    const m = champ && separateurAmbigu(champ.value);
    if (!m || champ.value === champ.defaultValue || champ.dataset.separateurConfirme === champ.value) return Promise.resolve(true);
    const [, signe, entier, sep, dec] = m, moins = signe === "-" ? "-" : "";
    const lectures = {
      milliers: { texte: moins + entier + MILLIERS + dec, saisie: moins + entier + dec, aide: lib("saisie.js.separateur_milliers", { sep }) },
      decimal: { texte: moins + entier + DECIMALE + dec, saisie: moins + entier + DECIMALE + dec, aide: lib("saisie.js.separateur_decimal", { sep }) },
    };
    const boite = document.createElement("div");
    boite.className = "question-fermeture question-separateur";
    boite.setAttribute("role", "group");
    boite.setAttribute("aria-labelledby", "question-separateur-titre");
    boite.setAttribute("aria-describedby", "question-separateur-detail");
    boite.innerHTML = `<p class="question-titre" id="question-separateur-titre">${echapper(lib("saisie.js.separateur_titre", { saisie: champ.value.trim(), milliers: lectures.milliers.texte, decimal: lectures.decimal.texte }))}</p>
      <p class="question-detail" id="question-separateur-detail">${echapper(lib("saisie.js.separateur_detail"))}</p>
      <div class="question-actions">${Object.entries(lectures).map(([cle, l]) => `<button type="button" data-lecture="${cle}"><strong>${echapper(l.texte)}</strong><span class="lecture-aide">${echapper(l.aide)}</span></button>`).join("")}</div>`;
    (form.querySelector(".saisie-duo") || champ).insertAdjacentElement("afterend", boite);
    return new Promise((fin) => {
      questionSeparateur = { boite, fin };
      boite.addEventListener("click", (e) => {
        const b = e.target.closest("[data-lecture]");
        if (!b) return;
        champ.value = lectures[b.dataset.lecture].saisie;
        champ.dataset.separateurConfirme = champ.value;
        champ.dispatchEvent(new Event("input", { bubbles: true }));  // écart N-1 et repère « Pas encore enregistré »
        finirQuestionSeparateur(true);
      });
      boite.addEventListener("keydown", (e) => {
        if (e.key !== "Escape") return;
        e.preventDefault();
        e.stopPropagation();  // le panneau reste ouvert
        finirQuestionSeparateur(false);
        champ.focus();
      });
      // retour dans le formulaire (clic ou Tab hors de la question) : on corrige la saisie
      const quitter = (e) => {
        if (questionSeparateur?.boite !== boite) { form.removeEventListener("focusin", quitter); return; }
        if (!boite.contains(e.target)) { form.removeEventListener("focusin", quitter); finirQuestionSeparateur(false); }
      };
      form.addEventListener("focusin", quitter);
      boite.scrollIntoView({ block: "nearest" });
      boite.querySelector("button").focus();
    });
  }

  // Formulaires du panneau envoyés sans quitter la page. Renvoie vrai si le serveur a tout accepté.
  async function envoyerFormulaire(form, submitter) {
    const action = submitter?.value || "";
    // enregistrement automatique en cours : attendu, pour envoyer la version qu'il renvoie (sinon : conflit avec soi-même)
    clearTimeout(minuteurAuto);
    minuteurAuto = null;
    while (envoiAuto) await envoiAuto.promesse;
    if (!form.isConnected) return false;
    if (form.matches("form[data-garde]") && ["enregistrer", "valider"].includes(action) && !(await confirmerSeparateur(form))) return false;
    const conteneur = form.closest("[data-conteneur]");
    const donnees = new FormData(form, submitter);
    // une autre action que l'enregistrement de la saisie (preuve, retrait, « Rouvrir la saisie ») réaffiche le panneau
    // depuis la base : la saisie tapée et pas encore enregistrée y est remise (rien après « revenir au total »)
    const garde = conteneur?.querySelector("form[data-garde]");
    const aRemettre = garde && action !== "revenir_total" && !(form === garde && ["enregistrer", "valider"].includes(action))
      && estModifie(garde) ? lireSaisie(garde) : null;
    // explications tapées dans les autres alertes : remises après l'affichage (celle envoyée revient du serveur)
    const explications = Object.fromEntries(explicationsModifiees(conteneur).filter((f) => f !== form)
      .map((f) => [f.querySelector("[name=alerte]").value, f.querySelector("textarea").value]));
    if (submitter) { submitter.disabled = true; submitter.setAttribute("aria-busy", "true"); }  // état « occupé » (DESIGN.md)
    envoiEnCours = true;
    let rep;
    try {
      rep = await fetch(form.getAttribute("action") || location.href, { method: "POST", body: donnees, headers: entetes() });
    } catch (err) {
      rep = null;
    } finally {
      envoiEnCours = false;
      submitter?.removeAttribute("aria-busy");
    }
    if (!repJson(rep)) { erreur(await motifErreur(rep, lib("saisie.js.erreur_enregistrement"))); if (submitter) submitter.disabled = false; return false; }
    const res = await rep.json();
    const suivant = submitter?.dataset.suivant;
    // la personne a choisi ce qui est en base (enregistré, validé, rouvert, effacé) : « Annuler mes modifications »
    // repart de là
    if (res.ok && garde && ["enregistrer", "valider", "brouillon", "a_saisir", "revenir_total"].includes(action)) departs.delete(cleCase(garde));
    conteneur.innerHTML = res.html;
    initialiser(conteneur);
    if (aRemettre) remettreSaisie(conteneur.querySelector("form[data-garde]"), aRemettre);
    Object.entries(explications).forEach(([pk, texte]) => {
      const t = conteneur.querySelector(`form[data-justification] [name=alerte][value="${CSS.escape(pk)}"]`)?.form.querySelector("textarea");
      if (t) t.value = texte;
    });
    remplacerLignes(res.lignes);
    if (res.ok || (res.lignes && Object.keys(res.lignes).length)) modifie = true;
    if (action === "justifier") {  // le message (succès, ou erreur sous le champ) reçoit le focus
      preparerSuivant(conteneur);
      (conteneur.querySelector("[data-message-justif]") || conteneur.querySelector("[data-justification] textarea[aria-invalid]")
        || conteneur.querySelector("[data-points] .erreur-champ") || conteneur.querySelector("[data-points] .pa-titre"))?.focus();
      if (!conteneur.contains(document.activeElement) && conteneur === panneau && panneauOuvert()) fenetre.focus();  // jamais perdu
      return Boolean(res.ok);
    }
    // une alerte apparaît avec cet envoi (E6) : « Valider et suivant » s'arrête sur cette valeur, l'encadré « À vérifier »
    // reçoit le focus
    if (res.nouvelles_alertes?.length && conteneur === panneau) {
      const titre = conteneur.querySelector("[data-points] .pa-titre");
      if (titre) {
        preparerSuivant(conteneur);
        titre.scrollIntoView({ block: "nearest" });
        titre.focus();
        if (suivant) toast(lib("saisie.js.alerte_apparue"));
        return Boolean(res.ok);
      }
    }
    if (suivant && ligneOuverte?.dataset.statut === "valide") {
      const prochaine = suivanteApres(ligneOuverte);
      if (prochaine) ouvrirLigne(prochaine);
      else {  // fin de la liste : on annonce le bandeau relu (tout le périmètre), jamais « Tout est fait » pour la seule liste
        await fermerPanneau();
        toast(document.querySelector("#resume [data-annonce]")?.dataset.annonce || lib("saisie.js.liste_validee"));
      }
      return Boolean(res.ok);
    }
    preparerSuivant(conteneur);
    const premier = conteneur.querySelector(".encart-erreur, .encart-succes");
    if (premier) premier.scrollIntoView({ block: "nearest" });
    // le bouton qui avait le focus a été remplacé : refusé, retour au champ de la valeur ; sinon, le panneau garde le focus
    // fichier de preuve refusé par le serveur : retour au champ du fichier, le motif est sous la zone de dépôt
    if (action === "preuve" && !res.ok) conteneur.querySelector("[data-depot][aria-invalid]")?.focus();
    // fiche refusée (organisation…) : le premier champ refusé reçoit le focus (son message lui est relié)
    if (!res.ok && !conteneur.contains(document.activeElement)) conteneur.querySelector('form [aria-invalid="true"]:not([disabled])')?.focus();
    if (!conteneur.contains(document.activeElement)) {
      const champ = !res.ok && conteneur.querySelector("form[data-garde] [name=valeur]:checked:not([disabled]), form[data-garde] [name=valeur]:not([disabled]):not([type=radio]), form[data-garde] textarea:not([disabled])");
      if (champ) champ.focus();
      else if (conteneur === panneau && panneauOuvert()) fenetre.focus();
    }
    return Boolean(res.ok);
  }
  document.addEventListener("submit", async (e) => {
    const form = e.target;
    if (!form.matches("form[data-ajax]")) return;
    e.preventDefault();
    // réouverture d'un exercice clos : la question rappelle le mode choisi (garder / recalculer)
    const mode = form.querySelector("[name=reouverture]:checked")?.value;
    const question = (mode === "garder" && e.submitter?.dataset.confirmerGarder)
      || (mode === "recalculer" && e.submitter?.dataset.confirmerRecalculer) || e.submitter?.dataset.confirmer;
    if (question && !(await confirmer(question, e.submitter))) return;
    if (envoiEnCours) return;  // double envoi
    await envoyerFormulaire(form, e.submitter);
  });

  // Case N/A : la valeur est vidée et désactivée
  document.addEventListener("change", (e) => {
    if (!e.target.matches("[data-na]")) return;
    e.target.form.querySelectorAll("[name=valeur]").forEach((valeur) => {  // nombre, boutons oui / non ou liste
      valeur.disabled = e.target.checked;
      if (!e.target.checked) return;
      if (valeur.type === "radio") valeur.checked = false;
      else if (valeur.tagName !== "TEXTAREA") valeur.value = "";  // un texte rédigé reste là (désactivé, pas envoyé) si N/A est décoché
    });
    majEditeurMd(e.target.form);
    majEditeurTableau(e.target.form);
    if (e.target.checked) e.target.form.querySelector("textarea[name=commentaire]")?.focus();
  });

  // ---------------------------------------------------------------- réponse rédigée (Markdown)
  // Barre d'outils (gras, italique, titre, listes, lien) : un bouton insère la syntaxe autour de la sélection ; les flèches
  // passent d'un bouton à l'autre (un seul arrêt de tabulation, motif « toolbar ») ; Ctrl+B et Ctrl+I dans la zone de texte.
  // « Aperçu » montre le rendu du serveur (le même que l'affichage, sûr : tout HTML écrit est échappé) à la place de la zone
  // de texte ; « Modifier » y revient. Sans JavaScript, la barre et l'aperçu restent cachés : la zone de texte suffit.
  function editeurMd(el) { return el?.closest("[data-editeur-md]"); }
  function majEditeurMd(racine) {  // N/A coché : barre et aperçu désactivés comme la zone de texte
    racine?.querySelectorAll("[data-editeur-md]").forEach((ed) => {
      const zone = ed.querySelector("textarea[name=valeur]");
      ed.querySelectorAll("[data-barre-md] button, [data-md-apercu]").forEach((b) => { b.disabled = !zone || zone.disabled; });
      if (zone?.disabled && ed.querySelector("[data-md-apercu]")?.getAttribute("aria-pressed") === "true") basculerApercu(ed, false);
    });
  }
  function compterMd(ed) {
    const zone = ed.querySelector("textarea[name=valeur]"), c = ed.querySelector("[data-md-compteur]");
    if (!zone || !c) return;
    const max = Number(c.dataset.max) || 0, n = zone.value.length;
    const ecrire = (x) => x.toLocaleString(document.documentElement.lang || "fr");
    c.textContent = n > max * 0.8 ? lib("saisie.js.md_compteur", { n: ecrire(n), max: ecrire(max) }) : lib("saisie.js.md_max", { max: ecrire(max) });
  }
  // ---------------------------------------------------------------- réponse en tableau
  // Le tableau de saisie (une ligne par polluant, déchet, filiale…) écrit, à chaque changement, un tableau Markdown dans la
  // zone « valeur » cachée : c'est elle qui part au serveur (brouillon automatique compris) et que le serveur vérifie
  // colonne par colonne. Sans JavaScript, le tableau reste caché et la zone de texte visible.
  function cellulesMd(valeurs) { return "| " + valeurs.map((v) => String(v).replace(/\|/g, "\\|").replace(/\s+/g, " ").trim()).join(" | ") + " |"; }
  function ecrireTableauMd(ed, ouverture = false) {  // ouverture : compter seulement, la zone reste telle que le serveur l'a écrite
    const zone = ed.querySelector("[data-zone-tableau]");
    if (!zone) return;
    const entetes = [...ed.querySelectorAll("[data-tableau-saisie] thead th[data-col]")].map((th) => th.textContent.trim());
    const lignes = [...ed.querySelectorAll("[data-lignes-tableau] tr")]
      .map((tr) => [...tr.querySelectorAll("[data-colonne]")].map((i) => i.value))
      .filter((l) => l.some((v) => v.trim()));
    const md = lignes.length ? [cellulesMd(entetes), "|" + entetes.map(() => " --- ").join("|") + "|"].concat(lignes.map(cellulesMd)).join("\n") : "";
    if (!ouverture && zone.value !== md) {
      zone.value = md;
      zone.dispatchEvent(new Event("input", { bubbles: true }));  // brouillon automatique et garde de fermeture
    }
    const compte = ed.querySelector("[data-compte-lignes]");
    if (compte) compte.textContent = lignes.length ? lib("saisie.js.tableau_lignes", { n: lignes.length.toLocaleString(document.documentElement.lang || "fr") }) : "";
  }
  function ajouterLigne(ed, focus = true) {
    const modele = ed.querySelector("template[data-modele-ligne]"), corps = ed.querySelector("[data-lignes-tableau]");
    if (!modele || !corps) return;
    corps.appendChild(modele.content.cloneNode(true));
    if (focus) corps.lastElementChild?.querySelector("input")?.focus();
  }
  function majEditeurTableau(racine) {  // N/A coché : le tableau est désactivé comme la zone de texte
    racine?.querySelectorAll("[data-editeur-tableau]").forEach((ed) => {
      const zone = ed.querySelector("[data-zone-tableau]");
      if (!zone) return;
      ed.querySelectorAll("[data-tableau-saisie] input, [data-tableau-saisie] button, [data-ajouter-ligne]").forEach((x) => { x.disabled = zone.disabled; });
    });
  }
  function initEditeursTableau(racine) {
    racine.querySelectorAll("[data-editeur-tableau]").forEach((ed) => {
      const table = ed.querySelector("[data-tableau-saisie]"), zone = ed.querySelector("[data-zone-tableau]");
      if (!table || ed.dataset.tableauPret) return;
      ed.dataset.tableauPret = "1";
      table.hidden = false;
      if (zone) {
        zone.hidden = true;
        ed.querySelector("[data-actions-tableau]").hidden = false;
        ed.querySelector("[data-aide-sans-script]").hidden = true;
        ed.querySelector("[data-aide-script]").hidden = false;
        if (!ed.querySelector("[data-lignes-tableau] tr")) ajouterLigne(ed, false);
        ecrireTableauMd(ed, true);
      }
      ed.addEventListener("input", (e) => { if (e.target.matches("[data-colonne]")) ecrireTableauMd(ed); });
      ed.addEventListener("click", (e) => {
        if (e.target.closest("[data-ajouter-ligne]")) {
          ajouterLigne(ed);
        } else if (e.target.closest("[data-supprimer-ligne]")) {
          const tr = e.target.closest("tr"), suivante = tr.nextElementSibling || tr.previousElementSibling;
          tr.remove();
          if (!ed.querySelector("[data-lignes-tableau] tr")) ajouterLigne(ed, false);
          ecrireTableauMd(ed);
          (suivante || ed.querySelector("[data-ajouter-ligne]"))?.querySelector?.("input")?.focus() || ed.querySelector("[data-ajouter-ligne]")?.focus();
        }
      });
    });
    majEditeurTableau(racine);
  }
  function initEditeursMd(racine) {
    racine.querySelectorAll("[data-editeur-md]").forEach((ed) => {
      ed.querySelectorAll("[data-barre-md], [data-md-apercu]").forEach((b) => { b.hidden = false; });
      compterMd(ed);
    });
    majEditeurMd(racine);
  }
  function inserer(zone, texte, debutSel, finSel) {
    zone.focus();
    // execCommand garde l'annulation (Ctrl+Z) du navigateur ; sinon, remplacement direct
    let fait = false;
    try { fait = document.execCommand("insertText", false, texte); } catch (err) { fait = false; }
    if (!fait) {
      zone.setRangeText(texte, zone.selectionStart, zone.selectionEnd, "end");
      zone.dispatchEvent(new Event("input", { bubbles: true }));
    }
    if (debutSel !== undefined) zone.setSelectionRange(debutSel, finSel);
  }
  function formaterMd(zone, action) {
    const debut = zone.selectionStart, fin = zone.selectionEnd, v = zone.value, choisi = v.slice(debut, fin);
    if (action === "gras" || action === "italique") {
      const m = action === "gras" ? "**" : "*", t = choisi || lib(action === "gras" ? "saisie.js.md_texte_gras" : "saisie.js.md_texte_italique");
      inserer(zone, m + t + m, debut + m.length, debut + m.length + t.length);
      return;
    }
    if (action === "lien") {
      const t = choisi || lib("saisie.js.md_texte_lien"), adresse = "https://";
      inserer(zone, `[${t}](${adresse})`, debut + t.length + 3, debut + t.length + 3 + adresse.length);
      return;
    }
    // titre, listes : sur les lignes entières de la sélection
    const d = v.lastIndexOf("\n", debut - 1) + 1, f0 = v.indexOf("\n", fin), f = f0 === -1 ? v.length : f0;
    const lignes = v.slice(d, f).split("\n");
    const prefixe = (i) => (action === "titre" ? "## " : action === "puces" ? "- " : `${i + 1}. `);
    const nettoyer = (l) => l.replace(/^(#{1,6}\s+|[-*+]\s+|\d{1,9}[.)]\s+)/, "");
    const texte = lignes.map((l, i) => prefixe(i) + nettoyer(l)).join("\n");
    zone.setSelectionRange(d, f);
    inserer(zone, texte, d + texte.length, d + texte.length);
  }
  async function basculerApercu(ed, montrer) {
    const bouton = ed.querySelector("[data-md-apercu]"), zone = ed.querySelector("textarea[name=valeur]");
    const rendu = ed.querySelector("[data-md-rendu]"), barre = ed.querySelector("[data-barre-md]");
    if (!bouton || !zone || !rendu) return;
    if (montrer) {
      const corps = new FormData();
      corps.append("texte", zone.value);
      let rep = null;
      try { rep = await fetch(bouton.dataset.url, { method: "POST", body: corps, headers: entetes() }); } catch (err) { rep = null; }
      if (!repJson(rep)) { erreur(await motifErreur(rep, lib("saisie.js.erreur_chargement"))); return; }
      rendu.innerHTML = (await rep.json()).html;  // HTML produit par le serveur (collecte.markdown), jamais le texte tapé tel quel
    }
    rendu.hidden = !montrer;
    zone.hidden = montrer;
    if (barre) barre.hidden = montrer;
    bouton.setAttribute("aria-pressed", String(montrer));
    bouton.textContent = montrer ? bouton.dataset.texteModifier : bouton.dataset.texteApercu;
    (montrer ? rendu : zone).focus();
  }
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-md], [data-md-apercu]");
    const ed = editeurMd(b);
    if (!b || !ed || b.disabled) return;
    e.preventDefault();
    if (b.hasAttribute("data-md-apercu")) { basculerApercu(ed, b.getAttribute("aria-pressed") !== "true"); return; }
    const zone = ed.querySelector("textarea[name=valeur]");
    if (zone && !zone.disabled) formaterMd(zone, b.dataset.md);
  });
  document.addEventListener("keydown", (e) => {
    const barre = e.target.closest?.("[data-barre-md]");
    if (barre && ["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) {  // une seule tabulation pour la barre
      const boutons = [...barre.querySelectorAll("button:not([disabled])")];
      const i = boutons.indexOf(e.target);
      const j = e.key === "Home" ? 0 : e.key === "End" ? boutons.length - 1 : (i + (e.key === "ArrowRight" ? 1 : -1) + boutons.length) % boutons.length;
      e.preventDefault();
      boutons.forEach((x, k) => { x.tabIndex = k === j ? 0 : -1; });
      boutons[j]?.focus();
      return;
    }
    if (e.target.matches?.("[data-editeur-md] textarea[name=valeur]") && (e.ctrlKey || e.metaKey) && !e.altKey && ["b", "i"].includes(e.key.toLowerCase())) {
      e.preventDefault();
      formaterMd(e.target, e.key.toLowerCase() === "b" ? "gras" : "italique");
    }
  });
  document.addEventListener("input", (e) => {
    const ed = e.target.matches?.("textarea[name=valeur]") && editeurMd(e.target);
    if (ed) compterMd(ed);
  });

  // Export : « Tous » coche toutes les années ; décocher une année décoche « Tous »
  document.addEventListener("change", (e) => {
    const bloc = e.target.closest("[data-exercices]");
    if (!bloc) return;
    const tous = bloc.querySelector("input[value=tous]");
    const annees = [...bloc.querySelectorAll("input:not([value=tous])")];
    if (e.target === tous) annees.forEach((a) => { a.checked = tous.checked; });
    else tous.checked = annees.every((a) => a.checked);
  });

