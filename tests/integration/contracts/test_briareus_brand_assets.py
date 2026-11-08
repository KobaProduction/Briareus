"""Exercise palette geometry and SVG composition with real selected frames."""

from __future__ import annotations

import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from scripts import brand_assets as brand

NS = {"s": brand.SVG}
SYMBOL = f'''<svg xmlns="{brand.SVG}" id="badge" viewBox="10 20 200 100">
<title id="title">Provider</title>
<defs><linearGradient id="paint"><stop stop-color="#FC6D26"/></linearGradient>
<clipPath id="clip"><rect x="10" y="20" width="200" height="100"/></clipPath></defs>
<g id="icon" clip-path="url(#clip)"><path id="shape" fill="url(#paint)" d="M10 20h200v100z"/>
<use href="#shape"/></g></svg>'''


class BrandAssetTests(unittest.TestCase):
    def test_composition_preserves_provider_and_scopes_references(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            icon, output = Path(temporary) / "provider.svg", Path(temporary) / "result.svg"
            icon.write_text(SYMBOL, encoding="utf-8")
            brand.compose(icon, output, theme="bronze", scale=0.5)
            root = ET.parse(output).getroot()
        symbol = root.find("s:svg", NS)
        assert symbol is not None
        self.assertEqual(symbol.get("viewBox"), "10 20 200 100")
        self.assertEqual(symbol.get("preserveAspectRatio"), "xMidYMid meet")
        self.assertEqual((symbol.get("x"), symbol.get("width")), ("387", "250"))
        identifiers = [element.get("id") for element in root.iter() if element.get("id")]
        self.assertEqual(len(identifiers), len(set(identifiers)))
        self.assertIn("service-badge", identifiers)
        self.assertEqual(symbol.find(".//s:use", NS).get("href"), "#service-shape")  # type: ignore[union-attr]
        self.assertEqual(symbol.find(".//s:g", NS).get("clip-path"), "url(#service-clip)")  # type: ignore[union-attr]
        self.assertEqual(symbol.find(".//s:stop", NS).get("stop-color"), "#FC6D26")  # type: ignore[union-attr]

    def test_bronze_retains_original_contours_and_colors_body(self) -> None:
        for name in ("briareus", "frame"):
            with self.subTest(name=name):
                marble = brand.read_svg(brand.BRAND / "base" / f"{name}-marble.svg")
                bronze = brand.read_svg(brand.BRAND / "base" / f"{name}.svg")
                for identifier in ("emblem",):
                    original = marble.find(f".//s:path[@id='{identifier}']", NS)
                    recolored = bronze.find(f".//s:path[@id='{identifier}']", NS)
                    assert original is not None and recolored is not None
                    self.assertEqual(original.get("d"), recolored.get("d"))
                self.assertIn("#E87516", {item.get("fill") for item in bronze.iter()})
                self.assertIn("#0A1928", {item.get("fill") for item in bronze.iter()})
                self.assertFalse(bronze.findall(".//s:image", NS))
        main = brand.read_svg(brand.BRAND / "base/briareus.svg")
        body = main.find(".//s:path[@id='body-color']", NS)
        background = main.find(".//s:path[@id='stone-background']", NS)
        assert body is not None and background is not None
        self.assertEqual(body.get("fill"), "#E87516")
        self.assertEqual(background.get("fill"), "#0A1928")

    def test_invalid_input_does_not_create_output(self) -> None:
        cases = (
            f'<svg xmlns="{brand.SVG}" viewBox="0 0 0 10"/>',
            f'<svg xmlns="{brand.SVG}" viewBox="0 0 nan 10"/>',
            f'<svg xmlns="{brand.SVG}" viewBox="0 0 10 10"><image href="icon.png"/></svg>',
            f'<svg xmlns="{brand.SVG}" viewBox="0 0 10 10"><use href="other.svg#x"/></svg>',
            f'<svg xmlns="{brand.SVG}" viewBox="0 0 10 10"><g id="x"/><g id="x"/></svg>',
        )
        with tempfile.TemporaryDirectory() as temporary:
            icon, output = Path(temporary) / "icon.svg", Path(temporary) / "result.svg"
            for text in cases:
                with self.subTest(svg=text):
                    icon.write_text(text, encoding="utf-8")
                    with self.assertRaises(ValueError):
                        brand.compose(icon, output)
                    self.assertFalse(output.exists())

    def test_pixel_dimensions_and_input_overwrite_guard(self) -> None:
        icon = ET.fromstring(f'<svg xmlns="{brand.SVG}" width="240px" height="120px"/>')
        self.assertEqual(brand.view_box(icon), "0 0 240 120")
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "source.svg"
            path.write_text(SYMBOL, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "overwrite"):
                brand.compose(path, path)
            for scale in (0, -1, 2, float("nan")):
                with self.subTest(scale=scale), self.assertRaises(ValueError):
                    brand.compose(path, path.with_name("out.svg"), scale=scale)
            self.assertEqual(path.read_text(encoding="utf-8"), SYMBOL)


if __name__ == "__main__":
    unittest.main()
