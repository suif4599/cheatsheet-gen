from pathlib import Path
from typing import Literal
import re

from utils.pdf import svg2pdf, pdf2svg, parse_page_size, pdf_size
from utils.svg import split_svg, concat_svg, empty_svg, scale_svg_vertical

def gen_cheatsheet(
    input_pdf: Path,
    svg_dir: Path,
    output_pdf: Path,
    page_size: str,
    orientation: Literal["horizontal", "vertical"],
    input_rows: int,
    y_limit: float,
    target_pages: int,
    page_ranges: str,
    safe_split_ratio: float,
    safe_cut_ratio: float,
    y_scale: float,
):
    if not (0 < y_scale <= 1):
        raise ValueError(f"y_scale 必须在 (0, 1] 范围内，当前为 {y_scale}")
    old_page_ranges_list: dict[int, tuple[int, int]] = {}
    page_no = 0
    for page_range in page_ranges.split(";"):
        page_range = page_range.strip()
        if not page_range:
            continue
        page_no += 1
        if "=" not in page_range:
            page_range = f"{page_no}={page_range}"
        match = re.match(r"(\d+)=(-?\d*):(-?\d*)", page_range)
        if not match:
            raise ValueError(f"Invalid page range format: {page_range}")
        page_no = int(match.group(1))
        start = int(match.group(2)) if match.group(2) else 0
        end = int(match.group(3)) if match.group(3) else input_rows
        if start < 0:
            start = input_rows + start
        if end < 0:
            end = input_rows + end
        if not (0 <= start <= end <= input_rows):
            raise ValueError(f"Invalid page range values: {page_range}")
        old_page_ranges_list[page_no] = (start, end)

    svg_dir.mkdir(parents=True, exist_ok=True)
    for file in svg_dir.glob("*"):
        if file.is_file():
            file.unlink()

    old_input_pages = pdf2svg(input_pdf, svg_dir)
    input_pages: list[Path] = []
    page_ranges_list: dict[int, tuple[int, int]] = {}
    for page_no in range(1, len(old_input_pages) + 1):
        if page_no in old_page_ranges_list and old_page_ranges_list[page_no][0] >= old_page_ranges_list[page_no][1]:
            old_input_pages[page_no - 1].unlink()
            continue
        input_pages.append(old_input_pages[page_no - 1])
        if page_no in old_page_ranges_list:
            page_ranges_list[len(input_pages)] = old_page_ranges_list[page_no]

    # --- Geometry model -------------------------------------------------------
    # Each input page physically holds `input_rows` real content rows that
    # evenly occupy the top `y_limit` fraction of the page. One real row is
    # therefore `y_limit * input_height / input_rows` tall, and that real row
    # is the atomic "strip" unit used for every cut and every grid cell below.
    #
    # `safe_cut_ratio` keeps a fraction of the bottom strip that `y_limit`
    # would otherwise discard, so the retained region grows from `y_limit` to
    # `effective_y_limit`. That extra bottom strip is genuine (overflow)
    # content: it is *not* one of the `input_rows` rows, so it is accounted for
    # as a fractional number of extra rows (`extra_rows`) attached to any page
    # whose range reaches the bottom.
    effective_y_limit = y_limit + (1 - y_limit) * safe_cut_ratio
    extra_rows = input_rows * (effective_y_limit - y_limit) / y_limit

    # Compress every row vertically by `y_scale` via a vector transform. All
    # cuts below are fractions of the page, so they are unaffected; only the
    # absolute row height (and thus strip_ratio / blank_height) changes.
    if y_scale != 1.0:
        for svg_file in input_pages:
            scale_svg_vertical(svg_file, y_scale)

    # Keep the retained region [0, effective_y_limit] of every page.
    for svg_file in input_pages:
        split_svg(svg_file, svg_file, None, effective_y_limit)

    # A full page contributes its `input_rows` real rows plus the extra bottom
    # strip. A ranged page contributes only the rows inside its range, plus the
    # extra strip only when the range reaches the bottom of the page.
    available_rows: list[float] = [input_rows + extra_rows] * len(input_pages)
    # `safe_split_ratio` has a second meaning for page-range cuts: it extends a
    # range slightly past its real-row boundary so the cut shows a sliver of the
    # neighbouring row as context. A positive value extends the BOTTOM cut
    # downward (the last row pulls in part of the row below it); a negative
    # value extends the TOP cut upward (the first row pulls in part of the row
    # above it). The extension is |safe_split_ratio| standard rows and only
    # applies where a neighbouring real row exists — the page bottom uses the
    # safe_cut extra strip instead, never this. This is independent of the
    # column-switch overlap behaviour in the stitching loop below.
    extra_down = max(safe_split_ratio, 0.0)   # extends the bottom cut downward
    extra_up = max(-safe_split_ratio, 0.0)    # extends the top cut upward
    for page_no, (start, end) in page_ranges_list.items():
        if page_no < 1 or page_no > len(input_pages):
            raise ValueError(f"Page number {page_no} is out of range (1-{len(input_pages)})")
        # Retained region in row units is [lo, hi]. Real rows occupy [0, y_limit],
        # i.e. the top `y_limit / effective_y_limit` fraction of the retained
        # page, so a row position r maps to the fraction
        # `r / input_rows * y_limit / effective_y_limit` of the page. The bottom
        # cut is applied first so the two cuts reference the same page and do
        # not compound (which previously stretched interior ranges such as "2:3").
        page = input_pages[page_no - 1]
        bottom_cut = end < input_rows
        if bottom_cut:
            hi = end + extra_down
            split_svg(page, page, None, hi / input_rows * y_limit / effective_y_limit)
        else:
            # Range reaches the page bottom: keep full real rows + extra strip.
            # No bottom extension here (no real row below to pull from).
            hi = input_rows + extra_rows
        if start > 0:
            lo = start - extra_up
            if lo > 0:
                if bottom_cut:
                    # Page now spans rows [0, hi], so cut at lo / hi.
                    split_svg(page, None, page, lo / hi)
                else:
                    split_svg(page, None, page, lo / input_rows * y_limit / effective_y_limit)
            else:
                lo = 0.0
        else:
            lo = 0.0
        available_rows[page_no - 1] = hi - lo
        if available_rows[page_no - 1] <= 0:
            raise ValueError(f"Invalid row range for page {page_no}: start={start}, end={end}")
    input_strips = sum(available_rows)

    total_width, total_height = parse_page_size(page_size)
    if orientation == "horizontal":
        total_height, total_width = total_width, total_height
    input_width, input_height = pdf_size(input_pdf)
    # One strip is exactly one real row, scaled vertically by `y_scale`.
    strip_ratio = input_height * y_limit / input_rows / input_width * y_scale
    cols = 1
    rows = -1
    while True:
        strip_height = total_width / cols * strip_ratio
        rows = int(total_height / strip_height)
        available_strips = rows * cols * target_pages
        if available_strips >= input_strips:
            break
        cols += 1
    print(f"Need {cols} columns to fit {len(input_pages)} pages into {target_pages} {orientation} pages.")
    cap = rows * cols * target_pages
    if cols > 1:
        rows_prev = int(total_height / (total_width / (cols - 1) * strip_ratio))
        cap_prev = rows_prev * (cols - 1) * target_pages
        print(
            f"  Capacity: {cols} columns ≈ {cap} standard rows ({rows}/col), "
            f"{cols - 1} columns ≈ {cap_prev} standard rows ({rows_prev}/col); "
            f"content ≈ {input_strips:.1f} rows."
        )
    else:
        print(f"  Capacity: {cols} column ≈ {cap} standard rows; content ≈ {input_strips:.1f} rows.")

    original_pages_count = len(input_pages)
    # A blank fills `input_rows` strips (real rows), matching the grid cell.
    blank_height = input_height * y_limit * y_scale
    blank_width = input_width
    blank_digits = max(3, len(str(original_pages_count)))
    for page_no in range(1, original_pages_count + 1):
        blank_path = svg_dir / f"blank_{page_no:0{blank_digits}d}.svg"
        input_pages.append(empty_svg(blank_width, blank_height, blank_path))
    available_rows += [input_rows] * original_pages_count

    current_page_index = 0
    this_page_rows = available_rows[0]
    page_tmp: Path | None = None
    for page_no in range(1, target_pages + 1):
        col_tmp: Path | None = None
        for col in range(1, cols + 1):
            current_rows = 0
            row_tmp: Path | None = None
            while True:
                if current_rows + this_page_rows > rows:
                    # Need to split: keep `keep` rows in this column and send
                    # the remaining `spill` rows to the next column.
                    keep = rows - current_rows
                    page_rows = this_page_rows
                    spill = page_rows - keep
                    page = input_pages[current_page_index]
                    if safe_split_ratio == 0 or abs(safe_split_ratio) >= spill:
                        # No overlap, or the spillover is too small to fit one:
                        # plain split at the real boundary.
                        split_svg(page, svg_dir / "up.svg", page, keep / page_rows)
                    elif safe_split_ratio > 0:
                        # Positive overlap: the boundary rows appear in both
                        # this column (end) and the next column (start).
                        split_svg(page, svg_dir / "up.svg", None, (keep + safe_split_ratio) / page_rows)
                        split_svg(page, None, page, keep / page_rows)
                    else:
                        # Negative overlap: skip |safe_split_ratio| rows at the
                        # boundary (a small gap between the two columns).
                        split_svg(page, svg_dir / "up.svg", None, keep / page_rows)
                        split_svg(page, None, page, (keep - safe_split_ratio) / page_rows)
                    if row_tmp is not None:
                        concat_svg(
                            row_tmp,
                            svg_dir / "up.svg",
                            row_tmp,
                            orientation="vertical",
                            draw_separator=False,
                        )
                    else:
                        row_tmp = svg_dir / "row_tmp.svg"
                        (svg_dir / "up.svg").rename(row_tmp)
                    this_page_rows = current_rows + available_rows[current_page_index] - rows
                    break
                # No split needed, just concatenate
                if row_tmp is not None:
                    concat_svg(
                        row_tmp,
                        input_pages[current_page_index],
                        row_tmp,
                        orientation="vertical",
                        draw_separator=False,
                    )
                else:
                    row_tmp = svg_dir / "row_tmp.svg"
                    input_pages[current_page_index].rename(row_tmp)
                current_rows += this_page_rows
                current_page_index += 1
                if current_page_index >= len(input_pages):
                    raise ValueError("Not enough input pages to fill the target pages with the given page ranges.")
                this_page_rows = available_rows[current_page_index]
                if current_rows >= rows:
                    break
            if row_tmp is None:
                raise ValueError("Unexpected error: row_tmp should not be None here")
            if col_tmp is not None:
                concat_svg(
                    col_tmp,
                    row_tmp,
                    col_tmp,
                    orientation="horizontal",
                )
                row_tmp.unlink()
            else:
                col_tmp = svg_dir / "col_tmp.svg"
                row_tmp.rename(col_tmp)
        if col_tmp is None:
            raise ValueError("Unexpected error: col_tmp should not be None here")
        page_tmp = svg_dir / f"page_{page_no:03d}.svg"
        col_tmp.rename(page_tmp)

    for temp_file in input_pages + list(svg_dir.glob("row_tmp.svg")) + list(svg_dir.glob("col_tmp.svg")) + list(svg_dir.glob("up.svg")):
        if temp_file.exists():
            temp_file.unlink()
    svg2pdf(svg_dir, output_pdf, page_size, orientation)
