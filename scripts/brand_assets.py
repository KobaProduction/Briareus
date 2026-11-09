"""Compose self-contained SVG service icons inside the Briareus brand frames."""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypedDict

ROOT = Path(__file__).resolve().parents[1]
BRAND = ROOT / "assets/brand"
SVG = "http://www.w3.org/2000/svg"
XLINK = "http://www.w3.org/1999/xlink"
ET.register_namespace("", SVG)
ET.register_namespace("xlink", XLINK)
PALETTES = {"marble": ("#E8E5DD", "#171A1D"), "bronze": ("#E87516", "#0A1928")}
# Outer contours and the large central field are structure, not skin/hand fill.
STRUCTURE_CONTOURS = {"logos/briareus": (0, 7, 8), "frames/briareus-ornate": (0, 13)}


@dataclass(frozen=True)
class Frame:
    filename: str
    slot: tuple[float, float, float, float]


FRAMES = {
    "ornate": Frame("briareus-ornate", (262, 262, 500, 500)),
}


def read_svg(path: Path) -> ET.Element:
    text = path.read_text(encoding="utf-8")
    if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        raise ValueError(f"{path}: SVG must not contain a document type or entity declarations")
    root = ET.fromstring(text)
    if root.tag != f"{{{SVG}}}svg":
        raise ValueError(f"{path}: expected an SVG root with the SVG namespace")
    validate_references(root)
    return root


def validate_references(root: ET.Element) -> None:
    for element in root.iter():
        tag = str(element.tag).rsplit("}", 1)[-1].lower()
        if tag in {"script", "foreignobject", "image"}:
            raise ValueError(f"SVG must use vector elements, not {tag}")
        for key, value in element.attrib.items():
            if key.rsplit("}", 1)[-1] == "href" and not value.startswith("#"):
                raise ValueError("SVG references must be local fragments")
        content = " ".join(element.attrib.values())
        if tag == "style":
            content += element.text or ""
        if "@import" in content.lower() or any(
            not match.strip(" \t\r\n\"'").startswith("#")
            for match in re.findall(r"url\(([^)]+)\)", content, flags=re.IGNORECASE)
        ):
            raise ValueError("SVG must be self-contained; external resources are unsupported")


def view_box(root: ET.Element) -> str:
    raw = root.get("viewBox")
    if raw is None:
        dimensions = [root.get(key, "").removesuffix("px") for key in ("width", "height")]
        raw = "0 0 " + " ".join(dimensions)
    try:
        values = [float(value) for value in re.split(r"[\s,]+", raw.strip())]
    except ValueError as error:
        raise ValueError("SVG needs a numeric viewBox or width/height in pixels") from error
    if len(values) != 4 or not all(math.isfinite(value) for value in values):
        raise ValueError("SVG viewBox must contain four finite numbers")
    if values[2] <= 0 or values[3] <= 0:
        raise ValueError("SVG viewBox width and height must be positive")
    return " ".join(f"{value:g}" for value in values)


def rewrite_references(value: str, identities: dict[str, str]) -> str:
    for old, new in identities.items():
        value = re.sub(r"#" + re.escape(old) + r"(?![\w.-])", "#" + new, value)
    return value


def namespace_ids(root: ET.Element, prefix: str) -> None:
    identities: dict[str, str] = {}
    for element in root.iter():
        identifier = element.get("id")
        if identifier is not None:
            if identifier in identities:
                raise ValueError(f"SVG contains duplicate id: {identifier}")
            identities[identifier] = f"{prefix}-{identifier}"
    for element in root.iter():
        rewrite_element(element, identities)


def rewrite_element(element: ET.Element, identities: dict[str, str]) -> None:
    for key, value in list(element.attrib.items()):
        if key == "id":
            element.set(key, identities[value])
        elif key in {"aria-labelledby", "aria-describedby"}:
            element.set(key, " ".join(identities.get(token, token) for token in value.split()))
        else:
            element.set(key, rewrite_references(value, identities))
    if element.tag == f"{{{SVG}}}style" and element.text:
        element.text = rewrite_references(element.text, identities)


