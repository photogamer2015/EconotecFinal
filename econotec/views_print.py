"""
Vistas para impresión y generación de PDF de los formularios.

Estrategia:
- "imprimir": muestra la plantilla HTML lista para imprimir (Ctrl+P del navegador,
  con CSS @media print).
- "pdf": genera un PDF descargable usando ReportLab que replica visualmente
  el formulario físico de Econotec.
"""
from io import BytesIO
from decimal import Decimal
import base64
import binascii

from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from .models import IngresoEquipo, SalidaEquipo
from .permisos import tecnico_requerido
from .qr_utils import qr_data_uri_para_ingreso, url_hoja_movil, qr_png_bytes_para_ingreso


# ═════════════════════════════════════════════════════════════════
# Versiones HTML imprimibles (para Ctrl+P o "Guardar como PDF" del navegador)
# ═════════════════════════════════════════════════════════════════

@tecnico_requerido
def ingreso_imprimir(request, pk):
    """Vista HTML lista para imprimir, con formato idéntico al papel."""
    ingreso = get_object_or_404(
        IngresoEquipo.objects.select_related('cliente'),
        pk=pk,
    )
    return render(request, 'ingresos/imprimir.html', {
        'ingreso': ingreso,
        'cliente': ingreso.cliente,
        'qr_data_uri': qr_data_uri_para_ingreso(request, ingreso),
        'qr_url': url_hoja_movil(request, ingreso),
    })


@tecnico_requerido
def ingreso_imprimir_qr(request, pk):
    """Muestra una página optimizada para imprimir 2 QRs del equipo."""
    ingreso = get_object_or_404(
        IngresoEquipo.objects.select_related('cliente'),
        pk=pk,
    )
    return render(request, 'ingresos/imprimir_qr.html', {
        'ingreso': ingreso,
        'cliente': ingreso.cliente,
        'qr_data_uri': qr_data_uri_para_ingreso(request, ingreso),
    })


@tecnico_requerido
def ingreso_qr_png(request, pk):
    """
    Descarga el código QR del equipo como imagen PNG.

    El QR es el mismo híbrido (datos embebidos + enlace a la hoja del técnico).
    Se sirve como descarga con un nombre de archivo basado en el código del
    equipo, p.ej. 'QR_Econotec_G3.png'.
    """
    ingreso = get_object_or_404(
        IngresoEquipo.objects.select_related('cliente'),
        pk=pk,
    )
    png = qr_png_bytes_para_ingreso(request, ingreso)
    response = HttpResponse(png, content_type='image/png')
    nombre = f'QR_Econotec_{ingreso.codigo_equipo}.png'
    response['Content-Disposition'] = f'attachment; filename="{nombre}"'
    return response


@tecnico_requerido
def salida_imprimir(request, pk):
    salida = get_object_or_404(
        SalidaEquipo.objects.select_related('ingreso', 'ingreso__cliente', 'tecnico_reparo')
        .prefetch_related('ingreso__abonos'),
        pk=pk,
    )
    return render(request, 'salidas/imprimir.html', {
        'salida': salida,
        'ingreso': salida.ingreso,
        'cliente': salida.ingreso.cliente,
        'mensaje_estado_salida': _mensaje_estado_salida(salida),
        'pagos_detallados': _pagos_detallados_salida(salida),
    })


def _salida_facturada_or_404(pk):
    return get_object_or_404(
        SalidaEquipo.objects.select_related('ingreso', 'ingreso__cliente', 'tecnico_reparo', 'registrado_por')
        .prefetch_related('ingreso__abonos'),
        pk=pk,
        factura_realizada='si',
    )


def _q_money(valor):
    valor = valor if valor is not None else Decimal('0.00')
    return Decimal(valor).quantize(Decimal('0.01'))


def _money_text_es(valor):
    valor = _q_money(valor)
    texto = f'{valor:,.2f}'
    texto = texto.replace(',', '\x00').replace('.', ',').replace('\x00', '.')
    return f'${texto}'


def _numero_factura_salida(salida):
    ingreso = salida.ingreso
    if ingreso.numero_factura:
        return ingreso.numero_factura
    if salida.numero_recibo:
        return salida.numero_recibo
    return f'FAC-{salida.pk:04d}'


def _descripcion_equipo_factura(ingreso):
    partes = [
        ingreso.tipo_equipo_display,
        ingreso.marca,
        ingreso.modelo_serie_detalle,
    ]
    return ' '.join(str(p).strip() for p in partes if str(p or '').strip())


def _factura_items_salida(salida):
    ingreso = salida.ingreso
    equipo = _descripcion_equipo_factura(ingreso) or ingreso.codigo_equipo
    items = []

    def agregar(descripcion, precio, detalle='', codigo=''):
        precio = _q_money(precio)
        if precio <= 0:
            return
        items.append({
            'descripcion': descripcion,
            'detalle': detalle,
            'codigo': codigo,
            'cantidad': 1,
            'precio_unitario': precio,
            'total': precio,
        })

    if salida.estado_reparacion == 'revision':
        agregar(
            f'Revisión técnica - Equipo {ingreso.codigo_equipo}',
            ingreso.valor_efectivo_a_cobrar,
            equipo,
            ingreso.codigo_equipo,
        )
    elif ingreso.reparacion_cancelada:
        descripcion = f'Revisión / diagnóstico técnico - Equipo {ingreso.codigo_equipo}'
        detalle = equipo
        if salida.tiene_valor_acordado_adicional:
            descripcion = f'Cobro adicional de finalización - Equipo {ingreso.codigo_equipo}'
            detalle = salida.motivo_valor_acordado_adicional or equipo
        agregar(
            descripcion,
            ingreso.valor_efectivo_a_cobrar,
            detalle,
            ingreso.codigo_equipo,
        )
    else:
        agregar(
            f'Servicio técnico y reparación - Equipo {ingreso.codigo_equipo}',
            ingreso.valor_acordado or ingreso.valor_efectivo_a_cobrar,
            equipo,
            ingreso.codigo_equipo,
        )
        if salida.tiene_valor_acordado_adicional:
            agregar(
                'Valor adicional acordado',
                salida.valor_acordado_adicional,
                salida.motivo_valor_acordado_adicional,
                'ADIC',
            )

    bodegaje_cobrado = sum(
        (
            abono.bodegaje_monto_aplicado or Decimal('0.00')
            for abono in ingreso.abonos.all()
            if abono.bodegaje_decision == 'si'
        ),
        Decimal('0.00'),
    )
    if bodegaje_cobrado <= 0 and salida.bodegaje_aplicado_al_pago:
        bodegaje_cobrado = salida.bodegaje_monto_congelado or Decimal('0.00')
    agregar('Bodegaje aplicado', bodegaje_cobrado, 'Cargo por días de bodegaje cobrados al cliente.', 'BOD')

    if not items:
        items.append({
            'descripcion': f'Servicio registrado - Equipo {ingreso.codigo_equipo}',
            'detalle': equipo,
            'codigo': ingreso.codigo_equipo,
            'cantidad': 1,
            'precio_unitario': Decimal('0.00'),
            'total': Decimal('0.00'),
        })
    return items


def _usuario_nombre(user):
    if not user or not getattr(user, 'is_authenticated', False):
        return '—'
    return (f'{user.first_name} {user.last_name}'.strip()) or user.username


def _factura_salida_contexto(salida, usuario=None):
    ingreso = salida.ingreso
    cliente = ingreso.cliente
    items = _factura_items_salida(salida)
    pagos_detallados = _pagos_detallados_salida(salida)
    total_facturado = _q_money(sum((item['total'] for item in items), Decimal('0.00')))
    total_pagado = _q_money(sum((pago['monto'] for pago in pagos_detallados), Decimal('0.00')))
    saldo_factura = _q_money(total_facturado - total_pagado)
    registrado_por = salida.registrado_por

    return {
        'salida': salida,
        'ingreso': ingreso,
        'cliente': cliente,
        'numero_factura': _numero_factura_salida(salida),
        'factura_cliente_nombre': salida.factura_nombres or cliente.nombres,
        'factura_cliente_cedula': salida.factura_cedula or cliente.cedula,
        'factura_cliente_correo': salida.factura_correo or cliente.correo,
        'factura_cliente_sector': cliente.sector_display,
        'factura_items': items,
        'pagos_detallados': pagos_detallados,
        'total_facturado': total_facturado,
        'total_pagado': total_pagado,
        'saldo_factura': saldo_factura,
        'saldo_factura_abs': abs(saldo_factura),
        'saldo_factura_negativo': saldo_factura < 0,
        'factura_estado_label': 'Pendiente' if saldo_factura > 0 else 'Pagado',
        'fecha_impresion': timezone.localtime(timezone.now()),
        'usuario_impresion_nombre': _usuario_nombre(usuario),
        'bodega_factura': ingreso.sede_display_corto,
        'descripcion_factura': ' / '.join(item['descripcion'] for item in items),
        'firma_cliente_disponible': bool(ingreso.firma_cliente and ingreso.firma_cliente_imagen),
        'registrado_por_nombre': (
            (f'{registrado_por.first_name} {registrado_por.last_name}'.strip() or registrado_por.username)
            if registrado_por else '—'
        ),
    }


@tecnico_requerido
def salida_factura_imprimir(request, pk):
    salida = _salida_facturada_or_404(pk)
    return render(request, 'facturas/salida_imprimir.html', _factura_salida_contexto(salida, request.user))


def _money_text(valor):
    valor = valor if valor is not None else Decimal('0.00')
    return f'$ {valor:.2f}'


def _detalle_partes_mixtas(partes):
    detalle = []
    for parte in partes or []:
        detalle.append(
            f"Parte {parte['numero']}: {_money_text(parte['monto'])} · {parte['detalle']}"
        )
    return '; '.join(detalle)


