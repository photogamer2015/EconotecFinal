"""Lo que EconoBot sabe del sistema: reglas reales y dónde está cada cosa.

Los números se leen de las mismas constantes que usa el sistema, así la
explicación nunca se desactualiza respecto al cálculo real.
"""
import re

from ..alertas import (
    COSTO_BODEGAJE_DIA, UMBRAL_DIAS_BODEGAJE, UMBRAL_DIAS_DIAGNOSTICO, UMBRAL_DIAS_REPARACION_ADMIN,
    UMBRAL_DIAS_REPARACION_TECNICO,
)
from ..gamificacion import PUNTOS_SALIDA_BUENA, PUNTOS_SALIDA_MALA_RESTA, PUNTOS_SALIDA_PRODUCTO
from ..permisos import es_admin, puede_ver_ranking
from . import texto as tx
from .respuesta import enlace, opcion, respuesta


# ─────────────────────────────────────────────────────────────────────
# Secciones del sistema («abrir pagos», «¿dónde veo los clientes?»)
# ─────────────────────────────────────────────────────────────────────

# (palabras clave, etiqueta, ruta, permiso: None = todos | 'admin' | 'ranking')
SECCIONES = [
    (('nueva solicitud', 'nuevo ingreso', 'formulario de ingreso', 'solicitud de ingreso'),
     'Nueva Solicitud de Ingreso', 'ingreso_registrar', None),
    (('menu de ingresos', 'ingreso de equipo', 'ingresos'), 'Ingreso de Equipo / Cliente', 'ingreso_menu', None),
    (('lista de equipos', 'equipos ingresados', 'lista de ingresos'), 'Lista de equipos', 'ingreso_lista', None),
    (('salidas fisicas', 'salida fisica confirmada', 'retirados'), 'Salidas físicas confirmadas',
     'salida_retiros_lista', None),
    (('equipos finalizados', 'lista de finalizados', 'equipo listo', 'finalizados'), 'Equipos finalizados',
     'salida_lista', None),
    (('menu de salidas', 'equipo listo / finalizado'), 'Equipo listo / finalizado', 'salida_menu', None),
    (('facturas realizadas', 'facturas'), 'Facturas realizadas', 'salida_facturas_lista', None),
    (('top clientes', 'clientes recurrentes'), 'Top clientes recurrentes', 'cliente_top_recurrentes', None),
    (('clientes', 'directorio'), 'Clientes', 'cliente_lista', None),
    (('historial de pagos', 'historial'), 'Historial de pagos', 'historial_lista', None),
    (('pagos', 'abonos', 'cobros'), 'Pagos', 'pagos_lista', None),
    (('venta de producto', 'ventas'), 'Venta de Producto', 'venta_menu', None),
    (('inventario',), 'Inventario', 'inventario_menu', None),
    (('bodegaje / chatarrerizacion', 'chatarrerizacion', 'panel de bodegaje'), 'Bodegaje / Chatarrerización',
     'admin_activos_bodegaje', None),
    (('ranking de tecnicos', 'ranking'), 'Ranking de Técnicos', 'salida_totales', 'ranking'),
    (('alertas de demora', 'demoras'), 'Alertas de demora', 'alertas_demora', None),
    (('alertas de bodegaje',), 'Alertas de bodegaje', 'alertas_bodegaje', None),
    (('notificaciones',), 'Notificaciones de asesoras', 'notificaciones_asesora', None),
    (('mi perfil', 'perfil'), 'Mi perfil', 'mi_perfil', None),
    (('comunidad',), 'Comunidad', 'comunidad', None),
    (('centro de ayuda', 'manual', 'ayuda'), 'Ayuda', 'ayuda', None),
    (('musica',), 'Música', 'reproductor_musica', None),
    (('inicio', 'panel principal', 'dashboard', 'pantalla principal'), 'Inicio', 'bienvenida', None),
    (('registro administrativo', 'panel administrativo', 'utilidad neta'), 'Registro Administrativo',
     'admin_dashboard', 'admin'),
    (('egresos', 'gastos'), 'Egresos', 'admin_egresos_lista', 'admin'),
    (('control de registro', 'auditoria'), 'Control de Registro', 'control_registro', 'admin'),
    (('avisos del panel', 'avisos'), 'Avisos del panel', 'avisos_lista', 'admin'),
    (('donados', 'equipos a comprar'), 'Donados / Equipos a comprar', 'admin_equipos_administrativos', 'admin'),
    (('ventas e inventario', 'administracion de ventas'), 'Administración de Ventas e Inventario',
     'admin_ventas_inventario', 'admin'),
]


