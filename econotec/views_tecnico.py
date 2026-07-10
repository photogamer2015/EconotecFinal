"""
Vistas para el técnico en MÓVIL (digitalización de la Solicitud de Ingreso).

Flujo:
─────────────────────────────────────────────────────────────────────────
1. Al registrar un ingreso se imprime/genera un QR HÍBRIDO que contiene un
   resumen de los datos de la hoja embebido + un enlace firmado a la URL
   `tecnico_hoja` del equipo.
2. El técnico escanea el QR con el celular. Si no tiene sesión, el sistema
   lo manda al login (usuario + contraseña + sede) y luego lo devuelve a la
   hoja. La sesión queda guardada, así que solo logea una vez.
3. Ve la "hoja digital": todos los datos de la solicitud, optimizada para
   pantalla de celular, en modo solo-lectura excepto:
       • Reporte del técnico  (lo escribe él)
       • Estado del equipo     (lo cambia él)
4. El estado se maneja igual que en el sistema de escritorio:
       • En reparación              → el equipo se mantiene donde está.
       • Entregado — Con solución   → genera SALIDA POSITIVA.
       • Entregado — Sin solución   → genera SALIDA NEGATIVA.
─────────────────────────────────────────────────────────────────────────
"""
from datetime import date

from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from .models import IngresoEquipo, SalidaEquipo
from .permisos import puede_gestionar_equipos
from .qr_utils import pk_desde_token, token_para_ingreso


# ─────────────────────────────────────────────────────────
# Opciones de estado que ve el técnico en el móvil.
# Es una vista SIMPLIFICADA del flujo de estados real del sistema:
# colapsa "estado + subestado/salida" en un único selector intuitivo.
# ─────────────────────────────────────────────────────────
ESTADO_INGRESADO        = 'ingresado'
ESTADO_EN_REPARACION    = 'en_reparacion'
ESTADO_ENTREGADO_OK     = 'entregado_con_solucion'   
ESTADO_ENTREGADO_FAIL   = 'entregado_sin_solucion'    
ESTADO_ENTREGADO_NO_QUISO = 'entregado_no_quiso'      

OPCIONES_ESTADO_MOVIL = [
    (ESTADO_INGRESADO,      'Ingresado / En diagnóstico'),
    (ESTADO_EN_REPARACION,  'En reparación (se mantiene aquí)'),
    (ESTADO_ENTREGADO_OK,   'Con solución (Pendiente de retiro)'),
    (ESTADO_ENTREGADO_FAIL, 'Sin solución (Pendiente de retiro)'),
    (ESTADO_ENTREGADO_NO_QUISO, 'No quiso reparar (Pendiente de retiro)'),
]


def _estado_movil_actual(ingreso):
    """
    Traduce el estado real del IngresoEquipo (+ su salida si existe) al
    valor del selector móvil, para preseleccionar la opción correcta.
    """
    salida = getattr(ingreso, 'salida', None)
    if salida is not None:
        if salida.estado_reparacion == 'cliente_no_acepta':
            return ESTADO_ENTREGADO_NO_QUISO
        if salida.es_positivo:
            return ESTADO_ENTREGADO_OK
        return ESTADO_ENTREGADO_FAIL
    if ingreso.estado == 'en_reparacion':
        return ESTADO_EN_REPARACION
    return ESTADO_INGRESADO


def _resolver_ingreso(token):
    """Valida el token y devuelve el ingreso, o None si el token es inválido."""
    pk = pk_desde_token(token)
    if pk is None:
        return None
    return (
        IngresoEquipo.objects
        .select_related('cliente', 'tecnico_encargado', 'registrado_por')
        .filter(pk=pk)
        .first()
    )


# ═════════════════════════════════════════════════════════════════
# Hoja digital móvil (solo lectura de datos + edición de reporte/estado)
# ═════════════════════════════════════════════════════════════════

