"""
Módulo de Alertas y Bodegaje del sistema Econotec.

Maneja DOS tipos de alertas independientes:

  1. ALERTA DE EQUIPOS DEMORADOS EN TALLER
     - Equipos en estado "Ingresado / En diagnóstico" que llevan más de
       UMBRAL_DIAS_DIAGNOSTICO días desde su ingreso.
     - Apenas el técnico cambia el estado a otro (En reparación, etc.)
       la alerta DESAPARECE — para que no sea molesta y se enfoque solo
       en equipos que llevan días sin diagnosticarse.

  2. ALERTA DE BODEGAJE (post-salida)
     - Equipos a los que ya se les registró salida POSITIVA pero el cliente
       aún no ha venido a retirarlos físicamente.
     - Pasados UMBRAL_DIAS_BODEGAJE días desde la fecha de salida, empieza
       a acumularse $COSTO_BODEGAJE_DIA por día.
     - El cobro NO se aplica automáticamente al saldo del cliente: queda
       calculado aparte y se le da al asesor la opción de aplicarlo o no
       cuando el cliente venga a pagar / retirar.
     - Cuando el cliente viene físicamente, se marca "Cliente ya retiró"
       en la salida, lo que congela el monto acumulado y cierra el caso.

También expone helpers para generar enlaces wa.me con mensajes
predefinidos profesionales.
"""
from datetime import date, timedelta
from decimal import Decimal
from urllib.parse import quote
from django.urls import reverse

from .models import IngresoEquipo, SalidaEquipo


# Días pasados los cuales un equipo "ingresado" sin diagnosticar genera alerta.
# Solo se mostrará la alerta cuando el equipo lleve 4 o más días sin diagnóstico.
UMBRAL_DIAS_DIAGNOSTICO = 4

# Estados que generan la alerta de demora en taller.
# El usuario pidió SOLO "ingresado / en diagnóstico". Si cambia el estado,
# la alerta desaparece automáticamente.
ESTADOS_ALERTA_DIAGNOSTICO = ['ingresado']

# Días de gracia después de que un equipo está listo (fecha_salida) antes de
# acumular cobro de bodegaje.
UMBRAL_DIAS_BODEGAJE = 5

# Costo de bodegaje por día acumulado (USD).
COSTO_BODEGAJE_DIA = Decimal('1.00')

# Estados de SalidaEquipo en los que aplica el cobro de bodegaje.
ESTADOS_SALIDA_CON_BODEGAJE = [
    'pendiente_retiro',
    'cliente_no_acepta',
    'no_reparable',
    'garantia',
    'garantia_fallos_adicionales',
    'retirado',
]


# ═════════════════════════════════════════════════════════════════
# 1. ALERTA: equipos demorados en diagnóstico
# ═════════════════════════════════════════════════════════════════

def equipos_demorados_qs(usuario=None, umbral_dias=UMBRAL_DIAS_DIAGNOSTICO, incluir_silenciados=False):
    """
    Devuelve un QuerySet de IngresoEquipo en estado 'ingresado' (esperando
    diagnóstico) que llevan demasiado tiempo sin que se les haga el
    diagnóstico inicial.

    Apenas el técnico cambia el estado a 'en_reparacion' u otro,
    el equipo desaparece de esta lista (es la lógica que pidió el usuario).

    Por defecto excluye los equipos con `diagnostico_silenciado=True`
    (modo "no molestar" — el equipo sigue pendiente pero no aparece
    en el banner del dashboard).

    Si se pasa `usuario`, filtra solo los equipos cuyo técnico encargado
    sea ese usuario. Si no, devuelve todos (vista admin).
    """
    fecha_limite = date.today() - timedelta(days=umbral_dias)

    qs = (
        IngresoEquipo.objects
        .select_related('cliente', 'tecnico_encargado')
        .filter(fecha_ingreso__lte=fecha_limite)
        .filter(estado__in=ESTADOS_ALERTA_DIAGNOSTICO)
        .filter(salida__isnull=True)
        .order_by('fecha_ingreso', 'numero_equipo')
    )

    if not incluir_silenciados:
        qs = qs.filter(diagnostico_silenciado=False)

    if usuario is not None and usuario.is_authenticated:
        qs = qs.filter(tecnico_encargado=usuario)

    return qs