def _detalle_pago_simple(obj, metodo, banco_attr='banco', banco_otro_attr='banco_otro',
                         tarjeta_attr='tarjeta_app', comprobante_attr='comprobante_url'):
    detalles = []
    if metodo == 'transferencia':
        banco = getattr(obj, banco_otro_attr, '') if getattr(obj, banco_attr, '') == 'otro' else ''
        if not banco:
            getter = getattr(obj, f'get_{banco_attr}_display', None)
            banco = getter() if getter else getattr(obj, banco_attr, '')
        if banco:
            detalles.append(f'Banco: {banco}')
    elif metodo == 'tarjeta':
        getter = getattr(obj, f'get_{tarjeta_attr}_display', None)
        tarjeta = getter() if getter and getattr(obj, tarjeta_attr, '') else getattr(obj, tarjeta_attr, '')
        if tarjeta:
            detalles.append(f'Tarjeta/App: {tarjeta}')

    comprobante = getattr(obj, comprobante_attr, '')
    if comprobante:
        detalles.append(f'Comprobante: {comprobante}')
    return ' · '.join(detalles)


def _pagos_detallados_ingreso(ingreso):
    """Historial económico del ingreso antes del pago propio de la salida."""
    pagos = []

    if ingreso.diagnostico_inmediato == 'si' and ingreso.valor_diagnostico and ingreso.valor_diagnostico > 0:
        detalle = _detalle_partes_mixtas(ingreso.diagnostico_mixto_partes)
        if not detalle:
            detalle = _detalle_pago_simple(
                ingreso,
                ingreso.diagnostico_metodo,
                banco_attr='diagnostico_banco',
                banco_otro_attr='diagnostico_banco_otro',
                tarjeta_attr='diagnostico_tarjeta_app',
                comprobante_attr='diagnostico_comprobante_url',
            )
        pagos.append({
            'fecha': ingreso.fecha_ingreso,
            'concepto': 'Diagnóstico rápido',
            'monto': ingreso.valor_diagnostico,
            'metodo': ingreso.get_diagnostico_metodo_display(),
            'detalle': detalle or '—',
        })

    if ingreso.abono_anticipo and ingreso.abono_anticipo > 0:
        detalle = _detalle_partes_mixtas(ingreso.anticipo_mixto_partes)
        if not detalle:
            detalle = _detalle_pago_simple(
                ingreso,
                ingreso.anticipo_metodo,
                banco_attr='anticipo_banco',
                banco_otro_attr='anticipo_banco_otro',
                tarjeta_attr='anticipo_tarjeta_app',
                comprobante_attr='anticipo_comprobante_url',
            )
        pagos.append({
            'fecha': ingreso.fecha_ingreso,
            'concepto': 'Anticipo / abono inicial',
            'monto': ingreso.abono_anticipo,
            'metodo': ingreso.get_anticipo_metodo_display(),
            'detalle': detalle or '—',
        })

    for abono in ingreso.abonos.all().order_by('fecha', 'creado'):
        detalle = _detalle_pago_simple(abono, abono.metodo)
        extras = []
        if abono.numero_recibo:
            extras.append(f'Recibo: {abono.numero_recibo}')
        if abono.bodegaje_decision == 'si':
            extras.append(f'Incluye bodegaje: {_money_text(abono.bodegaje_monto_aplicado)}')
        elif abono.bodegaje_decision == 'no':
            extras.append('Bodegaje perdonado')
        if abono.observaciones:
            extras.append(abono.observaciones)
        if extras:
            detalle = ' · '.join(part for part in [detalle, *extras] if part)
        pagos.append({
            'fecha': abono.fecha,
            'concepto': 'Abono registrado',
            'monto': abono.monto,
            'metodo': abono.get_metodo_display(),
            'detalle': detalle or '—',
        })

    return pagos


def _pagos_detallados_salida(salida):
    """Historial económico completo, incluido el pago propio de la salida."""
    ingreso = salida.ingreso
    pagos = _pagos_detallados_ingreso(ingreso)

    if salida.valor_final_cobrado and salida.valor_final_cobrado > 0:
        detalle = _detalle_partes_mixtas(salida.pago_mixto_partes)
        if not detalle:
            detalle = _detalle_pago_simple(
                salida,
                salida.metodo_pago_final,
                banco_attr='banco',
                banco_otro_attr='banco_otro',
                tarjeta_attr='tarjeta_app',
                comprobante_attr='comprobante_url',
            )
        if salida.numero_recibo:
            detalle = ' · '.join(part for part in [detalle, f'Recibo: {salida.numero_recibo}'] if part)
        pagos.append({
            'fecha': salida.fecha_salida,
            'concepto': 'Pago al finalizar',
            'monto': salida.valor_final_cobrado,
            'metodo': salida.get_metodo_pago_final_display(),
            'detalle': detalle or '—',
        })

    return pagos


def _mensaje_estado_salida(salida):
    estado = salida.estado_reparacion
    if salida.cliente_ya_retiro or estado == 'retirado':
        fecha = salida.fecha_retiro_real or salida.fecha_salida
        return f'Su equipo salió de la oficina el {fecha.strftime("%d/%m/%Y")}.'
    if estado == 'revision':
        return 'Su equipo está listo para su retiro en estado de revisión. Debe cancelar el saldo pendiente antes de retirarlo.'
    if estado == 'no_reparable':
        return 'Su equipo está listo para su retiro. No se pudo reparar.'
    if estado == 'cliente_no_acepta':
        return 'Su equipo está listo para su retiro. El cliente no aceptó la reparación.'
    if estado == 'garantia':
        return 'Su equipo ya está listo para su retiro por garantía.'
    if estado == 'garantia_fallos_adicionales':
        return 'Su equipo ya está listo para su retiro por garantía con fallos adicionales pendientes.'
    if estado == 'cortesia':
        return 'Su equipo de cortesía está finalizado y listo para retiro, sin cobro.'
    return 'Su equipo ya está listo para su retiro.'


# ═════════════════════════════════════════════════════════════════
# Versiones PDF descargables (ReportLab)
# ═════════════════════════════════════════════════════════════════

# Color naranja Econotec
ECO_NARANJA = (0xF9 / 255, 0x76 / 255, 0x18 / 255)
ECO_GRIS_BORDE = (0.78, 0.78, 0.78)


def _setup_pdf(buf, title='Documento Econotec'):
    """Crea un canvas A4 y devuelve (canvas, width, height)."""
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4

    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle(title)
    width, height = A4
    return c, width, height


def _draw_header_econotec(c, width, height, doc_title):
    """Dibuja el cabezal con logo, nombre y datos de Econotec."""
    from reportlab.lib.colors import Color, black
    from reportlab.lib.utils import ImageReader
    from django.conf import settings
    import os

    naranja = Color(*ECO_NARANJA)

    # Logo oficial Econotec — cargado desde /static/logo.jpg
    logo_path = os.path.join(settings.BASE_DIR, 'static', 'logo.jpg')
    if not os.path.exists(logo_path):
        logo_path = os.path.join(settings.BASE_DIR, 'static', 'logo.png')

    logo_size = 50
    logo_x = width / 2 - logo_size / 2
    logo_y = height - 75

    if os.path.exists(logo_path):
        try:
            logo = ImageReader(logo_path)
            # Fondo negro circular tras el logo (porque el logo tiene fondo oscuro)
            c.setFillColor(Color(0.1, 0.1, 0.1))
            c.circle(width / 2, logo_y + logo_size / 2, logo_size / 2 + 1, fill=1, stroke=0)
            c.drawImage(logo, logo_x, logo_y, width=logo_size, height=logo_size,
                        mask='auto', preserveAspectRatio=True)
        except Exception:
            # Fallback: círculo con texto
            c.setFillColor(naranja)
            c.circle(width / 2, logo_y + logo_size / 2, 16, fill=1, stroke=0)
            c.setFillColor(Color(1, 1, 1))
            c.setFont('Helvetica-Bold', 18)
            c.drawCentredString(width / 2, logo_y + logo_size / 2 - 6, 'O')
    else:
        # Fallback si no hay logo
        c.setFillColor(naranja)
        c.circle(width / 2, logo_y + logo_size / 2, 16, fill=1, stroke=0)
        c.setFillColor(Color(1, 1, 1))
        c.setFont('Helvetica-Bold', 18)
        c.drawCentredString(width / 2, logo_y + logo_size / 2 - 6, 'O')

    # Título grande del documento
    c.setFillColor(naranja)
    c.setFont('Helvetica-Bold', 22)
    c.drawCentredString(width / 2, height - 95, doc_title)

    # Direcciones (texto pequeño negro)
    c.setFillColor(black)
    c.setFont('Helvetica', 8)
    info_lines = [
        'Guayaquil: Sauces 8 Mz 462 Solar / 6 Piso 2 Oficina 2',
        'Quito: Av. Amazonas y 18 de septiembre / Piso 2 Oficina 102',
        'Celular / WhatsApp: 0963289727 — 0980758747',
        'Web: www.econotec.ec.com   Correo: ventas@econotec.ec.com',
    ]
    y = height - 112
    for line in info_lines:
        c.drawCentredString(width / 2, y, line)
        y -= 11

    return y - 8  # devuelve la y donde empezar el cuerpo


