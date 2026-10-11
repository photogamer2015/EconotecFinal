"""
Clip corto del tema de Tetris al registrar un equipo.

La vista que registra el equipo deja el clip pendiente en la sesión y
base.html lo toma una sola vez en la página a la que se redirige: recargar
esa página no lo vuelve a reproducir.
"""
import time

SONIDO_SESION = 'sonido_pendiente'
# Si la página de destino no usa base.html, el clip no debe sonar más tarde
# en otra página que no tiene nada que ver.
SONIDO_VIGENCIA_SEGUNDOS = 60

CLIPS = {
    'registro_equipo': 'sonidos/tetris-registro.mp3',  # 5 s
}


def programar_sonido(request, nombre):
    """Deja el clip `nombre` listo para la próxima página del usuario."""
    if nombre in CLIPS:
        request.session[SONIDO_SESION] = [nombre, int(time.time())]


def tomar_sonido_pendiente(request):
    """Ruta estática del clip pendiente (y lo quita de la sesión), o ''."""
    session = getattr(request, 'session', None)
    if session is None or SONIDO_SESION not in session:
        return ''
    valor = session.pop(SONIDO_SESION, None)
    if not (isinstance(valor, (list, tuple)) and len(valor) == 2):
        return ''
    nombre, programado = valor
    if not isinstance(programado, int) or time.time() - programado > SONIDO_VIGENCIA_SEGUNDOS:
        return ''
    return CLIPS.get(nombre, '')
