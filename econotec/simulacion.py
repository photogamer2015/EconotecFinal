"""
Simulación gamificada del recorrido de un equipo dentro de Econotec.

Arma los datos que consume `static/simulacion/simulacion.js` para pintar el
mapa isométrico del detalle del equipo: estaciones del flujo, personajes
(cliente, asesora y técnicos) con su género inferido por el nombre, dinero
y logros desbloqueados.
"""
import unicodedata
from decimal import Decimal

from django.utils import timezone

from .templatetags.econotec_extras import dinero_signo


# ─────────────────────────────────────────────────────────
# Género por nombre
# ─────────────────────────────────────────────────────────

# Nombres femeninos frecuentes que NO terminan en "a" (los terminados en "a"
# se resuelven con la regla general).
NOMBRES_FEMENINOS = frozenset('''
    abigail abril alice alison allison amparo anahi angie annie araceli aracely
    arlene ashley astrid beatriz belen betty britany brittany carmen carol
    caridad catherine chloe cielo cindy concepcion connie consuelo daisy darlene
    dayanne deisy dolores doris dulce edith elizabeth emely emily emilie ester
    esther evelyn flor gisselle giselle gissel gladys grace guadalupe heidi heidy
    ines ingrid irene iris isabel ivonne yvonne jacqueline jaqueline janeth jannet
    jazmin jennifer jenny jocelyn joselyn josselyn jhoselyn judith juliet julieth
    karen katherine katherin kathy kelly kimberly kimberley lady leidy leonor
    lilibeth lisbeth lisseth liseth lizbeth lizeth liz lourdes lucy luz ma mabel
    madeleine maite mayte marjorie maribel marisol marlene mary mayerli mely
    melany melanie mercedes mercy michelle mishell mishel milagros miriam mirian
    myriam nancy nathaly nataly nathalie nayeli nelly nicole nicol nikol nieves
    noemi paulette peggy pilar piedad rachel raquel remedios rocio rosario
    rosemary ruby rut ruth salome sandy sharon shirley sindy socorro sol soledad
    stefany stephanie estefany estefani tiffany trinidad valery valerie wendy
    yamileth yamilet yasmin yuleisy zoe
'''.split())

# Nombres masculinos que la regla general confundiría (terminan en "a" o en
# una terminación típicamente femenina).
NOMBRES_MASCULINOS = frozenset('''
    joshua jhoshua josua luca lucca nicola mattia ezra jona ilya nikita bautista
    misha kenneth seth gareth
'''.split())

TERMINACIONES_FEMENINAS = ('lyn', 'line', 'elle', 'ette', 'beth', 'eth', 'ely', 'aly', 'erly')

TITULOS_FEMENINOS = frozenset('sra srta senora senorita lcda licda dra doctora dona ingeniera abga'.split())
TITULOS_MASCULINOS = frozenset('sr senor lcdo licdo dr doctor don ingeniero'.split())
TITULOS_NEUTROS = frozenset('ing ab abg arq lic mgs msc phd prof tec'.split())


def _normalizar(texto):
    """Minúsculas, sin tildes y solo letras: «María» → «maria»."""
    sin_tildes = unicodedata.normalize('NFKD', texto or '')
    return ''.join(c for c in sin_tildes if c.isalpha() and not unicodedata.combining(c)).lower()


def _tokens_nombre(nombre):
    """Pares (texto original, texto normalizado) sin títulos de cortesía."""
    tokens = []
    for crudo in (nombre or '').split():
        normal = _normalizar(crudo)
        if normal:
            tokens.append((crudo.strip('.,;:'), normal))
    return tokens


def _genero_por_nombre(token):
    if token in NOMBRES_MASCULINOS:
        return 'm'
    if token in NOMBRES_FEMENINOS:
        return 'f'
    if token.endswith('a') or token.endswith(TERMINACIONES_FEMENINAS):
        return 'f'
    return 'm'


def inferir_genero(nombre, por_defecto='m'):
    """
    Devuelve 'f' o 'm' según el primer nombre.

    Un título (Sra., Lcdo., Dra.) manda sobre el nombre; si no hay nombre
    reconocible se usa `por_defecto`.
    """
    for _, token in _tokens_nombre(nombre):
        if token in TITULOS_FEMENINOS:
            return 'f'
        if token in TITULOS_MASCULINOS:
            return 'm'
        if token in TITULOS_NEUTROS:
            continue
        return _genero_por_nombre(token)
    return por_defecto


