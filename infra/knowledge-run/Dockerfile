# The scheduled knowledge run (docs/knowledge-cloud-run.md): Papyrus + Biblicus + BERTopic + GLiNER2 on CPU, models baked in.
# Papyrus and Biblicus are pinned (build args PAPYRUS_VERSION, BIBLICUS_REF). Build for arm64 (Fargate Graviton): infra/knowledge-run/build_image.sh
FROM public.ecr.aws/docker/library/python:3.12-slim-bookworm

ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONUNBUFFERED=1 \
    HF_HOME=/opt/hf TOKENIZERS_PARALLELISM=false

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates build-essential \
    && rm -rf /var/lib/apt/lists/*

# Pinned science stack: the versions of the 2026-10-22 workstation runs (torch is the CPU build on aarch64).
COPY infra/knowledge-run/constraints.txt /tmp/constraints.txt
# PyPI's aarch64 torch pulls the CUDA libraries (gigabytes, no GPU here), so torch comes from the CPU index first.
RUN pip install --index-url https://download.pytorch.org/whl/cpu "torch==2.14.1"
ARG BIBLICUS_REF=b433d5133287064221d82899206034a310ee1af9
RUN pip install -c /tmp/constraints.txt \
        "biblicus[typed-extraction,topic-modeling] @ git+https://github.com/AnthusAI/Biblicus@${BIBLICUS_REF}" boto3 \
    && rm -rf /root/.cache

# The models come before the Papyrus source, so a code change rebuilds only the last small layer.
COPY infra/knowledge-run/bake_models.py /tmp/bake_models.py
RUN python /tmp/bake_models.py && rm /tmp/bake_models.py

# Papyrus is the release from PyPI (it carries the data files the run needs), not a source tree.
ARG PAPYRUS_VERSION=5.30.0
ARG PAPYRUS_SPEC=
RUN pip install -c /tmp/constraints.txt "${PAPYRUS_SPEC:-papyrus-newsroom[markus]==${PAPYRUS_VERSION}}" && rm -rf /root/.cache

ENV PAPYRUS_ALLOW_CROSS_ROOT=1 PAPYRUS_GRAPHQL_AUTH=iam HOME=/tmp
WORKDIR /work
ENTRYPOINT []
CMD ["papyrus", "knowledge", "cloud-run", "--help"]
