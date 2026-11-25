#
# Copyright IBM Corp. 2026
# SPDX-License-Identifier: Apache-2.0
#

# The example runner: AgenticHarvest, its examples, and its tests in one image, so the
# only thing a user installs is Podman or Docker.
#
# Built by run.sh / run.ps1 (or `compose --profile runner build`) with the
# agenticharvest repo root as the build context. Nothing secret is copied in: the
# root .dockerignore excludes .env, and the image reads settings at run time
# from the /state volume and the environment.

FROM mirror.gcr.io/library/python:3.12.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies first, so editing an example does not reinstall them.
COPY pyproject.toml README.md LICENSE NOTICE ./
COPY src ./src
RUN pip install ".[web,openai_compatible]" "pytest>=8"

COPY tests ./tests
COPY examples ./examples
COPY examples/systems/runner/entrypoint.sh /usr/local/bin/agenticharvest-run

# Settings and downloaded API descriptions live on the /state volume, so they
# survive between runs; the code reads them at the paths it always uses.
RUN chmod +x /usr/local/bin/agenticharvest-run \
    && rm -rf /app/examples/systems/specs \
    && ln -s /state/specs /app/examples/systems/specs \
    && ln -s /state/.env /app/.env

ENTRYPOINT ["agenticharvest-run"]
CMD ["help"]
