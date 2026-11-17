import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def quoted_list(text, pattern):
    match = re.search(pattern, text, re.DOTALL)
    assert match, pattern
    return re.findall(r'"([^"]+)"', match.group(1))


class IosShellCache(unittest.TestCase):
    def test_the_iphone_app_keeps_the_same_shell_files_as_the_service_worker(self):
        with open(os.path.join(ROOT, "waypoint", "static", "sw.js"), encoding="utf-8") as f:
            worker = quoted_list(f.read(), r"const SHELL = \[(.*?)\];")
        with open(os.path.join(ROOT, "ios", "Waypoint", "OfflinePages.swift"), encoding="utf-8") as f:
            app = quoted_list(f.read(), r"static let shell = \[(.*?)\]\n")
        self.assertEqual(app, [p for p in worker if p != "/"])


if __name__ == "__main__":
    unittest.main()