@require_http_methods(['GET', 'POST'])
def tecnico_hoja(request, token):
    """
    Hoja digital del equipo para el técnico, optimizada para celular.

    El acceso exige sesión iniciada y rol que pueda gestionar equipos
    (técnico, asesor o admin). Si no hay sesión, redirige al login y vuelve
    aquí automáticamente con ?next=.
    """
    # ── Control de acceso (con redirección amable al login) ──────────
    if not request.user.is_authenticated:
        login_url = reverse('login')
        return redirect(f'{login_url}?next={request.path}')

    if not puede_gestionar_equipos(request.user):
        messages.error(
            request,
            'No tienes permiso para gestionar equipos. '
            'Pide a un administrador que te asigne el rol de Técnico.'
        )
        return redirect('econotec:bienvenida')

    ingreso = _resolver_ingreso(token)
    if ingreso is None:
        return render(request, 'tecnico/hoja_invalida.html', status=404)

    salida = getattr(ingreso, 'salida', None)

    if request.method == 'POST':
        return _procesar_actualizacion(request, ingreso, token)

    valor_acordado_bloqueado = (
        ingreso.valor_acordado is not None
        and ingreso.estado_pago == 'Pagado'
    )

    contexto = {
        'ingreso': ingreso,
        'cliente': ingreso.cliente,
        'salida': salida,
        'token': token,
        'opciones_estado': OPCIONES_ESTADO_MOVIL,
        'estado_actual_movil': _estado_movil_actual(ingreso),
        'reporte_actual': ingreso.reporte_tecnico or '',
        'valor_acordado_actual': '.' if ingreso.valor_acordado is None else ingreso.valor_acordado,
        'valor_acordado_bloqueado': valor_acordado_bloqueado,
        'subestado_reparacion_actual': ingreso.subestado_reparacion or '',
        'subestados_reparacion': IngresoEquipo._meta.get_field(
            'subestado_reparacion').choices,
    }
    return render(request, 'tecnico/hoja.html', contexto)


@transaction.atomic
def _procesar_actualizacion(request, ingreso, token):
    """
    Guarda el reporte del técnico y aplica el cambio de estado seleccionado.

    El valor acordado es solo lectura en la hoja móvil. Se administra desde
    el sistema principal, y la salida nunca se registra mientras siga pendiente.
    """
    reporte = (request.POST.get('reporte_tecnico') or '').strip()
    estado_movil = (request.POST.get('estado_movil') or '').strip()
    subestado_rep = (request.POST.get('subestado_reparacion') or '').strip()
    accion = (request.POST.get('accion') or 'guardar').strip()

    # 1) Reporte del técnico — siempre se guarda.
    #    Si el contenido cambió (o se escribió por primera vez), registramos
    #    QUIÉN lo hizo y CUÁNDO, para que quede constancia del autor.
    from django.utils import timezone
    if reporte != (ingreso.reporte_tecnico or '').strip():
        ingreso.reporte_por = request.user
        ingreso.reporte_actualizado = timezone.now()
    ingreso.reporte_tecnico = reporte

    if accion == 'actualizar_valor':
        ingreso.save(update_fields=['reporte_tecnico', 'reporte_por',
                                    'reporte_actualizado', 'actualizado'])
        messages.info(request, 'El valor acordado se edita desde el sistema principal.')
        return redirect('econotec:tecnico_hoja', token=token)

    estados_crean_salida = {
        ESTADO_ENTREGADO_OK,
        ESTADO_ENTREGADO_FAIL,
        ESTADO_ENTREGADO_NO_QUISO,
    }
    solicita_salida = accion == 'registrar_salida' or estado_movil in estados_crean_salida

    if solicita_salida and ingreso.valor_acordado is None:
        ingreso.save(update_fields=['reporte_tecnico', 'reporte_por',
                                    'reporte_actualizado', 'actualizado'])
        messages.warning(
            request,
            'Por favor registra un valor acordado para registrar la salida.'
        )
        return redirect('econotec:tecnico_hoja', token=token)

    if solicita_salida:
        ingreso.save(update_fields=['reporte_tecnico', 'reporte_por',
                                    'reporte_actualizado', 'actualizado'])
        return redirect('econotec:salida_registrar', ingreso_pk=ingreso.pk)

    # 2) Aplicar el estado.
    if estado_movil == ESTADO_INGRESADO:
        _quitar_salida_si_existe(ingreso)
        ingreso.estado = 'ingresado'
        ingreso.subestado_reparacion = ''
        ingreso.subestado_entregado = ''
        ingreso.save()
        messages.success(request, f'Equipo {ingreso.codigo_equipo}: marcado como En diagnóstico.')

    elif estado_movil == ESTADO_EN_REPARACION:
        _quitar_salida_si_existe(ingreso)
        ingreso.estado = 'en_reparacion'
        # subestado opcional: espera de cliente / espera de repuesto
        validos = {c[0] for c in IngresoEquipo._meta.get_field('subestado_reparacion').choices}
        ingreso.subestado_reparacion = subestado_rep if subestado_rep in validos else ''
        ingreso.subestado_entregado = ''
        ingreso.save()
        messages.success(request, f'Equipo {ingreso.codigo_equipo}: marcado como En reparación.')

    elif estado_movil == ESTADO_ENTREGADO_OK:
        _crear_o_actualizar_salida(request, ingreso, 'pendiente_retiro')
        messages.success(
            request,
            f'Equipo {ingreso.codigo_equipo}: marcado CON SOLUCIÓN (pendiente de retiro).'
        )

    elif estado_movil == ESTADO_ENTREGADO_FAIL:
        _crear_o_actualizar_salida(request, ingreso, 'no_reparable')
        messages.success(
            request,
            f'Equipo {ingreso.codigo_equipo}: marcado SIN SOLUCIÓN (pendiente de retiro).'
        )

    elif estado_movil == ESTADO_ENTREGADO_NO_QUISO:
        _crear_o_actualizar_salida(request, ingreso, 'cliente_no_acepta')
        messages.success(
            request,
            f'Equipo {ingreso.codigo_equipo}: marcado como NO QUISO REPARAR (pendiente de retiro).'
        )

    else:
        # Estado no reconocido: guardamos solo el reporte.
        ingreso.save(update_fields=['reporte_tecnico', 'reporte_por',
                                    'reporte_actualizado', 'actualizado'])
        messages.warning(request, 'Estado no reconocido. Se guardó solo el reporte del técnico.')

    return redirect('econotec:tecnico_hoja', token=token)


