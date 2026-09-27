"""Router de EconoBot: entiende el mensaje y decide qué hacer.

Orden de lectura:
1. Órdenes de control (cancelar, atrás, continuar, saludo, ayuda).
2. Un registro en curso recibe la respuesta a su pregunta pendiente.
3. Un paso corto en espera (p. ej. «¿qué equipo finalizo?»).
4. Un código de equipo (G1031) con o sin verbo.
5. Listas y consultas, acciones sin código, secciones y temas de ayuda.
"""
import json
import re

from .. import views as vistas
from ..models import Cliente, IngresoEquipo
from . import consultas, conocimiento
from . import texto as tx
from .acciones import (
    FlujoEstado, FlujoRetiro, FlujoValor, motivo_sin_cambio_estado, motivo_sin_retiro, motivo_sin_valor,
)
from .enviar import enviar
from .equipos import ingreso_por_codigo
from .finalizar import FlujoFinalizar, motivo_no_finalizable
from .flujo import ESTADO_SESION, aplicar, avanzar, deshacer, interpretar, pendiente_actual, siguiente
from .ingreso import FlujoIngreso
from .respuesta import enlace, opcion, respuesta

FLUJOS = {clase.nombre: clase for clase in (FlujoIngreso, FlujoFinalizar, FlujoEstado, FlujoValor, FlujoRetiro)}

_COLA = (r'(?:\s+(?:el|la|lo|los|las|un|una|este|esta|esto|eso|todo|nada|registro|proceso|ingreso|'
         r'finalizacion|cambio|por favor|gracias|ya))*$')
# Detener un registro debe funcionar con las formas naturales de pedirlo.
CANCELAR = re.compile(r'^(?:/clear|cancel\w*|anul\w*|deten\w*|salir|reinici\w*|empezar de nuevo|'
                      r'borrar todo|stop|ya no (?:lo )?(?:quiero|deseo) (?:registrar\w*|finalizar\w*|seguir|continuar))'
                      + _COLA)
# Formas breves de desistir: no se aplican si el dato pedido es texto libre.
CANCELAR_SUAVE = re.compile(r'^(?:olvida(?:lo|te)?|dejalo|dejemoslo|mejor no|ya no|no (?:lo )?(?:quiero|deseo))' + _COLA)
ATRAS = re.compile(r'^(?:atras|volver|regresar|anterior|paso anterior|volver atras|ir atras|dato anterior)$')
CONTINUAR = re.compile(r'^(?:continuar|seguir|sigamos|retomar|continuar registro|donde me quede|en que ibamos)$')
SALUDO = re.compile(r'^(?:hola|holi|hey|buen(?:os|as)(?: (?:dias|tardes|noches))?|saludos|que tal|buen dia)\b')
GRACIAS = re.compile(r'^(?:(?:muchas |mil )?gracias|ok gracias|listo gracias|genial|perfecto|excelente|chevere|bacan)\b')
AYUDA = re.compile(r'^(?:ayuda|help|menu|opciones|comandos|que (?:puedes|sabes) hacer|que haces|como funcionas|'
                   r'quien eres|que eres|econobot)\b')
EXPLICATIVA = re.compile(r'^(?:que (?:significa|es|son|quiere decir|pasa)|como|explica\w*|para que|por que|porque|'
                         r'en que consiste|cual es la regla|cuando se|cuanto (?:se )?cobra|cuanto cuesta|se puede|puedo)\b')
PREGUNTA = re.compile(r'^(?:como|que|cual|cuales|cuando|donde|por que|para que|quien|cuant\w+)\b')
# Mensajes que son órdenes o preguntas al sistema y no la respuesta a un dato.
ORDEN = re.compile(
    r'^(?:ver|mostrar|muestrame|abrir|abre|ir a|ve a|llevame|buscar|busca|consultar|lista\w*|alertas?|ayuda|'
    r'resumen|estadisticas|cuant\w+|cuales|que (?:es|son|significa|equipos)|como|donde|finaliz\w*|registr\w*|'
    r'confirmar salida|cambiar estado|valor acordado|reporte|enviar acta|mis equipos|equipos|clientes?)\b'
)

VERBO_FINALIZAR = re.compile(r'\b(?:finaliz\w*|equipo listo|dar(?:le)? (?:por )?finalizado|terminar|termine|termino|'
                             r'cerrar el trabajo)\b')
VERBO_RETIRO = re.compile(r'\b(?:confirmar? (?:la )?salida|confirma (?:la )?salida|salida fisica|retir\w*|se lo llevo|'
                          r'se la llevo|ya salio|entreg\w*)\b')