def primer_nombre(nombre):
    """Primer nombre legible, sin títulos: «Sra. MARÍA José» → «María»."""
    for crudo, token in _tokens_nombre(nombre):
        if token in TITULOS_FEMENINOS or token in TITULOS_MASCULINOS or token in TITULOS_NEUTROS:
            continue
        if crudo.isupper() or crudo.islower():
            return crudo.capitalize()
        return crudo
    return ''


def _nombre_usuario(usuario):
    if not usuario:
        return ''
    return (f'{usuario.first_name} {usuario.last_name}'.strip()) or usuario.username


def _personaje(nombre, roles, genero_por_defecto='m', respaldo=''):
    """Personaje del mapa; `roles` es (masculino, femenino)."""
    completo = (nombre or '').strip()
    genero = inferir_genero(completo, por_defecto=genero_por_defecto)
    return {
        'nombre': primer_nombre(completo) or respaldo,
        'nombre_completo': completo or respaldo,
        'genero': genero,
        'rol': roles[1] if genero == 'f' else roles[0],
    }


# ─────────────────────────────────────────────────────────
# Recorrido del equipo
# ─────────────────────────────────────────────────────────

ETAPAS = (
    ('recepcion', 'Recepción', '📥'),
    ('diagnostico', 'Diagnóstico', '🔍'),
    ('taller', 'Taller', '🛠'),
    ('listo', 'Listo para retiro', '📦'),
    ('caja', 'Caja', '💰'),
    ('salida', 'Salida', '🚪'),
)

XP_POR_ETAPA = 20

RESULTADOS_SALIDA = {
    'no_reparable': ('No se pudo reparar', 'malo'),
    'cliente_no_acepta': ('Cliente no quiso reparar', 'aviso'),
    'revision': ('Revisión', 'aviso'),
    'chatarrerizacion': ('Chatarrerización', 'malo'),
    'garantia': ('Garantía finalizada', 'bueno'),
    'garantia_fallos_adicionales': ('Garantía + fallos adicionales', 'bueno'),
    'cortesia': ('Cortesía finalizada', 'bueno'),
    'pendiente_retiro': ('Reparado', 'bueno'),
    'retirado': ('Reparado', 'bueno'),
}


def _salida_de(ingreso):
    try:
        return ingreso.salida
    except AttributeError:
        return None


def _equipo_retirado(ingreso, salida):
    """¿El equipo ya salió de la oficina? Sin hoja de salida manda el estado manual."""
    if salida is not None:
        return ingreso.retirado_por_cliente
    return ingreso.estado == 'entregado' and ingreso.subestado_entregado != 'pendiente_retiro'


def _etapa_actual(ingreso, salida, retirado):
    """Índice de la estación donde está físicamente el equipo."""
    if retirado:
        return len(ETAPAS) - 1
    if salida is not None or ingreso.estado == 'entregado':
        return 3
    if ingreso.estado == 'ingresado':
        return 1
    return 2


def _texto_dias(dias):
    if dias <= 0:
        return 'Hoy'
    if dias == 1:
        return '1 día'
    return f'{dias} días'


def _recortar(texto, limite=140):
    texto = ' '.join((texto or '').split())
    if len(texto) <= limite:
        return texto
    return texto[:limite - 1].rstrip() + '…'


def _fecha(valor):
    return valor.strftime('%d/%m/%Y') if valor else ''