def _permitido(user, permiso):
    if permiso == 'admin':
        return es_admin(user)
    if permiso == 'ranking':
        return puede_ver_ranking(user)
    return True


def _contiene(texto, frase):
    return re.search(r'(?:^|\b)' + re.escape(frase) + r'(?:\b|$)', texto) is not None


def seccion_pedida(user, mensaje):
    """(etiqueta, ruta) de la sección mencionada, o None. También dice si no hay permiso."""
    t = tx.limpiar(mensaje)
    mejor = None
    for claves, etiqueta, ruta, permiso in SECCIONES:
        for clave in claves:
            if _contiene(t, clave) and (mejor is None or len(clave) > mejor[0]):
                mejor = (len(clave), etiqueta, ruta, permiso)
    if mejor is None:
        return None
    _largo, etiqueta, ruta, permiso = mejor
    return etiqueta, ruta, _permitido(user, permiso)


def abrir_seccion(user, mensaje):
    encontrada = seccion_pedida(user, mensaje)
    if encontrada is None:
        return None
    etiqueta, ruta, permitido = encontrada
    if not permitido:
        if ruta == 'admin_equipos_administrativos':
            # El resto de roles consulta la misma información en su propia lista.
            return respuesta(f'Aquí tienes {etiqueta}:', [enlace(etiqueta, 'equipos_administrativos_general')])
        return respuesta(f'«{etiqueta}» es una sección solo para administradores.')
    tipo = 'nueva' if ruta == 'inventario_menu' else 'nav'
    return respuesta(f'Aquí tienes {etiqueta}:', [enlace(etiqueta, ruta, tipo=tipo)])


# ─────────────────────────────────────────────────────────────────────
# Temas de ayuda
# ─────────────────────────────────────────────────────────────────────

def _dinero(valor):
    return tx.dinero_legible(valor)


def _registrar(request):
    return respuesta(
        'Para registrar un equipo tienes dos caminos:\n'
        '1. Aquí mismo en el chat: escribe «registrar equipo» y te pido los datos uno por uno '
        '(cédula, equipo, problema, estado, asesora, técnico, valor acordado, abono y firma). '
        'Al final te muestro el resumen y solo se guarda cuando confirmas.\n'
        '2. En la web: Ingreso de Equipo / Cliente → Nueva Solicitud de Ingreso.\n'
        'Si la cédula ya existe, los datos del cliente se completan solos. Al guardar se genera el código '
        '(G para Guayaquil, U para Quito), la hoja para imprimir, el PDF, el QR y, si el cliente tiene correo, '
        'se le envía su comprobante.',
        [enlace('Nueva Solicitud de Ingreso', 'ingreso_registrar')],
        [opcion('📥 Registrar equipo aquí', 'registrar equipo')],
    )


def _estados(request):
    return respuesta(
        'Estados de un equipo en el taller:\n'
        '• Ingresado / En diagnóstico: recién recibido, esperando revisión.\n'
        '• En reparación: se trabaja en él. Lleva un detalle obligatorio: «En reparación», '
        '«En reparación - Cliente» (esperando respuesta del cliente) o «En reparación - Repuestos».\n'
        '• Garantía: vuelve por un trabajo anterior; se indica el motivo (no se cobra valor acordado).\n'
        '• Cortesía: no genera cobros.\n'
        '• Donado / Equipo a comprar: registros administrativos (sin finalización de reparación).\n'
        'Cuando termina el trabajo se «finaliza» (Equipo listo / finalizado) y queda en la oficina hasta '
        'confirmar su salida física.',
        opciones=[opcion('🔧 Cambiar estado de un equipo', 'cambiar estado')],
    )