VERBO_ACTA = re.compile(r'\b(?:enviar|envia|mandar|manda|reenviar|reenvia)\b.*\bacta\b|\bacta por correo\b')
VERBO_VALOR = re.compile(r'\b(?:valor acordado|valor|precio|cotizacion)\b')
VERBO_REPORTE = re.compile(r'\b(?:reporte|informe|nota del tecnico)\b')
VERBO_ESTADO = re.compile(r'\b(?:estado|pasar a|pasalo a|marcar como|marcalo como|ponerlo en|poner en|en reparacion|'
                          r'en diagnostico|ingresado)\b')
VERBO_REGISTRAR = re.compile(
    r'^(?:quiero |necesito |vamos a |voy a |ayudame a |puedes |podrias )?(?:registr\w*|ingres(?:ar|a|o|e)|nuevo ingreso|'
    r'nueva solicitud|recibir|recibi|agregar|anadir|crear)\b'
)
PRONOMBRE = re.compile(r'^(?:finalizal[oa]|confirmal[oa]|cambial[oa]|pasal[oa]|marcal[oa]|envial[oa]|mandal[oa])\b'
                       r'|\b(?:este equipo|ese equipo|el mismo|el ultimo|ese|este)\b')
SALUDO_INICIAL = re.compile(r'^\s*(?:hola|holi|hey|buen[oa]s(?:\s+(?:d[ií]as|tardes|noches))?|saludos|qu[eé] tal|'
                            r'buen d[ií]a)\b[\s,.;:!¡]*', re.IGNORECASE)

RESULTADOS_TEXTO = [
    (r'no se pudo|no reparable|sin solucion|no tiene arreglo', 'no_reparable'),
    (r'no quiso|no acepta|no acepto|rechazo', 'cliente_no_acepta'),
    (r'fallos adicionales', 'garantia_fallos_adicionales'),
    (r'garantia', 'garantia'),
    (r'revision', 'revision'),
    (r'cortesia', 'cortesia'),
    (r'reparad\w*|con solucion|arreglad\w*|quedo listo', 'pendiente_retiro'),
]

LISTAS = [
    (re.compile(r'\b(?:mis equipos|mis pendientes|asignados a mi|mis reparaciones|mi taller)\b'),
     lambda request, m: consultas.en_taller(request, m, solo_mios=True)),
    (re.compile(r'\b(?:salidas? fisicas?|retirados|ya retiraron|se llevaron|salieron de la oficina)\b'),
     consultas.salidas_fisicas),
    (re.compile(r'\b(?:finalizad[oa]s|equipos? listos?|listos para retirar|pendientes? de retiro|por retirar|'
                r'en (?:la )?oficina|esperando retiro)\b'), consultas.finalizados_en_oficina),
    (re.compile(r'\b(?:sin valor|valor(?:es)? (?:acordados? )?pendientes?|faltan? (?:el )?valor|sin precio)\b'),
     consultas.sin_valor_acordado),
    (re.compile(r'\b(?:saldos?|por cobrar|cobros pendientes|deudas?|deben)\b'), consultas.saldos_pendientes),
    (re.compile(r'\b(?:alertas?|demorados?|atrasados?|con bodegaje|bodegajes pendientes|equipos con bodegaje)\b'),
     lambda request, m: consultas.alertas(request)),
    (re.compile(r'\b(?:en (?:el )?taller|en reparacion|en diagnostico|por reparar|pendientes? de reparar|'
                r'equipos pendientes|equipos activos|ingresad[oa]s)\b'), consultas.en_taller),
    (re.compile(r'\b(?:ultimos (?:equipos|ingresos)|ingresos de hoy|registrados hoy|ingresaron hoy|ultimos registros)\b'),
     consultas.ultimos_ingresos),
    (re.compile(r'\b(?:top clientes|mejores clientes|clientes (?:recurrentes|frecuentes))\b'),
     lambda request, m: consultas.top_clientes()),
    (re.compile(r'\b(?:resumen|estadisticas?|como vamos|numeros del dia|reporte del dia|cuantos equipos)\b'),
     lambda request, m: consultas.estadisticas(request)),
]


# ─────────────────────────────────────────────────────────────────────
# Estado de la conversación (en la sesión del usuario)
# ─────────────────────────────────────────────────────────────────────

def _estado(request):
    estado = request.session.get(ESTADO_SESION)
    return estado if isinstance(estado, dict) else {}


def _guardar(request, estado):
    request.session[ESTADO_SESION] = estado
    request.session.modified = True


def _flujo(request, estado):
    datos = estado.get('flujo')
    if not isinstance(datos, dict):
        return None
    clase = FLUJOS.get(datos.get('nombre'))
    if clase is None:
        estado.pop('flujo', None)
        return None
    return clase(request, datos)


