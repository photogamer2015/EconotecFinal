# Bot de WhatsApp por código QR (sin API de Meta) — CRM Econotec

Programa pequeño en Node.js que se vincula al número de WhatsApp escaneando un QR, igual que WhatsApp Web
(librería `whatsapp-web.js`). Pasa al CRM cada mensaje que llega y envía las respuestas de EconoBot y de las asesoras.

> Cuando se conecte la **API oficial de WhatsApp** (claves `WA_API_*` en `.env`), el CRM la usa primero y este
> puente deja de ser necesario. Ver `crm/whatsapp_api.py`.

## Activarlo
1. Instala Node.js 18 o superior (`brew install node` en Mac).
2. En el `.env` de Econotec: `WA_QR_ACTIVO=True` y `WA_QR_TOKEN=` con una clave larga.
   Si Econotec no corre en `http://127.0.0.1:8000`, define también `CRM_URL=` (p. ej. `http://127.0.0.1:8000`).
3. `cd whatsapp_qr && npm install && npm start` (el QR también sale en la terminal).
4. En el CRM: **Ajustes de WhatsApp → Conexión** y escanea el QR con el celular
   (WhatsApp → Dispositivos vinculados → Vincular un dispositivo). Solo la primera vez: la sesión queda en `.wwebjs_auth/`.

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
