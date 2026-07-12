"""
Vistas del Registro Administrativo: dashboard de egresos/ingresos del taller.
Solo accesible por administradores.
"""
from datetime import date
from decimal import Decimal
from io import BytesIO
import json

from django.contrib import messages
from django.db.models import Count, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import EgresoForm
from .gamificacion import (
    SALIDA_BUENA_ESTADOS,
    SALIDA_GARANTIA_ESTADOS,
    SALIDA_MALA_ESTADOS,
    calcular_puntaje_gamificacion,
)
from .busqueda import filtrar_objetos_normalizado, texto_salida_busqueda, total_resultados
from .models import IngresoEquipo, SalidaEquipo, Abono, Egreso, CategoriaEgreso, Cliente, AvisoPanel
from .permisos import admin_requerido, tecnico_requerido


MESES_ES = [
    '', 'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
    'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre',
]


def _ingresos_dinero_mes(year, month):
    """Suma de dinero recibido en el mes (anticipos + abonos + cobros finales)."""
    anticipos = IngresoEquipo.objects.filter(
        fecha_ingreso__year=year, fecha_ingreso__month=month,
    ).aggregate(s=Sum('abono_anticipo'))['s'] or Decimal('0.00')

    diagnosticos_rapidos = IngresoEquipo.objects.filter(
        fecha_ingreso__year=year, fecha_ingreso__month=month,
        diagnostico_inmediato='si'
    ).aggregate(s=Sum('valor_diagnostico'))['s'] or Decimal('0.00')

    abonos = Abono.objects.filter(
        fecha__year=year, fecha__month=month,
    ).aggregate(s=Sum('monto'))['s'] or Decimal('0.00')

    salidas_mes = SalidaEquipo.objects.filter(
        fecha_salida__year=year, fecha_salida__month=month,
    )
    
    # Reparaciones (todo menos ventas)
    cobros_finales = salidas_mes.exclude(
        estado_reparacion='cliente_no_acepta'
    ).exclude(
        ingreso__sede='ventas'
    ).aggregate(s=Sum('valor_final_cobrado'))['s'] or Decimal('0.00')

    # Ventas de producto
    cobros_ventas = IngresoEquipo.objects.filter(
        fecha_ingreso__year=year, fecha_ingreso__month=month,
        sede='ventas'
    ).aggregate(s=Sum('valor_acordado'))['s'] or Decimal('0.00')

    cobros_diagnostico = salidas_mes.filter(
        estado_reparacion='cliente_no_acepta'
    ).aggregate(s=Sum('valor_final_cobrado'))['s'] or Decimal('0.00')

    return {
        'anticipos': anticipos,
        'diagnosticos_rapidos': diagnosticos_rapidos,
        'abonos': abonos,
        'cobros_finales': cobros_finales,
        'cobros_ventas': cobros_ventas,
        'cobros_diagnostico': cobros_diagnostico,
        'total': anticipos + diagnosticos_rapidos + abonos + cobros_finales + cobros_ventas + cobros_diagnostico,
    }


def _egresos_mes(year, month):
    return Egreso.objects.filter(
        fecha__year=year, fecha__month=month,
    ).aggregate(s=Sum('monto'))['s'] or Decimal('0.00')