def _finalizar_respuesta(request, estado, resultado):
    """Aplica los efectos de la respuesta en el estado y la deja lista para la interfaz."""
    resultado = dict(resultado)
    if resultado.pop('hecho', False):
        estado.pop('flujo', None)
    ultimo = resultado.pop('ultimo_equipo', None)
    if ultimo:
        estado['ultimo_equipo'] = ultimo
    esperar = resultado.pop('esperar', None)
    if esperar:
        estado['esperar'] = esperar if isinstance(esperar, dict) else {'tipo': esperar}
    flujo = _flujo(request, estado)
    resultado['pending'] = flujo is not None
    resultado['flow'] = flujo.titulo if flujo is not None else ''
    _guardar(request, estado)
    return resultado


# ─────────────────────────────────────────────────────────────────────
# Inicio de registros
# ─────────────────────────────────────────────────────────────────────

def _iniciar(request, estado, clase, *args, **kwargs):
    datos = {'nombre': clase.nombre}
    flujo = clase(request, datos)
    avisos = flujo.iniciar(*args, **kwargs) or []
    estado['flujo'] = datos
    estado.pop('esperar', None)
    return siguiente(flujo, avisos)


def _sede_valida(request):
    return (request.session.get('sede_actual') or '').strip().lower() in ('guayaquil', 'quito')


def iniciar_registro(request, estado, mensaje=''):
    if not _sede_valida(request):
        return respuesta('Tu sesión no tiene una sede de equipos (Guayaquil o Quito). Cierra sesión y vuelve a '
                         'entrar eligiendo la sede para registrar equipos.')
    return _iniciar(request, estado, FlujoIngreso, mensaje)


def iniciar_finalizar(request, estado, ingreso, mensaje=''):
    motivo = motivo_no_finalizable(ingreso)
    if motivo:
        return respuesta(motivo, [enlace('Abrir el equipo', 'ingreso_detalle', pk=ingreso.pk)] if ingreso else [],
                         [opcion(f'Ver {ingreso.codigo_equipo}', f'ver {ingreso.codigo_equipo}')] if ingreso else [],
                         ultimo_equipo=ingreso.pk if ingreso else None)
    datos = {'nombre': FlujoFinalizar.nombre}
    flujo = FlujoFinalizar(request, datos)
    flujo.iniciar(ingreso)
    t = tx.limpiar(mensaje)
    validos = {valor for valor, _etiqueta in flujo.opciones_resultado()}
    for patron, valor in RESULTADOS_TEXTO:
        if re.search(patron, t) and valor in validos:
            aplicar(flujo, 'resultado', valor)
            break
    estado['flujo'] = datos
    estado.pop('esperar', None)
    estado['ultimo_equipo'] = ingreso.pk
    return siguiente(flujo, [f'Vamos a finalizar {ingreso.codigo_equipo} ({ingreso.cliente.nombres}).'])


def iniciar_retiro(request, estado, ingreso):
    motivo = motivo_sin_retiro(ingreso)
    if motivo:
        opciones = []
        enlaces = []
        if ingreso is not None:
            opciones.append(opcion(f'Ver {ingreso.codigo_equipo}', f'ver {ingreso.codigo_equipo}'))
            if getattr(ingreso, 'salida', None) is None and not motivo_no_finalizable(ingreso):
                opciones.insert(0, opcion(f'✅ Finalizar {ingreso.codigo_equipo}', f'finalizar {ingreso.codigo_equipo}'))
            if getattr(ingreso, 'salida', None) is not None and ingreso.diferencia > 0:
                enlaces.append(enlace('Registrar pago', 'abono_crear', ingreso_pk=ingreso.pk))
        return respuesta(motivo, enlaces, opciones, ultimo_equipo=ingreso.pk if ingreso else None)
    estado['ultimo_equipo'] = ingreso.pk
    return _iniciar(request, estado, FlujoRetiro, ingreso)


def iniciar_estado(request, estado, ingreso, mensaje='', solo_reporte=False):
    motivo = motivo_sin_cambio_estado(ingreso)
    if motivo:
        return respuesta(motivo, [enlace('Abrir el equipo', 'ingreso_detalle', pk=ingreso.pk)] if ingreso else [],
                         ultimo_equipo=ingreso.pk if ingreso else None)
    t = tx.limpiar(mensaje)
    nuevo, subestado, reporte = '', '', None
    if solo_reporte:
        texto = _texto_despues_del_codigo(mensaje, ingreso.codigo_equipo, ('reporte', 'informe'))
        reporte = texto or None
    else:
        if re.search(r'\ben reparacion\b|\breparando\b|\ba reparacion\b', t):
            nuevo = 'en_reparacion'
        elif re.search(r'\bdiagnostico\b|\bingresado\b', t):
            nuevo = 'ingresado'
        if nuevo == 'en_reparacion' or not nuevo:
            if re.search(r'\brepuestos?\b', t):
                subestado, nuevo = 'espera_repuesto', 'en_reparacion'
            elif re.search(r'\b(?:espera(?:ndo)? (?:al |del |de )?cliente|respuesta del cliente)\b', t):
                subestado, nuevo = 'espera_cliente', 'en_reparacion'
    estado['ultimo_equipo'] = ingreso.pk
    return _iniciar(request, estado, FlujoEstado, ingreso, nuevo_estado=nuevo, subestado=subestado,
                    reporte=reporte, solo_reporte=solo_reporte)