def dias_en_taller(ingreso, hoy=None):
    """Cuántos días lleva el equipo en el taller desde su ingreso."""
    if hoy is None:
        hoy = date.today()
    if not ingreso.fecha_ingreso:
        return 0
    return (hoy - ingreso.fecha_ingreso).days


# ═════════════════════════════════════════════════════════════════
# 2. ALERTA: salidas con bodegaje pendiente
# ═════════════════════════════════════════════════════════════════

def salidas_bodegaje_qs(usuario=None, umbral_dias=UMBRAL_DIAS_BODEGAJE, incluir_silenciados=False):
    """
    Devuelve un QuerySet de SalidaEquipo POSITIVAS, sin retiro real
    confirmado, y que ya superaron el umbral de días para empezar a
    acumular bodegaje.

    Se excluyen las salidas donde fecha_retiro_real ya está marcada
    (caso cerrado, no hay nada por hacer).

    Por defecto excluye los equipos con `bodegaje_silenciado=True`
    (modo "no molestar" — el bodegaje sigue acumulándose pero no
    aparece en las alertas del dashboard).

    Si se pasa `usuario`, filtra solo las salidas cuyo equipo tenga
    como técnico encargado a ese usuario.
    """
    fecha_limite = date.today() - timedelta(days=umbral_dias)

    qs = (
        SalidaEquipo.objects
        .select_related('ingreso', 'ingreso__cliente', 'ingreso__tecnico_encargado')
        .filter(fecha_salida__lte=fecha_limite)
        .filter(estado_reparacion__in=ESTADOS_SALIDA_CON_BODEGAJE)
        .filter(fecha_retiro_real__isnull=True)
        .order_by('fecha_salida')
    )

    if not incluir_silenciados:
        qs = qs.filter(bodegaje_silenciado=False)

    if usuario is not None and usuario.is_authenticated:
        qs = qs.filter(ingreso__tecnico_encargado=usuario)

    return qs


def dias_desde_salida(salida, hoy=None):
    """Cuántos días pasaron desde que se registró la salida del equipo."""
    if hoy is None:
        hoy = date.today()
    if not salida.fecha_salida:
        return 0
    return (hoy - salida.fecha_salida).days


# ═════════════════════════════════════════════════════════════════
# 3. Mensajes de WhatsApp predefinidos
# ═════════════════════════════════════════════════════════════════

def whatsapp_link_demora(ingreso):
    """
    Mensaje al cliente cuando su equipo lleva varios días en
    diagnóstico sin novedad. Devuelve None si no hay número.
    """
    numero = (ingreso.cliente.whatsapp or '').strip()
    if not numero:
        return None
    numero_limpio = _normalizar_numero_ec(numero)
    if not numero_limpio:
        return None

    dias = dias_en_taller(ingreso)
    nombre_cliente = (ingreso.cliente.nombres or '').split(' ')[0] or 'cliente'
    nombre_tecnico = ingreso.tecnico_encargado_nombre or 'el equipo técnico de Econotec'

    if dias > 0:
        linea_dias = f"(lleva *{dias} día(s)* con nosotros)"
    else:
        linea_dias = "(ingresado el día de hoy)"

    mensaje = (
        f"Estimado(a) {nombre_cliente}, reciba un cordial saludo de parte de *Econotec — Reparación de Tecnología*.\n\n"
        f"Le escribimos para informarle sobre el estado de su equipo:\n\n"
        f"📋 *Equipo en revisión*\n"
        f"• Código: *{ingreso.codigo_equipo}*\n"
        f"• Equipo: {ingreso.tipo_equipo_display} {ingreso.marca}\n"
        f"• Fecha de ingreso: {ingreso.fecha_ingreso.strftime('%d/%m/%Y')} {linea_dias}\n\n"
        f"Nos encontramos finalizando el diagnóstico de su equipo. "
        f"En breve le confirmaremos el resultado y el costo aproximado de la reparación, "
        f"para que pueda tomar la mejor decisión.\n\n"
        f"Agradecemos su paciencia y confianza. Cualquier consulta, "
        f"no dude en escribirnos por este mismo medio.\n\n"
        f"Saludos cordiales,\n"
        f"{nombre_tecnico} — Econotec"
    )
    return f"https://wa.me/{numero_limpio}?text={quote(mensaje)}"