@admin_requerido
def admin_dashboard(request):
    """Dashboard financiero mensual."""
    hoy = date.today()
    year = int(request.GET.get('ano') or hoy.year)
    month = int(request.GET.get('mes') or hoy.month)

    dinero_in = _ingresos_dinero_mes(year, month)
    egresos_total = _egresos_mes(year, month)
    utilidad = dinero_in['total'] - egresos_total

    # Equipos del mes
    equipos_ingresados = IngresoEquipo.objects.filter(
        fecha_ingreso__year=year, fecha_ingreso__month=month,
    ).count()
    equipos_entregados = SalidaEquipo.objects.filter(
        fecha_salida__year=year, fecha_salida__month=month,
    ).count()

    # Desglose por tipo de salida
    salidas_por_estado = (
        SalidaEquipo.objects
        .filter(fecha_salida__year=year, fecha_salida__month=month)
        .values('estado_reparacion')
        .annotate(total=Sum('valor_final_cobrado'), count=Sum('id'))
    )
    salidas_por_estado = (
        SalidaEquipo.objects
        .filter(fecha_salida__year=year, fecha_salida__month=month)
        .values('estado_reparacion')
        .annotate(total=Sum('valor_final_cobrado'), count=Count('id'))
    )
    map_estados = dict(SalidaEquipo.ESTADO_REPARACION)
    salidas_resumen = [
        {
            'estado': map_estados.get(s['estado_reparacion'], s['estado_reparacion']),
            'count': s['count'],
            'total': s['total'] or Decimal('0.00'),
        }
        for s in salidas_por_estado
    ]

    # Bodegaje: totals for this month (based on actual retiro fecha)
    bodegaje_cobrado = SalidaEquipo.objects.filter(
        fecha_retiro_real__year=year, fecha_retiro_real__month=month,
        bodegaje_monto_congelado__gt=0, bodegaje_aplicado_al_pago=True,
    ).aggregate(s=Sum('bodegaje_monto_congelado'))['s'] or Decimal('0.00')
    bodegaje_perdonado = SalidaEquipo.objects.filter(
        fecha_retiro_real__year=year, fecha_retiro_real__month=month,
        bodegaje_monto_congelado__gt=0, bodegaje_aplicado_al_pago=False,
    ).aggregate(s=Sum('bodegaje_monto_congelado'))['s'] or Decimal('0.00')

    bodegaje_cobrado_count = SalidaEquipo.objects.filter(
        fecha_retiro_real__year=year, fecha_retiro_real__month=month,
        bodegaje_monto_congelado__gt=0, bodegaje_aplicado_al_pago=True,
    ).count()
    bodegaje_perdonado_count = SalidaEquipo.objects.filter(
        fecha_retiro_real__year=year, fecha_retiro_real__month=month,
        bodegaje_monto_congelado__gt=0, bodegaje_aplicado_al_pago=False,
    ).count()

    # Facturas en salidas del mes
    facturas_salidas_mes = SalidaEquipo.objects.filter(
        fecha_salida__year=year,
        fecha_salida__month=month,
    )
    facturas_si_count = facturas_salidas_mes.filter(factura_realizada='si').count()
    facturas_no_count = facturas_salidas_mes.filter(factura_realizada='no').count()

    # Egresos por categoría
    egresos_por_cat = (
        Egreso.objects
        .filter(fecha__year=year, fecha__month=month)
        .values('categoria__nombre', 'categoria__color', 'categoria__icono')
        .annotate(total=Sum('monto'), count=Count('id'))
        .order_by('-total')
    )

    # Lista de años con datos
    anos_disp = sorted(set(
        list(IngresoEquipo.objects.dates('fecha_ingreso', 'year').values_list('fecha_ingreso__year', flat=True)) +
        list(Egreso.objects.dates('fecha', 'year').values_list('fecha__year', flat=True))
    ), reverse=True)
    if not anos_disp:
        anos_disp = [hoy.year]

    # Datos para gráficos
    # 1. Ganancias por Técnico (Gráfico circular)
    ganancias_qs = (
        SalidaEquipo.objects
        .filter(fecha_salida__year=year, fecha_salida__month=month, ingreso__tecnico_encargado__isnull=False)
        .values('ingreso__tecnico_encargado__first_name', 'ingreso__tecnico_encargado__username')
        .annotate(total=Sum('valor_final_cobrado'))
        .filter(total__gt=0)
        .order_by('-total')
    )
    ganancias_tecnicos_labels = [g['ingreso__tecnico_encargado__first_name'] or g['ingreso__tecnico_encargado__username'] for g in ganancias_qs]
    ganancias_tecnicos_data = [float(g['total']) for g in ganancias_qs]

    # 2. Tendencia Anual (Gráfico de líneas y columnas)
    tendencia_ingresos = []
    tendencia_egresos = []
    for m in range(1, 13):
        tendencia_ingresos.append(float(_ingresos_dinero_mes(year, m)['total']))
        tendencia_egresos.append(float(_egresos_mes(year, m)))

    # 3. Egresos por categoría (Gráfico de columnas)
    column_egresos_labels = [e['categoria__nombre'] for e in egresos_por_cat]
    column_egresos_data = [float(e['total']) for e in egresos_por_cat]

    # Usuarios en línea
    from django.contrib.auth.models import User
    from django.utils import timezone
    from datetime import timedelta
    
    limite_online = timezone.now() - timedelta(minutes=5)
    usuarios_activos = User.objects.select_related('actividad').order_by('-actividad__ultima_conexion')
    lista_usuarios = []
    for u in usuarios_activos:
        en_linea = False
        ultima = getattr(u, 'actividad', None)
        if ultima and ultima.ultima_conexion >= limite_online:
            en_linea = True
        lista_usuarios.append({
            'user': u,
            'en_linea': en_linea,
            'ultima_conexion': ultima.ultima_conexion if ultima else None
        })

    return render(request, 'admin_panel/dashboard.html', {
        'year': year,
        'month': month,
        'mes_nombre': MESES_ES[month],
        'hoy': hoy,
        'anos_disp': anos_disp,
        'lista_usuarios': lista_usuarios,
        'dinero_in': dinero_in,
        'egresos_total': egresos_total,
        'utilidad': utilidad,
        'equipos_ingresados': equipos_ingresados,
        'equipos_entregados': equipos_entregados,
        'salidas_resumen': salidas_resumen,
        'egresos_por_cat': egresos_por_cat,
        'bodegaje_cobrado': bodegaje_cobrado,
        'bodegaje_perdonado': bodegaje_perdonado,
        'bodegaje_cobrado_count': bodegaje_cobrado_count,
        'bodegaje_perdonado_count': bodegaje_perdonado_count,
        'facturas_si_count': facturas_si_count,
        'facturas_no_count': facturas_no_count,
        'anos_disp': anos_disp,
        'meses_es': MESES_ES,
        'chart_ganancias_labels': json.dumps(ganancias_tecnicos_labels),
        'chart_ganancias_data': json.dumps(ganancias_tecnicos_data),
        'chart_tendencia_labels': json.dumps(MESES_ES[1:]),
        'chart_tendencia_ingresos': json.dumps(tendencia_ingresos),
        'chart_tendencia_egresos': json.dumps(tendencia_egresos),
        'chart_egresos_cat_labels': json.dumps(column_egresos_labels),
        'chart_egresos_cat_data': json.dumps(column_egresos_data),
    })


