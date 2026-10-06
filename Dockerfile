# BikeHound in a container. Build: docker build -t bikehound .
# Run with one folder per bike mounted at /bike (config.yaml, reference/, data/), see README.
FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --locked --no-dev --no-editable

# Chromium outside $HOME, so it also works under `docker run --user`
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN /app/.venv/bin/playwright install --with-deps chromium

# the image model (about 1.5 GB) is cached in the mounted folder, downloaded once;
# HOME=/tmp because an arbitrary --user has no writable home
ENV HF_HOME=/bike/data/hf HOME=/tmp
WORKDIR /bike
ENTRYPOINT ["/app/.venv/bin/bikehound"]
CMD ["run"]
