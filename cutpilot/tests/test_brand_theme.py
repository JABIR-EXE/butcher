from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

class BrandThemeTests(unittest.TestCase):
    def test_friendly_cow_logo_assets_are_installed(self):
        png = (ROOT / 'static' / 'brand' / 'cutpilot-mark.png').read_bytes()
        self.assertTrue(png.startswith(b'\x89PNG\r\n\x1a\n'))
        self.assertGreater(len(png), 50_000)
        svg = (ROOT / 'static' / 'brand' / 'cutpilot-mark.svg').read_text()
        self.assertIn('friendly cow mascot', svg)

    def test_teal_day_night_switch_is_wired(self):
        html = (ROOT / 'static' / 'index.html').read_text()
        js = (ROOT / 'static' / 'app.js').read_text()
        css = (ROOT / 'static' / 'themes.css').read_text()
        self.assertIn('id="theme-toggle"', html)
        self.assertIn('/themes.css', html)
        self.assertIn("localStorage.setItem('cutpilot-theme'", js)
        self.assertIn("dataset.theme==='dark'?'light':'dark'", js)
        self.assertIn('html[data-theme="light"]', css)
        self.assertIn('html[data-theme="dark"]', css)
        self.assertIn('--brand:#12a985', css)
        self.assertIn('document.documentElement.dataset.theme = saved || "light"', html)

    def test_plans_pricing_navigation_remains_available(self):
        html = (ROOT / 'static' / 'index.html').read_text()
        self.assertIn('Plans & pricing', html)
        self.assertIn('id="page-pricing"', html)

    def test_brand_wordmark_uses_cow_mascot(self):
        html = (ROOT / 'static' / 'index.html').read_text()
        self.assertIn('alt="Friendly CutPilot cow mascot"', html)
        self.assertIn('cutpilot<span>.</span>', html)

if __name__ == '__main__':
    unittest.main()