def _draw_label_value(c, x, y, label, value, label_w=140, font_size=9, line_w=300):
    """Dibuja una línea estilo formulario: 'Etiqueta: ___valor___'."""
    from reportlab.lib.colors import Color, black

    naranja = Color(*ECO_NARANJA)
    c.setFillColor(naranja)
    c.setFont('Helvetica-Bold', font_size)
    c.drawString(x, y, label)

    # Línea
    c.setStrokeColor(Color(0.6, 0.6, 0.6))
    c.setLineWidth(0.4)
    c.line(x + label_w, y - 1, x + label_w + line_w, y - 1)

    # Valor
    c.setFillColor(black)
    c.setFont('Helvetica', font_size)
    c.drawString(x + label_w + 4, y + 1, str(value or '—'))


def _signature_image_reader(data_uri):
    if not data_uri or not data_uri.startswith('data:image/png;base64,'):
        return None
    try:
        raw = base64.b64decode(data_uri.split(',', 1)[1], validate=True)
    except (binascii.Error, ValueError, IndexError):
        return None

    from reportlab.lib.utils import ImageReader
    return ImageReader(BytesIO(raw))


def _draw_signature_image(c, data_uri, x, y, w, h):
    imagen = _signature_image_reader(data_uri)
    if not imagen:
        return
    try:
        c.drawImage(imagen, x, y, width=w, height=h, mask='auto', preserveAspectRatio=True, anchor='c')
    except Exception:
        return


def _draw_static_image(c, filename, x, y, w, h):
    from django.conf import settings
    from reportlab.lib.utils import ImageReader
    import os

    image_path = os.path.join(settings.BASE_DIR, 'static', filename)
    if not os.path.exists(image_path):
        return
    try:
        imagen = ImageReader(image_path)
        c.drawImage(imagen, x, y, width=w, height=h, mask='auto')
    except Exception:
        return


def _draw_box_field(c, x, y, w, h, label, value, fill_label_color=None):
    """Dibuja una caja con etiqueta arriba y valor adentro (estilo Equipo N°)."""
    from reportlab.lib.colors import Color, black

    naranja = Color(*ECO_NARANJA)
    if fill_label_color is None:
        fill_label_color = naranja

    # Etiqueta
    c.setFillColor(fill_label_color)
    c.setFont('Helvetica-Bold', 9)
    c.drawString(x, y + h + 3, label)

    # Caja
    c.setStrokeColor(naranja)
    c.setLineWidth(1)
    c.rect(x, y, w, h, stroke=1, fill=0)

    # Valor centrado
    c.setFillColor(black)
    c.setFont('Helvetica-Bold', 14)
    c.drawCentredString(x + w / 2, y + h / 2 - 4, str(value or ''))


def _draw_checkbox_row(c, x, y, items, marcado_key=None):
    """Dibuja una fila de checkboxes tipo: [ ] Impresora  [ ] Laptop ..."""
    from reportlab.lib.colors import Color, black

    naranja = Color(*ECO_NARANJA)
    c.setFont('Helvetica-Bold', 9)
    cur_x = x
    for key, label in items:
        # Caja
        c.setStrokeColor(naranja)
        c.setLineWidth(0.8)
        c.rect(cur_x, y - 2, 12, 12, stroke=1, fill=0)
        if key == marcado_key:
            c.setFillColor(black)
            c.setFont('Helvetica-Bold', 13)
            c.drawString(cur_x + 1.5, y, 'X')
            c.setFont('Helvetica-Bold', 9)
        # Texto
        c.setFillColor(naranja)
        c.drawString(cur_x + 16, y + 1, label)
        cur_x += 70 + len(label) * 1.5  # espaciado dinámico


def _draw_paragraph(c, x, y, label, text, max_w=520, font_size=9, lines=3):
    """Dibuja un párrafo con etiqueta arriba y subrayado por cada línea."""
    from reportlab.lib.colors import Color, black

    naranja = Color(*ECO_NARANJA)
    c.setFillColor(naranja)
    c.setFont('Helvetica-Bold', font_size)
    c.drawString(x, y, label)

    # Texto
    c.setFillColor(black)
    c.setFont('Helvetica', font_size)
    text = (text or '').strip()

    line_h = 14
    cy = y - 15
    # Word-wrap simple
    palabras = text.split()
    line = ''
    cuenta_lineas = 0
    for w in palabras:
        prueba = (line + ' ' + w).strip()
        if c.stringWidth(prueba, 'Helvetica', font_size) > max_w:
            c.drawString(x, cy, line)
            c.setStrokeColor(Color(0.6, 0.6, 0.6))
            c.line(x, cy - 2, x + max_w, cy - 2)
            cy -= line_h
            line = w
            cuenta_lineas += 1
            if cuenta_lineas >= lines:
                break
        else:
            line = prueba
    if line and cuenta_lineas < lines:
        c.drawString(x, cy, line)
        c.setStrokeColor(Color(0.6, 0.6, 0.6))
        c.line(x, cy - 2, x + max_w, cy - 2)
        cy -= line_h
        cuenta_lineas += 1
    # Líneas vacías restantes para "rellenar" el formulario
    while cuenta_lineas < lines:
        c.setStrokeColor(Color(0.6, 0.6, 0.6))
        c.line(x, cy - 2, x + max_w, cy - 2)
        cy -= line_h
        cuenta_lineas += 1

    return cy


PDF_INVENTARIO_CATEGORIAS = {
    'impresora': {
        'nombre': 'Impresora',
        'tipos': {
            'impresora-laser': 'Impresora Laser',
            'impresora-inyeccion': 'Impresora Inyección',
        },
    },
    'computadora': {
        'nombre': 'Computadora',
        'tipos': {
            'pc': 'PC',
            'laptops': 'Laptops',
        },
    },
    'consola': {
        'nombre': 'Consola',
        'tipos': {
            'consola-de-mesa': 'Consola de mesa',
            'portatil': 'Portátil',
        },
    },
    'celular': {'nombre': 'Celular', 'tipos': {'celular': 'Celular'}},
    'tablet': {'nombre': 'Tablet', 'tipos': {'tablet': 'Tablet'}},
    'mando': {'nombre': 'Mando', 'tipos': {'mando': 'Mando'}},
    'otros-equipos-materiales': {
        'nombre': 'Otros equipos/materiales',
        'tipos': {
            'otros-equipos-materiales': 'Otros equipos/materiales',
        },
    },
}


def _texto_slug_legible(valor):
    valor = (valor or '').strip()
    if not valor:
        return ''
    return valor.replace('-', ' ').replace('_', ' ').title()


def _valor_producto_visible(valor):
    valor = str(valor or '').strip()
    if not valor or valor.upper() in {'N/A', 'NA', 'NONE', '—', '-'}:
        return ''
    return valor


def _venta_categoria_nombre(categoria):
    info = PDF_INVENTARIO_CATEGORIAS.get(categoria or '')
    return (info or {}).get('nombre') or _texto_slug_legible(categoria)


def _venta_tipo_nombre(categoria, tipo):
    info = PDF_INVENTARIO_CATEGORIAS.get(categoria or '')
    tipo_nombre = ((info or {}).get('tipos') or {}).get(tipo or '')
    return tipo_nombre or _texto_slug_legible(tipo)


def _venta_productos_pdf_items(ingreso):
    """Detalles de productos para el PDF de venta, sin sede ni stock."""
    relaciones = list(
        ingreso.productos_inventario
        .select_related('inventario_item')
        .all()
    )
    if not relaciones:
        descripcion = (ingreso.problema_reportado or '').strip()
        return [{'titulo': descripcion or 'Producto vendido', 'detalles': []}]

    items = []
    for relacion in relaciones:
        item = relacion.inventario_item
        categoria = _valor_producto_visible(_venta_categoria_nombre(item.categoria))
        tipo = _valor_producto_visible(_venta_tipo_nombre(item.categoria, item.tipo))
        marca = _valor_producto_visible(item.marca)
        modelo = _valor_producto_visible(item.modelo)
        serie = _valor_producto_visible(item.serie)

        detalles = []
        if categoria:
            detalles.append(f'Categoría: {categoria}')
        if tipo and tipo != categoria:
            detalles.append(f'Tipo: {tipo}')
        if marca:
            detalles.append(f'Marca: {marca}')
        if modelo:
            detalles.append(f'Modelo: {modelo}')
        if serie:
            detalles.append(f'Serie: {serie}')
        observacion = (relacion.observacion or '').strip()
        if observacion:
            detalles.append(f'Observación: {observacion}')

        items.append({
            'titulo': f'{relacion.cantidad} x {item.producto}',
            'detalles': detalles,
        })
    return items


def _wrap_pdf_text(c, text, font_name, font_size, max_w, max_lines=None):
    palabras = str(text or '').split()
    if not palabras:
        return []

    lineas = []
    linea = ''
    for palabra in palabras:
        prueba = (linea + ' ' + palabra).strip()
        if linea and c.stringWidth(prueba, font_name, font_size) > max_w:
            lineas.append(linea)
            linea = palabra
            if max_lines and len(lineas) >= max_lines:
                break
        else:
            linea = prueba
    if linea and (not max_lines or len(lineas) < max_lines):
        lineas.append(linea)
    return lineas


def _clip_pdf_text(c, text, font_name, font_size, max_w):
    text = str(text or '—')
    if c.stringWidth(text, font_name, font_size) <= max_w:
        return text
    sufijo = '...'
    while text and c.stringWidth(text + sufijo, font_name, font_size) > max_w:
        text = text[:-1]
    return (text + sufijo) if text else sufijo


def _venta_metodo_pago_pdf(ingreso):
    resumen = (ingreso.resumen_metodos_pago or '').strip()
    if resumen:
        return resumen
    metodo = (ingreso.anticipo_metodo or '').strip()
    if metodo:
        return ingreso.get_anticipo_metodo_display()
    return '—'


