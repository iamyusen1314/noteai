FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Debian DSA-6572-1: refresh both the CA bundle and its hashed trust directory.
RUN apt-get update \
    && apt-get install -y --no-install-recommends --only-upgrade ca-certificates \
    && update-ca-certificates --fresh \
    && rm -rf /var/lib/apt/lists/*

COPY gateway/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt \
    && python -c 'import re, ssl, sys; from pathlib import Path; import certifi; \
        defaults = ssl.get_default_verify_paths(); \
        ca_dir = Path(defaults.capath); \
        paths = {Path(certifi.where()), Path(defaults.cafile), Path("/etc/ssl/certs/ca-certificates.crt")}; \
        paths.update(p for p in ca_dir.iterdir() if re.fullmatch(r"[0-9a-fA-F]{8}\.[0-9]+", p.name)); \
        stores = [ssl.create_default_context(cafile=str(p)).get_ca_certs() for p in paths]; \
        any(not store for store in stores) and sys.exit("Empty CA trust store"); \
        names = {value for store in stores for cert in store for rdn in cert["subject"] for key, value in rdn if key == "commonName"}; \
        blocked = {"emSign ECC Root CA - G3", "AAA Certificate Services", "Comodo AAA Services root"}; \
        names.intersection(blocked) and sys.exit("eMudhra advisory roots remain trusted")'

COPY model/claude_gateway_protocol.py ./claude_gateway_protocol.py
COPY gateway/control_store.py ./control_store.py
COPY gateway/dynamodb_control_store.py ./dynamodb_control_store.py
COPY gateway/claude_gateway.py ./claude_gateway.py
COPY gateway/rehearsal.py ./rehearsal.py
COPY gateway/start.sh ./start.sh

RUN groupadd --system noteai-gateway \
    && useradd --system --gid noteai-gateway --home-dir /app --shell /usr/sbin/nologin noteai-gateway \
    && chmod 0555 /app/start.sh \
    && chown -R noteai-gateway:noteai-gateway /app

USER noteai-gateway

ENV PORT=8000
EXPOSE 8000

CMD ["/app/start.sh"]
