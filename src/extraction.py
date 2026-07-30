import json
import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

# Snapshot of the CATEGORIA taxonomy from the client's own monitoring DB
# (BD Monitoreo - Radio Monterrey.xlsx), so extraction output lines up with
# their existing schema instead of inventing a new one.
CATEGORIAS = [
    "ABARROTES / TIENDAS*", "ACEITES Y LUBRICANTES AUTOMOTRICES", "AFORES",
    "AGENCIAS DE VIAJES*", "AIRES ACONDICIONADOS / CLIMAS*", "ALIMENTOS / PRODUCTOS / CADENAS",
    "ALIMENTOS PARA ANIMALES", "ALIMENTOS Y COMPLEMENTOS REDUCTIVOS", "ALMACENES DEPARTAMENTALES*",
    "ALMACENES Y TIENDAS DE ROPA*", "ANDAMIOS TUBULARES*", "ASEGURADORAS",
    "ASESORIAS PROFESIONALES / CONSULTORES", "ATUNES / SARDINAS", "AUDITORIOS / EVENTOS",
    "AUTOMOVILES / MARCAS", "AUTOPISTAS DE CONCESION FEDERAL", "AUTOS / AGENCIAS Y DISTRIBUIDORES",
    "AUTOSERVICIOS*", "AVISOS DE OCASION*", "BAILES Y EVENTOS POPULARES", "BANCOS",
    "BANOS / MUEBLES Y ACCESORIOS", "BARES / MUSICA EN VIVO", "BOTANAS",
    "CADENAS TELEVISORAS / TELEVISION", "CAFETERIAS", "CALZADO / MARCAS / VENTA POR CATALOGO",
    "CAMARA DE DIPUTADOS*", "CAMARA DE SENADORES*", "CAMARAS EMPRESARIALES*",
    "CAMPANAS DE PARTIDOS POLITICOS", "CARNICERIAS*", "CARTON / TIENDAS / FABRICAS*",
    "CASAS DE BOLSA", "CASAS FUNERALES / SERVICIOS", "CASINOS / CENTROS DE APUESTAS Y JUEGOS",
    "CEMENTO / MARCAS*", "CENTROS COMERCIALES*", "CENTROS DE COMERCIO INTERNACIONAL",
    "CENTROS EMPRESARIALES*", "CERVEZAS", "CHOCOLATE EN POLVO / LIQUIDO / CASERO",
    "CINES / AUTOCINEMAS", "CLINICAS / CONSULTORIOS", "CLINICAS ODONTOLOGICAS / SERVICIOS",
    "CLOSETS / ROPEROS", "CLUBES DE PRECIOS", "CLUBES DEPORTIVOS / RECREATIVOS",
    "COLCHONERIAS / TIENDAS DE COLCHONES*", "COLCHONES / MARCAS", "COSMETICOS / MARCAS",
    "CURSOS DE ESPECIALIZACION / ACTUALIZACION", "CURSOS DE SUPERACION PERSONAL",
    "DECORACION DE INTERIORES", "DEPOSITOS / EXPENDIOS DE BEBIDAS*", "DETERGENTES",
    "DIRECTORIOS TURISTICOS", "DISQUERAS / COMPANIAS / CASAS*",
    "DISTRIBUIDORES DE EQUIPO CELULAR / SERVICIOS", "ENFRIADORES / CALENTADORES DE AGUA*",
    "ENTIDADES PARAESTATALES", "EQUIPOS Y SISTEMAS GPS", "ESPECIAL EN RADIO Y TV*",
    "ESTADIOS / ARENAS DEPORTIVAS", "EXPOSICIONES / SALAS / CENTROS", "FARMACIAS*",
    "FERIAS POPULARES", "FERRETERIAS Y TIENDAS DE MAT. CONSTRUCCION", "FONDOS DE INVERSION",
    "FRACCIONAMIENTOS/CONJUNTOS HABITACIONALES*", "FUMIGACIONES / SERVICIO*",
    "FUNERARIAS / PARQUES FUNERARIOS", "GAS NATURAL Y LP / INDUSTRIAL Y SERVICIO*",
    "GASOLINERAS*", "GIMNASIOS / SPA*", "GOBIERNO ESTATAL / CAMPANAS*",
    "GOBIERNO FEDERAL / CAMPANAS*", "GOBIERNO MUNICIPAL / CAMPANAS*",
    "GRUAS / TRACTOCAMIONES / SERVICIO", "GRUPOS RADIOFONICOS / EMISORAS",
    "HAMBURGUESAS / CADENAS", "HELADOS / NIEVES", "HERRAMIENTAS INDUSTRIALES Y DOMESTICAS*",
    "HOTELES / TIEMPOS COMPARTIDOS*", "IMPERMEABILIZANTES / SILICONES*",
    "INMOBILIARIAS / BIENES RAICES*", "INSTITUCIONES DE BENEFICENCIA*",
    "INSTITUTOS ELECTORALES*", "INTERNET / PROVEEDORES DE SERVICIO",
    "JOYERIA / PLATERIA / ORFEBRERIA*", "LINEAS AEREAS*", "LUZ Y SONIDO",
    "MEDICAMENTOS EN GENERAL", "MEDICOS ESPECIALISTAS", "MENSAJERIA Y PAQUETERIA",
    "MERMELADAS", "MOTOCICLETAS / AGENCIAS / DISTRIBUIDORAS", "MUEBLERIAS PARA EL HOGAR*",
    "OFTALMOLOGOS / OCULISTAS", "ORGANIZACIONES FINANCIERAS", "PAN / LINEA DE PRODUCTOS*",
    "PAPELERIAS*", "PARQUES DE DIVERSIONES / CENTROS", "PERIODICOS",
    "PILAS Y BATERIAS / MARCAS", "PINTURAS Y RECUBRIMIENTOS*", "PISOS Y AZULEJOS",
    "PIZZAS / PIZZERIAS", "PODER JUDICIAL DE LA FEDERACION*", "POLLO FRITO / ASADO",
    "PORTALES INFORMATIVOS Y DE NOTICIAS", "PROCURADURIA FEDERAL DEL CONSUMIDOR",
    "PROFESIONALES / SERVICIOS", "PROGRAMA RADIOFONICO*", "PROGRAMA TELEVISIVO*",
    "RECARGA DE CARTUCHOS TONER Y TINTA", "REFACCIONARIAS / TIENDAS DE AUTOPARTES",
    "REFRESCOS", "RENTA DE AUTOS Y AUTOBUSES", "RESTAURANTES",
    "SALONES DE BELLEZA / ESTETICAS*", "SALSAS", "SECRETARIAS DE ESTADO*",
    "SERVICIOS DE STREAMING DE AUDIO Y VIDEO", "SERVICIOS FINANCIEROS",
    "SISTEMAS Y PROGRAMAS DE COMPUTO*", "SOFIPO - SOC FIN POPULAR", "SORTEOS*",
    "TARJETAS DE CREDITO", "TEATROS", "TELEFONIA MOVIL / CELULAR",
    "TELEVISION SATELITAL", "TIENDAS DE CONVENIENCIA*", "TIENDAS DE IMPORTACION*",
    "TRANSPORTE FORANEO*", "TRIPLE PLAY / TELEF / TV CABLE / INTERNET",
    "UNIVERSIDADES / CENTROS DE ESTUDIOS PROFESIONALES", "VALES DE DESPENSA / BONOS",
    "VINOS Y LICORES / EXPENDIOS*", "ZAPATERIAS / TIENDAS*",
]

