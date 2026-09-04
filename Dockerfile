# Cloud Run image for the myworld Flask app, built by Cloud Build via
# `gcloud run deploy --source .` (see scripts/deploy.sh). Dependencies come
# from uv.lock, the single place versions are controlled.
FROM python:3.14-slim

RUN pip install --no-cache-dir uv

WORKDIR /app

# Install dependencies before copying the code so code-only changes reuse
# this layer.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# The app package lives under src/; keep that layout so the import path is
# the same as in development and in the tests.
COPY src ./src
# The deploy stamp is written by scripts/deploy.sh just before deploying;
# building without it fails on purpose so an unstamped image never ships.
COPY build_info.json ./

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app/src"

# Cloud Run sets PORT; default to 8080 for local `docker run`.
CMD ["sh", "-c", "exec gunicorn -b :${PORT:-8080} --workers 1 --threads 8 --timeout 0 'myworld:create_app()'"]
