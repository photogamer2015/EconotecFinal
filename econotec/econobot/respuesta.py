"""Forma común de las respuestas que el chat muestra en pantalla.

El texto siempre viaja como texto plano: la interfaz lo pinta sin HTML.
Los enlaces se limitan a rutas internas del sistema o a WhatsApp.
"""
from urllib.parse import urlparse

from django.urls import reverse


def respuesta(texto, enlaces=None, opciones=None, **extra):
    datos = {
        'reply': texto,
        'links': [e for e in (enlaces or []) if e],
        'options': [o for o in (opciones or []) if o],
    }
    datos.update({clave: valor for clave, valor in extra.items() if valor is not None})
    return datos


def enlace(etiqueta, ruta, *args, tipo='nav', **kwargs):
    return {'label': etiqueta, 'url': reverse('econotec:' + ruta, args=args or None, kwargs=kwargs or None), 'kind': tipo}


def enlace_url(etiqueta, url, tipo='nav'):
    """Enlace ya construido: solo rutas del sistema o WhatsApp."""
    if not url:
        return None
    partes = urlparse(url)
    if partes.scheme in ('', ) and url.startswith('/') and not url.startswith('//'):
        return {'label': etiqueta, 'url': url, 'kind': tipo}
    if partes.scheme == 'https' and partes.hostname in ('wa.me', 'api.whatsapp.com', 'web.whatsapp.com'):
        return {'label': etiqueta, 'url': url, 'kind': 'wa'}
    return None


def opcion(etiqueta, valor=None):
    return {'label': etiqueta, 'value': valor if valor is not None else etiqueta}


def lista(lineas):
    return '\n'.join(linea for linea in lineas if linea is not None)
