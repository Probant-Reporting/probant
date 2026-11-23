"""Ligne de la grille de saisie (Saisie, « Pour moi », ligne relue après une saisie) écrite en Python : le même HTML, au
caractère près, que l'ancien gabarit ``collecte/_ligne.html`` (recopié dans ``aides_tests/ligne_avant.html``, référence du
test ``test_ligne_grille_equivalence``). Échelle, lot D : « Pour moi » d'un validateur à 680 organisations rend 9 000
lignes ; le gabarit y passait près de 0,5 ms par ligne à résoudre ses variables (contexte de plusieurs étages, nom du KPI
traduit cinq fois par ligne). Mêmes fonctions d'affichage que le gabarit (libellés, valeur, unité, écart, pastille du
type, bulle d'un SPOC), même échappement ; les libellés qui ne dépendent pas de la ligne sont lus une fois par page.

Une évolution de la ligne se fait ici ; le test compare à l'ancien gabarit tant qu'elle n'est pas voulue (il faut alors
mettre à jour la référence du test)."""
import html

from django.template.defaultfilters import add
from django.urls import reverse
from django.utils.functional import Promise

from parametres import libelles as LB

from .templatetags import collecte as T


def e(x):
    """``conditional_escape`` de Django, sans son enveloppe (appelé 300 000 fois pour une longue liste) : même texte."""
    if isinstance(x, Promise):
        x = str(x)
    return x.__html__() if hasattr(x, "__html__") else html.escape(str(x))


def _lib(cle, **valeurs):
    return e(T.libelle(cle, **valeurs))


class Constantes:
    """Ce qui ne change pas d'une ligne à l'autre d'une même page (même personne, même langue, même campagne)."""

    def __init__(self, admin, user, campagne, comparaison, montrer_org):
        self.admin, self.user, self.campagne, self.comparaison, self.montrer_org = admin, user, campagne, comparaison, montrer_org
        self.pas_contributeur = user.role != "contributeur"
        self.lecture_seule = user.lecture_seule
        self.seuil = _attr(campagne, "seuil_ecart")
        self.gabarits, self.libelles, self.types, self.unites, self.adresses, self.avatars, self.titre_n1 = {}, {}, {}, {}, {}, {}, None

    def lib(self, cle):
        """Libellé sans paramètre, lu une fois par page."""
        v = self.libelles.get(cle)
        if v is None:
            v = self.libelles[cle] = _lib(cle)
        return v

    def lib_textes(self, cle, **valeurs):
        """Libellé dont les paramètres sont des textes : le texte du fichier lu et échappé une fois par page, puis les
        paramètres échappés et remplacés comme ``libelle_echappe`` (même résultat) ; autre paramètre : ``libelle``."""
        if not all(type(v) is str for v in valeurs.values()):
            return _lib(cle, **valeurs)
        texte = self.gabarits.get(cle)
        if texte is None:
            texte = self.gabarits[cle] = (LB.gabarit(cle).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                                          .replace('"', "&quot;"))
        return LB.remplacer(texte, {k: html.escape(v) for k, v in valeurs.items()})

    def type_saisie(self, k):
        """Pastille du type de saisie (``etiquette_type``) : ne dépend que du type."""
        v = self.types.get(k.type_saisie_id)
        if v is None:
            v = self.types[k.type_saisie_id] = e(T.etiquette_type(k))
        return v

    def unite(self, k):
        v = self.unites.get(k.code)
        if v is None:
            v = self.unites[k.code] = e(T.unite(k))
        return v

    def adresse(self, code, org_id):
        """Adresse du panneau de la case (``{% url 'collecte:cellule' %}``) : celle du KPI, l'organisation au bout."""
        v = self.adresses.get(code)
        if v is None:
            v = self.adresses[code] = e(reverse("collecte:cellule", args=[_attr(self.campagne, "pk"), code, 0]))[:-2]
        return f"{v}{org_id}/"

    def avatar(self, u, cache=False):
        cle = (u.pk, cache)
        v = self.avatars.get(cle)
        if v is None:
            v = self.avatars[cle] = e(T.avatar(u, True) if cache else T.avatar(u))
        return v


def _attr(objet, nom):
    """``objet.nom`` comme le gabarit : vide si l'objet manque."""
    return getattr(objet, nom, "") if objet is not None and objet != "" else ""


