"""Faux stockage compatible S3 pour les tests de la copie externe (``parametres/copie_s3.py``), sans réseau : un serveur
HTTP local (ou HTTPS avec une autorité de test) qui VÉRIFIE la signature de chaque requête (Signature Version 4,
recalculée avec la clé secrète du compte) et l'empreinte SHA-256 du contenu envoyé, comme un vrai service. Opérations :
dépôt, dépôt en morceaux, lecture, taille (HEAD), suppression, liste (``list-type=2``, par pages).

Pannes à la demande : ``refus`` (opérations refusées en 403 AccessDenied : « PUT », « DELETE »…), ``pannes`` (les N
prochaines requêtes répondent 503), ``couper_apres`` (connexion coupée après N octets reçus d'un dépôt, une fois),
``compartiment`` absent, ``garder`` faux (seulement taille et empreinte : grosses archives)."""
import hashlib
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from parametres import copie_s3 as S

ID, SECRET = "PROBANTTESTKEY", "secret-de-test-du-faux-stockage-0123456789"


class Objet:
    def __init__(self, contenu, sha, taille, meta):
        self.contenu, self.sha, self.taille, self.meta = contenu, sha, taille, meta


class FauxS3:
    def __init__(self, compartiment="sauvegardes", contexte=None, page=1000):
        self.compartiment, self.page, self.garder = compartiment, page, True
        self.objets, self.envois, self.requetes = {}, {}, []
        self.refus, self.pannes, self.couper_apres, self.signatures_refusees = set(), 0, None, 0
        self.verrou = threading.Lock()
        faux = self

        class Gestion(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def repondre(self, statut, corps=b"", entetes=None):
                self.send_response(statut)
                for k, v in (entetes or {}).items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(corps)))
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(corps)

            def erreur(self, statut, code):
                self.repondre(statut, f"<?xml version='1.0'?><Error><Code>{code}</Code><Message>message-interne-du-service"
                                      f"</Message></Error>".encode())

            def traiter(self):
                chemin, _, requete = self.path.partition("?")
                params = urllib.parse.parse_qsl(requete, keep_blank_values=True)
                longueur = int(self.headers.get("Content-Length") or 0)
                if self.command == "PUT" and faux.couper_apres is not None and longueur > faux.couper_apres:
                    self.rfile.read(faux.couper_apres)
                    faux.couper_apres = None
                    self.close_connection = True
                    self.connection.shutdown(2)
                    return
                corps = self.rfile.read(longueur) if longueur else b""
                with faux.verrou:
                    faux.requetes.append((self.command, chemin, dict(params)))
                if faux.pannes:
                    faux.pannes -= 1
                    return self.erreur(503, "SlowDown")
                if not self.signature_valide(chemin, params, corps):
                    faux.signatures_refusees += 1
                    return self.erreur(403, "SignatureDoesNotMatch")
                if hashlib.sha256(corps).hexdigest() != self.headers.get("x-amz-content-sha256"):
                    return self.erreur(400, "XAmzContentSHA256Mismatch")
                hote = (self.headers.get("Host") or "").split(":")[0]
                morceaux = urllib.parse.unquote(chemin).lstrip("/").split("/", 1)
                if hote.startswith(faux.compartiment + "."):  # style « virtual »
                    compartiment, cle = faux.compartiment, urllib.parse.unquote(chemin).lstrip("/")
                else:
                    compartiment, cle = morceaux[0], (morceaux[1] if len(morceaux) > 1 else "")
                if compartiment != faux.compartiment:
                    return self.erreur(404, "NoSuchBucket")
                if self.command in faux.refus:
                    return self.erreur(403, "AccessDenied")
                p = dict(params)
                if not cle:
                    return self.liste(p)
                if self.command == "PUT" and "uploadId" in p:
                    envoi = faux.envois.get(p["uploadId"])
                    if envoi is None:
                        return self.erreur(404, "NoSuchUpload")
                    envoi["parts"][int(p["partNumber"])] = corps if faux.garder else (len(corps),)
                    return self.repondre(200, entetes={"ETag": f'"{hashlib.md5(corps).hexdigest()}"'})  # noqa: S324
                if self.command == "PUT":
                    faux.objets[cle] = Objet(corps if faux.garder else None, hashlib.sha256(corps).hexdigest(), len(corps),
                                             self.headers.get(S.META_SHA))
                    return self.repondre(200, entetes={"ETag": '"x"'})
                if self.command == "POST" and "uploads" in p:
                    ident = f"envoi-{len(faux.envois) + 1}"
                    faux.envois[ident] = {"cle": cle, "parts": {}, "meta": self.headers.get(S.META_SHA)}
                    return self.repondre(200, f"<InitiateMultipartUploadResult><UploadId>{ident}</UploadId>"
                                              "</InitiateMultipartUploadResult>".encode())
                if self.command == "POST" and "uploadId" in p:
                    envoi = faux.envois.pop(p["uploadId"], None)
                    if envoi is None:
                        return self.erreur(404, "NoSuchUpload")
                    h, taille, contenu = hashlib.sha256(), 0, []
                    for n in sorted(envoi["parts"]):
                        part = envoi["parts"][n]
                        if faux.garder:
                            h.update(part)
                            taille += len(part)
                            contenu.append(part)
                        else:
                            taille += part[0]
                    faux.objets[cle] = Objet(b"".join(contenu) if faux.garder else None,
                                             h.hexdigest() if faux.garder else envoi["meta"], taille, envoi["meta"])
                    return self.repondre(200, b"<CompleteMultipartUploadResult/>")
                if self.command == "DELETE" and "uploadId" in p:
                    faux.envois.pop(p["uploadId"], None)
                    return self.repondre(204)
                o = faux.objets.get(cle)
                if self.command == "DELETE":
                    faux.objets.pop(cle, None)
                    return self.repondre(204)
                if o is None:
                    return self.erreur(404, "NoSuchKey")
                entetes = {"Content-Type": "application/zip", **({S.META_SHA: o.meta} if o.meta else {})}
                if self.command == "HEAD":
                    self.send_response(200)
                    for k, v in entetes.items():
                        self.send_header(k, v)
                    self.send_header("Content-Length", str(o.taille))
                    self.end_headers()
                    return None
                return self.repondre(200, o.contenu or b"", entetes)

            def liste(self, p):
                prefixe, debut = p.get("prefix", ""), p.get("continuation-token", "")
                cles = sorted(k for k in faux.objets if k.startswith(prefixe) and k > debut)
                page, reste = cles[:faux.page], cles[faux.page:]
                contenu = "".join(f"<Contents><Key>{k}</Key><Size>{faux.objets[k].taille}</Size></Contents>" for k in page)
                suite = f"<IsTruncated>true</IsTruncated><NextContinuationToken>{page[-1]}</NextContinuationToken>" if reste \
                    else "<IsTruncated>false</IsTruncated>"
                return self.repondre(200, f'<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">{contenu}'
                                          f"{suite}</ListBucketResult>".encode())

            def signature_valide(self, chemin, params, corps):
                auth = self.headers.get("Authorization") or ""
                try:
                    _, reste = auth.split(" ", 1)
                    champs = dict(x.strip().split("=", 1) for x in reste.split(","))
                    ident, jour, region, service, _fin = champs["Credential"].split("/")
                    signes = champs["SignedHeaders"].split(";")
                except (ValueError, KeyError):
                    return False
                if ident != ID or service != "s3" or "host" not in signes or "x-amz-content-sha256" not in signes:
                    return False
                import datetime

                quand = datetime.datetime.strptime(self.headers["x-amz-date"], "%Y%m%dT%H%M%SZ").replace(tzinfo=datetime.timezone.utc)
                entetes = {k: self.headers.get(k, "") for k in signes}
                attendu = S.autorisation(self.command, chemin, params, entetes, self.headers.get("x-amz-content-sha256", ""),
                                         ID, SECRET, region, quand)
                return attendu == auth

            def do_GET(self):
                self.traiter()

            do_PUT = do_POST = do_DELETE = do_HEAD = do_GET

        self.serveur = ThreadingHTTPServer(("127.0.0.1", 0), Gestion)
        self.serveur.daemon_threads = True
        self.schema = "http"
        if contexte is not None:
            self.serveur.socket = contexte.wrap_socket(self.serveur.socket, server_side=True)
            self.serveur.handle_error = lambda *a: None
            self.schema = "https"
        self.port = self.serveur.server_address[1]
        threading.Thread(target=self.serveur.serve_forever, daemon=True).start()

    @property
    def adresse(self):
        return f"{self.schema}://{'localhost' if self.schema == 'https' else '127.0.0.1'}:{self.port}"

    def fermer(self):
        self.serveur.shutdown()
        self.serveur.server_close()