def _finalizar(request):
    return respuesta(
        'Finalizar = registrar cómo terminó el trabajo (botón «Equipo listo / finalizado»). Resultados:\n'
        '• Reparado — pendiente de retiro (el más común).\n'
        '• Revisión (se cobra un valor de revisión).\n'
        '• Cliente no quiso reparar / No se pudo reparar.\n'
        '• Garantía finalizada (con o sin fallos adicionales) y Cortesía finalizada.\n'
        'Reglas: el equipo debe tener valor acordado para finalizarse como reparado; se indica el técnico que '
        f'reparó (una salida buena le suma {PUNTOS_SALIDA_BUENA} puntos y una mala le resta '
        f'{PUNTOS_SALIDA_MALA_RESTA}). Si queda saldo, se notifica a una asesora para cobrarlo.\n'
        'Finalizar NO es la salida física: el equipo sigue en la oficina hasta que confirmes que el cliente se lo llevó.\n'
        'Puedo hacerlo por ti: escribe «finalizar G1031».',
        [enlace('Equipos finalizados', 'salida_lista')],
        [opcion('✅ Finalizar un equipo', 'finalizar equipo')],
    )


def _salida_fisica(request):
    return respuesta(
        'La salida física se confirma cuando el cliente ya se llevó el equipo:\n'
        '• El saldo debe estar en $0,00 (primero registra el pago).\n'
        f'• Si acumuló bodegaje, se decide cobrarlo o perdonarlo en ese momento.\n'
        '• Se envía el acta de salida al correo del cliente (si tiene).\n'
        'Solo un administrador puede deshacer una salida física confirmada.\n'
        'Por chat: escribe «confirmar salida G1031».',
        [enlace('Equipos finalizados', 'salida_lista'), enlace('Salidas físicas confirmadas', 'salida_retiros_lista')],
        [opcion('🚚 Confirmar una salida', 'confirmar salida')],
    )


def _bodegaje(request):
    return respuesta(
        f'Bodegaje: cuando un equipo ya finalizado no se retira, desde el día {UMBRAL_DIAS_BODEGAJE} después de '
        f'finalizado se cobra {_dinero(COSTO_BODEGAJE_DIA)} por cada día (el día {UMBRAL_DIAS_BODEGAJE} cuenta como el '
        f'primer día: día {UMBRAL_DIAS_BODEGAJE} → {_dinero(COSTO_BODEGAJE_DIA)}, día {UMBRAL_DIAS_BODEGAJE + 1} → '
        f'{_dinero(COSTO_BODEGAJE_DIA * 2)}…).\n'
        '• No aplica a equipos de cortesía.\n'
        '• Al confirmar la salida física (o al registrar un pago) se decide si se cobra o se perdona, y el monto '
        'queda congelado.\n'
        '• Puedes silenciar la alerta de un equipo con 🔕; el bodegaje sigue sumando.\n'
        '• Desde «Bodegaje / Chatarrerización» se envían avisos por WhatsApp o correo; enviar a chatarrerización '
        'es solo para administradores.',
        [enlace('Alertas de bodegaje', 'alertas_bodegaje'), enlace('Bodegaje / Chatarrerización', 'admin_activos_bodegaje')],
        [opcion('📦 Ver equipos con bodegaje', 'alertas')],
    )


def _alertas(request):
    return respuesta(
        'Alertas automáticas del sistema:\n'
        f'• Diagnóstico demorado: equipos «Ingresado / En diagnóstico» con {UMBRAL_DIAS_DIAGNOSTICO} o más días '
        'sin cambiar de estado. Desaparece al cambiar el estado.\n'
        f'• Reparación detenida: equipos «En reparación» (cualquier detalle) sin cambios: el técnico la ve a los '
        f'{UMBRAL_DIAS_REPARACION_TECNICO} días y el administrador a los {UMBRAL_DIAS_REPARACION_ADMIN}.\n'
        f'• Bodegaje: equipos finalizados con {UMBRAL_DIAS_BODEGAJE} o más días sin retirar '
        f'({_dinero(COSTO_BODEGAJE_DIA)} por día).\n'
        'Con 🔕 se silencia la alerta de un equipo sin cambiar nada más.',
        [enlace('Alertas de demora', 'alertas_demora'), enlace('Alertas de bodegaje', 'alertas_bodegaje')],
        [opcion('🔔 Ver alertas ahora', 'alertas')],
    )


