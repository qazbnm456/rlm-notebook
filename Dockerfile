# rlm-notebook in a container, which exists for ONE reason: two of its dependencies are system
# binaries that no Python manifest can express, so `pip install rlm-notebook` is never sufficient
# on its own.
#
#   deno       every live run executes in a Deno-hosted pyodide sandbox (AGENTS.md invariant 9),
#              and `RN_INTERPRETER` refuses any other value rather than silently falling back
#   tesseract  the OCR fallback. `pytesseract` is a WRAPPER: invariant 7 records that without the
#              binary the fallback is silently not there, which is the failure mode this image
#              removes rather than documents
#
# Build:  docker build -t rlm-notebook .
# Run:    docker run --rm -p 127.0.0.1:8000:8000 \
#           -v "$PWD/data:/data" --env-file .env rlm-notebook
#
# PUBLISH THE PORT TO LOOPBACK, as above. This API has NO AUTHENTICATION of any kind (invariant
# 25): anyone who can reach it can read every notebook's full source text and reasoning traces,
# delete sources, and change settings for notebooks they never named. A bare `-p 8000:8000`
# publishes it on every interface of the host.

# 3.12, NOT 3.13, and this is a real constraint rather than caution: `rapidocr-onnxruntime`
# declares `Requires-Python >=3.6,<3.13`, so `pip install` on 3.13 fails outright with "No matching
# distribution found". The local `uv` environment runs 3.13 with rapidocr 1.4.4 anyway, which is uv
# resolving past the bound rather than the bound not existing. 3.12 is the newest interpreter every
# core dependency actually declares support for.
FROM python:3.12-slim AS base

# `deno` is fetched as a release binary rather than through the install script, so the version is
# pinned and the build does not depend on a shell script fetched at build time.
ARG DENO_VERSION=2.1.4
ARG TARGETARCH

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl unzip \
        tesseract-ocr \
        # rapidocr pulls opencv, which needs these at runtime even in its headless build
        libglib2.0-0 libgl1 \
    && rm -rf /var/lib/apt/lists/*

RUN set -eux; \
    case "${TARGETARCH:-amd64}" in \
      amd64) DENO_TARGET=x86_64-unknown-linux-gnu ;; \
      arm64) DENO_TARGET=aarch64-unknown-linux-gnu ;; \
      *) echo "unsupported architecture: ${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    curl -fsSL -o /tmp/deno.zip \
      "https://github.com/denoland/deno/releases/download/v${DENO_VERSION}/deno-${DENO_TARGET}.zip"; \
    unzip -q /tmp/deno.zip -d /usr/local/bin; \
    rm /tmp/deno.zip; \
    deno --version

WORKDIR /src
COPY pyproject.toml README.md ./
COPY rlm_notebook ./rlm_notebook

# The `api` extra only. `chatterbox` is deliberately absent: it is marked `python_full_version >=
# '3.13'` and drags torch in for a provider that is 33x the wall clock of the default
# (invariant 43), which is not what an image anybody pulls should carry.
RUN pip install --no-cache-dir '.[api]'

# `notebooks/`, `traces/` and `audio/` are relative paths resolved against the working directory
# (invariant 34), so the workdir IS where a reader's data lives. Mount it, or the container losing
# its filesystem loses their notebooks.
WORKDIR /data
VOLUME /data

EXPOSE 8000
# 0.0.0.0 inside the container, because the container boundary is what makes that safe. Which
# INTERFACE OF THE HOST it reaches is decided by `-p`, which is why the run command above binds it
# to loopback. `serve` prints its no-authentication warning either way, and it is not wrong to.
CMD ["rlm-notebook", "serve", "--host", "0.0.0.0", "--port", "8000"]
