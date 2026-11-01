"""Reglas compartidas para el puntaje de perfil de técnicos."""

PUNTOS_SALIDA_BUENA = 4
PUNTOS_SALIDA_PRODUCTO = 1
PUNTOS_SALIDA_MALA_RESTA = 1
# Compatibilidad con llamadas anteriores; las garantías ya no descuentan.
PUNTOS_SALIDA_GARANTIA_RESTA = 0

# Se conserva por compatibilidad con el cálculo histórico. Las garantías ahora
# forman parte de las salidas positivas y no se descuentan por separado.
SALIDA_GARANTIA_ESTADOS = ()


# ── Puntos del técnico (perfil, nivel y ranking) ─────────────────────────
# Puntos por cada equipo finalizado según el resultado de la salida. Se le
# acreditan al técnico que reparó. Los resultados que no aparecen valen 0
# (chatarrización, revisión y cortesía).
PUNTOS_POR_ESTADO_SALIDA = {
    'pendiente_retiro': 3,              # Reparado, en espera de retiro
    'retirado': 3,                      # Reparado y retirado por el cliente
    'cliente_no_acepta': 1,             # Cliente no quiso reparar
    'no_reparable': -1,                 # No se pudo reparar
    'garantia': -4,                     # Garantía finalizada
    'garantia_fallos_adicionales': -4,  # Garantía + fallos adicionales
}
PUNTOS_VENTA_PRODUCTO = 1

# Revisión es neutra (0), pero su subcategoría «No se pudo reparar» o
# «Cliente no quiso reparar» cuenta como ese estado. «Equipo de prueba» y
# las revisiones antiguas sin subcategoría siguen en 0.
SUBESTADOS_REVISION_CON_PUNTOS = ('no_reparable', 'cliente_no_acepta')


def estado_para_puntos(estado, subestado_revision=''):
    """Estado con el que se cuentan los puntos de una salida."""
    if estado == 'revision' and subestado_revision in SUBESTADOS_REVISION_CON_PUNTOS:
        return subestado_revision
    return estado


SALIDA_PUNTOS_POSITIVOS = tuple(
    estado for estado, puntos in PUNTOS_POR_ESTADO_SALIDA.items() if puntos > 0
)
SALIDA_PUNTOS_NEGATIVOS = tuple(
    estado for estado, puntos in PUNTOS_POR_ESTADO_SALIDA.items() if puntos < 0
)

# (nivel, puntos desde los que empieza, color)
NIVELES_TECNICO = (
    ('Novato', 0, '#8e8e8e'),
    ('Intermedio', 50, '#cd7f32'),
    ('Avanzado', 100, '#c0c0c0'),
    ('Experto', 500, '#ffd700'),
    ('Maestro', 1000, '#b9f2ff'),
    ('God Tec Econotec', 4000, 'linear-gradient(45deg, #FFD700, #ff8c00)'),
)


def puntos_de_salidas(conteo_por_estado, ventas_producto=0):
    """Suma de puntos de un grupo de salidas ({estado: cantidad}) y ventas.
    Puede ser negativa; el perfil la corta en 0 con calcular_puntaje_perfil."""
    return sum(
        PUNTOS_POR_ESTADO_SALIDA.get(estado, 0) * cantidad
        for estado, cantidad in conteo_por_estado.items()
    ) + ventas_producto * PUNTOS_VENTA_PRODUCTO


def calcular_puntaje_perfil(conteo_por_estado, ventas_producto):
    """Puntaje acumulado del perfil; nunca baja de 0."""
    return max(0, puntos_de_salidas(conteo_por_estado, ventas_producto))


def nivel_por_puntos(total):
    """Nivel, color, puntos donde empieza y puntos del siguiente nivel."""
    for indice, (nivel, desde, color) in enumerate(NIVELES_TECNICO):
        siguiente = NIVELES_TECNICO[indice + 1][1] if indice + 1 < len(NIVELES_TECNICO) else None
        if siguiente is None or total < siguiente:
            return {'nivel': nivel, 'color': color, 'desde': desde, 'proximo': siguiente}
    return None


def calcular_puntaje_gamificacion(
    salidas_buenas,
    salidas_producto,
    salidas_malas,
    salidas_garantia,
):
    """Cálculo anterior (4 / 1 / −1). Ya no se usa en el perfil; se conserva
    por compatibilidad con código antiguo."""
    return max(
        0,
        (salidas_buenas * PUNTOS_SALIDA_BUENA)
        + (salidas_producto * PUNTOS_SALIDA_PRODUCTO)
        - (salidas_malas * PUNTOS_SALIDA_MALA_RESTA)
        - (salidas_garantia * PUNTOS_SALIDA_GARANTIA_RESTA),
    )
