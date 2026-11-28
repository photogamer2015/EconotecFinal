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

# Tareas diarias (resumen al admin y recordatorio a técnicos). El cron corre
# cada hora y el comando solo envía a la hora configurada en Guayaquil.
# Se reemplaza la línea marcada para no duplicarla en cada despliegue.
CRON_MARCA="# econotec-tareas-diarias"
if command -v crontab >/dev/null 2>&1; then
    cron_linea="0 * * * * cd \"$PROJECT_DIR\" && \"$VENV_DIR/bin/python\" manage.py tareas_diarias >> \"$PROJECT_DIR/tareas_diarias.log\" 2>&1 $CRON_MARCA"
    cron_actual="$(crontab -l 2>/dev/null | grep -vF "$CRON_MARCA" || true)"
    { if [ -n "$cron_actual" ]; then printf '%s\n' "$cron_actual"; fi; echo "$cron_linea"; } | crontab -
    echo "Cron de tareas diarias instalado."
else
    echo "Aviso: crontab no esta disponible; las tareas diarias no se programaron."
fi

# Bot de WhatsApp por código QR del CRM (carpeta whatsapp_qr/, Node.js).
# Se instala como servicio econotec-whatsapp si hay Node.js y no está apagado
# con WA_QR_ACTIVO=False en .env. La sesión de WhatsApp queda en whatsapp_qr/.wwebjs_auth.
WA_SERVICE="econotec-whatsapp"
wa_apagado="$(grep -iE '^WA_QR_ACTIVO=(false|0|no)' "$PROJECT_DIR/.env" 2>/dev/null || true)"
if [ -n "$wa_apagado" ]; then
    echo "Bot de WhatsApp por QR apagado en .env (WA_QR_ACTIVO=False)."
elif command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1 && command -v systemctl >/dev/null 2>&1; then
    (cd "$PROJECT_DIR/whatsapp_qr" && npm install --no-fund --no-audit --omit=dev) || echo "Aviso: npm install de whatsapp_qr falló."
    wa_unit="[Unit]
Description=Econotec CRM - puente de WhatsApp por codigo QR
After=network-online.target ${SERVICE_NAME:-econotec}.service

[Service]
User=$(id -un)
WorkingDirectory=$PROJECT_DIR/whatsapp_qr
ExecStart=$(command -v node) index.js
Restart=always
RestartSec=10
Environment=NODE_ENV=production

[Install]
WantedBy=multi-user.target"
    if [ "$(cat /etc/systemd/system/${WA_SERVICE}.service 2>/dev/null)" != "$wa_unit" ]; then
        { printf '%s\n' "$wa_unit" | sudo tee "/etc/systemd/system/${WA_SERVICE}.service" >/dev/null \
            && sudo systemctl daemon-reload && sudo systemctl enable "${WA_SERVICE}.service"; } \
            || echo "Aviso: no se pudo instalar el servicio ${WA_SERVICE}."
    fi
    if sudo systemctl restart "${WA_SERVICE}.service"; then
        echo "Bot de WhatsApp (QR) en marcha: escanea el QR en CRM → Ajustes de WhatsApp → Conexión."
    else
        echo "Aviso: ${WA_SERVICE} no arrancó; revisa: sudo journalctl -u ${WA_SERVICE} -n 40"
    fi
else
    echo "Aviso: falta Node.js 18+ en el servidor para el bot de WhatsApp por QR (sudo apt install nodejs npm)."
fi

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
