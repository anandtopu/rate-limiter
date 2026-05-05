from scripts import load_test


def test_load_test_scenarios_cover_demo_segments():
    scenario_names = {scenario.name for scenario in load_test.SCENARIOS}

    assert {
        "free-data",
        "premium-data",
        "limited-health",
        "templated-account-data",
    }.issubset(scenario_names)


def test_load_test_summary_counts_limits_and_errors():
    summary = load_test.summarize([
        {"scenario": "free-data", "status": 200},
        {"scenario": "free-data", "status": 429},
        {"scenario": "free-data", "status": 503},
        {"scenario": "premium-data", "status": "error"},
    ])

    assert summary == {
        "free-data": {"requests": 3, "limited": 1, "errors": 1},
        "premium-data": {"requests": 1, "limited": 0, "errors": 1},
    }