def _draw_productos_venta_pdf(c, x, y, ingreso, max_w=510):
    from reportlab.lib.colors import Color, black

    naranja = Color(*ECO_NARANJA)
    borde = Color(0.88, 0.78, 0.72)

    c.setFillColor(naranja)
    c.setFont('Helvetica-Bold', 10)
    c.drawString(x, y, 'PRODUCTOS VENDIDOS')
    y -= 14

    for item in _venta_productos_pdf_items(ingreso):
        titulo_lineas = _wrap_pdf_text(c, item['titulo'], 'Helvetica-Bold', 8.8, max_w - 18, max_lines=1)
        detalle_texto = ' · '.join(item['detalles'])
        detalle_lineas = _wrap_pdf_text(c, detalle_texto, 'Helvetica', 7.6, max_w - 18, max_lines=2)
        if not titulo_lineas:
            titulo_lineas = ['Producto vendido']

        row_h = 16 + (len(titulo_lineas) * 10) + (max(len(detalle_lineas), 1) * 9)
        c.setStrokeColor(borde)
        c.setLineWidth(0.5)
        c.rect(x, y - row_h, max_w, row_h, stroke=1, fill=0)

        cy = y - 12
        c.setFillColor(black)
        c.setFont('Helvetica-Bold', 8.8)
        for linea in titulo_lineas:
            c.drawString(x + 8, cy, linea)
            cy -= 10

        c.setFont('Helvetica', 7.6)
        detalle_lineas = detalle_lineas or ['Detalle registrado en hoja de venta.']
        for linea in detalle_lineas:
            c.drawString(x + 8, cy, linea)
            cy -= 9

        y -= row_h + 6

    return y


def generar_ingreso_pdf_bytes(ingreso):
    """Genera el PDF oficial de la solicitud y devuelve su contenido en bytes."""
    from reportlab.lib.colors import Color, black
    naranja = Color(*ECO_NARANJA)

    cliente = ingreso.cliente
    buf = BytesIO()
    
    es_venta = (ingreso.sede == 'ventas')
    titulo_doc = 'REGISTRO DE VENTA' if es_venta else 'SOLICITUD DE INGRESO'
    c, width, height = _setup_pdf(buf, f'{titulo_doc} {ingreso.codigo_equipo}')

    body_y = _draw_header_econotec(c, width, height, titulo_doc)

    # Cajas Equipo N° y Factura N° (a izquierda y derecha del título)
    lbl_codigo = 'VENTA N°' if es_venta else 'EQUIPO'
    _draw_box_field(c, 40, height - 95, 90, 32, lbl_codigo, ingreso.codigo_equipo)
    _draw_box_field(c, width - 130, height - 95, 90, 32, 'FACTURA N°', ingreso.numero_factura or '')

    # ── Datos generales ─────────────
    y = body_y - 10
    margen = 50
    line_w = 380

    if es_venta:
        _draw_label_value(c, margen, y, 'Asesor Comercial:', ingreso.asesor_comercial, label_w=120, line_w=line_w)
        y -= 22
        _draw_label_value(c, margen, y, 'Técnico vendió:', ingreso.tecnico_encargado_nombre, label_w=120, line_w=line_w)
        y -= 22
        _draw_label_value(c, margen, y, 'Fecha de Venta:', ingreso.fecha_ingreso.strftime('%d/%m/%Y'), label_w=120, line_w=line_w)
        y -= 22
    else:
        _draw_label_value(c, margen, y, 'Asesora Comercial:', ingreso.asesor_comercial, label_w=120, line_w=line_w)
        y -= 22
        _draw_label_value(c, margen, y, 'Técnico Encargado:', ingreso.tecnico_encargado_nombre, label_w=120, line_w=line_w)
        y -= 22
        _draw_label_value(c, margen, y, 'Fecha de Ingreso:', ingreso.fecha_ingreso.strftime('%d/%m/%Y'), label_w=120, line_w=line_w)
        y -= 22

    _draw_label_value(c, margen, y, 'Nombres del Cliente:', cliente.nombres, label_w=120, line_w=line_w)
    y -= 22
    _draw_label_value(c, margen, y, 'Cédula o Ruc / Para la emisión de la factura:', cliente.cedula, label_w=240, line_w=260)
    y -= 22
    _draw_label_value(c, margen, y, 'WhatsApp:', cliente.whatsapp, label_w=80, line_w=420)
    y -= 22

    # Correo + Sector en una línea
    c.setFillColor(naranja)
    c.setFont('Helvetica-Bold', 9)
    c.drawString(margen, y, 'Correo:')
    c.setStrokeColor(Color(0.6, 0.6, 0.6))
    c.line(margen + 50, y - 1, margen + 290, y - 1)
    c.setFillColor(black)
    c.setFont('Helvetica', 9)
    c.drawString(margen + 54, y + 1, cliente.correo or '—')

    c.setFillColor(naranja)
    c.setFont('Helvetica-Bold', 9)
    c.drawString(margen + 320, y, 'Sector:')
    c.line(margen + 360, y - 1, margen + 500, y - 1)
    c.setFillColor(black)
    c.setFont('Helvetica', 9)
    c.drawString(margen + 364, y + 1, cliente.sector_display)
    y -= 30

    if es_venta:
        # ── DETALLES DEL PRODUCTO VENDIDO ─────────
        c.setFillColor(naranja)
        c.setFont('Helvetica-Bold', 11)
        c.drawString(margen, y, 'DETALLES DEL PRODUCTO VENDIDO')
        y -= 18

        # ── Productos vendidos ─────────
        y = _draw_productos_venta_pdf(c, margen, y, ingreso, max_w=510)
        y -= 14

        # ── Valores ──────
        c.setFillColor(naranja)
        c.setFont('Helvetica-Bold', 9)
        c.drawString(margen, y, 'Valor total de la venta:')
        c.setStrokeColor(Color(0.6, 0.6, 0.6))
        c.line(margen + 120, y - 1, margen + 220, y - 1)
        c.setFillColor(black)
        c.setFont('Helvetica', 9)
        val_acord_str = f'$ {ingreso.valor_acordado:.2f}' if ingreso.valor_acordado is not None else '—'
        c.drawString(margen + 124, y + 1, val_acord_str)

        metodo_pago_txt = _venta_metodo_pago_pdf(ingreso)

        c.setFillColor(naranja)
        c.setFont('Helvetica-Bold', 9)
        c.drawString(margen + 250, y, 'Método de pago:')
        c.setStrokeColor(Color(0.6, 0.6, 0.6))
        c.line(margen + 340, y - 1, margen + 480, y - 1)
        c.setFillColor(black)
        c.setFont('Helvetica', 7.8)
        c.drawString(margen + 344, y + 1, _clip_pdf_text(c, metodo_pago_txt, 'Helvetica', 7.8, 165))

        y -= 40

        # ── Nota importante (Ventas) ──
        y -= 6
        c.setStrokeColor(naranja)
        c.setLineWidth(1)
        c.rect(margen, y - 40, 510, 40, stroke=1, fill=0)

        c.setFillColor(naranja)
        c.setFont('Helvetica-Bold', 10)
        c.drawString(margen + 6, y - 12, 'NOTA')

        c.setFillColor(black)
        c.setFont('Helvetica', 7.5)
        nota_lines = [
            'Los productos vendidos cuentan con garantía de fábrica según las políticas de cada marca.',
            'Conserve este documento para cualquier reclamo o devolución.',
        ]
        cy = y - 24
        for line in nota_lines:
            c.drawString(margen + 6, cy, line)
            cy -= 9

        y -= 80

        # ── Firmas ──
        c.setStrokeColor(Color(0.4, 0.4, 0.4))
        if ingreso.firma_cliente and ingreso.firma_cliente_imagen:
            _draw_signature_image(c, ingreso.firma_cliente_imagen, margen + 12, y + 1, 176, 32)
        _draw_static_image(c, 'firma_tecnico_recibe.png', margen + 326, y + 1, 168, 32)
        c.line(margen, y, margen + 200, y)
        c.line(margen + 310, y, margen + 510, y)

        c.setFillColor(naranja)
        c.setFont('Helvetica-Bold', 7.5)
        c.drawString(margen + 50, y - 10, 'FIRMA DEL CLIENTE')
        c.drawString(margen + 365, y - 10, 'FIRMA DEL TÉCNICO')

    else:
        # ── DETALLES DEL EQUIPO (Reparaciones) ─────────
        c.setFillColor(naranja)
        c.setFont('Helvetica-Bold', 11)
        c.drawString(margen, y, 'DETALLES DEL EQUIPO')
        y -= 18

        # Checkboxes
        tipos_fila1 = [
            ('impresora', 'IMPRESORA'), ('laptop', 'LAPTOP'),
            ('pc', 'PC'), ('monitor', 'MONITOR'), ('cpu', 'CPU'),
        ]
        tipos_fila2 = [
            ('celular', 'CELULAR'), ('tablet', 'TABLET'),
            ('consola', 'CONSOLA'), ('mando', 'MANDO'),
            ('maquina_coser', 'MAQUINA DE COSER'),
            ('otro', 'OTROS EQUIPOS'),
        ]
        _draw_checkbox_row(c, margen, y, tipos_fila1, marcado_key=ingreso.tipo_equipo)
        y -= 22
        _draw_checkbox_row(c, margen, y, tipos_fila2, marcado_key=ingreso.tipo_equipo)
        y -= 25

        _draw_label_value(c, margen, y, 'MARCA:', ingreso.marca, label_w=60, line_w=440)
        y -= 22
        _draw_label_value(c, margen, y, 'MODELO:', ingreso.modelo_serie, label_w=70, line_w=430)
        y -= 22
        _draw_label_value(c, margen, y, 'SERIE:', ingreso.serie, label_w=60, line_w=440)
        y -= 22
        _draw_label_value(c, margen, y, 'ACCESORIOS ENTREGADOS:', ingreso.accesorios_entregados[:60] if ingreso.accesorios_entregados else '', label_w=170, line_w=330)
        y -= 30

        # ── PROBLEMA REPORTADO ─────────
        y = _draw_paragraph(c, margen, y, 'PROBLEMA REPORTADO',
                           ingreso.problema_reportado, max_w=500, lines=2)
        y -= 12

        # ── REPORTE DEL TÉCNICO ────────
        y = _draw_paragraph(c, margen, y,
                           'REPORTE DEL TÉCNICO DETALLAR LO QUE SE LE REALIZÓ AL EQUIPO:',
                           ingreso.reporte_tecnico, max_w=500, lines=4)
        y -= 18

        # ── Diagnóstico / Valores ──────
        c.setFillColor(naranja)
        c.setFont('Helvetica-Bold', 9)
        c.drawString(margen, y, 'Diagnóstico Inmediato:')

        # Checkbox SI
        c.setStrokeColor(naranja)
        c.rect(margen + 130, y - 2, 12, 12, stroke=1, fill=0)
        c.drawString(margen + 117, y + 1, 'SI')
        if ingreso.diagnostico_inmediato == 'si':
            c.setFillColor(black)
            c.setFont('Helvetica-Bold', 13)
            c.drawString(margen + 131, y, 'X')
            c.setFillColor(naranja)
            c.setFont('Helvetica-Bold', 9)
        # Checkbox NO
        c.rect(margen + 175, y - 2, 12, 12, stroke=1, fill=0)
        c.drawString(margen + 162, y + 1, 'NO')
        if ingreso.diagnostico_inmediato == 'no':
            c.setFillColor(black)
            c.setFont('Helvetica-Bold', 13)
            c.drawString(margen + 176, y, 'X')
            c.setFillColor(naranja)
            c.setFont('Helvetica-Bold', 9)

        c.drawString(margen + 200, y, 'Valor del Diagnóstico:')
        c.setStrokeColor(Color(0.6, 0.6, 0.6))
        c.line(margen + 320, y - 1, margen + 420, y - 1)
        c.setFillColor(black)
        c.setFont('Helvetica', 9)
        c.drawString(margen + 324, y + 1, f'$ {ingreso.valor_diagnostico:.2f}')

        y -= 22

        # Valor acordado / Abono / Diferencia
        c.setFillColor(naranja)
        c.setFont('Helvetica-Bold', 9)
        c.drawString(margen, y, 'Valor acordado:')
        c.setStrokeColor(Color(0.6, 0.6, 0.6))
        c.line(margen + 95, y - 1, margen + 200, y - 1)
        c.setFillColor(black)
        c.setFont('Helvetica', 9)
        val_acord_str = f'$ {ingreso.valor_acordado:.2f}' if ingreso.valor_acordado is not None else '—'
        c.drawString(margen + 99, y + 1, val_acord_str)

        c.setFillColor(naranja)
        c.setFont('Helvetica-Bold', 9)
        c.drawString(margen + 215, y, 'Total abonado:')
        c.setStrokeColor(Color(0.6, 0.6, 0.6))
        c.line(margen + 310, y - 1, margen + 395, y - 1)
        c.setFillColor(black)
        c.setFont('Helvetica', 9)
        c.drawString(margen + 314, y + 1, f'$ {ingreso.total_abonado:.2f}')

        c.setFillColor(naranja)
        c.setFont('Helvetica-Bold', 9)
        c.drawString(margen + 410, y, 'Diferencia:')
        c.setStrokeColor(Color(0.6, 0.6, 0.6))
        c.line(margen + 478, y - 1, margen + 555, y - 1)
        val_dif_str = f'$ {ingreso.diferencia:.2f}' if ingreso.valor_acordado is not None else '—'
        c.drawString(margen + 482, y + 1, val_dif_str)

        y -= 22

        # ── Nota importante ──
        y -= 6
        c.setStrokeColor(naranja)
        c.setLineWidth(1)
        nota_alto = 96
        c.rect(margen, y - nota_alto, 510, nota_alto, stroke=1, fill=0)

        c.setFillColor(naranja)
        c.setFont('Helvetica-Bold', 10)
        c.drawString(margen + 6, y - 12, 'NOTA IMPORTANTE')

        c.setFillColor(black)
        c.setFont('Helvetica', 7.1)
        nota_lines = [
            'El tiempo de revisión GRATUITA es de 24 a 96 horas, tiempo en el cual el cliente recibirá un mensaje con el',
            'informe técnico y la respectiva cotización. Si el presupuesto es menor a $40,00 se procederá a reparar el equipo.',
            '',
            'Si el técnico encargado le otorga el diagnóstico del equipo y usted decide NO REPARARLO porque el valor de la',
            'reparación no se ajusta a su presupuesto, deberá pagar el valor de $5,00 que es el costo de la revisión profunda',
            'del equipo. Pero si en el diagnóstico gratuito se determina que el equipo NO TIENE SOLUCIÓN, la revisión no',
            'tendrá ningún costo y deberá acercarse a las instalaciones a retirarlo.',
            '',
            'ADICIONAL: pasados 5 DÍAS a partir de que el técnico le indique que puede retirar el equipo, deberá cancelar',
            '$1,00 diario por concepto de bodegaje.',
        ]
        cy = y - 23
        for line in nota_lines:
            c.drawString(margen + 6, cy, line)
            cy -= 8

        y -= 130

        # ── Firmas ──
        c.setStrokeColor(Color(0.4, 0.4, 0.4))
        if ingreso.firma_cliente and ingreso.firma_cliente_imagen:
            _draw_signature_image(c, ingreso.firma_cliente_imagen, margen + 8, y + 1, 124, 28)
        _draw_static_image(c, 'firma_tecnico_recibe.png', margen + 181, y + 1, 138, 26)
        c.line(margen, y, margen + 140, y)
        c.line(margen + 180, y, margen + 320, y)
        c.line(margen + 360, y, margen + 510, y)

        c.setFillColor(naranja)
        c.setFont('Helvetica-Bold', 7.5)
        c.drawString(margen + 30, y - 10, 'FIRMA DEL CLIENTE')
        c.drawString(margen + 190, y - 10, 'FIRMA DEL TÉCNICO QUE RECIBE')
        c.drawString(margen + 370, y - 10, 'FIRMA DEL TÉCNICO QUE REPARA')

    c.showPage()
    c.save()

    pdf = buf.getvalue()
    buf.close()

    return pdf


