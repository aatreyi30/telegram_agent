from __future__ import annotations
import os, tempfile, inspect
import pytest


@pytest.fixture(scope="module", autouse=True)
def _isolated_db():
    tmp = tempfile.mkdtemp()
    os.environ["DB_URL"] = f"sqlite:///{tmp}/test.db"
    os.environ["RAW_SNAPSHOT_DIR"] = f"{tmp}/raw"
    from src.config.settings import get_settings
    from src.db import session as sess
    get_settings.cache_clear()
    sess.get_engine.cache_clear()
    sess.get_sessionmaker.cache_clear()
    from src.db.session import init_db
    init_db()
    yield


def test_no_run_in_executor_async_with():
    """The buggy `async with run_in_executor(...)` pattern must be gone."""
    import src.services.collection.telegram_competitor as mod
    src = inspect.getsource(mod)
    assert "async with asyncio.get_event_loop().run_in_executor" not in src, (
        "the Future-as-context-manager bug is still present"
    )


def test_floodwait_is_handled_distinctly():
    import src.services.collection.telegram_competitor as mod
    src = inspect.getsource(mod)
    assert "FloodWaitError" in src
    # FloodWaitError must appear in an except clause, not only the import
    assert "except FloodWaitError" in src or "except (FloodWaitError" in src
