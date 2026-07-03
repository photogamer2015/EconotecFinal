"""
Utilidades para generar el código QR de la Solicitud de Ingreso.

ESTRATEGIA: QR HÍBRIDO (datos embebidos + enlace)
─────────────────────────────────────────────────────────────────────────
El QR contiene un texto legible con:
  1) Un RESUMEN de los datos clave de la hoja (equipo, cliente, problema…),
     embebido directamente. Así, aunque no haya internet o el equipo cambie
     de estado más tarde, el QR por sí solo sigue mostrando la información
     esencial tal como estaba al imprimirse.
  2) Un ENLACE firmado a la "hoja digital" viva del equipo (vista móvil del
     técnico). Al tocarlo, el técnico ve el estado actual y puede editar el
     reporte y cambiar el estado.

El enlace incluye un token firmado (HMAC con SECRET_KEY) derivado del pk del
ingreso, para que no se puedan adivinar/iterar URLs de otros equipos.

NOTA sobre capacidad: un QR tiene espacio limitado. Por eso el resumen
embebido recorta los textos largos (problema, accesorios) a un máximo
razonable; la versión completa siempre está a un toque de distancia en el
enlace.
─────────────────────────────────────────────────────────────────────────
"""
import base64
from io import BytesIO

import qrcode
from qrcode.constants import ERROR_CORRECT_M, ERROR_CORRECT_H
from django.core import signing


# Namespace del firmado de tokens de hoja de equipo.
_FIRMA_SALT = 'econotec.hoja_equipo'

# Límites de recorte para mantener el QR escaneable.
_MAX_PROBLEMA = 90
_MAX_ACCESORIOS = 50


def token_para_ingreso(pk):
    """Devuelve un token firmado y url-safe para el ingreso indicado."""
    return signing.dumps(int(pk), salt=_FIRMA_SALT)


def pk_desde_token(token, max_age=None):
    """
    Recupera el pk del ingreso desde un token firmado.

    Devuelve el pk (int) si el token es válido, o None si es inválido/alterado.
    `max_age` (segundos) es opcional; por defecto los tokens no caducan, porque
    la hoja del equipo debe poder consultarse durante toda la vida del equipo
    en el taller.
    """
    try:
        return signing.loads(token, salt=_FIRMA_SALT, max_age=max_age)
    except signing.BadSignature:
        return None


def url_hoja_movil(request, ingreso):
    """
    Construye la URL absoluta a la hoja móvil del técnico para este ingreso,
    incluyendo el token firmado.

    Ej: https://midominio.com/tecnico/hoja/<token>/
    """
    from django.urls import reverse
    token = token_para_ingreso(ingreso.pk)
    ruta = reverse('econotec:tecnico_hoja', kwargs={'token': token})
    return request.build_absolute_uri(ruta)


def _recortar(texto, maximo):
    """Recorta un texto a `maximo` caracteres, añadiendo … si se cortó."""
    texto = (texto or '').strip().replace('\r', ' ').replace('\n', ' ')
    if len(texto) > maximo:
        return texto[:maximo - 1].rstrip() + '…'
    return texto


def contenido_qr_para_ingreso(request, ingreso):
    """
    Devuelve la URL pura para que Android y iOS la abran directamente.
    Al contener únicamente una URL, cualquier app de cámara detectará que
    es un enlace y sugerirá navegar a la página web de inmediato.
    """
    return url_hoja_movil(request, ingreso)


def qr_data_uri(texto, box_size=8, border=2, error_correction=ERROR_CORRECT_M, label=None):
    """
    Genera un QR a partir de `texto` y lo devuelve como Data URI PNG en base64,
    listo para incrustar directamente en <img src="...">.
    
    No requiere guardar archivos: el QR vive embebido en el HTML.
    """
    return 'data:image/png;base64,' + base64.b64encode(
        qr_png_bytes(texto, box_size=box_size, border=border,
                     error_correction=error_correction)
    ).decode('ascii')


