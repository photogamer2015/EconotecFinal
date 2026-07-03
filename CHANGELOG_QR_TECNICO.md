# CHANGELOG — QR + Hoja Digital del Técnico

## Versión: Econotec 2.9.3 (QR + Hoja móvil del técnico)

Esta actualización agrega el flujo completo de **digitalización de la Solicitud
de Ingreso mediante código QR**, optimizado para que el técnico actualice los
equipos desde el celular.

---

## ¿Qué hace?

1. **Al registrar un ingreso**, el sistema genera automáticamente un **código QR
   híbrido** que se imprime en la hoja física (esquina de "FACTURA N°").
   El QR contiene:
   - Un **resumen de los datos** de la hoja embebido (equipo, cliente, problema,
     fecha, técnico). Funciona aunque no haya internet o el equipo cambie luego.
   - Un **enlace firmado** a la "hoja digital viva" del equipo.

2. **El técnico escanea el QR con el celular.** Si no tiene sesión iniciada, el
   sistema lo lleva al **login** (usuario + contraseña + sede) y, tras iniciar
   sesión, lo devuelve **automáticamente a la hoja del equipo**. Como la sesión
   queda guardada, solo inicia sesión la primera vez.

   El QR también se puede **descargar como imagen PNG** (botón "⬇ Descargar QR"
   en el detalle del equipo y en la hoja imprimible), para guardarlo, pegarlo en
   otro documento o imprimirlo aparte. El archivo se nombra con el código del
   equipo, p.ej. `QR_Econotec_G3.png`.

3. **Ve la hoja digitalizada** en formato optimizado para celular: cliente,
   equipo, problema reportado (todo en solo lectura). Puede editar únicamente:
   - **Reporte del técnico** (lo que se le realizó al equipo).
   - **Estado del equipo**, con el mismo mapeo que el sistema:
     - **En diagnóstico** → `ingresado`
     - **En reparación** → `en_reparacion` (el equipo se mantiene en el taller;
       con subestado opcional: espera de cliente / espera de repuesto).
     - **Entregado — Con solución** → crea **Salida POSITIVA** (`retirado`).
     - **Entregado — Sin solución** → crea **Salida NEGATIVA** (`no_reparable`).

   > El técnico **no toca valores monetarios**. El cobro y el detalle financiero
   > se siguen gestionando desde el módulo de Pagos / Salidas en escritorio.

---

## Archivos NUEVOS

| Archivo | Descripción |
|---|---|
| `econotec/qr_utils.py` | Generación del QR híbrido + tokens firmados (HMAC). |
| `econotec/views_tecnico.py` | Vistas de la hoja móvil del técnico (ver + actualizar). |
| `templates/tecnico/hoja.html` | Hoja digital optimizada para celular. |
| `templates/tecnico/hoja_invalida.html` | Pantalla amable para QR inválido. |

## Archivos MODIFICADOS

| Archivo | Cambio |
|---|---|
| `econotec/urls.py` | Nueva ruta `tecnico/hoja/<token>/` y `ingresos/<pk>/qr.png`. |
| `econotec/views.py` | `ingreso_detalle` ahora pasa el QR al template. |
| `econotec/views_print.py` | La hoja imprimible incluye el QR + vista `ingreso_qr_png` para descargar el QR como PNG. |
| `econotec/views_auth.py` | Login respeta `?next=` de forma segura (anti open-redirect). |
| `templates/login.html` | Campo oculto `next` en el formulario. |
| `templates/ingresos/detalle.html` | Botón "📱 Ver QR" + modal con el QR y botón de descarga PNG. |
| `templates/ingresos/imprimir.html` | QR en el encabezado + botón "⬇ Descargar QR". |
| `requirements.txt` | Añadidas dependencias `qrcode` y `pillow`. |

---

## Migraciones

**Ninguna.** Esta funcionalidad reutiliza los campos existentes del modelo
(`reporte_tecnico`, `estado`, `subestado_reparacion`, `subestado_entregado`) y
el modelo `SalidaEquipo` ya existente. No hay cambios de base de datos.

---

## Instalación

```bash
pip install -r requirements.txt
python manage.py runserver
```

> **Importante para producción:** el enlace del QR usa el dominio desde el que se
> genera la hoja (`request.build_absolute_uri`). Asegúrate de acceder al sistema
> por el **dominio/IP definitivo** al imprimir las hojas, para que el QR apunte a
> la dirección correcta. Si usas `localhost`, el QR solo funcionará en esa
> máquina.

---

## Seguridad

- El acceso a la hoja exige **sesión iniciada** y rol que pueda gestionar equipos
  (Técnico, Asesor o Admin).
- El enlace usa un **token firmado** (HMAC con `SECRET_KEY`): no se pueden
  adivinar ni iterar URLs de otros equipos.
- El login valida `?next=` contra el host propio para evitar redirecciones
  maliciosas (open-redirect).

---

## Pruebas realizadas (todas pasaron)

- Token firmado: round-trip correcto; token alterado → inválido.
- QR híbrido: contiene datos embebidos + enlace; escaneable (verificado con
  decodificador real).
- Acceso sin sesión → redirige a login con `?next=`.
- Login con `next` → vuelve a la hoja.
- Reporte del técnico se guarda.
- Estado "En reparación" (con subestado) → sin salida.
- Estado "Con solución" → salida positiva (`retirado`).
- Estado "Sin solución" → salida negativa (`no_reparable`).
- Regresar a "En reparación" desde entregado → elimina la salida.
- Token inválido → 404 con mensaje amable.
