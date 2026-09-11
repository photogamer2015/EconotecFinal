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

## Actualizar después de subir cambios a GitHub

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