def iniciar_valor(request, estado, ingreso, mensaje=''):
    motivo = motivo_sin_valor(ingreso)
    if motivo:
        return respuesta(motivo, ultimo_equipo=ingreso.pk if ingreso else None)
    sin_codigo = _sin_codigos(mensaje)
    valor = ''
    if re.search(r'\d', sin_codigo):
        valor = tx.dinero(sin_codigo) or ''
    estado['ultimo_equipo'] = ingreso.pk
    return _iniciar(request, estado, FlujoValor, ingreso, valor=valor)


def _sin_codigos(mensaje):
    return re.sub(r'(?<![A-Za-z0-9])[GgUuPp][\s#-]?\d{1,6}(?![0-9])', ' ', mensaje or '')


def _texto_despues_del_codigo(mensaje, codigo, palabras):
    """Texto libre que sigue a «reporte G1031: …»."""
    crudo = mensaje or ''
    coincidencia = re.search(r'(?<![A-Za-z0-9])' + codigo[0] + r'[\s#-]?' + codigo[1:] + r'(?![0-9])', crudo,
                             re.IGNORECASE)
    resto = crudo[coincidencia.end():] if coincidencia else crudo
    resto = resto.strip(' :,-—\n\t')
    if not coincidencia:
        for palabra in palabras:
            resto = re.sub(r'^\s*' + palabra + r'\w*\s*', '', resto, flags=re.IGNORECASE)
    return resto.strip(' :,-—\n\t')


# ─────────────────────────────────────────────────────────────────────
# Acta por correo (pide confirmación: envía un correo al cliente)
# ─────────────────────────────────────────────────────────────────────

def preparar_acta(request, estado, ingreso):
    salida = getattr(ingreso, 'salida', None)
    if salida is None:
        return respuesta(f'{ingreso.codigo_equipo} todavía no está finalizado, así que no tiene acta.',
                         opciones=[opcion(f'✅ Finalizar {ingreso.codigo_equipo}', f'finalizar {ingreso.codigo_equipo}')])
    correo = (ingreso.cliente.correo or '').strip()
    if not correo:
        return respuesta(f'El cliente de {ingreso.codigo_equipo} no tiene correo registrado.',
                         [enlace('Acta de finalización (PDF)', 'salida_pdf', pk=salida.pk, tipo='nueva')])
    estado['esperar'] = {'tipo': 'acta', 'salida': salida.pk}
    return respuesta(f'¿Envío el acta de finalización de {ingreso.codigo_equipo} a {correo}?',
                     opciones=[opcion('📧 Sí, enviar', 'sí'), opcion('No', 'no')], ultimo_equipo=ingreso.pk)


def enviar_acta(request, salida_pk):
    resultado = enviar(request, vistas.salida_enviar_correo_finalizacion, pk=salida_pk, datos={})
    try:
        datos = json.loads(resultado.respuesta.content.decode('utf-8'))
    except (ValueError, AttributeError):
        datos = {}
    texto = datos.get('mensaje') or 'No pude enviar el acta.'
    return respuesta(('📧 ' if datos.get('ok') else '⚠️ ') + texto,
                     [enlace('Acta de finalización (PDF)', 'salida_pdf', pk=salida_pk, tipo='nueva')])


# ─────────────────────────────────────────────────────────────────────
# Acciones con código de equipo
# ─────────────────────────────────────────────────────────────────────

