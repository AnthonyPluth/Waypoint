from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from . import words

Kind = Literal["car", "train", "cruise"]
Table = dict[str, tuple[str, ...]]


@dataclass(frozen=True)
class Language:
    name: str
    shared: Table
    car: Table
    train: Table
    cruise: Table
    about: dict[str, tuple[str, ...]]
    same: tuple[str, ...]
    policy: tuple[str, ...]
    weekdays: tuple[str, ...]


ENGLISH = Language(
    "English",
    {"confirmation": (*words.ENGLISH.confirmation, "confirmation", "reservation", "booking")},
    {
        "start": ("pick-up date and time", "pick-up date/time", "pickup date and time", "pickup date/time", "pick up date and time",
                  "collection date and time", "pick-up", "pick up", "pickup", "collection"),
        "start_place": ("pick-up location", "pick up location", "pickup location", "pick-up branch", "pickup branch", "pick-up station",
                        "pick-up point", "pick-up address", "collection location", "collection branch", "collect from"),
        "start_date": ("pick-up date", "pick up date", "pickup date", "collection date"),
        "start_time": ("pick-up time", "pick up time", "pickup time", "collection time"),
        "end": ("drop-off date and time", "drop-off date/time", "dropoff date and time", "drop off date and time", "return date and time",
                "drop-off", "drop off", "dropoff", "returning", "return"),
        "end_place": ("drop-off location", "drop off location", "dropoff location", "return location", "return branch", "drop-off branch",
                      "drop-off station", "drop-off point", "return to"),
        "end_date": ("drop-off date", "drop off date", "dropoff date", "return date"),
        "end_time": ("drop-off time", "drop off time", "dropoff time", "return time"),
        "location": ("pick-up and drop-off location", "pick-up & drop-off location", "pick-up and return location", "pick-up & return location",
                     "pick-up/return location", "pickup and return location", "rental location", "location"),
        "provider": ("rental company", "car rental company", "rental agency", "car hire company", "supplier", "vendor", "company", "provider"),
        "vehicle": ("car type", "car class", "car group", "car category", "vehicle type", "vehicle", "car"),
    },
    {
        "start": ("departure date and time", "departure date/time", "departure", "departs", "depart", "departing", "leaves", "leaving"),
        "end": ("arrival date and time", "arrival date/time", "arrival", "arrives", "arrive", "arriving"),
        "start_place": ("departure station", "departing from", "departs from", "depart from", "boarding station", "origin station", "origin", "from"),
        "end_place": ("arrival station", "arriving at", "arrives at", "arrive at", "destination station", "destination", "to"),
        "start_date": ("departure date", "date of departure", "travel date", "journey date"),
        "start_time": ("departure time", "time of departure"),
        "end_date": ("arrival date", "date of arrival"),
        "end_time": ("arrival time", "time of arrival"),
        "number": ("train number", "train no.", "train no", "train #", "service number", "trip number", "train", "service"),
        "provider": ("train operator", "operator", "carrier", "railway", "rail company", "company"),
    },
    {
        "start": ("embarkation date and time", "embarkation", "embark", "departure", "departs"),
        "end": ("disembarkation date and time", "disembarkation", "disembark", "debarkation", "debark", "arrival", "arrives", "returns"),
        "start_place": ("embarkation port", "port of embarkation", "embark port", "embarkation city", "departure port", "port of departure",
                        "sailing from", "sails from", "departs from", "departing from", "home port"),
        "end_place": ("disembarkation port", "port of disembarkation", "disembark port", "debarkation port", "arrival port", "port of arrival",
                      "return port", "port of return", "returns to", "arrives at", "arriving at"),
        "start_date": ("embarkation date", "embark date", "sailing date", "sail date", "departure date", "date of departure"),
        "end_date": ("disembarkation date", "disembark date", "debarkation date", "arrival date", "return date", "date of arrival"),
        "start_time": ("embarkation time", "boarding time", "departure time"),
        "end_time": ("disembarkation time", "arrival time"),
        "ship": ("ship name", "vessel name", "ship", "vessel"),
        "provider": ("cruise line", "cruise company", "line"),
    },
    {
        "car": ("car", "rental", "vehicle", "car hire"),
        "train": ("train", "railway", "rail", "railroad"),
        "cruise": ("cruise", "ship", "vessel", "embarkation", "sailing"),
        "flight": ("flight", "airline", "airlines"),
    },
    ("same as pick-up", "same as pickup", "same as pick up", "same as above", "same location", "same place", "same"),
    ("policy", "policies", "terms", "conditions", "fee", "fees", "deposit", "late return"),
    ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "mon", "tue", "tues", "wed", "thu", "thur", "thurs", "fri", "sat", "sun"),
)
FRENCH = Language(
    "French",
    {"confirmation": words.FRENCH.confirmation},
    {
        "start": ("date et heure de prise en charge", "date et heure de retrait", "prise en charge", "retrait", "enlèvement"),
        "start_place": ("lieu de prise en charge", "lieu de retrait", "agence de prise en charge", "agence de départ", "point de retrait"),
        "start_date": ("date de prise en charge", "date de retrait"),
        "start_time": ("heure de prise en charge", "heure de retrait"),
        "end": ("date et heure de restitution", "date et heure de retour", "restitution", "retour"),
        "end_place": ("lieu de restitution", "lieu de retour", "agence de restitution", "agence de retour"),
        "end_date": ("date de restitution", "date de retour"),
        "end_time": ("heure de restitution", "heure de retour"),
        "location": ("lieu de prise en charge et de restitution", "lieu de retrait et de restitution", "agence de location"),
        "provider": ("société de location", "compagnie de location", "loueur", "fournisseur"),
        "vehicle": ("catégorie du véhicule", "type de véhicule", "catégorie", "véhicule", "voiture"),
    },
    {
        "start": ("date et heure de départ", "départ", "depart"),
        "end": ("date et heure d'arrivée", "arrivée", "arrivee"),
        "start_place": ("gare de départ", "gare d'origine", "départ de", "origine", "de"),
        "end_place": ("gare d'arrivée", "gare de destination", "arrivée à", "destination", "vers", "à"),
        "start_date": ("date de départ", "date du voyage"),
        "start_time": ("heure de départ",),
        "end_date": ("date d'arrivée",),
        "end_time": ("heure d'arrivée",),
        "number": ("numéro de train", "n° de train", "train"),
        "provider": ("transporteur", "opérateur", "compagnie"),
    },
    {
        "start": ("date et heure d'embarquement", "embarquement"),
        "end": ("date et heure de débarquement", "débarquement", "debarquement"),
        "start_place": ("port d'embarquement", "port de départ", "port d'attache"),
        "end_place": ("port de débarquement", "port de debarquement", "port d'arrivée", "port de retour"),
        "start_date": ("date d'embarquement", "date de départ"),
        "end_date": ("date de débarquement", "date de retour", "date d'arrivée"),
        "start_time": ("heure d'embarquement",),
        "end_time": ("heure de débarquement",),
        "ship": ("nom du navire", "navire", "bateau"),
        "provider": ("compagnie de croisière", "croisiériste", "compagnie"),
    },
    {
        "car": ("voiture", "location de voiture", "véhicule", "loueur"),
        "train": ("train", "ferroviaire", "gare"),
        "cruise": ("croisière", "croisiere", "navire", "paquebot", "embarquement"),
        "flight": ("vol", "compagnie aérienne"),
    },
    ("identique à la prise en charge", "même lieu", "meme lieu", "identique"),
    ("politique", "conditions", "frais", "caution"),
    ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche", "lun", "mar", "mer", "jeu", "ven", "sam", "dim"),
)
GERMAN = Language(
    "German",
    {"confirmation": words.GERMAN.confirmation},
    {
        "start": ("abholung",),
        "start_place": ("abholort", "abholstation", "abholfiliale", "abholadresse"),
        "start_date": ("abholdatum", "datum der abholung"),
        "start_time": ("abholzeit", "uhrzeit der abholung"),
        "end": ("rückgabe", "rueckgabe"),
        "end_place": ("rückgabeort", "rückgabestation", "rückgabefiliale"),
        "end_date": ("rückgabedatum", "datum der rückgabe"),
        "end_time": ("rückgabezeit", "uhrzeit der rückgabe"),
        "location": ("abhol- und rückgabeort", "abhol-/rückgabeort", "mietstation"),
        "provider": ("autovermietung", "mietwagenfirma", "vermieter", "mietfirma", "anbieter"),
        "vehicle": ("fahrzeugkategorie", "fahrzeugklasse", "fahrzeugtyp", "fahrzeug", "wagentyp"),
    },
    {
        "start": ("abfahrt", "abreise"),
        "end": ("ankunft",),
        "start_place": ("abfahrtsbahnhof", "abfahrtsort", "startbahnhof", "von"),
        "end_place": ("ankunftsbahnhof", "zielbahnhof", "ankunftsort", "nach", "ziel"),
        "start_date": ("abfahrtsdatum", "reisedatum", "datum der abfahrt"),
        "start_time": ("abfahrtszeit", "uhrzeit der abfahrt"),
        "end_date": ("ankunftsdatum", "datum der ankunft"),
        "end_time": ("ankunftszeit",),
        "number": ("zugnummer", "zug"),
        "provider": ("verkehrsunternehmen", "bahnunternehmen", "betreiber", "anbieter"),
    },
    {
        "start": ("einschiffung",),
        "end": ("ausschiffung",),
        "start_place": ("einschiffungshafen", "abfahrtshafen", "starthafen", "hafen der einschiffung"),
        "end_place": ("ausschiffungshafen", "zielhafen", "ankunftshafen", "endhafen"),
        "start_date": ("einschiffungsdatum", "abreisedatum", "abfahrtsdatum"),
        "end_date": ("ausschiffungsdatum", "rückreisedatum", "ankunftsdatum"),
        "start_time": ("einschiffungszeit",),
        "end_time": ("ausschiffungszeit",),
        "ship": ("schiffsname", "schiff"),
        "provider": ("kreuzfahrtgesellschaft", "kreuzfahrtlinie", "reederei"),
    },
    {
        "car": ("mietwagen", "leihwagen", "autovermietung", "fahrzeug"),
        "train": ("zug", "bahn", "bahnhof", "zugverbindung"),
        "cruise": ("kreuzfahrt", "schiff", "reederei", "einschiffung"),
        "flight": ("flug", "fluggesellschaft"),
    },
    ("gleich wie abholung", "gleicher ort", "wie abholort", "gleich"),
    ("richtlinie", "bedingungen", "gebühr", "gebuehr", "kaution"),
    ("montag", "dienstag", "mittwoch", "donnerstag", "freitag", "samstag", "sonntag", "mo", "di", "mi", "do", "fr", "sa", "so"),
)
SPANISH = Language(
    "Spanish",
    {"confirmation": words.SPANISH.confirmation},
    {
        "start": ("fecha y hora de recogida", "recogida"),
        "start_place": ("lugar de recogida", "oficina de recogida", "punto de recogida", "sucursal de recogida"),
        "start_date": ("fecha de recogida",),
        "start_time": ("hora de recogida",),
        "end": ("fecha y hora de devolución", "fecha y hora de devolucion", "devolución", "devolucion"),
        "end_place": ("lugar de devolución", "lugar de devolucion", "oficina de devolución", "punto de devolución"),
        "end_date": ("fecha de devolución", "fecha de devolucion"),
        "end_time": ("hora de devolución", "hora de devolucion"),
        "location": ("lugar de recogida y devolución", "lugar de recogida y devolucion", "oficina de alquiler"),
        "provider": ("empresa de alquiler", "compañía de alquiler", "proveedor", "arrendador"),
        "vehicle": ("tipo de vehículo", "categoría", "categoria", "vehículo", "coche"),
    },
    {
        "start": ("fecha y hora de salida", "salida"),
        "end": ("fecha y hora de llegada", "llegada"),
        "start_place": ("estación de origen", "estacion de origen", "origen", "desde"),
        "end_place": ("estación de destino", "estacion de destino", "destino", "hasta"),
        "start_date": ("fecha de salida",),
        "start_time": ("hora de salida",),
        "end_date": ("fecha de llegada",),
        "end_time": ("hora de llegada",),
        "number": ("número de tren", "numero de tren", "tren"),
        "provider": ("empresa ferroviaria", "operador", "compañía"),
    },
    {
        "start": ("fecha y hora de embarque", "embarque"),
        "end": ("fecha y hora de desembarque", "desembarque"),
        "start_place": ("puerto de embarque", "puerto de salida"),
        "end_place": ("puerto de desembarque", "puerto de llegada"),
        "start_date": ("fecha de embarque", "fecha de salida"),
        "end_date": ("fecha de desembarque", "fecha de llegada", "fecha de regreso"),
        "start_time": ("hora de embarque",),
        "end_time": ("hora de desembarque",),
        "ship": ("nombre del barco", "nombre del buque", "barco", "buque"),
        "provider": ("línea de cruceros", "linea de cruceros", "compañía de cruceros", "naviera"),
    },
    {
        "car": ("coche de alquiler", "alquiler de coche", "alquiler de vehículos", "vehículo", "coche", "rent a car"),
        "train": ("tren", "ferrocarril", "ferroviaria"),
        "cruise": ("crucero", "barco", "buque", "naviera", "embarque"),
        "flight": ("vuelo", "aerolínea", "aerolinea"),
    },
    ("mismo lugar", "igual que la recogida", "mismo"),
    ("política", "politica", "condiciones", "tarifa", "fianza"),
    ("lunes", "martes", "miércoles", "miercoles", "jueves", "viernes", "sábado", "sabado", "domingo", "lun", "mar", "mié", "jue", "vie", "sáb", "dom"),
)
JAPANESE = Language(
    "Japanese",
    {"confirmation": words.JAPANESE.confirmation},
    {
        "start": ("受取日時", "貸出日時", "受取", "貸出"),
        "start_place": ("受取場所", "受取店舗", "貸出場所", "貸出店舗", "出発店舗"),
        "start_date": ("受取日", "貸出日"),
        "start_time": ("受取時間", "受取時刻", "貸出時間"),
        "end": ("返却日時", "返却"),
        "end_place": ("返却場所", "返却店舗"),
        "end_date": ("返却日",),
        "end_time": ("返却時間", "返却時刻"),
        "location": ("受取・返却場所", "受取/返却場所", "営業所"),
        "provider": ("レンタカー会社", "貸出会社", "会社名"),
        "vehicle": ("車両タイプ", "車両クラス", "車種"),
    },
    {
        "start": ("出発日時", "出発", "発車"),
        "end": ("到着日時", "到着"),
        "start_place": ("出発駅", "乗車駅", "発駅"),
        "end_place": ("到着駅", "降車駅", "着駅"),
        "start_date": ("出発日", "乗車日"),
        "start_time": ("出発時刻", "出発時間", "発車時刻"),
        "end_date": ("到着日",),
        "end_time": ("到着時刻", "到着時間"),
        "number": ("列車番号", "列車名", "列車"),
        "provider": ("運行会社", "鉄道会社", "会社名"),
    },
    {
        "start": ("乗船日時", "乗船"),
        "end": ("下船日時", "下船"),
        "start_place": ("乗船港", "出港地", "出発港"),
        "end_place": ("下船港", "入港地", "到着港"),
        "start_date": ("乗船日", "出港日"),
        "end_date": ("下船日", "入港日"),
        "start_time": ("乗船時間", "乗船時刻", "出港時間"),
        "end_time": ("下船時間", "下船時刻"),
        "ship": ("客船名", "船名", "客船"),
        "provider": ("クルーズ会社", "クルーズライン", "船会社"),
    },
    {
        "car": ("レンタカー", "車両"),
        "train": ("列車", "新幹線", "鉄道", "電車"),
        "cruise": ("クルーズ", "客船", "乗船"),
        "flight": ("フライト", "航空"),
    },
    ("同じ", "同上"),
    ("規約", "ポリシー", "手数料", "条件"),
    ("月曜日", "火曜日", "水曜日", "木曜日", "金曜日", "土曜日", "日曜日", "月曜", "火曜", "水曜", "木曜", "金曜", "土曜", "日曜"),
)
LANGUAGES = (ENGLISH, FRENCH, GERMAN, SPANISH, JAPANESE)