@tecnico_requerido
def salida_facturas_lista(request):
    """Listado de salidas que sí tienen factura realizada."""
    hoy = date.today()
    year = int(request.GET.get('ano') or hoy.year)
    mes_param = (request.GET.get('mes') or str(hoy.month)).strip().lower()
    month = None if mes_param == 'todos' else int(mes_param)
    q = (request.GET.get('q') or '').strip()

    base_qs = (
        SalidaEquipo.objects
        .select_related('ingreso', 'ingreso__cliente', 'registrado_por', 'tecnico_reparo')
        .filter(fecha_salida__year=year, factura_realizada='si')
        .order_by('-fecha_salida', '-creado')
    )

    if month is not None:
        base_qs = base_qs.filter(fecha_salida__month=month)

    total_periodo = base_qs.count()
    qs = base_qs
    qs = filtrar_objetos_normalizado(qs, q, texto_salida_busqueda)

    anos_disp = sorted(set(
        list(SalidaEquipo.objects.dates('fecha_salida', 'year').values_list('fecha_salida__year', flat=True))
    ), reverse=True)
    if not anos_disp:
        anos_disp = [hoy.year]

    return render(request, 'admin_panel/facturas_salidas.html', {
        'year': year,
        'month': month,
        'mes_param': mes_param,
        'mes_nombre': MESES_ES[month] if month else 'Todos los meses',
        'meses_es': MESES_ES,
        'anos_disp': anos_disp,
        'q': q,
        'salidas': qs,
        'total': total_resultados(qs),
        'total_periodo': total_periodo,
    })


@admin_requerido
def admin_bodegajes(request):
    """Lista administrativa de bodegajes (cobrados y no cobrados) por mes."""
    hoy = date.today()
    year = int(request.GET.get('ano') or hoy.year)
    month = int(request.GET.get('mes') or hoy.month)

    base_qs = SalidaEquipo.objects.select_related('ingreso', 'ingreso__cliente')
    cobrados = base_qs.filter(
        fecha_retiro_real__year=year, fecha_retiro_real__month=month,
        bodegaje_monto_congelado__gt=0, bodegaje_aplicado_al_pago=True,
    ).order_by('-fecha_retiro_real')
    no_cobrados = base_qs.filter(
        fecha_retiro_real__year=year, fecha_retiro_real__month=month,
        bodegaje_monto_congelado__gt=0, bodegaje_aplicado_al_pago=False,
    ).order_by('-fecha_retiro_real')

    bodegaje_cobrado = cobrados.aggregate(s=Sum('bodegaje_monto_congelado'))['s'] or Decimal('0.00')
    bodegaje_perdonado = no_cobrados.aggregate(s=Sum('bodegaje_monto_congelado'))['s'] or Decimal('0.00')

    bodegaje_cobrado_count = cobrados.count()
    bodegaje_perdonado_count = no_cobrados.count()

    # Lista de años disponibles (reusar lógica)
    anos_disp = sorted(set(
        list(IngresoEquipo.objects.dates('fecha_ingreso', 'year').values_list('fecha_ingreso__year', flat=True)) +
        list(Egreso.objects.dates('fecha', 'year').values_list('fecha__year', flat=True))
    ), reverse=True)
    if not anos_disp:
        anos_disp = [hoy.year]

    return render(request, 'admin_panel/bodegajes.html', {
        'year': year,
        'month': month,
        'mes_nombre': MESES_ES[month],
        'cobrados': cobrados,
        'no_cobrados': no_cobrados,
        'bodegaje_cobrado': bodegaje_cobrado,
        'bodegaje_perdonado': bodegaje_perdonado,
        'bodegaje_cobrado_count': bodegaje_cobrado_count,
        'bodegaje_perdonado_count': bodegaje_perdonado_count,
        'anos_disp': anos_disp,
        'meses_es': MESES_ES,
    })


