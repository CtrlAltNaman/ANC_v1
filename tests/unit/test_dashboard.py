from array import array
import unittest

from tools.audio.dashboard import metrics, nlms


class DashboardTests(unittest.TestCase):
    def test_metrics_reports_peak_and_sample_rate_features(self):
        signal = array("h", [0, 1000, -1000, 0] * 100)
        result = metrics(signal, 16000)
        self.assertEqual(result["peak"], 1000)
        self.assertGreater(result["rms"], 0)
        self.assertEqual(result["zcr"], 8000.0)

    def test_nlms_returns_same_length_signal(self):
        desired = array("h", [1000, 1000, 1000, 1000] * 20)
        reference = array("h", [500, 500, 500, 500] * 20)
        cleaned = nlms(desired, reference, taps=8, mu=0.2)
        self.assertEqual(len(cleaned), len(desired))
        self.assertTrue(all(-32768 <= sample <= 32767 for sample in cleaned))


if __name__ == "__main__":
    unittest.main()
