import argparse
from pathlib import Path
from tempfile import TemporaryDirectory

from utils.cheatsheet import gen_cheatsheet


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate a compact cheat sheet PDF from an input PDF.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "input",
        type=Path,
        help="Path to the source PDF.",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=Path("output.pdf"),
        help="Path to the generated PDF.",
    )
    parser.add_argument(
        "--page-size", "-s",
        default="A4",
        help="Output page size. Use a standard size such as A4 or Letter, or a custom '{width}x{height}' size in points.",
    )
    parser.add_argument(
        "--orientation", "-r",
        choices=("horizontal", "vertical"),
        default="horizontal",
        help="Page arrangement direction in the output PDF.",
    )
    parser.add_argument(
        "--input-rows", "-n",
        type=int,
        default=17,
        help="Number of rows per input PDF page.",
    )
    parser.add_argument(
        "--y-limit", "-y",
        type=float,
        default=0.972,
        help="Fraction of each page treated as redundant content, between 0 and 1.",
    )
    parser.add_argument(
        "--target-pages", "-t",
        type=int,
        default=2,
        help="Target number of pages in the output PDF.",
    )
    parser.add_argument(
        "--page-ranges", "-p",
        default="",
        help=(
            "Page range specification. Entries are separated by ';' and each entry uses "
            "[page_no=][start]:[end]. Page numbers start at 1; row numbers start at 0 and "
            "may be negative to count from the end."
        ),
    )
    parser.add_argument(
        "--safe-split-ratio", "-S",
        type=float,
        default=0.3,
        help=(
            "Overlap ratio in [-1, 1] with two effects. (1) When stitching across "
            "columns, a positive value overlaps the boundary rows into the current "
            "column and a negative value leaves a small gap. (2) When a page range is "
            "cut between real rows, a positive value extends the bottom cut down by "
            "this fraction of a row (showing part of the next row) and a negative "
            "value extends the top cut up by this fraction of a row (showing part of "
            "the previous row)."
        ),
    )
    parser.add_argument(
        "--safe-cut-ratio", "-c",
        type=float,
        default=0.5,
        help=(
            "Ratio of the bottom strip (cut by y-limit) to preserve, in the range [0, 1]. "
            "This allows keeping more content from the bottom of each page by adjusting "
            "the effective cut position relative to the discarded strip height."
        ),
    )
    parser.add_argument(
        "--y-scale",
        type=float,
        default=None,
        help=(
            "Vertical compression applied to every row via a vector transform, in the "
            "range (0, 1]. E.g. 0.9 squishes each row to 90%% of its height so more rows "
            "fit per page while keeping the content fully vector. If omitted, after the "
            "layout is solved the program checks whether a modest auto-detected "
            "compression would fit the content into one fewer column and asks before "
            "applying it; pass 1.0 explicitly to skip that check."
        ),
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    with TemporaryDirectory() as temp_dir:
        gen_cheatsheet(
            args.input,
            Path(temp_dir),
            args.output,
            args.page_size,
            args.orientation,
            args.input_rows,
            args.y_limit,
            args.target_pages,
            args.page_ranges,
            args.safe_split_ratio,
            args.safe_cut_ratio,
            args.y_scale,
        )

# python main.py --page-ranges ":-3;:0;:-4;:-2;6=:-4" "复习.pdf"

if __name__ == "__main__":
    main()
