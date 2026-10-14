# Slim and multi-arch (amd64, arm64 for Oracle Ampere and Raspberry Pi). Pure Python, no build step.
#   docker compose up -d --build
# For CV tailoring: docker compose build --build-arg EXTRAS="anthropic python-docx"
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
ARG EXTRAS=""
RUN if [ -n "$EXTRAS" ]; then pip install $EXTRAS; fi

COPY jobbot/ jobbot/
COPY presets/ presets/
COPY tools/ tools/
COPY config.example.yml profile.example.yml companies.example.yml .env.example ./

# Same uid as the first user on most Linux hosts, so the bind-mounted data/ folder is writable.
RUN useradd --uid 1000 --home /app --shell /usr/sbin/nologin jobbot \
    && mkdir -p /app/data && chown jobbot:jobbot /app/data
USER jobbot

CMD ["python", "-m", "jobbot", "run"]
