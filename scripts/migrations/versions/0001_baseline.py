"""
The baseline: every table as it was when the migrations moved to Alembic.
A database older than this is first brought here by
scripts/history/migrate_legacy.sh, which scripts/migrate.sh runs for it.
"""

import sqlalchemy as sa
from alembic import op

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('email_verifications',
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('sent_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('email'),
    sa.UniqueConstraint('token_hash')
    )
    op.create_table('locales',
    sa.Column('code', sa.String(length=10), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('script', sa.String(length=50), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('native', sa.String(length=100), server_default='', nullable=False),
    sa.PrimaryKeyConstraint('code'),
    sa.UniqueConstraint('name')
    )
    op.create_table('library_works',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('title', sa.String(length=500), nullable=False),
    sa.Column('creator', sa.String(length=500), nullable=False),
    sa.Column('year', sa.Integer(), nullable=True),
    sa.Column('isbn', sa.String(length=20), server_default='', nullable=False),
    sa.Column('openlibrary_id', sa.String(length=20), server_default='', nullable=False),
    sa.Column('imdb_id', sa.String(length=20), nullable=False),
    sa.Column('tmdb_id', sa.Integer(), nullable=True),
    sa.Column('rotten_tomatoes_id', sa.String(length=200), nullable=False),
    sa.Column('goodreads_id', sa.String(length=20), nullable=False),
    sa.Column('simania_id', sa.String(length=20), nullable=False),
    sa.Column('title_locale', sa.String(length=10), server_default='en', nullable=False),
    sa.Column('original_locale', sa.String(length=10), nullable=True),
    sa.ForeignKeyConstraint(['original_locale'], ['locales.code'], ),
    sa.ForeignKeyConstraint(['title_locale'], ['locales.code'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('kind', 'title', 'creator', 'year', name='uq_work_identity')
    )
    op.create_table('users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('picture', sa.String(length=1000), nullable=False),
    sa.Column('role', sa.String(length=20), server_default='user', nullable=False),
    sa.Column('locale', sa.String(length=10), server_default='en', nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('last_login', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['locale'], ['locales.code'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('email')
    )
    op.create_table('disabled_checks',
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('check_name', sa.String(length=100), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', 'check_name')
    )
    op.create_table('images',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('owner_id', sa.Integer(), nullable=False),
    sa.Column('filename', sa.String(length=200), nullable=False),
    sa.Column('content_type', sa.String(length=100), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('data', sa.LargeBinary(), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('owner_id', 'filename', name='uq_image_filename')
    )
    with op.batch_alter_table('images', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_images_owner_id'), ['owner_id'], unique=False)

    op.create_table('library_work_titles',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('work_id', sa.Integer(), nullable=False),
    sa.Column('locale', sa.String(length=10), nullable=False),
    sa.Column('title', sa.String(length=500), nullable=False),
    sa.ForeignKeyConstraint(['locale'], ['locales.code'], ),
    sa.ForeignKeyConstraint(['work_id'], ['library_works.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('work_id', 'locale', name='uq_work_title_locale')
    )
    with op.batch_alter_table('library_work_titles', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_library_work_titles_work_id'), ['work_id'], unique=False)

    op.create_table('logins',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('subject', sa.String(length=400), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('picture', sa.String(length=1000), nullable=False),
    sa.Column('password_hash', sa.String(length=300), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('last_login', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('subject')
    )
    with op.batch_alter_table('logins', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_logins_user_id'), ['user_id'], unique=False)

    op.create_table('organization_types',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('owner_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('owner_id', 'name', name='uq_organization_type_name')
    )
    with op.batch_alter_table('organization_types', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_organization_types_owner_id'), ['owner_id'], unique=False)

    op.create_table('people',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('owner_id', sa.Integer(), nullable=False),
    sa.Column('is_self', sa.Boolean(), server_default=sa.text('0'), nullable=False),
    sa.Column('honorific', sa.String(length=50), server_default='', nullable=False),
    sa.Column('first_name', sa.String(length=200), nullable=False),
    sa.Column('middle_name', sa.String(length=200), server_default='', nullable=False),
    sa.Column('surname', sa.String(length=200), server_default='', nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('people', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_people_owner_id'), ['owner_id'], unique=False)

    op.create_table('person_organization_types',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('owner_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('owner_id', 'name', name='uq_person_organization_type_name')
    )
    with op.batch_alter_table('person_organization_types', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_person_organization_types_owner_id'), ['owner_id'], unique=False)

    op.create_table('person_relation_types',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('owner_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('inverse', sa.String(length=100), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('owner_id', 'name', name='uq_person_relation_type_name')
    )
    with op.batch_alter_table('person_relation_types', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_person_relation_types_owner_id'), ['owner_id'], unique=False)

    op.create_table('relation_types',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('owner_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('owner_id', 'name', name='uq_relation_type_name')
    )
    with op.batch_alter_table('relation_types', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_relation_types_owner_id'), ['owner_id'], unique=False)

    op.create_table('countries',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('owner_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('remark', sa.Text(), nullable=False),
    sa.Column('image_id', sa.Integer(), nullable=True),
    sa.Column('image_source', sa.String(length=1000), server_default='', nullable=False),
    sa.Column('image_license', sa.String(length=100), server_default='', nullable=False),
    sa.Column('image_author', sa.String(length=300), server_default='', nullable=False),
    sa.Column('latitude', sa.Double(), nullable=True),
    sa.Column('longitude', sa.Double(), nullable=True),
    sa.ForeignKeyConstraint(['image_id'], ['images.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('owner_id', 'name', name='uq_country_name')
    )
    with op.batch_alter_table('countries', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_countries_owner_id'), ['owner_id'], unique=False)

    op.create_table('devices',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('owner_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('image_id', sa.Integer(), nullable=True),
    sa.Column('image_source', sa.String(length=1000), server_default='', nullable=False),
    sa.Column('image_license', sa.String(length=100), server_default='', nullable=False),
    sa.Column('image_author', sa.String(length=300), server_default='', nullable=False),
    sa.ForeignKeyConstraint(['image_id'], ['images.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('owner_id', 'name', name='uq_device_name')
    )
    with op.batch_alter_table('devices', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_devices_owner_id'), ['owner_id'], unique=False)

    op.create_table('groups',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('owner_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=300), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('website', sa.String(length=1000), nullable=False),
    sa.Column('image_id', sa.Integer(), nullable=True),
    sa.Column('image_source', sa.String(length=1000), server_default='', nullable=False),
    sa.Column('image_license', sa.String(length=100), server_default='', nullable=False),
    sa.Column('image_author', sa.String(length=300), server_default='', nullable=False),
    sa.ForeignKeyConstraint(['image_id'], ['images.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('owner_id', 'name', name='uq_group_name')
    )
    with op.batch_alter_table('groups', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_groups_owner_id'), ['owner_id'], unique=False)

    op.create_table('library_entries',
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('work_id', sa.Integer(), nullable=False),
    sa.Column('notes', sa.Text(), nullable=False),
    sa.Column('not_owned', sa.Boolean(), server_default=sa.text('0'), nullable=False),
    sa.Column('image_id', sa.Integer(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['image_id'], ['images.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['work_id'], ['library_works.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', 'work_id')
    )
    op.create_table('person_names',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('person_id', sa.Integer(), nullable=False),
    sa.Column('locale', sa.String(length=10), nullable=False),
    sa.Column('name', sa.String(length=500), nullable=False),
    sa.Column('honorific', sa.String(length=50), server_default='', nullable=False),
    sa.Column('first_name', sa.String(length=200), server_default='', nullable=False),
    sa.Column('middle_name', sa.String(length=200), server_default='', nullable=False),
    sa.Column('surname', sa.String(length=200), server_default='', nullable=False),
    sa.ForeignKeyConstraint(['locale'], ['locales.code'], ),
    sa.ForeignKeyConstraint(['person_id'], ['people.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('person_id', 'locale', name='uq_person_name_locale')
    )
    with op.batch_alter_table('person_names', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_person_names_person_id'), ['person_id'], unique=False)

    op.create_table('person_photos',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('person_id', sa.Integer(), nullable=False),
    sa.Column('image_id', sa.Integer(), nullable=False),
    sa.Column('position', sa.Integer(), server_default='0', nullable=False),
    sa.Column('image_source', sa.String(length=1000), server_default='', nullable=False),
    sa.Column('image_license', sa.String(length=100), server_default='', nullable=False),
    sa.Column('image_author', sa.String(length=300), server_default='', nullable=False),
    sa.ForeignKeyConstraint(['image_id'], ['images.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['person_id'], ['people.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('person_photos', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_person_photos_person_id'), ['person_id'], unique=False)

    op.create_table('person_relations',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('person_id', sa.Integer(), nullable=False),
    sa.Column('relation_type_id', sa.Integer(), nullable=False),
    sa.Column('other_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['other_id'], ['people.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['person_id'], ['people.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['relation_type_id'], ['person_relation_types.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('person_id', 'relation_type_id', 'other_id', name='uq_person_relation')
    )
    with op.batch_alter_table('person_relations', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_person_relations_other_id'), ['other_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_person_relations_person_id'), ['person_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_person_relations_relation_type_id'), ['relation_type_id'], unique=False)

    op.create_table('person_types',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('owner_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('image_id', sa.Integer(), nullable=True),
    sa.Column('image_source', sa.String(length=1000), server_default='', nullable=False),
    sa.Column('image_license', sa.String(length=100), server_default='', nullable=False),
    sa.Column('image_author', sa.String(length=300), server_default='', nullable=False),
    sa.ForeignKeyConstraint(['image_id'], ['images.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('owner_id', 'name', name='uq_person_type_name')
    )
    with op.batch_alter_table('person_types', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_person_types_owner_id'), ['owner_id'], unique=False)

    op.create_table('audio_courses',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('owner_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=500), nullable=False),
    sa.Column('rating', sa.Integer(), nullable=True),
    sa.Column('review', sa.Text(), nullable=False),
    sa.Column('device_id', sa.Integer(), nullable=True),
    sa.Column('listened_at', sa.String(length=100), nullable=False),
    sa.Column('started_utcz', sa.DateTime(), nullable=True),
    sa.Column('ended_utcz', sa.DateTime(), nullable=True),
    sa.Column('progress', sa.String(length=20), nullable=False),
    sa.Column('great_courses_id', sa.Integer(), nullable=True),
    sa.Column('great_courses_slug', sa.String(length=300), nullable=False),
    sa.Column('audible_asin', sa.String(length=20), nullable=False),
    sa.Column('link', sa.String(length=1000), nullable=False),
    sa.Column('image_id', sa.Integer(), nullable=True),
    sa.Column('date_utcz', sa.DateTime(), nullable=True),
    sa.Column('date_ymd', sa.Date(), nullable=True),
    sa.Column('date_my', sa.String(length=7), nullable=False),
    sa.Column('date_y', sa.Integer(), nullable=True),
    sa.Column('date_timezone', sa.String(length=64), nullable=False),
    sa.CheckConstraint('rating IS NULL OR (rating >= 1 AND rating <= 10)', name='ck_audio_course_rating_range'),
    sa.ForeignKeyConstraint(['device_id'], ['devices.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['image_id'], ['images.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('audio_courses', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_audio_courses_owner_id'), ['owner_id'], unique=False)

    op.create_table('cities',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('owner_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('region', sa.String(length=100), nullable=False),
    sa.Column('country_id', sa.Integer(), nullable=True),
    sa.Column('remark', sa.Text(), nullable=False),
    sa.Column('image_id', sa.Integer(), nullable=True),
    sa.Column('image_source', sa.String(length=1000), server_default='', nullable=False),
    sa.Column('image_license', sa.String(length=100), server_default='', nullable=False),
    sa.Column('image_author', sa.String(length=300), server_default='', nullable=False),
    sa.Column('latitude', sa.Double(), nullable=True),
    sa.Column('longitude', sa.Double(), nullable=True),
    sa.ForeignKeyConstraint(['country_id'], ['countries.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['image_id'], ['images.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('owner_id', 'name', 'region', 'country_id', name='uq_city_name')
    )
    with op.batch_alter_table('cities', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_cities_country_id'), ['country_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_cities_owner_id'), ['owner_id'], unique=False)

    op.create_table('group_members',
    sa.Column('group_id', sa.Integer(), nullable=False),
    sa.Column('person_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['group_id'], ['groups.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['person_id'], ['people.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('group_id', 'person_id')
    )
    op.create_table('library_covers',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('work_id', sa.Integer(), nullable=False),
    sa.Column('image_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['image_id'], ['images.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id', 'work_id'], ['library_entries.user_id', 'library_entries.work_id'], name='fk_library_covers_entry', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('library_covers', schema=None) as batch_op:
        batch_op.create_index('ix_library_covers_entry', ['user_id', 'work_id'], unique=False)

    op.create_table('library_entry_authors',
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('work_id', sa.Integer(), nullable=False),
    sa.Column('person_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['person_id'], ['people.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id', 'work_id'], ['library_entries.user_id', 'library_entries.work_id'], name='fk_library_entry_authors_entry', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', 'work_id', 'person_id')
    )
    op.create_table('library_ownings',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('work_id', sa.Integer(), nullable=False),
    sa.Column('locale', sa.String(length=10), nullable=False),
    sa.ForeignKeyConstraint(['locale'], ['locales.code'], ),
    sa.ForeignKeyConstraint(['user_id', 'work_id'], ['library_entries.user_id', 'library_entries.work_id'], name='fk_library_ownings_entry', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'work_id', 'locale', name='uq_library_owning_locale')
    )
    op.create_table('library_reads',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('work_id', sa.Integer(), nullable=False),
    sa.Column('read_on', sa.Date(), nullable=True),
    sa.Column('locale', sa.String(length=10), nullable=True),
    sa.Column('status', sa.String(length=20), server_default='done', nullable=False),
    sa.Column('rating', sa.Integer(), nullable=True),
    sa.Column('started_on', sa.Date(), nullable=True),
    sa.Column('review', sa.Text(), server_default='', nullable=False),
    sa.CheckConstraint('rating IS NULL OR (rating >= 1 AND rating <= 10)', name='ck_read_rating_range'),
    sa.ForeignKeyConstraint(['locale'], ['locales.code'], ),
    sa.ForeignKeyConstraint(['user_id', 'work_id'], ['library_entries.user_id', 'library_entries.work_id'], name='fk_library_reads_entry', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('library_reads', schema=None) as batch_op:
        batch_op.create_index('ix_library_reads_entry', ['user_id', 'work_id'], unique=False)

    op.create_table('person_type_links',
    sa.Column('person_id', sa.Integer(), nullable=False),
    sa.Column('person_type_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['person_id'], ['people.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['person_type_id'], ['person_types.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('person_id', 'person_type_id')
    )
    op.create_table('youtube_videos',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('owner_id', sa.Integer(), nullable=False),
    sa.Column('youtube_id', sa.String(length=20), nullable=False),
    sa.Column('name', sa.String(length=500), nullable=False),
    sa.Column('rating', sa.Integer(), nullable=True),
    sa.Column('review', sa.Text(), nullable=False),
    sa.Column('device_id', sa.Integer(), nullable=True),
    sa.Column('watched_at', sa.String(length=100), nullable=False),
    sa.Column('channel', sa.String(length=200), nullable=False),
    sa.Column('category', sa.String(length=100), nullable=False),
    sa.Column('duration', sa.Integer(), nullable=True),
    sa.Column('uploaded', sa.Date(), nullable=True),
    sa.Column('views', sa.BigInteger(), nullable=True),
    sa.Column('unavailable', sa.Boolean(), server_default=sa.text('0'), nullable=False),
    sa.Column('date_utcz', sa.DateTime(), nullable=True),
    sa.Column('date_ymd', sa.Date(), nullable=True),
    sa.Column('date_my', sa.String(length=7), nullable=False),
    sa.Column('date_y', sa.Integer(), nullable=True),
    sa.Column('date_timezone', sa.String(length=64), nullable=False),
    sa.CheckConstraint('rating IS NULL OR (rating >= 1 AND rating <= 10)', name='ck_youtube_video_rating_range'),
    sa.ForeignKeyConstraint(['device_id'], ['devices.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('owner_id', 'youtube_id', name='uq_youtube_video_id')
    )
    with op.batch_alter_table('youtube_videos', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_youtube_videos_owner_id'), ['owner_id'], unique=False)

    op.create_table('audio_course_lecturers',
    sa.Column('audio_course_id', sa.Integer(), nullable=False),
    sa.Column('person_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['audio_course_id'], ['audio_courses.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['person_id'], ['people.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('audio_course_id', 'person_id')
    )
    op.create_table('city_photos',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('city_id', sa.Integer(), nullable=False),
    sa.Column('image_id', sa.Integer(), nullable=False),
    sa.Column('image_source', sa.String(length=1000), server_default='', nullable=False),
    sa.Column('image_license', sa.String(length=100), server_default='', nullable=False),
    sa.Column('image_author', sa.String(length=300), server_default='', nullable=False),
    sa.ForeignKeyConstraint(['city_id'], ['cities.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['image_id'], ['images.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('city_photos', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_city_photos_city_id'), ['city_id'], unique=False)

    op.create_table('museum_sites',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('owner_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=300), nullable=False),
    sa.Column('city_id', sa.Integer(), nullable=True),
    sa.Column('url', sa.String(length=1000), nullable=False),
    sa.Column('image_id', sa.Integer(), nullable=True),
    sa.Column('street', sa.String(length=300), server_default='', nullable=False),
    sa.Column('neighbourhood', sa.String(length=200), server_default='', nullable=False),
    sa.Column('postcode', sa.String(length=20), server_default='', nullable=False),
    sa.Column('latitude', sa.Double(), nullable=True),
    sa.Column('longitude', sa.Double(), nullable=True),
    sa.ForeignKeyConstraint(['city_id'], ['cities.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['image_id'], ['images.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('museum_sites', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_museum_sites_city_id'), ['city_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_museum_sites_owner_id'), ['owner_id'], unique=False)

    op.create_table('organizations',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('owner_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('type_id', sa.Integer(), nullable=True),
    sa.Column('status', sa.String(length=50), nullable=False),
    sa.Column('website', sa.String(length=1000), nullable=False),
    sa.Column('location', sa.String(length=300), nullable=False),
    sa.Column('headquarters_id', sa.Integer(), nullable=True),
    sa.Column('city_id', sa.Integer(), nullable=True),
    sa.Column('what_happened', sa.Text(), nullable=False),
    sa.Column('remark', sa.Text(), nullable=False),
    sa.Column('details', sa.JSON(), nullable=False),
    sa.Column('image_id', sa.Integer(), nullable=True),
    sa.Column('street', sa.String(length=300), server_default='', nullable=False),
    sa.Column('neighbourhood', sa.String(length=200), server_default='', nullable=False),
    sa.Column('postcode', sa.String(length=20), server_default='', nullable=False),
    sa.Column('latitude', sa.Double(), nullable=True),
    sa.Column('longitude', sa.Double(), nullable=True),
    sa.ForeignKeyConstraint(['city_id'], ['cities.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['headquarters_id'], ['cities.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['image_id'], ['images.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['type_id'], ['organization_types.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('owner_id', 'name', name='uq_organization_name')
    )
    with op.batch_alter_table('organizations', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_organizations_city_id'), ['city_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_organizations_headquarters_id'), ['headquarters_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_organizations_owner_id'), ['owner_id'], unique=False)

    op.create_table('places',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('owner_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=300), nullable=False),
    sa.Column('city_id', sa.Integer(), nullable=True),
    sa.Column('latitude', sa.Double(), nullable=True),
    sa.Column('longitude', sa.Double(), nullable=True),
    sa.Column('website', sa.String(length=1000), nullable=False),
    sa.Column('remark', sa.Text(), nullable=False),
    sa.Column('image_id', sa.Integer(), nullable=True),
    sa.Column('image_source', sa.String(length=1000), server_default='', nullable=False),
    sa.Column('image_license', sa.String(length=100), server_default='', nullable=False),
    sa.Column('image_author', sa.String(length=300), server_default='', nullable=False),
    sa.Column('street', sa.String(length=300), server_default='', nullable=False),
    sa.Column('neighbourhood', sa.String(length=200), server_default='', nullable=False),
    sa.Column('postcode', sa.String(length=20), server_default='', nullable=False),
    sa.ForeignKeyConstraint(['city_id'], ['cities.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['image_id'], ['images.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('owner_id', 'name', 'city_id', name='uq_place_name')
    )
    with op.batch_alter_table('places', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_places_city_id'), ['city_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_places_owner_id'), ['owner_id'], unique=False)

    op.create_table('concert_visits',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('owner_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=300), nullable=False),
    sa.Column('event', sa.String(length=300), nullable=False),
    sa.Column('genre', sa.String(length=50), nullable=False),
    sa.Column('place_id', sa.Integer(), nullable=True),
    sa.Column('tickets', sa.Integer(), nullable=True),
    sa.Column('broadcast', sa.Boolean(), nullable=False),
    sa.Column('alone', sa.Boolean(), server_default=sa.text('0'), nullable=False),
    sa.Column('review', sa.Text(), nullable=False),
    sa.Column('remark', sa.Text(), nullable=False),
    sa.Column('image_id', sa.Integer(), nullable=True),
    sa.Column('image_source', sa.String(length=1000), server_default='', nullable=False),
    sa.Column('image_license', sa.String(length=100), server_default='', nullable=False),
    sa.Column('image_author', sa.String(length=300), server_default='', nullable=False),
    sa.Column('date_utcz', sa.DateTime(), nullable=True),
    sa.Column('date_ymd', sa.Date(), nullable=True),
    sa.Column('date_my', sa.String(length=7), nullable=False),
    sa.Column('date_y', sa.Integer(), nullable=True),
    sa.Column('date_timezone', sa.String(length=64), nullable=False),
    sa.ForeignKeyConstraint(['image_id'], ['images.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['place_id'], ['places.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('concert_visits', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_concert_visits_owner_id'), ['owner_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_concert_visits_place_id'), ['place_id'], unique=False)

    op.create_table('museum_visits',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('museum_id', sa.Integer(), nullable=False),
    sa.Column('rating', sa.Integer(), nullable=True),
    sa.Column('review', sa.Text(), nullable=False),
    sa.Column('remark', sa.Text(), nullable=False),
    sa.Column('tickets', sa.Integer(), nullable=True),
    sa.Column('alone', sa.Boolean(), server_default=sa.text('0'), nullable=False),
    sa.Column('date_utcz', sa.DateTime(), nullable=True),
    sa.Column('date_ymd', sa.Date(), nullable=True),
    sa.Column('date_my', sa.String(length=7), nullable=False),
    sa.Column('date_y', sa.Integer(), nullable=True),
    sa.Column('date_timezone', sa.String(length=64), nullable=False),
    sa.CheckConstraint('rating IS NULL OR (rating >= 1 AND rating <= 10)', name='ck_museum_rating_range'),
    sa.ForeignKeyConstraint(['museum_id'], ['museum_sites.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('museum_visits', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_museum_visits_museum_id'), ['museum_id'], unique=False)

    op.create_table('organization_relation_types',
    sa.Column('organization_id', sa.Integer(), nullable=False),
    sa.Column('relation_type_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['relation_type_id'], ['relation_types.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('organization_id', 'relation_type_id')
    )
    op.create_table('person_organizations',
    sa.Column('person_id', sa.Integer(), nullable=False),
    sa.Column('organization_id', sa.Integer(), nullable=False),
    sa.Column('relation_type_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['person_id'], ['people.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['relation_type_id'], ['person_organization_types.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('person_id', 'organization_id', 'relation_type_id')
    )
    op.create_table('concert_companions',
    sa.Column('concert_id', sa.Integer(), nullable=False),
    sa.Column('person_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['concert_id'], ['concert_visits.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['person_id'], ['people.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('concert_id', 'person_id')
    )
    op.create_table('concert_groups',
    sa.Column('concert_id', sa.Integer(), nullable=False),
    sa.Column('group_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['concert_id'], ['concert_visits.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['group_id'], ['groups.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('concert_id', 'group_id')
    )
    op.create_table('concert_performers',
    sa.Column('concert_id', sa.Integer(), nullable=False),
    sa.Column('person_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['concert_id'], ['concert_visits.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['person_id'], ['people.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('concert_id', 'person_id')
    )
    op.create_table('museum_companions',
    sa.Column('museum_id', sa.Integer(), nullable=False),
    sa.Column('person_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['museum_id'], ['museum_visits.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['person_id'], ['people.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('museum_id', 'person_id')
    )


def downgrade() -> None:
    op.drop_table('museum_companions')
    op.drop_table('concert_performers')
    op.drop_table('concert_groups')
    op.drop_table('concert_companions')
    op.drop_table('person_organizations')
    op.drop_table('organization_relation_types')
    with op.batch_alter_table('museum_visits', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_museum_visits_museum_id'))

    op.drop_table('museum_visits')
    with op.batch_alter_table('concert_visits', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_concert_visits_place_id'))
        batch_op.drop_index(batch_op.f('ix_concert_visits_owner_id'))

    op.drop_table('concert_visits')
    with op.batch_alter_table('places', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_places_owner_id'))
        batch_op.drop_index(batch_op.f('ix_places_city_id'))

    op.drop_table('places')
    with op.batch_alter_table('organizations', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_organizations_owner_id'))
        batch_op.drop_index(batch_op.f('ix_organizations_headquarters_id'))
        batch_op.drop_index(batch_op.f('ix_organizations_city_id'))

    op.drop_table('organizations')
    with op.batch_alter_table('museum_sites', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_museum_sites_owner_id'))
        batch_op.drop_index(batch_op.f('ix_museum_sites_city_id'))

    op.drop_table('museum_sites')
    with op.batch_alter_table('city_photos', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_city_photos_city_id'))

    op.drop_table('city_photos')
    op.drop_table('audio_course_lecturers')
    with op.batch_alter_table('youtube_videos', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_youtube_videos_owner_id'))

    op.drop_table('youtube_videos')
    op.drop_table('person_type_links')
    with op.batch_alter_table('library_reads', schema=None) as batch_op:
        batch_op.drop_index('ix_library_reads_entry')

    op.drop_table('library_reads')
    op.drop_table('library_ownings')
    op.drop_table('library_entry_authors')
    with op.batch_alter_table('library_covers', schema=None) as batch_op:
        batch_op.drop_index('ix_library_covers_entry')

    op.drop_table('library_covers')
    op.drop_table('group_members')
    with op.batch_alter_table('cities', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_cities_owner_id'))
        batch_op.drop_index(batch_op.f('ix_cities_country_id'))

    op.drop_table('cities')
    with op.batch_alter_table('audio_courses', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_audio_courses_owner_id'))

    op.drop_table('audio_courses')
    with op.batch_alter_table('person_types', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_person_types_owner_id'))

    op.drop_table('person_types')
    with op.batch_alter_table('person_relations', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_person_relations_relation_type_id'))
        batch_op.drop_index(batch_op.f('ix_person_relations_person_id'))
        batch_op.drop_index(batch_op.f('ix_person_relations_other_id'))

    op.drop_table('person_relations')
    with op.batch_alter_table('person_photos', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_person_photos_person_id'))

    op.drop_table('person_photos')
    with op.batch_alter_table('person_names', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_person_names_person_id'))

    op.drop_table('person_names')
    op.drop_table('library_entries')
    with op.batch_alter_table('groups', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_groups_owner_id'))

    op.drop_table('groups')
    with op.batch_alter_table('devices', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_devices_owner_id'))

    op.drop_table('devices')
    with op.batch_alter_table('countries', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_countries_owner_id'))

    op.drop_table('countries')
    with op.batch_alter_table('relation_types', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_relation_types_owner_id'))

    op.drop_table('relation_types')
    with op.batch_alter_table('person_relation_types', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_person_relation_types_owner_id'))

    op.drop_table('person_relation_types')
    with op.batch_alter_table('person_organization_types', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_person_organization_types_owner_id'))

    op.drop_table('person_organization_types')
    with op.batch_alter_table('people', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_people_owner_id'))

    op.drop_table('people')
    with op.batch_alter_table('organization_types', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_organization_types_owner_id'))

    op.drop_table('organization_types')
    with op.batch_alter_table('logins', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_logins_user_id'))

    op.drop_table('logins')
    with op.batch_alter_table('library_work_titles', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_library_work_titles_work_id'))

    op.drop_table('library_work_titles')
    with op.batch_alter_table('images', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_images_owner_id'))

    op.drop_table('images')
    op.drop_table('disabled_checks')
    op.drop_table('users')
    op.drop_table('library_works')
    op.drop_table('locales')
    op.drop_table('email_verifications')
