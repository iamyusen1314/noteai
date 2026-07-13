FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY gateway/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

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
