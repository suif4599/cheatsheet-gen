#!/usr/bin/env python3
"""Split one SVG into two parts by a height ratio."""

from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Literal, Tuple
from uuid import uuid4
from xml.etree import ElementTree as ET


SVG_NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVG_NS)


def _local_name(tag: str) -> str:
	if tag.startswith("{") and "}" in tag:
		return tag.split("}", 1)[1]
	return tag


def _strip_unit(value: str | None) -> float | None:
	if value is None:
		return None
	match = re.match(r"^\s*([+-]?(?:\d+\.\d+|\d+|\.\d+))", value)
	if not match:
		return None
	return float(match.group(1))


def _get_root(svg_path: Path) -> ET.Element:
	tree = ET.parse(svg_path)
	root = tree.getroot()
	if _local_name(root.tag) != "svg":
		raise ValueError("输入文件不是合法的 SVG 根节点")
	return root


def _read_viewport(root: ET.Element) -> Tuple[float, float, float, float]:
	view_box = root.get("viewBox")
	if view_box:
		parts = re.split(r"[\s,]+", view_box.strip())
		if len(parts) != 4:
			raise ValueError("viewBox 格式无效，期望 4 个数字")
		x, y, width, height = map(float, parts)
		if width <= 0 or height <= 0:
			raise ValueError("viewBox 宽高必须大于 0")
		return x, y, width, height

	width = _strip_unit(root.get("width"))
	height = _strip_unit(root.get("height"))
	if width is None or height is None:
		raise ValueError("SVG 缺少可解析的 viewBox 或 width/height")
	if width <= 0 or height <= 0:
		raise ValueError("width/height 必须大于 0")
	return 0.0, 0.0, width, height


def split_svg(input_svg: Path | str, up_path: Path | str | None, down_path: Path | str | None, cut_ratio: float):
	"""Split one SVG into two files by vertical ratio.

	Args:
		input_svg: Input SVG path.
		up_path: Path for the upper part.
		down_path: Path for the lower part.
		cut_ratio: Ratio in (0, 1), measured from top to bottom.

	Returns:
		A tuple of output paths: (up.svg, down.svg).
	"""
	input_path = Path(input_svg)
	up_path = Path(up_path) if up_path is not None else None
	down_path = Path(down_path) if down_path is not None else None

	if not input_path.exists() or not input_path.is_file():
		raise ValueError(f"输入 SVG 不存在或不是文件: {input_path}")
	if not (0 < cut_ratio < 1):
		raise ValueError("cut_ratio 必须在 0 和 1 之间（不含端点）")

	root = _get_root(input_path)
	x, y, width, height = _read_viewport(root)

	up_h = height * cut_ratio
	down_y = y + up_h
	down_h = (y + height) - down_y

	up_root = copy.deepcopy(root)
	up_root.set("viewBox", f"{x} {y} {width} {up_h}")
	up_root.set("width", f"{width}")
	up_root.set("height", f"{up_h}")

	down_root = copy.deepcopy(root)
	down_root.set("viewBox", f"{x} {down_y} {width} {down_h}")
	down_root.set("width", f"{width}")
	down_root.set("height", f"{down_h}")

	if up_path is not None:
		up_path.parent.mkdir(parents=True, exist_ok=True)
		ET.ElementTree(up_root).write(up_path, encoding="utf-8", xml_declaration=True)
	if down_path is not None:
		down_path.parent.mkdir(parents=True, exist_ok=True)
		ET.ElementTree(down_root).write(down_path, encoding="utf-8", xml_declaration=True)


def scale_svg_vertical(svg_path: Path | str, factor: float) -> Path:
	"""Scale an SVG's content vertically by ``factor``, in place.

	The width is unchanged; the height becomes ``height * factor`` and the
	content is squished or stretched with a pure vector transform (no
	rasterization). ``factor`` of 0.9 compresses every row to 90% of its
	height. Because all downstream cuts are expressed as fractions of the
	page, they remain valid after this scaling.
	"""
	if factor <= 0:
		raise ValueError("factor 必须大于 0")
	svg_path = Path(svg_path)
	root = _get_root(svg_path)
	x, y, width, height = _read_viewport(root)

	new_height = height * factor
	# Wrap the existing content in a group scaled about the viewport's top
	# edge (y), so a point py maps to y + (py - y) * factor.
	group = ET.Element(f"{{{SVG_NS}}}g")
	group.set("transform", f"translate(0 {y * (1 - factor)}) scale(1 {factor})")
	for child in list(root):
		group.append(child)
	root.append(group)

	root.set("viewBox", f"{x} {y} {width} {new_height}")
	root.set("width", f"{width}")
	root.set("height", f"{new_height}")
	ET.ElementTree(root).write(svg_path, encoding="utf-8", xml_declaration=True)
	return svg_path


