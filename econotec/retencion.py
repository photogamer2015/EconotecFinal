"""
Retención en facturas.

Cuando la factura lleva retención, el cliente retiene el IVA (100 %) y el
10 % de renta. Para que el taller reciba el valor neto deseado se factura
por encima de ese valor:

    subtotal = neto ÷ 0,90
    IVA 15 % = subtotal × 0,15
    total factura (valor con retención) = subtotal + IVA
    recibe = total − retención del IVA − retención de renta  (= neto)

El valor con retención (total de la factura) se puede editar; el desglose
siempre se deriva de ese total para que cuadre con lo que se emitió.
"""
from decimal import Decimal, ROUND_HALF_UP

IVA = Decimal('0.15')
RETENCION_IVA = Decimal('1.00')
RETENCION_RENTA = Decimal('0.10')

CERO = Decimal('0.00')


def _q2(valor):
    return Decimal(valor).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def total_con_retencion(neto):
    """Total de factura necesario para recibir `neto` después de las retenciones."""
    neto = _q2(neto or CERO)
    if neto <= CERO:
        return CERO
    factor_recibido = 1 + IVA - (IVA * RETENCION_IVA) - RETENCION_RENTA
    subtotal = _q2(neto / factor_recibido)
    return subtotal + _q2(subtotal * IVA)


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