@tecnico_requerido
def ingreso_pdf(request, pk):
    """Descarga el PDF oficial de la Solicitud de Ingreso."""
    ingreso = get_object_or_404(
        IngresoEquipo.objects.select_related('cliente', 'tecnico_encargado'),
        pk=pk,
    )
    pdf = generar_ingreso_pdf_bytes(ingreso)

    response = HttpResponse(pdf, content_type='application/pdf')
    nombre_descarga = 'registro_venta' if ingreso.sede == 'ventas' else 'ingreso_equipo'
    response['Content-Disposition'] = (
        f'attachment; filename="{nombre_descarga}_{ingreso.codigo_equipo}.pdf"'
    )
    return response


def _draw_anexo_economico_salida(c, width, height, salida, pagos):
    """Dibuja el historial completo y la regla de bodegaje en páginas seguras."""
    from reportlab.lib.colors import Color, black
    from reportlab.lib.utils import simpleSplit

    from .alertas import COSTO_BODEGAJE_DIA, UMBRAL_DIAS_BODEGAJE

    ingreso = salida.ingreso
    naranja = Color(*ECO_NARANJA)
    gris = Color(0.42, 0.45, 0.52)
    borde = Color(0.88, 0.78, 0.72)
    margen = 48
    ancho = width - (margen * 2)

    def encabezado(pagina):
        y_inicio = _draw_header_econotec(
            c,
            width,
            height,
            'ANEXO ECONÓMICO Y BODEGAJE',
        )
        c.setFillColor(gris)
        c.setFont('Helvetica', 7.5)
        c.drawRightString(width - margen, height - 154, f'Equipo {ingreso.codigo_equipo} · Página {pagina}')
        return y_inicio - 8

    def tabla_encabezado(y):
        c.setFillColor(naranja)
        c.setFont('Helvetica-Bold', 7.5)
        columnas = [('FECHA', 0), ('CONCEPTO', 62), ('VALOR', 190), ('MÉTODO', 260), ('DETALLE', 355)]
        for texto, offset in columnas:
            c.drawString(margen + offset, y, texto)
        c.setStrokeColor(borde)
        c.line(margen, y - 5, margen + ancho, y - 5)
        return y - 16

    pagina = 1
    y = encabezado(pagina)

    c.setFillColor(naranja)
    c.setFont('Helvetica-Bold', 11)
    c.drawString(margen, y, 'RESUMEN ACTUALIZADO')
    y -= 18

    saldo = max(ingreso.diferencia, Decimal('0.00'))
    resumen = [
        ('Valor total del servicio', ingreso.valor_efectivo_a_cobrar),
        ('Total de pagos registrados', ingreso.total_abonado),
        ('Saldo pendiente', saldo),
    ]
    caja_w = ancho / 3
    for indice, (etiqueta, monto) in enumerate(resumen):
        x = margen + (indice * caja_w)
        c.setStrokeColor(borde)
        c.setFillColorRGB(1, 0.97, 0.94)
        c.rect(x, y - 42, caja_w, 42, stroke=1, fill=1)
        c.setFillColor(gris)
        c.setFont('Helvetica-Bold', 7)
        c.drawString(x + 8, y - 13, etiqueta.upper())
        c.setFillColor(black)
        c.setFont('Helvetica-Bold', 12)
        c.drawString(x + 8, y - 31, _money_text(monto))
    y -= 58

    calculo = salida.calcular_bodegaje()
    if salida.bodegaje_dias_congelado is not None:
        if salida.bodegaje_aplicado_al_pago:
            estado_bodegaje = 'Cobrado y cerrado'
        elif (salida.bodegaje_monto_congelado or Decimal('0.00')) > Decimal('0.00'):
            estado_bodegaje = 'Perdonado y cerrado'
        else:
            estado_bodegaje = 'Cerrado sin cargos'
    elif ingreso.bodegaje_pendiente > Decimal('0.00'):
        estado_bodegaje = 'Pendiente de decisión'
    else:
        estado_bodegaje = 'Dentro del período de gracia'

    regla = (
        f'Regla: {UMBRAL_DIAS_BODEGAJE} días de gracia desde la fecha de finalización. '
        f'Al cumplirse el plazo se cobra {_money_text(COSTO_BODEGAJE_DIA)} por cada día '
        'de bodegaje hasta el retiro del equipo.'
    )
    situacion = f'Situación actual: {estado_bodegaje}.'
    if calculo['aplica'] and calculo['monto'] > 0:
        if salida.bodegaje_dias_congelado is not None:
            concepto_bodegaje = (
                'Monto cobrado'
                if salida.bodegaje_aplicado_al_pago
                else 'Monto perdonado'
            )
        else:
            concepto_bodegaje = 'Acumulado actual'
        situacion += (
            f" {calculo['dias']} día(s). {concepto_bodegaje}: "
            f"{_money_text(calculo['monto'])}."
        )

    regla_lineas = simpleSplit(regla, 'Helvetica', 8, ancho - 20)
    situacion_lineas = simpleSplit(situacion, 'Helvetica-Bold', 8, ancho - 20)
    caja_h = 24 + ((len(regla_lineas) + len(situacion_lineas)) * 10)
    c.setStrokeColor(Color(0.88, 0.68, 0.2))
    c.setFillColorRGB(1, 0.98, 0.88)
    c.roundRect(margen, y - caja_h, ancho, caja_h, 5, stroke=1, fill=1)
    c.setFillColor(Color(0.43, 0.30, 0.0))
    c.setFont('Helvetica-Bold', 9)
    c.drawString(margen + 10, y - 14, 'REGLA DE BODEGAJE')
    cy = y - 27
    c.setFont('Helvetica', 8)
    for linea in regla_lineas:
        c.drawString(margen + 10, cy, linea)
        cy -= 10
    c.setFont('Helvetica-Bold', 8)
    for linea in situacion_lineas:
        c.drawString(margen + 10, cy, linea)
        cy -= 10
    y -= caja_h + 22

    c.setFillColor(naranja)
    c.setFont('Helvetica-Bold', 11)
    c.drawString(margen, y, 'HISTORIAL COMPLETO DE PAGOS')
    y -= 16
    y = tabla_encabezado(y)

    if not pagos:
        c.setFillColor(black)
        c.setFont('Helvetica', 8.5)
        c.drawString(margen, y, 'No existen pagos ni abonos registrados.')
        return

    font = 'Helvetica'
    tamano = 6.8
    leading = 8
    anchos = [55, 118, 62, 85, 143]
    for pago in pagos:
        c.setFont(font, tamano)
        celdas = [
            [pago['fecha'].strftime('%d/%m/%Y')],
            simpleSplit(str(pago['concepto']), font, tamano, anchos[1]) or ['—'],
            [_money_text(pago['monto'])],
            simpleSplit(str(pago['metodo']), font, tamano, anchos[3]) or ['—'],
            simpleSplit(str(pago['detalle'] or '—'), font, tamano, anchos[4]) or ['—'],
        ]
        celdas = [lineas[:4] for lineas in celdas]
        alto = (max(len(lineas) for lineas in celdas) * leading) + 8
        if y - alto < 52:
            c.showPage()
            pagina += 1
            y = encabezado(pagina)
            c.setFillColor(naranja)
            c.setFont('Helvetica-Bold', 11)
            c.drawString(margen, y, 'CONTINUACIÓN DEL HISTORIAL DE PAGOS')
            y -= 16
            y = tabla_encabezado(y)

        offsets = [0, 62, 190, 260, 355]
        c.setFillColor(black)
        c.setFont(font, tamano)
        for columna, lineas in enumerate(celdas):
            for indice, linea in enumerate(lineas):
                c.drawString(margen + offsets[columna], y - (indice * leading), linea)
        y -= alto
        c.setStrokeColor(Color(0.9, 0.9, 0.9))
        c.line(margen, y + 3, margen + ancho, y + 3)