def _whole(options: tuple[str, ...]) -> re.Pattern[str]:
    ordered = sorted(dict.fromkeys(options), key=len, reverse=True)
    latin = [re.escape(w) for w in ordered if w[0].isascii() or (w[0].isalpha() and ord(w[0]) < 0x250)]
    other = [re.escape(w) for w in ordered if re.escape(w) not in latin]
    parts = [rf"(?<![^\W\d_])(?:{'|'.join(latin)})(?![^\W\d_])"] if latin else []
    return re.compile("|".join(parts + other), re.IGNORECASE)


def table(kind: Kind) -> Table:
    merged: dict[str, list[str]] = {}
    seen: set[str] = set()
    for lang in LANGUAGES:
        for key, options in (*lang.shared.items(), *getattr(lang, kind).items()):
            for option in options:
                if option.lower() not in seen:
                    seen.add(option.lower())
                    merged.setdefault(key, []).append(option)
    return {key: tuple(options) for key, options in merged.items()}


def about(kind: str) -> re.Pattern[str]:
    return _whole(tuple(w for lang in LANGUAGES for w in lang.about[kind]))


POLICY = _whole(tuple(w for lang in LANGUAGES for w in lang.policy))
SAME = _whole(tuple(w for lang in LANGUAGES for w in lang.same))
WEEKDAYS = _whole(tuple(w for lang in LANGUAGES for w in lang.weekdays))
