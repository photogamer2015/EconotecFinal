"""Motor común de los registros guiados por chat.

Cada flujo declara sus preguntas activas según las respuestas, valida con
los formularios reales del sistema y, al confirmar, envía los datos a la
vista original. Mientras tanto no se escribe nada en la base de datos.
"""
import re

from ..busqueda import normalizar_texto_busqueda
from . import texto as tx
from .respuesta import opcion, respuesta


ESTADO_SESION = 'econobot_estado_v1'


class Pregunta:
    """Un dato que el chat necesita, con la forma de interpretarlo."""

    def __init__(self, clave, etiqueta, texto, tipo='texto', opciones=None,
                 opcional=False, ayuda='', libre=False, sugerencias=None,
                 max_opciones=14):
        self.clave = clave
        self.etiqueta = etiqueta
        self.texto = texto
        self.tipo = tipo
        self.opciones = list(opciones or [])
        self.opcional = opcional
        self.ayuda = ayuda
        # En texto libre una frase suelta es el dato, nunca una orden.
        self.libre = libre or tipo in ('texto_largo',)
        self.sugerencias = list(sugerencias or [])
        self.max_opciones = max_opciones


class Flujo:
    """Base de un registro guiado. Las subclases definen el contenido."""

    nombre = ''
    titulo = ''
    verbo_confirmar = 'Registrar'
    pregunta_confirmacion = '¿Lo registro?'
    alias = {}

    def __init__(self, request, estado):
        self.request = request
        self.user = request.user
        self.estado = estado
        self.datos = estado.setdefault('datos', {})
        self._cache = {}

    # ── Contenido que define cada flujo ──────────────────────────────
    def preguntas(self):
        return []

    def errores(self):
        """Errores de los formularios reales, por clave de pregunta."""
        return {}

    def resumen(self):
        return ''

    def ejecutar(self):
        raise NotImplementedError

    def al_capturar(self, clave, valor):
        """Gancho para completar datos relacionados (p. ej. cliente existente)."""
        return []

    def interpretar_especial(self, pregunta, mensaje):
        """Permite a un flujo interpretar tipos propios. (valor, error) o None."""
        return None

    # ── Utilidades ───────────────────────────────────────────────────
    def cache(self, clave, funcion):
        if clave not in self._cache:
            self._cache[clave] = funcion()
        return self._cache[clave]

    def olvidar_cache(self):
        self._cache = {}

    def pregunta_por_clave(self, clave):
        for pregunta in self.preguntas():
            if pregunta.clave == clave:
                return pregunta
        return None

    def guardar(self):
        self.request.session[ESTADO_SESION] = self.estado_global

    @property
    def estado_global(self):
        return self.request.session.get(ESTADO_SESION) or {}


# ─────────────────────────────────────────────────────────────────────
# Interpretación de respuestas
# ─────────────────────────────────────────────────────────────────────

def interpretar(flujo, pregunta, mensaje):
    """Convierte el mensaje en el valor de la pregunta. Devuelve (valor, error)."""
    especial = flujo.interpretar_especial(pregunta, mensaje)
    if especial is not None:
        return especial

    crudo = (mensaje or '').strip()
    if pregunta.opcional and tx.es_omitir(crudo) and pregunta.tipo != 'sino':
        return '', None

    tipo = pregunta.tipo
    if tipo in ('texto', 'texto_largo'):
        if not crudo:
            return None, 'Escribe el dato para continuar.'
        return crudo, None
    if tipo == 'sino':
        valor = tx.sino(crudo)
        if valor is None:
            return None, 'Responde «sí» o «no».'
        return valor, None
    if tipo == 'opcion':
        valor = tx.elegir(crudo, pregunta.opciones)
        if valor is None:
            return None, 'No identifiqué una opción válida. Elige una de la lista (puedes escribir su número).'
        return str(valor), None
    if tipo == 'dinero':
        if tx.es_no(crudo) and pregunta.clave in ('abono_anticipo', 'pago_ahora'):
            return '0.00', None
        valor = tx.dinero(crudo)
        if valor is None:
            return None, 'Escribe un monto válido, por ejemplo 25 o 25,50.'
        return valor, None
    if tipo == 'fecha':
        valor = tx.fecha(crudo)
        if valor is None:
            return None, 'Escribe la fecha como DD/MM/AAAA o «hoy».'
        return valor, None
    if tipo == 'digitos':
        valor = tx.solo_digitos(tx.solo_espacios_numericos(crudo))
        if not valor:
            return None, 'Escribe solo números.'
        return valor, None
    if tipo == 'correo':
        valor = crudo.replace(' ', '').lower()
        if '@' not in valor:
            return None, 'Escribe un correo válido (con @) o «omitir».'
        return valor, None
    if tipo == 'url':
        valor = crudo.strip()
        if not re.match(r'^https?://', valor, re.IGNORECASE):
            return None, 'Pega un enlace que empiece con https:// o escribe «omitir».'
        return valor, None
    if tipo == 'firma':
        return None, 'Usa el recuadro para que el cliente firme, o escribe «no firma».'
    return crudo, None


