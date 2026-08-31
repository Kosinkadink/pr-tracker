from pr_tracker.data import compute_ci_status


def check_run(*, conclusion: str | None, status: str = "completed") -> dict:
    return {"conclusion": conclusion, "status": status}


def test_compute_ci_status_accepts_success_skipped_and_neutral_checks():
    checks = [
        check_run(conclusion="success"),
        check_run(conclusion="skipped"),
        check_run(conclusion="neutral"),
    ]

    assert compute_ci_status(checks) == {"status": "pass", "failed_count": 0}


def test_compute_ci_status_reports_failure_among_skipped_checks():
    checks = [
        check_run(conclusion="skipped"),
        check_run(conclusion="failure"),
    ]

    assert compute_ci_status(checks) == {"status": "fail", "failed_count": 1}


def test_compute_ci_status_reports_running_check():
    checks = [
        check_run(conclusion="success"),
        check_run(conclusion=None, status="in_progress"),
    ]

    assert compute_ci_status(checks) == {"status": "running", "failed_count": 0}


def test_compute_ci_status_keeps_cancelled_check_mixed():
    checks = [
        check_run(conclusion="success"),
        check_run(conclusion="cancelled"),
    ]

    assert compute_ci_status(checks) == {"status": "mixed", "failed_count": 0}
