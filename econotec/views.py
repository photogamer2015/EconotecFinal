"""
Vistas principales de Econotec.
Maneja: bienvenida, ayuda, ingresos de equipos, salidas y clientes.
"""
from datetime import date
from decimal import Decimal as D
from io import BytesIO
import json
import unicodedata

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST

from .forms import (
    ClienteForm, IngresoEquipoForm, SalidaEquipoForm,
)
from .busqueda import (
    filtrar_objetos_normalizado,
    texto_cliente_busqueda,
    texto_ingreso_busqueda,
    texto_salida_busqueda,
    total_resultados,
)
from .models import (
    Cliente, IngresoEquipo, SalidaEquipo, Abono, SEDES_EQUIPOS,
    UsuarioActividad, NotificacionAsesora,
)
from .permisos import admin_requerido, tecnico_requerido, es_admin, es_asesor, es_tecnico
from .gamificacion import (
    SALIDA_BUENA_ESTADOS,
    SALIDA_GARANTIA_ESTADOS,
    SALIDA_MALA_ESTADOS,
    calcular_puntaje_gamificacion,
)
from .alertas import (
    equipos_demorados_qs,
    salidas_bodegaje_qs,
    dias_en_taller,
    dias_desde_salida,
    whatsapp_link_demora,
    whatsapp_link_equipo_listo,
    whatsapp_link_bodegaje,
    whatsapp_link_hoja_ingreso,
    UMBRAL_DIAS_DIAGNOSTICO,
    UMBRAL_DIAS_BODEGAJE,
    COSTO_BODEGAJE_DIA,
)


def _sincronizar_notificacion_asesora(form, salida, user):
    """Crea/actualiza la notificación interna para cobros pendientes de asesora."""
    tipos_controlados = [
        NotificacionAsesora.TIPO_FALLOS_ADICIONALES,
        NotificacionAsesora.TIPO_REVISION_PENDIENTE,
        NotificacionAsesora.TIPO_SALDO_RETIRO,
    ]
    tipo = getattr(form, 'notificacion_asesora_tipo', None)
    valor = getattr(form, 'notificacion_asesora_valor', D('0.00')) or D('0.00')

    NotificacionAsesora.objects.filter(
        salida=salida,
        tipo__in=[tipo_actual for tipo_actual in tipos_controlados if tipo_actual != tipo],
    ).delete()

    if not tipo or valor <= 0:
        NotificacionAsesora.objects.filter(
            salida=salida,
            tipo__in=tipos_controlados,
        ).delete()
        return

    asesora = form.cleaned_data.get('asesora_notificacion')
    if not asesora:
        return

    mensaje = (form.cleaned_data.get('mensaje_notificacion') or '').strip()
    if not mensaje:
        mensaje_default = getattr(form, 'notificacion_asesora_mensaje_default', '')
        mensaje = mensaje_default.format(
            codigo=salida.ingreso.codigo_equipo,
            valor=valor,
            cliente=salida.ingreso.cliente.nombres,
        )

    NotificacionAsesora.objects.update_or_create(
        salida=salida,
        tipo=tipo,
        defaults={
            'ingreso': salida.ingreso,
            'asesora': asesora,
            'creado_por': user,
            'valor_acordado': valor,
            'mensaje': mensaje,
            'leida': False,
            'leida_en': None,
        }
    )


def _normalizar_comparacion(valor):
    texto = ' '.join((valor or '').strip().casefold().split())
    texto = unicodedata.normalize('NFD', texto)
    return ''.join(c for c in texto if unicodedata.category(c) != 'Mn')


def _identidad_equipo_normalizada(datos_ingreso):
    tipo = _normalizar_comparacion(datos_ingreso.get('tipo_equipo'))
    tipo_otro = _normalizar_comparacion(datos_ingreso.get('tipo_equipo_otro')) if tipo == 'otro' else ''
    return (
        tipo,
        tipo_otro,
        _normalizar_comparacion(datos_ingreso.get('marca')),
        _normalizar_comparacion(datos_ingreso.get('modelo_serie')),
    )


def _identidad_equipo_de_ingreso(ingreso):
    return _identidad_equipo_normalizada({
        'tipo_equipo': ingreso.tipo_equipo,
        'tipo_equipo_otro': ingreso.tipo_equipo_otro,
        'marca': ingreso.marca,
        'modelo_serie': ingreso.modelo_serie,
    })


def _equipos_duplicados_para_cliente(cliente, datos_ingreso, excluir_pk=None):
    modelo = _normalizar_comparacion(datos_ingreso.get('modelo_serie'))

    if not cliente or not modelo:
        return []

    qs = cliente.ingresos.order_by('-creado')
    if excluir_pk:
        qs = qs.exclude(pk=excluir_pk)

    duplicados = []
    for equipo in qs:
        modelo_existente = _normalizar_comparacion(equipo.modelo_serie)
        if modelo_existente == modelo:
            duplicados.append(equipo)

    return duplicados


def _equipo_duplicado_para_cliente(cliente, datos_ingreso, excluir_pk=None):
    duplicados = _equipos_duplicados_para_cliente(cliente, datos_ingreso, excluir_pk)
    return duplicados[0] if duplicados else None


def _confirmo_mismo_equipo_cliente(request):
    return request.POST.get('confirmar_mismo_equipo_cliente') == '1'


# ═════════════════════════════════════════════════════════════════
# Páginas base
# ═════════════════════════════════════════════════════════════════


def ingresos_de_equipo_qs():
    return IngresoEquipo.objects.filter(sede__in=SEDES_EQUIPOS)


def home(request):
    if request.user.is_authenticated:
        return redirect('econotec:bienvenida')
    return redirect('login')


@login_required
def bienvenida(request):
    """Dashboard de inicio."""
    hoy = date.today()
    mes_actual = hoy.month
    ano_actual = hoy.year
    ingresos_equipos = ingresos_de_equipo_qs()

    stats = {
        'total_ingresos': ingresos_equipos.count(),
        'ingresos_mes': ingresos_equipos.filter(
            fecha_ingreso__year=ano_actual, fecha_ingreso__month=mes_actual,
        ).count(),
        'total_salidas': SalidaEquipo.objects.count(),
        'salidas_mes': SalidaEquipo.objects.filter(
            fecha_salida__year=ano_actual, fecha_salida__month=mes_actual,
        ).count(),
        'total_clientes': Cliente.objects.count(),
        'pendientes_retiro': ingresos_equipos.filter(
            estado__in=['ingresado', 'en_reparacion'],
            salida__isnull=True,
        ).count() + SalidaEquipo.objects.filter(
            ingreso__sede__in=SEDES_EQUIPOS,
            estado_reparacion='pendiente_retiro',
        ).count(),
    }
    salidas_equipos = SalidaEquipo.objects.filter(ingreso__sede__in=SEDES_EQUIPOS)
    ingresos_por_sede = dict(
        ingresos_equipos
        .values('sede')
        .annotate(total=Count('id'))
        .values_list('sede', 'total')
    )
    salidas_por_sede = dict(
        salidas_equipos
        .values('ingreso__sede')
        .annotate(total=Count('id'))
        .values_list('ingreso__sede', 'total')
    )
    resumen_movimientos = {
        'ingresos': {
            'guayaquil': ingresos_por_sede.get('guayaquil', 0),
            'quito': ingresos_por_sede.get('quito', 0),
            'total': stats['total_ingresos'],
        },
        'salidas': {
            'guayaquil': salidas_por_sede.get('guayaquil', 0),
            'quito': salidas_por_sede.get('quito', 0),
            'total': salidas_equipos.count(),
        },
    }
    resumen_movimientos['total_general'] = (
        resumen_movimientos['ingresos']['total'] + resumen_movimientos['salidas']['total']
    )

    # ── Equipos más ingresados ──────────────────────────────
    from .models import TIPOS_EQUIPO

    qs_equipos = (
        ingresos_equipos.values('tipo_equipo', 'tipo_equipo_otro')
        .annotate(total=Count('id'))
        .order_by('-total')
    )
    
    dict_tipos = dict(TIPOS_EQUIPO)
    equipos_stats = []
    
    # We might have multiple "otro" with different text, they are already grouped by (tipo_equipo, tipo_equipo_otro)
    for row in qs_equipos:
        if row['tipo_equipo'] == 'otro' and row['tipo_equipo_otro']:
            nombre = row['tipo_equipo_otro'].title()
        else:
            nombre = dict_tipos.get(row['tipo_equipo'], row['tipo_equipo']).title()
            
        # To avoid duplicates if casing differs in 'otro'
        found = False
        for stat in equipos_stats:
            if stat['nombre'].lower() == nombre.lower():
                stat['total'] += row['total']
                found = True
                break
        if not found:
            equipos_stats.append({'nombre': nombre, 'total': row['total']})
            
    # Re-sort and take top 5
    equipos_stats.sort(key=lambda x: x['total'], reverse=True)
    equipos_top = equipos_stats[:5]

    # ── Alertas: dos tipos independientes ────────────────────────
    es_admin_user = request.user.is_superuser or request.user.groups.filter(
        name__in=['Administradores', 'Admin']
    ).exists()

    # 1. Equipos demorados en diagnóstico (4+ días sin diagnosticar)
    demorados_qs = equipos_demorados_qs(usuario=None)

    demorados = []
    for ing in demorados_qs[:10]:
        demorados.append({
            'ingreso': ing,
            'dias': dias_en_taller(ing, hoy=hoy),
            'wa_link': whatsapp_link_demora(ing),
        })

    # 2. Salidas con bodegaje pendiente (5+ días sin que el cliente venga)
    bodegaje_qs = salidas_bodegaje_qs(usuario=None)

    bodegajes = []
    for sal in bodegaje_qs[:10]:
        bod = sal.calcular_bodegaje(hoy=hoy)
        bodegajes.append({
            'salida': sal,
            'ingreso': sal.ingreso,
            'dias_desde_salida': dias_desde_salida(sal, hoy=hoy),
            'bodegaje_dias': bod['dias'],
            'bodegaje_monto': bod['monto'],
            'wa_link': whatsapp_link_bodegaje(sal),
        })

    # 1b. Diagnósticos silenciados
    from datetime import timedelta as _td
    fecha_limite_diag = date.today() - _td(days=UMBRAL_DIAS_DIAGNOSTICO)
    qs_diag_silenciados = (
        IngresoEquipo.objects
        .select_related('cliente', 'tecnico_encargado')
        .filter(fecha_ingreso__lte=fecha_limite_diag)
        .filter(estado='ingresado')
        .filter(salida__isnull=True)
        .filter(diagnostico_silenciado=True)
    )
    # No filtramos por usuario para los técnicos, ven todo
    
    demorados_silenciados = []
    for ing in qs_diag_silenciados:
        demorados_silenciados.append({
            'ingreso': ing,
            'dias': dias_en_taller(ing, hoy=hoy),
        })

    # 2b. Bodegajes silenciados
    fecha_limite_bod = date.today() - _td(days=UMBRAL_DIAS_BODEGAJE)
    qs_bod_silenciados = (
        SalidaEquipo.objects
        .select_related('ingreso', 'ingreso__cliente', 'ingreso__tecnico_encargado', 'tecnico_reparo')
        .filter(fecha_salida__lte=fecha_limite_bod)
        .filter(fecha_retiro_real__isnull=True)
        .filter(bodegaje_silenciado=True)
    )
    # No filtramos por usuario para los técnicos, ven todo
    
    bodegajes_silenciados = []
    for sal in qs_bod_silenciados:
        bod = sal.calcular_bodegaje(hoy=hoy)
        bodegajes_silenciados.append({
            'salida': sal,
            'ingreso': sal.ingreso,
            'dias_desde_salida': dias_desde_salida(sal, hoy=hoy),
            'bodegaje_dias': bod['dias'],
            'bodegaje_monto': bod['monto'],
        })
    # ── Top Clientes ──────────────────────────────
    clientes_top = (
        Cliente.objects
        .annotate(total_ingresos=Count('ingresos', filter=Q(ingresos__sede__in=SEDES_EQUIPOS)))
        .filter(total_ingresos__gt=0)
        .order_by('-total_ingresos')[:5]
    )

    ctx = {
        'usuario': request.user,
        'es_admin': es_admin_user,
        'stats': stats,
        'resumen_movimientos': resumen_movimientos,
        'equipos_top': equipos_top,
        'clientes_top': clientes_top,
        'demorados': demorados,
        'demorados_total': demorados_qs.count(),
        'demorados_silenciados': demorados_silenciados,
        'bodegajes': bodegajes,
        'bodegajes_total': bodegaje_qs.count(),
        'bodegajes_silenciados': bodegajes_silenciados,
        'total_silenciados': len(demorados_silenciados) + len(bodegajes_silenciados),
        'umbral_diagnostico': UMBRAL_DIAS_DIAGNOSTICO,
        'umbral_bodegaje': UMBRAL_DIAS_BODEGAJE,
        'costo_bodegaje_dia': COSTO_BODEGAJE_DIA,
    }
    return render(request, 'bienvenida.html', ctx)

