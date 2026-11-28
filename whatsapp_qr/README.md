# Bot de WhatsApp por código QR (sin API de Meta) — CRM Econotec

Programa pequeño en Node.js que se vincula al número de WhatsApp escaneando un QR, igual que WhatsApp Web
(librería `whatsapp-web.js`). Pasa al CRM cada mensaje que llega y envía las respuestas de EconoBot y de las asesoras.

> Cuando se conecte la **API oficial de WhatsApp** (claves `WA_API_*` en `.env`), el CRM la usa primero y este
> puente deja de ser necesario. Ver `crm/whatsapp_api.py`.

## Activarlo
Viene **encendido**: no hay que poner claves. La clave entre Econotec y este programa sale sola de `SECRET_KEY`
(o de `WA_QR_TOKEN` si la defines). Para apagarlo: `WA_QR_ACTIVO=False` en `.env`.

**En el servidor**: `scripts/aws_update.sh` lo instala y lo deja corriendo como servicio `econotec-whatsapp`
(necesita Node.js 18+ y las librerías de Chrome: `sudo apt install nodejs npm` y, si Chrome no abre,
`sudo apt install -y libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxrandr2 libgbm1 libasound2 libpango-1.0-0`).
Registro: `sudo journalctl -u econotec-whatsapp -f`.

**En la Mac**: doble clic en `Iniciar WhatsApp.command` (la primera vez instala lo necesario).

Luego, en el CRM: **Ajustes de WhatsApp → Conexión** y escanea el QR con el celular de la empresa
(WhatsApp → Dispositivos vinculados → Vincular un dispositivo). Solo la primera vez: la sesión queda en `.wwebjs_auth/`.

Dónde busca a Econotec: `CRM_URL` o `SISTEMA_URL` del `.env`; si no hay, `https://econosystem.cc` con `DEBUG=False`
y `http://127.0.0.1:8000` en la Mac.

## Qué hace
- Responde solo a chats individuales que escriben primero (no grupos, estados ni difusiones).
- Pausa de 1-2 s antes de cada respuesta y "escribiendo…", para no parecer spam.
- Al reconectar no responde mensajes viejos.
- Si el cliente pide un asesor, o una asesora responde desde **Chats de WhatsApp**, el bot se calla en ese chat.

## Límites
- No es oficial: WhatsApp puede bloquear el número si detecta uso automatizado intenso. Para pocos mensajes y
  respondiendo a quien escribe, el riesgo es bajo; para alto volumen, la API oficial.
- El equipo donde corre debe estar encendido con el programa abierto y el celular con internet.
- Si WhatsApp cambia algo y deja de funcionar: `cd whatsapp_qr && npm update whatsapp-web.js`.
- Cambiar de número: en el celular cierra el dispositivo vinculado y borra la carpeta `.wwebjs_auth/`.