def recolor(root: ET.Element, theme: str, structure: tuple[int, ...] = ()) -> None:
    background, foreground = PALETTES[theme]
    for element in root.iter():
        if element.get("id") in {"marble", "stone-background"}:
            element.set("fill", foreground if structure else background)
        elif element.get("id") == "emblem":
            element.set("fill", foreground)
    if structure:
        color_body(root, background, structure)


def color_body(root: ET.Element, color: str, structure: tuple[int, ...]) -> None:
    group = root.find(f"{{{SVG}}}g")
    if group is None:
        raise ValueError("Expected the master geometry group")
    emblem = group.find(f"{{{SVG}}}path[@id='emblem']")
    if emblem is None:
        raise ValueError("Expected the master emblem path")
    contours = [part for part in re.split(r"(?=M )", emblem.get("d", "")) if part.strip()]
    ET.SubElement(
        group,
        f"{{{SVG}}}path",
        {
            "id": "body-color",
            "fill": color,
            "d": " ".join(part for index, part in enumerate(contours) if index not in structure),
        },
    )


def write_svg(root: ET.Element, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(output, encoding="utf-8", xml_declaration=True)


def export_palettes(destination: Path = BRAND) -> None:
    """Rebuild color variants from marble masters, retaining every geometry attribute."""
    for name, structure in (
        ("briareus", STRUCTURE_CONTOURS["logos/briareus"]),
        ("frame", STRUCTURE_CONTOURS["frames/briareus-ornate"]),
    ):
        master = read_svg(destination / "base" / f"{name}-marble.svg")
        recolor(master, "bronze", structure)
        write_svg(master, destination / "base" / f"{name}.svg")


def compose(
    icon: Path,
    output: Path,
    *,
    frame: str = "ornate",
    theme: str = "marble",
    scale: float = 1.0,
    frame_path: Path | None = None,
    slot: tuple[float, ...] | None = None,
    color: str | None = None,
    symbol: ET.Element | None = None,
) -> None:
    if not math.isfinite(scale) or not 0 < scale <= 1.25:
        raise ValueError("Scale must be greater than zero and no greater than 1.25")
    layout = FRAMES[frame]
    frame_path = frame_path or (
        BRAND / "base" / ("frame-marble.svg" if theme == "marble" else "frame.svg")
    )
    if output.resolve() in {icon.resolve(), frame_path.resolve()}:
        raise ValueError("Output must not overwrite the input icon or frame")
    root = read_svg(frame_path)
    symbol = symbol if symbol is not None else read_svg(icon)
    if color:
        symbol.set("color", color)
    symbol.set("viewBox", view_box(symbol))
    namespace_ids(root, "frame")
    namespace_ids(symbol, "service")
    x, y, width, height = slot or layout.slot
    symbol.set("x", f"{x + width * (1 - scale) / 2:g}")
    symbol.set("y", f"{y + height * (1 - scale) / 2:g}")
    symbol.set("width", f"{width * scale:g}")
    symbol.set("height", f"{height * scale:g}")
    symbol.set("preserveAspectRatio", "xMidYMid meet")
    symbol.set("overflow", "hidden")
    if symbol.get("id") is None:
        symbol.set("id", "service-icon")
    title = root.find(f"{{{SVG}}}title")
    if title is not None:
        title.text = f"{icon.stem} / Briareus"
    root.append(symbol)
    write_svg(root, output)


class OverlayPosition(TypedDict):
    source: str
    x: float
    y: float
    width: float
    height: float


class OverlaySettings(OverlayPosition, total=False):
    coordinateSpace: Literal["source", "frame"]


class SymbolAdjustments(TypedDict, total=False):
    viewBox: str
    removeFilters: bool
    fills: dict[str, str]
    removeTags: list[str]
    removePaths: list[str]
    removeClasses: list[str]
    overlay: OverlaySettings


def adjust_element(parent: ET.Element, service: SymbolAdjustments) -> None:
    if service.get("removeFilters"):
        parent.attrib.pop("filter", None)
    fills = service.get("fills", {})
    fill = parent.get("fill")
    if fill is not None and fill in fills:
        parent.set("fill", fills[fill])
    for child in list(parent):
        tag = child.tag.rsplit("}", 1)[-1]
        if tag in service.get("removeTags", []) or any(
            name in child.get("class", "").split() for name in service.get("removeClasses", [])
        ) or (
            tag == "path" and child.get("d") in service.get("removePaths", [])
        ):
            parent.remove(child)


def prepare_symbol(source: Path, service: SymbolAdjustments, base: Path) -> ET.Element:
    prepared = read_svg(source)
    if "viewBox" in service:
        prepared.set("viewBox", service["viewBox"])
        view_box(prepared)
    for parent in prepared.iter():
        adjust_element(parent, service)
    if "overlay" in service and service["overlay"].get("coordinateSpace", "source") == "source":
        append_overlay(prepared, service["overlay"], base)
    return prepared


def append_overlay(parent: ET.Element, overlay: OverlaySettings, base: Path) -> None:
    badge = read_svg(base / overlay["source"])
    namespace_ids(badge, "badge")
    for attribute in ("x", "y", "width", "height"):
        badge.set(attribute, str(overlay[attribute]))
    parent.append(badge)


def append_frame_overlay(output: Path, service: SymbolAdjustments, base: Path) -> None:
    if "overlay" not in service or service["overlay"].get("coordinateSpace") != "frame":
        return
    root = read_svg(output)
    append_overlay(root, service["overlay"], base)
    write_svg(root, output)


def build_all(config_path: Path) -> None:
    config_path = config_path.resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    base = config_path.parent
    jobs = []
    output_dir = base / config["output"]
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, service in config["services"].items():
        for theme, palette in config["themes"].items():
            source = service["source"]
            source = base / (source[theme] if isinstance(source, dict) else source)
            prepared = prepare_symbol(source, service, base)
            output = output_dir / f"{name}.svg"
            compose(
                source,
                output,
                theme=theme,
                frame_path=base / palette["frame"],
                slot=tuple(config["slot"]),
                scale=service.get("scale", 1),
                color=palette["symbolColor"] if service.get("currentColor") else None,
                symbol=prepared,
            )
            append_frame_overlay(output, service, base)
            jobs.append({"svg": str(output), "png": str(output.with_suffix(".png"))})
    # One renderer process for the whole batch. No network or archive creation.
    request = {"png": config["png"], "jobs": jobs, "base": str(base)}
    subprocess.run(
        ["node", str(ROOT / "scripts/brand/render.mjs")],
        input=json.dumps(request),
        text=True,
        check=True,
    )
    if config.get("frontendLogo"):
        target = (base / config["frontendLogo"]).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(base / "base/briareus.svg", target)
        print(f"Frontend logo: {target}")
    if config.get("frontendFavicon"):
        favicon = config["frontendFavicon"]
        target = (base / favicon["output"]).resolve()
        root = read_svg(base / "base/briareus.svg")
        root.set("viewBox", favicon["viewBox"])
        root.set("width", "32")
        root.set("height", "32")
        write_svg(root, target)
        print(f"Frontend favicon: {target}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("palettes", help="Regenerate bronze files from marble SVG masters")
    batch = commands.add_parser("build", help="Rebuild configured SVGs and size-limited PNGs")
    batch.add_argument("--config", type=Path, default=BRAND / "build.json")
    build = commands.add_parser("compose", help="Place a supplied service SVG inside a frame")
    build.add_argument("--icon", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--frame", choices=FRAMES, default="ornate")
    build.add_argument("--theme", choices=PALETTES, default="marble")
    build.add_argument(
        "--scale", type=float, default=1.0, help="Fraction of the center slot (0, 1.25]"
    )
    args = parser.parse_args()
    try:
        if args.command == "palettes":
            export_palettes()
        elif args.command == "build":
            build_all(args.config)
        else:
            compose(args.icon, args.output, frame=args.frame, theme=args.theme, scale=args.scale)
    except (OSError, ValueError, ET.ParseError, subprocess.CalledProcessError) as error:
        print(f"brand_assets: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
