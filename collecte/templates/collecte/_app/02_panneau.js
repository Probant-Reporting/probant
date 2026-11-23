{# panneau latéral de saisie : saisie non enregistrée, brouillon automatique, saisie au fil de la liste, rafraîchissement #}
  // ---------------------------------------------------------------- panneau latéral
  // Fenêtre modale : le reste de la page devient inerte, le focus reste dans le panneau et revient, à la fermeture,
  // sur la ligne (ou le lien) qui l'a ouvert.
  const fenetre = document.getElementById("panneau");
  const horsPanneau = () => [document.querySelector("header.haut"), document.querySelector("main"), document.querySelector("footer.pied-version")].filter(Boolean);
  const focusables = () => [...fenetre.querySelectorAll('a[href], button:not([disabled]), input:not([disabled]):not([type=hidden]), select:not([disabled]), textarea:not([disabled]), summary, [tabindex]:not([tabindex="-1"])')]
    .filter((el) => el.offsetParent !== null || el === document.activeElement);

  // Focus donné par le script à un champ de texte prérempli (proposition, reprise, commentaire) : le curseur va à la fin
  // du texte (Chromium le met au début : ce qu'on tape se collerait devant la proposition)
  function focusAuBout(champ) {
    champ.focus();
    if (champ.tagName === "TEXTAREA") champ.setSelectionRange(champ.value.length, champ.value.length);
  }
  async function ouvrirPanneau(url, focus) {
    let rep = null;
    try { rep = await fetch(url, { headers: entetes() }); } catch (err) { rep = null; }
    if (!repJson(rep)) { erreur(await motifErreur(rep, lib("saisie.js.erreur_chargement"))); return; }
    const donnees = await rep.json();
    const dejaOuvert = document.body.classList.contains("panneau-ouvert");
    if (!dejaOuvert && !fenetre.contains(document.activeElement)) retourFocus = document.activeElement;
    panneau.innerHTML = donnees.html;
    initialiser(panneau);
    preparerSuivant(panneau);
    panneau.dataset.url = url;
    const titre = panneau.querySelector("h2, h1");
    if (titre) { titre.id = titre.id || "panneau-titre"; fenetre.setAttribute("aria-labelledby", titre.id); }
    else fenetre.removeAttribute("aria-labelledby");
    document.body.classList.add("panneau-ouvert");
    horsPanneau().forEach((el) => { el.inert = true; });
    panneau.scrollTop = 0;
    // « justifier » (bouton Justifier du bandeau) : le champ d'explication de la première alerte, sinon (écart avec N-1)
    // le bouton « J'explique dans le commentaire », sinon le titre « À vérifier »
    const champ = focus === "justifier"
      ? panneau.querySelector("[data-justification] textarea") || panneau.querySelector("[data-points] [data-vers-commentaire]")
        || panneau.querySelector("[data-points] .pa-titre")
      : focus === "valeur"
      ? panneau.querySelector("[name=valeur]:checked:not([disabled])") || panneau.querySelector("[name=valeur]:not([disabled]):not([hidden])")
        // réponse en tableau : la zone Markdown est cachée par le script, le focus va à la première cellule
        || panneau.querySelector("[data-tableau-saisie] [data-colonne]:not([disabled])")
      : panneau.querySelector("input:not([type=hidden]):not([disabled]), textarea");
    if (champ && focus) focusAuBout(champ);
    // aucun champ pris par le focus (champ caché, désactivé, panneau en lecture) : le focus va dans le panneau lui-même
    if (!fenetre.contains(document.activeElement)) fenetre.focus();
    // téléphone : entrée d'historique pour que le retour referme le panneau (après le retour encore en cours d'une
    // fermeture précédente, dont le popstate ne doit pas refermer ce panneau-ci)
    if (popIgnore) await retourEnCours;
    popIgnore = false;
    pousserEntree();
  }

  function fermerPanneau() {
    if (!document.body.classList.contains("panneau-ouvert")) return;
    clearTimeout(minuteurAuto);  // rien n'attend plus : enregistré, ou abandonné après la question
    minuteurAuto = null;
    departs.clear();
    consommerEntree();
    document.body.classList.remove("panneau-ouvert");
    horsPanneau().forEach((el) => { el.inert = false; });
    const cible = ligneOuverte && ligneOuverte.isConnected ? ligneOuverte : (retourFocus && retourFocus.isConnected ? retourFocus : null);
    if (ligneOuverte) ligneOuverte.classList.remove("ouverte");
    ligneOuverte = null;
    retourFocus = null;
    let attente = Promise.resolve();
    if (modifie) { modifie = false; attente = rafraichir(); }
    cible?.focus();
    return attente;  // bandeau et sélecteur d'organisations relus
  }

  // ---------------------------------------------------------------- saisie non enregistrée
  // Formulaire de saisie d'une case (form[data-garde]) : une valeur, la case N/A ou le commentaire modifiés, ou une
  // saisie refusée par le serveur (data-non-enregistre), ne sont pas encore en base. Fermer le panneau (croix, voile,
  // Échap, retour du téléphone) ou suivre un de ses liens pose d'abord la question « Enregistrer le brouillon et fermer
  // / Fermer sans enregistrer / Continuer la saisie ». Rien n'est jamais validé à la place de la personne. En pleine
  // page, seul l'avertissement du navigateur protège (Échap et la croix n'y font rien).
  let suiteQuestion = null, champAvantQuestion = null, envoiEnCours = false;
  const panneauOuvert = () => document.body.classList.contains("panneau-ouvert");
  const formPanneau = () => (panneauOuvert() ? panneau.querySelector("form[data-garde]") : null);
  // formulaires visibles seulement : panneau ouvert, ou page d'une case (pleine page)
  const formsGardes = () => [formPanneau(), document.querySelector(".page-cellule form[data-garde]")].filter(Boolean);
  const CHAMPS_GARDES = ["valeur", "non_applicable", "commentaire"];
  function champsModifies(form) {
    return [...form.elements].some((c) => {
      if (!CHAMPS_GARDES.includes(c.name)) return false;
      if (c.type === "radio" || c.type === "checkbox") return c.checked !== c.defaultChecked;
      if (c.tagName === "SELECT") {  // liste sans option marquée : la première (« — choisir — ») est celle par défaut
        const defaut = [...c.options].find((o) => o.defaultSelected) || c.options[0];
        return c.value !== (defaut ? defaut.value : "");
      }
      return c.value !== c.defaultValue;
    });
  }
  const estModifie = (form) => Boolean(form && (form.hasAttribute("data-non-enregistre") || champsModifies(form)));
  // explication d'une alerte (« Expliquer pourquoi la valeur est juste ») tapée et pas enregistrée ; le texte proposé
  // (commentaire de la saisie, justification rejetée) n'en est pas une tant qu'il n'est pas modifié
  const explicationModifiee = (f) => {
    const t = f.querySelector("textarea[name=justification]");
    return Boolean(t && t.value.trim() !== t.defaultValue.trim());
  };
  const explicationsModifiees = (racine) => (racine ? [...racine.querySelectorAll("form[data-justification]")].filter(explicationModifiee) : []);
  const racineGardee = () => (panneauOuvert() ? panneau : document.querySelector(".page-cellule"));
  // ---------------------------------------------------------------- brouillon enregistré automatiquement
  // Valeur, case N/A, commentaire ou texte rédigé modifiés (form[data-auto], personne qui peut modifier la case) :
  // enregistrés en brouillon après DELAI_AUTO sans frappe, avant de fermer le panneau (croix, voile, Échap, retour, lien
  // du panneau) et quand la page est cachée ou quittée (autre onglet, téléphone verrouillé : envoi « keepalive »). Même
  // envoi que « Enregistrer le brouillon » (action enregistrer, version, contrôles du serveur) avec auto=1 : jamais validé,
  // sans redessiner le panneau ni déplacer le focus. Rien n'est envoyé pour une valeur validée (elle ne change que sur
  // « Enregistrer la modification », qui la repasse en brouillon), pour un séparateur ambigu (« 1,234 » : la question est
  // posée en enregistrant), pour une saisie déjà refusée telle quelle, ni après un conflit de version (une autre personne a
  // enregistré la case : seul un enregistrement explicite remplace sa valeur). Le repère dit l'état ; « Annuler mes
  // modifications » remet la saisie trouvée à l'ouverture (ou au dernier enregistrement explicite).
  const DELAI_AUTO = 2000;
  const etatsAuto = new WeakMap();  // formulaire → { echec: { cle, motif }, arret (conflit) }
  const departs = new Map();  // adresse de la case → { saisie (à l'ouverture), heure (dernier enregistrement auto), auto, annule }
  let minuteurAuto = null, envoiAuto = null, fermetureEnCours = false;
  const etatAuto = (form) => { let e = etatsAuto.get(form); if (!e) { e = {}; etatsAuto.set(form, e); } return e; };
  const cleCase = (form) => (form.getAttribute("action") || location.pathname).split("?")[0];
  const cleSaisie = (s) => JSON.stringify(s);
  const autoActif = (form) => Boolean(form?.isConnected && form.hasAttribute("data-auto"));
  function ambiguEnAttente(form) {  // même condition que confirmerSeparateur : la question serait posée à l'enregistrement
    const champ = form.querySelector("input[type=text][name=valeur]:not([disabled])");
    return Boolean(champ && separateurAmbigu(champ.value) && champ.value !== champ.defaultValue && champ.dataset.separateurConfirme !== champ.value);
  }
  // ce qui empêche l'enregistrement automatique (texte du repère, qui reste : Error-Stays), "" s'il peut partir
  function empecheAuto(form) {
    if (form.dataset.statutEnregistre === "valide") return lib("saisie.js.auto_valide");
    if (form.hasAttribute("data-conflit")) return lib("saisie.js.auto_non_enregistre", { motif: lib("saisie.js.auto_conflit") });
    if (ambiguEnAttente(form)) return lib("saisie.js.auto_ambigu", { saisie: form.querySelector("input[name=valeur]").value.trim() });
    const e = etatAuto(form);
    if (e.echec && (e.arret || e.echec.cle === cleSaisie(lireSaisie(form)))) return lib("saisie.js.auto_non_enregistre", { motif: e.echec.motif });
    return "";
  }
  // nombre qui a des chances d'être lu par le serveur (avant de quitter la page sans avertissement)
  const nombrePlausible = (form) => {
    const champ = form.querySelector("input[type=text][name=valeur]:not([disabled])");
    return !champ || /^[-+]?[\d\s   '.,]*%?$/.test(champ.value.trim());
  };
  // repère : la région annoncée (data-repere-annonce) ne change que pour un état durable ; l'attente et
  // « Enregistrement… » sont seulement affichés (data-repere-passager, aria-hidden), pour ne pas parler à chaque pause
  let numeroRepere = 0;  // identifiants des repères reliés à un champ refusé (aria-describedby)
  function majRepere(form) {
    const r = form?.querySelector("[data-repere]");
    if (!r) return;
    let durable = "", passe = "";
    if (!autoActif(form)) durable = estModifie(form) ? lib("saisie.js.pas_enregistre") : "";
    else if (envoiAuto?.form === form) passe = lib("saisie.js.auto_envoi");
    else if (estModifie(form)) {
      durable = empecheAuto(form);
      if (!durable && !champsModifies(form)) durable = lib("saisie.js.pas_enregistre");  // saisie refusée, affichée telle quelle
      else if (!durable) passe = lib("saisie.js.pas_enregistre");  // enregistrée dans deux secondes
    } else {
      const d = departs.get(cleCase(form));
      durable = d?.annule ? lib("saisie.js.auto_annule") : d?.heure ? lib("saisie.js.auto_enregistre", { heure: d.heure }) : "";
    }
    const annonce = r.querySelector("[data-repere-annonce]"), passager = r.querySelector("[data-repere-passager]");
    if (!annonce || !passager) { if (r.textContent !== (passe || durable)) r.textContent = passe || durable; return; }
    if (passager.textContent !== passe) passager.textContent = passe;
    if (!passe && annonce.textContent !== durable) annonce.textContent = durable;
    const annuler = form.querySelector("[data-annuler-auto]");
    if (annuler) {
      const d = departs.get(cleCase(form));
      annuler.hidden = !(d?.auto && d.saisie && envoiAuto?.form !== form && cleSaisie(lireSaisie(form)) !== cleSaisie(d.saisie));
    }
  }
  function planifierAuto(form) {
    clearTimeout(minuteurAuto);
    minuteurAuto = null;
    if (!autoActif(form) || !champsModifies(form) || empecheAuto(form)) return;
    minuteurAuto = setTimeout(() => { minuteurAuto = null; brouillonAuto(form); }, DELAI_AUTO);
  }
  // la saisie envoyée devient celle « par défaut » du formulaire : estModifie compare à ce qui est en base, et « Fermer
  // sans enregistrer » (form.reset) revient au dernier brouillon enregistré
  function poserDefauts(form, s) {
    const na = form.querySelector("[name=non_applicable]");
    if (na) na.defaultChecked = s.na;
    form.querySelectorAll("[name=valeur]").forEach((v) => {
      if (v.type === "radio") v.defaultChecked = s.valeur !== "" && v.value === s.valeur;
      else if (v.tagName === "SELECT") [...v.options].forEach((o) => { o.defaultSelected = s.valeur !== "" && o.value === s.valeur; });
      else v.defaultValue = s.valeur;
    });
    const com = form.querySelector("[name=commentaire]");
    if (com) com.defaultValue = s.commentaire;
  }
  // Envoi automatique ; vrai quand plus rien n'attend d'être enregistré. Un envoi en cours est attendu d'abord (jamais
  // deux à la fois : la version renvoyée par le premier sert au second).
  async function brouillonAuto(form, { keepalive = false } = {}) {
    clearTimeout(minuteurAuto);
    minuteurAuto = null;
    while (envoiAuto) await envoiAuto.promesse;
    if (!autoActif(form)) return !estModifie(form);
    if (!champsModifies(form) || empecheAuto(form)) { majRepere(form); return !estModifie(form); }
    const saisie = lireSaisie(form), cle = cleSaisie(saisie), avaitErreur = form.hasAttribute("data-non-enregistre");
    const donnees = new FormData(form);
    donnees.set("action", "enregistrer");
    donnees.set("auto", "1");
    const envoi = { form };
    envoiAuto = envoi;
    envoi.promesse = (async () => {
      let rep = null, res = null;
      try { rep = await fetch(form.getAttribute("action") || location.href, { method: "POST", body: donnees, headers: entetes(), keepalive }); } catch (err) { rep = null; }
      if (repJson(rep)) { try { res = await rep.json(); } catch (err) { res = null; } }
      return { res, motif: res ? res.motif : await motifErreur(rep, lib("saisie.js.erreur_enregistrement")) };
    })();
    majRepere(form);
    const { res, motif } = await envoi.promesse;
    envoiAuto = null;
    if (!form.isConnected) return Boolean(res?.ok);
    const e = etatAuto(form);
    if (res?.ok) {
      e.echec = null;
      poserDefauts(form, saisie);
      form.removeAttribute("data-non-enregistre");
      form.querySelectorAll("[aria-invalid]").forEach((c) => c.removeAttribute("aria-invalid"));
      form.querySelector(".choix-reponse")?.removeAttribute("aria-invalid");
      const repere = form.querySelector("[data-repere-annonce]")?.id;  // motif dépassé : plus relié au champ
      if (repere) form.querySelectorAll(`[aria-describedby~="${repere}"]`).forEach((c) => {
        const reste = c.getAttribute("aria-describedby").split(/\s+/).filter((x) => x && x !== repere).join(" ");
        if (reste) c.setAttribute("aria-describedby", reste); else c.removeAttribute("aria-describedby");
      });
      const v = form.querySelector("input[name=version]");
      if (v) { v.value = res.version; v.defaultValue = res.version; }
      form.dataset.statutEnregistre = res.statut;
      const puce = form.closest("[data-conteneur]")?.querySelector(".statut-panneau .statut");
      if (puce) { puce.className = `statut statut-${res.statut}`; puce.textContent = res.statut_libelle; }
      const d = departs.get(cleCase(form));
      if (d) Object.assign(d, { heure: res.heure, auto: true, annule: false });
      remplacerLignes(res.lignes);
      modifie = true;
      if (avaitErreur) await relireCase(form);  // l'encadré « À vérifier » ne montre plus un refus dépassé
    } else {
      e.echec = { cle, motif: motif || lib("saisie.js.erreur_enregistrement") };
      if (res?.conflit) e.arret = true;
      if (res?.valeur_refusee) {
        const champ = form.querySelector(".choix-reponse") || form.querySelector("[name=valeur]");
        champ?.setAttribute("aria-invalid", "true");
        // le motif affiché (repère sous le champ) est relié au champ refusé (accessibilité)
        const annonce = form.querySelector("[data-repere-annonce]");
        if (champ && annonce) {
          if (!annonce.id) annonce.id = `repere-annonce-${++numeroRepere}`;
          const ids = (champ.getAttribute("aria-describedby") || "").split(/\s+/).filter(Boolean);
          if (!ids.includes(annonce.id)) champ.setAttribute("aria-describedby", ids.concat(annonce.id).join(" "));
        }
      }
    }
    const neuf = form.isConnected ? form : formsGardes()[0];
    majRepere(neuf);
    if (res?.ok && neuf && champsModifies(neuf)) planifierAuto(neuf);  // tapé pendant l'envoi
    return Boolean(res?.ok) && !(neuf && estModifie(neuf));
  }
  // case relue sans rien changer à la saisie en cours (après un refus que l'enregistrement automatique a dépassé)
  async function relireCase(form) {
    const conteneur = form.closest("[data-conteneur]");
    if (!conteneur || questionVisible() || explicationsModifiees(conteneur).length) return;
    let rep = null;
    try { rep = await fetch(conteneur === panneau ? panneau.dataset.url : location.href, { headers: entetes() }); } catch (err) { rep = null; }
    if (!repJson(rep) || !form.isConnected) return;
    const html = (await rep.json()).html;
    if (!html || !form.isConnected) return;
    const tape = champsModifies(form) ? lireSaisie(form) : null;
    const actif = form.contains(document.activeElement) ? document.activeElement : null;
    const repere = actif && { id: actif.id, nom: actif.name, debut: actif.selectionStart, fin: actif.selectionEnd };
    conteneur.innerHTML = html;
    initialiser(conteneur);
    preparerSuivant(conteneur);
    const neuf = conteneur.querySelector("form[data-garde]");
    if (tape) remettreSaisie(neuf, tape);
    const champ = repere && (repere.id ? neuf?.querySelector(`#${CSS.escape(repere.id)}`) : neuf?.querySelector(`[name="${CSS.escape(repere.nom)}"]`));
    if (champ) {
      champ.focus();
      if (typeof repere.debut === "number" && champ.setSelectionRange) try { champ.setSelectionRange(repere.debut, repere.fin); } catch (err) { /* sans sélection */ }
    }
  }
  function initAuto(racine) {
    racine.querySelectorAll?.("form[data-auto]").forEach((form) => {
      const k = cleCase(form);
      if (!departs.has(k)) departs.set(k, { saisie: form.hasAttribute("data-non-enregistre") ? null : lireSaisie(form), heure: null, auto: false });
      majRepere(form);
    });
  }
  // « Annuler mes modifications » : la saisie de l'ouverture est remise puis enregistrée (nouvelles lignes au journal,
  // qui ne fait que grandir) ; le bouton disparaît, le focus va à la valeur
  document.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-annuler-auto]");
    const form = b?.closest("form[data-garde]");
    const d = form && departs.get(cleCase(form));
    if (!d?.saisie) return;
    remettreSaisie(form, d.saisie);
    etatAuto(form).echec = null;
    if (await brouillonAuto(form)) {
      Object.assign(d, { auto: false, heure: null, annule: true });
      majRepere(form);
    }
    if (form.isConnected) (form.querySelector("[name=valeur]:checked:not([disabled])") || form.querySelector("[name=valeur]:not([disabled]), textarea:not([disabled])"))?.focus();
  });
  ["input", "change"].forEach((type) => document.addEventListener(type, (e) => {
    const f = e.target.closest?.("form[data-garde]");
    if (!f || !CHAMPS_GARDES.includes(e.target.name)) { if (f) queueMicrotask(() => majRepere(f)); return; }
    queueMicrotask(() => {  // après la case N/A, qui vide et désactive la valeur
      const d = departs.get(cleCase(f));
      if (d) d.annule = false;
      majRepere(f);
      planifierAuto(f);
    });
  }));
  // page cachée (autre onglet, application quittée, téléphone verrouillé) ou quittée : envoi qui survit à la page
  function enregistrerAvantDepart() {
    formsGardes().forEach((f) => { if (autoActif(f) && !envoiAuto && champsModifies(f) && !empecheAuto(f)) brouillonAuto(f, { keepalive: true }); });
  }
  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "hidden") enregistrerAvantDepart(); });
  window.addEventListener("pagehide", enregistrerAvantDepart);
  // saisie lue puis remise (après un dépôt ou un retrait de preuve, ou « Rouvrir la saisie ») : valeur, N/A et
  // commentaire seulement, jamais la version (date de mise à jour, changée par la preuve) ni le jeton CSRF
  function lireSaisie(form) {
    const valeurs = [...form.querySelectorAll("[name=valeur]")];
    const radio = valeurs.find((v) => v.type === "radio");
    return {
      valeur: radio ? (valeurs.find((v) => v.checked)?.value ?? "") : (valeurs[0]?.value ?? ""),
      na: Boolean(form.querySelector("[name=non_applicable]")?.checked),
      commentaire: form.querySelector("[name=commentaire]")?.value ?? "",
    };
  }
  function synchroniserNa(form) {  // la valeur est désactivée quand N/A est coché (comme au clic sur la case)
    const na = form.querySelector("[name=non_applicable]");
    if (!na || na.disabled) return;
    form.querySelectorAll("[name=valeur]").forEach((v) => { v.disabled = na.checked; });
    majEditeurMd(form);
  }
  function remettreSaisie(form, s) {
    if (!form) return;
    const na = form.querySelector("[name=non_applicable]");
    if (na && !na.disabled) na.checked = s.na;
    form.querySelectorAll("[name=valeur]").forEach((v) => {
      if (v.type === "radio") v.checked = v.value === s.valeur && s.valeur !== "";
      else v.value = s.valeur;
    });
    synchroniserNa(form);
    const com = form.querySelector("[name=commentaire]");
    if (com && !com.disabled) com.value = s.commentaire;
    form.querySelector("input[data-n1]")?.dispatchEvent(new Event("input", { bubbles: true }));  // écart N-1 recalculé
    majRepere(form);
    planifierAuto(form);
  }
  function remettreAZero(form) {  // « Fermer sans enregistrer » : le formulaire revient à ce qui est affiché du serveur
    explicationsModifiees(panneau).forEach((f) => f.reset());
    if (!form) return;
    form.reset();
    form.removeAttribute("data-non-enregistre");
    synchroniserNa(form);
    form.querySelector("input[data-n1]")?.dispatchEvent(new Event("input", { bubbles: true }));
    majRepere(form);
  }
  const questionVisible = () => panneau.querySelector("[data-question]:not([hidden])");
  // suite : ce qui se fait une fois la question réglée (fermer le panneau, ouvrir un lien) ; tout de suite sinon.
  // depuisLien : la suite ouvre un lien du panneau, les deux premiers boutons le disent (data-texte-lien). Le focus va
  // sur le premier bouton (« Fermer sans enregistrer » en cas de conflit de version, pour ne rien remplacer sur Entrée)
  // Deux questions : la saisie (valeur, N/A, commentaire), qui dit aussi si une explication tapée serait perdue ; ou,
  // quand seule une explication d'alerte est tapée, « Enregistrer l'explication et fermer / Fermer sans l'enregistrer /
  // Continuer » (data-question-explication)
  // phrase de la question montrée et lue avec elle (aria-describedby) seulement quand elle s'applique
  function detailQuestion(q, el, montrer) {
    if (!q || !el) return;
    el.hidden = !montrer;
    const ids = (q.getAttribute("aria-describedby") || "").split(" ").filter((i) => i && i !== el.id);
    if (montrer) ids.push(el.id);
    if (ids.length) q.setAttribute("aria-describedby", ids.join(" ")); else q.removeAttribute("aria-describedby");
  }
  // Brouillon enregistré automatiquement : la saisie est d'abord enregistrée (même si l'attente de deux secondes n'est pas
  // finie) ; la question n'est posée que pour ce qui n'a pas pu l'être (valeur validée, refus, séparateur ambigu, conflit)
  async function demanderAvant(suite, depuisLien = false) {
    if (envoiEnCours || fermetureEnCours) return;  // Échap ou clic pendant un enregistrement : on attend sa réponse
    if (!panneauOuvert()) { suite(); return; }
    let form = formPanneau();
    if (autoActif(form) && !questionVisible() && (envoiAuto || minuteurAuto || champsModifies(form))) {
      fermetureEnCours = true;
      try { await brouillonAuto(form); } finally { fermetureEnCours = false; }
      if (!panneauOuvert()) return;
      form = formPanneau();
    }
    const explications = explicationsModifiees(panneau).length > 0;
    let q = null;
    if (form && estModifie(form)) {
      q = panneau.querySelector("[data-question]:not([data-question-explication])");
      detailQuestion(q, q?.querySelector("[data-explication-perdue]"), explications);
      // un brouillon a été enregistré automatiquement : « Fermer sans enregistrer » le garde, la question le dit
      const garde = q?.querySelector("[data-brouillon-garde]"), d = departs.get(cleCase(form));
      if (garde && d?.heure) garde.textContent = lib("saisie.js.auto_garde", { heure: d.heure });
      detailQuestion(q, garde, Boolean(d?.heure));
    } else if (explications) q = panneau.querySelector("[data-question-explication]");
    if (!q) { suite(); return; }
    const autre = questionVisible();
    if (autre && autre !== q) autre.hidden = true;
    suiteQuestion = suite;
    q.querySelectorAll("[data-texte-lien]").forEach((b) => {
      b.dataset.texteFermer ??= b.textContent;
      b.textContent = depuisLien ? b.dataset.texteLien : b.dataset.texteFermer;
    });
    if (q.hidden) {
      champAvantQuestion = panneau.contains(document.activeElement) && document.activeElement.matches("input, select, textarea")
        ? document.activeElement : null;
      q.hidden = false;
    }
    q.querySelector("button")?.focus();
  }
  function cacherQuestion() {
    const q = questionVisible();
    if (q) q.hidden = true;
    suiteQuestion = null;
  }
  function reprendreSaisie() {  // « Continuer la saisie », Échap ou clic dans le formulaire : retour au champ
    cacherQuestion();
    const form = formPanneau();
    const champ = champAvantQuestion && champAvantQuestion.isConnected && !champAvantQuestion.disabled ? champAvantQuestion
      : form && estModifie(form) ? form.querySelector("[name=valeur]:checked:not([disabled]), [name=valeur]:not([disabled]):not([type=radio]), [name=valeur]:not([disabled]), textarea:not([disabled])")
      : explicationsModifiees(panneau)[0]?.querySelector("textarea") || form?.querySelector("[name=valeur]:not([disabled]), textarea:not([disabled])");
    const memeChamp = champ === champAvantQuestion;  // le champ quitté garde son curseur ; un autre l'a à la fin
    champAvantQuestion = null;
    if (memeChamp) champ.focus();
    else if (champ) focusAuBout(champ);
  }
  document.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-question-choix]");
    if (!b) return;
    const choix = b.dataset.questionChoix, suite = suiteQuestion, form = formPanneau(), message = b.dataset.toast;
    if (choix === "continuer") { reprendreSaisie(); return; }
    cacherQuestion();
    champAvantQuestion = null;
    if (choix === "abandonner") { remettreAZero(form); suite?.(); return; }
    if (choix === "explication") {  // « Enregistrer l'explication et fermer » : refusée (texte vide…), le panneau reste ouvert
      const f = explicationsModifiees(panneau)[0];
      if (f && await envoyerFormulaire(f, f.querySelector("button[name=action][value=justifier]"))) {
        if (!explicationsModifiees(panneau).length) { await suite?.(); toast(message); } else demanderAvant(suite);
      }
      return;
    }
    // « Enregistrer le brouillon et fermer » : enregistrement simple (jamais validé), confirmé par un message ; refusé,
    // le panneau reste ouvert et montre l'erreur avec la saisie
    const enregistrer = form?.querySelector("button[name=action][value=enregistrer]");
    if (form && enregistrer && await envoyerFormulaire(form, enregistrer)) { await suite?.(); toast(message); }
  });
  // clic dans le formulaire pendant la question : on reprend la saisie
  panneau?.addEventListener("focusin", (e) => {
    const q = questionVisible();
    if (q && !q.contains(e.target)) { cacherQuestion(); champAvantQuestion = null; }
  });
  // langue changée dans la barre du haut : la saisie en cours est d'abord enregistrée, par le
  // même chemin que l'enregistrement automatique, puis la langue change ; refusée (valeur illisible, valeur validée,
  // conflit), la langue ne change pas : le motif reste sous le champ, le focus y revient. Sans cela, la page rechargée
  // dans l'autre langue pouvait montrer l'ancienne valeur (l'envoi de secours de « beforeunload » arrivait après).
  document.addEventListener("submit", async (e) => {
    const f = e.target;
    if (!f.matches?.("form.liste-langues") || f.dataset.langueEnregistree) return;
    const gardes = formsGardes().filter(estModifie);
    if (!gardes.length) return;
    e.preventDefault();
    const bouton = e.submitter;
    f.closest("details")?.removeAttribute("open");
    let ok = true;
    for (const g of gardes) { if (!(await brouillonAuto(g))) ok = false; }
    const reste = formsGardes().find(estModifie);
    if (!ok || reste) {
      const g = reste || gardes[0];
      majRepere(g);
      (g.querySelector("[aria-invalid=true]:not(.choix-reponse)") || g.querySelector("[name=valeur]:not([disabled])"))?.focus();
      return;
    }
    f.dataset.langueEnregistree = "1";
    if (f.requestSubmit && bouton) f.requestSubmit(bouton); else f.submit();
  });
  // page quittée : ce qui peut s'enregistrer automatiquement part (envoi qui survit à la page) sans avertissement ; le
  // navigateur avertit pour le reste (valeur validée, refus, nombre illisible, séparateur ambigu, explication)
  window.addEventListener("beforeunload", (e) => {
    const restent = formsGardes().filter(estModifie).filter((f) => {
      if (envoiAuto || !(autoActif(f) && champsModifies(f) && !empecheAuto(f) && nombrePlausible(f))) return true;
      brouillonAuto(f, { keepalive: true });
      return false;
    });
    if (restent.length || explicationsModifiees(racineGardee()).length) { e.preventDefault(); e.returnValue = ""; }
  });

  // Retour du téléphone (sous 560 px) : il referme le panneau de saisie d'une case, sans quitter la page. L'ouverture
  // ajoute une entrée d'historique (même adresse) que le retour consomme ; la croix, le voile et Échap la retirent ;
  // un lien ordinaire du panneau la remplace, pour qu'un seul retour ramène à la saisie. Quand le retour pose la
  // question, l'entrée est remise aussitôt : un second retour la repose au lieu de quitter la page (Safari sur iPhone
  // n'affiche pas « Quitter la page ? ») ; fermer ensuite la retire comme d'habitude.
  let entreePoussee = false, popIgnore = false, retourEnCours = Promise.resolve(), finRetour = null;
  const telephone = () => window.matchMedia("(max-width: 560px)").matches;
  function pousserEntree() {
    if (entreePoussee || !telephone() || !panneauOuvert() || !panneau.querySelector("[data-cellule]")) return;
    history.pushState({ panneauSaisie: true }, "");
    entreePoussee = true;
  }
  function consommerEntree() {
    if (!entreePoussee) return;
    entreePoussee = false;
    popIgnore = true;  // le popstate de ce retour-là n'est pas un geste de la personne
    retourEnCours = new Promise((fin) => { finRetour = fin; setTimeout(fin, 800); });
    history.back();
  }
  window.addEventListener("popstate", () => {
    if (popIgnore) { popIgnore = false; finRetour?.(); return; }
    if (!entreePoussee) return;
    entreePoussee = false;
    if (!panneauOuvert()) return;
    demanderAvant(fermerPanneau);
    pousserEntree();  // panneau resté ouvert (question posée, ou enregistrement en cours) : sans effet s'il est fermé
  });
  document.addEventListener("click", (e) => {
    if (!entreePoussee || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    const a = e.target.closest("a[href]");
    if (!a || !panneau.contains(a) || a.hasAttribute("data-panneau") || a.target || a.hasAttribute("download")
        || a.origin !== location.origin || a.getAttribute("href").startsWith("#")) return;
    e.preventDefault();
    location.replace(a.href);  // l'entrée du panneau devient la page suivante : un seul retour ramène à la saisie
  });
  window.addEventListener("pageshow", (e) => {  // page reprise du cache de retour : l'historique et le panneau se remettent d'accord
    if (!e.persisted) return;
    popIgnore = false;
    entreePoussee = Boolean(history.state?.panneauSaisie);
    if (panneauOuvert() && !entreePoussee) pousserEntree();
    else if (!panneauOuvert() && entreePoussee) { history.replaceState(null, ""); entreePoussee = false; }
  });

  // Saisie au fil de la liste : « Commencer » ouvre la première valeur à saisir, « Valider et suivant » enchaîne
  // (les cases qui ne sont pas attendues, data-attendue="0", ne font pas partie de la chaîne)
  const enAttente = (tr) => (tr.dataset.statut === "a_saisir" || tr.dataset.statut === "brouillon") && tr.dataset.attendue !== "0"
    && !tr.hidden && !tr.closest("[hidden]");
  const lignesListe = () => [...document.querySelectorAll("#liste tr.ligne[data-url]:not(.calculee)")];
  function suivanteApres(tr) {
    const toutes = lignesListe(), i = toutes.indexOf(tr);
    return [...toutes.slice(i + 1), ...toutes.slice(0, Math.max(i, 0))].find(enAttente);
  }
  function ouvrirLigne(tr) {
    if (ligneOuverte) ligneOuverte.classList.remove("ouverte");
    ligneOuverte = tr;
    tr.classList.add("ouverte");
    const section = tr.closest("details");
    if (section) section.open = true;
    tr.scrollIntoView({ block: "nearest" });
    ouvrirPanneau(tr.dataset.url, "valeur");
  }
  function preparerSuivant(conteneur) {
    if (conteneur !== panneau || !ligneOuverte || !document.getElementById("liste")) return;
    const b = conteneur.querySelector(".actions button[name=action][value=valider]");
    if (!b || !["a_saisir", "brouillon"].includes(ligneOuverte.dataset.statut)) return;
    b.dataset.suivant = "1";  // après la dernière valeur en attente, le panneau se ferme et l'on annonce le bandeau
    if (suivanteApres(ligneOuverte)) b.textContent = lib("saisie.js.valider_suivant");
  }
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-commencer]");
    if (!b) return;
    const premiere = lignesListe().find(enAttente);
    if (premiere) { e.preventDefault(); ouvrirLigne(premiere); }
  });
  // « Justifier » du bandeau : ouvre la première ligne en alerte de la liste, sur son explication (sans ligne en alerte
  // affichée, le lien mène à la page Cohérence filtrée)
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-justifier]");
    if (!b || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    const tr = [...document.querySelectorAll("#liste tr.ligne[data-url][data-alerte='1']")].find((l) => !l.hidden);
    if (!tr) return;
    e.preventDefault();
    if (ligneOuverte) ligneOuverte.classList.remove("ouverte");
    ligneOuverte = tr;
    tr.classList.add("ouverte");
    const section = tr.closest("details");
    if (section) section.open = true;
    tr.scrollIntoView({ block: "nearest" });
    ouvrirPanneau(tr.dataset.url, "justifier");
  });
  // écart avec N-1 : « J'explique dans le commentaire » amène au champ Commentaire de la saisie
  document.addEventListener("click", (e) => {
    if (!e.target.closest("[data-vers-commentaire]")) return;
    const c = e.target.closest("#panneau-contenu, .page-cellule")?.querySelector("form[data-garde] textarea[name=commentaire]:not([disabled])");
    if (!c) return;
    c.scrollIntoView({ block: "center" });
    focusAuBout(c);
  });

  // Tab et Maj+Tab tournent dans le panneau ouvert
  fenetre?.addEventListener("keydown", (e) => {
    if (e.key !== "Tab" || !document.body.classList.contains("panneau-ouvert")) return;
    const q = questionVisible();  // question posée : Tab reste dans ses trois boutons
    const liste = q ? [...q.querySelectorAll("button")] : focusables();
    if (!liste.length) { e.preventDefault(); fenetre.focus(); return; }
    const premier = liste[0], dernier = liste[liste.length - 1];
    if (e.shiftKey && (document.activeElement === premier || document.activeElement === fenetre)) { e.preventDefault(); dernier.focus(); }
    else if (!e.shiftKey && document.activeElement === dernier) { e.preventDefault(); premier.focus(); }
  });

  // Recharge les blocs marqués data-rafraichir (résumé, liste du référentiel) sans recharger la page
  async function rafraichir() {
    const blocs = document.querySelectorAll("[data-rafraichir][id]");
    if (!blocs.length) return;
    const rep = await fetch(location.href);
    const doc = new DOMParser().parseFromString(avecJetonPage(await rep.text(), rep), "text/html");
    const replies = Array.from(document.querySelectorAll('.replier-org[aria-expanded="false"]')).map((b) => b.closest("tr").dataset.id);
    blocs.forEach((b) => { const n = doc.getElementById(b.id); if (n) { b.replaceWith(n); restaurerReplis(n); } });
    replies.forEach((id) => document.querySelector(`tr[data-id="${id}"] .replier-org`)?.setAttribute("aria-expanded", "false"));
    preparerTris(document);  // tableaux triables remplacés : le tri de l'adresse s'applique de nouveau
    majArbre();
    appliquerFiltres();
  }

  function remplacerLignes(lignes) {
    Object.entries(lignes || {}).forEach(([cle, html]) => {
      const tr = document.querySelector(`[data-cle="${CSS.escape(cle)}"]`);  // ligne (Saisie) ou case (grille)
      if (!tr) return;
      const tmp = document.createElement("template");
      tmp.innerHTML = html.trim();
      const neuve = tmp.content.firstElementChild;
      const coche = tr.querySelector(".choix-case")?.checked;
      if (tr === ligneOuverte) { neuve.classList.add("ouverte"); ligneOuverte = neuve; }
      tr.replaceWith(neuve);
      if (coche) neuve.querySelector(".choix-case").checked = true;
    });
    appliquerFiltres();
    majGrille();
  }

  document.addEventListener("click", (e) => {
    if (e.target.closest("[data-fermer]") || e.target.id === "voile") { demanderAvant(fermerPanneau); return; }
    const lien = e.target.closest("a[data-panneau]");
    if (lien) { e.preventDefault(); demanderAvant(() => ouvrirPanneau(lien.href), true); return; }
    // toucher la cellule autour de la case (ligne ou en-tête « tout sélectionner ») la coche, sans ouvrir le panneau : zone de 24 px au moins
    const caseChoix = e.target.closest("td.choix, th.choix");
    if (caseChoix && !e.target.closest("input")) { caseChoix.querySelector("input")?.click(); return; }
    const tr = e.target.closest("tr.ligne[data-url]");
    if (tr && !e.target.closest("a, button, input, summary, .menu-liste, .spoc, .poignee")) {
      if (e.detail > 1) return;  // second clic d'un double clic sur une ligne : n'ouvre rien de plus
      if (ligneOuverte) ligneOuverte.classList.remove("ouverte");
      ligneOuverte = tr;
      tr.classList.add("ouverte");
      ouvrirPanneau(tr.dataset.url, e.target.closest("td.valeur") ? "valeur" : null);
    }
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      fermerSpoc();
      if (questionVisible()) reprendreSaisie();  // Échap sur la question : retour à la saisie
      else demanderAvant(fermerPanneau);
    }
    // une case s'ouvre aussi au clavier : Tab jusqu'à la ligne, puis Entrée ou Espace
    if ((e.key === "Enter" || e.key === " ") && e.target.matches?.("tr.ligne[data-url]")) {
      e.preventDefault();
      if (ligneOuverte) ligneOuverte.classList.remove("ouverte");
      ligneOuverte = e.target;
      e.target.classList.add("ouverte");
      ouvrirPanneau(e.target.dataset.url, "valeur");
    }
  });

