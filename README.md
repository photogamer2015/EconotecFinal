# Econotec 2.8 — Sistema de Gestión de Reparación de Tecnología

Sistema web para administrar el flujo de reparaciones de Econotec: ingreso de equipos, abonos, salidas y panel administrativo. Permite **imprimir o descargar** la Solicitud de Ingreso y el Acta de Salida ya rellenadas con los datos del cliente, con un formato visual que replica las hojas físicas.

---

## 🆕 Cambios versión 2.8

- **Formulario de Abono rediseñado** con secciones claras (Bodegaje, Método de pago, Factura).
- **Método de pago**: el formulario de abonos usa 3 opciones: Efectivo, Transferencia bancaria y Tarjeta de crédito / Débito.
- **Transferencia bancaria**: si el método de pago es transferencia, ahora son **obligatorios** el banco y el **link del comprobante** (Drive, WhatsApp, etc.). Si se elige "Otro banco", aparece un input para escribir el nombre.
- **Factura**: nuevo bloque con "¿Factura realizada? Sí/No". Si se elige **Sí**, los 4 campos (Nombres, Apellidos, Cédula/RUC, Correo) se marcan en rojo con asterisco y se vuelven obligatorios. Si se elige **No**, son opcionales.
- **Bodegaje en el abono**: cuando el equipo tiene bodegaje acumulado, el formulario muestra la pregunta **"¿Aplicar valor de bodegaje?"** con dos opciones:
  - **Sí**: el monto del bodegaje se suma automáticamente al monto del abono (autocompleta el campo) y queda registrado como cobrado.
  - **No**: el bodegaje se perdona automáticamente, deja de acumular día a día y no se le cobra al cliente.
  En ambos casos, el bodegaje queda congelado en la salida del equipo sin marcar al cliente como ya retirado.

## 🆕 Cambios versión 2.7

- **Formato de dinero corregido**: se eliminó el problema de números con muchos decimales (ej. `$234,970000000000`). Ahora todos los montos se muestran con formato estilo Ecuador: `$1.234,56`.
- **Bodegaje como saldo informativo**: el bodegaje acumulado aparece junto al saldo del cliente en Pagos (`📦 +$X,XX — Con bodegaje: $Y,YY`), sin afectar el saldo real. La decisión de cobrarlo o perdonarlo se mantiene al momento del retiro físico.
- **Alertas mejoradas**: ya no aparece el confuso "hace más de 0 días" cuando el umbral está en cero. Se muestra "pendientes de diagnóstico" / "listos pendientes de retiro". La píldora por equipo dice "Hoy" si fue ingresado el mismo día.
- **Mensajes WhatsApp profesionales**: reescritos los tres mensajes automáticos (equipo listo, demora en diagnóstico, bodegaje pendiente) con tono formal "Estimado(a)..." y bloque de detalle completo con código, equipo, fecha, técnico, saldo y garantía.
- **Pantalla post-salida ampliada**: al registrar una salida positiva ahora aparece, además del botón verde de WhatsApp, una guía clara y botones directos de "Descargar hoja de salida (PDF)" e "Imprimir" para que se pueda adjuntar al chat.

---

## 📋 Contenido

- **Ingreso de Equipo / Cliente** → Reemplaza al módulo de matrícula. Genera la Solicitud de Ingreso lista para imprimir.
- **Salida de Equipo** → Cierre de la reparación con estado (reparado / no reparable / cliente no quiso / parcial / garantía), repuestos, garantía y cobro final.
- **Pagos / Abonos** → Control de pagos parciales por equipo, con recibo imprimible.
- **Clientes** → Directorio con historial de equipos por cliente.
- **Historial** → Equipos agrupados por mes/año.
- **Registro Administrativo** *(solo admin)* → Balance financiero del mes (ingresos vs egresos).
- **Roles**: Administrador y Técnico.

---

## 🚀 Instalación

### 1) Requisitos previos
- Python 3.10 o superior
- pip

### 2) Clonar / descomprimir el proyecto y entrar a la carpeta
```bash
cd econotec
```

### 3) Crear un entorno virtual e instalar dependencias
```bash
python -m venv venv
# Activar:
#   Windows:  venv\Scripts\activate
#   Linux/Mac: source venv/bin/activate

pip install -r requirements.txt
```

