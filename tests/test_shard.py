"""tests/shard.py, which splits the Postgres tests across CI's runners: every module runs in exactly one shard."""
import unittest

from tests import shard


class ShardTests(unittest.TestCase):
    def test_every_module_in_exactly_one_shard(self):
        for count in (1, 2, 3, 5):
            with self.subTest(count=count):
                parts = shard.shards(count)
                self.assertEqual(len(parts), count)
                placed = [m for p in parts for m in p]
                self.assertEqual(sorted(placed), shard.modules())
                self.assertIn("test_shard", placed)

    def test_shards_are_about_the_same_size(self):
        import os
        size = {m: os.path.getsize(os.path.join(shard.HERE, m + ".py")) for m in shard.modules()}
        totals = [sum(size[m] for m in p) for p in shard.shards(3)]
        self.assertLessEqual(max(totals) - min(totals), max(size.values()))

    def test_arguments(self):
        args = shard.main("1/1").split()
        self.assertEqual(args[0::2], ["-k"] * (len(args) // 2))
        self.assertEqual(sorted(a.removeprefix("tests.").rstrip(".") for a in args[1::2]), shard.modules())
        self.assertTrue(all(a.endswith(".") for a in args[1::2]))
        for bad in ("", "x", "0/3", "4/3", "1/", "/3", "-1/3"):
            with self.subTest(arg=bad), self.assertRaises(SystemExit):
                shard.main(bad)


if __name__ == "__main__":
    unittest.main()