@login_required
def dashboard_details(request, tipo):
    """Devuelve el HTML parcial para el modal del dashboard."""
    hoy = date.today()
    mes_actual = hoy.month
    ano_actual = hoy.year

    titulo = ""
    columnas = []
    filas = []

    link_ver_todos = ""

    def estado_ingreso_para_modal(ingreso):
        return ingreso.estado_visual_display

    sedes_dashboard = {
        'guayaquil': ('Guayaquil', 'G'),
        'quito': ('Quito', 'U'),
    }

    def dinero_modal(valor):
        if valor is None:
            return '—'
        return f'${valor:.2f}'

    if tipo == 'equipos_total':
        titulo = "Total de Equipos Ingresados"
        link_ver_todos = "/ingresos/"
        qs = ingresos_de_equipo_qs().select_related('cliente', 'salida').order_by('-fecha_ingreso')
        columnas = ['Código', 'Cliente', 'Equipo', 'Fecha Ingreso', 'Estado', 'Acción']
        for eq in qs:
            btn = f'<a href="/ingresos/{eq.pk}/" class="badge badge-ingresado" style="text-decoration:none; padding: 4px 8px;">Ver detallles</a>'
            filas.append([eq.codigo_equipo, eq.cliente.nombres, eq.tipo_equipo_display, eq.fecha_ingreso.strftime('%d/%m/%Y'), estado_ingreso_para_modal(eq), btn])

    elif tipo.startswith('ingresos_sede_'):
        sede = tipo.replace('ingresos_sede_', '', 1)
        sede_nombre, sede_codigo = sedes_dashboard.get(sede, ('Sede', ''))
        titulo = f"Ingresos de Equipo {sede_nombre} ({sede_codigo})"
        qs = (
            ingresos_de_equipo_qs()
            .select_related('cliente', 'tecnico_encargado', 'salida')
            .filter(sede=sede)
            .order_by('-fecha_ingreso', '-creado')
        )
        columnas = ['Código', 'Cliente', 'Equipo', 'Fecha', 'Técnico', 'Estado', 'Valor', 'Acción']
        for eq in qs:
            btn = f'<a href="/ingresos/{eq.pk}/" class="badge badge-ingresado" style="text-decoration:none; padding: 4px 8px;">Ver detalle</a>'
            filas.append([
                eq.codigo_equipo,
                eq.cliente.nombres,
                f'{eq.tipo_equipo_display} — {eq.marca} {eq.modelo_serie_detalle}',
                eq.fecha_ingreso.strftime('%d/%m/%Y'),
                eq.tecnico_encargado_nombre or '—',
                estado_ingreso_para_modal(eq),
                dinero_modal(eq.valor_acordado),
                btn,
            ])

    elif tipo == 'ingresos_mes':
        titulo = f"Ingresos del Mes ({hoy.strftime('%B %Y').capitalize()})"
        link_ver_todos = "/ingresos/"
        qs = ingresos_de_equipo_qs().select_related('cliente', 'salida').filter(
            fecha_ingreso__year=ano_actual, fecha_ingreso__month=mes_actual
        ).order_by('-fecha_ingreso')
        columnas = ['Código', 'Cliente', 'Equipo', 'Fecha Ingreso', 'Estado', 'Acción']
        for eq in qs:
            btn = f'<a href="/ingresos/{eq.pk}/" class="badge badge-ingresado" style="text-decoration:none; padding: 4px 8px;">Ver detallles</a>'
            filas.append([eq.codigo_equipo, eq.cliente.nombres, eq.tipo_equipo_display, eq.fecha_ingreso.strftime('%d/%m/%Y'), estado_ingreso_para_modal(eq), btn])

    elif tipo == 'pendientes':
        titulo = "Equipos Pendientes en Taller"
        link_ver_todos = "/ingresos/"
        ingresos = list(ingresos_de_equipo_qs().select_related('cliente').filter(
            estado__in=['ingresado', 'en_reparacion'],
            salida__isnull=True,
        ))
        salidas = list(SalidaEquipo.objects.select_related('ingreso__cliente').filter(
            ingreso__sede__in=SEDES_EQUIPOS,
            estado_reparacion='pendiente_retiro',
        ))
        columnas = ['Código', 'Cliente', 'Equipo', 'Fase', 'Estado', 'Acción']
        
        for eq in ingresos:
            btn = f'<a href="/ingresos/{eq.pk}/" class="badge badge-ingresado" style="text-decoration:none; padding: 4px 8px;">Ver detallles</a>'
            filas.append([eq.codigo_equipo, eq.cliente.nombres, eq.tipo_equipo_display, 'En Proceso', estado_ingreso_para_modal(eq), btn])
        for sal in salidas:
            btn = f'<a href="/ingresos/{sal.ingreso.pk}/" class="badge badge-ingresado" style="text-decoration:none; padding: 4px 8px;">Ver detallles</a>'
            filas.append([sal.ingreso.codigo_equipo, sal.ingreso.cliente.nombres, sal.ingreso.tipo_equipo_display, 'Terminado', 'Listo (Pendiente Retiro)', btn])

    elif tipo == 'salidas_mes':
        titulo = f"Salidas del Mes ({hoy.strftime('%B %Y').capitalize()})"
        link_ver_todos = "/salidas/"
        qs = SalidaEquipo.objects.select_related('ingreso__cliente').filter(
            ingreso__sede__in=SEDES_EQUIPOS,
            fecha_salida__year=ano_actual, fecha_salida__month=mes_actual
        ).order_by('-fecha_salida')
        columnas = ['Código', 'Cliente', 'Equipo', 'Fecha Salida', 'Estado Reparación', 'Acción']
        for sal in qs:
            btn = f'<a href="/salidas/{sal.pk}/imprimir/" class="badge badge-entregado" style="text-decoration:none; padding: 4px 8px;">Ver PDF</a>'
            filas.append([sal.ingreso.codigo_equipo, sal.ingreso.cliente.nombres, sal.ingreso.tipo_equipo_display, sal.fecha_salida.strftime('%d/%m/%Y'), sal.get_estado_reparacion_display(), btn])

    elif tipo.startswith('salidas_sede_'):
        sede = tipo.replace('salidas_sede_', '', 1)
        sede_nombre, sede_codigo = sedes_dashboard.get(sede, ('Sede', ''))
        titulo = f"Salidas de Equipo {sede_nombre} ({sede_codigo})"
        qs = (
            SalidaEquipo.objects
            .select_related('ingreso', 'ingreso__cliente', 'tecnico_reparo')
            .filter(ingreso__sede=sede)
            .order_by('-fecha_salida', '-creado')
        )
        columnas = ['Código', 'Cliente', 'Equipo', 'Fecha', 'Técnico', 'Estado salida', 'Cobrado', 'Acción']
        for sal in qs:
            btn = f'<a href="/salidas/{sal.pk}/imprimir/" class="badge badge-entregado" style="text-decoration:none; padding: 4px 8px;">Ver PDF</a>'
            filas.append([
                sal.ingreso.codigo_equipo,
                sal.ingreso.cliente.nombres,
                f'{sal.ingreso.tipo_equipo_display} — {sal.ingreso.marca} {sal.ingreso.modelo_serie_detalle}',
                sal.fecha_salida.strftime('%d/%m/%Y'),
                sal.tecnico_reparo.get_username() if sal.tecnico_reparo else '—',
                sal.get_estado_reparacion_display(),
                dinero_modal(sal.valor_final_cobrado),
                btn,
            ])

    elif tipo == 'clientes':
        titulo = "Directorio de Clientes"
        link_ver_todos = ""
        qs = Cliente.objects.order_by('-id')
        columnas = ['Nombre / Razón Social', 'Cédula / RUC', 'WhatsApp', 'Email']
        for cli in qs:
            filas.append([cli.nombres, cli.cedula, cli.whatsapp or '-', cli.correo or '-'])

    ctx = {
        'titulo': titulo,
        'columnas': columnas,
        'filas': filas,
        'link_ver_todos': link_ver_todos,
    }
    return render(request, 'includes/dashboard_modal_content.html', ctx)

@login_required
def ayuda(request):
    return render(request, 'ayuda.html')


@login_required
def reproductor_musica(request):
    """Mini-reproductor de música de YouTube para técnicos."""
    return render(request, 'musica.html')


# ═════════════════════════════════════════════════════════════════
# Ingreso de Equipos
# ═════════════════════════════════════════════════════════════════

@tecnico_requerido
def ingreso_menu(request):
    """Menú de ingresos: registrar nuevo / ver lista."""
    ingresos_equipos = ingresos_de_equipo_qs()
    total = ingresos_equipos.count()
    pendientes = ingresos_equipos.filter(
        estado__in=['ingresado', 'en_reparacion'],
        salida__isnull=True,
    ).count() + SalidaEquipo.objects.filter(
        ingreso__sede__in=SEDES_EQUIPOS,
        estado_reparacion='pendiente_retiro',
    ).count()
    pendientes_valor = _ingresos_pendientes_valor_qs().count()
    return render(request, 'ingresos/menu.html', {
        'total': total,
        'pendientes': pendientes,
        'pendientes_valor': pendientes_valor,
    })


def _ingresos_pendientes_valor_qs():
    return (
        IngresoEquipo.objects
        .filter(sede__in=['guayaquil', 'quito'], valor_acordado__isnull=True)
        .exclude(estado='entregado')
    )


@tecnico_requerido
@require_GET
def cliente_buscar_por_cedula(request):
    """
    Endpoint AJAX: busca un cliente por cédula y devuelve sus datos en JSON.
    Lo usa el formulario de ingreso para autocompletar nombre, WhatsApp, correo
    y sector cuando el técnico escribe una cédula que ya existe en el sistema.

    Respuesta cuando existe el cliente:
        {"existe": true, "cliente": {...campos...}, "num_equipos_anteriores": N}
    Respuesta cuando NO existe:
        {"existe": false}
    """
    cedula = (request.GET.get('cedula') or '').strip()
    if not cedula:
        return JsonResponse({'existe': False})

    cliente = Cliente.objects.filter(cedula=cedula).first()
    if not cliente:
        return JsonResponse({'existe': False})

    equipos_qs = cliente.ingresos.order_by('-creado')
    equipos_data = [
        {
            'id': eq.id, 
            'codigo': eq.codigo_equipo,
            'label': f"{eq.codigo_equipo} — {eq.marca} {eq.modelo_serie_detalle} ({eq.creado.strftime('%d/%m/%Y')})",
            'tipo_equipo': eq.tipo_equipo,
            'tipo_equipo_otro': eq.tipo_equipo_otro,
            'marca': eq.marca,
            'modelo_serie': eq.modelo_serie,
            'serie': eq.serie,
            'detalle_url': reverse('econotec:ingreso_detalle', args=[eq.pk]),
        }
        for eq in equipos_qs
    ]

    return JsonResponse({
        'existe': True,
        'cliente': {
            'nombres': cliente.nombres,
            'whatsapp': cliente.whatsapp,
            'correo': cliente.correo,
            'sector': cliente.sector,
            'sector_otro': cliente.sector_otro,
        },
        'equipos': equipos_data,
        'num_equipos_anteriores': equipos_qs.count(),
    })