def whatsapp_link_equipo_listo(salida):
    """
    Mensaje al cliente cuando se acaba de registrar la salida:
    "Su equipo ya está listo, puede pasar a retirarlo".

    Devuelve None si la salida NO está pendiente de retiro o si el cliente no tiene WhatsApp.
    """
    if not salida.pendiente_de_retiro_fisico:
        return None

    ingreso = salida.ingreso
    numero = (ingreso.cliente.whatsapp or '').strip()
    if not numero:
        return None
    numero_limpio = _normalizar_numero_ec(numero)
    if not numero_limpio:
        return None

    # Saludo personalizado por género no detectable → usamos "estimado(a)"
    nombre_cliente = (ingreso.cliente.nombres or '').split(' ')[0] or 'cliente'
    nombre_tecnico = ingreso.tecnico_encargado_nombre or 'el equipo técnico de Econotec'

    # Estado del trabajo en términos claros para el cliente
    estado_label = salida.get_estado_reparacion_display()

    saldo = ingreso.diferencia
    if saldo and saldo > 0:
        # ingreso.diferencia ya viene cuantizado a 2 decimales,
        # pero formateamos explícitamente por seguridad
        saldo_fmt = f'{saldo:.2f}'.replace('.', ',')
        linea_saldo = (
            f"💵 *Saldo pendiente al retiro:* ${saldo_fmt}\n"
        )
    elif ingreso.estado_pago == 'Pagado':
        linea_saldo = "✅ *Estado de pago:* Cancelado en su totalidad.\n"
    else:
        linea_saldo = ""

    if salida.garantia_dias and salida.garantia_dias > 0:
        linea_garantia = (
            f"🛡 *Garantía:* {salida.garantia_dias} días sobre el trabajo realizado.\n"
        )
    else:
        linea_garantia = ""

    # Mensaje formal estilo correspondencia profesional
    mensaje = (
        f"Estimado(a) {nombre_cliente}, reciba un cordial saludo de parte de *Econotec — Reparación de Tecnología*.\n\n"
        f"Nos complace informarle que su equipo se encuentra *listo para retiro*:\n\n"
        f"📋 *Detalle de salida*\n"
        f"• Código de equipo: *{ingreso.codigo_equipo}*\n"
        f"• Equipo: {ingreso.tipo_equipo_display} {ingreso.marca}"
    )
    if ingreso.modelo_serie:
        mensaje += f" — {ingreso.modelo_serie_detalle}"
    mensaje += (
        f"\n• Estado del trabajo: {estado_label}\n"
        f"• Fecha de salida: {salida.fecha_salida.strftime('%d/%m/%Y')}\n"
        f"• Técnico encargado: {nombre_tecnico}\n\n"
        f"{linea_saldo}"
        f"{linea_garantia}"
        f"\nPor favor, coordine con nosotros el día y horario para pasar a retirar su equipo. "
        f"Le recordamos presentar su comprobante de ingreso al momento del retiro.\n\n"
        f"📦 *Política de bodegaje:* Le informamos que, para garantizar la seguridad y el espacio adecuado, "
        f"todo equipo no retirado generará un cargo de *${COSTO_BODEGAJE_DIA:.2f}* diarios a partir del 5to día desde esta notificación.\n\n"
        f"Agradecemos su confianza en Econotec. Quedamos atentos a sus comentarios.\n\n"
        f"Saludos cordiales,\n"
        f"*Econotec — Reparación de Tecnología*"
    )
    return f"https://wa.me/{numero_limpio}?text={quote(mensaje)}"


