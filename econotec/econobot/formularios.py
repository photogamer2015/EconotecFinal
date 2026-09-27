"""Datos de formulario idénticos a los que envía la página web."""
from datetime import date, datetime
from decimal import Decimal

from django.db.models import Model

from ..forms import _queryset_asesores, _queryset_tecnicos
from ..models import IngresoEquipo
from . import texto as tx
from .flujo import Pregunta


def a_texto(valor):
    """Valor de un campo tal como viaja en un POST del navegador."""
    if valor is None:
        return ''
    if isinstance(valor, bool):
        return 'true' if valor else 'false'
    if isinstance(valor, datetime):
        return valor.date().isoformat()
    if isinstance(valor, date):
        return valor.isoformat()
    if isinstance(valor, Decimal):
        return f'{valor:.2f}'
    if isinstance(valor, Model):
        return str(valor.pk)
    if isinstance(valor, (list, tuple)):
        return [a_texto(v) for v in valor]
    return str(valor)


def valores_de_formulario(formulario):
    """{nombre_html: valor} con lo que la página mostraría precargado."""
    datos = {}
    for nombre in formulario.fields:
        campo = formulario[nombre]
        datos[campo.html_name] = a_texto(campo.value())
    return datos


def opciones_tecnicos():
    return [(str(u.pk), tx.nombre_usuario(u)) for u in _queryset_tecnicos()]


def opciones_asesores():
    return [(tx.nombre_usuario(u), tx.nombre_usuario(u)) for u in _queryset_asesores()]


def usuario_es_tecnico_de_lista(user):
    return any(str(user.pk) == valor for valor, _ in opciones_tecnicos())


def usuario_es_asesor_de_lista(user):
    nombre = tx.nombre_usuario(user)
    return any(nombre == valor for valor, _ in opciones_asesores())


def etiqueta_de(opciones, valor, defecto='—'):
    for clave, etiqueta in opciones:
        if str(clave) == str(valor):
            return etiqueta
    return defecto if valor in (None, '') else str(valor)


# ─────────────────────────────────────────────────────────────────────
# Métodos de pago (anticipo, diagnóstico, compra, cobros y bodegaje)
# ─────────────────────────────────────────────────────────────────────

METODOS = [
    ('efectivo', 'Efectivo'),
    ('transferencia', 'Transferencia bancaria'),
    ('tarjeta', 'Tarjeta / App (Payphone, Deuna)'),
    ('mixto', 'Pago mixto (2 métodos)'),
]
METODOS_SIMPLES = METODOS[:3]
BANCOS = list(IngresoEquipo.BANCOS)
TARJETAS = list(IngresoEquipo.TARJETAS_APPS)