### 4) Aplicar las migraciones (crea las tablas en la base SQLite por defecto)
```bash
python manage.py migrate
```

### 5) Crear los grupos de roles y categorías de egreso por defecto
```bash
python manage.py setup_roles
```

### 6) Crear un superusuario (administrador inicial)
```bash
python manage.py createsuperuser
```
Te pedirá usuario, correo y contraseña.

### 7) Levantar el servidor
```bash
python manage.py runserver
```
Accede a `http://127.0.0.1:8000/` y entra con tu superusuario.

---

## 👥 Asignar usuarios a roles

1. Entra a `http://127.0.0.1:8000/admin/`
2. Ve a **Users** → selecciona un usuario.
3. En la sección **Groups**, agrégalo a **Administradores** o **Tecnicos**.

> Los superusuarios siempre tienen acceso total, incluso sin estar en un grupo.

---

## 🖨 Imprimir / Descargar formularios

Desde el detalle de cada equipo o salida, hay dos opciones:
- **🖨 Imprimir** → Abre una versión HTML estilo "papel Econotec" lista para usar Ctrl+P o Cmd+P.
- **📄 Descargar PDF** → Genera un PDF con el formato exacto de la hoja física (logo, cajas Equipo N°, checkboxes, nota importante, firmas).

---

## 📂 Estructura del proyecto

```
econotec/
├── manage.py
├── requirements.txt
├── README.md
├── core/
│   ├── settings.py     # config Django
│   ├── urls.py
│   └── wsgi.py / asgi.py
├── econotec/           # app principal
│   ├── models.py       # Cliente, IngresoEquipo, Abono, SalidaEquipo, Egreso
│   ├── views.py        # ingresos, salidas, clientes, bienvenida
│   ├── views_pagos.py  # abonos, historial
│   ├── views_admin.py  # dashboard administrativo, egresos
│   ├── views_print.py  # generación PDF (ReportLab)
│   ├── forms.py
│   ├── urls.py
│   ├── permisos.py     # decoradores admin_requerido / tecnico_requerido
│   ├── admin.py        # registro Django Admin
│   ├── migrations/
│   └── management/commands/setup_roles.py
├── templates/          # plantillas HTML
│   ├── base.html       # layout con tema naranja Econotec
│   ├── login.html
│   ├── bienvenida.html # dashboard
│   ├── ingresos/       # menu, lista, form, detalle, imprimir
│   ├── salidas/        # menu, lista, form, imprimir
│   ├── clientes/
│   ├── pagos/
│   ├── historial/
│   └── admin_panel/
└── static/             # logo, etc.
```

---

## 🔧 Configuración para producción

En desarrollo se usa SQLite. Para usar MySQL, crea un archivo `.env` en la raíz:

```ini
DEBUG=False
SECRET_KEY=cambia-esto-por-una-cadena-larga-y-aleatoria
DB_NAME=econotec
DB_USER=tu_usuario
DB_PASSWORD=tu_password
DB_HOST=127.0.0.1
DB_PORT=3306
```

Luego instala `mysqlclient` y corre `python manage.py migrate`.

### Correo para doble factor

Por defecto, en desarrollo Django imprime el código de doble factor en la terminal del servidor. Para enviar el código por correo real, agrega tu SMTP al `.env`:

```ini
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.tu-proveedor.com
EMAIL_PORT=587
EMAIL_HOST_USER=tu_correo@dominio.com
EMAIL_HOST_PASSWORD=tu_clave_smtp
EMAIL_USE_TLS=True
DEFAULT_FROM_EMAIL=Econotec <tu_correo@dominio.com>
```

Si un usuario todavía no tiene correo, el sistema se lo pedirá una sola vez
después de validar usuario, contraseña, sede y captcha. El correo se guarda
solo cuando el usuario confirma el código enviado a ese correo.

Si el usuario se equivoca, olvida o pierde acceso a ese correo, un administrador
puede corregirlo manualmente desde Django Admin en **Users** → usuario → **Email
address**.

---

## 📞 Contacto Econotec

- **Guayaquil:** Sauces 8 Mz 462 Solar / 6 Piso 2 Oficina 2
- **Quito:** Av. Amazonas y 18 de septiembre / Piso 2 Oficina 102
- WhatsApp: 0963289727 — 0980758747
- Web: www.econotec.ec.com — Correo: ventas@econotec.ec.com
# Econotec