def construir_simulacion(ingreso, hoy=None):
    """Datos serializables (json_script) para la simulación del equipo."""
    hoy = hoy or timezone.localdate()
    salida = _salida_de(ingreso)
    retirado = _equipo_retirado(ingreso, salida)
    actual = _etapa_actual(ingreso, salida, retirado)

    fin = salida.fecha_retiro_real if salida is not None and salida.fecha_retiro_real else hoy
    dias = max(0, (fin - ingreso.fecha_ingreso).days) if ingreso.fecha_ingreso else 0

    # ── Personajes ──────────────────────────────────────
    nombre_asesora = ingreso.asesor_comercial or _nombre_usuario(ingreso.registrado_por)
    tecnico = _personaje(ingreso.tecnico_encargado_nombre, ('Técnico', 'Técnica'), respaldo='Técnico')
    personajes = {
        'cliente': _personaje(ingreso.cliente.nombres, ('Cliente', 'Cliente'), respaldo='Cliente'),
        'asesora': _personaje(
            nombre_asesora, ('Asesor comercial', 'Asesora comercial'),
            genero_por_defecto='f', respaldo='Asesora',
        ),
        'tecnico': tecnico,
        'tecnico_reparo': tecnico,
    }
    if salida is not None and salida.tecnico_reparo_nombre:
        personajes['tecnico_reparo'] = _personaje(
            salida.tecnico_reparo_nombre, ('Técnico que reparó', 'Técnica que reparó'),
        )

    # ── Dinero ──────────────────────────────────────────
    valor_pendiente = ingreso.valor_acordado is None and not ingreso.reparacion_cancelada
    total = ingreso.valor_total_con_bodegaje
    pagado = ingreso.total_abonado
    saldo = ingreso.diferencia
    sin_cobro = not valor_pendiente and total <= 0
    if total > 0:
        pagado_pct = int(min(Decimal('100'), max(Decimal('0'), pagado * 100 / total)))
    else:
        pagado_pct = 100 if not valor_pendiente else 0
    pagado_completo = not valor_pendiente and saldo <= 0
    dinero = {
        'total': 'Pendiente' if valor_pendiente else dinero_signo(total),
        'pagado': dinero_signo(pagado),
        'saldo': dinero_signo(max(saldo, Decimal('0.00'))),
        'anticipo': dinero_signo(ingreso.abono_anticipo or 0),
        'tiene_anticipo': (ingreso.abono_anticipo or 0) > 0,
        'saldo_pendiente': saldo > 0,
        'valor_pendiente': valor_pendiente,
        'pagado_pct': pagado_pct,
        'sin_cobro': sin_cobro,
    }

    # ── Resultado técnico y alertas ─────────────────────
    resultado = None
    if salida is not None:
        texto, tono = RESULTADOS_SALIDA.get(salida.estado_reparacion, ('Finalizado', 'bueno'))
        resultado = {'texto': texto, 'tono': tono}

    alerta = None
    if retirado:
        if saldo > 0:
            alerta = {'tipo': 'saldo', 'etapa': 4, 'texto': f'Salió con saldo pendiente {dinero_signo(saldo)}'}
    else:
        if valor_pendiente:
            alerta = {'tipo': 'valor', 'etapa': 1, 'texto': 'Falta registrar el valor acordado'}
        elif ingreso.estado == 'en_reparacion' and ingreso.subestado_reparacion == 'espera_repuesto':
            alerta = {'tipo': 'repuesto', 'etapa': 2, 'texto': 'Esperando repuestos'}
        elif ingreso.estado == 'en_reparacion' and ingreso.subestado_reparacion == 'espera_cliente':
            alerta = {'tipo': 'cliente', 'etapa': 2, 'texto': 'Esperando respuesta del cliente'}
        elif actual == 3 and saldo > 0:
            alerta = {'tipo': 'saldo', 'etapa': 4, 'texto': f'Saldo pendiente {dinero_signo(saldo)}'}
        elif actual == 3:
            alerta = {'tipo': 'retiro', 'etapa': 3, 'texto': 'Esperando que el cliente lo retire'}

    # ── Estaciones ──────────────────────────────────────
    detalles = {
        'recepcion': [
            ['Asesora', personajes['asesora']['nombre_completo']],
            ['Registró', _nombre_usuario(ingreso.registrado_por) or '—'],
            ['Fecha de ingreso', _fecha(ingreso.fecha_ingreso)],
            ['Anticipo', dinero['anticipo'] if dinero['tiene_anticipo'] else 'Sin anticipo'],
            ['Accesorios', _recortar(ingreso.accesorios_entregados, 80) or '—'],
            ['Problema', _recortar(ingreso.problema_reportado)],
        ],
        'diagnostico': [
            ['Técnico', tecnico['nombre_completo']],
            ['Diagnóstico express', 'Sí' if ingreso.diagnostico_inmediato == 'si' else 'No'],
            ['Valor acordado', 'Pendiente' if ingreso.valor_acordado is None else dinero_signo(ingreso.valor_acordado)],
            ['Reporte', _recortar(ingreso.reporte_tecnico) or 'Sin reporte aún'],
        ],
        'taller': [
            ['Técnico', personajes['tecnico_reparo']['nombre_completo']],
            ['Detalle', ingreso.subestado_visual_display or ingreso.estado_visual_display],
            ['Días en Econotec', _texto_dias(dias)],
        ],
        'listo': [
            ['Finalizado', _fecha(salida.fecha_salida) if salida is not None else 'Aún no'],
            ['Resultado', resultado['texto'] if resultado else '—'],
            ['Técnico que reparó', personajes['tecnico_reparo']['nombre_completo'] if salida is not None else '—'],
        ],
        'caja': [
            ['Total a cobrar', 'Sin cobro' if sin_cobro else dinero['total']],
            ['Pagado', dinero['pagado']],
            ['Saldo', dinero['saldo']],
            ['Abonos registrados', str(ingreso.abonos.count())],
        ],
        'salida': [
            ['Retiro', _fecha(salida.fecha_retiro_real) if salida is not None and salida.fecha_retiro_real else ('Confirmado' if retirado else 'Pendiente')],
            ['A domicilio', 'Sí' if ingreso.a_domicilio == 'si' else 'No'],
            ['Cliente', personajes['cliente']['nombre_completo']],
        ],
    }
    if ingreso.estado == 'garantia' and ingreso.equipo_garantia_referencia:
        detalles['taller'].append(['Garantía de', str(ingreso.equipo_garantia_referencia)])

    etapas = []
    for indice, (clave, titulo, icono) in enumerate(ETAPAS):
        if retirado or indice < actual:
            estado = 'hecho'
        elif indice == actual:
            estado = 'actual'
        else:
            estado = 'pendiente'
        if clave == 'caja':
            if pagado_completo and (pagado > 0 or sin_cobro):
                estado = 'hecho'
            elif actual >= 3 and saldo > 0:
                estado = 'alerta'
        etapas.append({
            'clave': clave,
            'titulo': titulo,
            'icono': icono,
            'estado': estado,
            'detalles': [fila for fila in detalles[clave] if fila[1]],
        })

    completadas = sum(1 for etapa in etapas if etapa['estado'] == 'hecho')
    logros = [
        {'clave': 'recibido', 'titulo': 'Recibido', 'icono': '📥', 'ok': True},
        {'clave': 'diagnosticado', 'titulo': 'Diagnosticado', 'icono': '🔍', 'ok': actual >= 2 or bool(ingreso.reporte_tecnico)},
        {'clave': 'reparado', 'titulo': 'Reparado', 'icono': '🛠', 'ok': salida is not None and (resultado or {}).get('tono') == 'bueno'},
        {'clave': 'pagado', 'titulo': 'Pagado', 'icono': '💰', 'ok': pagado_completo},
        {'clave': 'entregado', 'titulo': 'Entregado', 'icono': '🏁', 'ok': retirado},
    ]

    return {
        'codigo': ingreso.codigo_equipo,
        'equipo': {
            'tipo': ingreso.tipo_equipo,
            'tipo_display': ingreso.tipo_equipo_display,
            'marca': ingreso.marca,
            'modelo': ingreso.modelo_serie,
        },
        'estado': {
            'clave': ingreso.estado_visual_key,
            'texto': ingreso.estado_visual_display,
            'subestado': ingreso.subestado_visual_display,
        },
        'etapa_actual': actual,
        'retirado': retirado,
        'progreso': 100 if retirado else round(actual * 100 / (len(ETAPAS) - 1)),
        'xp': completadas * XP_POR_ETAPA,
        'xp_max': len(ETAPAS) * XP_POR_ETAPA,
        'dias': dias,
        'dias_texto': _texto_dias(dias),
        'a_domicilio': ingreso.a_domicilio == 'si',
        'garantia': ingreso.estado == 'garantia',
        'resultado': resultado,
        'alerta': alerta,
        'dinero': dinero,
        'personajes': personajes,
        'etapas': etapas,
        'logros': logros,
    }
