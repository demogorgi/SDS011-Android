# -*- coding: utf-8 -*-
"""Tests fuer das SDS011-Protokoll."""

from __future__ import absolute_import

import unittest

import protocol


class BuildAndParseTest(unittest.TestCase):

    def test_roundtrip(self):
        frame = protocol.build_frame(12.3, 45.6, device_id=0xA160)
        self.assertEqual(len(frame), protocol.FRAME_LEN)
        reading = protocol.parse_frame(frame)
        self.assertIsNotNone(reading)
        self.assertEqual(reading.pm_25, 12.3)
        self.assertEqual(reading.pm_10, 45.6)
        self.assertEqual(reading.device_id, 0xA160)

    def test_known_frame(self):
        # Von Hand gerechnet: PM2.5 = 0x007B = 123 -> 12.3
        #                     PM10  = 0x01C8 = 456 -> 45.6
        raw = bytearray([0xAA, 0xC0, 0x7B, 0x00, 0xC8, 0x01, 0xA1, 0x60, 0, 0xAB])
        raw[8] = sum(raw[2:8]) % 256
        reading = protocol.parse_frame(bytes(raw))
        self.assertEqual((reading.pm_25, reading.pm_10), (12.3, 45.6))

    def test_zero_values(self):
        reading = protocol.parse_frame(protocol.build_frame(0.0, 0.0))
        self.assertEqual((reading.pm_25, reading.pm_10), (0.0, 0.0))

    def test_high_values(self):
        # 999.9 ug/m3 ist der Messbereich des SDS011.
        reading = protocol.parse_frame(protocol.build_frame(999.9, 999.9))
        self.assertEqual((reading.pm_25, reading.pm_10), (999.9, 999.9))


class RejectTest(unittest.TestCase):

    def setUp(self):
        self.frame = bytearray(protocol.build_frame(20.0, 30.0))

    def test_bad_checksum(self):
        self.frame[8] = (self.frame[8] + 1) % 256
        self.assertIsNone(protocol.parse_frame(bytes(self.frame)))

    def test_bad_head(self):
        self.frame[0] = 0xAB
        self.assertIsNone(protocol.parse_frame(bytes(self.frame)))

    def test_bad_commander(self):
        self.frame[1] = 0xC1
        self.assertIsNone(protocol.parse_frame(bytes(self.frame)))

    def test_bad_tail(self):
        self.frame[9] = 0xAA
        self.assertIsNone(protocol.parse_frame(bytes(self.frame)))

    def test_wrong_length(self):
        self.assertIsNone(protocol.parse_frame(bytes(self.frame[:9])))
        self.assertIsNone(protocol.parse_frame(bytes(self.frame) + b'\x00'))


class FrameDecoderTest(unittest.TestCase):

    def setUp(self):
        self.decoder = protocol.FrameDecoder()

    def test_single_frame(self):
        readings = self.decoder.feed(protocol.build_frame(1.0, 2.0))
        self.assertEqual(len(readings), 1)
        self.assertEqual(readings[0].pm_25, 1.0)

    def test_frame_split_across_reads(self):
        frame = protocol.build_frame(5.5, 6.6)
        self.assertEqual(self.decoder.feed(frame[:3]), [])
        self.assertEqual(self.decoder.feed(frame[3:7]), [])
        readings = self.decoder.feed(frame[7:])
        self.assertEqual(len(readings), 1)
        self.assertEqual(readings[0].pm_10, 6.6)

    def test_two_frames_in_one_read(self):
        data = protocol.build_frame(1.0, 2.0) + protocol.build_frame(3.0, 4.0)
        readings = self.decoder.feed(data)
        self.assertEqual([r.pm_25 for r in readings], [1.0, 3.0])

    def test_leading_garbage_is_skipped(self):
        data = b'\x01\x02\x03' + protocol.build_frame(7.0, 8.0)
        readings = self.decoder.feed(data)
        self.assertEqual(len(readings), 1)
        self.assertEqual(self.decoder.discarded_bytes, 3)

    def test_resync_after_false_head(self):
        # Ein 0xAA mitten im Muell darf den folgenden echten Frame
        # nicht verschlucken.
        data = b'\xaa\xaa\xc0\x00' + protocol.build_frame(9.0, 10.0)
        readings = self.decoder.feed(data)
        self.assertEqual(len(readings), 1)
        self.assertEqual(readings[0].pm_25, 9.0)

    def test_corrupt_frame_is_dropped_but_next_survives(self):
        bad = bytearray(protocol.build_frame(1.0, 2.0))
        bad[8] = (bad[8] + 7) % 256
        readings = self.decoder.feed(bytes(bad) + protocol.build_frame(3.0, 4.0))
        self.assertEqual([r.pm_25 for r in readings], [3.0])

    def test_buffer_does_not_grow_unbounded(self):
        for _ in range(50):
            self.decoder.feed(b'\xaa' * 100)
        self.assertLessEqual(self.decoder.pending(), protocol.FrameDecoder.MAX_BUFFER)

    def test_pure_garbage_yields_nothing(self):
        self.assertEqual(self.decoder.feed(b'\x01\x02\x03\x04'), [])
        self.assertEqual(self.decoder.pending(), 0)


if __name__ == '__main__':
    unittest.main()
