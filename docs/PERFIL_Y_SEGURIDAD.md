# Perfil unificado y seguridad — 12 de septiembre de 2026

## Uso del perfil

En **Mi perfil** se reúnen avatar, portada, biografía, intereses, amigos, nivel, estadísticas y progreso. La comunidad autenticada puede consultar el nivel y estadísticas de otros miembros. El correo y los tres accesos personales solo se renderizan en el perfil propio: equipos recibidos, equipos reparados y bitácora del día. Las APIs de perfil y bitácora siempre usan al usuario de la sesión, aunque se envíe otro identificador en la URL.

Los permisos de trabajo de los módulos de equipos siguen permitiendo la colaboración entre técnicos, asesores y administradores. Ocultar los accesos personales en perfiles ajenos no convierte los registros operativos compartidos en registros exclusivos del propietario. La edición de avatar, portada e información sí se comprueba por propietario en el servidor.

El puntaje conserva las reglas del sistema: buena +4, producto +1, mala −1, mínimo cero; las garantías cuentan como buenas. El progreso se calcula desde el comienzo del nivel actual. Los asesores conservan su categoría y selector de color.

## Protección aplicada

- Cierre de sesión mediante POST con CSRF; una petición GET no cierra la cuenta.
- Respuestas autenticadas con `private, no-store`, y recarga al restaurar una página desde la caché de navegación. El servidor invalida la sesión al salir. Atrás sigue siendo una función normal del navegador; no concede permisos ni recupera una sesión cerrada.
- Sesión de ocho horas, con un plazo absoluto comprobado en cada petición, y cookie de sesión que expira al cerrar el navegador (los navegadores con restauración de sesión pueden conservarla). Las sesiones antiguas adoptan el plazo en su primera petición posterior a esta actualización.
- Contadores de acceso persistentes, compartidos entre procesos: máximo 20 peticiones por cuenta y 120 por IP en ventanas de 15 minutos. Incluyen captcha fallido; los endpoints de verificación y reenvío también consumen el límite por IP. Se responde 429 con `Retry-After`. Los identificadores se guardan como hashes y los contadores vencidos se eliminan al recibir nuevos intentos.
- `/admin/login/` usa el mismo flujo con captcha y verificación por correo, evitando el formulario alternativo de contraseña del administrador de Django.
- Dos redirecciones de alertas ahora validan el destino; esas acciones requieren un rol operativo. Se rechazan tipos JSON incorrectos en el selector de color.
- Con `DEBUG=False`: HTTPS obligatorio, cookies Secure, HSTS, validación de clave privada y rechazo de `ALLOWED_HOSTS=*`. Se quitaron los dominios y orígenes CSRF comodín predeterminados.
- Django 5.2.17 LTS y dependencias fijadas en `requirements.lock`. La auditoría del conjunto resuelto no encontró vulnerabilidades conocidas el 12/09/2026; esto no certifica ausencia de fallos en la aplicación.

## Arranque local

Se preparó `.venv` dentro del proyecto con las versiones de `requirements.lock`. Para iniciar desde esta carpeta:

```sh
source .venv/bin/activate
python manage.py migrate
python manage.py runserver
```

Para otra computadora, crear primero el entorno con `python3 -m venv .venv` e instalar con `python -m pip install -r requirements.lock`. La migración `0065_limite_acceso` agrega únicamente la tabla de límites de acceso; `0066_alerta_reparacion_estado` agrega la fecha que mide alertas de equipos detenidos en reparación. No eliminan equipos, usuarios ni perfiles.

## Servidor de producción

1. Respaldar la base de datos y probar restaurarla. Instalar `requirements.lock`, ejecutar `migrate`, `collectstatic --noinput` y `check --deploy`, y reiniciar Gunicorn usando ese entorno virtual.
2. Configurar `.env` con `DEBUG=False`, una `SECRET_KEY` aleatoria de al menos 50 caracteres y los dominios exactos en `ALLOWED_HOSTS` y `CSRF_TRUSTED_ORIGINS`. No publicar `.env`, bases de datos ni respaldos como archivos estáticos.
3. Configurar correo SMTP real y verificar que llega el código de acceso, también para el administrador. No usar el backend de consola en producción.
4. Terminar TLS en un proxy propio. Activar `TRUST_PROXY_HTTPS=True` solo si ese proxy elimina/sobrescribe `X-Forwarded-Proto` del cliente; de lo contrario, mantenerlo en False. No exponer el puerto de Gunicorn directamente a Internet.
5. El límite por IP utiliza `REMOTE_ADDR`, no cabeceras enviadas por el cliente. Detrás de un proxy puede ser compartido por todos los usuarios; configurar además limitación en el proxy y revisar su capacidad según el uso real.
6. `SECURE_HSTS_INCLUDE_SUBDOMAINS` y `SECURE_HSTS_PRELOAD` están desactivados por defecto. Activarlos solo si todos los subdominios están preparados para HTTPS; mientras estén desactivados, `check --deploy` muestra W005/W021. No se silencian esos avisos.

No se ha publicado esta modificación ni inspeccionado un servidor remoto. Firewall, TLS real, permisos del sistema, correo, copias de seguridad y restauración necesitan validación en el entorno de despliegue. La revisión cubre los puntos descritos y no equivale a una auditoría exhaustiva o certificación de todo el software.

Referencias: [lista de despliegue de Django](https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/), [versiones soportadas](https://www.djangoproject.com/download/).

## Verificación realizada

- 293 pruebas automatizadas aprobadas con las versiones instaladas desde `requirements.lock`.
- Perfil y editor comprobados en Chromium a 320, 375, 480, 768, 1024, 1440 y 1920 píxeles de ancho, sin desbordamiento horizontal ni errores de JavaScript. No se ha probado cada dispositivo o motor de navegador.
- Prueba real de Atrás después de salir: redirección a login, sin recuperar el perfil privado.
- API de perfil y bitácora privada, edición ajena, CSRF, límites de intentos, sesión vencida y redirecciones externas comprobadas mediante pruebas.
- Migración local aplicada. Respaldo previo en `output/backups/antes-perfil-seguridad-20260912.sqlite3` (permisos 600). Las 20 tablas existentes de negocio, usuarios, grupos y sesiones conservan exactamente sus registros; Django añadió los metadatos y permisos de la tabla nueva.
- Evidencias en `output/perfil-seguridad/`: capturas de escritorio y móvil con datos de prueba, resultado de la suite y auditoría de dependencias.
