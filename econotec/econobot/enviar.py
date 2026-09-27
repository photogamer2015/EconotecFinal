"""Envía los datos reunidos por el chat a las MISMAS vistas del sistema.

EconoBot no guarda registros por su cuenta: arma exactamente el formulario
que enviaría la página web y lo entrega a la vista original (registrar
ingreso, finalizar, valor acordado, salida física…). Así se aplican las
mismas validaciones, permisos, bitácora, correos y notificaciones.
"""
from dataclasses import dataclass, field
from urllib.parse import urlparse

from django.contrib.messages.storage.base import BaseStorage
from django.http import HttpRequest, QueryDict
from django.urls import Resolver404, resolve


class _MensajesInternos(BaseStorage):
    """Recoge los avisos que la vista genera para mostrarlos en el chat."""

    def _get(self, *args, **kwargs):
        return [], True

    def _store(self, messages, response, *args, **kwargs):
        return []


class _SolicitudInterna(HttpRequest):
    """Copia de la solicitud del chat con los datos del formulario."""

    def __init__(self, original, metodo, datos):
        super().__init__()
        self._original = original
        self.method = metodo
        self.user = original.user
        self.session = original.session
        self.META = original.META.copy()
        self.META['REQUEST_METHOD'] = metodo
        self.COOKIES = original.COOKIES
        self.path = self.path_info = original.path
        consulta = QueryDict(mutable=True)
        for clave, valor in (datos or {}).items():
            if valor is None:
                valor = ''
            if isinstance(valor, (list, tuple)):
                consulta.setlist(clave, [str(v) for v in valor])
            else:
                consulta[clave] = str(valor)
        consulta._mutable = False
        if metodo == 'POST':
            self.POST = consulta
        else:
            self.GET = consulta
        self._messages = _MensajesInternos(self)
        self.resolver_match = None
        self._dont_enforce_csrf_checks = True

    def _get_scheme(self):
        return self._original.scheme

    def get_host(self):
        return self._original.get_host()


@dataclass
class Resultado:
    status: int
    destino: str = ''
    destino_nombre: str = ''
    destino_kwargs: dict = field(default_factory=dict)
    mensajes: list = field(default_factory=list)
    respuesta: object = None

    @property
    def redirigio(self):
        return self.status in (301, 302, 303) and bool(self.destino)

    def mensajes_de(self, *niveles):
        return [texto for nivel, texto in self.mensajes if not niveles or nivel in niveles]

    @property
    def errores(self):
        return [texto for nivel, texto in self.mensajes if nivel == 'error']


def solicitud_interna(request, datos=None, metodo='POST'):
    return _SolicitudInterna(request, metodo, datos)


def enviar(request, vista, *args, datos=None, metodo='POST', **kwargs):
    """Ejecuta la vista original con los datos del formulario y resume el resultado."""
    interna = _SolicitudInterna(request, metodo, datos)
    respuesta = vista(interna, *args, **kwargs)
    destino = respuesta.get('Location', '') if hasattr(respuesta, 'get') else ''
    nombre, argumentos = '', {}
    if destino:
        try:
            coincidencia = resolve(urlparse(destino).path)
            nombre, argumentos = coincidencia.url_name or '', dict(coincidencia.kwargs)
        except Resolver404:
            pass
    mensajes = [
        (mensaje.level_tag, str(mensaje.message))
        for mensaje in getattr(interna._messages, '_queued_messages', [])
    ]
    return Resultado(
        status=respuesta.status_code,
        destino=destino,
        destino_nombre=nombre,
        destino_kwargs=argumentos,
        mensajes=mensajes,
        respuesta=respuesta,
    )