@admin_requerido
def admin_activos_bodegaje(request):
    """Manejo de equipos en bodegaje activo y chatarrerización."""
    from .alertas import salidas_bodegaje_qs
    import json
    from django.http import JsonResponse
    
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            accion = data.get('accion')
            salida_id = data.get('salida_id')
            
            salida = SalidaEquipo.objects.get(pk=salida_id)
            if accion == 'retirado':
                salida.estado_reparacion = 'retirado'
                salida.fecha_retiro_real = date.today()
            elif accion == 'chatarrerizacion':
                salida.estado_reparacion = 'chatarrerizacion'
                salida.fecha_retiro_real = date.today()  # Detiene el bodegaje
                
            salida.save()
            return JsonResponse({'status': 'ok'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'msg': str(e)})

    activos_qs = salidas_bodegaje_qs(incluir_silenciados=True).select_related('ingreso', 'ingreso__cliente')
    from .alertas import whatsapp_link_bodegaje
    
    # Procesar bodegaje para la vista
    activos = []
    hoy = date.today()
    for s in activos_qs:
        bod = s.calcular_bodegaje()
        if bod['dias'] > 0:
            dias_totales = (hoy - s.fecha_salida).days if s.fecha_salida else 0
            activos.append({
                'salida': s,
                'dias_bodegaje': bod['dias'],
                'monto_bodegaje': bod['monto'],
                'dias_totales': dias_totales,
                'wa_link': whatsapp_link_bodegaje(s),
            })
            
    chatarrerizacion = SalidaEquipo.objects.filter(
        estado_reparacion='chatarrerizacion'
    ).select_related('ingreso', 'ingreso__cliente').order_by('-fecha_retiro_real')
    
    return render(request, 'admin_panel/activos_bodegaje.html', {
        'activos': activos,
        'chatarrerizacion': chatarrerizacion,
        'count_chatarrerizacion': chatarrerizacion.count(),
    })

@admin_requerido
def egresos_lista(request):
    cat_filtro = (request.GET.get('cat') or '').strip()
    ano_filtro = (request.GET.get('ano') or '').strip()
    mes_filtro = (request.GET.get('mes') or '').strip()

    qs = Egreso.objects.select_related('categoria', 'registrado_por').order_by('-fecha', '-creado')
    if cat_filtro and cat_filtro.isdigit():
        qs = qs.filter(categoria_id=int(cat_filtro))
    if ano_filtro and ano_filtro.isdigit():
        qs = qs.filter(fecha__year=int(ano_filtro))
    if mes_filtro and mes_filtro.isdigit():
        qs = qs.filter(fecha__month=int(mes_filtro))

    total = qs.aggregate(s=Sum('monto'))['s'] or Decimal('0.00')

    return render(request, 'admin_panel/egresos_lista.html', {
        'egresos': qs,
        'total': total,
        'categorias': CategoriaEgreso.objects.filter(activo=True),
        'cat_filtro': cat_filtro,
        'ano_filtro': ano_filtro,
        'mes_filtro': mes_filtro,
        'meses_es': MESES_ES,
    })


@admin_requerido
def egreso_crear(request):
    if request.method == 'POST':
        form = EgresoForm(request.POST)
        if form.is_valid():
            egreso = form.save(commit=False)
            egreso.registrado_por = request.user
            egreso.save()
            messages.success(request, f'Egreso registrado: ${egreso.monto}.')
            return redirect('econotec:admin_egresos_lista')
    else:
        form = EgresoForm(initial={'fecha': date.today()})
    return render(request, 'admin_panel/egreso_form.html', {
        'form': form,
        'modo': 'crear',
        'titulo': 'Nuevo Egreso',
    })


@admin_requerido
def egreso_editar(request, pk):
    egreso = get_object_or_404(Egreso, pk=pk)
    if request.method == 'POST':
        form = EgresoForm(request.POST, instance=egreso)
        if form.is_valid():
            form.save()
            messages.success(request, 'Egreso actualizado.')
            return redirect('econotec:admin_egresos_lista')
    else:
        form = EgresoForm(instance=egreso)
    return render(request, 'admin_panel/egreso_form.html', {
        'form': form,
        'egreso': egreso,
        'modo': 'editar',
        'titulo': f'Editar egreso: {egreso.concepto}',
    })


@admin_requerido
@require_POST
def egreso_eliminar(request, pk):
    egreso = get_object_or_404(Egreso, pk=pk)
    concepto = egreso.concepto
    egreso.delete()
    messages.success(request, f'Egreso "{concepto}" eliminado.')
    return redirect('econotec:admin_egresos_lista')


# ─────────────────────────────────────────────────────────
# Exportación
# ─────────────────────────────────────────────────────────

