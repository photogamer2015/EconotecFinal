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


def _pagos_detallados_salida(salida):
    ingreso = salida.ingreso
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
            'concepto': 'Pago en salida',
            'monto': salida.valor_final_cobrado,
            'metodo': salida.get_metodo_pago_final_display(),
            'detalle': detalle or '—',
        })

    return pagos


def _mensaje_estado_salida(salida):
    estado = salida.estado_reparacion
    if salida.cliente_ya_retiro or estado == 'retirado':
        fecha = salida.fecha_retiro_real or salida.fecha_salida
        return f'Su equipo fue retirado por el cliente el {fecha.strftime("%d/%m/%Y")}.'
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


@tecnico_requerido
def ingreso_pdf(request, pk):
    """Genera el PDF de la Solicitud de Ingreso, replicando el formato del papel."""
    from reportlab.lib.colors import Color, black
    naranja = Color(*ECO_NARANJA)

    ingreso = get_object_or_404(
        IngresoEquipo.objects.select_related('cliente', 'tecnico_encargado'),
        pk=pk,
    )
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
        c.drawString(margen + 215, y, 'Abono/Anticipo:')
        c.setStrokeColor(Color(0.6, 0.6, 0.6))
        c.line(margen + 310, y - 1, margen + 395, y - 1)
        c.setFillColor(black)
        c.setFont('Helvetica', 9)
        c.drawString(margen + 314, y + 1, f'$ {ingreso.abono_anticipo:.2f}')

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

    response = HttpResponse(pdf, content_type='application/pdf')
    nombre_descarga = 'registro_venta' if es_venta else 'ingreso_equipo'
    response['Content-Disposition'] = (
        f'attachment; filename="{nombre_descarga}_{ingreso.codigo_equipo}.pdf"'
    )
    return response


@tecnico_requerido
def salida_pdf(request, pk):
    """Genera el PDF del Acta de Salida del equipo."""
    salida = get_object_or_404(
        SalidaEquipo.objects.select_related('ingreso', 'ingreso__cliente', 'tecnico_reparo')
        .prefetch_related('ingreso__abonos'),
        pk=pk,
    )
    ingreso = salida.ingreso
    cliente = ingreso.cliente
    tecnico_nombre = salida.tecnico_reparo_nombre or ingreso.tecnico_encargado_nombre
    pagos_detallados = _pagos_detallados_salida(salida)
    mensaje_estado = _mensaje_estado_salida(salida)
    buf = BytesIO()
    c, width, height = _setup_pdf(buf, f'Acta de Salida {ingreso.codigo_equipo}')

    body_y = _draw_header_econotec(c, width, height, 'ACTA DE SALIDA DE EQUIPO')

    # Cajas equipo y fecha
    _draw_box_field(c, 40, height - 95, 90, 32, 'EQUIPO', ingreso.codigo_equipo)
    _draw_box_field(c, width - 130, height - 95, 90, 32, 'FECHA',
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
    c.drawString(margen, y, 'ESTADO DE LA SALIDA')
    y -= 18

    # Mostrar las 5 opciones con marcado
    estados = [
        ('pendiente_retiro', 'Reparado — pendiente de retiro'),
        ('retirado', 'Retirado por el cliente'),
        ('revision', 'Revisión'),
        ('reparado_parcial', 'Reparado parcialmente'),
        ('no_reparable', 'No se pudo reparar'),
        ('cliente_no_acepta', 'Cliente no quiso reparar'),
        ('garantia', 'Salida por garantía'),
        ('garantia_fallos_adicionales', 'Garantía + fallos adicionales'),
    ]
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

    c.setStrokeColor(naranja)
    c.setLineWidth(0.8)
    c.roundRect(margen, y - 34, 500, 34, 4, stroke=1, fill=0)
    c.setFillColor(naranja)
    c.setFont('Helvetica-Bold', 11)
    c.drawString(margen + 10, y - 21, 'Su valor pendiente es:')
    c.setFillColor(black)
    c.setFont('Helvetica-Bold', 13)
    c.drawRightString(margen + 490, y - 21, _money_text(ingreso.diferencia))
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

        for pago in pagos_detallados[:6]:
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
        if len(pagos_detallados) > 6:
            c.setFont('Helvetica-Oblique', 6.8)
            c.drawString(margen, y, f'Hay {len(pagos_detallados) - 6} pago(s) adicional(es) en el historial de abonos.')
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
    c.save()

    pdf = buf.getvalue()
    buf.close()

    response = HttpResponse(pdf, content_type='application/pdf')
    response['Content-Disposition'] = (
        f'attachment; filename="salida_equipo_{ingreso.codigo_equipo}.pdf"'
    )
    return response
