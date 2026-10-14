"""Driver-utilization accounting (FEEDBACK-V2 P0 item 3).

Utilization must be the fraction of the measurement window during which a driver
is busy, which requires clipping each busy interval to the window and merging
overlaps before measuring. Summing raw spans is what previously produced values
above 1.
"""

import pytest

from mvp_sim.core.driver import Driver
from mvp_sim.stats.metrics import busy_time_in_window


def make_driver() -> Driver:
    return Driver(zone_id=1, position=(0.0, 0.0), driver_id=1)


class TestBusyTimeInWindow:
    def test_single_interval_inside_window(self):
        assert busy_time_in_window([(2.0, 5.0)], 0.0, 10.0) == pytest.approx(3.0)

    def test_interval_crossing_warmup_boundary_is_clipped(self):
        # Busy from 1 to 8, but the window opens at 5: only 3 units count.
        assert busy_time_in_window([(1.0, 8.0)], 5.0, 10.0) == pytest.approx(3.0)

    def test_interval_crossing_horizon_is_clipped(self):
        # Busy from 8 to 40 while the window closes at 10: only 2 units count.
        assert busy_time_in_window([(8.0, 40.0)], 5.0, 10.0) == pytest.approx(2.0)

    def test_interval_spanning_whole_window_is_capped(self):
        assert busy_time_in_window([(-5.0, 100.0)], 5.0, 10.0) == pytest.approx(5.0)

    def test_interval_entirely_outside_window_contributes_nothing(self):
        assert busy_time_in_window([(0.0, 4.0)], 5.0, 10.0) == 0.0
        assert busy_time_in_window([(20.0, 30.0)], 5.0, 10.0) == 0.0

    def test_disjoint_intervals_add(self):
        assert busy_time_in_window([(0.0, 2.0), (4.0, 5.0)], 0.0, 10.0) == pytest.approx(3.0)

    def test_overlapping_intervals_are_merged_not_summed(self):
        # This is the regression: summing gives 4+4=8 > the 5-unit window.
        # The union is [0,6] clipped to [0,5], so 5.
        assert busy_time_in_window([(0.0, 4.0), (2.0, 6.0)], 0.0, 5.0) == pytest.approx(5.0)

    def test_duplicate_intervals_counted_once(self):
        assert busy_time_in_window([(1.0, 3.0)] * 5, 0.0, 10.0) == pytest.approx(2.0)

    def test_intervals_out_of_order(self):
        assert busy_time_in_window([(6.0, 8.0), (1.0, 3.0)], 0.0, 10.0) == pytest.approx(4.0)

    def test_adjacent_intervals_do_not_double_count(self):
        # Travel-to-restaurant [0,3] abutting batch delivery [3,7].
        assert busy_time_in_window([(0.0, 3.0), (3.0, 7.0)], 0.0, 10.0) == pytest.approx(7.0)

    def test_empty(self):
        assert busy_time_in_window([], 0.0, 10.0) == 0.0

    def test_degenerate_window(self):
        assert busy_time_in_window([(0.0, 5.0)], 5.0, 5.0) == 0.0

    def test_never_exceeds_window_for_arbitrary_input(self):
        window_start, window_end = 5.0, 17.0
        intervals = [(float(a), float(a + b))
                     for a in range(0, 30, 2) for b in (1, 3, 9)]
        busy = busy_time_in_window(intervals, window_start, window_end)
        assert 0.0 <= busy <= window_end - window_start


class TestDriverMarkBusy:
    def test_mark_busy_records_interval(self):
        d = make_driver()
        d.mark_busy(1.0, 4.0)
        assert d.busy_intervals == [(1.0, 4.0)]

    def test_zero_length_and_inverted_spans_are_dropped(self):
        d = make_driver()
        d.mark_busy(2.0, 2.0)
        d.mark_busy(5.0, 3.0)
        assert d.busy_intervals == []

    def test_utilization_of_a_fully_busy_driver_is_one(self):
        d = make_driver()
        d.mark_busy(0.0, 100.0)
        assert busy_time_in_window(d.busy_intervals, 5.0, 20.0) / 15.0 == pytest.approx(1.0)
