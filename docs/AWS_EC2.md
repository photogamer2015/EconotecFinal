# Despliegue y actualización en AWS EC2

Esta guía deja Econotec listo para actualizarse desde GitHub con un solo script
en un servidor EC2 con Ubuntu.

## Primer despliegue

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip nginx
sudo mkdir -p /var/www
sudo chown "$USER":"$USER" /var/www
git clone https://github.com/photogamer2015/EconotecFinal.git /var/www/EconotecFinal
cd /var/www/EconotecFinal
cp .env.example .env
nano .env
bash scripts/aws_update.sh
```

En `.env`, cambia al menos estos valores:

```ini
DEBUG=False
SECRET_KEY=pon-una-clave-larga-y-segura
ALLOWED_HOSTS=econotec.ec.com,www.econotec.ec.com,IP_PUBLICA_DE_EC2
CSRF_TRUSTED_ORIGINS=https://econotec.ec.com,https://www.econotec.ec.com
```

Si usas MySQL o Amazon RDS, instala las librerías del sistema y llena el bloque
`DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST` y `DB_PORT` en `.env`.

```bash
sudo apt install -y build-essential pkg-config default-libmysqlclient-dev
/var/www/EconotecFinal/.venv/bin/python -m pip install mysqlclient
```

## Servicio systemd

Crea `/etc/systemd/system/econotec.service`:

```ini
[Unit]
Description=Econotec Django
After=network.target

[Service]
User=ubuntu
Group=www-data
WorkingDirectory=/var/www/EconotecFinal
ExecStart=/var/www/EconotecFinal/.venv/bin/gunicorn core.wsgi:application --bind 127.0.0.1:8000 --workers 3 --timeout 120
Restart=always

