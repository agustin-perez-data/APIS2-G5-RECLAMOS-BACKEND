"""Seed corpus used to train the claims classifier.

This is the Sprint 1 bootstrap dataset: claims written the way a neighbour
would write them, labelled by hand. The plan is to replace and grow it with
real claims coming from the app — the ones an operator reclassifies manually
are the most valuable examples, since those are exactly the ones the model got
wrong.

Retraining needs no special step: add rows here and the model trains itself
when the process starts.
"""

from __future__ import annotations

from app.domain.enums import CategoriaReclamo

CORPUS: list[tuple[str, CategoriaReclamo]] = [
    # --- ALUMBRADO -----------------------------------------------------------
    ("La luminaria de la esquina esta apagada hace dos semanas", CategoriaReclamo.ALUMBRADO),
    ("Foco quemado en el poste de luz frente a mi casa", CategoriaReclamo.ALUMBRADO),
    ("Toda la cuadra quedo a oscuras, no anda el alumbrado publico", CategoriaReclamo.ALUMBRADO),
    ("La luz de la plaza titila toda la noche y no ilumina", CategoriaReclamo.ALUMBRADO),
    ("Poste de alumbrado sin lampara desde el temporal", CategoriaReclamo.ALUMBRADO),
    ("Reflector del playon deportivo quemado", CategoriaReclamo.ALUMBRADO),
    ("Falta iluminacion en el pasaje, esta muy oscuro de noche", CategoriaReclamo.ALUMBRADO),
    # --- BACHES --------------------------------------------------------------
    ("Hay un bache enorme en el medio de la calzada", CategoriaReclamo.BACHES),
    ("Pozo profundo en la calle que rompe los autos", CategoriaReclamo.BACHES),
    ("El asfalto esta todo roto y hundido en la bocacalle", CategoriaReclamo.BACHES),
    ("Baches en la avenida despues de la obra de gas", CategoriaReclamo.BACHES),
    ("La vereda esta levantada y rota, es intransitable", CategoriaReclamo.BACHES),
    ("Hundimiento del pavimento frente al colegio", CategoriaReclamo.BACHES),
    ("Calle de tierra intransitable, necesita reparacion y nivelado", CategoriaReclamo.BACHES),
    # --- RESIDUOS ------------------------------------------------------------
    ("El contenedor de basura esta desbordado hace dias", CategoriaReclamo.RESIDUOS),
    ("No pasa el camion recolector por mi cuadra", CategoriaReclamo.RESIDUOS),
    ("Basural a cielo abierto en el terreno baldio", CategoriaReclamo.RESIDUOS),
    ("Bolsas de residuos tiradas en la esquina, olor insoportable", CategoriaReclamo.RESIDUOS),
    ("Contenedor roto y volcado sobre la vereda", CategoriaReclamo.RESIDUOS),
    ("Escombros abandonados en la calle hace un mes", CategoriaReclamo.RESIDUOS),
    ("No hay recoleccion de reciclables en el barrio", CategoriaReclamo.RESIDUOS),
    # --- ARBOLADO ------------------------------------------------------------
    ("Rama de arbol a punto de caerse sobre los cables", CategoriaReclamo.ARBOLADO),
    ("Arbol caido bloqueando la calle despues de la tormenta", CategoriaReclamo.ARBOLADO),
    ("Necesito poda del arbol de la vereda, tapa la luminaria", CategoriaReclamo.ARBOLADO),
    ("Las raices del arbol levantaron la vereda", CategoriaReclamo.ARBOLADO),
    ("Arbol seco que puede caer sobre la casa", CategoriaReclamo.ARBOLADO),
    ("Pasto y yuyos altisimos en el cantero central", CategoriaReclamo.ARBOLADO),
    ("Solicito plantacion de arboles en la plaza del barrio", CategoriaReclamo.ARBOLADO),
    # --- AGUA_CLOACAS --------------------------------------------------------
    ("Perdida de agua en la vereda, sale agua del caño hace dias", CategoriaReclamo.AGUA_CLOACAS),
    ("Cloaca desbordada, corre liquido con olor por la calle", CategoriaReclamo.AGUA_CLOACAS),
    ("No tenemos presion de agua en todo el edificio", CategoriaReclamo.AGUA_CLOACAS),
    ("Se tapo el sumidero y se inunda la esquina cuando llueve", CategoriaReclamo.AGUA_CLOACAS),
    ("Rotura de caño maestro, hay una laguna en la calle", CategoriaReclamo.AGUA_CLOACAS),
    ("Desague pluvial obstruido con basura", CategoriaReclamo.AGUA_CLOACAS),
    ("Agua turbia y con olor en la canilla", CategoriaReclamo.AGUA_CLOACAS),
    # --- TRANSITO ------------------------------------------------------------
    ("El semaforo de la avenida no funciona", CategoriaReclamo.TRANSITO),
    ("Autos estacionados sobre la senda peatonal todos los dias", CategoriaReclamo.TRANSITO),
    ("Falta senalizacion y cartel de pare en el cruce", CategoriaReclamo.TRANSITO),
    ("Camiones circulando por calle prohibida a alta velocidad", CategoriaReclamo.TRANSITO),
    ("El lomo de burro esta destruido y nadie baja la velocidad", CategoriaReclamo.TRANSITO),
    ("Vehiculo abandonado hace meses ocupando lugar", CategoriaReclamo.TRANSITO),
    ("La senda peatonal esta borrada frente a la escuela", CategoriaReclamo.TRANSITO),
    # --- RUIDOS --------------------------------------------------------------
    ("Ruidos molestos del boliche hasta las seis de la manana", CategoriaReclamo.RUIDOS),
    ("El taller mecanico trabaja de madrugada con amoladora", CategoriaReclamo.RUIDOS),
    ("Fiestas con musica a todo volumen todos los fines de semana", CategoriaReclamo.RUIDOS),
    ("Obra en construccion rompiendo pared antes de las siete", CategoriaReclamo.RUIDOS),
    ("Alarma de un auto sonando hace horas sin parar", CategoriaReclamo.RUIDOS),
    ("Bar con parlantes en la vereda, no se puede dormir", CategoriaReclamo.RUIDOS),
    ("Contaminacion sonora por escapes libres de motos", CategoriaReclamo.RUIDOS),
    # --- ESPACIOS_PUBLICOS ---------------------------------------------------
    ("Los juegos de la plaza estan rotos y oxidados", CategoriaReclamo.ESPACIOS_PUBLICOS),
    (
        "La hamaca del parque esta rota, es peligrosa para los chicos",
        CategoriaReclamo.ESPACIOS_PUBLICOS,
    ),
    ("Bancos de la plaza vandalizados y llenos de grafitis", CategoriaReclamo.ESPACIOS_PUBLICOS),
    ("El baño del polideportivo esta clausurado hace meses", CategoriaReclamo.ESPACIOS_PUBLICOS),
    ("Falta mantenimiento en la cancha del club municipal", CategoriaReclamo.ESPACIOS_PUBLICOS),
    ("La fuente de la plaza no funciona y esta sucia", CategoriaReclamo.ESPACIOS_PUBLICOS),
    ("Rejas del parque rotas, cualquiera entra de noche", CategoriaReclamo.ESPACIOS_PUBLICOS),
    # --- SEGURIDAD -----------------------------------------------------------
    ("Robos constantes en la parada del colectivo", CategoriaReclamo.SEGURIDAD),
    ("Camara de seguridad municipal fuera de servicio", CategoriaReclamo.SEGURIDAD),
    ("Grupo de personas amenazando a los vecinos en la esquina", CategoriaReclamo.SEGURIDAD),
    ("Casa tomada y usurpada en la cuadra", CategoriaReclamo.SEGURIDAD),
    ("Pedimos mas patrullaje policial, hubo varios arrebatos", CategoriaReclamo.SEGURIDAD),
    ("Venta de drogas en la plaza a la vista de todos", CategoriaReclamo.SEGURIDAD),
    (
        "Cable de electricidad caido en la vereda, riesgo de electrocucion",
        CategoriaReclamo.SEGURIDAD,
    ),
    # --- OTROS ---------------------------------------------------------------
    ("Consulta por el tramite de habilitacion comercial", CategoriaReclamo.OTROS),
    ("Quiero saber el estado de mi expediente municipal", CategoriaReclamo.OTROS),
    ("No me llego la boleta de la tasa municipal", CategoriaReclamo.OTROS),
    ("Mala atencion en la oficina de rentas", CategoriaReclamo.OTROS),
    ("Solicito informacion sobre los talleres culturales", CategoriaReclamo.OTROS),
    ("Problema con la carga de la tarjeta ciudadana", CategoriaReclamo.OTROS),
    ("Sugerencia para mejorar la aplicacion del municipio", CategoriaReclamo.OTROS),
]


# --- Urgency lexicon ---------------------------------------------------------
# Priority is not decided by the Bayesian classifier but by an explicit rule:
# it is a public-policy decision, so it has to stay auditable and tunable by the
# city rather than learned from biased historical data.
TERMINOS_CRITICOS: tuple[str, ...] = (
    "fuga",
    "gas",
    "incendio",
    "fuego",
    "electrocucion",
    "derrumbe",
    "colapso",
    "herido",
    "heridos",
    "cable_caido",
    "fuga_gas",
    "riesgo_vida",
    "explosion",
)

TERMINOS_ALTOS: tuple[str, ...] = (
    "peligro",
    "peligroso",
    "riesgo",
    "urgente",
    "inundacion",
    "inundado",
    "caido",
    "caida",
    "roto",
    "rota",
    "desbordado",
    "amenaza",
    "escuela",
    "hospital",
    "chicos",
    "menores",
    "discapacidad",
)
