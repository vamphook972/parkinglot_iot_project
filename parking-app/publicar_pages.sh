#!/usr/bin/env bash
# Publica la página del usuario en GitHub Pages (rama gh-pages).
#
# Uso (desde la raíz del repo):
#   parking-app/publicar_pages.sh                          # publica tal cual
#   parking-app/publicar_pages.sh https://xxxx.trycloudflare.com   # cambia la URL del túnel y publica
#
# Solo se publica la página del usuario. El panel de administración se queda en local
# (http://localhost:1880/app/admin.html) porque muestra placas y permite cancelar reservas.
# La rama gh-pages solo tiene estos archivos; GitHub Pages la sirve tal cual (Settings -> Pages ->
# Deploy from a branch -> gh-pages / root).
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"
ARCHIVOS=(index.html estilos.css comun.js usuario.js config.js)

if [[ $# -ge 1 ]]; then
    url="${1%/}"
    [[ "$url" =~ ^https://[a-z0-9.-]+$ ]] || { echo "URL inválida: $url" >&2; exit 1; }
    sed -i.bak -E "s#^window\.PARKING_API = '.*';#window.PARKING_API = '$url';#" parking-app/config.js
    rm -f parking-app/config.js.bak
    git add parking-app/config.js
    git commit -m "chore: URL del túnel -> $url" || true
    git push origin main
fi

tmp="$(mktemp -d)"
trap 'git worktree remove --force "$tmp" 2>/dev/null || true; rm -rf "$tmp"' EXIT

git fetch -q origin gh-pages 2>/dev/null || true
if git show-ref -q --verify refs/remotes/origin/gh-pages; then
    git worktree add -q -B gh-pages "$tmp" origin/gh-pages
else
    git worktree add -q --detach "$tmp"
    git -C "$tmp" checkout -q --orphan gh-pages
    git -C "$tmp" rm -rq --cached . && find "$tmp" -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
fi

for f in "${ARCHIVOS[@]}"; do cp "parking-app/$f" "$tmp/$f"; done
# GitHub Pages deja los archivos 10 min en la caché del navegador: con ?v=<commit> en cada
# script y hoja de estilos, al publicar código nuevo el navegador lo pide de nuevo.
version="$(git rev-parse --short HEAD)"
sed -i.bak -E "s#(src|href)=\"(estilos\.css|comun\.js|usuario\.js|config\.js)\"#\1=\"\2?v=$version\"#g" "$tmp/index.html"
rm -f "$tmp/index.html.bak"
touch "$tmp/.nojekyll"
git -C "$tmp" add -A
if git -C "$tmp" diff --cached --quiet; then
    echo "gh-pages ya está al día."
else
    git -C "$tmp" commit -qm "Publicar página del usuario ($(git rev-parse --short HEAD))"
    git -C "$tmp" push -q origin gh-pages
    echo "Publicado en gh-pages. GitHub Pages tarda ~1 min en actualizar."
fi