def whatsapp_link_bodegaje(salida):
    """
    Mensaje al cliente cuando ya pasaron varios días desde la salida y
    aún no ha venido a retirar el equipo. Le informa profesionalmente
    del cobro de bodegaje acumulado.
    """
    ingreso = salida.ingreso
    numero = (ingreso.cliente.whatsapp or '').strip()
    if not numero:
        return None
    numero_limpio = _normalizar_numero_ec(numero)
    if not numero_limpio:
        return None

    bodegaje = salida.calcular_bodegaje()
    if not bodegaje['aplica']:
        return None

    dias_desde = dias_desde_salida(salida)
    nombre_cliente = (ingreso.cliente.nombres or '').split(' ')[0] or 'cliente'
    nombre_tecnico = ingreso.tecnico_encargado_nombre or 'el equipo técnico de Econotec'

    monto_fmt = f"{bodegaje['monto']:.2f}".replace('.', ',')
    costo_dia_fmt = f"{COSTO_BODEGAJE_DIA:.2f}".replace('.', ',')

    mensaje = (
        f"Estimado(a) {nombre_cliente}, reciba un cordial saludo de parte de *Econotec — Reparación de Tecnología*.\n\n"
        f"Le recordamos que su equipo "
        f"({ingreso.tipo_equipo_display} {ingreso.marca}) "
        f"con código *{ingreso.codigo_equipo}* se encuentra *listo* desde el "
        f"{salida.fecha_salida.strftime('%d/%m/%Y')} "
        f"(hace *{dias_desde} día(s)*) y aún no ha sido retirado.\n\n"
        f"📦 Conforme a nuestra política de bodegaje, a partir del sexto día de estar listo "
        f"se aplica un cargo de *${costo_dia_fmt} diarios* por almacenamiento. "
        f"Hasta hoy se han acumulado *${monto_fmt}* "
        f"({bodegaje['dias']} día(s) de bodegaje).\n\n"
        f"Le agradecemos coordinar el retiro de su equipo a la brevedad "
        f"para evitar mayores cargos.\n\n"
        f"Quedamos atentos a sus comentarios.\n\n"
        f"Saludos cordiales,\n"
        f"{nombre_tecnico} — Econotec"
    )
    return f"https://wa.me/{numero_limpio}?text={quote(mensaje)}"


# ─────────────────────────────────────────────────────────────────
# Helpers internos
# ─────────────────────────────────────────────────────────────────

def _normalizar_numero_ec(numero):
    """
    Limpia un número de teléfono y le agrega el código de país de
    Ecuador (+593) si no lo trae. Devuelve solo dígitos, listo para wa.me.
    """
    if not numero:
        return ''
    solo_digitos = ''.join(ch for ch in numero if ch.isdigit())
    if not solo_digitos:
        return ''
    if solo_digitos.startswith('593') and len(solo_digitos) >= 11:
        return solo_digitos
    if solo_digitos.startswith('0'):
        return '593' + solo_digitos[1:]
    if solo_digitos.startswith('9') and len(solo_digitos) == 9:
        return '593' + solo_digitos
    return solo_digitos

def whatsapp_link_hoja_ingreso(request, ingreso):
    """
    Mensaje al cliente para enviarle la hoja de ingreso en PDF (sin URL).
    """
    numero = (ingreso.cliente.whatsapp or '').strip()
    if not numero:
        return None
    numero_limpio = _normalizar_numero_ec(numero)
    if not numero_limpio:
        return None

    nombre_cliente = (ingreso.cliente.nombres or '').split(' ')[0] or 'cliente'

    texto = (
        f"Hola *{nombre_cliente}* 👋,\n\n"
        f"Te adjuntamos la hoja de ingreso de tu equipo *{ingreso.marca}*.\n\n"
        f"Por favor, lea detenidamente los términos y condiciones indicados en el documento adjunto. "
        f"Para autorizar la revisión y reparación de su equipo, responda a este mensaje con la palabra *SÍ* o *ACEPTAR*.\n\n"
        f"Gracias por confiar en *Econotec*."
    )

    return f"https://api.whatsapp.com/send?phone={numero_limpio}&text={quote(texto)}"
