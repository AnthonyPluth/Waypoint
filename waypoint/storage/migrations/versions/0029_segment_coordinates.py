import gzip
import json
import re
import unicodedata
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = '0029'
down_revision = '0027'
branch_labels = None
depends_on = None

STORAGE = Path(__file__).resolve().parent.parent.parent
LOCATED_KINDS = ('hotel', 'car', 'train', 'cruise', 'parking')
BATCH = 500
DOMINANCE = 3

US_STATES = frozenset(
    ['AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'DC', 'FL', 'GA', 'HI', 'ID', 'IL', 'IN', 'IA', 'KS', 'KY', 'LA', 'ME', 'MD', 'MA',
     'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH', 'NJ', 'NM', 'NY', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC', 'SD', 'TN',
     'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY'])
COUNTRIES = {
    'USA': 'US', 'US': 'US', 'U.S.A.': 'US', 'U.S.': 'US', 'UNITED STATES': 'US', 'UNITED STATES OF AMERICA': 'US',
    'CANADA': 'CA', 'UK': 'GB', 'U.K.': 'GB', 'UNITED KINGDOM': 'GB', 'GREAT BRITAIN': 'GB', 'ENGLAND': 'GB',
    'SCOTLAND': 'GB', 'WALES': 'GB', 'NORTHERN IRELAND': 'GB', 'IRELAND': 'IE', 'FRANCE': 'FR', 'GERMANY': 'DE',
    'DEUTSCHLAND': 'DE', 'ITALY': 'IT', 'ITALIA': 'IT', 'SPAIN': 'ES', 'ESPANA': 'ES', 'PORTUGAL': 'PT',
    'NETHERLANDS': 'NL', 'THE NETHERLANDS': 'NL', 'BELGIUM': 'BE', 'SWITZERLAND': 'CH', 'AUSTRIA': 'AT',
    'DENMARK': 'DK', 'NORWAY': 'NO', 'SWEDEN': 'SE', 'FINLAND': 'FI', 'ICELAND': 'IS', 'POLAND': 'PL', 'CZECHIA': 'CZ',
    'CZECH REPUBLIC': 'CZ', 'HUNGARY': 'HU', 'GREECE': 'GR', 'TURKEY': 'TR', 'TURKIYE': 'TR', 'JAPAN': 'JP',
    'SOUTH KOREA': 'KR', 'KOREA': 'KR', 'CHINA': 'CN', 'TAIWAN': 'TW', 'HONG KONG': 'HK', 'SINGAPORE': 'SG',
    'THAILAND': 'TH', 'VIETNAM': 'VN', 'MALAYSIA': 'MY', 'PHILIPPINES': 'PH', 'INDIA': 'IN', 'UNITED ARAB EMIRATES': 'AE',
    'UAE': 'AE', 'ISRAEL': 'IL', 'EGYPT': 'EG', 'SOUTH AFRICA': 'ZA', 'KENYA': 'KE', 'MOROCCO': 'MA',
    'NEW ZEALAND': 'NZ', 'AUSTRALIA': 'AU', 'MEXICO': 'MX', 'BRAZIL': 'BR', 'ARGENTINA': 'AR', 'CHILE': 'CL',
    'PERU': 'PE', 'COLOMBIA': 'CO', 'COSTA RICA': 'CR', 'JAMAICA': 'JM', 'BAHAMAS': 'BS', 'DOMINICAN REPUBLIC': 'DO',
}

US_STATE_ZIP = re.compile(r'\b([A-Z]{2})\.?\s+(\d{5})(?:-\d{4})?\b')
US_ZIP_TOKEN = re.compile(r'(?:[A-Z]{2}\.?\s+)?(\d{5})(?:-\d{4})?')
CA_POSTAL = re.compile(r'\b([A-Z]\d[A-Z])[ -]?\d[A-Z]\d\b')
GB_POSTCODE = re.compile(r'\b([A-Z]{1,2}\d[A-Z\d]?)\s*\d[A-Z]{2}\b')
AIRPORT_CODE = re.compile(r'[A-Za-z]{3}')
AIRPORT_NEAR_WORD = re.compile(r'\b([A-Za-z]{3})\b(?=[^A-Za-z]{0,4}airport\b)|\bairport[^A-Za-z]{0,4}\(?\b([A-Za-z]{3})\b', re.IGNORECASE)
NUMBER_AFFIX = re.compile(r'^\d{4,6}(?:-\d{4})?\s+|\s+\d{4,6}(?:-\d{4})?$')
STATE_TOKEN = re.compile(r'([A-Z]{2})\.?(?:\s+\d{5}(?:-\d{4})?)?')


def _rows(name):
    with gzip.open(STORAGE / name, 'rt', encoding='utf-8') as f:
        return [line.rstrip('\n').split('\t') for line in f if line.strip()]


def _key(name):
    plain = ''.join(c for c in unicodedata.normalize('NFKD', name) if not unicodedata.combining(c))
    return ' '.join(re.sub(r'[^a-z0-9]+', ' ', plain.casefold()).split())


def _data():
    airports = {r[0]: (float(r[5]), float(r[6])) for r in _rows('airports.tsv.gz') if len(r) >= 7 and r[5] and r[6]}
    postal: dict = {}
    cities: dict = {}
    for r in _rows('places.tsv.gz'):
        if r[0] == 'Z' and len(r) >= 5:
            postal[(r[1], r[2])] = (float(r[3]), float(r[4]))
        elif r[0] == 'C' and len(r) >= 6:
            state, _, population = r[5].partition('|')
            cities.setdefault(_key(r[2]), []).append((r[1], state, float(r[3]), float(r[4]), int(population or 0)))
    return airports, postal, cities


