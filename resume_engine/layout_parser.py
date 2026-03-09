"""
Layout Parser — Header/Body Block Separation (PyMuPDF)

Extracts text blocks from PDF pages and separates them into:
  - header_blocks: text from top 20% of first page (name, contact)
  - body_blocks:   text from remaining 80%
  - ordered_text:  full vertically-ordered text

Uses page.get_text("blocks") for position-aware extraction.
"""

import logging
import fitz  # PyMuPDF

logger = logging.getLogger('resume_engine.layout_parser')

HEADER_RATIO = 0.20  # Top 20% of page height = header region
Y_MERGE_THRESHOLD = 5  # px tolerance for "same row" in multi-column merging


# ═══════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ═══════════════════════════════════════════════════════════════════════════

def extract_layout_blocks(pdf_path: str) -> dict:
    """
    Layout-aware PDF extraction with header/body separation.

    Returns:
        {
            "header_blocks": [str, ...],   # text from top 20% of page 1
            "body_blocks":   [str, ...],   # text from rest of document
            "ordered_text":  str,          # full text, vertically ordered
        }
    """
    logger.info(f"📄 Layout-aware block extraction: {pdf_path}")
    doc = fitz.open(pdf_path)

    header_blocks = []
    body_blocks = []
    all_lines = []

    for page_num, page in enumerate(doc):
        blocks = page.get_text("blocks")
        # Format: (x0, y0, x1, y1, text, block_no, block_type)
        # block_type 0 = text, 1 = image

        text_blocks = [b for b in blocks if b[6] == 0 and b[4].strip()]
        if not text_blocks:
            continue

        # Sort by vertical position, then horizontal
        text_blocks.sort(key=lambda b: (round(b[1], 1), b[0]))

        page_height = page.rect.height
        page_width = page.rect.width
        header_cutoff = page_height * HEADER_RATIO

        # ── Multi-column merge ──────────────────────────────────────────
        merged = _merge_columns(text_blocks, page_width)

        # ── Separate header vs body (first page only) ───────────────────
        if page_num == 0:
            for block in text_blocks:
                y0 = block[1]
                text = block[4].strip()
                if not text:
                    continue
                if y0 <= header_cutoff:
                    header_blocks.append(text)
                else:
                    body_blocks.append(text)

            logger.info(f"   Page 1: header cutoff={header_cutoff:.0f}px "
                        f"({len(header_blocks)} header, {len(body_blocks)} body blocks)")
        else:
            for block in text_blocks:
                text = block[4].strip()
                if text:
                    body_blocks.append(text)

        all_lines.extend(merged)
        logger.info(f"   Page {page_num + 1}: {len(text_blocks)} blocks → {len(merged)} merged lines")

    doc.close()

    ordered_text = '\n'.join(all_lines)
    logger.info(f"   ✅ Layout: {len(ordered_text)} chars, "
                f"{len(header_blocks)} header blocks, {len(body_blocks)} body blocks")

    return {
        'header_blocks': header_blocks,
        'body_blocks': body_blocks,
        'ordered_text': ordered_text,
    }


# ═══════════════════════════════════════════════════════════════════════════
# INTERNAL — Multi-column row merging
# ═══════════════════════════════════════════════════════════════════════════

def _merge_columns(blocks: list, page_width: float) -> list[str]:
    """
    Merge blocks on the same vertical line (multi-column layout).
    Blocks within Y_MERGE_THRESHOLD px are considered same row.
    """
    if not blocks:
        return []

    rows = []
    current_row = [blocks[0]]

    for block in blocks[1:]:
        if abs(block[1] - current_row[-1][1]) < Y_MERGE_THRESHOLD:
            current_row.append(block)
        else:
            rows.append(current_row)
            current_row = [block]
    rows.append(current_row)

    lines = []
    for row in rows:
        row.sort(key=lambda b: b[0])  # left-to-right
        row_text = '  '.join(b[4].strip() for b in row)
        if row_text.strip():
            lines.append(row_text.strip())

    return lines