def _quitar_salida_si_existe(ingreso):
    """
    Si el equipo tenía una salida y el técnico lo regresa a reparación/diagnóstico,
    eliminamos la salida (el equipo vuelve al taller). Se conserva el resto.
    """
    salida = getattr(ingreso, 'salida', None)
    if salida is not None:
        salida.delete()


def _crear_o_actualizar_salida(request, ingreso, estado_rep):
    """
    Crea (o actualiza) la SalidaEquipo según el resultado.


    NO cobra nada aquí: deja los valores monetarios en cero/sin pago. El cobro
    y el detalle financiero se gestionan desde el módulo de Pagos/Salidas en
    escritorio. El técnico solo declara el resultado técnico.
    """
    positiva = (estado_rep == 'pendiente_retiro')
    salida = getattr(ingreso, 'salida', None)

    if salida is None:
        salida = SalidaEquipo(
            ingreso=ingreso,
            fecha_salida=date.today(),
            estado_reparacion=estado_rep,
            metodo_pago_final='sin_pago',
            cliente_recibe_conforme='si' if positiva else 'no',
            registrado_por=request.user,
            # El técnico que marca la salida desde su celular ES quien reparó:
            # por eso él asume la responsabilidad y suma/resta puntos.
            tecnico_reparo=request.user,
        )
    else:
        salida.estado_reparacion = estado_rep
        salida.cliente_recibe_conforme = 'si' if positiva else 'no'
        # Si aún no tenía técnico asignado, lo toma quien marca la salida.
        if salida.tecnico_reparo_id is None:
            salida.tecnico_reparo = request.user

    # Guardamos primero el reporte en el ingreso…
    ingreso.save(update_fields=['reporte_tecnico', 'reporte_por',
                                'reporte_actualizado', 'actualizado'])
    # …y luego la salida (su save() sincroniza ingreso.estado = 'entregado').
    salida.save()

    # Reflejar el subestado "entregado" en el ingreso para que coincida
    # con lo que muestra el resto del sistema.
    if estado_rep == 'pendiente_retiro':
        ingreso.subestado_entregado = 'con_solucion'
    elif estado_rep == 'cliente_no_acepta':
        ingreso.subestado_entregado = 'no_quiso_reparar'
    else:
        ingreso.subestado_entregado = 'sin_solucion'

    ingreso.save(update_fields=['subestado_entregado', 'actualizado'])
