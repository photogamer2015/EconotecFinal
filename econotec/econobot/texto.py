"""Lectura tolerante de lo que escribe la persona en el chat.

Nada de lo escrito se ejecuta: solo se normaliza y se compara contra
opciones conocidas del sistema.
"""
import re
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from django.utils import timezone

from ..busqueda import normalizar_texto_busqueda


def norm(valor):
    """Minúsculas, sin tildes y con espacios simples."""
    return ' '.join(normalizar_texto_busqueda(valor).split())


def limpiar(valor):
    """Texto sin puntuación de cierre ni espacios sobrantes."""
    return norm(valor).strip(' .,;:!?¿¡"\'')


SI = {
    'si', 's', 'sip', 'sii', 'claro', 'correcto', 'ok', 'okay', 'dale', 'de acuerdo',
    'afirmativo', 'confirmo', 'confirmar', 'confirmado', 'listo', 'por supuesto',
    'si claro', 'si por favor', 'si registrar', 'registrar', 'guardar', 'si guardar',
    'si confirmar', 'si confirmo', 'adelante', 'hazlo', 'si hazlo', 'yes', 'va',
    'registrala', 'registralo', 'finalizar', 'finalizalo', 'confirmar salida',
}
NO = {
    'no', 'n', 'nop', 'nel', 'negativo', 'ninguno', 'ninguna', 'no tiene',
    'no tengo', 'no hay', 'nada', 'no gracias', 'sin', 'no trajo', 'no firma',
    'no firmo', 'no dejo', 'no dejo nada', 'sin abono', 'sin anticipo', 'no aplica',
}
OMITIR = {
    'omitir', 'omite', 'saltar', 'salta', 'siguiente', 'sin dato', 'sin datos',
    'no se', 'no sabe', 'no lo se', 'luego', 'despues', 'n/a', 'na', '-', '—',
    'ninguno', 'ninguna', 'no tiene', 'no tengo', 'no hay', 'nada', 'sin',
    'omitir opcionales',
}


def es_si(texto):
    t = limpiar(texto)
    return t in SI or t.startswith('si ') and len(t) < 30


def es_no(texto):
    t = limpiar(texto)
    return t in NO or t.startswith('no ') and len(t) < 30


def es_omitir(texto):
    return limpiar(texto) in OMITIR


def sino(texto):
    """Devuelve 'si', 'no' o None."""
    if es_si(texto):
        return 'si'
    if es_no(texto):
        return 'no'
    return None


_NUMERO = re.compile(r'-?\d+(?:[.,]\d{1,2})?')


def dinero(texto):
    """Convierte «$25», «25,50» o «25.5» en '25.50'. Devuelve None si no hay número."""
    crudo = str(texto or '').strip().replace('$', '').replace('usd', '').replace('USD', '')
    crudo = crudo.replace(' ', '')
    if crudo.count(',') == 1 and crudo.count('.') >= 1:
        # Formato 1.234,56 → 1234.56
        crudo = crudo.replace('.', '').replace(',', '.')
    elif crudo.count(',') == 1:
        crudo = crudo.replace(',', '.')
    coincidencia = _NUMERO.fullmatch(crudo) or _NUMERO.search(crudo)
    if not coincidencia:
        return None
    try:
        valor = Decimal(coincidencia.group().replace(',', '.'))
    except InvalidOperation:
        return None
    return f'{valor.quantize(Decimal("0.01"))}'


def fecha(texto):
    """Acepta «hoy», «ayer», DD/MM/AAAA, DD-MM-AAAA, DD/MM y AAAA-MM-DD."""
    t = limpiar(texto)
    hoy = timezone.localdate()
    if t in ('hoy', 'ahora', 'el dia de hoy'):
        return hoy.isoformat()
    if t == 'ayer':
        return (hoy - timedelta(days=1)).isoformat()
    crudo = str(texto or '').strip()
    for formato in ('%d/%m/%Y', '%d-%m-%Y', '%Y-%m-%d', '%d/%m/%y', '%d-%m-%y'):
        try:
            return datetime.strptime(crudo, formato).date().isoformat()
        except ValueError:
            pass
    for formato in ('%d/%m', '%d-%m'):
        try:
            parcial = datetime.strptime(crudo, formato)
            return date(hoy.year, parcial.month, parcial.day).isoformat()
        except ValueError:
            pass
    return None


def fecha_legible(valor):
    if not valor:
        return '—'
    if isinstance(valor, str):
        try:
            valor = date.fromisoformat(valor)
        except ValueError:
            return valor
    return valor.strftime('%d/%m/%Y')


def dinero_legible(valor):
    """$1.234,56 como en el resto del sistema."""
    try:
        numero = Decimal(str(valor if valor not in (None, '') else '0'))
    except InvalidOperation:
        return str(valor)
    signo = '-' if numero < 0 else ''
    entero, decimales = f'{abs(numero):.2f}'.split('.')
    grupos = []
    while entero:
        grupos.insert(0, entero[-3:])
        entero = entero[:-3]
    return f'{signo}${".".join(grupos)},{decimales}'


def solo_digitos(texto):
    return re.sub(r'\D', '', str(texto or ''))


_CODIGO = re.compile(r'(?<![A-Za-z0-9])([GgUuPp])[\s#-]?(\d{1,6})(?![0-9])')


def codigos_equipo(texto):
    """Códigos como G1031, U1002 o P001 escritos en el mensaje."""
    return [f'{letra.upper()}{numero}' for letra, numero in _CODIGO.findall(str(texto or ''))]


def cedula_en(texto):
    """Primera cédula (10 dígitos) o RUC (13 dígitos) del mensaje."""
    coincidencia = re.search(r'(?<!\d)(\d{10}|\d{13})(?!\d)', solo_espacios_numericos(texto))
    return coincidencia.group(1) if coincidencia else ''


def solo_espacios_numericos(texto):
    """Une dígitos separados por espacios o guiones: 0912 345 678 → 0912345678."""
    return re.sub(r'(?<=\d)[\s-](?=\d)', '', str(texto or ''))


def elegir(texto, opciones):
    """Busca una opción por número, valor o etiqueta.

    `opciones` es una lista de (valor, etiqueta). Devuelve el valor elegido o
    None si no hay una coincidencia única.
    """
    t = limpiar(texto)
    if not t:
        return None
    if t.isdigit():
        indice = int(t) - 1
        if 0 <= indice < len(opciones):
            return opciones[indice][0]
    exactas = [valor for valor, etiqueta in opciones
               if t in (norm(valor), limpiar(etiqueta))]
    if len(exactas) == 1:
        return exactas[0]
    parciales = [valor for valor, etiqueta in opciones
                 if t in limpiar(etiqueta) or limpiar(etiqueta) in t]
    if len(parciales) == 1:
        return parciales[0]
    palabras = set(t.split())
    por_palabras = [valor for valor, etiqueta in opciones
                    if palabras and palabras <= set(limpiar(etiqueta).split())]
    if len(por_palabras) == 1:
        return por_palabras[0]
    return None


def nombre_usuario(user):
    if not user:
        return ''
    return (f'{user.first_name} {user.last_name}'.strip()) or user.username


def primer_nombre(user):
    nombre = nombre_usuario(user)
    return nombre.split(' ')[0] if nombre else ''