def ligne(l, c):
    """HTML d'une ligne ``l`` (``saisie.Ligne``) avec les constantes ``c`` de la page."""
    k, o, r, campagne = l.kpi, l.organisation, l.reponse, c.campagne
    nom_kpi, nom_org, code = k.nom, o.nom, k.code
    spocs, alertes = l.spocs, l.alertes
    p = ['<tr class="ligne', " calculee" if l.calculee else "", '" tabindex="0" aria-label="']
    if alertes:
        p.append(_lib("saisie.ligne.aria_alertes", nom=nom_kpi, organisation=nom_org, constats=T.constats_joints(alertes)))
    else:
        p.append(c.lib_textes("saisie.ligne.aria", nom=nom_kpi, organisation=nom_org))
    statut = e(l.statut)
    p += ['" data-cle="', e(l.cle), '" data-statut="', statut, '"']
    if not l.attendue:
        p.append(' data-attendue="0"')
    if alertes:
        p.append(' data-alerte="1"')
    p += ['\n    data-url="', c.adresse(code, o.id), '"\n    data-texte="',
          e(str(code).lower()), " ", e(str(nom_kpi).lower()), " ", e(str(nom_org).lower())]
    for u in spocs:
        p += [" ", e(str(u).lower())]
    p += ['"\n    data-spocs="', ",".join(e(u.id) for u in spocs), '" data-spocs-noms="', "|".join(e(u) for u in spocs), '">\n  ']
    if c.admin:
        p.append('<td class="choix">')
        if not l.calculee and not l.au_dessus:
            p += ['<input type="checkbox" class="choix-ligne" aria-label="', c.lib("saisie.ligne.selectionner"), '">']
        p.append("</td>")
    nom_kpi_html = e(nom_kpi)
    p += ['\n  <td class="ind" title="', nom_kpi_html, '"><div class="nom">', nom_kpi_html]
    if alertes:
        p.append(' <span class="badge-alerte')
        p += [" bloquante" for a in alertes if a.gravite == "bloquante"]
        p += ['">', e(T.icone("alerte")), " "]
        p.append(_lib("saisie.ligne.a_verifier_n", n=len(alertes)) if len(alertes) > 1 else c.lib("saisie.ligne.a_verifier"))
        p.append("</span>")
    p.append("</div>\n    ")
    if alertes:
        p.append('<div class="constat-ligne">')
        p += ["<span>" + e(T.constat(a)) + "</span>" for a in alertes]
        p.append("</div>")
    p += ['\n    <div class="discret"><span class="code-kpi">', e(code), " · " if c.montrer_org else "", "</span>"]
    if c.montrer_org:
        p.append(e(nom_org))
    if k.preuve_obligatoire and not l.calculee:
        p += [' <span class="preuve-requise" title="', c.lib("saisie.ligne.preuve_titre"), '">', c.lib("saisie.ligne.preuve"), "</span>"]
    if l.couverte:
        nom_couverte = l.couverte.nom
        p += [' <span class="facultatif" title="', _lib("saisie.ligne.couvert_titre", kpi=nom_couverte), '">',
              _lib("saisie.ligne.couvert", kpi=nom_couverte), "</span>"]
    if l.facultatif:
        p += [' <span class="facultatif">', c.lib("saisie.ligne.facultatif"), '<span class="visually-hidden"> ',
              c.lib("saisie.ligne.facultatif_aide"), "</span></span>"]
    for ref in l.autres_refs:
        p += [' <span class="ref-chip aussi-dans ', e(T.classe_ref(ref)), '" title="']
        if ref.frequence == _attr(_attr(campagne, "referentiel"), "frequence"):
            p.append(_lib("saisie.ligne.ref_commune", referentiel=ref))
        else:
            p.append(_lib("saisie.ligne.ref_autre", referentiel=ref, frequence=str(LB.choix_phrase(ref, "frequence"))))
        p += ['">', _lib("saisie.ligne.aussi_dans", referentiel=ref), "</span>"]
    p.append("</div></td>\n  ")
    statut_lib = None
    if c.pas_contributeur:
        p.append('<td class="mq-s">')
        if l.au_dessus:
            p += ['<span class="type type-agrege" title="', c.lib("saisie.ligne.type.au_dessus_titre"), '">',
                  c.lib("saisie.ligne.type.saisi_ici") if l.saisie_ici else c.lib("saisie.ligne.type.agrege_saisissable"), "</span>"]
        elif l.calculee and not k.est_calcule:
            p += ['<span class="type type-agrege" title="', c.lib("saisie.ligne.type.agrege_titre"), '">']
            if _attr(r, "origine") == "cumul":
                p.append(c.lib("saisie.ligne.type.cumul"))
            elif k.methode_agregation == "Décompte":
                p.append(c.lib("saisie.ligne.type.decompte"))
            else:
                p.append(c.lib("saisie.ligne.type.agrege"))
            p.append("</span>")
        else:
            p.append(c.type_saisie(k))
        p.append("</td>")
    est_texte = k.est_texte
    texte_rep = _attr(r, "texte")
    p += ['\n  <td class="', "valeur extrait-redige" if est_texte else "nombre valeur", '"']
    if texte_rep and not est_texte:  # liste, oui / non : la réponse traduite (comme la case) ; tableau : son texte
        p += [' title="', e(texte_rep if k.est_tableau else T.valeur(r, k, False)), '"']
    p.append(">")
    if l.au_dessus and not r:
        p += ['<span class="discret">', c.lib("saisie.ligne.facultatif"), "</span>"]
    elif not l.calculee and l.statut == "a_saisir":
        if c.lecture_seule:
            p += ['<span class="discret">', c.lib("choix.reponse.statut.a_saisir"), "</span>"]
        else:
            p += ['<span class="a-saisir">', c.lib("saisie.ligne.saisir"), "</span>"]
    else:
        p.append(e(T.valeur(r, k, False)))
    unite = c.unite(k)
    p += ['<div class="discret unite-sous">', unite, "</div>", e(T.ecart_sous(l.ecart, c.seuil, c.comparaison))]
    if c.admin:
        statut_lib = e(T.statut_libelle(l.statut))
        p += ['<div class="statut-sous"><span class="statut statut-', statut, '">', statut_lib, "</span></div>"]
    p += ['</td>\n  <td class="unite mq-xs" title="', unite, '">', unite, '</td>\n  <td class="nombre mq-m n1']
    if est_texte:
        p.append(" texte")
    n1 = l.n1
    if not n1 or n1.valeur is None and not n1.non_applicable:
        p.append(" vide")
    p.append('" title="')
    if c.titre_n1 is None:
        c.titre_n1 = (_lib("saisie.ligne.n1_exercice", exercice=add(_attr(campagne, "exercice"), "-1")) if c.comparaison == "N-1"
                      else e(c.comparaison))
    p.append(c.titre_n1)
    texte_n1 = _attr(n1, "texte")
    if texte_n1 and not est_texte:
        p += [" : ", e(texte_n1)]
    p += ['">', e(T.valeur(n1, k, False)), '</td>\n  <td class="nombre mq-s">', e(T.ecart_fleche(l.ecart, c.seuil)),
          '</td>\n  <td class="col-statut"><span class="statut statut-', statut, '">',
          statut_lib if statut_lib is not None else e(T.statut_libelle(l.statut)), "</span></td>\n  "]
    if c.pas_contributeur:
        p.append('<td class="spoc">')
        if c.admin and not l.calculee and not l.au_dessus:
            p += ['<button type="button" class="bouton-spoc" title="', c.lib("saisie.ligne.spoc_choisir"), '">']
            if spocs:
                p += [c.avatar(u, True) for u in spocs[:3]]
            else:
                p.append('<span class="avatar vide" aria-hidden="true">+</span>')
            if len(spocs) > 3:
                p += ['<span class="discret" aria-hidden="true">&nbsp;+', e(add(len(spocs), "-3")), "</span>"]
            p += ['<span class="visually-hidden">', c.lib("saisie.ligne.spoc_choisir"), " – "]
            p.append(", ".join(e(u) for u in spocs) if spocs else c.lib("saisie.ligne.aucun_spoc"))
            p.append("</span></button>")
        elif spocs:
            p += [c.avatar(u) for u in spocs[:3]]
        else:
            p.append('<span class="discret">–</span>')
        p.append('</td>\n  <td class="nombre mq-m">')
        if l.nb_preuves:
            p += ['<span title="', _lib("saisie.ligne.preuves", n=l.nb_preuves), '">', e(T.icone("trombone")), " ",
                  e(l.nb_preuves), "</span>"]
        else:
            p.append('<span class="discret">0</span>')
        p.append("</td>")
    p.append("\n</tr>\n")
    return "".join(p)



def constantes(context):
    """Constantes de la page, lues dans le contexte du gabarit comme le faisait ``_ligne.html`` (une variable absente vaut
    ""), gardées le temps d'un rendu (``render_context`` : propre à ce rendu, jamais d'une page à l'autre)."""
    valeurs = tuple(context.get(n, "") for n in ("admin", "user", "campagne", "comparaison", "montrer_org"))
    c = context.render_context.get(Constantes)
    if c is None or len(c[0]) != len(valeurs) or any(a is not b for a, b in zip(c[0], valeurs)):  # mêmes objets
        c = context.render_context[Constantes] = (valeurs, Constantes(*valeurs))
    return c[1]