SYSTEM_PROMPT = f"""You are helping a media monitoring company that tracks commercials on radio and TV.
You will be given the transcript of a short audio clip suspected to be a commercial, and must extract it
into the same fields the client already uses in their monitoring database, so the output can be merged
directly into their existing records.

Extract:
- "categoria": the single best-matching category for this clip, chosen from this exact list (copy the
  string exactly as written, including any trailing "*"): {json.dumps(CATEGORIAS, ensure_ascii=False)}
  If truly nothing on the list fits (e.g. a station jingle with no commercial content), use null.
- "anunciante": the company/organization behind the ad (e.g. "GRUPO H.E.B.", "GENERAL MOTORS"). If the
  transcript only gives a consumer-facing brand and the parent company isn't identifiable from it, reuse
  the brand name here.
- "marca": the full brand/product name as said in the transcript (e.g. "H.E.B. TIENDA DE AUTOSERVICIO").
- "marca_corto": a short version of the brand name (e.g. "H.E.B.", "CHEVROLET").
- "version": a short tag summarizing the spot's key promotional content (offer, price, tagline) in the
  style "<MARCA_CORTO> / <short highlight>", e.g. "COPPEL / 40% DESCUENTO LINEA BLANCA".
- "vigencia": the offer's validity/expiration date, ONLY if a specific date is explicitly stated in the
  transcript (e.g. "válido hasta el 19 de julio" -> "2026-07-19"). Otherwise null. Do not guess or infer
  a date that isn't spoken.
- "keywords": brand names, product names, and other commercial-relevant entities mentioned.

Write all output text in Spanish (brand/product names should stay as mentioned in the transcript, but
any descriptive wording you generate must be in Spanish).

If the transcript is empty, too short, or too garbled to make sense of, set every field to null (empty
list for "keywords") instead of inventing a brand or category. Do not invent brands that are not actually
mentioned.

Respond with JSON only, matching this shape:
{{"categoria": "...", "anunciante": "...", "marca": "...", "marca_corto": "...", "version": "...",
"vigencia": "...", "keywords": ["..."]}}
"""

_EMPTY_RESULT = {
    "categoria": None,
    "anunciante": None,
    "marca": None,
    "marca_corto": None,
    "version": None,
    "vigencia": None,
    "keywords": [],
}


def extract_spot_details(transcript: str) -> dict:
    if not transcript or not transcript.strip():
        return dict(_EMPTY_RESULT)

    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": transcript},
        ],
        response_format={"type": "json_object"},
    )

    content = response.choices[0].message.content
    data = json.loads(content or "{}")

    return {
        "categoria": data.get("categoria"),
        "anunciante": data.get("anunciante"),
        "marca": data.get("marca"),
        "marca_corto": data.get("marca_corto"),
        "version": data.get("version"),
        "vigencia": data.get("vigencia"),
        "keywords": data.get("keywords", []),
    }