def _con_codigo(request, estado, t, mensaje, codigo, permitir_flujos=True):
    ingreso = ingreso_por_codigo(codigo)
    if ingreso is None:
        return respuesta(f'No encontré el equipo {codigo}. Revisa el código (G = Guayaquil, U = Quito, P = ventas).',
                         [enlace('Buscar en la lista de equipos', 'ingreso_lista')])
    es_pregunta = bool(PREGUNTA.search(t) or '?' in mensaje or '¿' in mensaje)
    # Una pregunta («¿en qué estado está?», «¿cuál es el valor?») muestra la ficha;
    # solo las órdenes inician un cambio, y todo cambio pide confirmación.
    finalizar = VERBO_FINALIZAR.search(t) and not re.search(r'\bfinalizad[oa]s?\b', t)
    acta = VERBO_ACTA.search(t)
    retiro = VERBO_RETIRO.search(t) and (not es_pregunta or re.search(r'\bconfirm', t))
    valor = VERBO_VALOR.search(t) and not es_pregunta and not re.search(r'\bsaldo\b', t)
    reporte = VERBO_REPORTE.search(t) and not es_pregunta
    cambio = VERBO_ESTADO.search(t) and not es_pregunta
    if (finalizar or acta or retiro or valor or reporte or cambio) and not permitir_flujos:
        return respuesta(f'Para trabajar con {ingreso.codigo_equipo} primero termina o cancela el registro en curso.')
    if finalizar:
        return iniciar_finalizar(request, estado, ingreso, mensaje)
    if acta:
        return preparar_acta(request, estado, ingreso)
    if retiro:
        return iniciar_retiro(request, estado, ingreso)
    if valor:
        return iniciar_valor(request, estado, ingreso, mensaje)
    if reporte:
        return iniciar_estado(request, estado, ingreso, mensaje, solo_reporte=True)
    if cambio:
        return iniciar_estado(request, estado, ingreso, mensaje)
    if re.search(r'\bcliente\b', t) and not re.search(r'\bequipo\b', t):
        return consultas.ficha_cliente(ingreso.cliente)
    return consultas.ficha_equipo(request, ingreso)


def _ultimo_equipo(estado):
    pk = estado.get('ultimo_equipo')
    return IngresoEquipo.objects.select_related('cliente').filter(pk=pk).first() if pk else None


def _pedir_equipo(estado, tipo, pregunta, sugeridos=()):
    """Pregunta qué equipo usar y recuerda para qué."""
    opciones = [opcion(i.codigo_equipo, i.codigo_equipo) for i in sugeridos if i is not None][:6]
    estado['esperar'] = {'tipo': tipo}
    return respuesta(pregunta, opciones=opciones + [opcion('Cancelar', 'cancelar')])


def _sugeridos_finalizar(request, estado):
    ultimo = _ultimo_equipo(estado)
    qs = (IngresoEquipo.objects.select_related('cliente')
          .filter(estado__in=('ingresado', 'en_reparacion', 'garantia', 'cortesia'), salida__isnull=True,
                  sede__in=('guayaquil', 'quito')))
    propios = list(qs.filter(tecnico_encargado=request.user).order_by('fecha_ingreso')[:5])
    lista = ([ultimo] if ultimo and not getattr(ultimo, 'salida', None) else []) + propios
    vistos, unicos = set(), []
    for ingreso in lista:
        if ingreso.pk not in vistos:
            vistos.add(ingreso.pk)
            unicos.append(ingreso)
    return unicos


def _sugeridos_retiro(estado):
    ultimo = _ultimo_equipo(estado)
    return [ultimo] if ultimo and getattr(ultimo, 'salida', None) and not ultimo.salida.cliente_ya_retiro else []


ACCION_SALIDA = re.compile(r'\b(?:confirmar? (?:la )?salida|confirma (?:la )?salida|salida fisica|ya se lo llevo|'
                           r'ya lo retiro|ya retiro)\b')
ACCION_ESTADO = re.compile(r'^(?:cambiar|cambia|actualizar|actualiza) (?:el )?estado\b')
ACCION_REPORTE = re.compile(r'^(?:escribir |agregar |actualizar |poner )?(?:el )?reporte\b')
ACCION_VALOR = re.compile(r'^(?:poner |registrar |cambiar |actualizar )?(?:el )?valor acordado\b')
NO_ES_EQUIPO = re.compile(r'\b(?:abono|pago|venta|producto|gasto|egreso)\b')


def _es_accion(t):
    return bool(
        (VERBO_FINALIZAR.search(t) and not re.search(r'\bfinalizad[oa]s\b', t)) or VERBO_ACTA.search(t)
        or ACCION_SALIDA.search(t) or ACCION_ESTADO.search(t) or ACCION_REPORTE.search(t) or ACCION_VALOR.search(t)
        or (VERBO_REGISTRAR.search(t) and not NO_ES_EQUIPO.search(t))
    )


