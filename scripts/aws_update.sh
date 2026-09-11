#!/usr/bin/env bash
set -euo pipefail

BRANCH="${BRANCH:-main}"
SERVICE_NAME="${SERVICE_NAME-econotec}"
PROJECT_DIR="${PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${VENV_DIR:-$PROJECT_DIR/.venv}"

cd "$PROJECT_DIR"

if [ ! -d ".git" ]; then
    echo "Este script debe ejecutarse dentro del clon Git de Econotec."
    exit 1
fi

if ! command -v git >/dev/null 2>&1; then
    echo "Git no esta instalado en este servidor."
    exit 1
fi

if ! git diff-index --quiet HEAD --; then
    echo "Hay cambios locales en archivos versionados. Revisa antes de actualizar:"
    git status --short
    exit 1
fi

current_branch="$(git rev-parse --abbrev-ref HEAD)"
if [ "$current_branch" != "$BRANCH" ]; then
    echo "Rama actual: $current_branch. Para actualizar desde otra rama usa BRANCH=$current_branch."
    echo "Este script esta configurado para actualizar desde: $BRANCH."
    exit 1
fi

git fetch origin "$BRANCH"
git pull --ff-only origin "$BRANCH"

if [ ! -d "$VENV_DIR" ]; then
    "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install -r requirements.txt
"$VENV_DIR/bin/python" manage.py migrate --noinput
"$VENV_DIR/bin/python" manage.py collectstatic --noinput
"$VENV_DIR/bin/python" manage.py setup_roles
"$VENV_DIR/bin/python" manage.py check

if [ -n "$SERVICE_NAME" ]; then
    if command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files --type=service --no-pager | awk '{print $1}' | grep -Fxq "${SERVICE_NAME}.service"; then
        sudo systemctl restart "${SERVICE_NAME}.service"
        sudo systemctl --no-pager --lines=12 status "${SERVICE_NAME}.service"
    else
        echo "No se encontro el servicio ${SERVICE_NAME}.service; reinicialo manualmente si usas otro nombre."
    fi
fi

echo "Econotec actualizado correctamente desde origin/$BRANCH."