@tecnico_requerido
@transaction.atomic
def ingreso_registrar(request):
    """Registra un nuevo ingreso.
    - La SEDE se toma de la sesión (la elegida en el login).
    - Si la cédula del cliente ya existe, se reutiliza.
    - El número de equipo es correlativo dentro de la sede (G1/U1...).
    """
    # La sede se toma de la sesión. Si no hay sede, mandamos al login.
    sede_actual = (request.session.get('sede_actual') or '').strip().lower()
    if sede_actual not in ('guayaquil', 'quito'):
        messages.error(request, 'Tu sesión no tiene una sede asignada. Vuelve a iniciar sesión.')
        return redirect('login')

    confirmar_mismo_equipo_cliente = (
        _confirmo_mismo_equipo_cliente(request) if request.method == 'POST' else False
    )

    if request.method == 'POST':
        cli_form = ClienteForm(request.POST, prefix='cli')
        ing_form = IngresoEquipoForm(request.POST, prefix='ing')

        cedula = (request.POST.get('cli-cedula') or '').strip()
        cliente_existente = Cliente.objects.filter(cedula=cedula).first() if cedula else None

        if cliente_existente:
            # Actualizar datos del cliente con la nueva info, si hay cambios
            cli_form_existente = ClienteForm(request.POST, prefix='cli', instance=cliente_existente)
            if ing_form.is_valid() and cli_form_existente.is_valid():
                duplicado = _equipo_duplicado_para_cliente(cliente_existente, ing_form.cleaned_data)
                if duplicado and not confirmar_mismo_equipo_cliente:
                    mensaje_duplicado = (
                        'ESTE EQUIPO YA SE ENCUENTRA REGISTRADO, POR FAVOR VERIFICA EN LA LISTA DE EQUIPOS.'
                    )
                    ing_form.add_error('modelo_serie', f'{mensaje_duplicado} Coincide con el equipo {duplicado.codigo_equipo}.')
                    messages.error(
                        request,
                        f'{mensaje_duplicado} Coincide con {duplicado.codigo_equipo}.'
                    )
                    cli_form = cli_form_existente
                else:
                    cliente = cli_form_existente.save()
                    ingreso = ing_form.save(commit=False)
                    ingreso.cliente = cliente
                    ingreso.sede = sede_actual           # ← sede de la sesión
                    ingreso.registrado_por = request.user
                    ingreso.save()
                    messages.success(
                        request,
                        f'Equipo {ingreso.codigo_equipo} ingresado para {cliente.nombres}.'
                    )
                    if duplicado and confirmar_mismo_equipo_cliente:
                        messages.info(
                            request,
                            f'Reingreso confirmado: mismo cliente y mismo equipo que {duplicado.codigo_equipo}.'
                        )
                    return redirect('econotec:ingreso_detalle', pk=ingreso.pk)
            else:
                cli_form = cli_form_existente
        else:
            if cli_form.is_valid() and ing_form.is_valid():
                cliente = cli_form.save()
                ingreso = ing_form.save(commit=False)
                ingreso.cliente = cliente
                ingreso.sede = sede_actual           # ← sede de la sesión
                ingreso.registrado_por = request.user
                ingreso.save()
                messages.success(
                    request,
                    f'Equipo {ingreso.codigo_equipo} ingresado para {cliente.nombres}.'
                )
                return redirect('econotec:ingreso_detalle', pk=ingreso.pk)

    else:
        cli_initial = {
            'cedula': request.GET.get('cedula', ''),
            'nombres': request.GET.get('nombres', ''),
            'whatsapp': request.GET.get('whatsapp', ''),
            'correo': request.GET.get('correo', ''),
            'sector': request.GET.get('sector', ''),
            'sector_otro': request.GET.get('sector_otro', ''),
        }
        
        # Validar tipo_equipo contra las opciones disponibles
        from .models import TIPOS_EQUIPO
        tipo_get = request.GET.get('tipo_equipo', '').lower()
        tipos_validos = [t[0] for t in TIPOS_EQUIPO]
        if tipo_get and tipo_get not in tipos_validos:
            tipo_get = 'otro'
            
        ing_initial = {
            'fecha_ingreso': timezone.now().date(),
            'tecnico_encargado': request.user if request.user.groups.filter(name='Tecnicos').exists() else None,
            'tipo_equipo': tipo_get,
            'tipo_equipo_otro': request.GET.get('tipo_equipo_otro', ''),
            'marca': request.GET.get('marca', ''),
            'modelo_serie': request.GET.get('modelo_serie', ''),
            'serie': request.GET.get('serie', ''),
            'problema_reportado': request.GET.get('problema_reportado', ''),
            'accesorios_entregados': request.GET.get('accesorios_entregados', ''),
            'numero_factura': request.GET.get('numero_factura', ''),
            'asesor_comercial': request.GET.get('asesor_comercial', ''),
            'reporte_tecnico': request.GET.get('reporte_tecnico', ''),
            'diagnostico_inmediato': request.GET.get('diagnostico_inmediato', 'no'),
            'valor_diagnostico': request.GET.get('valor_diagnostico', '0.00'),
            'valor_acordado': request.GET.get('valor_acordado', ''),
            'abono_anticipo': request.GET.get('abono_anticipo', '0.00'),
        }
        cli_form = ClienteForm(prefix='cli', initial=cli_initial)
        ing_form = IngresoEquipoForm(prefix='ing', initial=ing_initial)

    # El siguiente código se calcula dentro de la sede actual
    from .models import SEDE_PREFIJOS
    siguiente_numero = IngresoEquipo.siguiente_numero_equipo(sede_actual)
    siguiente_codigo = f"{SEDE_PREFIJOS.get(sede_actual, '?')}{siguiente_numero}"

    return render(request, 'ingresos/form.html', {
        'cli_form': cli_form,
        'ing_form': ing_form,
        'modo': 'registrar',
        'titulo': 'Nueva Solicitud de Ingreso',
        'siguiente_numero': siguiente_numero,
        'siguiente_codigo': siguiente_codigo,
        'confirmar_mismo_equipo_cliente': confirmar_mismo_equipo_cliente,
    })


@tecnico_requerido
@transaction.atomic
def ingreso_editar(request, pk):
    """Edita un ingreso existente."""
    ingreso = get_object_or_404(IngresoEquipo, pk=pk)
    if ingreso.retirado_por_cliente:
        messages.warning(
            request,
            f'Ya este equipo fue retirado por el cliente. '
            f'La hoja de ingreso {ingreso.codigo_equipo} queda cerrada y no se puede editar.'
        )
        return redirect('econotec:ingreso_detalle', pk=ingreso.pk)

    identidad_original = _identidad_equipo_de_ingreso(ingreso)
    confirmar_mismo_equipo_cliente = (
        _confirmo_mismo_equipo_cliente(request) if request.method == 'POST' else False
    )

    # Mapeo subestado_entregado → estado_reparacion de SalidaEquipo
    _MAPA_SALIDA = {
        'con_solucion': {
            'estado_reparacion': 'pendiente_retiro',
            'cliente_recibe_conforme': 'si',
        },
        'sin_solucion': {
            'estado_reparacion': 'no_reparable',
            'cliente_recibe_conforme': 'no',
        },
        'no_quiso_reparar': {
            'estado_reparacion': 'cliente_no_acepta',
            'cliente_recibe_conforme': 'no',
        },
        'pendiente_retiro': {
            'estado_reparacion': 'pendiente_retiro',
            'cliente_recibe_conforme': 'si',
        },
    }

    if request.method == 'POST':
        cli_form = ClienteForm(request.POST, prefix='cli', instance=ingreso.cliente)
        ing_form = IngresoEquipoForm(request.POST, prefix='ing', instance=ingreso)
        if cli_form.is_valid() and ing_form.is_valid():
            cliente_editado = cli_form.save(commit=False)
            identidad_sin_cambios = (
                _identidad_equipo_normalizada(ing_form.cleaned_data)
                == identidad_original
            )
            duplicado = None
            if not identidad_sin_cambios:
                duplicado = _equipo_duplicado_para_cliente(
                    cliente_editado,
                    ing_form.cleaned_data,
                    excluir_pk=ingreso.pk,
                )
            if duplicado and not confirmar_mismo_equipo_cliente:
                mensaje_duplicado = (
                    'ESTE EQUIPO YA SE ENCUENTRA REGISTRADO, POR FAVOR VERIFICA EN LA LISTA DE EQUIPOS.'
                )
                ing_form.add_error('modelo_serie', f'{mensaje_duplicado} Coincide con el equipo {duplicado.codigo_equipo}.')
                messages.error(
                    request,
                    f'{mensaje_duplicado} Coincide con {duplicado.codigo_equipo}.'
                )
                return render(request, 'ingresos/form.html', {
                    'cli_form': cli_form,
                    'ing_form': ing_form,
                    'modo': 'editar',
                    'titulo': f'Editar equipo {ingreso.codigo_equipo}',
                    'siguiente_numero': ingreso.numero_equipo,
                    'siguiente_codigo': ingreso.codigo_equipo,
                    'ingreso': ingreso,
                    'confirmar_mismo_equipo_cliente': confirmar_mismo_equipo_cliente,
                })

            estado_nuevo = ing_form.cleaned_data.get('estado')
            valor_acordado_nuevo = ing_form.cleaned_data.get('valor_acordado')
            if estado_nuevo == 'entregado' and valor_acordado_nuevo is None:
                ing_form.add_error(
                    'valor_acordado',
                    'Por favor registra un valor acordado para registrar la salida.'
                )
                return render(request, 'ingresos/form.html', {
                    'cli_form': cli_form,
                    'ing_form': ing_form,
                    'modo': 'editar',
                    'titulo': f'Editar equipo {ingreso.codigo_equipo}',
                    'siguiente_numero': ingreso.numero_equipo,
                    'siguiente_codigo': ingreso.codigo_equipo,
                    'ingreso': ingreso,
                    'confirmar_mismo_equipo_cliente': confirmar_mismo_equipo_cliente,
                })

            cliente_editado.save()
            ing_form.save()

            # ── Auto-crear Salida si estado=entregado + subestado definido ──
            subestado = ingreso.subestado_entregado
            if ingreso.estado == 'entregado' and subestado in _MAPA_SALIDA:
                datos_salida = _MAPA_SALIDA[subestado]
                salida_existente = getattr(ingreso, 'salida', None)
                if salida_existente is None:
                    # Calcular saldo pendiente para sugerir el valor final
                    saldo = ingreso.diferencia
                    SalidaEquipo.objects.create(
                        ingreso=ingreso,
                        fecha_salida=date.today(),
                        estado_reparacion=datos_salida['estado_reparacion'],
                        cliente_recibe_conforme=datos_salida['cliente_recibe_conforme'],
                        valor_final_cobrado=saldo if saldo > 0 else 0,
                        metodo_pago_final='efectivo' if saldo > 0 else 'sin_pago',
                        registrado_por=request.user,
                    )
                    if subestado == 'con_solucion':
                        etiqueta = 'Con solución — cliente conforme'
                    elif subestado == 'sin_solucion':
                        etiqueta = 'Sin solución — no se pudo reparar'
                    elif subestado == 'pendiente_retiro':
                        etiqueta = 'Pendiente de retiro'
                    else:
                        etiqueta = 'Sin reparación — cliente no quiso repararlo'
                    
                    messages.success(
                        request,
                        f'✅ Equipo {ingreso.codigo_equipo} actualizado. '
                        f'Salida registrada automáticamente: {etiqueta}.'
                    )
                else:
                    messages.success(request, f'Equipo {ingreso.codigo_equipo} actualizado.')
            else:
                messages.success(request, f'Equipo {ingreso.codigo_equipo} actualizado.')

            return redirect('econotec:ingreso_detalle', pk=ingreso.pk)
    else:
        cli_form = ClienteForm(prefix='cli', instance=ingreso.cliente)
        ing_form = IngresoEquipoForm(prefix='ing', instance=ingreso)

    return render(request, 'ingresos/form.html', {
        'cli_form': cli_form,
        'ing_form': ing_form,
        'ingreso': ingreso,
        'modo': 'editar',
        'titulo': f'Editar Equipo {ingreso.codigo_equipo}',
        'siguiente_numero': ingreso.numero_equipo,
        'siguiente_codigo': ingreso.codigo_equipo,
        'confirmar_mismo_equipo_cliente': confirmar_mismo_equipo_cliente,
    })


