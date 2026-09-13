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

echo "Proyecto: $PROJECT_DIR"
echo "Rama esperada: $BRANCH"
echo "Commit actual antes de actualizar: $(git rev-parse --short HEAD)"

current_branch="$(git rev-parse --abbrev-ref HEAD)"
if [ "$current_branch" != "$BRANCH" ]; then
    echo "Rama actual: $current_branch. Para actualizar desde otra rama usa BRANCH=$current_branch."
    echo "Este script esta configurado para actualizar desde: $BRANCH."
    exit 1
fi

git fetch origin "$BRANCH"
echo "Commit disponible en origin/$BRANCH: $(git rev-parse --short "origin/$BRANCH")"
git pull --ff-only origin "$BRANCH"
echo "Commit actual despues de actualizar: $(git rev-parse --short HEAD)"

if [ ! -d "$VENV_DIR" ]; then
    "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install -r requirements.lock
"$VENV_DIR/bin/python" manage.py migrate --noinput
"$VENV_DIR/bin/python" manage.py collectstatic --noinput
"$VENV_DIR/bin/python" manage.py setup_roles
"$VENV_DIR/bin/python" manage.py check

if [ -n "$SERVICE_NAME" ]; then
    if command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files --type=service --no-pager | awk '{print $1}' | grep -Fxq "${SERVICE_NAME}.service"; then
        service_workdir="$(systemctl show "${SERVICE_NAME}.service" -p WorkingDirectory --value 2>/dev/null || true)"
        service_exec="$(systemctl show "${SERVICE_NAME}.service" -p ExecStart --value 2>/dev/null || true)"
        if [ -n "$service_workdir" ] && [ "$service_workdir" != "$PROJECT_DIR" ]; then
            echo "Aviso: ${SERVICE_NAME}.service usa WorkingDirectory=$service_workdir, pero este script actualizo $PROJECT_DIR."
        fi
        if [ -n "$service_exec" ] && ! printf '%s' "$service_exec" | grep -Fq "$PROJECT_DIR"; then
            echo "Aviso: ExecStart de ${SERVICE_NAME}.service no parece apuntar a $PROJECT_DIR."
            echo "$service_exec"
        fi
        sudo systemctl restart "${SERVICE_NAME}.service"
        sudo systemctl --no-pager --lines=12 status "${SERVICE_NAME}.service"
    else
        echo "No se encontro el servicio ${SERVICE_NAME}.service; reinicialo manualmente si usas otro nombre."
    fi
fi

echo "Econotec actualizado correctamente desde origin/$BRANCH en commit $(git rev-parse --short HEAD)."
