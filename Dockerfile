FROM python:3.12-slim AS builder

WORKDIR /build
COPY pyproject.toml .
COPY forgeloop/ forgeloop/
RUN pip install --no-cache-dir build && python -m build --wheel --outdir /wheels

FROM python:3.12-slim

LABEL org.opencontainers.image.title="ForgeLoop"
LABEL org.opencontainers.image.description="Self-built coding agent harness with governance guardrails, HITL approval, and deterministic feedback loop"
LABEL org.opencontainers.image.source="https://github.com/Re4543/forgeloop"

RUN useradd --create-home --shell /bin/bash forgeloop
USER forgeloop
WORKDIR /home/forgeloop

COPY --from=builder /wheels/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && rm /tmp/*.whl

RUN mkdir -p /home/forgeloop/workspace
WORKDIR /home/forgeloop/workspace

EXPOSE 8000

ENV FORGELOOP_HOST=0.0.0.0
ENV FORGELOOP_PORT=8000

ENTRYPOINT ["forgeloop"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8000"]
