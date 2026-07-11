"""Reglas compartidas para el puntaje de perfil de técnicos."""

PUNTOS_SALIDA_BUENA = 4
PUNTOS_SALIDA_PRODUCTO = 1
PUNTOS_SALIDA_MALA_RESTA = 1
PUNTOS_SALIDA_GARANTIA_RESTA = 2

SALIDA_BUENA_ESTADOS = ('pendiente_retiro', 'retirado')
SALIDA_MALA_ESTADOS = ('no_reparable',)
SALIDA_GARANTIA_ESTADOS = ('garantia',)


def calcular_puntaje_gamificacion(
    salidas_buenas,
    salidas_producto,
    salidas_malas,
    salidas_garantia,
):
    """Calcula el puntaje total sin permitir valores negativos."""
    return max(
        0,
        (salidas_buenas * PUNTOS_SALIDA_BUENA)
        + (salidas_producto * PUNTOS_SALIDA_PRODUCTO)
        - (salidas_malas * PUNTOS_SALIDA_MALA_RESTA)
        - (salidas_garantia * PUNTOS_SALIDA_GARANTIA_RESTA),
    )