def concat_svg(
	first_svg: Path | str,
	second_svg: Path | str,
	output_svg: Path | str,
	orientation: Literal["horizontal", "vertical"] = "vertical",
	draw_separator: bool = True,
) -> Path:
	"""Concatenate two SVG files into one SVG with configurable orientation.

	When orientation is:
	- "vertical": first on top, second below
	- "horizontal": first on left, second on right
	"""
	first_path = Path(first_svg)
	second_path = Path(second_svg)
	out_path = Path(output_svg)

	if orientation not in ("horizontal", "vertical"):
		raise ValueError("orientation 必须是 'horizontal' 或 'vertical'")

	if not first_path.exists() or not first_path.is_file():
		raise ValueError(f"第一个 SVG 不存在或不是文件: {first_path}")
	if not second_path.exists() or not second_path.is_file():
		raise ValueError(f"第二个 SVG 不存在或不是文件: {second_path}")

	first_root = _get_root(first_path)
	second_root = _get_root(second_path)

	_, _, first_w, first_h = _read_viewport(first_root)
	_, _, second_w, second_h = _read_viewport(second_root)

	if orientation == "vertical":
		out_w = max(first_w, second_w)
		out_h = first_h + second_h
		first_x, first_y = 0.0, 0.0
		second_x, second_y = 0.0, first_h
	else:
		out_w = first_w + second_w
		out_h = max(first_h, second_h)
		first_x, first_y = 0.0, 0.0
		second_x, second_y = first_w, 0.0

	out_root = ET.Element(f"{{{SVG_NS}}}svg")
	out_root.set("viewBox", f"0 0 {out_w} {out_h}")
	out_root.set("width", f"{out_w}")
	out_root.set("height", f"{out_h}")
	defs = ET.SubElement(out_root, f"{{{SVG_NS}}}defs")

	clip_prefix = uuid4().hex

	def _append_as_group(src_root: ET.Element, place_x: float, place_y: float, slot_w: float, slot_h: float, idx: int) -> None:
		src_x, src_y, _, _ = _read_viewport(src_root)
		tx = place_x - src_x
		ty = place_y - src_y

		clip_id = f"concat_clip_{clip_prefix}_{idx}"
		clip = ET.SubElement(defs, f"{{{SVG_NS}}}clipPath")
		clip.set("id", clip_id)
		clip_rect = ET.SubElement(clip, f"{{{SVG_NS}}}rect")
		clip_rect.set("x", f"{place_x}")
		clip_rect.set("y", f"{place_y}")
		clip_rect.set("width", f"{slot_w}")
		clip_rect.set("height", f"{slot_h}")

		group = ET.SubElement(out_root, f"{{{SVG_NS}}}g")
		group.set("clip-path", f"url(#{clip_id})")
		inner = ET.SubElement(group, f"{{{SVG_NS}}}g")
		inner.set("transform", f"translate({tx} {ty})")
		for child in list(src_root):
			inner.append(copy.deepcopy(child))

	_append_as_group(first_root, first_x, first_y, first_w, first_h, idx=1)
	_append_as_group(second_root, second_x, second_y, second_w, second_h, idx=2)

	if draw_separator:
		# Draw a separator line at the stitch boundary to avoid visible seam artifacts.
		line = ET.SubElement(out_root, f"{{{SVG_NS}}}line")
		if orientation == "vertical":
			boundary = first_h
			line.set("x1", "0")
			line.set("y1", f"{boundary}")
			line.set("x2", f"{out_w}")
			line.set("y2", f"{boundary}")
		else:
			boundary = first_w
			line.set("x1", f"{boundary}")
			line.set("y1", "0")
			line.set("x2", f"{boundary}")
			line.set("y2", f"{out_h}")
		line.set("stroke", "#000000")
		line.set("stroke-width", "1")
		line.set("vector-effect", "non-scaling-stroke")

	out_path.parent.mkdir(parents=True, exist_ok=True)
	ET.ElementTree(out_root).write(out_path, encoding="utf-8", xml_declaration=True)
	return out_path


def empty_svg(width: float, height: float, output: Path | str) -> Path:
	"""Create an empty SVG with the given size."""
	if width <= 0 or height <= 0:
		raise ValueError("width 和 height 必须大于 0")

	out_path = Path(output)
	out_root = ET.Element(f"{{{SVG_NS}}}svg")
	out_root.set("viewBox", f"0 0 {width} {height}")
	out_root.set("width", f"{width}")
	out_root.set("height", f"{height}")

	bg = ET.SubElement(out_root, f"{{{SVG_NS}}}rect")
	bg.set("x", "0")
	bg.set("y", "0")
	bg.set("width", f"{width}")
	bg.set("height", f"{height}")
	bg.set("fill", "#ffffff")

	out_path.parent.mkdir(parents=True, exist_ok=True)
	ET.ElementTree(out_root).write(out_path, encoding="utf-8", xml_declaration=True)
	return out_path
