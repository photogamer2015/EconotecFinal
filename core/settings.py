"""
Django settings for Econotec project.
Sistema de gestión de reparación de tecnología.
"""
from pathlib import Path
import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, True),
    SECRET_KEY=(str, 'django-insecure-econotec-dev-key-cambiar-en-produccion-xxxxxxxx'),
    DB_NAME=(str, ''),
    DB_USER=(str, ''),
    DB_PASSWORD=(str, ''),
    DB_HOST=(str, '127.0.0.1'),
    DB_PORT=(str, '3306'),
)
env_file = BASE_DIR / '.env'
if env_file.exists():
    environ.Env.read_env(env_file)

import os

SECRET_KEY = env('SECRET_KEY')
DEBUG = env('DEBUG')
GEMINI_API_KEY = env('GEMINI_API_KEY', default='')

# ── AWS S3 — Backup automático de la base de datos ──────────
# Configura estas variables en tu archivo .env cuando tengas tus credenciales.
# Mientras estén vacías, el backup simplemente no se ejecuta (no causa error).
AWS_ACCESS_KEY_ID = env('AWS_ACCESS_KEY_ID', default='')
AWS_SECRET_ACCESS_KEY = env('AWS_SECRET_ACCESS_KEY', default='')
AWS_S3_BUCKET_NAME = env('AWS_S3_BUCKET_NAME', default='')
AWS_S3_REGION = env('AWS_S3_REGION', default='us-east-1')

# ── Correo — doble factor de autenticación ──────────
# En desarrollo el código se imprime en la terminal del servidor. Para enviar
# correos reales, configura estas variables en .env con tu proveedor SMTP.
EMAIL_HOST = env('EMAIL_HOST', default='')
EMAIL_PORT = env.int('EMAIL_PORT', default=587)
EMAIL_HOST_USER = env('EMAIL_HOST_USER', default='')
EMAIL_HOST_PASSWORD = env('EMAIL_HOST_PASSWORD', default='')
EMAIL_USE_TLS = env.bool('EMAIL_USE_TLS', default=True)
DEFAULT_FROM_EMAIL = env('DEFAULT_FROM_EMAIL', default='Econotec <no-reply@econotec.local>')
EMAIL_BACKEND = env('EMAIL_BACKEND', default='')
if not EMAIL_BACKEND:
    EMAIL_BACKEND = (
        'django.core.mail.backends.smtp.EmailBackend'
        if EMAIL_HOST and EMAIL_HOST_USER and EMAIL_HOST_PASSWORD
        else 'django.core.mail.backends.console.EmailBackend'
    )

ALLOWED_HOSTS = ['127.0.0.1', 'localhost', '*']

# Orígenes confiables para formularios POST (CSRF).
# Necesario al entrar por una IP de red local o por un túnel (Cloudflare/ngrok)
# desde el celular. Los comodines aceptan los subdominios temporales que generan
# estas herramientas, así que sirve aunque cambie la URL al reabrir el túnel.
# IMPORTANTE: en producción reemplaza esto por tu dominio real, p.ej.:
#   CSRF_TRUSTED_ORIGINS = ['https://econotec.ec.com']
CSRF_TRUSTED_ORIGINS = [
    'http://192.168.*.*:8000',
    'http://192.168.*.*',
    'http://10.*.*.*:8000',
    'http://172.16.*.*:8000',
    # Túneles para probar desde el celular (Cloudflare Tunnel / ngrok).
    'https://*.trycloudflare.com',
    'https://*.ngrok-free.app',
    'https://*.ngrok.io',
]

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'econotec',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'econotec.middleware.ActividadUsuarioMiddleware',
]

# Sesiones persistentes: no se cierran por inactividad.
# El cierre normal de sesión ocurre solo al usar el botón "Cerrar sesión".
SESSION_COOKIE_AGE = 60 * 60 * 24 * 365  # 1 año
SESSION_SAVE_EVERY_REQUEST = False
SESSION_EXPIRE_AT_BROWSER_CLOSE = False

ROOT_URLCONF = 'core.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'econotec.context_processors.roles',
            ],
        },
    },
]

WSGI_APPLICATION = 'core.wsgi.application'

if env('DB_NAME'):
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.mysql',
            'NAME': env('DB_NAME'),
            'USER': env('DB_USER'),
            'PASSWORD': env('DB_PASSWORD'),
            'HOST': env('DB_HOST'),
            'PORT': env('DB_PORT'),
            'OPTIONS': {
                'charset': 'utf8mb4',
                'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
            },
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'es-ec'
TIME_ZONE = 'America/Guayaquil'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/bienvenida/'