[Install]
WantedBy=multi-user.target
```

Activa el servicio:

```bash
sudo systemctl daemon-reload
sudo systemctl enable econotec
sudo systemctl restart econotec
sudo systemctl status econotec
```

## Nginx

Crea `/etc/nginx/sites-available/econotec`:

```nginx
server {
    listen 80;
    server_name econotec.ec.com www.econotec.ec.com IP_PUBLICA_DE_EC2;

    location /static/ {
        alias /var/www/EconotecFinal/staticfiles/;
    }

    location /media/ {
        alias /var/www/EconotecFinal/media/;
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Activa Nginx:

```bash
sudo ln -sf /etc/nginx/sites-available/econotec /etc/nginx/sites-enabled/econotec
sudo nginx -t
sudo systemctl restart nginx
```

## Actualizar después de subir cambios a GitHub (a mano)

Si ya configuraste el despliegue automático (sección siguiente), esto no hace
falta: queda como respaldo.

```bash
cd /var/www/EconotecFinal
SERVICE_NAME=econotec bash scripts/aws_update.sh
```

El script:

- baja la última versión desde `origin/main`;
- instala dependencias en `.venv`;
- aplica migraciones;
- actualiza archivos estáticos;
- ejecuta `setup_roles`;
- valida Django con `manage.py check`;
- reinicia `econotec.service` si existe.

Si el servicio tiene otro nombre:

```bash
SERVICE_NAME=nombre-del-servicio bash scripts/aws_update.sh
```

Si solo quieres preparar archivos sin reiniciar systemd:

```bash
SERVICE_NAME= bash scripts/aws_update.sh
```

## Despliegue automático desde GitHub

El workflow `.github/workflows/desplegar.yml` hace esto solo: cada vez que algo
entra en `main` (merge de un PR o push directo), GitHub entra por SSH al
servidor y ejecuta `scripts/aws_update.sh`, el mismo script de arriba.

### 1. Clave SSH solo para el despliegue

En tu computadora:

```bash
ssh-keygen -t ed25519 -C "despliegue-econotec" -f ~/.ssh/econotec_deploy -N ""
ssh-copy-id -i ~/.ssh/econotec_deploy.pub ubuntu@IP_DEL_SERVIDOR
ssh-keyscan -H IP_DEL_SERVIDOR
```

### 2. Secretos en GitHub

En el repositorio → **Settings → Secrets and variables → Actions → New
repository secret**:

| Secreto | Valor |
| --- | --- |
| `SSH_HOST` | IP o dominio del servidor |
| `SSH_USUARIO` | usuario del servidor (ej.: `ubuntu`) |
| `SSH_CLAVE_PRIVADA` | contenido completo de `~/.ssh/econotec_deploy` (con las líneas `BEGIN`/`END`) |
| `SSH_KNOWN_HOSTS` | salida de `ssh-keyscan -H IP_DEL_SERVIDOR` |

En la pestaña **Variables** puedes cambiar, si tu servidor es distinto:
`RUTA_PROYECTO` (por defecto `/var/www/EconotecFinal`), `NOMBRE_SERVICIO`
(por defecto `econotec`) y `SSH_PUERTO` (por defecto `22`).

Mientras falten `SSH_HOST` o `SSH_USUARIO`, el workflow se salta el despliegue
y lo avisa: no falla nada y el servidor se sigue actualizando a mano.

### 3. Sudo sin contraseña para reiniciar el servicio

El script reinicia `econotec.service` con `sudo`, y por SSH automático no hay
quién escriba la contraseña. En el servidor:

```bash
echo 'ubuntu ALL=(ALL) NOPASSWD: /bin/systemctl restart econotec.service, /bin/systemctl status econotec.service' | sudo tee /etc/sudoers.d/econotec-deploy
sudo chmod 440 /etc/sudoers.d/econotec-deploy
```

### 4. Probarlo

En GitHub → pestaña **Actions** → «Desplegar en el servidor» → **Run
workflow**. Ahí mismo se ve el registro completo del despliegue.

Ojo: el script se detiene si el servidor tiene cambios locales en archivos
versionados (`git status` sucio). Es a propósito, para no pisar nada.

## Tareas diarias (cron automático)

`scripts/aws_update.sh` instala solo, en el crontab del usuario que despliega,
esta línea (la reemplaza en cada despliegue, nunca la duplica):

```cron
0 * * * * cd "/var/www/EconotecFinal" && "/var/www/EconotecFinal/.venv/bin/python" manage.py tareas_diarias >> "/var/www/EconotecFinal/tareas_diarias.log" 2>&1 # econotec-tareas-diarias
```

Corre cada hora, pero el comando solo envía cuando en Guayaquil son las
`TAREAS_DIARIAS_HORA` (7 por defecto), así que no importa la zona horaria del
servidor. Necesita el correo SMTP configurado (`EMAIL_HOST`, etc.). Para
probarlo sin esperar:

```bash
cd /var/www/EconotecFinal
.venv/bin/python manage.py tareas_diarias --forzar
tail -n 20 tareas_diarias.log
```

## Notificaciones push (app en el celular)

No hay que configurar nada en el servidor: las dependencias (`pywebpush`)
vienen en `requirements.lock` y las claves VAPID se crean solas en la base de
datos. Solo hace falta que el sitio se sirva por **HTTPS** y que `/service-worker.js`
y `/manifest.webmanifest` lleguen a Django (si Nginx sirve archivos de la raíz,
no debe interceptar esas dos rutas). Para apagarlo: `PUSH_ACTIVO=False` en el `.env`.

## Backup opcional a S3

Si usas SQLite, Econotec incluye un comando de backup a S3:

```bash
/var/www/EconotecFinal/.venv/bin/python manage.py backup_s3
```

Para programarlo todos los días a las 3:00 AM:

```bash
crontab -e
```

Agrega:

```cron
0 3 * * * cd /var/www/EconotecFinal && .venv/bin/python manage.py backup_s3 >> /var/log/econotec-backup.log 2>&1
```
