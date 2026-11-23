{# ouverture de la fonction englobante : variables partagées, libellés, nombres, messages, annulation, confirmation, bandeau, menu des rubriques #}
{% load collecte %}// Interactions des pages : panneau latéral, filtres, SPOC, actions en masse, ordre du référentiel.
// Sans JavaScript, chaque lien et formulaire fonctionne aussi en page complète.
(function () {
  "use strict";
  const csrf = document.querySelector("meta[name=csrf]")?.content || "";
  // Page entière reçue par un script, puis écrite dans le document (téléchargement qui reçoit une page) ou lue par
  // DOMParser (blocs rafraîchis) : la politique de sécurité des contenus de la page actuelle s'y applique (document.open
  // ne la change pas, un document de DOMParser en hérite), donc son jeton. Les scripts et styles de la page reçue portent
  // le jeton de leur réponse (lu dans son en-tête) : on lui substitue celui de la page, et seulement lui (un jeton qui ne
  // serait pas celui de la réponse reste sans effet). collecte/politique_contenus.py.
  const jetonPage = document.currentScript?.nonce || "";
  function avecJetonPage(html, rep) {
    const politique = rep.headers.get("Content-Security-Policy") || rep.headers.get("Content-Security-Policy-Report-Only") || "";
    const jeton = /'nonce-([A-Za-z0-9_-]+)'/.exec(politique)?.[1];
    return jeton && jetonPage ? html.split(`nonce="${jeton}"`).join(`nonce="${jetonPage}"`) : html;
  }
  const panneau = document.getElementById("panneau-contenu");
  const page = document.body.dataset.page || "";
  let modifie = false;
  let ligneOuverte = null;
  let retourFocus = null;  // élément à qui rendre le focus quand le panneau se ferme
  let catalogueKpi = null;  // KPI du constructeur de formule, chargés à la demande (déclaré avant initialiser(document))

  // Libellés de l'interface pour le script (fichiers de langue, clés « commun.* » et « <zone>.js.* », docs/traduction.md) :
  // lib("commun.enregistre"), lib("commun.kpi.nb", { n: 3 }) (pluriel {one, other} : en français 0 et 1 au
  // singulier, ailleurs 1 seul). Clé absente : la clé elle-même, visible, jamais d'erreur.
  const LIBELLES = (() => {
    try { return JSON.parse(document.getElementById("libelles-js")?.textContent || "{}"); } catch (err) { return {}; }
  })();
  const LANGUE = (document.documentElement.lang || "fr").split("-")[0];
  function lib(cle, valeurs = {}) {
    let texte = LIBELLES[cle];
    if (texte === undefined) return cle;
    if (typeof texte === "object") {
      const n = Math.abs(Number(valeurs.n));
      const un = Number.isNaN(n) ? false : (LIBELLES["format.zero_singulier"] === "1" ? n < 2 : n === 1);
      texte = (un ? texte.one : texte.other) || texte.other || "";
    }
    return texte.replace(/\{(\w+)\}/g, (m, nom) => (nom in valeurs ? String(valeurs[nom]) : m));
  }
  window.lib = lib;  // aussi pour les petits scripts propres à une page
  // Gestes simples, sans gestionnaire en attribut (politique de sécurité des contenus, collecte/politique_contenus.py) :
  // un choix qui envoie son formulaire (« Je réponds à », « Affichage », regroupement, portée des relances), un lien
  // d'aperçu sans effet (Identité), le libellé proposé d'une langue (assistant de mise en place). Écouteurs posés sur le
  // document : ils valent aussi pour les morceaux de page insérés ensuite.
  document.addEventListener("change", (e) => {
    const c = e.target;
    if (!(c instanceof Element)) return;
    if (c.matches("[data-envoi-changement]") && c.form) c.form.submit();
    else if (c.matches("select[data-remplir-libelle]") && c.form) c.form.libelle.value = c.selectedOptions[0]?.dataset.libelle || "";
  });
  document.addEventListener("input", (e) => {
    const c = e.target;
    if (c instanceof Element && c.matches("input[data-vider-code]") && c.value && c.form) c.form.code.value = "";
  });
  document.addEventListener("click", (e) => {
    if (e.target instanceof Element && e.target.closest("a[data-lien-inerte]")) e.preventDefault();
  }, true);
  window.confirmer = confirmer;  // question de l'outil, aussi pour la Visualisation (annuler les modifications d'une vue)
  window.erreur = erreur;  // erreur qui reste à l'écran (Error-Stays), aussi pour la Visualisation (« Enregistrer et quitter »)
  // Nombres selon la langue de l'interface, comme le serveur (templatetags.collecte.nombre et
  // saisie.texte_nombre) : français 1 234,5 · anglais 1,234.5 · espagnol 1.234,5 ; virgule ou point acceptés à la saisie.
  // Séparateurs réglés par les fichiers de la langue (clés « format.milliers » et « format.decimal »).
  const MILLIERS = LIBELLES["format.milliers"] ?? ",";
  const DECIMALE = LIBELLES["format.decimal"] ?? ".";
  const decimale = (s) => String(s).replace(".", DECIMALE);  // « 12.5 » écrit avec la décimale de la langue
  // Un groupe de milliers commence par un chiffre de 1 à 9 : « 0,205 » est zéro virgule deux cent cinq dans toutes les
  // langues ; « 0,205,123 », « 0,205.5 » ou « 1.234.5 » ne sont pas des nombres (NaN), comme pour le serveur.
  function lireNombre(texte) {
    let t = String(texte ?? "").replace(/[\s\u00a0\u202f\u2009']/g, "");
    if (t.includes(",") && t.includes(".")) {
      const mille = t.lastIndexOf(".") > t.lastIndexOf(",") ? "," : ".";
      if (!(mille === "," ? /^[-+]?0\d*,/ : /^[-+]?0\d*\./).test(t)) t = t.split(mille).join("");
    } else if (/^[-+]?[1-9]\d{0,2}([.,]\d{3}){2,}%?$/.test(t) || (DECIMALE === "." && /^[-+]?[1-9]\d{0,2},\d{3}%?$/.test(t))) t = t.replace(/[.,]/g, "");
    t = t.replace(/,/g, ".");
    return t.indexOf(".") !== t.lastIndexOf(".") ? NaN : parseFloat(t);
  }
  const echapper = (t) => String(t ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));  // texte inséré dans du HTML
  const sansAccents = (t) => String(t ?? "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();  // recherche
  const hexValide = (v) => /^#[0-9A-F]{6}$/.test(v);  // couleur « #RRGGBB » (en majuscules)

  // Texte d'un nombre arrondi comme Excel et comme le serveur (0,5 s'éloigne de zéro), sans les écarts du binaire
  // (1,005 → « 1.01 », que toFixed donne « 1.00 »)
  function arrondiTexte(v, d) {
    const t = Number(Math.round(Number(Math.abs(v) + "e" + d)) + "e-" + d).toFixed(d);
    return t === "NaN" ? Math.abs(v).toFixed(d) : t;
  }

  function entetes(json) {
    const h = { "X-Requested-With": "fetch", "X-CSRFToken": csrf, "X-Page": page };
    if (json) h["Content-Type"] = "application/json";
    return h;
  }
  // aussi pour static/js/visualisation.js (chargé en « defer », donc après ce script en ligne)
  window.outils = { echapper, sansAccents, entetes, hexValide };

  function toast(texte, duree = 3500) {
    const t = document.getElementById("toast");
    if (!t || !texte) return;
    t.textContent = texte;
    t.style.display = "block";
    clearTimeout(toast.minuteur);
    toast.minuteur = setTimeout(() => { t.style.display = "none"; }, duree);
  }
  // Échec (non enregistré, non chargé…) : le message reste jusqu'à ce que la personne le ferme (DESIGN.md, Error-Stays)
  function erreur(texte) {
    const z = document.getElementById("erreur-persistante");
    if (!z) { toast(texte, 8000); return; }
    if (!texte) return;
    z.querySelector("[data-texte]").textContent = texte;
    z.hidden = false;
  }
  document.addEventListener("click", (e) => {
    if (e.target.closest("[data-fermer-erreur]")) document.getElementById("erreur-persistante").hidden = true;
  });

  // « Supprimé : X. Annuler » après une suppression sans question (corbeille, collecte/corbeille.py ; DESIGN.md, Undo-Not-Ask).
  // Le message (role="status", lu par les lecteurs d'écran) prend le focus sur « Annuler » ; il reste tant qu'il a le
  // focus ou le pointeur, puis 10 secondes ; Échap le ferme. offre : {texte, bouton, url} ; apres(reponse) remet l'objet à
  // l'écran sans recharger la page et renvoie l'élément à qui rendre le focus. Sans « apres », « Annuler » envoie le
  // formulaire (la page se recharge, objet remis en place). Sans « url » : annulation faite par la page seule (visuel
  // d'une vue en cours de modification).
  const zoneAnnulation = document.getElementById("annulation");
  const DUREE_ANNULATION = 10000;
  let minuteurAnnulation = null, apresAnnulation = null, retourAnnulation = null;
  function cacherAnnulation(rendreFocus) {
    if (!zoneAnnulation) return;
    clearTimeout(minuteurAnnulation);
    const avaitFocus = zoneAnnulation.contains(document.activeElement);
    zoneAnnulation.replaceChildren();
    apresAnnulation = null;
    if (rendreFocus || avaitFocus) (retourAnnulation?.isConnected ? retourAnnulation : document.getElementById("contenu"))?.focus({ preventScroll: true });
  }
  function armerAnnulation() {
    clearTimeout(minuteurAnnulation);
    if (!zoneAnnulation?.firstChild || zoneAnnulation.contains(document.activeElement) || zoneAnnulation.matches(":hover")) return;
    minuteurAnnulation = setTimeout(() => cacherAnnulation(false), DUREE_ANNULATION);
  }
  function proposerAnnulation(offre, apres, retour) {
    if (!zoneAnnulation || !offre) return;
    clearTimeout(minuteurAnnulation);
    retourAnnulation = retour || (document.activeElement !== document.body ? document.activeElement : null);
    apresAnnulation = apres || null;
    const bouton = document.createElement("button");
    bouton.className = "lien-annulation";
    bouton.textContent = offre.bouton || lib("commun.defaire");
    const texte = document.createElement("span");
    texte.dataset.texte = "";
    texte.textContent = offre.texte;
    let boite = document.createElement("div");
    if (offre.url) {
      boite = document.createElement("form");
      boite.method = "post";
      boite.action = offre.url;
      boite.dataset.annulation = "";
      [["csrfmiddlewaretoken", csrf], ["suivant", location.pathname + location.search]].forEach(([n, v]) => {
        const i = document.createElement("input");
        Object.assign(i, { type: "hidden", name: n, value: v });
        boite.appendChild(i);
      });
      bouton.type = "submit";
    } else {
      bouton.type = "button";
      bouton.dataset.annulerIci = "";
    }
    boite.append(texte, " ", bouton);
    zoneAnnulation.replaceChildren(boite);  // contenu nouveau de la zone role="status" : annoncé
    bouton.focus({ preventScroll: true });
    armerAnnulation();
  }
  window.proposerAnnulation = proposerAnnulation;  // aussi pour la Visualisation
  async function annulerSuppression(form) {
    const apres = apresAnnulation;
    if (form && !apres) return false;  // envoi ordinaire du formulaire : la page se recharge
    let reponse = {};
    if (form) {
      const rep = await fetch(form.action, { method: "POST", body: new FormData(form), headers: entetes() }).catch(() => null);
      if (!repJson(rep)) { erreur(await motifErreur(rep, lib("commun.erreur.serveur"))); return true; }
      reponse = await rep.json();
    }
    clearTimeout(minuteurAnnulation);
    zoneAnnulation.replaceChildren();
    apresAnnulation = null;
    const cible = apres?.(reponse);
    if (reponse.message) toast(reponse.message);
    (cible?.isConnected ? cible : retourAnnulation?.isConnected ? retourAnnulation : document.getElementById("contenu"))?.focus({ preventScroll: !cible });
    return true;
  }
  if (zoneAnnulation) {
    zoneAnnulation.addEventListener("submit", async (e) => {
      if (!e.target.matches("form[data-annulation]") || !apresAnnulation) return;  // sans « apres » : envoi ordinaire
      e.preventDefault();
      await annulerSuppression(e.target);
    });
    zoneAnnulation.addEventListener("click", (e) => { if (e.target.closest("[data-annuler-ici]")) annulerSuppression(null); });
    zoneAnnulation.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.stopPropagation(); cacherAnnulation(true); } });
    ["focusin", "mouseenter"].forEach((t) => zoneAnnulation.addEventListener(t, () => clearTimeout(minuteurAnnulation)));
    zoneAnnulation.addEventListener("focusout", () => setTimeout(armerAnnulation));
    zoneAnnulation.addEventListener("mouseleave", armerAnnulation);
    // offre écrite par le serveur (suppression suivie d'un rechargement) : réécrite pour être annoncée, focus sur « Annuler »
    const deja = zoneAnnulation.querySelector("form[data-annulation]");
    if (deja) {
      const offre = { texte: deja.querySelector("[data-texte]").textContent, bouton: deja.querySelector("button").textContent, url: deja.action };
      zoneAnnulation.replaceChildren();
      setTimeout(() => proposerAnnulation(offre, null, document.getElementById("contenu")), 150);
    }
  }
  // Confirmation de l'outil (DESIGN.md, Own-Confirmation) : promesse vraie si la personne confirme. Le bouton de
  // confirmation reprend le verbe du bouton d'origine (« Supprimer »), en style danger si le bouton l'était ;
  // « Annuler » a le focus, Échap annule.
  function confirmer(message, source) {
    const dlg = document.getElementById("confirmation");
    if (!message) return Promise.resolve(true);
    if (!dlg?.showModal) return Promise.resolve(window.confirm(message));  // navigateur ancien
    dlg.querySelector("#confirmation-texte").textContent = message;
    const ok = dlg.querySelector("[data-confirmer-ok]");
    // verbe du bouton d'origine : son texte, sinon son titre (bouton à icône, ex. la corbeille « Supprimer »)
    const verbe = [source?.dataset?.confirmerBouton, source?.textContent, source?.title]
      .map((v) => (v || "").trim().replace(/[…\s]+$/, "")).find((v) => v && v.length <= 40);
    ok.textContent = verbe || lib("commun.confirmer");
    const detruit = Boolean(verbe?.startsWith(lib("commun.supprimer")));
    ok.className = source?.classList?.contains("bouton-danger") ? "bouton-danger"
      : source?.classList?.contains("danger") || source?.classList?.contains("lien-danger") || detruit ? "secondaire danger" : "";
    dlg.returnValue = "";
    dlg.showModal();
    dlg.querySelector("[data-annuler]").focus();
    return new Promise((ok_) => {
      dlg.addEventListener("close", () => { ok_(dlg.returnValue === "oui"); source?.focus?.(); }, { once: true });
    });
  }
  // Réponse du serveur à un envoi du script : JSON attendu. Sinon, le motif à montrer : refus (motif du serveur), session
  // expirée (401, ou page de connexion reçue après une redirection), réseau coupé, erreur.
  const repJson = (rep) => Boolean(rep?.ok && !rep.redirected && (rep.headers.get("content-type") || "").includes("json"));
  async function motifErreur(rep, defaut) {
    if (!rep) return lib("commun.erreur.serveur");
    let d = null;
    try { d = await rep.clone().json(); } catch (err) { d = null; }
    if (d?.erreur || d?.message) return d.erreur || d.message;  // format unique des erreurs (reponse_erreur) : les deux clés
    if (rep.status === 401 || rep.redirected) {
      return lib("saisie.js.session_expiree");
    }
    return rep.status === 403 ? lib("saisie.js.action_non_autorisee") : defaut;
  }

  // ---------------------------------------------------------------- bandeau : onglets serrés selon la place
  // Le nom de l'outil (Paramètres › Identité, jusqu'à 60 caractères) et le choix de campagne changent la place laissée
  // aux onglets : on retire, dans l'ordre, ce qui ne tient pas (nom du compte, nom du référentiel dans le bouton
  // « Je réponds à », libellés des onglets à icône non actifs,
  // puis libellé de l'actif), seulement quand les onglets débordent. Sans JavaScript, les règles par largeur
  // d'outil.css (1599, 1439 et 1339 px) s'appliquent seules.
  // En dernier recours, les onglets passent sur leur propre rangée (onglets-a-la-ligne) : ils n'y sont plus serrés.
  // « choix-serre » : le bouton « Je réponds à » ne garde que la période (le nom du référentiel reste lu par les lecteurs
  // d'écran et dans l'infobulle), avant que les onglets ne perdent leurs libellés.
  const SERRAGES = ["bandeau-serre", "choix-serre", "onglets-serres", "onglets-tres-serres", "onglets-a-la-ligne"];
  function serrerOnglets() {
    const haut = document.querySelector("header.haut");
    const nav = haut?.querySelector("nav.onglets");
    if (!nav) return;
    const deborde = () => nav.scrollWidth > nav.clientWidth;
    haut.classList.remove(...SERRAGES);
    if (window.matchMedia("(max-width: 800px)").matches) return;  // téléphone et petite tablette : les onglets défilent (fondu)
    for (const classe of SERRAGES) {
      if (!deborde()) break;
      haut.classList.add(classe);
    }
    if (!haut.classList.contains("onglets-a-la-ligne")) return;
    // sur leur rangée, les onglets reprennent leurs libellés s'ils tiennent
    for (const classe of ["onglets-tres-serres", "onglets-serres"]) {
      haut.classList.remove(classe);
      if (deborde()) { haut.classList.add(classe); break; }
    }
  }
  // Téléphone : la barre d'onglets défile ; l'onglet de la page en cours (Cohérence, Administration…) peut être hors de
  // l'écran. On l'amène au milieu de la partie visible, seulement s'il n'y est pas déjà en entier, au chargement et quand
  // la largeur change (pas quand seule la hauteur change : barre d'adresse du téléphone qui se replie pendant le
  // défilement, qui reprendrait un défilement fait par la personne). Le fondu de droite disparaît au bout de la barre.
  let largeurOnglets = 0;
  function montrerOngletActif() {
    if (window.innerWidth === largeurOnglets) return;
    largeurOnglets = window.innerWidth;
    const nav = document.querySelector("header.haut nav.onglets");
    const actif = nav?.querySelector("a.actif");
    if (!nav || !actif || nav.scrollWidth <= nav.clientWidth) return;
    const n = nav.getBoundingClientRect(), a = actif.getBoundingClientRect();
    if (a.left >= n.left && a.right <= n.right - 24) return;  // 24 px : le fondu de droite
    nav.scrollLeft += (a.left + a.width / 2) - (n.left + n.width / 2);
  }
  function finOnglets() {
    const nav = document.querySelector("header.haut nav.onglets");
    if (!nav) return;
    nav.classList.toggle("au-bout", nav.scrollLeft + nav.clientWidth >= nav.scrollWidth - 1);
    nav.classList.toggle("sans-defilement", nav.scrollWidth <= nav.clientWidth);
  }
  document.querySelector("header.haut nav.onglets")?.addEventListener("scroll", finOnglets, { passive: true });
  // flèche du téléphone : un toucher fait défiler les onglets d'environ deux onglets vers la droite
  document.querySelector("[data-indice-onglets]")?.addEventListener("click", (e) => {
    const nav = e.currentTarget.closest("nav.onglets");
    nav.scrollBy({ left: nav.clientWidth * 0.6, behavior: "smooth" });
  });
  function ajusterBandeau() { serrerOnglets(); montrerOngletActif(); finOnglets(); }
  let minuteurOnglets = null;
  window.addEventListener("resize", () => { cancelAnimationFrame(minuteurOnglets); minuteurOnglets = requestAnimationFrame(ajusterBandeau); });
  ajusterBandeau();
  document.fonts?.ready.then(() => { largeurOnglets = 0; ajusterBandeau(); });  // largeur des textes connue une fois la police chargée

  // ---------------------------------------------------------------- menu compact des rubriques (téléphone)
  // Sous 560 px (outil.css), les rubriques de l'administration et les pages des paramètres se replient derrière un
  // bouton « Rubrique : <actuelle> » (bouton de divulgation : aria-expanded ; Échap referme et rend le focus au bouton ;
  // un clic ailleurs referme). La liste garde ses liens ordinaires ; sans script, les onglets restent affichés.
  document.querySelectorAll("[data-menu-compact]").forEach((menu) => {
    const bouton = menu.querySelector(":scope > .bouton-menu-compact");
    const liste = menu.querySelector(":scope > nav");
    if (!bouton || !liste) return;
    const ouvrir = (oui) => { bouton.setAttribute("aria-expanded", oui ? "true" : "false"); liste.classList.toggle("ouvert", oui); };
    menu.classList.add("menu-compact-actif");
    bouton.hidden = false;
    bouton.addEventListener("click", () => ouvrir(bouton.getAttribute("aria-expanded") !== "true"));
    menu.addEventListener("keydown", (e) => {
      if (e.key !== "Escape" || bouton.getAttribute("aria-expanded") !== "true") return;
      e.preventDefault(); e.stopPropagation(); ouvrir(false); bouton.focus();
    });
    document.addEventListener("click", (e) => { if (!menu.contains(e.target) && liste.classList.contains("ouvert")) ouvrir(false); });
  });