def _accion_sin_codigo(request, estado, t, mensaje):
    """Órdenes de registro/acción que todavía no traen el código del equipo."""
    ultimo = _ultimo_equipo(estado) if PRONOMBRE.search(t) else None
    if VERBO_FINALIZAR.search(t) and not re.search(r'\bfinalizad[oa]s\b', t):
        if ultimo:
            return iniciar_finalizar(request, estado, ultimo, mensaje)
        return _pedir_equipo(estado, 'finalizar', '¿Qué equipo finalizo? Escribe su código (por ejemplo G1031).',
                             _sugeridos_finalizar(request, estado))
    if VERBO_ACTA.search(t):
        if ultimo:
            return preparar_acta(request, estado, ultimo)
        return _pedir_equipo(estado, 'acta_codigo', '¿De qué equipo envío el acta? Escribe su código.',
                             _sugeridos_retiro(estado))
    if ACCION_SALIDA.search(t):
        if ultimo:
            return iniciar_retiro(request, estado, ultimo)
        return _pedir_equipo(estado, 'retiro', '¿Qué equipo salió de la oficina? Escribe su código.',
                             _sugeridos_retiro(estado))
    if ACCION_ESTADO.search(t):
        if ultimo:
            return iniciar_estado(request, estado, ultimo, mensaje)
        return _pedir_equipo(estado, 'estado', '¿A qué equipo le cambio el estado? Escribe su código.',
                             _sugeridos_finalizar(request, estado))
    if ACCION_REPORTE.search(t):
        if ultimo:
            return iniciar_estado(request, estado, ultimo, mensaje, solo_reporte=True)
        return _pedir_equipo(estado, 'reporte', '¿De qué equipo es el reporte? Escribe su código.',
                             _sugeridos_finalizar(request, estado))
    if ACCION_VALOR.search(t):
        if ultimo:
            return iniciar_valor(request, estado, ultimo, mensaje)
        return _pedir_equipo(estado, 'valor', '¿A qué equipo le pongo el valor acordado? Escribe su código.')
    if VERBO_REGISTRAR.search(t) and not NO_ES_EQUIPO.search(t):
        return iniciar_registro(request, estado, mensaje)
    return None


# ─────────────────────────────────────────────────────────────────────
# Mensajes fuera de un registro
# ─────────────────────────────────────────────────────────────────────

def _libre(request, estado, mensaje, permitir_flujos=True):
    """Responde consultas y órdenes. Con permitir_flujos=False no inicia registros."""
    t = tx.limpiar(mensaje)
    if not t:
        return conocimiento.capacidades(request)

    codigos = tx.codigos_equipo(mensaje)
    if codigos:
        resultado = _con_codigo(request, estado, t, mensaje, codigos[0], permitir_flujos)
        if len(codigos) > 1:
            resultado['reply'] = (f'(Voy con {codigos[0]}; luego escríbeme los demás uno por uno.)\n'
                                  + resultado['reply'])
        return resultado

    explicativa = EXPLICATIVA.search(t) is not None
    if explicativa:
        tema = conocimiento.tema(request, mensaje)
        if tema is not None:
            return tema

    for patron, funcion in LISTAS:
        if patron.search(t):
            return funcion(request, mensaje)

    cliente = re.match(r'^(?:ver |buscar |busca |busco |consultar |datos del |datos de |info(?:rmacion)? del? )?'
                       r'(?:el |al |la |un |una )?clientes?\b\s*(.*)$', t)
    if cliente:
        termino = mensaje.strip()
        termino = re.sub(r'^.*?\bclientes?\b\s*', '', termino, count=1, flags=re.IGNORECASE)
        if not termino.strip():
            estado['esperar'] = {'tipo': 'cliente'}
        return consultas.buscar_cliente(termino)

    buscar = re.match(r'^(?:buscar|busca|busco|encuentra|encontrar|localiza|localizar)\b\s*(?:el |la |un |una )?'
                      r'(?:equipos? )?(.*)$', t)
    if buscar:
        termino = re.sub(r'^\s*(?:buscar|busca|busco|encuentra|encontrar|localiza|localizar)\b\s*'
                         r'(?:el |la |un |una )?(?:equipos? )?', '', mensaje.strip(), count=1, flags=re.IGNORECASE)
        if not termino.strip():
            estado['esperar'] = {'tipo': 'buscar'}
        return consultas.buscar_equipos(request, termino)

    if permitir_flujos:
        accion = _accion_sin_codigo(request, estado, t, mensaje)
        if accion is not None:
            return accion
    elif _es_accion(t):
        return respuesta('Primero termina o cancela el registro en curso; después lo hacemos.')

    if re.match(r'^(?:abrir|abre|ir a|ve a|vamos a|llevame a|mostrar|muestrame|donde (?:esta|estan|veo|encuentro|queda))\b', t):
        seccion = conocimiento.abrir_seccion(request.user, mensaje)
        if seccion is not None:
            return seccion

    tema = conocimiento.tema(request, mensaje)
    if tema is not None:
        return tema

    seccion = conocimiento.abrir_seccion(request.user, mensaje)
    if seccion is not None and len(t.split()) <= 4:
        return seccion

    cedula = tx.cedula_en(mensaje)
    if cedula:
        cliente = Cliente.objects.filter(cedula=cedula).first()
        if cliente:
            return consultas.ficha_cliente(cliente)
        return respuesta(f'No hay un cliente con la cédula {cedula}.',
                         opciones=[opcion('📥 Registrar equipo con esa cédula', f'registrar equipo {cedula}')])

    # Un nombre suelto: se busca como cliente y luego como equipo.
    if re.fullmatch(r'[a-z0-9ñ .-]{3,40}', t) and len(t.split()) <= 4 and not PREGUNTA.search(t):
        encontrados = consultas.buscar_cliente(mensaje)
        if not encontrados['reply'].startswith('No encontré'):
            return encontrados
        equipos = consultas.buscar_equipos(request, mensaje)
        if not equipos['reply'].startswith('No encontré'):
            return equipos

    return respuesta(
        f'No entendí «{mensaje.strip()[:80]}». Puedo registrar o finalizar equipos, confirmar salidas y mostrarte '
        'equipos, clientes, listas y alertas. Escribe «ayuda» para ver ejemplos.',
        opciones=[
            opcion('📥 Registrar equipo', 'registrar equipo'),
            opcion('✅ Finalizar equipo', 'finalizar equipo'),
            opcion('📦 Finalizados en oficina', 'equipos finalizados'),
            opcion('👤 Buscar cliente', 'buscar cliente'),
            opcion('❓ Ayuda', 'ayuda'),
        ],
    )


