import gzip
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = '0034'
down_revision = None
branch_labels = None
depends_on = None

HERE = Path(__file__).resolve().parent.parent.parent


def _rows(name: str) -> list[list[str]]:
    with gzip.open(HERE / name, 'rt', encoding='utf-8') as f:
        return [line.rstrip('\n').split('\t') for line in f if line.strip()]


def upgrade() -> None:
    op.create_table('airlines',
    sa.Column('code', sa.Text(), nullable=False),
    sa.Column('icao', sa.Text(), nullable=True),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('country', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('code'),
    )
    op.create_table('airports',
    sa.Column('code', sa.Text(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('city', sa.Text(), nullable=False),
    sa.Column('country', sa.Text(), nullable=False),
    sa.Column('zone', sa.Text(), nullable=False),
    sa.Column('latitude', sa.Float(), nullable=False),
    sa.Column('longitude', sa.Float(), nullable=False),
    sa.PrimaryKeyConstraint('code'),
    )
    op.create_table('auth_pending',
    sa.Column('state', sa.Text(), nullable=False),
    sa.Column('nonce', sa.Text(), nullable=True),
    sa.Column('verifier', sa.Text(), nullable=True),
    sa.Column('next', sa.Text(), nullable=True),
    sa.Column('created', sa.Float(), nullable=True),
    sa.PrimaryKeyConstraint('state'),
    )
    op.create_table('auth_sessions',
    sa.Column('token_hash', sa.Text(), nullable=False),
    sa.Column('sub', sa.Text(), nullable=True),
    sa.Column('email', sa.Text(), nullable=True),
    sa.Column('name', sa.Text(), nullable=True),
    sa.Column('created', sa.Float(), nullable=True),
    sa.Column('expires', sa.Float(), nullable=True),
    sa.Column('id_token', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('token_hash'),
    )
    op.create_table('brand_logos',
    sa.Column('key', sa.Text(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('logo', sa.LargeBinary(), nullable=True),
    sa.Column('logo_type', sa.Text(), nullable=True),
    sa.Column('checked', sa.Text(), nullable=True),
    sa.Column('source', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('key'),
    )
    op.create_table('calendar_feeds',
    sa.Column('owner_sub', sa.Text(), nullable=False),
    sa.Column('key_hash', sa.Text(), nullable=False),
    sa.Column('created', sa.Float(), nullable=False),
    sa.PrimaryKeyConstraint('owner_sub'),
    sa.UniqueConstraint('key_hash', name='uq_calendar_feeds_key_hash'),
    )
    op.create_table('flight_status',
    sa.Column('flight_number', sa.Text(), nullable=False),
    sa.Column('date', sa.Text(), nullable=False),
    sa.Column('state', sa.Text(), nullable=False),
    sa.Column('origin', sa.Text(), nullable=True),
    sa.Column('destination', sa.Text(), nullable=True),
    sa.Column('dep_scheduled', sa.Text(), nullable=True),
    sa.Column('dep_estimated', sa.Text(), nullable=True),
    sa.Column('dep_actual', sa.Text(), nullable=True),
    sa.Column('dep_zone', sa.Text(), nullable=True),
    sa.Column('dep_terminal', sa.Text(), nullable=True),
    sa.Column('dep_gate', sa.Text(), nullable=True),
    sa.Column('arr_scheduled', sa.Text(), nullable=True),
    sa.Column('arr_estimated', sa.Text(), nullable=True),
    sa.Column('arr_actual', sa.Text(), nullable=True),
    sa.Column('arr_zone', sa.Text(), nullable=True),
    sa.Column('arr_terminal', sa.Text(), nullable=True),
    sa.Column('arr_gate', sa.Text(), nullable=True),
    sa.Column('fetched_at', sa.Float(), nullable=False),
    sa.Column('attempted_at', sa.Float(), nullable=True),
    sa.PrimaryKeyConstraint('flight_number', 'date'),
    )
    op.create_table('mailbox_pending',
    sa.Column('state', sa.Text(), nullable=False),
    sa.Column('owner_sub', sa.Text(), nullable=False),
    sa.Column('verifier', sa.Text(), nullable=False),
    sa.Column('created', sa.Float(), nullable=False),
    sa.PrimaryKeyConstraint('state'),
    )
    op.create_table('mailboxes',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('owner_sub', sa.Text(), nullable=False),
    sa.Column('address', sa.Text(), nullable=False),
    sa.Column('token', sa.Text(), nullable=False),
    sa.Column('history_id', sa.Text(), nullable=True),
    sa.Column('last_scan', sa.Float(), nullable=True),
    sa.Column('status', sa.Text(), nullable=False),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('created', sa.Float(), nullable=True),
    sa.Column('scan_error', sa.Text(), nullable=True),
    sa.Column('share_review', sa.Boolean(), server_default=sa.false(), nullable=False),
    sa.Column('scan_summary', sa.Text(), nullable=True),
    sa.Column('scan_labels', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('owner_sub', 'address', name='uq_mailboxes_owner_address'),
    )
    op.create_table('oauth_clients',
    sa.Column('id', sa.Text(), nullable=False),
    sa.Column('name', sa.Text(), nullable=True),
    sa.Column('redirect_uris', sa.Text(), nullable=False),
    sa.Column('auth_method', sa.Text(), nullable=False),
    sa.Column('secret_hash', sa.Text(), nullable=True),
    sa.Column('kind', sa.Text(), server_default=sa.text("'dcr'"), nullable=False),
    sa.Column('metadata_url', sa.Text(), nullable=True),
    sa.Column('created', sa.Float(), nullable=False),
    sa.Column('last_used', sa.Float(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    )
    op.create_table('oauth_consents',
    sa.Column('token_hash', sa.Text(), nullable=False),
    sa.Column('params', sa.Text(), nullable=False),
    sa.Column('created', sa.Float(), nullable=False),
    sa.PrimaryKeyConstraint('token_hash'),
    )
    op.create_table('push_devices',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('owner_sub', sa.Text(), nullable=False),
    sa.Column('endpoint', sa.Text(), nullable=False),
    sa.Column('p256dh', sa.Text(), nullable=False),
    sa.Column('auth', sa.Text(), nullable=False),
    sa.Column('created', sa.Float(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('endpoint', name='uq_push_devices_endpoint'),
    )
    op.create_index('ix_push_devices_owner', 'push_devices', ['owner_sub'], unique=False)
    op.create_table('reminder_prefs',
    sa.Column('owner_sub', sa.Text(), nullable=False),
    sa.Column('check_in', sa.Boolean(), nullable=False),
    sa.Column('day_of', sa.Boolean(), nullable=False),
    sa.PrimaryKeyConstraint('owner_sub'),
    )
    op.create_table('reminders_sent',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('owner_sub', sa.Text(), nullable=False),
    sa.Column('kind', sa.Text(), nullable=False),
    sa.Column('ref', sa.Text(), nullable=False),
    sa.Column('sent', sa.Float(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('owner_sub', 'kind', 'ref', name='uq_reminders_sent_owner_kind_ref'),
    )
    op.create_table('settings',
    sa.Column('key', sa.Text(), nullable=False),
    sa.Column('value', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('key')
    )
    op.create_table('users',
    sa.Column('sub', sa.Text(), nullable=False),
    sa.Column('email', sa.Text(), nullable=True),
    sa.Column('name', sa.Text(), nullable=True),
    sa.Column('first_name', sa.Text(), nullable=True),
    sa.Column('last_seen', sa.Float(), nullable=True),
    sa.PrimaryKeyConstraint('sub'),
    )
    op.create_table('ignored_senders',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('mailbox_id', sa.Integer(), nullable=False),
    sa.Column('domain', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['mailbox_id'], ['mailboxes.id'], name='fk_ignored_senders_mailbox_id', ondelete='CASCADE', initially='IMMEDIATE', deferrable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('mailbox_id', 'domain', name='uq_ignored_senders_mailbox_domain'),
    )
    op.create_table('oauth_grants',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('client_id', sa.Text(), nullable=False),
    sa.Column('sub', sa.Text(), nullable=True),
    sa.Column('email', sa.Text(), nullable=True),
    sa.Column('scope', sa.Text(), nullable=False),
    sa.Column('resource', sa.Text(), nullable=False),
    sa.Column('created', sa.Float(), nullable=False),
    sa.Column('last_used', sa.Float(), nullable=True),
    sa.Column('revoked', sa.Float(), nullable=True),
    sa.Column('revoked_reason', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['client_id'], ['oauth_clients.id'], name='fk_oauth_grants_client_id', ondelete='CASCADE', initially='IMMEDIATE', deferrable=True),
    sa.PrimaryKeyConstraint('id'),
    sqlite_autoincrement=True
    )
    op.create_index('ix_oauth_grants_client_id', 'oauth_grants', ['client_id'], unique=False)
    op.create_table('people',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('display_name', sa.Text(), nullable=False),
    sa.Column('first_name', sa.Text(), nullable=True),
    sa.Column('legal_name', sa.Text(), nullable=True),
    sa.Column('aliases', sa.Text(), nullable=True),
    sa.Column('user_sub', sa.Text(), nullable=True),
    sa.Column('links', sa.Text(), nullable=True),
    sa.Column('claim_dismissed', sa.Boolean(), nullable=True),
    sa.ForeignKeyConstraint(['user_sub'], ['users.sub'], name='fk_people_user_sub', ondelete='SET NULL', initially='IMMEDIATE', deferrable=True),
    sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ux_people_user_sub', 'people', ['user_sub'], unique=True)
    op.create_table('review_items',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('mailbox_id', sa.Integer(), nullable=False),
    sa.Column('message_id', sa.Text(), nullable=False),
    sa.Column('sender_domain', sa.Text(), nullable=False),
    sa.Column('received', sa.Text(), nullable=True),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('created', sa.Float(), nullable=False),
    sa.Column('suggestion', sa.Text(), nullable=True),
    sa.Column('suggestion_error', sa.Text(), nullable=True),
    sa.Column('matches', sa.Text(), nullable=True),
    sa.Column('gap', sa.Text(), nullable=True),
    sa.Column('reference', sa.Text(), nullable=True),
    sa.Column('auto_state', sa.Text(), nullable=True),
    sa.Column('auto_tries', sa.Integer(), server_default='0', nullable=False),
    sa.ForeignKeyConstraint(['mailbox_id'], ['mailboxes.id'], name='fk_review_items_mailbox_id', ondelete='CASCADE', initially='IMMEDIATE', deferrable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('mailbox_id', 'message_id', name='uq_review_items_mailbox_message'),
    )
    op.create_table('stored_messages',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('mailbox_id', sa.Integer(), nullable=False),
    sa.Column('message_id', sa.Text(), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('subject', sa.Text(), nullable=True),
    sa.Column('created', sa.Float(), nullable=False),
    sa.ForeignKeyConstraint(['mailbox_id'], ['mailboxes.id'], name='fk_stored_messages_mailbox_id', ondelete='CASCADE', initially='IMMEDIATE', deferrable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('mailbox_id', 'message_id', name='uq_stored_messages_mailbox_message'),
    )
    op.create_table('trusted_senders',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('mailbox_id', sa.Integer(), nullable=False),
    sa.Column('domain', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['mailbox_id'], ['mailboxes.id'], name='fk_trusted_senders_mailbox_id', ondelete='CASCADE', initially='IMMEDIATE', deferrable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('mailbox_id', 'domain', name='uq_trusted_senders_mailbox_domain'),
    )
    op.create_table('loyalty_ids',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('person_id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.Text(), nullable=False),
    sa.Column('program', sa.Text(), nullable=False),
    sa.Column('number', sa.Text(), nullable=False),
    sa.Column('expiry', sa.Text(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['person_id'], ['people.id'], name='fk_loyalty_ids_person_id', ondelete='CASCADE', initially='IMMEDIATE', deferrable=True),
    sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_loyalty_ids_person_id', 'loyalty_ids', ['person_id'], unique=False)
    op.create_table('oauth_codes',
    sa.Column('code_hash', sa.Text(), nullable=False),
    sa.Column('client_id', sa.Text(), nullable=False),
    sa.Column('grant_id', sa.Integer(), nullable=False),
    sa.Column('redirect_uri', sa.Text(), nullable=False),
    sa.Column('code_challenge', sa.Text(), nullable=False),
    sa.Column('resource', sa.Text(), nullable=False),
    sa.Column('created', sa.Float(), nullable=False),
    sa.Column('used', sa.Float(), nullable=True),
    sa.ForeignKeyConstraint(['client_id'], ['oauth_clients.id'], name='fk_oauth_codes_client_id', ondelete='CASCADE', initially='IMMEDIATE', deferrable=True),
    sa.ForeignKeyConstraint(['grant_id'], ['oauth_grants.id'], name='fk_oauth_codes_grant_id', ondelete='CASCADE', initially='IMMEDIATE', deferrable=True),
    sa.PrimaryKeyConstraint('code_hash'),
    )
    op.create_index('ix_oauth_codes_grant_id', 'oauth_codes', ['grant_id'], unique=False)
    op.create_table('oauth_tokens',
    sa.Column('token_hash', sa.Text(), nullable=False),
    sa.Column('kind', sa.Text(), nullable=False),
    sa.Column('grant_id', sa.Integer(), nullable=False),
    sa.Column('created', sa.Float(), nullable=False),
    sa.Column('expires', sa.Float(), nullable=False),
    sa.Column('consumed', sa.Float(), nullable=True),
    sa.Column('replaced_by', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['grant_id'], ['oauth_grants.id'], name='fk_oauth_tokens_grant_id', ondelete='CASCADE', initially='IMMEDIATE', deferrable=True),
    sa.PrimaryKeyConstraint('token_hash'),
    )
    op.create_index('ix_oauth_tokens_grant_id', 'oauth_tokens', ['grant_id'], unique=False)
    op.create_table('trips',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('start_date', sa.Text(), nullable=True),
    sa.Column('end_date', sa.Text(), nullable=True),
    sa.Column('destination', sa.Text(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('auto', sa.Boolean(), nullable=False),
    sa.Column('booked_by', sa.Integer(), nullable=True),
    sa.Column('destination_manual', sa.Boolean(), server_default=sa.false(), nullable=False),
    sa.Column('done_at', sa.Float(), nullable=True),
    sa.ForeignKeyConstraint(['booked_by'], ['people.id'], name='fk_trips_booked_by', ondelete='SET NULL', initially='IMMEDIATE', deferrable=True),
    sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_trips_booked_by', 'trips', ['booked_by'], unique=False)
    op.create_table('segments',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('trip_id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.Text(), nullable=False),
    sa.Column('status', sa.Text(), nullable=False),
    sa.Column('confirmation', sa.Text(), nullable=True),
    sa.Column('provider', sa.Text(), nullable=True),
    sa.Column('start_local', sa.Text(), nullable=False),
    sa.Column('start_zone', sa.Text(), nullable=False),
    sa.Column('end_local', sa.Text(), nullable=False),
    sa.Column('end_zone', sa.Text(), nullable=False),
    sa.Column('origin', sa.Text(), nullable=True),
    sa.Column('destination', sa.Text(), nullable=True),
    sa.Column('details', sa.Text(), nullable=True),
    sa.Column('manage_url', sa.Text(), nullable=True),
    sa.Column('source', sa.Text(), nullable=False),
    sa.Column('booked_by', sa.Integer(), nullable=True),
    sa.Column('locked_fields', sa.Text(), nullable=True),
    sa.Column('check_times', sa.Boolean(), server_default=sa.false(), nullable=False),
    sa.Column('latitude', sa.Float(), nullable=True),
    sa.Column('longitude', sa.Float(), nullable=True),
    sa.Column('geo_precision', sa.Text(), nullable=True),
    sa.Column('travelers_from_trip', sa.Boolean(), server_default=sa.false(), nullable=False),
    sa.Column('price_minor', sa.Integer(), nullable=True),
    sa.Column('price_currency', sa.Text(), nullable=True),
    sa.Column('price_source', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['booked_by'], ['people.id'], name='fk_segments_booked_by', ondelete='SET NULL', initially='IMMEDIATE', deferrable=True),
    sa.ForeignKeyConstraint(['trip_id'], ['trips.id'], name='fk_segments_trip_id', ondelete='CASCADE', initially='IMMEDIATE', deferrable=True),
    sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_segments_booked_by', 'segments', ['booked_by'], unique=False)
    op.create_index('ix_segments_trip_id', 'segments', ['trip_id'], unique=False)
    op.create_table('trip_people',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('trip_id', sa.Integer(), nullable=False),
    sa.Column('person_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['person_id'], ['people.id'], name='fk_trip_people_person_id', ondelete='CASCADE', initially='IMMEDIATE', deferrable=True),
    sa.ForeignKeyConstraint(['trip_id'], ['trips.id'], name='fk_trip_people_trip_id', ondelete='CASCADE', initially='IMMEDIATE', deferrable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('trip_id', 'person_id', name='uq_trip_people_trip_person'),
    )
    op.create_index('ix_trip_people_person_id', 'trip_people', ['person_id'], unique=False)
    op.create_table('scanned_messages',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('mailbox_id', sa.Integer(), nullable=False),
    sa.Column('message_id', sa.Text(), nullable=False),
    sa.Column('outcome', sa.Text(), nullable=False),
    sa.Column('scanned', sa.Float(), nullable=False),
    sa.Column('sender_domain', sa.Text(), nullable=True),
    sa.Column('segment_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['mailbox_id'], ['mailboxes.id'], name='fk_scanned_messages_mailbox_id', ondelete='CASCADE', initially='IMMEDIATE', deferrable=True),
    sa.ForeignKeyConstraint(['segment_id'], ['segments.id'], name='fk_scanned_messages_segment_id', ondelete='SET NULL', initially='IMMEDIATE', deferrable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('mailbox_id', 'message_id', name='uq_scanned_messages_mailbox_message'),
    )
    op.create_table('segment_codes',
    sa.Column('segment_id', sa.Integer(), nullable=False),
    sa.Column('mailbox_id', sa.Integer(), nullable=False),
    sa.Column('content', sa.Text(), nullable=True),
    sa.Column('day', sa.Text(), nullable=True),
    sa.Column('created', sa.Float(), nullable=False),
    sa.ForeignKeyConstraint(['mailbox_id'], ['mailboxes.id'], name='fk_segment_codes_mailbox_id', ondelete='CASCADE', initially='IMMEDIATE', deferrable=True),
    sa.ForeignKeyConstraint(['segment_id'], ['segments.id'], name='fk_segment_codes_segment_id', ondelete='CASCADE', initially='IMMEDIATE', deferrable=True),
    sa.PrimaryKeyConstraint('segment_id'),
    )
    op.create_table('segment_messages',
    sa.Column('segment_id', sa.Integer(), nullable=False),
    sa.Column('stored_message_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['segment_id'], ['segments.id'], name='fk_segment_messages_segment_id', ondelete='CASCADE', initially='IMMEDIATE', deferrable=True),
    sa.ForeignKeyConstraint(['stored_message_id'], ['stored_messages.id'], name='fk_segment_messages_stored_message_id', ondelete='CASCADE', initially='IMMEDIATE', deferrable=True),
    sa.PrimaryKeyConstraint('segment_id', 'stored_message_id'),
    )
    op.create_table('segment_ports',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('segment_id', sa.Integer(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('zone', sa.Text(), nullable=False),
    sa.Column('arrive_local', sa.Text(), nullable=True),
    sa.Column('depart_local', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['segment_id'], ['segments.id'], name='fk_segment_ports_segment_id', ondelete='CASCADE', initially='IMMEDIATE', deferrable=True),
    sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_segment_ports_segment_id', 'segment_ports', ['segment_id'], unique=False)
    op.create_table('segment_recipients',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('segment_id', sa.Integer(), nullable=False),
    sa.Column('person_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['person_id'], ['people.id'], name='fk_segment_recipients_person_id', ondelete='CASCADE', initially='IMMEDIATE', deferrable=True),
    sa.ForeignKeyConstraint(['segment_id'], ['segments.id'], name='fk_segment_recipients_segment_id', ondelete='CASCADE', initially='IMMEDIATE', deferrable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('segment_id', 'person_id', name='uq_segment_recipients_segment_person'),
    )
    op.create_index('ix_segment_recipients_person_id', 'segment_recipients', ['person_id'], unique=False)
    op.create_table('segment_travelers',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('segment_id', sa.Integer(), nullable=False),
    sa.Column('person_id', sa.Integer(), nullable=True),
    sa.Column('name', sa.Text(), nullable=True),
    sa.Column('seat', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['person_id'], ['people.id'], name='fk_segment_travelers_person_id', ondelete='CASCADE', initially='IMMEDIATE', deferrable=True),
    sa.ForeignKeyConstraint(['segment_id'], ['segments.id'], name='fk_segment_travelers_segment_id', ondelete='CASCADE', initially='IMMEDIATE', deferrable=True),
    sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_segment_travelers_person_id', 'segment_travelers', ['person_id'], unique=False)
    op.create_index('ix_segment_travelers_segment_id', 'segment_travelers', ['segment_id'], unique=False)

    airports = sa.table('airports', sa.column('code'), sa.column('name'), sa.column('city'), sa.column('country'), sa.column('zone'),
                        sa.column('latitude'), sa.column('longitude'))
    op.bulk_insert(airports, [{'code': c, 'name': n, 'city': city, 'country': country, 'zone': z,
                               'latitude': float(lat), 'longitude': float(lon)}
                              for c, n, city, country, z, lat, lon in _rows('airports.tsv.gz')])
    airlines = sa.table('airlines', sa.column('code'), sa.column('icao'), sa.column('name'), sa.column('country'))
    op.bulk_insert(airlines, [{'code': code, 'icao': icao or None, 'name': name, 'country': country or None}
                              for code, icao, name, country in _rows('airlines.tsv.gz')])


def downgrade() -> None:
    op.drop_table('segment_travelers')
    op.drop_table('segment_recipients')
    op.drop_table('segment_ports')
    op.drop_table('segment_messages')
    op.drop_table('segment_codes')
    op.drop_table('scanned_messages')
    op.drop_table('trip_people')
    op.drop_table('segments')
    op.drop_table('trips')
    op.drop_table('oauth_tokens')
    op.drop_table('oauth_codes')
    op.drop_table('loyalty_ids')
    op.drop_table('trusted_senders')
    op.drop_table('stored_messages')
    op.drop_table('review_items')
    op.drop_table('people')
    op.drop_table('oauth_grants')
    op.drop_table('ignored_senders')
    op.drop_table('users')
    op.drop_table('settings')
    op.drop_table('reminders_sent')
    op.drop_table('reminder_prefs')
    op.drop_table('push_devices')
    op.drop_table('oauth_consents')
    op.drop_table('oauth_clients')
    op.drop_table('mailboxes')
    op.drop_table('mailbox_pending')
    op.drop_table('flight_status')
    op.drop_table('calendar_feeds')
    op.drop_table('brand_logos')
    op.drop_table('auth_sessions')
    op.drop_table('auth_pending')
    op.drop_table('airports')
    op.drop_table('airlines')
