#!/usr/bin/env python3
from __future__ import annotations

import html
import re
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "report"
main_md = REPORT / "nanobody_tool_survey_report.md"
open_notes_md = REPORT / "open_reproducibility_notes.md"
asset_md = REPORT / "asset_inventory.md"
missing_md = REPORT / "missing_pdfs.md"
combined_md = REPORT / "nanobody_tool_survey_full.md"
html_out = REPORT / "nanobody_tool_survey_full.html"
pdf_out = REPORT / "nanobody_tool_survey_full.pdf"

TITLE = "纳米抗体/VHH 工具全景调研报告"
SUBTITLE = "开源可复现优先版：结构预测、设计、识别/发现、性质预测与本地论文/代码资料包"
GENERATED_DATE = "2026-07-06"


def read_sections() -> str:
    sections = [main_md.read_text(encoding="utf-8")]
    if open_notes_md.exists():
        sections.append(open_notes_md.read_text(encoding="utf-8"))
    sections.append(asset_md.read_text(encoding="utf-8"))
    if missing_md.exists():
        sections.append(missing_md.read_text(encoding="utf-8"))
    combined = "\n\n---\n\n".join(sections)
    combined_md.write_text(combined, encoding="utf-8")
    return combined


def write_html(combined: str) -> None:
    try:
        import markdown

        body = markdown.markdown(combined, extensions=["tables", "fenced_code", "toc"])
    except Exception:
        body = "<pre>" + html.escape(combined) + "</pre>"

    html_doc = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>{html.escape(TITLE)}</title>
