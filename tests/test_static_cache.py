import os
import unittest

from waypoint.server import static


class CacheControl(unittest.TestCase):
    def test_hashed_assets_are_cached_for_good(self):
        self.assertEqual(static.cache_control(os.path.join(static.APP_DIR, "assets", "index-abc.js")), "public, max-age=31536000, immutable")

    def test_fonts_and_icons_are_cached_for_a_week(self):
        for name in ("fonts/Geist-Variable.woff2", "logo.svg", "logo-180.png", "icon-192.png", "icon-512.png", "icon-maskable-512.png"):
            self.assertEqual(static.cache_control(os.path.join(static.STATIC, name)), "public, max-age=604800", name)

    def test_everything_else_is_revalidated_every_time(self):
        for name in ("sw.js", "manifest.webmanifest", "page.css", "app/index.html"):
            self.assertEqual(static.cache_control(os.path.join(static.STATIC, name)), "no-cache", name)

    def test_a_lookalike_outside_the_fonts_folder_is_not_cached_long(self):
        self.assertEqual(static.cache_control(os.path.join(static.STATIC, "fontsmith", "x.woff2")), "no-cache")
        self.assertEqual(static.cache_control(os.path.join(static.STATIC, "app", "logo.svg")), "no-cache")


if __name__ == "__main__":
    unittest.main()