# Nombre real de cada parte del pago en el formulario del sistema.
GRUPOS_PAGO = {
    'anticipo': {
        'metodo': 'anticipo_metodo', 'banco': 'anticipo_banco', 'banco_otro': 'anticipo_banco_otro',
        'tarjeta_app': 'anticipo_tarjeta_app', 'comprobante_url': 'anticipo_comprobante_url',
        'monto_1': 'anticipo_monto_1', 'metodo_1': 'anticipo_metodo_1', 'banco_1': 'anticipo_banco_1',
        'monto_2': 'anticipo_monto_2', 'metodo_2': 'anticipo_metodo_2', 'banco_2': 'anticipo_banco_2',
    },
    'diagnostico': {
        'metodo': 'diagnostico_metodo', 'banco': 'diagnostico_banco', 'banco_otro': 'diagnostico_banco_otro',
        'tarjeta_app': 'diagnostico_tarjeta_app', 'comprobante_url': 'diagnostico_comprobante_url',
        'monto_1': 'diagnostico_monto_1', 'metodo_1': 'diagnostico_metodo_1', 'banco_1': 'diagnostico_banco_1',
        'monto_2': 'diagnostico_monto_2', 'metodo_2': 'diagnostico_metodo_2', 'banco_2': 'diagnostico_banco_2',
    },
    'compra': {
        'metodo': 'compra_metodo_pago', 'banco': 'compra_banco', 'banco_otro': 'compra_banco_otro',
        'tarjeta_app': 'compra_tarjeta_app', 'comprobante_url': 'compra_comprobante_url',
        'monto_1': 'compra_monto_1', 'metodo_1': 'compra_metodo_1', 'banco_1': 'compra_banco_1',
        'banco_otro_1': 'compra_banco_otro_1', 'tarjeta_app_1': 'compra_tarjeta_app_1',
        'monto_2': 'compra_monto_2', 'metodo_2': 'compra_metodo_2', 'banco_2': 'compra_banco_2',
        'banco_otro_2': 'compra_banco_otro_2', 'tarjeta_app_2': 'compra_tarjeta_app_2',
    },
    'final': {
        'metodo': 'metodo_pago_final', 'banco': 'banco', 'banco_otro': 'banco_otro',
        'tarjeta_app': 'tarjeta_app', 'comprobante_url': 'comprobante_url',
        'monto_1': 'monto_1', 'metodo_1': 'metodo_1', 'banco_1': 'banco_1',
        'monto_2': 'monto_2', 'metodo_2': 'metodo_2', 'banco_2': 'banco_2',
    },
    'bodegaje': {
        'metodo': 'pago_bod_metodo', 'banco': 'pago_bod_banco', 'banco_otro': 'pago_bod_banco_otro',
        'tarjeta_app': 'pago_bod_tarjeta_app', 'comprobante_url': 'pago_bod_comprobante_url',
        'monto_1': 'pago_bod_monto_1', 'metodo_1': 'pago_bod_metodo_1', 'banco_1': 'pago_bod_banco_1',
        'banco_otro_1': 'pago_bod_banco_otro_1', 'tarjeta_app_1': 'pago_bod_tarjeta_app_1',
        'comprobante_url_1': 'pago_bod_comprobante_url_1',
        'monto_2': 'pago_bod_monto_2', 'metodo_2': 'pago_bod_metodo_2', 'banco_2': 'pago_bod_banco_2',
        'banco_otro_2': 'pago_bod_banco_otro_2', 'tarjeta_app_2': 'pago_bod_tarjeta_app_2',
        'comprobante_url_2': 'pago_bod_comprobante_url_2',
    },
}


def clave_pago(grupo, parte):
    return f'{grupo}__{parte}'


def preguntas_pago(grupo, datos, concepto, total):
    """Preguntas activas del método de pago de un grupo, en orden."""
    campos = GRUPOS_PAGO[grupo]
    k = lambda parte: clave_pago(grupo, parte)  # noqa: E731
    total_txt = tx.dinero_legible(total)
    preguntas = [Pregunta(
        k('metodo'), f'Método de pago del {concepto}',
        f'¿Cómo se pagó el {concepto} de {total_txt}?',
        tipo='opcion', opciones=METODOS,
    )]
    metodo = datos.get(k('metodo'))
    if metodo == 'transferencia':
        preguntas += _preguntas_banco(grupo, '', datos, concepto)
        preguntas.append(Pregunta(
            k('comprobante_url'), 'Comprobante', 'Pega el enlace del comprobante (Drive, WhatsApp…).',
            tipo='url', opcional=True,
        ))
    elif metodo == 'tarjeta':
        preguntas.append(Pregunta(
            k('tarjeta_app'), 'Tarjeta / App', '¿Con qué tarjeta o aplicación se pagó?',
            tipo='opcion', opciones=TARJETAS,
        ))
    elif metodo == 'mixto':
        for numero in ('1', '2'):
            if numero == '1':
                preguntas.append(Pregunta(
                    k('monto_1'), f'Monto 1 del {concepto}',
                    f'Pago mixto: ¿cuánto se pagó con el primer método? (el total es {total_txt})',
                    tipo='dinero',
                ))
            preguntas.append(Pregunta(
                k('metodo_' + numero), f'Método {numero}',
                f'¿Con qué método fue la parte {numero}' + (
                    f' ({tx.dinero_legible(datos.get(k("monto_2")))})?' if numero == '2' and datos.get(k('monto_2')) else '?'
                ),
                tipo='opcion', opciones=METODOS_SIMPLES,
            ))
            metodo_parte = datos.get(k('metodo_' + numero))
            if metodo_parte == 'transferencia':
                preguntas += _preguntas_banco(grupo, '_' + numero, datos, f'{concepto} (parte {numero})')
                if 'comprobante_url_' + numero in campos:
                    preguntas.append(Pregunta(
                        k('comprobante_url_' + numero), f'Comprobante {numero}',
                        f'Enlace del comprobante de la parte {numero}.', tipo='url', opcional=True,
                    ))
            elif metodo_parte == 'tarjeta' and 'tarjeta_app_' + numero in campos:
                preguntas.append(Pregunta(
                    k('tarjeta_app_' + numero), f'Tarjeta / App {numero}',
                    f'¿Con qué tarjeta o aplicación fue la parte {numero}?',
                    tipo='opcion', opciones=TARJETAS,
                ))
    return preguntas