<style>
:root {{ --ink:#1b2430; --muted:#667085; --rule:#d9e2ec; --soft:#f6f8fb; --accent:#0f5e8c; --accent2:#b45309; }}
* {{ box-sizing: border-box; }}
body {{ font-family: 'WenQuanYi Zen Hei', 'Noto Sans CJK SC', 'Source Han Sans SC', sans-serif; line-height: 1.72; max-width: 1120px; margin: 0 auto; padding: 42px 28px 80px; color: var(--ink); background: linear-gradient(180deg, #f8fbff 0, #fff 180px); }}
body::before {{ content: '{html.escape(TITLE)}'; display: block; padding: 34px 38px; margin: 0 0 34px; border-radius: 22px; color: white; font-size: 30px; font-weight: 700; letter-spacing: .03em; background: linear-gradient(135deg, #0f5e8c, #12324a 70%); box-shadow: 0 18px 44px rgba(15,94,140,.20); }}
h1 {{ display: none; }}
h2 {{ margin-top: 42px; padding-top: 14px; border-top: 2px solid var(--rule); color: #12324a; font-size: 25px; }}
h3 {{ margin-top: 26px; color: #0f5e8c; font-size: 19px; }}
p, li {{ font-size: 15.5px; }}
ul, ol {{ padding-left: 1.4em; }}
li {{ margin: .28em 0; }}
a {{ color: var(--accent); text-decoration-color: rgba(15,94,140,.35); overflow-wrap: anywhere; }}
code {{ background: #eef4f8; color: #334155; padding: 2px 5px; border-radius: 5px; font-family: 'DejaVu Sans Mono', 'Noto Sans Mono CJK SC', monospace; font-size: .92em; }}
pre {{ background: #0f172a; color: #e5eef8; padding: 15px 18px; border-radius: 12px; overflow-x: auto; line-height: 1.55; }}
table {{ border-collapse: collapse; width: 100%; margin: 18px 0 26px; font-size: 14px; box-shadow: 0 8px 28px rgba(15,23,42,.06); }}
th,td {{ border: 1px solid var(--rule); padding: 9px 10px; vertical-align: top; overflow-wrap: anywhere; }}
th {{ background: #eaf2f8; color: #12324a; }}
tr:nth-child(even) td {{ background: #fafcff; }}
hr {{ border: 0; border-top: 1px solid var(--rule); margin: 34px 0; }}
@media print {{ body {{ max-width: none; padding: 0; background: white; }} body::before {{ box-shadow: none; }} a {{ color: #0f5e8c; }} }}
</style></head><body>{body}</body></html>"""
    html_out.write_text(html_doc, encoding="utf-8")


# PDF rendering uses ReportLab's document model rather than line-by-line drawing.
from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable,
    ListFlowable,
    ListItem,
    PageBreak,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

PAGE_W, PAGE_H = A4
LEFT = RIGHT = 19 * mm
TOP = 18 * mm
BOTTOM = 18 * mm
CONTENT_W = PAGE_W - LEFT - RIGHT


def register_fonts() -> tuple[str, str, str]:
    candidates = [
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/arphic/uming.ttc",
    ]
    font_path = next((p for p in candidates if Path(p).exists()), None)
    if not font_path:
        return "Helvetica", "Helvetica-Bold", "Courier"
    pdfmetrics.registerFont(TTFont("CJK", font_path))
    pdfmetrics.registerFont(TTFont("CJK-Bold", font_path))
    mono_candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    ]
    mono_path = next((p for p in mono_candidates if Path(p).exists()), font_path)
    pdfmetrics.registerFont(TTFont("Mono", mono_path))
    return "CJK", "CJK-Bold", "Mono"


FONT, BOLD, MONO = register_fonts()
def make_styles() -> dict[str, ParagraphStyle]:
    return {
        "cover_title": ParagraphStyle(
            "CoverTitle", fontName=BOLD, fontSize=28, leading=35, textColor=colors.HexColor("#12324a"),
            alignment=TA_LEFT, spaceAfter=14,
        ),
        "cover_subtitle": ParagraphStyle(
            "CoverSubtitle", fontName=FONT, fontSize=12.5, leading=18, textColor=colors.HexColor("#536473"),
            alignment=TA_LEFT, spaceAfter=26,
        ),
        "cover_meta": ParagraphStyle(
            "CoverMeta", fontName=FONT, fontSize=9.8, leading=15, textColor=colors.HexColor("#667085"),
            alignment=TA_LEFT,
        ),
        "toc_title": ParagraphStyle(
            "TocTitle", fontName=BOLD, fontSize=18, leading=23, textColor=colors.HexColor("#12324a"), spaceAfter=10,
        ),
        "toc_h2": ParagraphStyle(
            "TocH2", fontName=BOLD, fontSize=9.6, leading=13, textColor=colors.HexColor("#253858"), leftIndent=0,
        ),
        "toc_h3": ParagraphStyle(
            "TocH3", fontName=FONT, fontSize=8.5, leading=11.5, textColor=colors.HexColor("#64748b"), leftIndent=12,
        ),
        "h1": ParagraphStyle(
            "H1", fontName=BOLD, fontSize=20, leading=26, textColor=colors.HexColor("#12324a"),
            spaceBefore=12, spaceAfter=12, keepWithNext=True,
        ),
        "h2": ParagraphStyle(
            "H2", fontName=BOLD, fontSize=15.2, leading=20, textColor=colors.HexColor("#0f5e8c"),
            spaceBefore=14, spaceAfter=8, keepWithNext=True,
        ),
        "h3": ParagraphStyle(
            "H3", fontName=BOLD, fontSize=11.5, leading=15.2, textColor=colors.HexColor("#25415a"),
            spaceBefore=9, spaceAfter=5, keepWithNext=True,
        ),
        "body": ParagraphStyle(
            "Body", fontName=FONT, fontSize=8.8, leading=13.2, textColor=colors.HexColor("#22272e"),
            alignment=TA_JUSTIFY, spaceAfter=4.5, wordWrap="CJK",
        ),
        "bullet": ParagraphStyle(
            "Bullet", fontName=FONT, fontSize=8.7, leading=12.8, textColor=colors.HexColor("#22272e"),
            leftIndent=11, firstLineIndent=-7, bulletIndent=0, spaceAfter=3.5, wordWrap="CJK",
        ),
        "code": ParagraphStyle(
            "Code", fontName=MONO, fontSize=7.1, leading=9.2, textColor=colors.HexColor("#1f2937"),
            backColor=colors.HexColor("#f2f5f8"), borderColor=colors.HexColor("#d8e1ea"), borderWidth=.35,
            borderPadding=6, leftIndent=2, rightIndent=2, spaceBefore=4, spaceAfter=7, wordWrap="CJK",
        ),
        "table_cell": ParagraphStyle(
            "TableCell", fontName=FONT, fontSize=6.6, leading=8.3, textColor=colors.HexColor("#26323f"),
            wordWrap="CJK", splitLongWords=True,
        ),
        "table_head": ParagraphStyle(
            "TableHead", fontName=BOLD, fontSize=6.7, leading=8.4, textColor=colors.HexColor("#12324a"),
            wordWrap="CJK", splitLongWords=True,
        ),
    }


STYLES = make_styles()


def xml_escape(text: str) -> str:
    return html.escape(text, quote=True)


def inline_markdown(text: str) -> str:
    text = xml_escape(text.strip())
    text = re.sub(r"`([^`]+)`", lambda m: f'<font name="{MONO}" color="#334155">{m.group(1)}</font>', text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)
    text = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        lambda m: f'<a href="{m.group(2)}" color="#0f5e8c">{m.group(1)}</a>',
        text,
    )
    text = re.sub(
        r"(?<![\"'=])(https?://[^\s；，。)]+)",
        lambda m: f'<a href="{m.group(1)}" color="#0f5e8c">{m.group(1)}</a>',
        text,
    )
    return text


def para(text: str, style: str = "body") -> Paragraph:
    return Paragraph(inline_markdown(text), STYLES[style])


def split_pipe_row(line: str) -> List[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def is_table_separator(line: str) -> bool:
    return bool(re.match(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$", line))


def table_flowable(rows: list[str]) -> Table | None:
    parsed = [split_pipe_row(row) for row in rows]
    if len(parsed) < 2:
        return None
    if is_table_separator(rows[1]):
        parsed.pop(1)
    col_count = max(len(row) for row in parsed)
    for row in parsed:
        row.extend([""] * (col_count - len(row)))
    data = []
    for r_i, row in enumerate(parsed):
        style = "table_head" if r_i == 0 else "table_cell"
        data.append([Paragraph(inline_markdown(cell), STYLES[style]) for cell in row])
    col_width = CONTENT_W / col_count
    table = Table(data, colWidths=[col_width] * col_count, repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eaf2f8")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#12324a")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#fbfdff")]),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#d8e1ea")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def collect_headings(combined: str) -> list[tuple[int, str]]:
    headings: list[tuple[int, str]] = []
    # Keep the quick TOC focused on the main report; appendices contain many
    # per-tool headings that make the preview harder to scan.
    main_section = main_md.read_text(encoding="utf-8") if main_md.exists() else combined
    for line in main_section.splitlines():
        match = re.match(r"^(#{1,3})\s+(.+)$", line)
        if not match:
            continue
        level = len(match.group(1))
        title = re.sub(r"`([^`]+)`", r"\1", match.group(2)).strip()
        if level == 1 and title == TITLE:
            continue
        headings.append((level, title))
    return headings


def make_cover(combined: str) -> list:
    flowables: list = [Spacer(1, 44 * mm)]
    flowables.append(Paragraph(TITLE, STYLES["cover_title"]))
    flowables.append(Paragraph(SUBTITLE, STYLES["cover_subtitle"]))
    meta = [
        f"生成日期：{GENERATED_DATE}",
        f"资料包目录：{ROOT}",
        f"合并稿：{combined_md.name}",
        "版式：ReportLab 本地渲染；中文字体优先使用 WenQuanYi/Noto CJK。",
    ]
    flowables.append(HRFlowable(width="100%", thickness=1.2, color=colors.HexColor("#d9e2ec"), spaceBefore=4, spaceAfter=10))
    for item in meta:
        flowables.append(Paragraph(xml_escape(item), STYLES["cover_meta"]))
    flowables.append(Spacer(1, 12 * mm))
    highlights = [
        "四类工具地图：结构预测/复合物建模、设计与人源化、识别发现、性质预测。",
        "附录合并：本地 PDF、代码仓库、下载失败原因与资产状态。",
        "阅读路径：先看总览和推荐工作流，再按工具类别查细节，最后查附录路径。",
    ]
    flowables.append(ListFlowable([ListItem(para(item, "body"), leftIndent=10) for item in highlights], bulletType="bullet", start="circle"))
    flowables.append(PageBreak())
    return flowables


def make_toc(combined: str) -> list:
    headings = collect_headings(combined)
    flowables: list = [Paragraph("目录速览", STYLES["toc_title"])]
    items = []
    for level, title in headings:
        if level == 2:
            items.append(Paragraph(inline_markdown(title), STYLES["toc_h2"]))
        elif level == 3 and len(items) < 72:
            items.append(Paragraph(inline_markdown("- " + title), STYLES["toc_h3"]))
    flowables.extend(items)
    flowables.append(PageBreak())
    return flowables


def flush_paragraph(lines: list[str], story: list) -> None:
    if not lines:
        return
    text = " ".join(line.strip() for line in lines if line.strip())
    if text:
        story.append(para(text))
    lines.clear()


def flush_bullets(items: list[str], story: list) -> None:
    if not items:
        return
    list_items = [ListItem(Paragraph(inline_markdown(item), STYLES["bullet"]), leftIndent=12) for item in items]
    story.append(ListFlowable(list_items, bulletType="bullet", start="circle", leftIndent=10, bulletFontName=FONT, bulletFontSize=6.5))
    story.append(Spacer(1, 1.5 * mm))
    items.clear()


def markdown_to_flowables(combined: str) -> list:
    story: list = []
    paragraph_lines: list[str] = []
    bullet_items: list[str] = []
    table_lines: list[str] = []
    code_lines: list[str] = []
    in_code = False

    def flush_table() -> None:
        nonlocal table_lines
        if table_lines:
            table = table_flowable(table_lines)
            if table:
                story.append(table)
                story.append(Spacer(1, 4 * mm))
            table_lines = []

    lines = combined.splitlines()
    for raw in lines:
        line = raw.rstrip("\n")
        if line.startswith("```"):
            flush_paragraph(paragraph_lines, story)
            flush_bullets(bullet_items, story)
            flush_table()
            if in_code:
                story.append(Preformatted("\n".join(code_lines), STYLES["code"])); code_lines = []
                in_code = False
            else:
                in_code = True
            continue
        if in_code:
            code_lines.append(line)
            continue
        if line.startswith("|"):
            flush_paragraph(paragraph_lines, story)
            flush_bullets(bullet_items, story)
            table_lines.append(line)
            continue
        flush_table()
        if not line.strip():
            flush_paragraph(paragraph_lines, story)
            flush_bullets(bullet_items, story)
            continue
        if line.strip() == "---":
            flush_paragraph(paragraph_lines, story)
            flush_bullets(bullet_items, story)
            story.append(HRFlowable(width="100%", thickness=.55, color=colors.HexColor("#d8e1ea"), spaceBefore=8, spaceAfter=8))
            continue
        heading = re.match(r"^(#{1,3})\s+(.+)$", line)
        if heading:
            flush_paragraph(paragraph_lines, story)
            flush_bullets(bullet_items, story)
            level = min(len(heading.group(1)), 3)
            text = heading.group(2).strip()
            style = f"h{level}"
            if level == 2:
                story.append(Spacer(1, 2 * mm))
            story.append(Paragraph(inline_markdown(text), STYLES[style]))
            continue
        bullet = re.match(r"^\s*(?:[-*]|\d+\.)\s+(.+)$", line)
        if bullet:
            flush_paragraph(paragraph_lines, story)
            bullet_items.append(bullet.group(1).strip())
            continue
        flush_bullets(bullet_items, story)
        paragraph_lines.append(line)

    flush_paragraph(paragraph_lines, story)
    flush_bullets(bullet_items, story)
    flush_table()
    if code_lines:
        story.append(Preformatted("\n".join(code_lines), STYLES["code"]))
    return story


def draw_header_footer(canvas, doc) -> None:
    canvas.saveState()
    page = canvas.getPageNumber()
    if page == 1:
        # Cover gets a subtle framing rule only.
        canvas.setStrokeColor(colors.HexColor("#d9e2ec"))
        canvas.setLineWidth(1)
        canvas.line(LEFT, BOTTOM, PAGE_W - RIGHT, BOTTOM)
    else:
        canvas.setFont(FONT, 7.4)
        canvas.setFillColor(colors.HexColor("#667085"))
        canvas.drawString(LEFT, PAGE_H - 10 * mm, TITLE)
        canvas.setStrokeColor(colors.HexColor("#d9e2ec"))
        canvas.setLineWidth(.45)
        canvas.line(LEFT, PAGE_H - 13 * mm, PAGE_W - RIGHT, PAGE_H - 13 * mm)
        canvas.drawRightString(PAGE_W - RIGHT, 9 * mm, f"Page {page}")
    canvas.restoreState()


def write_pdf(combined: str) -> None:
    doc = SimpleDocTemplate(
        str(pdf_out),
        pagesize=A4,
        rightMargin=RIGHT,
        leftMargin=LEFT,
        topMargin=TOP + 4 * mm,
        bottomMargin=BOTTOM,
        title=TITLE,
        author="nanobody_tool_survey",
    )
    story = make_cover(combined) + make_toc(combined) + markdown_to_flowables(combined)
    doc.build(story, onFirstPage=draw_header_footer, onLaterPages=draw_header_footer)


def main() -> None:
    combined = read_sections()
    write_html(combined)
    write_pdf(combined)
    print(combined_md)
    print(html_out)
    print(pdf_out)


if __name__ == "__main__":
    main()