@tecnico_requerido
def ingreso_lista(request):
    """Listado de ingresos con filtros.
    Por defecto se filtra por la sede actual de la sesión, pero el usuario
    puede ver "Todas" o cambiar entre Guayaquil/Quito con el filtro.
    """
    q = (request.GET.get('q') or '').strip()
    estado = (request.GET.get('estado') or '').strip()
    tipo = (request.GET.get('tipo') or '').strip()
    valor = (request.GET.get('valor') or '').strip()

    # Filtro por sede:
    # - Si el querystring trae explícitamente sede=todas → no filtrar
    # - Si trae sede=guayaquil/quito → filtrar por esa
    # - Si NO viene en el querystring → usar la sede de la sesión
    sede_sesion = (request.session.get('sede_actual') or '').strip().lower()
    if 'sede' in request.GET:
        sede_filtro = (request.GET.get('sede') or '').strip().lower()
    else:
        sede_filtro = sede_sesion

    qs = (ingresos_de_equipo_qs()
          .select_related('cliente', 'registrado_por', 'salida')
          .prefetch_related('abonos'))

    if sede_filtro in ('guayaquil', 'quito'):
        qs = qs.filter(sede=sede_filtro)
    # si sede_filtro es 'todas' o vacío → no se filtra

    estados_salida_filtro = {
        'salida_pendiente_retiro': 'pendiente_retiro',
        'salida_entregado_cliente': 'retirado',
        'salida_cliente_no_acepta': 'cliente_no_acepta',
        'salida_no_reparable': 'no_reparable',
        'salida_garantia': 'garantia',
    }

    subestados_reparacion_filtro = {
        'reparacion_en_reparacion': 'en_reparacion',
        'espera_cliente': 'espera_cliente',
        'espera_repuesto': 'espera_repuesto',
    }

    if estado:
        if estado in subestados_reparacion_filtro:
            qs = qs.filter(
                estado='en_reparacion',
                subestado_reparacion=subestados_reparacion_filtro[estado],
            )
        elif estado == 'con_salida':
            qs = qs.filter(salida__isnull=False)
        elif estado in estados_salida_filtro:
            qs = qs.filter(salida__estado_reparacion=estados_salida_filtro[estado])
        else:
            qs = qs.filter(estado=estado)
    if tipo:
        qs = qs.filter(tipo_equipo=tipo)

    if valor == 'pendiente':
        qs = qs.filter(
            sede__in=['guayaquil', 'quito'],
            valor_acordado__isnull=True,
        ).exclude(estado='entregado')
    elif valor == 'con_valor':
        qs = qs.filter(valor_acordado__isnull=False)

    tecnico_filtro = (request.GET.get('tecnico') or '').strip()
    registrador_filtro = (request.GET.get('registrador') or '').strip()
    asesor_filtro = (request.GET.get('asesor') or '').strip()

    if tecnico_filtro.isdigit():
        qs = qs.filter(tecnico_encargado_id=tecnico_filtro)
    if registrador_filtro.isdigit():
        qs = qs.filter(registrado_por_id=registrador_filtro)
    if asesor_filtro:
        qs = qs.filter(asesor_comercial=asesor_filtro)

    qs = filtrar_objetos_normalizado(qs, q, texto_ingreso_busqueda)

    from django.contrib.auth import get_user_model
    User = get_user_model()
    usuarios_all = User.objects.filter(is_active=True).order_by('first_name', 'username')
    from .forms import _queryset_asesores
    asesores_qs = _queryset_asesores()
    asesores_choices = [f'{u.first_name} {u.last_name}'.strip() or u.username for u in asesores_qs]

    estados_filtro = [
        ('', '— Estado —'),
        ('ingresado', 'Ingresado / En diagnóstico'),
        ('en_reparacion', 'En reparación (Todos)'),
        ('reparacion_en_reparacion', '   ↳ En reparación'),
        ('espera_cliente', '   ↳ En reparación - Cliente'),
        ('espera_repuesto', '   ↳ En reparación - Repuestos'),
        ('entregado', 'Entregado al cliente (Ingreso)'),
        ('garantia', 'Garantía (Ingreso)'),
        ('con_salida', 'Salida registrada (Todos)'),
        ('salida_pendiente_retiro', '   ↳ Reparado - pendiente de retiro'),
        ('salida_entregado_cliente', '   ↳ Entregado / retirado por cliente'),
        ('salida_cliente_no_acepta', '   ↳ Cliente no quiso reparar'),
        ('salida_no_reparable', '   ↳ No se pudo reparar'),
        ('salida_garantia', '   ↳ Salida por garantía'),
    ]

    return render(request, 'ingresos/lista.html', {
        'ingresos': qs,
        'q': q,
        'estado_filtro': estado,
        'tipo_filtro': tipo,
        'valor_filtro': valor,
        'sede_filtro': sede_filtro,
        'sede_sesion': sede_sesion,
        'tecnico_filtro': tecnico_filtro,
        'registrador_filtro': registrador_filtro,
        'asesor_filtro': asesor_filtro,
        'usuarios_all': usuarios_all,
        'asesores_choices': asesores_choices,
        'estados': estados_filtro,
        'tipos': IngresoEquipo._meta.get_field('tipo_equipo').choices,
        'total': total_resultados(qs),
    })


@tecnico_requerido
def ingreso_detalle(request, pk):
    """Vista de detalle de un ingreso con todas sus relaciones."""
    ingreso = get_object_or_404(
        IngresoEquipo.objects.select_related(
            'cliente',
            'registrado_por',
            'equipo_garantia',
            'valor_pendiente_reporte_por',
        ),
        pk=pk,
    )
    abonos = ingreso.abonos.all().order_by('-fecha', '-creado')
    salida = getattr(ingreso, 'salida', None)
    from .qr_utils import qr_data_uri_para_ingreso, url_hoja_movil
    return render(request, 'ingresos/detalle.html', {
        'ingreso': ingreso,
        'abonos': abonos,
        'salida': salida,
        'qr_data_uri': qr_data_uri_para_ingreso(request, ingreso, box_size=6),
        'qr_url': url_hoja_movil(request, ingreso),
        'wa_link': whatsapp_link_hoja_ingreso(request, ingreso),
    })


@admin_requerido
@require_POST
def ingreso_eliminar(request, pk):
    """Solo admin: eliminar ingreso (con confirmación)."""
    ingreso = get_object_or_404(IngresoEquipo, pk=pk)
    numero = ingreso.numero_equipo
    if hasattr(ingreso, 'salida'):
        messages.error(
            request,
            f'No se puede eliminar el equipo #{numero}: ya tiene una salida registrada. '
            'Elimina primero la salida.'
        )
        return redirect('econotec:ingreso_detalle', pk=ingreso.pk)
    ingreso.delete()
    messages.success(request, f'Equipo #{numero} eliminado.')
    return redirect('econotec:ingreso_lista')


# ═════════════════════════════════════════════════════════════════
# Ventas de Productos
# ═════════════════════════════════════════════════════════════════

@tecnico_requerido
def venta_menu(request):
    """Menú de ventas: registrar nueva / ver lista."""
    total = IngresoEquipo.objects.filter(sede='ventas').count()
    return render(request, 'ventas/menu.html', {
        'total': total,
    })


def _preparar_post_venta(post_data):
    """
    Completa los campos del formulario de ingreso que no se muestran en ventas.
    Ventas reutiliza IngresoEquipoForm, pero omite diagnóstico/técnico/estado
    en la pantalla; sin estos defaults el formulario puede fallar en silencio.
    """
    defaults_si_falta = {
        'ing-marca': 'N/A',
        'ing-modelo_serie': 'N/A',
        'ing-serie': '',
        'ing-tipo_equipo': 'otro',
        'ing-tipo_equipo_otro': '',
        'ing-accesorios_entregados': 'Ninguno',
        'ing-abono_anticipo': '0.00',
        'ing-anticipo_metodo': 'efectivo',
        'ing-anticipo_banco': '',
        'ing-anticipo_banco_otro': '',
        'ing-anticipo_tarjeta_app': '',
        'ing-anticipo_comprobante_url': '',
        'ing-anticipo_monto_1': '',
        'ing-anticipo_metodo_1': '',
        'ing-anticipo_banco_1': '',
        'ing-anticipo_monto_2': '',
        'ing-anticipo_metodo_2': '',
        'ing-anticipo_banco_2': '',
        'ing-equipo_garantia': '',
        'ing-equipo_garantia_manual': '',
        'ing-motivo_garantia': '',
    }
    for campo, valor in defaults_si_falta.items():
        if not post_data.get(campo):
            post_data[campo] = valor

    # El diagnóstico no aplica a ventas, pero IngresoEquipoForm exige el método.
    post_data['ing-diagnostico_inmediato'] = 'no'
    post_data['ing-valor_diagnostico'] = '0.00'
    post_data['ing-diagnostico_metodo'] = 'efectivo'
    post_data['ing-diagnostico_banco'] = ''
    post_data['ing-diagnostico_banco_otro'] = ''
    post_data['ing-diagnostico_tarjeta_app'] = ''
    post_data['ing-diagnostico_comprobante_url'] = ''
    post_data['ing-diagnostico_monto_1'] = ''
    post_data['ing-diagnostico_metodo_1'] = ''
    post_data['ing-diagnostico_banco_1'] = ''
    post_data['ing-diagnostico_monto_2'] = ''
    post_data['ing-diagnostico_metodo_2'] = ''
    post_data['ing-diagnostico_banco_2'] = ''

    # IngresoEquipoForm oculta la opción "entregado"; validamos como ingreso
    # normal y luego forzamos el estado final de venta antes de guardar.
    post_data['ing-estado'] = 'ingresado'
    post_data['ing-subestado_reparacion'] = ''
    post_data['ing-subestado_entregado'] = ''


def _configurar_form_venta(ing_form):
    ing_form.fields['tecnico_encargado'].required = True
    ing_form.fields['tecnico_encargado'].label = 'Técnico vendió'
    ing_form.fields['tecnico_encargado'].empty_label = '— Selecciona el técnico que vendió —'
    if 'equipo_garantia' in ing_form.fields:
        ing_form.fields['equipo_garantia'].required = False
    ing_form.fields['problema_reportado'].widget.attrs['placeholder'] = 'Ej.: 1 Tinta Epson Negra, 2 Cables USB'


