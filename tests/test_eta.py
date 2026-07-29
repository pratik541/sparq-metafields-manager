import pytest

from eta import (
    ASSUMED_SECONDS_PER_BATCH,
    eta_seconds,
    format_duration,
    progress_line,
    upfront_estimate_seconds,
)


class TestFormatDuration:
    @pytest.mark.parametrize("seconds,expected", [
        (0, "0s"),
        (1, "1s"),
        (45, "45s"),
        (59, "59s"),
        (60, "1m 00s"),
        (80, "1m 20s"),
        (200, "3m 20s"),
        (3599, "59m 59s"),
        (3600, "1h 00m"),
        (3900, "1h 05m"),
        (7200, "2h 00m"),
    ])
    def test_formats(self, seconds, expected):
        assert format_duration(seconds) == expected

    def test_none_is_placeholder(self):
        assert format_duration(None) == "--"

    def test_negative_clamps_to_zero(self):
        assert format_duration(-5) == "0s"

    def test_rounds_rather_than_truncates(self):
        assert format_duration(59.6) == "1m 00s"


class TestEtaSeconds:
    def test_halfway_predicts_the_same_again(self):
        assert eta_seconds(elapsed=60, done=50, total=100) == 60.0

    def test_quarter_done_predicts_three_times_more(self):
        assert eta_seconds(elapsed=10, done=25, total=100) == 30.0

    def test_nothing_done_yet_is_unknown(self):
        assert eta_seconds(elapsed=5, done=0, total=100) is None

    def test_no_elapsed_time_is_unknown(self):
        assert eta_seconds(elapsed=0, done=10, total=100) is None

    def test_all_done_is_zero(self):
        assert eta_seconds(elapsed=100, done=100, total=100) == 0.0

    def test_overshoot_is_zero_not_negative(self):
        assert eta_seconds(elapsed=100, done=105, total=100) == 0.0

    def test_zero_total_is_zero(self):
        assert eta_seconds(elapsed=10, done=0, total=0) == 0.0

    def test_slowing_down_is_reflected(self):
        """A run that throttles partway should report a larger ETA than at the start."""
        early = eta_seconds(elapsed=10, done=10, total=100)   # 1s/batch
        later = eta_seconds(elapsed=100, done=20, total=100)  # 5s/batch
        assert later > early


class TestUpfrontEstimate:
    def test_uses_the_assumed_rate(self):
        assert upfront_estimate_seconds(100) == 100 * ASSUMED_SECONDS_PER_BATCH

    def test_zero_batches_is_zero(self):
        assert upfront_estimate_seconds(0) == 0

    def test_negative_clamps_to_zero(self):
        assert upfront_estimate_seconds(-5) == 0

    def test_rate_is_overridable(self):
        assert upfront_estimate_seconds(10, seconds_per_batch=2.0) == 20.0


class TestProgressLine:
    def test_includes_position_elapsed_and_remaining(self):
        line = progress_line(elapsed=14, done=12, total=300)
        assert "Batch 12/300" in line
        assert "14s elapsed" in line
        assert "remaining" in line

    def test_first_batch_says_estimating(self):
        line = progress_line(elapsed=2, done=0, total=300)
        assert "estimating" in line

    def test_completion_says_done(self):
        line = progress_line(elapsed=100, done=300, total=300)
        assert "done" in line
        assert "remaining" not in line

    def test_noun_is_configurable(self):
        line = progress_line(elapsed=10, done=5, total=10, noun="Request")
        assert line.startswith("Request 5/10")

    def test_realistic_30k_run_reads_sensibly(self):
        """3000 batches, 1.1s each, one tenth done."""
        line = progress_line(elapsed=330, done=300, total=3000)
        assert "Batch 300/3000" in line
        assert "5m 30s elapsed" in line
        assert "~49m 30s remaining" in line
