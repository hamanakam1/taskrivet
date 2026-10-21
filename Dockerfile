FROM python:3.13-slim
LABEL org.opencontainers.image.source="https://github.com/hamanakam1/taskrivet" \
      org.opencontainers.image.description="Taskrivet coordination CLI; desktop and local dashboard bridge are separate" \
      org.opencontainers.image.licenses="MIT"
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY taskrivet ./taskrivet
RUN pip install --no-cache-dir . && useradd --create-home --uid 10001 taskrivet && mkdir /data && chown taskrivet /data
USER taskrivet
ENV TASKRIVET_DB=/data/ledger.sqlite
VOLUME ["/data"]
ENTRYPOINT ["taskrivet"]
CMD ["--help"]