@admin_requerido
def export_reporte_mes(request):
    """Exporta el reporte mensual (ingresos vs egresos) a Excel."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    hoy = date.today()
    year = int(request.GET.get('ano') or hoy.year)
    month = int(request.GET.get('mes') or hoy.month)

    dinero_in = _ingresos_dinero_mes(year, month)
    egresos_total = _egresos_mes(year, month)
    utilidad = dinero_in['total'] - egresos_total

    bodegaje_cobrado = SalidaEquipo.objects.filter(
        fecha_retiro_real__year=year, fecha_retiro_real__month=month,
        bodegaje_monto_congelado__gt=0, bodegaje_aplicado_al_pago=True,
    ).aggregate(s=Sum('bodegaje_monto_congelado'))['s'] or Decimal('0.00')
    
    bodegaje_perdonado = SalidaEquipo.objects.filter(
        fecha_retiro_real__year=year, fecha_retiro_real__month=month,
        bodegaje_monto_congelado__gt=0, bodegaje_aplicado_al_pago=False,
    ).aggregate(s=Sum('bodegaje_monto_congelado'))['s'] or Decimal('0.00')

    wb = Workbook()
    ws = wb.active
    ws.title = f'Reporte {MESES_ES[month][:3]}-{year}'

    ws.merge_cells('A1:D1')
    title = ws.cell(row=1, column=1,
                    value=f'Reporte financiero — {MESES_ES[month]} {year} — Econotec')
    title.font = Font(bold=True, size=14, color='F97618')
    title.alignment = Alignment(horizontal='center')
    ws.row_dimensions[1].height = 26

    rows = [
        ('Anticipos recibidos', dinero_in['anticipos']),
        ('Diagnósticos rápidos (adicionales)', dinero_in['diagnosticos_rapidos']),
        ('Abonos posteriores', dinero_in['abonos']),
        ('Cobros en salida (reparaciones)', dinero_in['cobros_finales']),
        ('Ventas de productos', dinero_in['cobros_ventas']),
        ('Cobros por diagnóstico (no reparado)', dinero_in['cobros_diagnostico']),
        ('Bodegaje cobrado (en retiros)', bodegaje_cobrado),
        ('N° casos bodegaje cobrados', SalidaEquipo.objects.filter(
            fecha_retiro_real__year=year, fecha_retiro_real__month=month,
            bodegaje_monto_congelado__gt=0, bodegaje_aplicado_al_pago=True,
        ).count()),
        ('Bodegaje no cobrado / perdonado', bodegaje_perdonado),
        ('N° casos bodegaje no cobrados', SalidaEquipo.objects.filter(
            fecha_retiro_real__year=year, fecha_retiro_real__month=month,
            bodegaje_monto_congelado__gt=0, bodegaje_aplicado_al_pago=False,
        ).count()),
        ('TOTAL DINERO RECIBIDO', dinero_in['total']),
        ('', None),
        ('TOTAL EGRESOS', egresos_total),
        ('', None),
        ('UTILIDAD DEL MES', utilidad),
    ]
    for r, (label, value) in enumerate(rows, start=3):
        ws.cell(row=r, column=1, value=label).font = Font(bold=True)
        if value is not None:
            ws.cell(row=r, column=2, value=float(value))

    ws.column_dimensions['A'].width = 32
    ws.column_dimensions['B'].width = 18

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)

    response = HttpResponse(
        buf.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = (
        f'attachment; filename="reporte_{year}_{month:02d}_econotec.xlsx"'
    )
    return response


@admin_requerido
def export_egresos(request):
    """Exporta egresos a Excel."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    wb = Workbook()
    ws = wb.active
    ws.title = 'Egresos Econotec'

    headers = ['Fecha', 'Categoría', 'Concepto', 'Monto', 'Notas', 'Registrado por']
    for col, h in enumerate(headers, start=1):
        c = ws.cell(row=1, column=col, value=h)
        c.font = Font(bold=True, color='FFFFFF')
        c.fill = PatternFill('solid', fgColor='F97618')
        c.alignment = Alignment(horizontal='center')

    qs = Egreso.objects.select_related('categoria', 'registrado_por').order_by('-fecha')
    for row, e in enumerate(qs, start=2):
        ws.cell(row=row, column=1, value=e.fecha.strftime('%d/%m/%Y'))
        ws.cell(row=row, column=2, value=e.categoria.nombre)
        ws.cell(row=row, column=3, value=e.concepto)
        ws.cell(row=row, column=4, value=float(e.monto))
        ws.cell(row=row, column=5, value=e.notas)
        ws.cell(row=row, column=6,
                value=e.registrado_por.get_full_name() if e.registrado_por else '')

    for col in range(1, 7):
        ws.column_dimensions[chr(64 + col)].width = 22

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)

    response = HttpResponse(
        buf.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = 'attachment; filename="egresos_econotec.xlsx"'
    return response


@admin_requerido
def admin_mantenimiento_reset(request):
    """
    Vista de Mantenimiento para respaldar y borrar todos los datos transaccionales.
    """
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'download_backup':
            try:
                from openpyxl import Workbook
                from openpyxl.styles import Font
            except ImportError:
                messages.error(request, 'No se pudo generar el Excel (falta openpyxl).')
                return redirect('econotec:admin_mantenimiento_reset')
                
            wb = Workbook()
            
            # Pestaña 1: Clientes
            ws_clientes = wb.active
            ws_clientes.title = 'Clientes'
            ws_clientes.append(['ID', 'Nombres', 'Cedula', 'WhatsApp', 'Correo', 'Sector', 'Fecha Registro'])
            for col in range(1, 8): ws_clientes.cell(row=1, column=col).font = Font(bold=True)
            for c in Cliente.objects.all():
                ws_clientes.append([c.id, c.nombres, c.cedula, c.whatsapp, c.correo, c.sector, str(c.creado.date())])

            # Pestaña 2: Equipos
            ws_equipos = wb.create_sheet(title='Equipos')
            ws_equipos.append(['Codigo', 'Cliente', 'Tipo', 'Marca', 'Modelo', 'Serie', 'Sede', 'Estado', 'Valor Acordado', 'Fecha Ingreso'])
            for col in range(1, 11): ws_equipos.cell(row=1, column=col).font = Font(bold=True)
            for eq in IngresoEquipo.objects.select_related('cliente').all():
                ws_equipos.append([
                    eq.codigo_equipo, eq.cliente.nombres, eq.tipo_equipo, eq.marca, eq.modelo_serie, eq.serie,
                    eq.get_sede_display(), eq.get_estado_display(), 
                    float(eq.valor_acordado or 0), str(eq.fecha_ingreso)
                ])
                
            # Pestaña 3: Pagos
            ws_pagos = wb.create_sheet(title='Pagos (Abonos)')
            ws_pagos.append(['Recibo', 'Equipo', 'Cliente', 'Monto', 'Metodo', 'Fecha'])
            for col in range(1, 7): ws_pagos.cell(row=1, column=col).font = Font(bold=True)
            for p in Abono.objects.select_related('ingreso__cliente').all():
                ws_pagos.append([
                    p.numero_recibo, p.ingreso.codigo_equipo, p.ingreso.cliente.nombres, 
                    float(p.monto), p.get_metodo_display(), str(p.fecha)
                ])

            # Pestaña 4: Egresos
            ws_egresos = wb.create_sheet(title='Egresos')
            ws_egresos.append(['Concepto', 'Categoria', 'Monto', 'Fecha'])
            for col in range(1, 5): ws_egresos.cell(row=1, column=col).font = Font(bold=True)
            for eg in Egreso.objects.select_related('categoria').all():
                ws_egresos.append([
                    eg.concepto, eg.categoria.nombre if eg.categoria else '', 
                    float(eg.monto), str(eg.fecha)
                ])

            # Pestaña 5: Bodegaje
            from .alertas import salidas_bodegaje_qs
            ws_bodegaje = wb.create_sheet(title='Bodegaje')
            ws_bodegaje.append(['Equipo', 'Cliente', 'Sede', 'Dias en Bodega', 'Monto Acumulado', 'Fecha Salida'])
            for col in range(1, 7): ws_bodegaje.cell(row=1, column=col).font = Font(bold=True)
            for s in salidas_bodegaje_qs(incluir_silenciados=True).select_related('ingreso__cliente'):
                bod = s.calcular_bodegaje()
                if bod['dias'] > 0:
                    ws_bodegaje.append([
                        s.ingreso.codigo_equipo, s.ingreso.cliente.nombres, 
                        s.ingreso.get_sede_display(), bod['dias'], 
                        float(bod['monto']), str(s.fecha_salida)
                    ])

            # Pestaña 6: Chatarrizacion
            ws_chatarra = wb.create_sheet(title='Chatarrizados')
            ws_chatarra.append(['Equipo', 'Cliente', 'Sede', 'Fecha Salida', 'Fecha Chatarr.'])
            for col in range(1, 6): ws_chatarra.cell(row=1, column=col).font = Font(bold=True)
            for s in SalidaEquipo.objects.filter(estado_reparacion='chatarrerizacion').select_related('ingreso__cliente'):
                ws_chatarra.append([
                    s.ingreso.codigo_equipo, s.ingreso.cliente.nombres, 
                    s.ingreso.get_sede_display(), str(s.fecha_salida), str(s.fecha_retiro_real)
                ])

            buf = BytesIO()
            wb.save(buf)
            buf.seek(0)
            
            response = HttpResponse(
                buf.getvalue(),
                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            )
            filename = f"econotec_full_backup_{date.today().strftime('%Y%m%d')}.xlsx"
            response['Content-Disposition'] = f'attachment; filename="{filename}"'
            return response
            
        elif action == 'reset_all':
            admin_password = request.POST.get('admin_password', '')
            if not request.user.check_password(admin_password):
                messages.error(request, 'Contraseña de administrador incorrecta. Se ha cancelado el reinicio por seguridad.')
                return redirect('econotec:admin_mantenimiento_reset')
                
            # Borrar en orden inverso de dependencias para no violar foreign keys
            Egreso.objects.all().delete()
            SalidaEquipo.objects.all().delete()
            Abono.objects.all().delete()
            IngresoEquipo.objects.all().delete()
            Cliente.objects.all().delete()
            
            messages.success(request, '¡La base de datos transaccional ha sido reseteada por completo! Los correlativos de G y U empezarán desde 1.')
            return redirect('econotec:admin_dashboard')
            
    return render(request, 'admin/mantenimiento_confirmar.html')


# ═════════════════════════════════════════════════════════════════
# Gamificación - Reseteo y Exportación
# ═════════════════════════════════════════════════════════════════
from django.contrib.auth.models import User
from django.utils import timezone
from .models import UsuarioActividad

def _obtener_estadisticas_gamificacion():
    stats = []
    usuarios = User.objects.filter(is_active=True, groups__name__in=['Tecnicos', 'Asesores']).distinct()
    
    for u in usuarios:
        fecha_reinicio = None
        if hasattr(u, 'actividad') and u.actividad.fecha_reinicio_perfil:
            fecha_reinicio = u.actividad.fecha_reinicio_perfil

        ingresos_qs = IngresoEquipo.objects.filter(registrado_por=u)
        # El nivel se calcula por las salidas que el técnico REPARÓ, no por
        # las que registró ni por los ingresos (misma regla que api_perfil).
        salidas_qs = SalidaEquipo.objects.filter(tecnico_reparo=u)
        ventas_producto_qs = IngresoEquipo.objects.filter(
            sede='ventas',
            tecnico_encargado=u,
        )

        if fecha_reinicio:
            ingresos_qs = ingresos_qs.filter(creado__gte=fecha_reinicio)
            salidas_qs = salidas_qs.filter(creado__gte=fecha_reinicio)
            ventas_producto_qs = ventas_producto_qs.filter(creado__gte=fecha_reinicio)

        ingresos = ingresos_qs.count()
        ventas_producto = ventas_producto_qs.count()
        salidas_buenas = salidas_qs.filter(estado_reparacion__in=SALIDA_BUENA_ESTADOS).count()
        salidas_malas = salidas_qs.filter(estado_reparacion__in=SALIDA_MALA_ESTADOS).count()
        salidas_garantia = salidas_qs.filter(estado_reparacion__in=SALIDA_GARANTIA_ESTADOS).count()
        
        total = calcular_puntaje_gamificacion(
            salidas_buenas,
            ventas_producto,
            salidas_malas,
            salidas_garantia,
        )
        
        if total <= 49:
            nivel = 'Novato'
        elif total <= 99:
            nivel = 'Intermedio'
        elif total <= 499:
            nivel = 'Avanzado'
        elif total <= 999:
            nivel = 'Experto'
        elif total <= 3999:
            nivel = 'Maestro'
        else:
            nivel = 'God Tec Econotec'
            
        stats.append({
            'usuario': f"{u.first_name} {u.last_name}".strip() or u.username,
            'ingresos': ingresos,
            'buenas': salidas_buenas,
            'producto': ventas_producto,
            'malas': salidas_malas,
            'total': total,
            'nivel': nivel
        })
    
    # Ordenar por puntaje total descendente
    stats.sort(key=lambda x: x['total'], reverse=True)
    return stats

@admin_requerido
@require_POST
def admin_perfiles_reiniciar(request):
    password = request.POST.get('password', '')
    if not request.user.check_password(password):
        messages.error(request, 'Contraseña incorrecta. No se han reiniciado los perfiles.')
        return redirect('econotec:admin_dashboard')
        
    ahora = timezone.now()
    usuarios = User.objects.filter(groups__name__in=['Tecnicos', 'Asesores']).distinct()
    for u in usuarios:
        act, created = UsuarioActividad.objects.get_or_create(user=u)
        act.fecha_reinicio_perfil = ahora
        act.save()
        
    messages.success(request, '¡Perfiles gamificados reiniciados con éxito! Ahora todos empiezan desde cero.')
    return redirect('econotec:admin_dashboard')

@admin_requerido
def admin_perfiles_exportar(request, formato):
    stats = _obtener_estadisticas_gamificacion()
    fecha_str = timezone.now().strftime("%Y%m%d_%H%M")
    
    if formato == 'excel':
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Ranking Perfiles"
        
        # Headers
        headers = ['Posición', 'Técnico / Asesor', 'Ingresos', 'Salidas Buenas', 'Salida de Producto', 'Salidas Malas', 'Puntaje Total', 'Nivel Alcanzado']
        for col_num, header in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col_num)
            cell.value = header
            cell.font = openpyxl.styles.Font(bold=True)
            
        # Data
        for row_num, stat in enumerate(stats, 2):
            ws.cell(row=row_num, column=1, value=row_num - 1)
            ws.cell(row=row_num, column=2, value=stat['usuario'])
            ws.cell(row=row_num, column=3, value=stat['ingresos'])
            ws.cell(row=row_num, column=4, value=stat['buenas'])
            ws.cell(row=row_num, column=5, value=stat['producto'])
            ws.cell(row=row_num, column=6, value=stat['malas'])
            ws.cell(row=row_num, column=7, value=stat['total'])
            ws.cell(row=row_num, column=8, value=stat['nivel'])
            
        response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition'] = f'attachment; filename=Ranking_Perfiles_{fecha_str}.xlsx'
        wb.save(response)
        return response
        
    elif formato == 'pdf':
        from reportlab.pdfgen import canvas
        from reportlab.lib.pagesizes import A4
        
        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename=Ranking_Perfiles_{fecha_str}.pdf'
        
        c = canvas.Canvas(response, pagesize=A4)
        y = 800
        
        c.setFont("Helvetica-Bold", 16)
        c.drawString(50, y, "Econotec - Ranking de Productividad (Gamificacion)")
        y -= 30
        
        c.setFont("Helvetica", 10)
        c.drawString(50, y, f"Fecha de reporte: {timezone.now().strftime('%d/%m/%Y %H:%M')}")
        y -= 40
        
        # Table Header
        c.setFont("Helvetica-Bold", 10)
        c.drawString(50, y, "Pos")
        c.drawString(90, y, "Usuario")
        c.drawString(220, y, "Ingresos")
        c.drawString(280, y, "S. Buenas")
        c.drawString(340, y, "S. Prod.")
        c.drawString(400, y, "S. Malas")
        c.drawString(460, y, "Puntos")
        c.drawString(510, y, "Nivel")
        y -= 20
        
        c.line(50, y+10, 550, y+10)
        
        c.setFont("Helvetica", 10)
        for i, stat in enumerate(stats, 1):
            if y < 50:
                c.showPage()
                y = 800
            c.drawString(50, y, str(i))
            c.drawString(90, y, str(stat['usuario'])[:25])
            c.drawString(220, y, str(stat['ingresos']))
            c.drawString(280, y, str(stat['buenas']))
            c.drawString(340, y, str(stat['producto']))
            c.drawString(400, y, str(stat['malas']))
            c.drawString(460, y, str(stat['total']))
            c.drawString(510, y, str(stat['nivel']))
            y -= 20
            
        c.save()
        return response
        
    return redirect('econotec:admin_dashboard')


