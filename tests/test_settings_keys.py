import ast
import os
import re
import unittest

from waypoint.storage import settings_keys as sk

WAYPOINT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "waypoint")
SQL_KEY = re.compile(r"\bsettings\b.*\bkey\s*(=|LIKE|IN)\s*\(?\s*'", re.I | re.S)


def sources():
    for root, dirs, files in os.walk(WAYPOINT):
        dirs[:] = sorted(d for d in dirs if d not in ("migrations", "static", "__pycache__"))
        for name in sorted(files):
            path = os.path.join(root, name)
            rel = os.path.relpath(path, WAYPOINT)
            if name.endswith(".py") and rel != os.path.join("storage", "settings_keys.py"):
                with open(path) as f:
                    src = f.read()
                yield rel, src, ast.parse(src, path)


def literal(node) -> bool:
    if isinstance(node, ast.Constant):
        return isinstance(node.value, str)
    if isinstance(node, ast.JoinedStr):
        return True
    if isinstance(node, ast.BinOp):
        return literal(node.left) or literal(node.right)
    return False


def constants() -> dict[str, str]:
    return {k: v for k, v in vars(sk).items() if k.isupper() and isinstance(v, str)}


class SettingsKeysTest(unittest.TestCase):
    def test_no_literal_keys_at_call_sites(self):
        found = []
        for name, _src, tree in sources():
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                fn = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", None)
                if fn not in ("get_setting", "set_setting"):
                    continue
                key = node.args[1] if len(node.args) > 1 else next((k.value for k in node.keywords if k.arg == "key"), None)
                if key is not None and literal(key):
                    found.append(f"{name}:{node.lineno}")
        self.assertEqual(found, [], "use a name from waypoint/storage/settings_keys.py for the settings key")

    def test_no_literal_keys_in_sql(self):
        found = []
        for name, _src, tree in sources():
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and SQL_KEY.search(node.value):
                    found.append(f"{name}:{node.lineno}")
        self.assertEqual(found, [], "pass the settings key as a parameter, from waypoint/storage/settings_keys.py")

    def test_keys_are_distinct(self):
        values = [v for k, v in constants().items() if not k.endswith("_PREFIX")]
        self.assertEqual(len(values), len(set(values)), "two names for the same settings key")

    def test_secrets_are_known_keys(self):
        self.assertLessEqual(set(sk.SECRETS), set(constants().values()))

    def test_every_key_is_used(self):
        code = "\n".join(src for _name, src, _tree in sources())
        unused = [k for k in constants() if not re.search(rf"\bsk\.{k}\b", code)]
        self.assertEqual(unused, [])


if __name__ == "__main__":
    unittest.main()