# ─────────────────────────────────────────────────────────────────────
# «campo: valor» — varios datos en un solo mensaje
# ─────────────────────────────────────────────────────────────────────

def extraer_pares(flujo, mensaje):
    alias = flujo.alias
    if not alias or not mensaje:
        return {}
    normalizado = normalizar_texto_busqueda(mensaje)
    original = mensaje if len(normalizado) == len(mensaje) else normalizado
    patron = (r'(?:^|(?<=[\n;,]))\s*(' + '|'.join(sorted(map(re.escape, alias), key=len, reverse=True))
              + r')\s*(?::|=)\s*')
    coincidencias = list(re.finditer(patron, normalizado))
    pares = {}
    for indice, coincidencia in enumerate(coincidencias):
        fin = coincidencias[indice + 1].start() if indice + 1 < len(coincidencias) else len(original)
        valor = original[coincidencia.end():fin].strip(' ,;\n\t')
        pares[alias[coincidencia.group(1)]] = valor
    return pares


def clave_mencionada(flujo, mensaje):
    """Dato que la persona quiere corregir: «corregir marca»."""
    t = tx.limpiar(mensaje)
    for nombre in sorted(flujo.alias, key=len, reverse=True):
        if re.search(r'\b' + re.escape(nombre) + r'\b', t):
            return flujo.alias[nombre]
    return None


# ─────────────────────────────────────────────────────────────────────
# Avance del registro
# ─────────────────────────────────────────────────────────────────────

def recordar(estado, clave):
    orden = [c for c in estado.get('orden', []) if c != clave]
    orden.append(clave)
    estado['orden'] = orden


def aplicar(flujo, clave, valor):
    flujo.datos[clave] = valor
    recordar(flujo.estado, clave)
    avisos = flujo.al_capturar(clave, valor) or []
    flujo.olvidar_cache()
    return avisos


def deshacer(flujo):
    orden = list(flujo.estado.get('orden', []))
    while orden:
        clave = orden.pop()
        if clave in flujo.datos and not clave.startswith('_'):
            flujo.datos.pop(clave, None)
            flujo.estado['orden'] = orden
            flujo.estado['confirmando'] = False
            flujo.olvidar_cache()
            return clave
    flujo.estado['orden'] = orden
    return None


def opciones_de(pregunta):
    if pregunta.tipo == 'sino':
        chips = [opcion('Sí'), opcion('No')]
    elif pregunta.tipo == 'opcion':
        chips = [opcion(etiqueta, etiqueta) for _valor, etiqueta in pregunta.opciones[:pregunta.max_opciones]]
    else:
        chips = [opcion(s) for s in pregunta.sugerencias]
    if pregunta.opcional and pregunta.tipo not in ('sino',):
        chips.append(opcion('Omitir'))
    return chips


def preguntar(flujo, pregunta, error='', avisos=None):
    flujo.estado['esperando'] = pregunta.clave
    flujo.estado['confirmando'] = False
    flujo.estado['corrigiendo'] = False
    lineas = list(avisos or [])
    if error:
        lineas.append('⚠️ ' + error)
    lineas.append(pregunta.texto)
    if pregunta.tipo == 'opcion' and len(pregunta.opciones) > pregunta.max_opciones:
        lineas.append('Opciones: ' + ', '.join(f'{i}. {e}' for i, (_v, e) in enumerate(pregunta.opciones, 1)))
    if pregunta.ayuda:
        lineas.append(pregunta.ayuda)
    if pregunta.opcional and pregunta.tipo not in ('sino',):
        lineas.append('Es opcional: puedes escribir «omitir».')
    if not flujo.estado.get('guia_mostrada'):
        lineas.append('Tip: escribe «atrás» para corregir el dato anterior o «cancelar» para salir. '
                      'También puedes enviar varios datos juntos, por ejemplo «marca: HP; modelo: 250 G8».')
        flujo.estado['guia_mostrada'] = True
    extra = {'widget': 'firma'} if pregunta.tipo == 'firma' else {}
    return respuesta('\n'.join(lineas), opciones=opciones_de(pregunta), **extra)


def confirmar(flujo, avisos=None, errores_generales=None):
    flujo.estado['confirmando'] = True
    flujo.estado['esperando'] = None
    flujo.estado['corrigiendo'] = False
    lineas = list(avisos or [])
    lineas.append(flujo.resumen())
    for error in errores_generales or []:
        lineas.append('⚠️ ' + error)
    lineas.append(flujo.pregunta_confirmacion)
    return respuesta(
        '\n'.join(lineas),
        opciones=[
            opcion('✅ ' + flujo.verbo_confirmar, 'sí'),
            opcion('✏️ Corregir un dato', 'corregir'),
            opcion('Cancelar', 'cancelar'),
        ],
    )