# ═════════════════════════════════════════════════════════════════
# Avisos del panel principal (solo administrador)
# ═════════════════════════════════════════════════════════════════

@admin_requerido
def avisos_lista(request):
    """Lista de avisos del panel. Solo el administrador puede gestionarlos."""
    avisos = AvisoPanel.objects.select_related('creado_por').all()
    vigentes = sum(1 for a in avisos if a.vigente)
    return render(request, 'admin_panel/avisos_lista.html', {
        'avisos': avisos,
        'total': avisos.count(),
        'vigentes': vigentes,
    })


@admin_requerido
def aviso_crear(request):
    from .forms import AvisoPanelForm
    if request.method == 'POST':
        form = AvisoPanelForm(request.POST)
        if form.is_valid():
            aviso = form.save(commit=False)
            aviso.creado_por = request.user
            aviso.save()
            messages.success(request, 'Aviso creado. Se mostrará en el inicio según sus fechas.')
            return redirect('econotec:avisos_lista')
    else:
        from datetime import date as _date
        form = AvisoPanelForm(initial={
            'fecha_inicio': _date.today(),
            'fecha_fin': _date.today(),
            'activo': True,
            'tipo': 'info',
        })
    return render(request, 'admin_panel/aviso_form.html', {
        'form': form, 'modo': 'crear', 'titulo': 'Nuevo aviso',
    })


