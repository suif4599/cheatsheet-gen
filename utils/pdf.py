from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
from typing import Literal

from reportlab.graphics import renderPDF
from reportlab.lib.pagesizes import A0, A1, A2, A3, A4, A5, A6, LEGAL, LETTER
from reportlab.pdfgen import canvas
from svglib.svglib import svg2rlg


_PAGE_SIZES = {
	"A0": A0,
	"A1": A1,
	"A2": A2,
	"A3": A3,
	"A4": A4,
	"A5": A5,
	"A6": A6,
	"LETTER": LETTER,
	"LEGAL": LEGAL,
}


def parse_page_size(page: str) -> tuple[float, float]:
	"""Parse page size from name or numeric format.

	Supported values:
	- Standard names: A4, A3, LETTER, LEGAL (case-insensitive)
	- Custom numeric: "595x842" (points)
	"""
	key = page.strip().upper()
	if key in _PAGE_SIZES:
		return _PAGE_SIZES[key]

	if "X" in key:
		left, right = key.split("X", 1)
		try:
			w = float(left)
			h = float(right)
		except ValueError as exc:
			raise ValueError(f"无效页面尺寸: {page}") from exc
		if w <= 0 or h <= 0:
			raise ValueError(f"页面宽高必须大于 0: {page}")
		return (w, h)

	raise ValueError(
		"不支持的页面大小。可用示例: A4, A3, LETTER, LEGAL, 595x842"
	)


def _apply_orientation(
	page_w: float,
	page_h: float,
	orientation: Literal["horizontal", "vertical"],
) -> tuple[float, float]:
	if orientation == "horizontal":
		return (max(page_w, page_h), min(page_w, page_h))
	return (min(page_w, page_h), max(page_w, page_h))


def svg2pdf(
	svg_dir: Path,
	output: Path,
	page: str = "A4",
	orientation: Literal["horizontal", "vertical"] = "vertical",
) -> None:
	"""Convert sorted SVG files in a directory to a multi-page vector PDF.

	Each SVG becomes one page. SVG content is uniformly scaled to fit the page
	while preserving aspect ratio, and centered on the page.
	"""
	if not svg_dir.exists() or not svg_dir.is_dir():
		raise ValueError(f"svg_dir 不存在或不是目录: {svg_dir}")
	if orientation not in ("horizontal", "vertical"):
		raise ValueError("orientation 必须是 'horizontal' 或 'vertical'")

	page_w, page_h = parse_page_size(page)
	page_w, page_h = _apply_orientation(page_w, page_h, orientation)
	svg_files = sorted(
		(p for p in svg_dir.iterdir() if p.is_file() and p.suffix.lower() == ".svg"),
		key=lambda p: p.name,
	)
	if not svg_files:
		raise ValueError(f"目录中未找到 SVG 文件: {svg_dir}")

	output.parent.mkdir(parents=True, exist_ok=True)
	pdf = canvas.Canvas(str(output), pagesize=(page_w, page_h))

	for svg_path in svg_files:
		# Ensure no leftover transform state affects this page.
		pdf.resetTransforms()

		drawing = svg2rlg(str(svg_path))
		if drawing is None:
			raise ValueError(f"SVG 解析失败: {svg_path}")

		dw = float(drawing.width)
		dh = float(drawing.height)
		if dw <= 0 or dh <= 0:
			raise ValueError(f"SVG 尺寸无效: {svg_path}")

		scale = min(page_w / dw, page_h / dh)
		fit_w = dw * scale
		fit_h = dh * scale
		offset_x = (page_w - fit_w) / 2.0
		offset_y = (page_h - fit_h) / 2.0

		pdf.saveState()
		pdf.translate(offset_x, offset_y)
		pdf.scale(scale, scale)

		# Clip to the SVG drawing box, so out-of-bounds vector objects do not bleed.
		clip_path = pdf.beginPath()
		clip_path.rect(0, 0, dw, dh)
		pdf.clipPath(clip_path, stroke=0, fill=0)

		renderPDF.draw(drawing, pdf, 0, 0)
		pdf.restoreState()
		pdf.showPage()

	pdf.save()


