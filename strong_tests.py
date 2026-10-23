import unittest, solution

class T(unittest.TestCase):
    def test_clamp_bounds(self):
        self.assertEqual(solution.clamp(-5), 0)
        self.assertEqual(solution.clamp(500), 100)
        self.assertEqual(solution.clamp(5), 5)
        self.assertEqual(solution.clamp(5, lo=10, hi=20), 10)
    def test_mean(self):
        self.assertEqual(solution.mean([1,2,3]), 2)
        self.assertEqual(solution.mean([2,4]), 3)
    def test_discount(self):
        self.assertEqual(solution.apply_discount(100, 10), 90)
        self.assertEqual(solution.apply_discount(100, 80), 50)
        self.assertEqual(solution.apply_discount(200, 25), 150)

if __name__ == "__main__":
    unittest.main()