def _pagos(request):
    return respuesta(
        'Pagos y abonos:\n'
        '• Pagos → busca el equipo → «Ingresar abono». Métodos: efectivo, transferencia (banco + enlace del '
        'comprobante), tarjeta/app (Payphone o Deuna) o pago mixto (dos métodos que suman el total).\n'
        '• El anticipo del ingreso y el diagnóstico inmediato también cuentan como pagos.\n'
        '• Cada abono genera su recibo; todo queda en el Historial de pagos.\n'
        '• Si el equipo tiene bodegaje, al registrar el pago se pregunta si se cobra o se perdona.\n'
        '• Con saldo en $0,00 ya se puede confirmar la salida física.\n'
        'Pregúntame «saldos pendientes» o «saldo G1031» para ver lo que se debe.',
        [enlace('Pagos', 'pagos_lista'), enlace('Historial de pagos', 'historial_lista')],
        [opcion('💰 Saldos pendientes', 'saldos pendientes')],
    )


def _valor_acordado(request):
    return respuesta(
        'Valor acordado = el precio de la reparación acordado con el cliente.\n'
        '• Se puede registrar al ingresar el equipo o después, desde Pagos del equipo.\n'
        '• Es obligatorio para finalizar un equipo como reparado.\n'
        '• Si aún no hay valor, el técnico puede dejar el motivo en su Hoja del técnico.\n'
        'Por chat: «valor acordado G1031 45».',
        [enlace('Equipos sin valor acordado', 'ingreso_lista')],
        [opcion('💲 Ver equipos sin valor', 'sin valor acordado')],
    )


def _hoja_tecnico(request):
    return respuesta(
        'Hoja del técnico (QR): cada equipo lleva un QR. Al escanearlo con el celular se abre su hoja digital, '
        'donde el técnico escribe el reporte y cambia el estado (Ingresado, En reparación, Con solución, '
        'Sin solución o No quiso reparar). El QR se imprime en formato ticket desde el equipo.\n'
        'Desde aquí también puedo cambiar el estado o el reporte: «cambiar estado G1031» o «reporte G1031».',
        opciones=[opcion('📝 Escribir un reporte', 'reporte'), opcion('🔧 Cambiar estado', 'cambiar estado')],
    )


def _garantia(request):
    return respuesta(
        'Garantía: se registra como un ingreso con estado «Garantía», indicando el motivo y, si existe, el equipo '
        'anterior del cliente. No lleva valor acordado ni anticipo. Al terminar se finaliza como «Garantía '
        'finalizada» o «Garantía finalizada + fallos adicionales» (en este caso se cobra el valor de los fallos '
        'adicionales).',
        opciones=[opcion('📥 Registrar una garantía', 'registrar equipo')],
    )


def _cortesia(request):
    return respuesta(
        'Cortesía: equipo que se atiende sin costo. No lleva valor acordado, anticipo ni pagos, no acumula '
        'bodegaje y al terminar se finaliza como «Equipo de cortesía finalizado».',
    )


def _diagnostico(request):
    return respuesta(
        'Diagnóstico inmediato: si al recibir el equipo se cobra un diagnóstico, se marca «Sí» y se registra el '
        'valor con su método de pago. Cuenta como pago del cliente. Si luego el equipo no se repara, ese pago se '
        'recalcula igual que en la web.',
    )


def _anticipo(request):
    return respuesta(
        'Abono / anticipo: dinero que deja el cliente al ingresar el equipo. Se registra con su método de pago '
        '(efectivo, transferencia, tarjeta/app o mixto) y se descuenta del saldo. No aplica a cortesía, donado ni '
        'equipo a comprar.',
    )


def _donado(request):
    return respuesta(
        'Donado y Equipo a comprar son registros administrativos: un equipo donado no tiene valor a pagar, y en '
        '«Equipo a comprar» el valor acordado es lo que se paga por el equipo (se registra como egreso). '
        'No usan la finalización de reparación.',
        [enlace('Donados / Equipos a comprar', 'equipos_administrativos_general')],
    )


def _ventas(request):
    return respuesta(
        'Venta de Producto: para vender repuestos, tintas u otros productos sin reparación. Cada venta lleva '
        'código P (P001, P002…), se registra en Venta de Producto → Nueva Venta y puede pagarse completa o por '
        'partes (Control de Pago de Ventas).',
        [enlace('Venta de Producto', 'venta_menu')],
    )