def generar_salida_pdf_bytes(salida):
    """Genera el acta oficial de equipo finalizado y devuelve sus bytes."""
    ingreso = salida.ingreso
    cliente = ingreso.cliente
    # La responsabilidad de la salida nunca se hereda del técnico asignado
    # al ingreso. Los registros históricos incompletos se muestran sin técnico.
    tecnico_nombre = salida.tecnico_reparo_nombre or '— Sin técnico registrado —'
    pagos_detallados = _pagos_detallados_salida(salida)
    mensaje_estado = _mensaje_estado_salida(salida)
    buf = BytesIO()
    c, width, height = _setup_pdf(buf, f'Equipo Finalizado {ingreso.codigo_equipo}')

    body_y = _draw_header_econotec(c, width, height, 'ACTA DE EQUIPO FINALIZADO')

    # Cajas equipo y fecha
    _draw_box_field(c, 40, height - 95, 90, 32, 'EQUIPO', ingreso.codigo_equipo)
    _draw_box_field(c, width - 130, height - 95, 90, 32, 'FECHA FINAL',
                   salida.fecha_salida.strftime('%d/%m/%Y'))

    margen = 50
    y = body_y - 10
    line_w = 380

    _draw_label_value(c, margen, y, 'Cliente:', cliente.nombres, label_w=70, line_w=line_w + 50)
    y -= 22
    _draw_label_value(c, margen, y, 'Cédula / RUC:', cliente.cedula, label_w=90, line_w=line_w + 30)
    y -= 22
    _draw_label_value(c, margen, y, 'WhatsApp:', cliente.whatsapp, label_w=80, line_w=line_w + 40)
    y -= 22
    _draw_label_value(c, margen, y, 'Equipo:',
                     f'{ingreso.tipo_equipo_display} — {ingreso.marca} {ingreso.modelo_serie_detalle}',
                     label_w=60, line_w=line_w + 60)
    y -= 22
    _draw_label_value(c, margen, y, 'Técnico que reparó:', tecnico_nombre,
                     label_w=130, line_w=line_w - 10)
    y -= 30

    from reportlab.lib.colors import Color, black
    from reportlab.lib.utils import simpleSplit
    naranja = Color(*ECO_NARANJA)

    # ── Estado de la reparación (destacado) ──
    c.setFillColor(naranja)
    c.setFont('Helvetica-Bold', 11)
    c.drawString(margen, y, 'RESULTADO FINAL DEL EQUIPO')
    y -= 18

    # Mostrar las 5 opciones con marcado
    estados = (
        [('cortesia', 'EQUIPO DE CORTESÍA FINALIZADO')]
        if salida.estado_reparacion == 'cortesia'
        else [
            ('pendiente_retiro', 'Reparado — pendiente de retiro'),
            ('retirado', 'Salió de la oficina'),
            ('revision', 'Revisión'),
            ('reparado_parcial', 'Reparado parcialmente'),
            ('no_reparable', 'No se pudo reparar'),
            ('cliente_no_acepta', 'Cliente no quiso reparar'),
            ('garantia', 'Garantía finalizada'),
            ('garantia_fallos_adicionales', 'Garantía finalizada + fallos adicionales'),
        ]
    )
    for key, label in estados:
        c.setStrokeColor(naranja)
        c.setLineWidth(0.8)
        c.rect(margen, y - 2, 12, 12, stroke=1, fill=0)
        if key == salida.estado_reparacion:
            c.setFillColor(black)
            c.setFont('Helvetica-Bold', 13)
            c.drawString(margen + 1.5, y, 'X')
        c.setFillColor(naranja if key != salida.estado_reparacion else black)
        c.setFont('Helvetica-Bold' if key == salida.estado_reparacion else 'Helvetica', 9)
        c.drawString(margen + 18, y + 1, label)
        y -= 16

    y -= 10

    # ── Problema reportado (del ingreso) ──
    y = _draw_paragraph(c, margen, y, 'PROBLEMA REPORTADO ORIGINALMENTE',
                       ingreso.problema_reportado, max_w=500, lines=2)
    y -= 4

    c.setStrokeColor(naranja)
    c.setFillColorRGB(1, 0.97, 0.94)
    c.roundRect(margen, y - 24, 500, 24, 4, stroke=1, fill=1)
    c.setFillColor(black)
    c.setFont('Helvetica-Bold', 8.5)
    c.drawCentredString(margen + 250, y - 15, mensaje_estado[:128])
    y -= 36

    # ── Reporte del técnico (del ingreso) ──
    if ingreso.reporte_tecnico:
        y = _draw_paragraph(c, margen, y, 'REPORTE DEL TÉCNICO (DEL INGRESO)',
                           ingreso.reporte_tecnico, max_w=500, lines=3)
        y -= 8

    # ── Observaciones del cierre ──
    if salida.observaciones:
        y = _draw_paragraph(c, margen, y, 'OBSERVACIONES DEL CIERRE',
                           salida.observaciones, max_w=500, lines=2)
        y -= 8

    if salida.estado_reparacion == 'cortesia':
        y -= 48
        c.setStrokeColor(Color(0.4, 0.4, 0.4))
        firma_x = margen + 145
        _draw_static_image(c, 'firma_tecnico_recibe.png', firma_x + 52, y + 4, 112, 28)
        c.line(firma_x, y, firma_x + 220, y)
        c.setFillColor(naranja)
        c.setFont('Helvetica-Bold', 8)
        c.drawCentredString(firma_x + 110, y - 10, 'FIRMA DEL TÉCNICO')

        c.showPage()
        c.save()
        pdf = buf.getvalue()
        buf.close()
        return pdf

    # ── Factura ──
    def _clip_factura(valor, max_len=42):
        texto = str(valor or '—')
        return texto if len(texto) <= max_len else f'{texto[:max_len - 1]}…'

    if salida.factura_realizada == 'si':
        c.setStrokeColor(naranja)
        c.setLineWidth(0.8)
        c.rect(margen, y - 62, 500, 62, stroke=1, fill=0)
        c.setFillColor(naranja)
        c.setFont('Helvetica-Bold', 10)
        c.drawString(margen + 8, y - 14, 'FACTURA REALIZADA')
        c.setFillColor(black)
        c.setFont('Helvetica-Bold', 9)
        c.drawRightString(margen + 490, y - 14, 'SI')
        c.setFillColor(naranja)
        c.setFont('Helvetica-Bold', 7.5)
        c.drawString(margen + 8, y - 32, 'NOMBRES / RAZÓN SOCIAL')
        c.drawString(margen + 235, y - 32, 'CÉDULA / RUC')
        c.drawString(margen + 350, y - 32, 'CORREO')
        c.setFillColor(black)
        c.setFont('Helvetica', 8)
        c.drawString(margen + 8, y - 47, _clip_factura(salida.factura_nombres, 38))
        c.drawString(margen + 235, y - 47, _clip_factura(salida.factura_cedula, 18))
        c.drawString(margen + 350, y - 47, _clip_factura(salida.factura_correo, 30))
        y -= 78

    # ── Cierre económico ──
    c.setFillColor(naranja)
    c.setFont('Helvetica-Bold', 11)
    c.drawString(margen, y, 'CIERRE ECONÓMICO')
    y -= 18

    if salida.tiene_valor_acordado_adicional:
        es_cierre_sin_reparacion = salida.estado_reparacion in (
            'cliente_no_acepta',
            'no_reparable',
        )
        box_h = 62
        c.setStrokeColor(naranja)
        c.setFillColorRGB(1, 0.97, 0.94)
        c.roundRect(margen, y - box_h, 500, box_h, 4, stroke=1, fill=1)
        c.setFillColor(naranja)
        c.setFont('Helvetica-Bold', 8.5)
        titulo_adicional = (
            'DETALLE DEL COBRO ADICIONAL'
            if es_cierre_sin_reparacion
            else 'DETALLE DEL VALOR ACORDADO ADICIONAL'
        )
        c.drawString(margen + 10, y - 13, titulo_adicional)

        if es_cierre_sin_reparacion:
            columnas = [
                ('RESULTADO BASE', 'SIN COBRO', margen + 10),
                ('COBRO ADICIONAL', salida.valor_acordado_adicional, margen + 175),
                ('TOTAL A COBRAR', ingreso.valor_efectivo_a_cobrar, margen + 340),
            ]
        else:
            columnas = [
                ('VALOR ORIGINAL', ingreso.valor_acordado or Decimal('0.00'), margen + 10),
                ('VALOR ADICIONAL', salida.valor_acordado_adicional, margen + 175),
                ('TOTAL ACTUALIZADO', ingreso.valor_efectivo_a_cobrar, margen + 340),
            ]
        for etiqueta, monto, x in columnas:
            c.setFillColor(Color(0.38, 0.38, 0.38))
            c.setFont('Helvetica-Bold', 6.8)
            c.drawString(x, y - 27, etiqueta)
            c.setFillColor(black)
            c.setFont('Helvetica-Bold', 9.2)
            valor_mostrado = monto if isinstance(monto, str) else _money_text(monto)
            c.drawString(x, y - 39, valor_mostrado)

        motivo = f'Motivo acordado: {salida.motivo_valor_acordado_adicional}'
        motivo_lineas = simpleSplit(motivo, 'Helvetica', 7.2, 475)[:2] or ['—']
        c.setFillColor(black)
        c.setFont('Helvetica', 7.2)
        for idx, linea in enumerate(motivo_lineas):
            c.drawString(margen + 10, y - 51 - (idx * 8), linea)
        y -= box_h + 8

    c.setStrokeColor(naranja)
    c.setLineWidth(0.8)
    c.roundRect(margen, y - 34, 500, 34, 4, stroke=1, fill=0)
    c.setFillColor(naranja)
    c.setFont('Helvetica-Bold', 11)
    c.drawString(margen + 10, y - 21, 'Su valor pendiente es:')
    c.setFillColor(black)
    c.setFont('Helvetica-Bold', 13)
    c.drawRightString(
        margen + 490,
        y - 21,
        _money_text(max(ingreso.diferencia, Decimal('0.00'))),
    )
    y -= 48

    if pagos_detallados:
        c.setFillColor(black)
        c.setFont('Helvetica-Bold', 8.5)
        c.drawString(margen, y, 'Pagos / abonos registrados')
        y -= 12
        headers = [('Fecha', 0), ('Concepto', 58), ('Valor', 178), ('Método', 248), ('Detalle', 350)]
        c.setFillColor(naranja)
        c.setFont('Helvetica-Bold', 7.5)
        for label, offset in headers:
            c.drawString(margen + offset, y, label)
        y -= 6
        c.setStrokeColor(Color(0.88, 0.72, 0.6))
        c.line(margen, y, margen + 500, y)
        y -= 8
        c.setFillColor(black)
        font_name = 'Helvetica'
        font_size = 6.8
        leading = 8
        c.setFont(font_name, font_size)

        def _cell_lines(texto, ancho, max_lines=3):
            lineas = simpleSplit(str(texto or '—'), font_name, font_size, ancho)
            if not lineas:
                return ['—']
            if len(lineas) > max_lines:
                lineas = lineas[:max_lines]
                lineas[-1] = f'{lineas[-1].rstrip()[:-1]}…' if len(lineas[-1].rstrip()) > 1 else '…'
            return lineas

        max_pagos_pdf = 4 if salida.tiene_valor_acordado_adicional else 6
        for pago in pagos_detallados[:max_pagos_pdf]:
            fecha_lineas = [pago['fecha'].strftime('%d/%m/%Y')]
            concepto_lineas = _cell_lines(pago['concepto'], 110, max_lines=2)
            monto_lineas = [_money_text(pago['monto'])]
            metodo_lineas = _cell_lines(pago['metodo'], 92, max_lines=2)
            detalle_lineas = _cell_lines(pago['detalle'], 145, max_lines=3)
            filas = max(
                len(fecha_lineas),
                len(concepto_lineas),
                len(monto_lineas),
                len(metodo_lineas),
                len(detalle_lineas),
            )

            for idx, texto in enumerate(fecha_lineas):
                c.drawString(margen, y - (idx * leading), texto)
            for idx, texto in enumerate(concepto_lineas):
                c.drawString(margen + 58, y - (idx * leading), texto)
            for idx, texto in enumerate(monto_lineas):
                c.drawString(margen + 178, y - (idx * leading), texto)
            for idx, texto in enumerate(metodo_lineas):
                c.drawString(margen + 248, y - (idx * leading), texto)
            for idx, texto in enumerate(detalle_lineas):
                c.drawString(margen + 350, y - (idx * leading), texto)

            y -= (filas * leading) + 5
        if len(pagos_detallados) > max_pagos_pdf:
            c.setFont('Helvetica-Oblique', 6.8)
            c.drawString(
                margen,
                y,
                'Consulta el historial completo de pagos en el anexo económico de este documento.',
            )
            y -= 10
    else:
        c.setFillColor(black)
        c.setFont('Helvetica', 8)
        c.drawString(margen, y, 'Este equipo no registra pagos ni abonos previos.')
        y -= 12

    y -= 48
    # ── Firmas ──
    c.setStrokeColor(Color(0.4, 0.4, 0.4))
    firma_x = margen + 145
    _draw_static_image(c, 'firma_tecnico_recibe.png', firma_x + 52, y + 4, 112, 28)
    c.line(firma_x, y, firma_x + 220, y)
    c.setFillColor(naranja)
    c.setFont('Helvetica-Bold', 8)
    c.drawCentredString(firma_x + 110, y - 10, 'FIRMA DEL TÉCNICO')

    c.showPage()
    _draw_anexo_economico_salida(c, width, height, salida, pagos_detallados)
    c.showPage()
    c.save()

    pdf = buf.getvalue()
    buf.close()

    return pdf


