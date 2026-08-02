"""Reglas compartidas para el puntaje de perfil de técnicos."""

PUNTOS_SALIDA_BUENA = 4
PUNTOS_SALIDA_PRODUCTO = 1
PUNTOS_SALIDA_MALA_RESTA = 1
# Compatibilidad con llamadas anteriores; las garantías ya no descuentan.
PUNTOS_SALIDA_GARANTIA_RESTA = 0

SALIDA_BUENA_ESTADOS = (
    'pendiente_retiro',
    'garantia',
    'garantia_fallos_adicionales',
    'retirado',
)
SALIDA_MALA_ESTADOS = (
    'no_reparable',
    'cliente_no_acepta',
    'chatarrerizacion',
)
# Se conserva por compatibilidad con el cálculo histórico. Las garantías ahora
# forman parte de las salidas positivas y no se descuentan por separado.
SALIDA_GARANTIA_ESTADOS = ()


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