def qr_png_bytes(texto, box_size=8, border=2, error_correction=ERROR_CORRECT_M, top_lines=None, bottom_lines=None):
    """
    Genera un QR a partir de `texto` y devuelve los BYTES del PNG.
    Útil para descargas (HttpResponse con Content-Disposition: attachment).
    """
    qr = qrcode.QRCode(
        version=None,                 # autoajusta el tamaño según el contenido
        error_correction=error_correction,
        box_size=box_size,
        border=border,
    )
    qr.add_data(texto)
    # Generate the base QR (black and white)
    qr.make(fit=True)
    img_base = qr.make_image(fill_color='black', back_color='white').get_image().convert('L')
    
    # Create a gradient image (black to deep red) for the QR fill
    from PIL import Image, ImageDraw
    img_width, img_height = img_base.size
    gradient = Image.new('RGB', (img_width, img_height))
    draw_grad = ImageDraw.Draw(gradient)
    
    # Econotec colors: Black (#1f2937 or #111) to Red (#c62828 or #d9381e)
    r1, g1, b1 = 20, 20, 20       # Almost black
    r2, g2, b2 = 190, 30, 20      # Deep red
    
    for y in range(img_height):
        # Linear gradient from top to bottom
        factor = y / img_height
        r = int(r1 + (r2 - r1) * factor)
        g = int(g1 + (g2 - g1) * factor)
        b = int(b1 + (b2 - b1) * factor)
        draw_grad.line([(0, y), (img_width, y)], fill=(r, g, b))
        
    # Create the final QR image using the base as a mask:
    # Where img_base is black (0), we want the gradient.
    # Where img_base is white (255), we want white.
    # So we composite white and gradient using img_base as the mask (inverted).
    from PIL import ImageOps
    mask = ImageOps.invert(img_base)  # Now QR data is white (255), bg is black (0)
    white_bg = Image.new('RGB', (img_width, img_height), 'white')
    img = Image.composite(gradient, white_bg, mask)

    from django.conf import settings
    import os
    logo_path = os.path.join(settings.BASE_DIR, 'static', 'logo.png')
    if not os.path.exists(logo_path):
        logo_path = os.path.join(settings.BASE_DIR, 'static', 'logo.jpg')

    if os.path.exists(logo_path):
        from PIL import Image
        try:
            logo = Image.open(logo_path)
            if logo.mode != 'RGBA':
                logo = logo.convert('RGBA')
            
            resample_filter = getattr(Image, 'Resampling', Image).LANCZOS
            
            max_logo_size = int(img.width * 0.28)
            logo.thumbnail((max_logo_size, max_logo_size), resample_filter)
            
            logo_pos = ((img.width - logo.width) // 2, (img.height - logo.height) // 2)
            
            pad = int(img.width * 0.015)
            # Create a rounded rectangle background for the logo
            logo_bg = Image.new('RGBA', (logo.width + pad*2, logo.height + pad*2), (255, 255, 255, 0))
            draw_logo_bg = ImageDraw.Draw(logo_bg)
            # Draw rounded rectangle (supported in newer Pillow)
            if hasattr(draw_logo_bg, 'rounded_rectangle'):
                draw_logo_bg.rounded_rectangle([0, 0, logo.width + pad*2, logo.height + pad*2], radius=10, fill='white')
            else:
                draw_logo_bg.rectangle([0, 0, logo.width + pad*2, logo.height + pad*2], fill='white')
            
            # Paste the rounded white background first (using itself as mask for rounded corners)
            img.paste(logo_bg, (logo_pos[0] - pad, logo_pos[1] - pad), mask=logo_bg)
            
            # Paste logo
            img.paste(logo, logo_pos, mask=logo)
        except Exception as e:
            print("Error pegando el logo en el QR:", e)

    if top_lines or bottom_lines:
        from PIL import Image, ImageDraw, ImageFont
        font_size_main = max(16, int(box_size * 2.5))
        font_size_sub = max(12, int(box_size * 1.5))
        
        try:
            font_main = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", font_size_main)
            font_sub = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", font_size_sub)
        except Exception:
            try:
                font_main = ImageFont.truetype("Arial.ttf", font_size_main)
                font_sub = ImageFont.truetype("Arial.ttf", font_size_sub)
            except Exception:
                font_main = ImageFont.load_default()
                font_sub = ImageFont.load_default()

        def draw_lines(draw, lines, y_start, font_m, font_s):
            y = y_start
            for idx, text in enumerate(lines):
                font = font_m if idx == 0 else font_s
                if hasattr(draw, 'textbbox'):
                    bbox = draw.textbbox((0, 0), text, font=font)
                    tw = bbox[2] - bbox[0]
                    th = bbox[3] - bbox[1]
                else:
                    tw, th = draw.textsize(text, font=font)
                x = (img.width - tw) // 2
                draw.text((x, y), text, fill='#1f2937' if idx == 0 else '#555555', font=font)
                y += th + 6
            return y - y_start

        top_h = len(top_lines) * (font_size_main + 6) + 10 if top_lines else 0
        bottom_h = len(bottom_lines) * (font_size_main + 6) + 10 if bottom_lines else 0
        
        new_img = Image.new('RGB', (img.width, img.height + top_h + bottom_h), 'white')
        new_img.paste(img, (0, top_h))
        
        draw = ImageDraw.Draw(new_img)
        if top_lines:
            draw_lines(draw, top_lines, 10, font_main, font_sub)
        if bottom_lines:
            draw_lines(draw, bottom_lines, img.height + top_h + 4, font_main, font_sub)
            
        img = new_img

    buf = BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()


def qr_data_uri_para_ingreso(request, ingreso, **kwargs):
    """
    Genera el QR (Data URI) HÍBRIDO del ingreso: resumen de datos embebido +
    enlace a la hoja viva del técnico.

    Como el contenido es más largo que una simple URL, usamos corrección de
    error 'L' (más capacidad de datos) para que el QR no crezca demasiado y
    siga siendo cómodo de escanear desde el papel.
    """
    kwargs.setdefault('error_correction', ERROR_CORRECT_H)
    kwargs['label'] = f"Equipo {ingreso.codigo_equipo}"
    texto = contenido_qr_para_ingreso(request, ingreso)
    return qr_data_uri(texto, **kwargs)


def qr_png_bytes_para_ingreso(request, ingreso, **kwargs):
    """
    Genera los BYTES del PNG del QR HÍBRIDO del ingreso, para descarga directa.
    Usa una resolución más alta por defecto (box_size grande) para que la
    imagen descargada se vea nítida al imprimirla o pegarla en otro documento.
    """
    kwargs.setdefault('error_correction', ERROR_CORRECT_H)
    kwargs.setdefault('box_size', 12)
    kwargs.setdefault('border', 4)
    
    top_lines = [ingreso.cliente.nombres, ingreso.cliente.whatsapp] if ingreso.cliente.whatsapp else [ingreso.cliente.nombres]
    bottom_lines = [ingreso.codigo_equipo, ingreso.tipo_equipo_display.upper()]
    
    kwargs['top_lines'] = top_lines
    kwargs['bottom_lines'] = bottom_lines
    if 'label' in kwargs:
        del kwargs['label']
        
    texto = contenido_qr_para_ingreso(request, ingreso)
    return qr_png_bytes(texto, **kwargs)