@tecnico_requerido
def salida_pdf(request, pk):
    """Descarga el PDF oficial del acta de equipo finalizado."""
    salida = get_object_or_404(
        SalidaEquipo.objects.select_related(
            'ingreso',
            'ingreso__cliente',
            'tecnico_reparo',
        ).prefetch_related('ingreso__abonos'),
        pk=pk,
    )
    pdf = generar_salida_pdf_bytes(salida)
    response = HttpResponse(pdf, content_type='application/pdf')
    nombre = (
        f'equipo_finalizado_cortesia_{salida.ingreso.codigo_equipo}.pdf'
        if salida.estado_reparacion == 'cortesia'
        else f'equipo_finalizado_{salida.ingreso.codigo_equipo}.pdf'
    )
    response['Content-Disposition'] = f'attachment; filename="{nombre}"'
    return response


@tecnico_requerido
def salida_factura_pdf(request, pk):
    """Genera el PDF comercial de factura, separado del Acta de Salida."""
    from reportlab.lib.colors import Color
    from reportlab.lib.utils import simpleSplit

    salida = _salida_facturada_or_404(pk)
    ctx = _factura_salida_contexto(salida, request.user)
    ingreso = ctx['ingreso']
    cliente = ctx['cliente']
    buf = BytesIO()
    c, width, height = _setup_pdf(buf, f'Factura {ctx["numero_factura"]} {ingreso.codigo_equipo}')

    brand = Color(*ECO_NARANJA)
    tinta = Color(0.14, 0.10, 0.10)
    muted = Color(0.42, 0.45, 0.52)
    rojo_logo = Color(0.76, 0.22, 0.07)
    line_color = Color(0.20, 0.20, 0.20)

    margin_x = 42
    right_x = width - margin_x

    def draw_text(x, y, text, font='Helvetica', size=9, color=tinta):
        c.setFillColor(color)
        c.setFont(font, size)
        c.drawString(x, y, str(text or ''))

    def draw_right(x, y, text, font='Helvetica', size=9, color=tinta):
        c.setFillColor(color)
        c.setFont(font, size)
        c.drawRightString(x, y, str(text or ''))

    def draw_wrapped(x, y, text, max_w, font='Helvetica', size=8.5, leading=10, max_lines=3):
        lines = simpleSplit(str(text or '-'), font, size, max_w)[:max_lines] or ['-']
        c.setFillColor(tinta)
        c.setFont(font, size)
        for idx, line in enumerate(lines):
            c.drawString(x, y - (idx * leading), line)
        return len(lines)

    def draw_info_row(x, y, label, value, label_w=125, value_w=250):
        draw_text(x, y, label, 'Helvetica-Bold', 9)
        lines = simpleSplit(str(value or 'N/A'), 'Helvetica', 9, value_w)[:2] or ['N/A']
        c.setFont('Helvetica', 9)
        c.setFillColor(tinta)
        for idx, line in enumerate(lines):
            c.drawString(x + label_w, y - (idx * 11), line)
        return y - max(17, len(lines) * 11)

    # Encabezado
    _draw_static_image(c, 'logo.jpg', margin_x + 28, height - 86, 54, 54)
    draw_right(right_x, height - 48, 'ECONOTEC - REPARACIÓN DE TECNOLOGÍA', 'Helvetica-Bold', 10.5, rojo_logo)
    draw_right(right_x, height - 66, f'Usuario: {ctx["usuario_impresion_nombre"]}', 'Helvetica', 9)
    draw_right(right_x, height - 82, f'Fecha de impresión: {ctx["fecha_impresion"].strftime("%d/%m/%Y %H:%M")}', 'Helvetica', 9)
    c.setStrokeColor(line_color)
    c.setLineWidth(0.8)
    c.line(margin_x, height - 101, right_x, height - 101)

    draw_right(
        (width / 2) + 145,
        height - 154,
        f'Comprobante de Compra/Venta: {ctx["numero_factura"]}',
        'Helvetica-Bold',
        15,
    )

    # Datos del comprobante
    y = height - 218
    y_left = y
    y_left = draw_info_row(margin_x + 4, y_left, 'Fecha de emisión:', salida.fecha_salida.strftime('%d/%m/%Y'))
    y_left = draw_info_row(margin_x + 4, y_left, 'Documento:', ctx['numero_factura'])
    y_left = draw_info_row(
        margin_x + 4,
        y_left,
        'Cliente:',
        f'{ctx["factura_cliente_nombre"]} - RUC/C.I.: {ctx["factura_cliente_cedula"]}',
    )
    y_left = draw_info_row(margin_x + 4, y_left, 'Teléfonos:', cliente.whatsapp or 'N/A')
    y_left = draw_info_row(margin_x + 4, y_left, 'Estado:', ctx['factura_estado_label'])
    y_left = draw_info_row(margin_x + 4, y_left, 'Bodega:', ctx['bodega_factura'])
    y_left = draw_info_row(margin_x + 4, y_left, 'Dirección:', ctx['factura_cliente_sector'] or 'N/A')

    y_right = y
    y_right = draw_info_row(margin_x + 330, y_right, 'Vencimiento:', '0 días', label_w=120, value_w=120)
    y_right = draw_info_row(margin_x + 330, y_right, 'Equipo:', ingreso.codigo_equipo, label_w=120, value_w=120)
    y_right = draw_info_row(margin_x + 330, y_right, 'Registró salida:', ctx['registrado_por_nombre'], label_w=120, value_w=120)
    y_right = draw_info_row(margin_x + 330, y_right, 'Correo:', ctx['factura_cliente_correo'] or 'N/A', label_w=120, value_w=120)

    y = min(y_left, y_right) - 26

    # Tabla de bienes/servicios
    draw_text(margin_x + 4, y, 'Bienes/Servicios', 'Helvetica-BoldOblique', 11)
    c.setLineWidth(1)
    c.line(margin_x + 4, y - 3, margin_x + 105, y - 3)
    y -= 22

    table_x = margin_x + 4
    widths = [58, 54, 132, 112, 64, 72]
    headers = ['Cantidad', 'Código', 'Bien/Servicio', 'Detalle', 'Precio', 'Subtotal']
    row_h = 20
    c.setStrokeColor(line_color)
    c.setLineWidth(0.6)
    c.rect(table_x, y - row_h, sum(widths), row_h, stroke=1, fill=0)
    cur_x = table_x
    for idx, header in enumerate(headers):
        if idx:
            c.line(cur_x, y, cur_x, y - row_h)
        draw_text(cur_x + 6, y - 14, header, 'Helvetica-Bold', 8.2)
        cur_x += widths[idx]
    y -= row_h

    for item in ctx['factura_items']:
        servicio_lines = simpleSplit(str(item['descripcion']), 'Helvetica', 8.4, widths[2] - 12)[:3] or ['-']
        detalle_lines = simpleSplit(str(item.get('detalle') or '-'), 'Helvetica', 8.4, widths[3] - 12)[:3] or ['-']
        item_row_h = max(38, (max(len(servicio_lines), len(detalle_lines)) * 10) + 14)
        if y - item_row_h < 190:
            c.showPage()
            y = height - 70
        c.rect(table_x, y - item_row_h, sum(widths), item_row_h, stroke=1, fill=0)
        cur_x = table_x
        for w in widths[:-1]:
            cur_x += w
            c.line(cur_x, y, cur_x, y - item_row_h)
        draw_text(table_x + 6, y - 16, f'{item["cantidad"]}.00 Unid.', 'Helvetica', 8.4)
        draw_text(table_x + widths[0] + 6, y - 16, item.get('codigo') or '-', 'Helvetica', 8.4)
        draw_wrapped(table_x + widths[0] + widths[1] + 6, y - 16, item['descripcion'], widths[2] - 12, size=8.4)
        draw_wrapped(table_x + widths[0] + widths[1] + widths[2] + 6, y - 16, item.get('detalle') or '-', widths[3] - 12, size=8.4)
        draw_right(table_x + sum(widths[:-1]) - 8, y - 16, _money_text_es(item['precio_unitario']), 'Helvetica', 8.4)
        draw_right(table_x + sum(widths) - 8, y - 16, _money_text_es(item['total']), 'Helvetica', 8.4)
        y -= item_row_h

    y -= 32
    draw_text(margin_x + 4, y, 'Descripción:', 'Helvetica-Bold', 9.2)
    draw_wrapped(margin_x + 88, y, ctx['descripcion_factura'], 255, size=9, max_lines=3)

    totals_x = right_x - 150
    totals_y = y + 2
    total_rows = [
        ('Subtotal 15%:', '$0,00'),
        ('Subtotal 5%:', '$0,00'),
        ('Subtotal 0%:', _money_text_es(ctx['total_facturado'])),
        ('IVA 15%:', '$0,00'),
        ('IVA 5%:', '$0,00'),
        ('Total:', _money_text_es(ctx['total_facturado'])),
        ('Pagado:', _money_text_es(ctx['total_pagado'])),
        ('Saldo a favor:' if ctx['saldo_factura_negativo'] else 'Saldo:', _money_text_es(ctx['saldo_factura_abs'])),
    ]
    for label, value in total_rows:
        draw_right(totals_x + 92, totals_y, label, 'Helvetica-Bold', 9)
        draw_right(totals_x + 150, totals_y, value, 'Helvetica', 9)
        totals_y -= 15

    # Firmas del comprobante: técnico con imagen fija, cliente solo con línea.
    sig_y = 95
    sig_w = 190
    tech_x = margin_x + 4
    client_x = right_x - sig_w

    _draw_static_image(c, 'firma_tecnico_recibe.png', tech_x + 48, sig_y + 9, 96, 28)
    c.setStrokeColor(line_color)
    c.setLineWidth(0.8)
    c.line(tech_x, sig_y, tech_x + sig_w, sig_y)
    draw_text(tech_x, sig_y - 18, 'Firma del técnico', 'Helvetica-Bold', 9.2)

    c.line(client_x, sig_y, client_x + sig_w, sig_y)
    draw_text(client_x, sig_y - 18, 'Firma del cliente', 'Helvetica-Bold', 9.2)

    draw_right(width / 2 + 125, 38, 'Documento comercial generado desde el sistema Econotec.', 'Helvetica', 7.5, muted)

    c.showPage()
    c.save()

    pdf = buf.getvalue()
    buf.close()

    response = HttpResponse(pdf, content_type='application/pdf')
    response['Content-Disposition'] = (
        f'attachment; filename="factura_{ingreso.codigo_equipo}.pdf"'
    )
    return response