def siguiente(flujo, avisos=None):
    """Pregunta el primer dato faltante o inválido; si no hay, pide confirmación."""
    preguntas = flujo.preguntas()
    errores = flujo.errores()
    invalidas = [p for p in preguntas if p.clave in flujo.datos and errores.get(p.clave)]
    faltantes = [p for p in preguntas if p.clave not in flujo.datos]
    if invalidas:
        pregunta = invalidas[0]
        flujo.datos.pop(pregunta.clave, None)
        return preguntar(flujo, pregunta, ' '.join(errores[pregunta.clave]), avisos)
    if faltantes:
        return preguntar(flujo, faltantes[0], '', avisos)
    generales = errores.get('__all__') or []
    return confirmar(flujo, avisos, generales)


def avanzar(flujo, mensaje, firma=None):
    """Procesa una respuesta dentro de un registro en curso."""
    estado = flujo.estado
    texto = (mensaje or '').strip()

    if estado.get('confirmando'):
        pares = extraer_pares(flujo, texto)
        if pares:
            avisos = []
            for clave, valor in pares.items():
                pregunta = flujo.pregunta_por_clave(clave)
                if pregunta is None:
                    continue
                interpretado, error = interpretar(flujo, pregunta, valor)
                if error:
                    return preguntar(flujo, pregunta, error)
                avisos += aplicar(flujo, clave, interpretado)
            return siguiente(flujo, avisos)
        if tx.es_si(texto) and not estado.get('corrigiendo'):
            return flujo.ejecutar()
        t = tx.limpiar(texto)
        pide_correccion = (
            t.startswith('corregir') or t.startswith('cambiar') or t.startswith('editar')
            or tx.es_no(texto) or estado.get('corrigiendo')
        )
        if pide_correccion:
            clave = clave_mencionada(flujo, texto)
            if clave and flujo.pregunta_por_clave(clave):
                estado['corrigiendo'] = False
                flujo.datos.pop(clave, None)
                flujo.olvidar_cache()
                return preguntar(flujo, flujo.pregunta_por_clave(clave))
            if estado.get('corrigiendo') and tx.es_si(texto):
                estado['corrigiendo'] = False
                return confirmar(flujo)
            respondidas = [p for p in flujo.preguntas() if p.clave in flujo.datos and not p.clave.startswith('_')]
            estado['corrigiendo'] = True
            return respuesta(
                '¿Qué dato quieres corregir? Elige uno o escribe «campo: nuevo valor».',
                opciones=[opcion(p.etiqueta, 'corregir ' + p.etiqueta) for p in respondidas[:16]],
            )
        return confirmar(flujo, ['Responde «sí» para guardar, «corregir» para cambiar un dato o «cancelar».'])

    # Firma dibujada en el recuadro del chat.
    if firma is not None and estado.get('esperando'):
        pregunta = flujo.pregunta_por_clave(estado['esperando'])
        if pregunta is not None and pregunta.tipo == 'firma':
            avisos = aplicar(flujo, pregunta.clave, firma)
            return siguiente(flujo, avisos)

    pares = extraer_pares(flujo, texto)
    avisos = []
    if pares:
        for clave, valor in pares.items():
            pregunta = flujo.pregunta_por_clave(clave)
            if pregunta is None:
                avisos.append(f'Por ahora no necesito «{clave.replace("_", " ")}» en este registro; lo dejé de lado.')
                continue
            interpretado, error = interpretar(flujo, pregunta, valor)
            if error:
                return preguntar(flujo, pregunta, error, avisos)
            avisos += aplicar(flujo, clave, interpretado)
        return siguiente(flujo, avisos)

    esperando = estado.get('esperando')
    if esperando:
        pregunta = flujo.pregunta_por_clave(esperando)
        if pregunta is not None:
            if not texto:
                return preguntar(flujo, pregunta)
            interpretado, error = interpretar(flujo, pregunta, texto)
            if error:
                return preguntar(flujo, pregunta, error)
            avisos += aplicar(flujo, pregunta.clave, interpretado)
    return siguiente(flujo, avisos)


def pendiente_actual(flujo):
    """Repite la pregunta en curso sin cambiar nada (al reabrir el chat)."""
    if flujo.estado.get('confirmando'):
        return confirmar(flujo)
    esperando = flujo.estado.get('esperando')
    pregunta = flujo.pregunta_por_clave(esperando) if esperando else None
    if pregunta is not None:
        guia = flujo.estado.get('guia_mostrada')
        flujo.estado['guia_mostrada'] = True
        resultado = preguntar(flujo, pregunta)
        flujo.estado['guia_mostrada'] = guia
        return resultado
    return siguiente(flujo)
