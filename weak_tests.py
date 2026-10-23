import unittest, solution

class T(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(solution.clamp(5), 5)
        self.assertEqual(solution.mean([1,2,3]), 2)
    def test_discount(self):
        self.assertEqual(solution.apply_discount(100, 10), 90)

if __name__ == "__main__":
    unittest.main()