@tecnico_requerido
@transaction.atomic
def venta_registrar(request):
    """Registra una nueva venta de producto."""
    if request.method == 'POST':
        post_data = request.POST.copy()
        _preparar_post_venta(post_data)

        cli_form = ClienteForm(post_data, prefix='cli')
        ing_form = IngresoEquipoForm(post_data, prefix='ing')
        _configurar_form_venta(ing_form)

        cedula = (post_data.get('cli-cedula') or '').strip()
        cliente_existente = Cliente.objects.filter(cedula=cedula).first() if cedula else None

        cliente = None
        venta = None

        if cliente_existente:
            cli_form_existente = ClienteForm(post_data, prefix='cli', instance=cliente_existente)
            if ing_form.is_valid() and cli_form_existente.is_valid():
                cliente = cli_form_existente.save()
                venta = ing_form.save(commit=False)
            else:
                cli_form = cli_form_existente # Pass the instance form so it doesn't show "Cedula exists" error
        else:
            if cli_form.is_valid() and ing_form.is_valid():
                cliente = cli_form.save()
                venta = ing_form.save(commit=False)

        if cliente and venta:
            venta.cliente = cliente
            venta.sede = 'ventas'
            venta.registrado_por = request.user
            venta.estado = 'entregado'
            venta.subestado_entregado = 'con_solucion'
            venta.save()

            messages.success(request, f'Venta {venta.codigo_equipo} registrada para {cliente.nombres}.')
            return redirect('econotec:venta_lista')
            
    else:
        cli_form = ClienteForm(prefix='cli')
        initial = {
            'fecha_ingreso': date.today(),
            'estado': 'entregado',
            'subestado_entregado': 'con_solucion', # Asumimos la venta está finalizada y entregada
            'diagnostico_inmediato': 'no',
            'accesorios_entregados': 'Ninguno',
            'marca': 'N/A',
            'modelo_serie': 'N/A',
            'serie': '',
            'tipo_equipo': 'otro',
        }
        if es_tecnico(request.user):
            initial['tecnico_encargado'] = request.user
        ing_form = IngresoEquipoForm(prefix='ing', initial=initial)
        _configurar_form_venta(ing_form)

    from .models import SEDE_PREFIJOS
    siguiente_numero = IngresoEquipo.siguiente_numero_equipo('ventas')
    siguiente_codigo = f"{siguiente_numero:03d}"

    return render(request, 'ventas/form.html', {
        'cli_form': cli_form,
        'ing_form': ing_form,
        'modo': 'registrar',
        'titulo': 'Nueva Venta de Producto',
        'siguiente_numero': siguiente_numero,
        'siguiente_codigo': siguiente_codigo,
    })

@tecnico_requerido
@transaction.atomic
def venta_editar(request, pk):
    """Edita una venta existente."""
    venta = get_object_or_404(IngresoEquipo, pk=pk, sede='ventas')

    if request.method == 'POST':
        post_data = request.POST.copy()
        _preparar_post_venta(post_data)
            
        cli_form = ClienteForm(post_data, prefix='cli', instance=venta.cliente)
        ing_form = IngresoEquipoForm(post_data, prefix='ing', instance=venta)
        _configurar_form_venta(ing_form)
        
        if cli_form.is_valid() and ing_form.is_valid():
            cli_form.save()
            venta = ing_form.save(commit=False)
            venta.sede = 'ventas'
            venta.estado = 'entregado'
            venta.subestado_entregado = 'con_solucion'
            venta.save()
            messages.success(request, f'Venta {venta.codigo_equipo} actualizada.')
            return redirect('econotec:venta_lista')
    else:
        cli_form = ClienteForm(prefix='cli', instance=venta.cliente)
        ing_form = IngresoEquipoForm(prefix='ing', instance=venta)
        
    _configurar_form_venta(ing_form)

    return render(request, 'ventas/form.html', {
        'cli_form': cli_form,
        'ing_form': ing_form,
        'modo': 'editar',
        'titulo': f'Editar Venta {venta.codigo_equipo}',
        'siguiente_numero': venta.numero_equipo,
        'siguiente_codigo': venta.codigo_equipo,
    })

@admin_requerido
@require_POST
def venta_eliminar(request, pk):
    """Elimina una venta."""
    venta = get_object_or_404(IngresoEquipo, pk=pk, sede='ventas')
    venta.delete()
    messages.success(request, 'Venta eliminada correctamente.')
    return redirect('econotec:venta_lista')

