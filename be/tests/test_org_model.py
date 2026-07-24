"""Org model + seed tests — structural multi-tenancy, idempotent seeding, channel backfill."""

from __future__ import annotations

import os
import tempfile

import pytest


@pytest.fixture(scope="module", autouse=True)
def _isolated_db():
    tmp = tempfile.mkdtemp()
    os.environ["DB_URL"] = f"sqlite:///{tmp}/org.db"
    os.environ["RAW_SNAPSHOT_DIR"] = f"{tmp}/raw"
    os.environ["OWNED_CHANNELS"] = "MyChannel"
    from src.config.settings import get_settings
    from src.db import session as sess

    get_settings.cache_clear()
    sess.get_engine.cache_clear()
    sess.get_sessionmaker.cache_clear()
    from src.db.models import Channel
    from src.db.session import init_db, session_scope

    init_db()
    with session_scope() as s:
        s.add(Channel(tg_channel_id=111, username="MyChannel", title="Mine"))
        s.add(Channel(tg_channel_id=222, username="SomeCompetitor", title="Other"))
    yield


def test_seed_org_is_idempotent_and_links_channels():
    from sqlalchemy import func, select

    from src.db.models import Channel
    from src.db.models_org import Organization, User
    from src.db.org_seed import seed_org
    from src.db.session import session_scope

    with session_scope() as s:
        org1 = seed_org(s)
    with session_scope() as s:
        org2 = seed_org(s)                      # second run must not duplicate
        n_orgs = s.scalar(select(func.count()).select_from(Organization))
        n_users = s.scalar(select(func.count()).select_from(User))
        linked = s.scalar(select(func.count()).select_from(Channel)
                          .where(Channel.org_id.isnot(None)))
        owned = s.scalar(select(Channel).where(Channel.username == "MyChannel"))
    assert org1.id == org2.id
    assert n_orgs == 1 and n_users == 1         # idempotent
    assert linked == 2                           # both channels linked to the org
    assert owned.kind == "owned"                 # owned handle labelled correctly


def test_org_settings_snapshot_affiliate_config():
    from src.db.org_seed import seed_org
    from src.db.session import session_scope

    with session_scope() as s:
        org = seed_org(s)
        assert "grabon_shortener_url" in (org.settings or {})
