from __future__ import annotations
import inspect
import src.controllers.schedulers as sched


def test_intel_does_not_discover_in_same_tick():
    src = inspect.getsource(sched.j_competitor_intel)
    assert "discover_competitors" not in src, (
        "discovery must not run in the same tick as profiling"
    )


def test_discovery_job_exists():
    assert hasattr(sched, "j_competitor_discover"), "discovery needs its own job function"
    src = inspect.getsource(sched.j_competitor_discover)
    assert "discover_competitors" in src


def _cron_field(trigger, name: str) -> str:
    for f in trigger.fields:
        if f.name == name:
            return str(f)
    raise AssertionError(f"no {name!r} field on {trigger!r}")


def test_discovery_job_registered_before_intel():
    """Discovery must be registered on the JOBS list and its cron must fire
    before the competitor_intel job so j_competitor_sync (every 10 min) has
    a chance to collect posts for newly discovered competitors first."""
    by_key = {j.key: j for j in sched.JOBS}
    assert "competitor_discover" in by_key
    discover_hour = int(_cron_field(by_key["competitor_discover"].trigger, "hour"))
    intel_hour = int(_cron_field(by_key["competitor_intel"].trigger, "hour"))
    assert discover_hour < intel_hour, "discovery must be scheduled ahead of intel"