def _tokens(text):
    return [t.strip() for t in re.split(r'[,\n;]+', text) if t.strip()]


def _country(tokens):
    names = {_key(n).upper(): c for n, c in COUNTRIES.items()}
    for token in reversed(tokens[-2:]):
        code = names.get(_key(token).upper())
        if code:
            return code
    return None


def _state(tokens):
    for token in tokens:
        found = STATE_TOKEN.fullmatch(token.upper())
        if found and found.group(1) in US_STATES:
            return found.group(1)
    return None


def _postal(postal, text, country, tokens):
    upper = text.upper()
    if country in (None, 'CA'):
        found = CA_POSTAL.search(upper)
        if found and ('CA', found.group(1)) in postal:
            return postal[('CA', found.group(1))] + ('zip',)
    if country in (None, 'GB'):
        found = GB_POSTCODE.search(upper)
        if found and ('GB', found.group(1)) in postal:
            return postal[('GB', found.group(1))] + ('zip',)
    if country in (None, 'US'):
        for state, zip5 in US_STATE_ZIP.findall(upper):
            if state in US_STATES and ('US', zip5) in postal:
                return postal[('US', zip5)] + ('zip',)
        if country == 'US':
            for token in reversed(tokens[1:]):
                found = US_ZIP_TOKEN.fullmatch(token.upper())
                if found and ('US', found.group(1)) in postal:
                    return postal[('US', found.group(1))] + ('zip',)
    return None


def _city(cities, name, country, state):
    found = list(cities.get(_key(name), ()))
    if country:
        found = [c for c in found if c[0] == country]
    if state:
        in_state = [c for c in found if c[1] == state]
        if in_state:
            found = in_state
    if not found:
        return None
    found.sort(key=lambda c: -c[4])
    if len(found) > 1 and country is None and state is None and found[0][4] < DOMINANCE * found[1][4]:
        return None
    return (found[0][2], found[0][3], 'city')


def _city_in(cities, text, country, state):
    tokens = _tokens(text)
    country = country or _country(tokens)
    state = state or (_state(tokens) if country in (None, 'US') else None)
    for token in reversed(tokens):
        name = NUMBER_AFFIX.sub('', token)
        if not name or name[0].isdigit() or STATE_TOKEN.fullmatch(name.upper()) or name.upper() in COUNTRIES:
            continue
        point = _city(cities, name, country, state)
        if point:
            return point
    return None


def _airport(airports, text):
    plain = text.strip()
    if AIRPORT_CODE.fullmatch(plain):
        code = plain
    else:
        code = next((g for m in AIRPORT_NEAR_WORD.finditer(plain) for g in m.groups() if g), None)
    if code and code.upper() in airports:
        return airports[code.upper()] + ('airport',)
    return None


def _locate(data, kind, origin, destination, address):
    airports, postal, cities = data
    ordered = {'hotel': [destination], 'parking': [destination], 'car': [origin, destination], 'train': [destination, origin],
               'cruise': [origin, destination]}.get(kind, [])
    places = [p.strip() for p in ordered if p and p.strip()]
    where = (address or '').strip()
    tokens = _tokens(where)
    country = _country(tokens)
    if where:
        point = _postal(postal, where, country, tokens)
        if point:
            return point
    if kind in ('car', 'train'):
        for place in places:
            point = _airport(airports, place)
            if point:
                return point
    state = _state(tokens) if country in (None, 'US') else None
    for place in places:
        point = _city_in(cities, place, country, state)
        if point:
            return point
    return _city_in(cities, where, country, state) if where else None


def _address(raw):
    try:
        found = json.loads(raw) if raw else {}
    except ValueError:
        return None
    value = found.get('address') if isinstance(found, dict) else None
    return value if isinstance(value, str) else None


def upgrade() -> None:
    op.add_column('segments', sa.Column('latitude', sa.Float()))
    op.add_column('segments', sa.Column('longitude', sa.Float()))
    op.add_column('segments', sa.Column('geo_precision', sa.Text()))
    segments = sa.table('segments', sa.column('id', sa.Integer()), sa.column('kind', sa.Text()), sa.column('origin', sa.Text()),
                        sa.column('destination', sa.Text()), sa.column('details', sa.Text()), sa.column('latitude', sa.Float()),
                        sa.column('longitude', sa.Float()), sa.column('geo_precision', sa.Text()))
    conn = op.get_bind()
    rows = conn.execute(sa.select(segments.c.id, segments.c.kind, segments.c.origin, segments.c.destination, segments.c.details)
                        .where(segments.c.kind.in_(LOCATED_KINDS)).order_by(segments.c.id)).fetchall()
    data = _data() if rows else None
    found = []
    for row_id, kind, origin, destination, details in rows:
        point = _locate(data, kind, origin, destination, _address(details))
        if point is not None:
            found.append({'b_id': row_id, 'b_lat': point[0], 'b_lon': point[1], 'b_precision': point[2]})
    update = (sa.update(segments).where(segments.c.id == sa.bindparam('b_id'))
              .values(latitude=sa.bindparam('b_lat'), longitude=sa.bindparam('b_lon'), geo_precision=sa.bindparam('b_precision')))
    for start in range(0, len(found), BATCH):
        conn.execute(update, found[start:start + BATCH])


def downgrade() -> None:
    op.drop_column('segments', 'geo_precision')
    op.drop_column('segments', 'longitude')
    op.drop_column('segments', 'latitude')
