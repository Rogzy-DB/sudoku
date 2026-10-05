# The public container

`SUDOKU_PUBLIC=1`: one cookie per browser, games under `/data/games/<visitor>/`, the
private-only routes (`/act`, `/status.json`, `/capabilities`, `/import`) answer 404,
and the stylesheet is served from `public/static/`. Build from a **tag**, never from a
working tree:

    git archive --format=tar <tag> | docker build -t sudoku-public -f deploy/public/Dockerfile -
    docker run -d --name sudoku-public --restart unless-stopped -p 127.0.0.1:8801:8801 \
      --read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges \
      --memory 256m --cpus 0.5 -v sudoku-public-data:/data sudoku-public

TLS and the hostname are the reverse proxy's job; the cookie is `Secure`, so it needs HTTPS.
