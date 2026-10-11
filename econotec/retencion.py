"""
Retención en facturas.

Cuando la factura lleva retención, el cliente retiene el IVA (100 %) y el
10 % de renta. El valor con retención (total de la factura) lo escribe el
usuario; el desglose que se guarda y se imprime se deriva de ese total:

    subtotal = total ÷ 1,15 · IVA 15 % = total − subtotal
    recibe   = total − retención del IVA − retención de renta
"""
from decimal import Decimal, ROUND_HALF_UP

IVA = Decimal('0.15')
RETENCION_IVA = Decimal('1.00')
RETENCION_RENTA = Decimal('0.10')

CERO = Decimal('0.00')


def _q2(valor):
    return Decimal(valor).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def desglose_retencion(total):
    """Desglose de una factura con retención a partir de su total."""
    total = _q2(total or CERO)
    subtotal = _q2(total / (1 + IVA))
    iva = total - subtotal
    iva_retenido = _q2(iva * RETENCION_IVA)
    renta_retenida = _q2(subtotal * RETENCION_RENTA)
    return {
        'subtotal': subtotal,
        'iva': iva,
        'total': total,
        'iva_retenido': iva_retenido,
        'renta_retenida': renta_retenida,
        'recibido': total - iva_retenido - renta_retenida,
    }


def porcentajes_retencion():
    """Porcentajes enteros para mostrar en pantalla y pasar al cálculo en JS."""
    return {
        'iva': int(IVA * 100),
        'retencion_iva': int(RETENCION_IVA * 100),
        'retencion_renta': int(RETENCION_RENTA * 100),
    }
