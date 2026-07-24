import src.controllers.schedulers as sched


def test_daily_report_job_exists():
    assert hasattr(sched, "j_daily_report")
