#!/bin/bash
# Econotec CRM — abre el puente de WhatsApp por código QR en la Mac.
# Deja esta ventana abierta mientras uses los Chats de WhatsApp. Detener: Ctrl + C.
cd "$(dirname "$0")"
if ! command -v node >/dev/null 2>&1; then
  echo "Falta Node.js. Instálalo con: brew install node   (o desde https://nodejs.org)"
  read -r -p "Presiona Enter para cerrar"; exit 1
fi
if [ ! -d node_modules ]; then
  echo "Instalando el bot de WhatsApp (solo la primera vez, tarda 1-2 minutos)..."
  npm install --no-fund --no-audit || { read -r -p "No se pudo instalar. Enter para cerrar"; exit 1; }
fi
echo "Abre Econotec → CRM → Ajustes de WhatsApp → Conexión y escanea el QR (también sale aquí abajo)."
exec node index.js