@admin_requerido
def aviso_editar(request, pk):
    from .forms import AvisoPanelForm
    aviso = get_object_or_404(AvisoPanel, pk=pk)
    if request.method == 'POST':
        form = AvisoPanelForm(request.POST, instance=aviso)
        if form.is_valid():
            form.save()
            messages.success(request, 'Aviso actualizado.')
            return redirect('econotec:avisos_lista')
    else:
        form = AvisoPanelForm(instance=aviso)
    return render(request, 'admin_panel/aviso_form.html', {
        'form': form, 'modo': 'editar', 'aviso': aviso,
        'titulo': f'Editar aviso — {aviso.titulo}',
    })


@admin_requerido
@require_POST
def aviso_eliminar(request, pk):
    aviso = get_object_or_404(AvisoPanel, pk=pk)
    aviso.delete()
    messages.success(request, 'Aviso eliminado.')
    return redirect('econotec:avisos_lista')


# ═════════════════════════════════════════════════════════════════
# Control de Registro (Auditoría) — solo administrador
# ═════════════════════════════════════════════════════════════════

@admin_requerido
def control_registro(request):
    """
    Auditoría: últimos equipos registrados y últimos pagos registrados en el
    sistema, con fecha/hora, quién los registró (asesor) y el cliente.
    Solo visible para administradores.
    """
    LIMITE = 100

    equipos = (
        IngresoEquipo.objects
        .select_related('cliente', 'registrado_por', 'tecnico_encargado')
        .order_by('-creado')[:LIMITE]
    )

    abonos = (
        Abono.objects
        .select_related('ingreso', 'ingreso__cliente', 'registrado_por')
        .order_by('-creado')[:LIMITE]
    )

    return render(request, 'admin_panel/control_registro.html', {
        'equipos': equipos,
        'abonos': abonos,
        'limite': LIMITE,
    })