def _inventario(request):
    return respuesta(
        'Inventario: productos por sede y categoría con su cantidad. Desde cada producto puedes ajustar la '
        'cantidad, imprimir su QR o avisar al administrador cuando el stock es crítico.',
        [enlace('Inventario', 'inventario_menu', tipo='nueva')],
    )


def _roles(request):
    return respuesta(
        'Roles del sistema:\n'
        '• Administrador: acceso total (Registro Administrativo, egresos, auditoría, avisos, deshacer salidas, '
        'chatarrerización, valores del ranking).\n'
        '• Técnico y Asesora comercial: registran ingresos, finalizan equipos, registran pagos, confirman salidas '
        'y consultan clientes e historial.\n'
        '• Las asesoras reciben notificaciones cuando queda un saldo por cobrar.',
    )


def _ranking(request):
    return respuesta(
        f'Ranking de técnicos: el técnico que reparó (el que se indica al finalizar) suma {PUNTOS_SALIDA_BUENA} '
        f'puntos por cada salida buena (reparado, garantía) y {PUNTOS_SALIDA_PRODUCTO} por venta de producto; '
        f'resta {PUNTOS_SALIDA_MALA_RESTA} por salida mala (no se pudo reparar, cliente no quiso, chatarrerización). '
        'Los valores económicos del ranking solo los ve el administrador.',
        [enlace('Ranking de Técnicos', 'salida_totales')] if puede_ver_ranking(request.user) else [],
    )


def _firma(request):
    return respuesta(
        'Firma del cliente: al registrar el equipo se pregunta si el cliente firmará. Si dice que sí, firma en el '
        'recuadro (con el dedo o el mouse) y la firma queda en la hoja y en el PDF. En el chat te muestro el '
        'recuadro para firmar.',
    )


def _factura(request):
    return respuesta(
        'Factura: al finalizar o editar la finalización puedes indicar si se realizó factura (nombres, cédula y '
        'correo de facturación). Las facturas registradas se consultan en «Facturas realizadas».',
        [enlace('Facturas realizadas', 'salida_facturas_lista')],
    )


def _codigos(request):
    return respuesta(
        'Códigos de equipo: G = Guayaquil (G1000, G1001…), U = Quito (U1000…) y P = Venta de producto (P001…). '
        'Cada sede lleva su propia numeración. Escríbeme cualquier código para ver su ficha, por ejemplo «G1031».',
    )


def _correos(request):
    return respuesta(
        'Correos automáticos al cliente (si tiene correo registrado):\n'
        '• Al registrar el equipo: comprobante de ingreso con el PDF.\n'
        '• Al finalizar: puedes enviar el acta de finalización (yo te doy el botón).\n'
        '• Al confirmar la salida física: acta de salida actualizada.',
    )


def _whatsapp(request):
    return respuesta(
        'WhatsApp: el sistema arma mensajes listos para el cliente (hoja de ingreso, equipo listo, demora y '
        'bodegaje). Cuando registro o finalizo un equipo te dejo el botón «WhatsApp» con el mensaje preparado.',
    )


def _contacto(request):
    return respuesta(
        'Contacto Econotec:\n'
        '• Guayaquil: Sauces 8 Mz 462 Solar 6, Piso 2, Oficina 2.\n'
        '• Quito: Av. Amazonas y 18 de Septiembre, Piso 2, Oficina 102.\n'
        '• WhatsApp: +593 96 383 6191 (central) · +593 96 328 9727 (Guayaquil) · +593 98 075 8747 (Quito).\n'
        '• Web: econotec-ec.com',
    )


