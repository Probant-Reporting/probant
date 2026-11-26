# Single image of the KPI reporting tool: gunicorn server, static files served by WhiteNoise, data in the
# /data volume (SQLite database, uploaded files, backups, secret key). Guide: docs/installation.md
FROM python:3.12-slim

ARG VERSION_COMMIT=""
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DJANGO_DEBUG=0 DATA_DIR=/data DANS_DOCKER=1 TZ=Europe/Brussels VERSION_COMMIT=${VERSION_COMMIT}
# certificate authorities added by the IT for outgoing connections (docs/installation.md, "Company network"): the PEM
# files of this folder (certificates/ca of the installation, mounted by docker-compose.yml); empty: nothing changes
ENV EXTRA_CA_CERTS=/etc/probant/ca

RUN useradd --uid 1000 --create-home --shell /usr/sbin/nologin probant \
 && mkdir -p /data /etc/probant/ca && chown probant:probant /data

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

# The code belongs to root: the user of the tool (probant) can read it but never change it. It writes only in the data
# folder (/data): databases, files, backups, secret key, logs of restores and checks. Static files are collected now,
# at build time (the umask of the tool makes them private: they are made readable for everyone afterwards).
COPY . .
RUN mkdir /tmp/build-data && DJANGO_SECRET_KEY=build DATA_DIR=/tmp/build-data python manage.py collectstatic --noinput -v 0 \
 && rm -rf /tmp/build-data && chmod -R a+rX,go-w /app && chmod 755 docker/entrypoint.sh

USER probant
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/sante/', timeout=4).status == 200 else 1)"
LABEL org.opencontainers.image.title="Probant" \
      org.opencontainers.image.description="Configurable KPI collection and monitoring" \
      org.opencontainers.image.source="https://github.com/Probant-Reporting/probant"
ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["server"]