def pdf2svg(pdf: Path, output: Path) -> list[Path]:
	"""Convert a PDF into per-page SVG files with zero-padded ascending names.

	Output files are written as page_01.svg, page_02.svg, ...
	"""
	if not pdf.exists() or not pdf.is_file():
		raise ValueError(f"pdf 不存在或不是文件: {pdf}")

	if output.exists() and not output.is_dir():
		raise ValueError(f"output 已存在但不是目录: {output}")
	output.mkdir(parents=True, exist_ok=True)

	pdf2svg_cmd = shutil.which("pdf2svg")
	if pdf2svg_cmd is None:
		raise ValueError("未找到 pdf2svg 命令，请先安装 pdf2svg")
	pdfinfo_cmd = shutil.which("pdfinfo")
	if pdfinfo_cmd is None:
		raise ValueError("未找到 pdfinfo 命令，无法获取 PDF 总页数")

	info = subprocess.run(
		[pdfinfo_cmd, str(pdf)],
		capture_output=True,
		text=True,
	)
	if info.returncode != 0:
		err = (info.stderr or info.stdout or "").strip()
		extra = f"，错误信息: {err}" if err else ""
		raise ValueError(f"读取 PDF 信息失败{extra}")

	total_pages = 0
	for line in info.stdout.splitlines():
		if line.startswith("Pages:"):
			count_text = line.split(":", 1)[1].strip()
			try:
				total_pages = int(count_text)
			except ValueError as exc:
				raise ValueError(f"无法解析 PDF 页数: {count_text}") from exc
			break

	if total_pages <= 0:
		raise ValueError("未能获取有效 PDF 页数")

	width = max(2, len(str(total_pages)))
	out_files: list[Path] = []

	for page_no in range(1, total_pages + 1):
		out_path = output / f"page_{page_no:0{width}d}.svg"
		proc = subprocess.run(
			[pdf2svg_cmd, str(pdf), str(out_path), str(page_no)],
			capture_output=True,
			text=True,
		)
		if proc.returncode != 0:
			err = (proc.stderr or proc.stdout or "").strip()
			extra = f"，错误信息: {err}" if err else ""
			raise ValueError(f"导出第 {page_no} 页失败{extra}")
		if not out_path.exists() or out_path.stat().st_size == 0:
			raise ValueError(f"导出第 {page_no} 页失败: 输出为空文件")
		out_files.append(out_path)

	return out_files


def pdf_size(pdf: Path) -> tuple[float, float]:
	"""Get the width and height of the first page of a PDF in points."""
	if not pdf.exists() or not pdf.is_file():
		raise ValueError(f"pdf 不存在或不是文件: {pdf}")

	pdfinfo_cmd = shutil.which("pdfinfo")
	if pdfinfo_cmd is None:
		raise ValueError("未找到 pdfinfo 命令，无法获取 PDF 信息")

	info = subprocess.run(
		[pdfinfo_cmd, str(pdf)],
		capture_output=True,
		text=True,
	)
	if info.returncode != 0:
		err = (info.stderr or info.stdout or "").strip()
		extra = f"，错误信息: {err}" if err else ""
		raise ValueError(f"读取 PDF 信息失败{extra}")

	width = height = 0.0
	for line in info.stdout.splitlines():
		if line.startswith("Page size:"):
			size_text = line.split(":", 1)[1].strip()
			try:
				dimensions = size_text.split("pts")[0].strip()
				w_str, h_str = dimensions.lower().split("x", 1)
				width = float(w_str.strip())
				height = float(h_str.strip())
			except Exception as exc:
				raise ValueError(f"无法解析 PDF 页面尺寸: {size_text}") from exc
			break

	if width <= 0 or height <= 0:
		raise ValueError("未能获取有效的 PDF 页面尺寸")

	return width, height