# (frases que lo activan, respuesta). Gana la frase más larga encontrada.
TEMAS = [
    (('como registro un equipo', 'como registro el equipo', 'como registro equipos', 'como ingreso un equipo',
      'como ingresar un equipo', 'registrar un equipo', 'registrar equipos', 'solicitud de ingreso', 'nuevo ingreso',
      'como se registra un equipo', 'ingresar un equipo'), _registrar),
    (('estados', 'estado del equipo', 'que significa en reparacion', 'espera de repuesto', 'espera de cliente',
      'subestado', 'en diagnostico'), _estados),
    (('finalizar', 'finalizo', 'finaliza', 'equipo listo', 'equipo finalizado', 'resultado final',
      'pendiente de retiro'), _finalizar),
    (('salida fisica', 'retiro', 'retirar', 'retira', 'se lo llevo', 'confirmar salida', 'entregar el equipo',
      'entrega del equipo', 'deshacer'), _salida_fisica),
    (('bodegaje', 'penalidad', 'multa', 'almacenaje', 'cobro por dia'), _bodegaje),
    (('alertas', 'alerta', 'demora', 'demorado', 'atrasado', 'silenciar'), _alertas),
    (('abono', 'abonos', 'pago', 'pagos', 'cobrar', 'recibo', 'metodo de pago', 'pago mixto', 'transferencia',
      'payphone', 'deuna', 'saldo'), _pagos),
    (('valor acordado', 'precio', 'cotizacion', 'valor pendiente'), _valor_acordado),
    (('qr', 'hoja del tecnico', 'hoja tecnica', 'escanear', 'reporte del tecnico', 'reporte tecnico'), _hoja_tecnico),
    (('garantia',), _garantia),
    (('cortesia',), _cortesia),
    (('diagnostico inmediato', 'diagnostico'), _diagnostico),
    (('anticipo',), _anticipo),
    (('donado', 'equipo a comprar', 'comprar un equipo'), _donado),
    (('venta de producto', 'ventas', 'vender', 'tintas', 'repuestos'), _ventas),
    (('inventario', 'stock'), _inventario),
    (('roles', 'rol', 'permisos', 'administrador', 'asesora', 'asesor'), _roles),
    (('ranking', 'puntos', 'puntaje', 'nivel'), _ranking),
    (('firma', 'firmar'), _firma),
    (('factura', 'facturas', 'facturacion'), _factura),
    (('codigo', 'codigos', 'numeracion', 'que significa la g', 'que significa la u'), _codigos),
    (('correo', 'correos', 'email', 'acta'), _correos),
    (('whatsapp',), _whatsapp),
    (('direccion', 'contacto', 'telefono de econotec', 'ubicacion', 'donde queda', 'donde estan'), _contacto),
]


def tema(request, mensaje):
    """Respuesta de ayuda para la pregunta, o None si no es un tema conocido."""
    t = tx.limpiar(mensaje)
    mejor = None
    for frases, funcion in TEMAS:
        for frase in frases:
            if _contiene(t, frase) and (mejor is None or len(frase) > mejor[0]):
                mejor = (len(frase), funcion)
    return mejor[1](request) if mejor else None


def capacidades(request):
    nombre = tx.primer_nombre(request.user)
    saludo = f'¡Hola, {nombre}! ' if nombre else '¡Hola! '
    return respuesta(
        saludo + '👋 Soy EconoBot, el asistente de Econotec. Puedo hacer por ti:\n'
        '• 📥 Registrar un equipo nuevo, paso a paso (con firma del cliente).\n'
        '• ✅ Finalizar un equipo: «finalizar G1031».\n'
        '• 🚚 Confirmar la salida física: «confirmar salida G1031».\n'
        '• 🔧 Cambiar estado o reporte: «cambiar estado G1031», «reporte G1031».\n'
        '• 💲 Poner el valor acordado: «valor acordado G1031 45».\n'
        '• 🔎 Ver un equipo («G1031»), un cliente («cliente 0912345678» o su nombre) o buscar («buscar HP»).\n'
        '• 📋 Listas: equipos en taller, mis equipos, finalizados en oficina, salidas físicas, sin valor acordado, '
        'saldos pendientes, alertas, resumen del día.\n'
        '• ❓ Explicarte cómo funciona el sistema: «¿qué es el bodegaje?», «¿cómo registro un abono?».\n'
        'Nada se guarda sin que lo confirmes, y todo pasa por las mismas validaciones de la web.',
        opciones=[
            opcion('📥 Registrar equipo', 'registrar equipo'),
            opcion('✅ Finalizar equipo', 'finalizar equipo'),
            opcion('📦 Finalizados en oficina', 'equipos finalizados'),
            opcion('🔧 Equipos en taller', 'equipos en taller'),
            opcion('👤 Buscar cliente', 'buscar cliente'),
            opcion('🔔 Alertas', 'alertas'),
        ],
    )
