FROM public.ecr.aws/lambda/python:3.13

COPY pyproject.toml README.md LICENSE* ${LAMBDA_TASK_ROOT}/papyrus/
COPY src ${LAMBDA_TASK_ROOT}/papyrus/src
COPY corpora ${LAMBDA_TASK_ROOT}/papyrus/corpora
RUN python3 -m pip install --no-cache-dir "${LAMBDA_TASK_ROOT}/papyrus[markus]" "tactus >=0.53.4,<1" \
        "pypdf >=5,<7" "youtube-transcript-api >=1.2.4,<2" "tiktoken >=0.12.0,<0.13.0" \
    && rm -rf /root/.cache

ENV PAPYRUS_ROOT=${LAMBDA_TASK_ROOT}/papyrus \
    PAPYRUS_GRAPHQL_AUTH=iam \
    HOME=/tmp

CMD ["papyrus_content.procedure_runner.handler"]
