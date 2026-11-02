import unittest

import pandas as pd

from fdq.metrics import ewma


class EwmaTest(unittest.TestCase):
    def test_constant_load_is_flat(self):
        s = pd.Series([5000.0] * 30)
        self.assertTrue((ewma(s, 7) == 5000.0).all())

    def test_spike_decays_smoothly(self):
        s = pd.Series([1000.0] * 10 + [8000.0] + [1000.0] * 10)
        e = ewma(s, 7)
        after = e.iloc[10:].tolist()
        self.assertTrue(all(a > b for a, b in zip(after, after[1:])), "must decay every day after the spike")
        # Unlike a 7-day rolling mean, there is no cliff exactly 7 days later.
        rolling = s.rolling(7).mean()
        cliff_rolling = rolling.iloc[16] - rolling.iloc[17]
        cliff_ewma = e.iloc[16] - e.iloc[17]
        self.assertGreater(cliff_rolling, 5 * cliff_ewma)

    def test_lambda(self):
        s = pd.Series([0.0, 100.0])
        self.assertAlmostEqual(ewma(s, 7).iloc[1], 100 * 2 / 8)


if __name__ == "__main__":
    unittest.main()
