"""
Filtros de plantilla personalizados para Econotec.

Principal uso: filtro `dinero` que formatea cualquier número/Decimal
SIEMPRE con 2 decimales y coma decimal (formato latinoamericano),
sin sufrir el problema de Decimal mostrando 12 decimales basura.

Ejemplos:
    {{ valor|dinero }}        → "234,97"
    {{ valor|dinero_signo }}  → "$234,97"
    {{ valor|dinero_signo:"-" }}  → "—" si es 0 o vacío

Por qué existe:
    En el panel los totales se calculaban con Decimal y al imprimirse
    aparecían como "$234,970000000000". Este filtro lo soluciona
    cuantizando siempre a 2 decimales.
"""
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

from django import template

register = template.Library()


def _a_decimal(valor):
    """Convierte cualquier entrada en Decimal con 2 decimales fijos."""
    if valor is None or valor == '':
        return Decimal('0.00')
    try:
        if isinstance(valor, Decimal):
            d = valor
        else:
            d = Decimal(str(valor))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal('0.00')
    return d.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def _formatear_es(valor_decimal):
    """
    Toma un Decimal ya cuantizado y lo formatea estilo Ecuador:
    miles con punto, decimales con coma. Ej.: 1234.5 → "1.234,50"
    """
    # str → "234.97" o "-1234.50"
    s = f'{valor_decimal:,.2f}'   # "1,234.50"
    # Cambiamos: , (miles) → temporal, . (decimal) → ,, temporal → .
    s = s.replace(',', '\x00').replace('.', ',').replace('\x00', '.')
    return s


@register.filter(name='dinero')
def dinero(valor):
    """Devuelve el monto con 2 decimales y coma decimal, sin signo $.

    Uso: {{ saldo|dinero }} → "234,97"
    """
    return _formatear_es(_a_decimal(valor))


@register.filter(name='dinero_signo')
def dinero_signo(valor, vacio='$0,00'):
    """Devuelve el monto con prefijo $ y 2 decimales.

    Si el valor es explícitamente None o vacío, devuelve "—" o el vacio deseado.
    """
    if valor is None or valor == '':
        return '—'
        
    d = _a_decimal(valor)
    if d == Decimal('0.00') and vacio != '$0,00':
        return vacio
    return f'${_formatear_es(d)}'


@register.filter(name='dinero_o_cero')
def dinero_o_cero(valor):
    """Alias de dinero_signo sin vacío especial."""
    return f'${_formatear_es(_a_decimal(valor))}'
