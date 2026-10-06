import unittest

from tools import no_comments


class PythonComments(unittest.TestCase):
    def test_a_comment_is_flagged_with_its_line(self):
        self.assertEqual(no_comments.problems("a.py", "x = 1\n# why\ny = 2  # also\n"), [
            "a.py:2: a comment or docstring: say it in the code's names, or in the commit message or docs",
            "a.py:3: a comment or docstring: say it in the code's names, or in the commit message or docs",
        ])

    def test_directives_and_a_shebang_are_not_comments(self):
        source = "#!/usr/bin/env python3\nimport os  # noqa: F401\nx: int = y  # type: ignore[assignment]\n"
        self.assertEqual(no_comments.problems("a.py", source), [])

    def test_a_docstring_or_a_bare_string_is_flagged(self):
        source = 'def f():\n    "says what it does"\n    return 1\n\n\nclass C:\n    x = 1\n    """about x"""\n'
        self.assertEqual([p.split(" ")[0] for p in no_comments.problems("a.py", source)], ["a.py:2:", "a.py:8:"])

    def test_a_string_that_is_used_is_not_a_docstring(self):
        self.assertEqual(no_comments.problems("a.py", 'x = "text"\nprint("text")\n'), [])

    def test_a_hash_inside_a_string_is_not_a_comment(self):
        self.assertEqual(no_comments.problems("a.py", 'x = "# not a comment"\n'), [])


class CssComments(unittest.TestCase):
    def test_a_css_comment_is_flagged(self):
        self.assertEqual(len(no_comments.problems("a.css", "a { color: red; }\n/* why */\n")), 1)

    def test_a_svelte_style_block_is_checked_and_its_script_is_not(self):
        source = "<script>\n  // eslint's job\n</script>\n<style>\n  a { /* why */ color: red; }\n</style>\n"
        self.assertEqual([p.split(" ")[0] for p in no_comments.problems("A.svelte", source)], ["A.svelte:5:"])

    def test_a_banner_that_a_minifier_keeps_is_not_a_comment(self):
        self.assertEqual(no_comments.problems("a.css", "/*! font license */\na { color: red; }\n"), [])


class Repository(unittest.TestCase):
    def test_the_tracked_files_carry_none(self):
        self.assertEqual(no_comments.main(), 0)
