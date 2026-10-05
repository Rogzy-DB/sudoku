# Public mode of the sudoku (sudoku.rogzy.org) — stdlib only, no pip install.
# Build from a TAG, never from a working tree (see README.md next to this file).
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SUDOKU_PUBLIC=1 \
    SUDOKU_DIR=/data \
    LUNA_APP_HOST=0.0.0.0 \
    PORT=8801

WORKDIR /app
# only what runs: the server, the vendored kit, the engine, the version, the stylesheet
COPY app.py lunaapp.py VERSION /app/
COPY sudoku/ /app/sudoku/
COPY public/ /app/public/

# precompile (the root fs is read-only at run time), then a non-root owner for /data
RUN python -m compileall -q /app \
 && groupadd --system --gid 10001 sudoku \
 && useradd --system --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin sudoku \
 && mkdir -p /data && chown 10001:10001 /data

USER 10001:10001
VOLUME /data
EXPOSE 8801

HEALTHCHECK --interval=60s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8801/healthz', timeout=4).status == 200 else 1)"

CMD ["python", "/app/app.py"]