@tecnico_requerido
def venta_export(request):
    """Exportar ventas a Excel."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from io import BytesIO
    q = (request.GET.get('q') or '').strip()
    tecnico_vendio_filtro = (request.GET.get('tecnico_vendio') or '').strip()
    registrador_filtro = (request.GET.get('registrador') or '').strip()

    wb = Workbook()
    ws = wb.active
    ws.title = 'Ventas Econotec'

    headers = ['Código', 'Fecha', 'Cliente', 'Cédula', 'Descripción', 'Técnico vendió', 'Registrado por', 'Valor']
    for col, h in enumerate(headers, start=1):
        c = ws.cell(row=1, column=col, value=h)
        c.font = Font(bold=True, color='FFFFFF')
        c.fill = PatternFill('solid', fgColor='F97618')
        c.alignment = Alignment(horizontal='center')

    ventas = (
        IngresoEquipo.objects
        .select_related('cliente', 'tecnico_encargado', 'registrado_por')
        .filter(sede='ventas')
        .order_by('-fecha_ingreso', '-pk')
    )
    if tecnico_vendio_filtro.isdigit():
        ventas = ventas.filter(tecnico_encargado_id=tecnico_vendio_filtro)
    if registrador_filtro.isdigit():
        ventas = ventas.filter(registrado_por_id=registrador_filtro)
    ventas = filtrar_objetos_normalizado(ventas, q, texto_ingreso_busqueda)

    for row, v in enumerate(ventas, start=2):
        ws.cell(row=row, column=1, value=v.codigo_equipo)
        ws.cell(row=row, column=2, value=v.fecha_ingreso.strftime('%d/%m/%Y'))
        ws.cell(row=row, column=3, value=v.cliente.nombres)
        ws.cell(row=row, column=4, value=v.cliente.cedula)
        ws.cell(row=row, column=5, value=v.problema_reportado)
        tecnico_vendio = f"{v.tecnico_encargado.first_name} {v.tecnico_encargado.last_name}".strip() if v.tecnico_encargado else 'N/A'
        tecnico_vendio = tecnico_vendio or (v.tecnico_encargado.username if v.tecnico_encargado else 'N/A')
        ws.cell(row=row, column=6, value=tecnico_vendio)
        registrador = f"{v.registrado_por.first_name} {v.registrado_por.last_name}".strip() if v.registrado_por else 'N/A'
        registrador = registrador or (v.registrado_por.username if v.registrado_por else 'N/A')
        ws.cell(row=row, column=7, value=registrador)
        ws.cell(row=row, column=8, value=v.valor_acordado)

    for col in range(1, 9):
        ws.column_dimensions[chr(64 + col)].width = 22

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)

    response = HttpResponse(
        buf.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = 'attachment; filename="ventas_econotec.xlsx"'
    return response


@tecnico_requerido
def venta_lista(request):
    """Listado de ventas."""
    q = (request.GET.get('q') or '').strip()
    tecnico_vendio_filtro = (request.GET.get('tecnico_vendio') or '').strip()
    registrador_filtro = (request.GET.get('registrador') or '').strip()

    qs = (IngresoEquipo.objects
          .select_related('cliente', 'tecnico_encargado', 'registrado_por')
          .prefetch_related('abonos')
          .filter(sede='ventas')
          .order_by('-fecha_ingreso', '-pk'))

    if tecnico_vendio_filtro.isdigit():
        qs = qs.filter(tecnico_encargado_id=tecnico_vendio_filtro)
    if registrador_filtro.isdigit():
        qs = qs.filter(registrado_por_id=registrador_filtro)

    qs = filtrar_objetos_normalizado(qs, q, texto_ingreso_busqueda)

    from django.contrib.auth import get_user_model
    User = get_user_model()
    usuarios_all = User.objects.filter(is_active=True).order_by('first_name', 'username')
    from .forms import _queryset_tecnicos
    tecnicos_solo = _queryset_tecnicos()

    return render(request, 'ventas/lista.html', {
        'ingresos': qs,
        'q': q,
        'tecnico_vendio_filtro': tecnico_vendio_filtro,
        'registrador_filtro': registrador_filtro,
        'usuarios_all': usuarios_all,
        'tecnicos_solo': tecnicos_solo,
        'total': total_resultados(qs),
    })


# ═════════════════════════════════════════════════════════════════
# Salida de Equipos
# ═════════════════════════════════════════════════════════════════

@tecnico_requerido
def salida_menu(request):
    """Menú de salidas."""
    total = SalidaEquipo.objects.count()
    listos_para_entregar = SalidaEquipo.objects.filter(
        estado_reparacion='pendiente_retiro',
    ).count()
    facturas_realizadas = SalidaEquipo.objects.filter(
        factura_realizada='si',
    ).count()
    return render(request, 'salidas/menu.html', {
        'total': total,
        'listos_para_entregar': listos_para_entregar,
        'facturas_realizadas': facturas_realizadas,
    })


@tecnico_requerido
def salida_lista(request):
    """Listado de salidas con filtros por estado y sede."""
    q = (request.GET.get('q') or '').strip()
    estado = (request.GET.get('estado') or '').strip()
    sede_filtro = (request.GET.get('sede') or '').strip().lower()
    tecnico_registro_filtro = (request.GET.get('tecnico_registro') or '').strip()
    tecnico_salida_filtro = (request.GET.get('tecnico_salida') or '').strip()

    qs = (SalidaEquipo.objects
          .select_related('ingreso', 'ingreso__cliente', 'registrado_por', 'tecnico_reparo')
          .order_by('-fecha_salida', '-creado'))

    if estado:
        qs = qs.filter(estado_reparacion=estado)
    if sede_filtro in ('guayaquil', 'quito'):
        qs = qs.filter(ingreso__sede=sede_filtro)
    if tecnico_registro_filtro:
        qs = qs.filter(registrado_por_id=tecnico_registro_filtro)
    if tecnico_salida_filtro:
        qs = qs.filter(tecnico_reparo_id=tecnico_salida_filtro)

    qs = filtrar_objetos_normalizado(qs, q, texto_salida_busqueda)

    from django.contrib.auth import get_user_model
    User = get_user_model()
    tecnicos_all = User.objects.filter(is_active=True).order_by('first_name', 'username')
    from .forms import _queryset_tecnicos
    tecnicos_solo = _queryset_tecnicos()

    # Excluir 'chatarrerizacion' del filtro de vistas públicas
    estados_filtro = [e for e in SalidaEquipo.ESTADO_REPARACION if e[0] != 'chatarrerizacion']

    return render(request, 'salidas/lista.html', {
        'salidas': qs,
        'q': q,
        'estado_filtro': estado,
        'sede_filtro': sede_filtro,
        'tecnico_registro_filtro': tecnico_registro_filtro,
        'tecnico_salida_filtro': tecnico_salida_filtro,
        'tecnicos_all': tecnicos_all,
        'tecnicos_solo': tecnicos_solo,
        'estados': estados_filtro,
        'total': total_resultados(qs),
    })


@tecnico_requerido
@transaction.atomic
def salida_registrar(request, ingreso_pk):
    """Registrar la salida de un equipo (cierre del ciclo de reparación)."""
    ingreso = get_object_or_404(IngresoEquipo, pk=ingreso_pk)

    if hasattr(ingreso, 'salida'):
        messages.info(
            request,
            f'El equipo {ingreso.codigo_equipo} ya tiene salida registrada. '
            'Puedes editarla aquí.'
        )
        return redirect('econotec:salida_editar', pk=ingreso.salida.pk)

    if ingreso.valor_acordado is None:
        messages.warning(
            request,
            'Por favor registra un valor acordado para registrar la salida.'
        )
        return redirect('econotec:ingreso_detalle', pk=ingreso.pk)

    if request.method == 'POST':
        salida_inst = SalidaEquipo(ingreso=ingreso)
        form = SalidaEquipoForm(request.POST, instance=salida_inst)
        if form.is_valid():
            salida = form.save(commit=False)
            salida.registrado_por = request.user
            salida.save()
            _sincronizar_notificacion_asesora(form, salida, request.user)
            messages.success(
                request,
                f'Salida del equipo {ingreso.codigo_equipo} registrada como '
                f'"{salida.get_estado_reparacion_display()}".'
            )
            # Si la salida es positiva, redirigir a la pantalla de "salida creada"
            # con el botón de WhatsApp para avisar al cliente.
            if salida.pendiente_de_retiro_fisico:
                return redirect('econotec:salida_listo_aviso', pk=salida.pk)
            return redirect('econotec:salida_lista')
    else:
        # Saldo pendiente sugerido como valor a cobrar
        saldo = ingreso.diferencia
        salida_inst = SalidaEquipo(ingreso=ingreso)
        form = SalidaEquipoForm(instance=salida_inst, initial={
            'fecha_salida': date.today(),
            'estado_reparacion': 'pendiente_retiro',
            'metodo_pago_final': 'efectivo',
            'valor_final_cobrado': 0,
            'tecnico_reparo': request.user if es_tecnico(request.user) else None,
        })

    return render(request, 'salidas/form.html', {
        'form': form,
        'ingreso': ingreso,
        'modo': 'registrar',
        'titulo': f'Registrar Salida — Equipo {ingreso.codigo_equipo}',
    })


@tecnico_requerido
@transaction.atomic
def salida_editar(request, pk):
    salida = get_object_or_404(
        SalidaEquipo.objects.select_related('ingreso', 'ingreso__cliente'),
        pk=pk,
    )
    if request.method == 'POST':
        form = SalidaEquipoForm(request.POST, instance=salida)
        if form.is_valid():
            salida = form.save()
            _sincronizar_notificacion_asesora(form, salida, request.user)
            messages.success(request, 'Salida actualizada correctamente.')
            return redirect('econotec:salida_lista')
    else:
        form = SalidaEquipoForm(instance=salida)
    return render(request, 'salidas/form.html', {
        'form': form,
        'ingreso': salida.ingreso,
        'salida': salida,
        'modo': 'editar',
        'titulo': f'Editar Salida — Equipo {salida.ingreso.codigo_equipo}',
        # Si la salida ya está marcada como positiva (retirado/garantía/parcial)
        # y el cliente tiene WhatsApp, generamos el link para reenviar el aviso
        # junto con el PDF de la hoja de salida.
        'wa_link': whatsapp_link_equipo_listo(salida),
    })


@login_required
def notificaciones_asesora(request):
    admin_mode = es_admin(request.user)
    if not (admin_mode or es_asesor(request.user)):
        messages.warning(request, 'No tienes acceso a las notificaciones de asesoras.')
        return redirect('econotec:bienvenida')

    qs = (
        NotificacionAsesora.objects
        .select_related('ingreso', 'ingreso__cliente', 'salida', 'asesora', 'creado_por')
    )
    asesora_filtro_id = None
    asesoras_filtro = []

    if admin_mode:
        from django.contrib.auth import get_user_model

        ids_asesoras = (
            NotificacionAsesora.objects
            .exclude(asesora_id__isnull=True)
            .values_list('asesora_id', flat=True)
            .distinct()
        )
        asesoras_filtro = (
            get_user_model().objects
            .filter(pk__in=ids_asesoras)
            .order_by('first_name', 'last_name', 'username')
        )

        asesora_param = (request.GET.get('asesora') or '').strip()
        if asesora_param and asesora_param != 'todas':
            try:
                asesora_filtro_id = int(asesora_param)
            except (TypeError, ValueError):
                asesora_filtro_id = None
            if asesora_filtro_id:
                qs = qs.filter(asesora_id=asesora_filtro_id)
    else:
        qs = qs.filter(asesora=request.user)

    total_bandeja = qs.count()
    total_pendientes = qs.filter(leida=False).count()
    total_vistas = qs.filter(leida=True).count()

    estado = (request.GET.get('estado') or 'pendientes').strip()
    if estado == 'vistas':
        qs = qs.filter(leida=True)
    elif estado != 'todas':
        estado = 'pendientes'
        qs = qs.filter(leida=False)

    return render(request, 'notificaciones/asesoras.html', {
        'notificaciones': qs,
        'estado_filtro': estado,
        'total_notificaciones': total_resultados(qs),
        'total_bandeja': total_bandeja,
        'total_pendientes': total_pendientes,
        'total_vistas': total_vistas,
        'admin_notificaciones': admin_mode,
        'asesoras_filtro': asesoras_filtro,
        'asesora_filtro_id': asesora_filtro_id,
    })


@login_required
@require_POST
def notificacion_asesora_marcar_vista(request, pk):
    admin_mode = es_admin(request.user)
    if not (admin_mode or es_asesor(request.user)):
        messages.warning(request, 'No tienes acceso a las notificaciones de asesoras.')
        return redirect('econotec:bienvenida')

    qs = NotificacionAsesora.objects.all() if admin_mode else NotificacionAsesora.objects.filter(asesora=request.user)
    notificacion = get_object_or_404(qs, pk=pk)
    notificacion.leida = True
    notificacion.leida_en = timezone.now()
    notificacion.save(update_fields=['leida', 'leida_en', 'actualizado'])
    if admin_mode:
        messages.success(request, 'Notificación marcada como gestionada.')
    else:
        messages.success(request, 'Notificación marcada como vista.')

    next_url = request.POST.get('next') or ''
    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect(next_url)
    return redirect('econotec:notificaciones_asesora')


@login_required
@require_POST
def notificacion_asesora_limpiar_bandeja(request):
    if not es_asesor(request.user):
        messages.warning(request, 'No tienes acceso a las notificaciones de asesoras.')
        return redirect('econotec:bienvenida')

    total, _ = NotificacionAsesora.objects.filter(asesora=request.user).delete()
    if total:
        messages.success(request, f'Bandeja limpiada. Se eliminaron {total} notificación(es).')
    else:
        messages.info(request, 'La bandeja ya estaba vacía.')
    return redirect('econotec:notificaciones_asesora')


@admin_requerido
@require_POST
def salida_eliminar(request, pk):
    salida = get_object_or_404(SalidaEquipo, pk=pk)
    ingreso = salida.ingreso
    salida.delete()
    # Volver el equipo al estado anterior
    ingreso.estado = 'en_reparacion'
    ingreso.save(update_fields=['estado'])
    messages.success(
        request,
        f'Salida del equipo {ingreso.codigo_equipo} eliminada. '
        'El equipo vuelve a estado "Pendiente de retiro".'
    )
    return redirect('econotec:salida_lista')


# ═════════════════════════════════════════════════════════════════
# Clientes
# ═════════════════════════════════════════════════════════════════

@tecnico_requerido
def cliente_lista(request):
    q = (request.GET.get('q') or '').strip()
    sede_filtro = (request.GET.get('sede') or '').strip().lower()

    qs = Cliente.objects.prefetch_related('ingresos').annotate(
        equipos_total=Count('ingresos'),
    ).order_by('nombres')

    if sede_filtro in ('guayaquil', 'quito'):
        qs = qs.filter(ingresos__sede=sede_filtro).distinct()

    qs = filtrar_objetos_normalizado(qs, q, texto_cliente_busqueda)
    return render(request, 'clientes/lista.html', {
        'clientes': qs,
        'q': q,
        'sede_filtro': sede_filtro,
        'total': total_resultados(qs),
    })


@tecnico_requerido
def cliente_top_recurrentes(request):
    """Ranking de clientes recurrentes separados por sede (Top 10 cada una)."""
    clientes_guayaquil = (
        Cliente.objects
        .annotate(total_ingresos=Count(
            'ingresos',
            filter=Q(ingresos__sede='guayaquil'),
            distinct=True,
        ))
        .filter(total_ingresos__gt=0)
        .order_by('-total_ingresos', 'nombres')[:10]
    )
    clientes_quito = (
        Cliente.objects
        .annotate(total_ingresos=Count(
            'ingresos',
            filter=Q(ingresos__sede='quito'),
            distinct=True,
        ))
        .filter(total_ingresos__gt=0)
        .order_by('-total_ingresos', 'nombres')[:10]
    )

    return render(request, 'clientes/top.html', {
        'clientes_guayaquil': clientes_guayaquil,
        'clientes_quito': clientes_quito,
    })


@tecnico_requerido
def cliente_detalle(request, pk):
    cliente = get_object_or_404(Cliente, pk=pk)
    ingresos = (cliente.ingresos
                .select_related('cliente')
                .prefetch_related('abonos', 'salida')
                .order_by('-fecha_ingreso'))

    total_pagado = sum((ing.total_abonado for ing in ingresos), 0)
    total_acordado = sum((ing.valor_acordado or 0 for ing in ingresos), 0)

    return render(request, 'clientes/detalle.html', {
        'cliente': cliente,
        'ingresos': ingresos,
        'total_equipos': ingresos.count(),
        'total_pagado': total_pagado,
        'total_acordado': total_acordado,
    })


@tecnico_requerido
def cliente_export(request):
    """Exportar clientes a Excel."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    wb = Workbook()
    ws = wb.active
    ws.title = 'Clientes Econotec'

    headers = ['Cédula/RUC', 'Nombres', 'WhatsApp', 'Correo', 'Sector', 'Equipos', 'Registrado']
    for col, h in enumerate(headers, start=1):
        c = ws.cell(row=1, column=col, value=h)
        c.font = Font(bold=True, color='FFFFFF')
        c.fill = PatternFill('solid', fgColor='F97618')
        c.alignment = Alignment(horizontal='center')

    clientes = Cliente.objects.annotate(
        equipos_total=Count('ingresos'),
    ).order_by('nombres')

    for row, cli in enumerate(clientes, start=2):
        ws.cell(row=row, column=1, value=cli.cedula)
        ws.cell(row=row, column=2, value=cli.nombres)
        ws.cell(row=row, column=3, value=cli.whatsapp)
        ws.cell(row=row, column=4, value=cli.correo)
        ws.cell(row=row, column=5, value=cli.sector_display)
        ws.cell(row=row, column=6, value=cli.equipos_total)
        ws.cell(row=row, column=7, value=cli.creado.strftime('%d/%m/%Y'))

    for col in range(1, 8):
        ws.column_dimensions[chr(64 + col)].width = 22

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)

    response = HttpResponse(
        buf.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = 'attachment; filename="clientes_econotec.xlsx"'
    return response


# ═════════════════════════════════════════════════════════════════
# Ranking de Técnicos (totales por técnico)
# ═════════════════════════════════════════════════════════════════

from .permisos import ranking_requerido as _ranking_requerido

@_ranking_requerido
def salida_totales(request):
    """
    Ranking de técnicos: cuántos equipos atendió cada uno como
    *técnico encargado* (responsable directo de la reparación), cuántos
    terminó positivamente (retirados/garantía), cuánto dinero generó, etc.

    El ranking SE AGRUPA POR `tecnico_encargado` — el técnico responsable
    del equipo — no por el usuario que digitó la solicitud en el sistema.

    Filtros opcionales por rango de fechas.
    """
    from decimal import Decimal as D

    desde = (request.GET.get('desde') or '').strip()
    hasta = (request.GET.get('hasta') or '').strip()

    # Base: ingresos en el rango. La métrica se calcula sobre ingresos
    # (cada equipo cuenta para el técnico ENCARGADO, no para el que registró).
    qs_ing = IngresoEquipo.objects.select_related('tecnico_encargado')
    if desde:
        qs_ing = qs_ing.filter(fecha_ingreso__gte=desde)
    if hasta:
        qs_ing = qs_ing.filter(fecha_ingreso__lte=hasta)

    # Agrupar por técnico encargado
    from django.db.models import Count, Sum, Q
    ranking = (
        qs_ing
        .values('tecnico_encargado_id', 'tecnico_encargado__first_name',
                'tecnico_encargado__last_name', 'tecnico_encargado__username')
        .annotate(
            num_equipos=Count('id'),
            total_acordado=Sum('valor_acordado'),
            total_anticipo=Sum('abono_anticipo'),
            entregados=Count('id', filter=Q(estado='entregado')),
            pendientes=Count('id', filter=Q(estado__in=[
                'ingresado', 'en_reparacion'
            ])),
        )
        .order_by('-num_equipos', '-total_acordado')
    )

    # Por cada técnico calcular sus salidas positivas (retirados, garantía, parciales)
    ranking_list = []
    for row in ranking:
        tid = row['tecnico_encargado_id']
        nombre = (
            f"{row['tecnico_encargado__first_name'] or ''} {row['tecnico_encargado__last_name'] or ''}".strip()
            or row['tecnico_encargado__username']
            or '— Sin asignar —'
        )

        # Salidas asociadas a equipos de este técnico encargado
        # Usamos select_related para evitar querys extra al pedir salida.ingreso.valor_acordado
        sal_qs = SalidaEquipo.objects.filter(ingreso__tecnico_encargado_id=tid).select_related('ingreso')
        if desde:
            sal_qs = sal_qs.filter(fecha_salida__gte=desde)
        if hasta:
            sal_qs = sal_qs.filter(fecha_salida__lte=hasta)

        total_salidas = sal_qs.count()
        
        salidas_positivas = 0
        salidas_negativas = 0
        cobrado_final = D('0.00')
        
        total_acordado = row['total_acordado'] or D('0.00')
        total_anticipo = row['total_anticipo'] or D('0.00')

        for salida in sal_qs:
            estado = salida.estado_reparacion
            
            # Conteo de salidas
            if estado in ['pendiente_retiro', 'garantia', 'garantia_fallos_adicionales', 'retirado']:
                salidas_positivas += 1
            elif estado in ['no_reparable', 'cliente_no_acepta', 'chatarrerizacion']:
                salidas_negativas += 1
                
            # Cobrado
            cobrado_final += (salida.valor_final_cobrado or D('0.00'))
            
            # Ajuste de Venta (Acordado)
            if estado == 'cliente_no_acepta':
                total_acordado -= (salida.ingreso.valor_acordado or D('0.00'))
                total_acordado += D('5.00')
            elif estado == 'no_reparable':
                total_acordado -= (salida.ingreso.valor_acordado or D('0.00'))

        # Recaudado para el técnico: EXCLUYE anticipos, SOLO cobros de salida
        total_recaudado = cobrado_final

        ranking_list.append({
            'tecnico_id': tid,
            'nombre': nombre,
            'sin_asignar': tid is None,
            'num_equipos': row['num_equipos'],
            'entregados': row['entregados'],
            'pendientes': row['pendientes'],
            'total_acordado': total_acordado,
            'total_anticipo': total_anticipo,
            'cobrado_final': cobrado_final,
            'total_recaudado': total_recaudado,
            'total_salidas': total_salidas,
            'salidas_positivas': salidas_positivas,
            'salidas_negativas': salidas_negativas,
            'efectividad': round((salidas_positivas / total_salidas * 100) if total_salidas else 0, 1),
        })

    # Totales globales
    total_equipos = qs_ing.count()
    total_acordado_global = qs_ing.aggregate(s=Sum('valor_acordado'))['s'] or D('0.00')
    total_anticipos_global = qs_ing.aggregate(s=Sum('abono_anticipo'))['s'] or D('0.00')

    # Salidas globales
    sal_global = SalidaEquipo.objects.all()
    if desde:
        sal_global = sal_global.filter(fecha_salida__gte=desde)
    if hasta:
        sal_global = sal_global.filter(fecha_salida__lte=hasta)
    total_salidas_global = sal_global.count()
    total_positivas_global = sal_global.filter(
        estado_reparacion__in=[
            'pendiente_retiro',
            'garantia',
            'garantia_fallos_adicionales',
            'retirado',
            'cliente_no_acepta',
            'no_reparable',
        ]
    ).count()
    cobrado_final_global = sal_global.aggregate(s=Sum('valor_final_cobrado'))['s'] or D('0.00')

    total_diag_no_reparado = sal_global.filter(
        estado_reparacion__in=['no_reparable', 'cliente_no_acepta']
    ).aggregate(s=Sum('valor_final_cobrado'))['s'] or D('0.00')

    # Top tipos de equipo trabajados
    por_tipo = (
        qs_ing.values('tipo_equipo')
        .annotate(num=Count('id'), suma=Sum('valor_acordado'))
        .order_by('-num')
    )
    map_tipos = dict(IngresoEquipo._meta.get_field('tipo_equipo').choices)
    por_tipo_list = [{
        'tipo': map_tipos.get(t['tipo_equipo'], t['tipo_equipo']),
        'num': t['num'],
        'suma': t['suma'] or D('0.00'),
    } for t in por_tipo]

    return render(request, 'salidas/totales.html', {
        'ranking': ranking_list,
        'por_tipo': por_tipo_list,
        'total_equipos': total_equipos,
        'total_acordado_global': total_acordado_global,
        'total_anticipos_global': total_anticipos_global,
        'cobrado_final_global': cobrado_final_global,
        'total_recaudado_global': total_anticipos_global + cobrado_final_global,
        'total_salidas_global': total_salidas_global,
        'total_positivas_global': total_positivas_global,
        'total_diag_no_reparado': total_diag_no_reparado,
        'filtros': {'desde': desde, 'hasta': hasta},
    })


# ═════════════════════════════════════════════════════════════════
# Vistas de Alertas (demora en taller + bodegaje post-salida)
# ═════════════════════════════════════════════════════════════════

@login_required
def alertas_demora(request):
    """
    Lista completa de equipos demorados en diagnóstico (4+ días sin diagnosticar).
    Muestra dos secciones: activos y silenciados.
    """
    es_admin_user = request.user.is_superuser or request.user.groups.filter(
        name__in=['Administradores', 'Admin']
    ).exists()

    qs_activos = equipos_demorados_qs(usuario=None)

    # Silenciados: mismo filtro de estado pero con diagnostico_silenciado=True
    from datetime import timedelta as _td
    fecha_limite = date.today() - _td(days=UMBRAL_DIAS_DIAGNOSTICO)
    qs_silenciados = (
        IngresoEquipo.objects
        .select_related('cliente', 'tecnico_encargado')
        .filter(fecha_ingreso__lte=fecha_limite)
        .filter(estado='ingresado')
        .filter(salida__isnull=True)
        .filter(diagnostico_silenciado=True)
        .order_by('fecha_ingreso', 'numero_equipo')
    )
    # Todos ven todo

    hoy = date.today()

    def _build(qs):
        return [{
            'ingreso': ing,
            'dias': dias_en_taller(ing, hoy=hoy),
            'wa_link': whatsapp_link_demora(ing),
        } for ing in qs]

    items = _build(qs_activos)
    items_silenciados = _build(qs_silenciados)

    return render(request, 'alertas_demora.html', {
        'items': items,
        'total': len(items),
        'items_silenciados': items_silenciados,
        'total_silenciados': len(items_silenciados),
        'umbral_dias': UMBRAL_DIAS_DIAGNOSTICO,
        'es_admin_view': es_admin_user,
    })


@login_required
def alertas_bodegaje(request):
    """
    Lista completa de salidas con bodegaje pendiente
    (5+ días sin que el cliente venga a retirar).

    Muestra dos secciones:
      - Activos: alertas visibles
      - Silenciados: alertas que el usuario marcó como "no molestar"
    """
    es_admin_user = request.user.is_superuser or request.user.groups.filter(
        name__in=['Administradores', 'Admin']
    ).exists()

    qs_activos = salidas_bodegaje_qs(usuario=None)

    # Para los silenciados: incluimos todos los del usuario/admin que estén silenciados
    from django.db.models import Q as _Q
    from datetime import timedelta as _td
    fecha_limite = date.today() - _td(days=UMBRAL_DIAS_BODEGAJE)
    qs_silenciados = (
        SalidaEquipo.objects
        .select_related('ingreso', 'ingreso__cliente', 'ingreso__tecnico_encargado', 'tecnico_reparo')
        .filter(fecha_salida__lte=fecha_limite)
        .filter(fecha_retiro_real__isnull=True)
        .filter(bodegaje_silenciado=True)
        .order_by('fecha_salida')
    )
    # Todos ven todo

    hoy = date.today()

    def _build_items(qs):
        out = []
        total = D('0.00')
        for sal in qs:
            bod = sal.calcular_bodegaje(hoy=hoy)
            out.append({
                'salida': sal,
                'ingreso': sal.ingreso,
                'dias_desde_salida': dias_desde_salida(sal, hoy=hoy),
                'bodegaje_dias': bod['dias'],
                'bodegaje_monto': bod['monto'],
                'wa_link': whatsapp_link_bodegaje(sal),
            })
            total += bod['monto']
        return out, total

    items, total_acumulado = _build_items(qs_activos)
    items_silenciados, total_silenciados = _build_items(qs_silenciados)

    return render(request, 'alertas_bodegaje.html', {
        'items': items,
        'total': len(items),
        'total_acumulado': total_acumulado,
        'items_silenciados': items_silenciados,
        'total_silenciados': len(items_silenciados),
        'total_acumulado_silenciado': total_silenciados,
        'umbral_dias': UMBRAL_DIAS_BODEGAJE,
        'costo_dia': COSTO_BODEGAJE_DIA,
        'es_admin_view': es_admin_user,
    })


@tecnico_requerido
def salida_listo_aviso(request, pk):
    """
    Pantalla post-salida positiva: muestra el botón "Avisar al cliente
    por WhatsApp que su equipo está listo".
    """
    salida = get_object_or_404(
        SalidaEquipo.objects.select_related('ingreso', 'ingreso__cliente'),
        pk=pk,
    )
    return render(request, 'salidas/listo_aviso.html', {
        'salida': salida,
        'ingreso': salida.ingreso,
        'wa_link': whatsapp_link_equipo_listo(salida),
    })


@tecnico_requerido
@require_POST
def salida_marcar_retirada(request, pk):
    """
    Marca la salida como "Cliente ya retiró", congelando el bodegaje
    acumulado hasta hoy. Esto cierra el caso.

    Si en el POST viene `aplicar_bodegaje=on`, marca el bodegaje como
    cobrado al cliente (esto es solo informativo: el monto del bodegaje
    debe haberse incluido manualmente al hacer el último abono).
    """
    salida = get_object_or_404(SalidaEquipo, pk=pk)

    if salida.cliente_ya_retiro:
        messages.info(
            request,
            f'El equipo {salida.ingreso.codigo_equipo} ya estaba marcado como retirado.'
        )
        return redirect('econotec:salida_lista')

    bod = salida.calcular_bodegaje()
    aplicar = request.POST.get('aplicar_bodegaje') == 'on'

    salida.fecha_retiro_real = date.today()
    if salida.estado_reparacion == 'pendiente_retiro':
        salida.estado_reparacion = 'retirado'
    salida.bodegaje_dias_congelado = bod['dias']
    salida.bodegaje_monto_congelado = bod['monto']
    salida.bodegaje_aplicado_al_pago = aplicar
    salida.save(update_fields=[
        'fecha_retiro_real',
        'estado_reparacion',
        'bodegaje_dias_congelado',
        'bodegaje_monto_congelado',
        'bodegaje_aplicado_al_pago',
    ])

    if bod['monto'] > 0 and aplicar:
        # ── Normalizar los datos del método de pago del bodegaje ──
        # El campo correcto en el modelo Abono es `metodo` (NO `metodo_pago`).
        # Además, el modal ofrece algunas opciones que no existen en los
        # choices del modelo; las saneamos para que el recibo muestre el
        # nombre correcto en lugar de un código crudo.
        metodo_bod = request.POST.get('pago_bod_metodo', 'efectivo')
        if metodo_bod not in dict(Abono.METODOS_PAGO):
            metodo_bod = 'efectivo'

        banco_bod = request.POST.get('pago_bod_banco', '') if metodo_bod == 'transferencia' else ''
        banco_otro_bod = request.POST.get('pago_bod_banco_otro', '') if metodo_bod == 'transferencia' else ''
        tarjeta_bod = request.POST.get('pago_bod_tarjeta_app', '') if metodo_bod == 'tarjeta' else ''
        comprobante_bod = request.POST.get('pago_bod_comprobante_url', '') if metodo_bod == 'transferencia' else ''

        # Si el banco elegido no está en los choices del modelo, lo movemos
        # a "otro" + texto libre para no perder el dato y mostrarlo bien.
        if banco_bod and banco_bod not in dict(Abono.BANCOS):
            if not banco_otro_bod:
                banco_otro_bod = dict([
                    ('bolivariano', 'Bolivariano'),
                    ('internacional', 'Internacional'),
                    ('austro', 'Banco del Austro'),
                    ('cooperativa_jep', 'Cooperativa JEP'),
                ]).get(banco_bod, banco_bod.replace('_', ' ').title())
            banco_bod = 'otro'

        # Igual para tarjeta/app fuera de choices.
        if tarjeta_bod and tarjeta_bod not in dict(Abono.TARJETAS_APPS):
            tarjeta_bod = ''

        # Crear el Abono por el bodegaje
        Abono.objects.create(
            ingreso=salida.ingreso,
            monto=bod['monto'],
            fecha=date.today(),
            metodo=metodo_bod,
            banco=banco_bod,
            banco_otro=banco_otro_bod,
            tarjeta_app=tarjeta_bod,
            comprobante_url=comprobante_bod,
            observaciones=f"Cobro por {bod['dias']} días de bodegaje al retirar el equipo.",
            bodegaje_decision='si',
            bodegaje_monto_aplicado=bod['monto'],
            registrado_por=request.user
        )

    if bod['monto'] > 0:
        if aplicar:
            messages.success(
                request,
                f'Equipo {salida.ingreso.codigo_equipo} marcado como retirado. '
                f'Se cobraron ${bod["monto"]} de bodegaje ({bod["dias"]} días).'
            )
        else:
            messages.success(
                request,
                f'Equipo {salida.ingreso.codigo_equipo} marcado como retirado. '
                f'Bodegaje de ${bod["monto"]} ({bod["dias"]} días) NO cobrado al cliente.'
            )
    else:
        messages.success(
            request,
            f'Equipo {salida.ingreso.codigo_equipo} marcado como retirado.'
        )

    next_url = request.POST.get('next') or request.GET.get('next')
    if next_url:
        return redirect(next_url)
    return redirect('econotec:salida_lista')


@admin_requerido
@require_POST
def salida_deshacer_retiro(request, pk):
    """
    Deshace el retiro físico de un equipo. Solo para administradores.
    """
    salida = get_object_or_404(SalidaEquipo, pk=pk)

    if not salida.cliente_ya_retiro:
        messages.info(
            request,
            f'El equipo {salida.ingreso.codigo_equipo} no estaba marcado como retirado.'
        )
        return redirect('econotec:salida_lista')

    salida.fecha_retiro_real = None
    if salida.estado_reparacion == 'retirado':
        salida.estado_reparacion = 'pendiente_retiro'
    salida.bodegaje_dias_congelado = None
    salida.bodegaje_monto_congelado = None
    salida.bodegaje_aplicado_al_pago = False
    salida.save(update_fields=[
        'fecha_retiro_real',
        'estado_reparacion',
        'bodegaje_dias_congelado',
        'bodegaje_monto_congelado',
        'bodegaje_aplicado_al_pago',
    ])
    messages.success(
        request,
        f'Deshecho: El equipo {salida.ingreso.codigo_equipo} vuelve a estar físicamente en el local.'
    )
    return redirect('econotec:salida_lista')


@login_required
@require_POST
def salida_bodegaje_silenciar(request, pk):
    """
    Activa/desactiva el modo 'no molestar' para la alerta de bodegaje
    de un equipo específico. El bodegaje sigue acumulándose; solo se
    oculta del banner del dashboard.

    El parámetro POST `accion` puede ser 'silenciar' o 'reactivar'.
    Si no viene, hace toggle.
    """
    salida = get_object_or_404(SalidaEquipo, pk=pk)
    accion = (request.POST.get('accion') or '').strip().lower()

    if accion == 'silenciar':
        salida.bodegaje_silenciado = True
    elif accion == 'reactivar':
        salida.bodegaje_silenciado = False
    else:
        # Toggle
        salida.bodegaje_silenciado = not salida.bodegaje_silenciado

    salida.save(update_fields=['bodegaje_silenciado', 'actualizado'])

    codigo = salida.ingreso.codigo_equipo
    if salida.bodegaje_silenciado:
        messages.success(
            request,
            f'🔕 Alerta silenciada para el equipo {codigo}. '
            f'El bodegaje sigue acumulándose, pero no aparecerá en el dashboard.'
        )
    else:
        messages.success(
            request,
            f'🔔 Alerta reactivada para el equipo {codigo}.'
        )

    # Volver a donde venía: alerta detallada o dashboard
    next_url = request.POST.get('next', '')
    if next_url:
        return redirect(next_url)
    return redirect('econotec:bienvenida')


@login_required
@require_POST
def ingreso_diagnostico_silenciar(request, pk):
    """
    Activa/desactiva el modo 'no molestar' para la alerta de diagnóstico
    pendiente de un equipo específico. El equipo sigue pendiente; solo
    se oculta del banner del dashboard.

    Se reactiva automáticamente cuando el estado del equipo cambia
    (lógica implementada en IngresoEquipo.save()).

    El parámetro POST `accion` puede ser 'silenciar' o 'reactivar'.
    Si no viene, hace toggle.
    """
    ingreso = get_object_or_404(IngresoEquipo, pk=pk)
    accion = (request.POST.get('accion') or '').strip().lower()

    if accion == 'silenciar':
        ingreso.diagnostico_silenciado = True
    elif accion == 'reactivar':
        ingreso.diagnostico_silenciado = False
    else:
        # Toggle
        ingreso.diagnostico_silenciado = not ingreso.diagnostico_silenciado

    ingreso.save(update_fields=['diagnostico_silenciado', 'actualizado'])

    codigo = ingreso.codigo_equipo
    if ingreso.diagnostico_silenciado:
        messages.success(
            request,
            f'🔕 Alerta silenciada para el equipo {codigo}. '
            f'Se reactivará automáticamente cuando cambie el estado del equipo.'
        )
    else:
        messages.success(
            request,
            f'🔔 Alerta de diagnóstico reactivada para el equipo {codigo}.'
        )

    next_url = request.POST.get('next', '')
    if next_url:
        return redirect(next_url)
    return redirect('econotec:bienvenida')


# ═════════════════════════════════════════════════════════════════
# API Perfil (Gamificación)
# ═════════════════════════════════════════════════════════════════

COLORES_PERFIL_ASESOR = {
    '#0d47a1': 'Azul',
    '#ec4899': 'Rosa',
    '#c62828': 'Rojo',
    '#f97618': 'Naranja',
    '#2e7d32': 'Verde',
    '#f9c74f': 'Amarillo',
}


@login_required
def api_perfil(request):
    user = request.user

    if es_asesor(user) and not es_tecnico(user) and not user.is_superuser:
        actividad, _ = UsuarioActividad.objects.get_or_create(user=user)
        color = actividad.perfil_color_asesor
        if color not in COLORES_PERFIL_ASESOR:
            color = '#0d47a1'

        return JsonResponse({
            'username': user.username,
            'nombre': user.first_name or user.username,
            'email': user.email or '',
            'tipo_perfil': 'asesor',
            'rol': 'Asesor registrado',
            'nivel': 'Asesor registrado',
            'color': color,
            'colores_disponibles': COLORES_PERFIL_ASESOR,
            'ingresos': 0,
            'salidas_buenas': 0,
            'salidas_producto': 0,
            'salidas_malas': 0,
            'total': 0,
            'proximo': None,
        })
    
    # Verificar si el usuario tiene una fecha de reinicio
    fecha_reinicio = None
    if hasattr(user, 'actividad') and user.actividad.fecha_reinicio_perfil:
        fecha_reinicio = user.actividad.fecha_reinicio_perfil

    # Base querysets
    #
    # IMPORTANTE (regla del negocio): el NIVEL del técnico se calcula SOLO por
    # las SALIDAS que él reparó (campo `tecnico_reparo`), NO por los ingresos.
    # Quien marca la salida asume la responsabilidad del resultado:
    #   • salida buena  → suma
    #   • salida mala    → resta
    #   • garantía       → resta doble
    # Los ingresos se siguen mostrando como dato informativo, pero ya NO cuentan
    # para subir de nivel.
    ingresos_qs = IngresoEquipo.objects.filter(registrado_por=user)
    salidas_qs = SalidaEquipo.objects.filter(tecnico_reparo=user)
    ventas_producto_qs = IngresoEquipo.objects.filter(
        sede='ventas',
        tecnico_encargado=user,
    )

    if fecha_reinicio:
        ingresos_qs = ingresos_qs.filter(creado__gte=fecha_reinicio)
        salidas_qs = salidas_qs.filter(creado__gte=fecha_reinicio)
        ventas_producto_qs = ventas_producto_qs.filter(creado__gte=fecha_reinicio)

    # Ingresos registrados por el usuario (solo informativo, no suma nivel)
    ingresos_count = ingresos_qs.count()
    salidas_producto = ventas_producto_qs.count()
    
    # Salidas buenas positivas (reparadas por el técnico)
    salidas_buenas = salidas_qs.filter(
        estado_reparacion__in=SALIDA_BUENA_ESTADOS
    ).count()
    
    # Salidas negativas (restan 1 punto)
    salidas_malas = salidas_qs.filter(
        estado_reparacion__in=SALIDA_MALA_ESTADOS
    ).count()
    
    # Salidas por garantía (restan 2 puntos)
    salidas_garantia = salidas_qs.filter(
        estado_reparacion__in=SALIDA_GARANTIA_ESTADOS
    ).count()
    
    # Calcular total (no puede ser menor a 0).
    # Las ventas de producto cuentan como salida positiva de producto: +1 cada una.
    # Las salidas buenas positivas valen más para equilibrar el perfil.
    total_operaciones = calcular_puntaje_gamificacion(
        salidas_buenas,
        salidas_producto,
        salidas_malas,
        salidas_garantia,
    )
    
    # Gamificación
    if total_operaciones <= 49:
        nivel = 'Novato'
        color = '#8e8e8e' # Gris
        proximo = 50
    elif total_operaciones <= 99:
        nivel = 'Intermedio'
        color = '#cd7f32' # Bronce
        proximo = 100
    elif total_operaciones <= 499:
        nivel = 'Avanzado'
        color = '#c0c0c0' # Plata
        proximo = 500
    elif total_operaciones <= 999:
        nivel = 'Experto'
        color = '#ffd700' # Oro
        proximo = 1000
    elif total_operaciones <= 3999:
        nivel = 'Maestro'
        color = '#b9f2ff' # Diamante brillante
        proximo = 4000
    else:
        nivel = 'God Tec Econotec'
        color = 'linear-gradient(45deg, #FFD700, #ff8c00)' # Oro
        proximo = None
        
    return JsonResponse({
        'username': user.username,
        'nombre': user.first_name or user.username,
        'email': user.email or '',
        'tipo_perfil': 'tecnico',
        'ingresos': ingresos_count,
        'salidas_buenas': salidas_buenas,
        'salidas_producto': salidas_producto,
        'salidas_malas': salidas_malas,
        'total': total_operaciones,
        'nivel': nivel,
        'color': color,
        'proximo': proximo
    })


@login_required
@require_POST
def api_perfil_color(request):
    user = request.user
    if not (es_asesor(user) and not es_tecnico(user) and not user.is_superuser):
        return JsonResponse({'ok': False, 'error': 'No autorizado.'}, status=403)

    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except json.JSONDecodeError:
        payload = {}

    color = (payload.get('color') or '').strip()
    if color not in COLORES_PERFIL_ASESOR:
        return JsonResponse({'ok': False, 'error': 'Color no permitido.'}, status=400)

    actividad, _ = UsuarioActividad.objects.get_or_create(user=user)
    actividad.perfil_color_asesor = color
    actividad.save(update_fields=['perfil_color_asesor'])
    return JsonResponse({'ok': True, 'color': color})