def _preguntas_banco(grupo, sufijo, datos, concepto):
    campos = GRUPOS_PAGO[grupo]
    k = lambda parte: clave_pago(grupo, parte)  # noqa: E731
    preguntas = [Pregunta(
        k('banco' + sufijo), 'Banco' + (f' {sufijo[1:]}' if sufijo else ''),
        f'¿De qué banco fue la transferencia del {concepto}?', tipo='opcion', opciones=BANCOS,
    )]
    if datos.get(k('banco' + sufijo)) == 'otro' and 'banco_otro' + sufijo in campos:
        preguntas.append(Pregunta(
            k('banco_otro' + sufijo), 'Nombre del banco', 'Escribe el nombre del banco.',
        ))
    return preguntas


def completar_monto_2(grupo, datos, total):
    """En pago mixto el segundo monto es lo que falta para el total."""
    monto_1 = datos.get(clave_pago(grupo, 'monto_1'))
    if datos.get(clave_pago(grupo, 'metodo')) != 'mixto' or not monto_1:
        return
    try:
        restante = Decimal(str(total)) - Decimal(monto_1)
    except Exception:
        return
    if restante > 0:
        datos[clave_pago(grupo, 'monto_2')] = f'{restante:.2f}'
    else:
        datos.pop(clave_pago(grupo, 'monto_2'), None)


def post_pago(grupo, datos, prefijo_html=''):
    """Campos del método de pago con los nombres del formulario real."""
    campos = GRUPOS_PAGO[grupo]
    resultado = {}
    metodo = datos.get(clave_pago(grupo, 'metodo'), '')
    activos = {'metodo'}
    if metodo == 'transferencia':
        activos |= {'banco', 'banco_otro', 'comprobante_url'}
    elif metodo == 'tarjeta':
        activos |= {'tarjeta_app'}
    elif metodo == 'mixto':
        activos |= {'monto_1', 'metodo_1', 'banco_1', 'banco_otro_1', 'tarjeta_app_1', 'comprobante_url_1',
                    'monto_2', 'metodo_2', 'banco_2', 'banco_otro_2', 'tarjeta_app_2', 'comprobante_url_2'}
    for parte, nombre in campos.items():
        valor = datos.get(clave_pago(grupo, parte), '') if parte in activos else ''
        resultado[prefijo_html + nombre] = valor or ''
    return resultado


def resumen_pago(grupo, datos):
    k = lambda parte: clave_pago(grupo, parte)  # noqa: E731
    metodo = datos.get(k('metodo'))
    if not metodo:
        return ''
    texto = etiqueta_de(METODOS, metodo)
    if metodo == 'transferencia':
        banco = datos.get(k('banco'))
        nombre_banco = datos.get(k('banco_otro')) if banco == 'otro' else etiqueta_de(BANCOS, banco, '')
        return f'{texto} ({nombre_banco})' if nombre_banco else texto
    if metodo == 'tarjeta':
        return f'{texto} ({etiqueta_de(TARJETAS, datos.get(k("tarjeta_app")), "")})'
    if metodo == 'mixto':
        partes = []
        for numero in ('1', '2'):
            parte = etiqueta_de(METODOS_SIMPLES, datos.get(k('metodo_' + numero)), '?')
            partes.append(f'{tx.dinero_legible(datos.get(k("monto_" + numero)))} {parte}')
        return 'Mixto: ' + ' + '.join(partes)
    return texto


def errores_pago(grupo, errores_formulario, prefijo_html=''):
    """Traduce errores del formulario a las preguntas del grupo de pago."""
    traducidos = {}
    for parte, nombre in GRUPOS_PAGO[grupo].items():
        mensajes = errores_formulario.get(nombre) or errores_formulario.get(prefijo_html + nombre)
        if mensajes:
            # El segundo monto se calcula solo: su error se corrige en el primero.
            destino = 'monto_1' if parte == 'monto_2' else parte
            traducidos.setdefault(clave_pago(grupo, destino), []).extend(list(mensajes))
    return traducidos