def _en_espera(request, estado, mensaje):
    """Respuesta a un paso corto pendiente («¿qué equipo finalizo?»). None si no aplica."""
    espera = estado.get('esperar')
    if not isinstance(espera, dict):
        return None
    tipo = espera.get('tipo')
    t = tx.limpiar(mensaje)

    if tipo == 'acta':
        estado.pop('esperar', None)
        if tx.es_si(mensaje) or t in ('enviar', 'si enviar', 'enviala', 'envialo'):
            return enviar_acta(request, espera.get('salida'))
        if tx.es_no(mensaje):
            return respuesta('Listo, no envié el acta.')
        return None

    if tipo in ('cliente', 'buscar'):
        if ORDEN.search(t) or tx.codigos_equipo(mensaje):
            estado.pop('esperar', None)
            return None
        estado.pop('esperar', None)
        if tipo == 'cliente':
            return consultas.buscar_cliente(mensaje)
        return consultas.buscar_equipos(request, mensaje)

    if tipo in ('finalizar', 'retiro', 'estado', 'reporte', 'valor', 'acta_codigo'):
        codigos = tx.codigos_equipo(mensaje)
        if not codigos:
            if ORDEN.search(t) or PREGUNTA.search(t):
                estado.pop('esperar', None)
                return None
            return respuesta('No reconocí el código. Escribe el código del equipo, por ejemplo G1031, o «cancelar».',
                             opciones=[opcion('Cancelar', 'cancelar')])
        estado.pop('esperar', None)
        ingreso = ingreso_por_codigo(codigos[0])
        if ingreso is None:
            estado['esperar'] = espera
            return respuesta(f'No encontré el equipo {codigos[0]}. Revisa el código o escribe «cancelar».')
        if tipo == 'finalizar':
            return iniciar_finalizar(request, estado, ingreso, mensaje)
        if tipo == 'retiro':
            return iniciar_retiro(request, estado, ingreso)
        if tipo == 'estado':
            return iniciar_estado(request, estado, ingreso, mensaje)
        if tipo == 'reporte':
            return iniciar_estado(request, estado, ingreso, mensaje, solo_reporte=True)
        if tipo == 'valor':
            return iniciar_valor(request, estado, ingreso, mensaje)
        return preparar_acta(request, estado, ingreso)
    estado.pop('esperar', None)
    return None


# ─────────────────────────────────────────────────────────────────────
# Registro en curso
# ─────────────────────────────────────────────────────────────────────

def _recordatorio(flujo, resultado):
    resultado = dict(resultado)
    resultado['reply'] = (resultado.get('reply', '') + f'\n\n📝 Sigues con «{flujo.titulo}». '
                          'Cuando quieras, escribe «continuar» para retomarlo o «cancelar» para salir.')
    resultado['options'] = list(resultado.get('options') or []) + [
        opcion('↩️ Continuar ' + flujo.titulo.lower(), 'continuar'), opcion('Cancelar registro', 'cancelar')]
    return resultado


def _es_orden(t, mensaje):
    return bool(ORDEN.search(t) or '?' in mensaje or '¿' in mensaje)


