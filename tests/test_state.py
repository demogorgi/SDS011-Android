# -*- coding: utf-8 -*-
"""AppState: Summen fuer Fenster-Mittelwerte, Messintervall, Verlauf,
Sitzung und Upload-Anzeige."""

from __future__ import absolute_import

import threading
import unittest

from state import AppState


class SampleTotalsTest(unittest.TestCase):

    def test_starts_empty(self):
        self.assertEqual(AppState().sample_totals(), (0, 0.0, 0.0))

    def test_every_measurement_counts(self):
        state = AppState()
        state.set_measurement(1.0, 10.0)
        state.set_measurement(2.0, 20.0)
        self.assertEqual(state.sample_totals(), (2, 3.0, 30.0))

    def test_windows_do_not_disturb_each_other(self):
        """Aufzeichnung und Upload mitteln ueber verschiedene Fenster."""
        state = AppState()
        state.set_measurement(100.0, 100.0)
        upload_start = state.sample_totals()
        state.set_measurement(10.0, 20.0)
        record_start = state.sample_totals()
        state.set_measurement(30.0, 40.0)
        now = state.sample_totals()

        def mean(start):
            count = now[0] - start[0]
            return ((now[1] - start[1]) / count, (now[2] - start[2]) / count)
        self.assertEqual(mean(upload_start), (20.0, 30.0))
        self.assertEqual(mean(record_start), (30.0, 40.0))

    def test_totals_are_consistent_under_load(self):
        state = AppState()

        def feed():
            for _ in range(2000):
                state.set_measurement(1.0, 2.0)
        threads = [threading.Thread(target=feed) for _ in range(4)]
        for thread in threads:
            thread.start()
        for _ in range(200):
            count, sum_25, sum_10 = state.sample_totals()
            self.assertEqual(sum_25, count * 1.0)
            self.assertEqual(sum_10, count * 2.0)
        for thread in threads:
            thread.join()
        self.assertEqual(state.sample_totals()[0], 8000)


class RecordIntervalTest(unittest.TestCase):

    def test_default_and_change(self):
        self.assertEqual(AppState().record_interval(), 5)
        state = AppState(record_interval=30)
        self.assertEqual(state.record_interval(), 30)
        state.set_record_interval(60)
        self.assertEqual(state.record_interval(), 60)
        self.assertEqual(state.snapshot()['record_interval'], 60)


class HistoryTest(unittest.TestCase):

    def test_points_and_revision(self):
        state = AppState()
        self.assertEqual(state.history(), [])
        self.assertEqual(state.history_rev(), 0)
        state.add_history_point(1000, 1.0, 2.0, 5, False)
        state.add_history_point(1005.5, 3.0, 4.0, 5, 1)
        self.assertEqual(state.history(), [(1000.0, 1.0, 2.0, 5, False),
                                           (1005.5, 3.0, 4.0, 5, True)])
        self.assertEqual(state.history_rev(), 2)
        self.assertEqual(state.snapshot()['history_rev'], 2)

    def test_since(self):
        state = AppState()
        for epoch in (100, 200, 300):
            state.add_history_point(epoch, 1.0, 1.0, 5, False)
        self.assertEqual([p[0] for p in state.history(since=200)], [200.0, 300.0])
        self.assertEqual(state.history(since=301), [])
        self.assertEqual(len(state.history(since=None)), 3)

    def test_oldest_points_drop_out(self):
        state = AppState(history_size=3)
        for epoch in range(5):
            state.add_history_point(epoch, 1.0, 1.0, 5, False)
        self.assertEqual([p[0] for p in state.history()], [2.0, 3.0, 4.0])
        # Die Revision zaehlt weiter, auch wenn der Puffer voll ist.
        self.assertEqual(state.history_rev(), 5)

    def test_returned_list_is_a_copy(self):
        state = AppState()
        state.add_history_point(1, 1.0, 1.0, 5, False)
        state.history().append('fremd')
        self.assertEqual(len(state.history()), 1)


class SessionAndUploadTest(unittest.TestCase):

    def test_session_is_copied_in_and_out(self):
        state = AppState()
        self.assertIsNone(state.session())
        info = {'mode': 'lokal', 'active': True, 'points': 0}
        state.set_session(info)
        info['points'] = 99
        self.assertEqual(state.session()['points'], 0)
        state.session()['points'] = 42
        self.assertEqual(state.session()['points'], 0)
        self.assertEqual(state.snapshot()['session']['mode'], 'lokal')
        state.set_session(None)
        self.assertIsNone(state.session())

    def test_upload_info_is_copied(self):
        state = AppState()
        self.assertIsNone(state.upload_info())
        info = {'last_at': None, 'last_ok': None, 'last_message': u'', 'next_at': 5.0}
        state.set_upload_info(info)
        info['next_at'] = 7.0
        self.assertEqual(state.upload_info()['next_at'], 5.0)
        self.assertEqual(state.snapshot()['upload_info']['next_at'], 5.0)

    def test_next_point_at(self):
        state = AppState()
        self.assertIsNone(state.next_point_at())
        state.set_next_point_at(1234.5)
        self.assertEqual(state.next_point_at(), 1234.5)
        self.assertEqual(state.snapshot()['next_point_at'], 1234.5)


if __name__ == '__main__':
    unittest.main()