def _en_flujo(request, estado, flujo, mensaje, firma):
    t = tx.limpiar(mensaje)
    if firma is not None:
        return avanzar(flujo, '', firma=firma)

    datos = flujo.estado
    pregunta = flujo.pregunta_por_clave(datos.get('esperando')) if datos.get('esperando') else None

    if datos.get('confirmando'):
        decision = tx.es_si(mensaje) or tx.es_no(mensaje) or t.startswith(('corregir', 'cambiar', 'editar'))
        if not decision and ':' not in mensaje and _es_orden(t, mensaje):
            lateral = _libre(request, estado, mensaje, permitir_flujos=False)
            if lateral is not None:
                return _recordatorio(flujo, lateral)
        return avanzar(flujo, mensaje)

    if pregunta is None or pregunta.libre:
        return avanzar(flujo, mensaje)

    if ':' not in mensaje and _es_orden(t, mensaje):
        if pregunta.tipo == 'texto':
            lateral = _libre(request, estado, mensaje, permitir_flujos=False)
            if lateral is not None:
                return _recordatorio(flujo, lateral)
        else:
            _valor, error = interpretar(flujo, pregunta, mensaje)
            if error:
                lateral = _libre(request, estado, mensaje, permitir_flujos=False)
                if lateral is not None:
                    return _recordatorio(flujo, lateral)
    return avanzar(flujo, mensaje)


# ─────────────────────────────────────────────────────────────────────
# Punto de entrada
# ─────────────────────────────────────────────────────────────────────

def responder(request, mensaje, firma=None):
    estado = _estado(request)
    mensaje = (mensaje or '').strip()
    t = tx.limpiar(mensaje)
    flujo = _flujo(request, estado)

    if flujo is not None:
        pregunta_libre = False
        if flujo.estado.get('esperando'):
            pregunta = flujo.pregunta_por_clave(flujo.estado['esperando'])
            pregunta_libre = pregunta is not None and pregunta.libre
        if firma is None and (CANCELAR.match(t) or (CANCELAR_SUAVE.match(t) and not pregunta_libre)):
            titulo = flujo.titulo
            estado.pop('flujo', None)
            return _finalizar_respuesta(request, estado, respuesta(
                f'Listo, cancelé «{titulo}». No se guardó nada.',
                opciones=[opcion('📥 Registrar equipo', 'registrar equipo'), opcion('❓ Ayuda', 'ayuda')]))
        if firma is None and ATRAS.match(t):
            clave = deshacer(flujo)
            if clave is None:
                return _finalizar_respuesta(request, estado, pendiente_actual(flujo))
            return _finalizar_respuesta(request, estado, siguiente(flujo, ['Volvamos a ese dato:']))
        if firma is None and CONTINUAR.match(t):
            return _finalizar_respuesta(request, estado, pendiente_actual(flujo))
        return _finalizar_respuesta(request, estado, _en_flujo(request, estado, flujo, mensaje, firma))

    if firma is not None:
        return _finalizar_respuesta(request, estado, respuesta(
            'No hay ninguna firma pendiente. Si quieres registrar un equipo, escribe «registrar equipo».'))

    if CANCELAR.match(t) or CANCELAR_SUAVE.match(t):
        estado.pop('esperar', None)
        return _finalizar_respuesta(request, estado, respuesta('Listo, no hay nada pendiente. ¿En qué más te ayudo?'))
    if ATRAS.match(t) or CONTINUAR.match(t):
        return _finalizar_respuesta(request, estado, respuesta('No hay ningún registro en curso. ¿Qué necesitas?',
                                                               opciones=[opcion('❓ Ver lo que puedo hacer', 'ayuda')]))
    if AYUDA.match(t) or (SALUDO.match(t) and len(t.split()) <= 4):
        estado.pop('esperar', None)
        return _finalizar_respuesta(request, estado, conocimiento.capacidades(request))
    if GRACIAS.match(t) and len(t.split()) <= 4:
        return _finalizar_respuesta(request, estado, respuesta('¡Con gusto! Aquí estoy si necesitas algo más. 🤖'))
    if SALUDO.match(t):
        # «Hola, quiero registrar un equipo»: se atiende lo que sigue al saludo.
        mensaje = SALUDO_INICIAL.sub('', mensaje, count=1).strip() or mensaje

    resultado = _en_espera(request, estado, mensaje)
    if resultado is None:
        resultado = _libre(request, estado, mensaje)
    return _finalizar_respuesta(request, estado, resultado)


def estado_actual(request):
    """Lo que la interfaz necesita al abrir el chat."""
    estado = _estado(request)
    flujo = _flujo(request, estado)
    datos = {'pending': flujo is not None, 'flow': flujo.titulo if flujo is not None else ''}
    if flujo is not None:
        datos['resume'] = _finalizar_respuesta(request, estado, pendiente_actual(flujo))
    return datos
