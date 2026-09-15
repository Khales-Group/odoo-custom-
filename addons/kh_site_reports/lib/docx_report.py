"""Builds the site-progress Monthly Report .docx.

Python script to build Khales Monthly Report Word documents with full RTL,
proper Arabic bullet points, table alignment, and bidirectional text handling.
"""

import io

from docx import Document
from docx.enum.table import WD_ALIGN_VERTICAL
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Emu, Pt, RGBColor, Inches
from PIL import Image

FONT_SERIF = "Times New Roman"
FONT_SANS = "Calibri"
FONT_ARABIC = "Arial"
COLOR_TEXT = "252525"
COLOR_GRAY = "808080"
COLOR_BORDER = "D9D9D9"
COLOR_ACCENT = "AF8D56"

EMU_PER_PIXEL = 9525

LABELS = {
    "en": {
        "monthly_report": "Monthly Report",
        "company": "Khales Engineering Consultancy",
        "prepared_for": "Prepared For",
        "prepared_for_value": "Mr. {name}",
        "project_location": "Project Location",
        "plot_number": "Plot Number",
        "document_ref": "Document Ref",
        "project_name": "Project Name",
        "location": "Location",
        "contractor": "Contractor",
        "consultant": "Consultant",
        "disclaimer": (
            "This report was generated automatically: site-visit photographs and their AI-written summaries "
            "were pulled from the project's records, and this month's planned activities/recommendations "
            "were drafted by AI from those summaries. Please verify before formal client issue."
        ),
        "heading_1": "1. EXECUTIVE SUMMARY",
        "heading_2": "2. SITE UPDATE - WORKS COMPLETED THIS MONTH",
        "heading_3": "3. SITE PHOTOS",
        "heading_4": "4. PLANNED ACTIVITIES — NEXT MONTH",
        "heading_5": "5. RECOMMENDATIONS / OWNER ACTION REQUIRED",
        "summary_line": (
            "This report covers {count} site visit(s) for {project} during {period} ({dates})."
        ),
        "date_prefix": "Date: {label}",
        "prepared_by": "Prepared By",
        "manager_title": "{name} / Project Manager",
        "name_title_sig": "[Name / Title / Signature]",
        "reviewed_by": "Reviewed / Approved By",
        "footer_confidential": "Confidential - Prepared for Owner Use Only",
        "footer_page": "Page ",
        "footer_of": " of ",
    },
    "ar": {
        "monthly_report": "التقرير الشهري",
        "company": "خالص للاستشارات الهندسية",
        "prepared_for": "معدّ إلى",
        "prepared_for_value": "السيد {name}",
        "project_location": "موقع المشروع",
        "plot_number": "رقم القطعة",
        "document_ref": "المرجع",
        "project_name": "اسم المشروع",
        "location": "الموقع",
        "contractor": "المقاول",
        "consultant": "الاستشاري",
        "disclaimer": (
            "تم إعداد هذا التقرير تلقائيًا: تم استخراج صور الزيارات الميدانية وملخصاتها المكتوبة بواسطة الذكاء "
            "الاصطناعي من سجلات المشروع، كما تمت صياغة الأنشطة المخطط لها والتوصيات لهذا الشهر بواسطة الذكاء "
            "الاصطناعي استنادًا إلى تلك الملخصات. يُرجى المراجعة قبل الإصدار الرسمي للعميل."
        ),
        "heading_1": "\u200F1. الملخص التنفيذي",
        "heading_2": "\u200F2. تحديث الموقع - الأعمال المنجزة هذا الشهر",
        "heading_3": "\u200F3. صور الموقع",
        "heading_4": "\u200F4. الأنشطة المخطط لها - الشهر القادم",
        "heading_5": "\u200F5. التوصيات / الإجراءات المطلوبة من المالك",
        "summary_line": (
            "\u200Fيغطي هذا التقرير {count} زيارة/زيارات ميدانية لمشروع {project} خلال {period} ({dates})."
        ),
        "date_prefix": "\u200Fالتاريخ: {label}",
        "prepared_by": "أُعد بواسطة",
        "manager_title": "{name} / مدير المشروع",
        "name_title_sig": "[الاسم / المسمى الوظيفي / التوقيع]",
        "reviewed_by": "روجع / اعتمد بواسطة",
        "footer_confidential": "سري - مُعد لاستخدام المالك فقط",
        "footer_page": "صفحة ",
        "footer_of": " من ",
    },
}


def _t(lang, key, **kwargs):
    text = LABELS[lang][key]
    return text.format(**kwargs) if kwargs else text


def _font_for(lang, serif=False):
    if lang == "ar":
        return FONT_ARABIC
    return FONT_SERIF if serif else FONT_SANS


def _hp(half_points):
    return Pt(half_points / 2)


def _dxa(dxa):
    return Pt(dxa / 20)


def _color(hex_str):
    return RGBColor.from_string(hex_str)


# ECMA-376 Schema Order Tables
_PPR_ORDER = [
    "w:pStyle", "w:keepNext", "w:keepLines", "w:pageBreakBefore", "w:framePr",
    "w:widowControl", "w:numPr", "w:suppressLineNumbers", "w:pBdr", "w:shd",
    "w:tabs", "w:suppressAutoHyphens", "w:kinsoku", "w:wordWrap", "w:overflowPunct",
    "w:topLinePunct", "w:autoSpaceDE", "w:autoSpaceDN", "w:bidi", "w:adjustRightInd",
    "w:snapToGrid", "w:spacing", "w:ind", "w:contextualSpacing", "w:mirrorIndents",
    "w:suppressOverlap", "w:jc", "w:textDirection", "w:textAlignment",
    "w:textboxTightWrap", "w:outlineLvl", "w:divId", "w:cnfStyle", "w:rPr",
    "w:sectPr", "w:pPrChange",
]

_TBLPR_ORDER = [
    "w:tblStyle", "w:tblpPr", "w:tblOverlap", "w:bidiVisual",
    "w:tblStyleRowBandSize", "w:tblStyleColBandSize", "w:tblW", "w:jc",
    "w:tblCellSpacing", "w:tblInd", "w:tblBorders", "w:shd", "w:tblLayout",
    "w:tblCellMar", "w:tblLook", "w:tblCaption", "w:tblDescription", "w:tblPrChange",
]

_RPR_ORDER = [
    "w:rStyle", "w:rFonts", "w:b", "w:bCs", "w:i", "w:iCs", "w:caps", "w:smallCaps",
    "w:strike", "w:dstrike", "w:outline", "w:shadow", "w:emboss", "w:imprint",
    "w:noProof", "w:snapToGrid", "w:vanish", "w:webHidden", "w:color", "w:spacing",
    "w:w", "w:kerning", "w:position", "w:sz", "w:szCs", "w:highlight", "w:u",
    "w:effect", "w:bdr", "w:shd", "w:fitText", "w:vertAlign", "w:rtl", "w:cs",
    "w:em", "w:lang", "w:eastAsianLayout", "w:specVanish", "w:oMath", "w:rPrChange"
]


def _insert_pPr_child(pPr, element, tag):
    successors = _PPR_ORDER[_PPR_ORDER.index(tag) + 1 :]
    pPr.insert_element_before(element, *successors)


def _insert_tblPr_child(tblPr, element, tag):
    successors = _TBLPR_ORDER[_TBLPR_ORDER.index(tag) + 1 :]
    tblPr.insert_element_before(element, *successors)


def _insert_rPr_child(rPr, element, tag):
    successors = _RPR_ORDER[_RPR_ORDER.index(tag) + 1 :]
    rPr.insert_element_before(element, *successors)


def _set_paragraph_alignment(paragraph, align_val):
    pPr = paragraph._p.get_or_add_pPr()
    existing_jc = pPr.find(qn("w:jc"))
    if existing_jc is not None:
        pPr.remove(existing_jc)
    jc = OxmlElement("w:jc")
    jc.set(qn("w:val"), align_val)
    _insert_pPr_child(pPr, jc, "w:jc")


def _set_section_rtl(section):
    sectPr = section._sectPr
    if sectPr.find(qn("w:bidi")) is None:
        bidi = OxmlElement("w:bidi")
        bidi.set(qn("w:val"), "1")
        sectPr.insert_element_before(
            bidi,
            "w:rtlGutter",
            "w:docGrid",
            "w:printerSettings",
            "w:sectPrChange",
        )


def _set_cell_shading(cell, hex_color):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_color)
    tcPr.append(shd)


def _set_paragraph_bottom_border(paragraph, hex_color, size=6, space=4):
    pPr = paragraph._p.get_or_add_pPr()
    pBdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), str(size))
    bottom.set(qn("w:space"), str(space))
    bottom.set(qn("w:color"), hex_color)
    pBdr.append(bottom)
    _insert_pPr_child(pPr, pBdr, "w:pBdr")


def _set_paragraph_top_border(paragraph, hex_color, size=4, space=4):
    pPr = paragraph._p.get_or_add_pPr()
    pBdr = OxmlElement("w:pBdr")
    top = OxmlElement("w:top")
    top.set(qn("w:val"), "single")
    top.set(qn("w:sz"), str(size))
    top.set(qn("w:space"), str(space))
    top.set(qn("w:color"), hex_color)
    pBdr.append(top)
    _insert_pPr_child(pPr, pBdr, "w:pBdr")


def _set_paragraph_rtl(paragraph, keep_alignment=False):
    pPr = paragraph._p.get_or_add_pPr()
    if pPr.find(qn("w:bidi")) is None:
        bidi = OxmlElement("w:bidi")
        bidi.set(qn("w:val"), "1")
        _insert_pPr_child(pPr, bidi, "w:bidi")
    if not keep_alignment:
        _set_paragraph_alignment(paragraph, "right")


def _set_run_rtl(run, font_name):
    rPr = run._r.get_or_add_rPr()

    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        rFonts = OxmlElement("w:rFonts")
        _insert_rPr_child(rPr, rFonts, "w:rFonts")
    rFonts.set(qn("w:cs"), font_name)
    rFonts.set(qn("w:ascii"), font_name)
    rFonts.set(qn("w:hAnsi"), font_name)

    if run.bold:
        bCs = OxmlElement("w:bCs")
        _insert_rPr_child(rPr, bCs, "w:bCs")

    if run.italic:
        iCs = OxmlElement("w:iCs")
        _insert_rPr_child(rPr, iCs, "w:iCs")

    sz = rPr.find(qn("w:sz"))
    if sz is not None:
        szCs = OxmlElement("w:szCs")
        szCs.set(qn("w:val"), sz.get(qn("w:val")))
        _insert_rPr_child(rPr, szCs, "w:szCs")

    if rPr.find(qn("w:rtl")) is None:
        rtl = OxmlElement("w:rtl")
        rtl.set(qn("w:val"), "1")
        _insert_rPr_child(rPr, rtl, "w:rtl")

    if rPr.find(qn("w:lang")) is None:
        lang_elem = OxmlElement("w:lang")
        lang_elem.set(qn("w:bidi"), "ar-SA")
        _insert_rPr_child(rPr, lang_elem, "w:lang")


def _apply_rtl(paragraph, font_name, keep_alignment=False):
    _set_paragraph_rtl(paragraph, keep_alignment=keep_alignment)
    for run in paragraph.runs:
        _set_run_rtl(run, font_name)


def _set_table_rtl(table):
    tblPr = table._tbl.tblPr
    if tblPr.find(qn("w:bidiVisual")) is None:
        bidi = OxmlElement("w:bidiVisual")
        bidi.set(qn("w:val"), "1")
        _insert_tblPr_child(tblPr, bidi, "w:bidiVisual")


def _add_field(paragraph, field_code):
    run = paragraph.add_run()
    r = run._r
    fld_begin = OxmlElement("w:fldChar")
    fld_begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = field_code
    fld_end = OxmlElement("w:fldChar")
    fld_end.set(qn("w:fldCharType"), "end")
    r.append(fld_begin)
    r.append(instr)
    r.append(fld_end)
    return run


def prepare_embedded_photo(raw_bytes, max_width=300, max_height=220):
    with Image.open(io.BytesIO(raw_bytes)) as img:
        img = img.convert("RGB")
        img.thumbnail((900, 900))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=80)
        width, height = img.size

    scale = min(max_width / width, max_height / height, 1)
    return {
        "data": buf.getvalue(),
        "width": round(width * scale),
        "height": round(height * scale),
    }


def _add_heading(document, text, with_rule=False, lang="en"):
    p = document.add_paragraph()
    p.paragraph_format.space_before = _dxa(300)
    p.paragraph_format.space_after = _dxa(120)
    run = p.add_run(text)
    run.bold = True
    run.font.name = _font_for(lang)
    run.font.size = _hp(24)
    run.font.color.rgb = _color(COLOR_TEXT)
    if with_rule:
        _set_paragraph_bottom_border(p, COLOR_ACCENT, size=6, space=4)
    if lang == "ar":
        _apply_rtl(p, FONT_ARABIC)
    return p


def _add_body_paragraph(document, text, gray=False, italic=False, lang="en"):
    p = document.add_paragraph()
    p.paragraph_format.space_after = _dxa(120)
    run = p.add_run(text or "")
    run.font.name = _font_for(lang)
    run.font.size = _hp(20)
    run.font.color.rgb = _color(COLOR_GRAY if gray else COLOR_TEXT)
    run.italic = italic
    if lang == "ar":
        _apply_rtl(p, FONT_ARABIC)
    return p


def _add_bullet(document, text, lang="en"):
    p = document.add_paragraph()
    p.paragraph_format.space_after = _dxa(80)

    if lang == "ar":
        # Custom XML hanging indent for Arabic bullet points to avoid Word's LTR List Bullet bugs
        pPr = p._p.get_or_add_pPr()
        ind = OxmlElement("w:ind")
        ind.set(qn("w:right"), "500")
        ind.set(qn("w:hanging"), "260")
        _insert_pPr_child(pPr, ind, "w:ind")

        run_bullet = p.add_run("\u200F•\t")
        run_bullet.font.name = FONT_ARABIC
        run_bullet.font.size = _hp(20)
        run_bullet.font.color.rgb = _color(COLOR_TEXT)

        run_text = p.add_run(text)
        run_text.font.name = FONT_ARABIC
        run_text.font.size = _hp(20)
        run_text.font.color.rgb = _color(COLOR_TEXT)

        _apply_rtl(p, FONT_ARABIC)
    else:
        p.style = "List Bullet"
        run = p.add_run(text)
        run.font.name = FONT_SANS
        run.font.size = _hp(20)
        run.font.color.rgb = _color(COLOR_TEXT)

    return p


def _add_info_table(document, rows, lang="en"):
    table = document.add_table(rows=0, cols=2)
    table.autofit = False
    if lang == "ar":
        _set_table_rtl(table)

    for label, value in rows:
        row = table.add_row()
        label_cell, value_cell = row.cells
        label_cell.width = Inches(1.8)
        value_cell.width = Inches(4.7)

        _set_cell_shading(label_cell, COLOR_BORDER)

        label_cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        p_label = label_cell.paragraphs[0]
        run = p_label.add_run(label)
        run.bold = True
        run.font.name = _font_for(lang)
        run.font.size = _hp(20)
        run.font.color.rgb = _color(COLOR_TEXT)
        if lang == "ar":
            _apply_rtl(p_label, FONT_ARABIC)

        value_cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        p_value = value_cell.paragraphs[0]
        run = p_value.add_run(value or "")
        run.font.name = _font_for(lang)
        run.font.size = _hp(20)
        run.font.color.rgb = _color(COLOR_TEXT)
        if lang == "ar":
            _apply_rtl(p_value, FONT_ARABIC)
    return table


def _add_photo_grid(document, photos, lang="en"):
    prepared = [prepare_embedded_photo(p) for p in photos]
    rows = [prepared[i : i + 2] for i in range(0, len(prepared), 2)]

    table = document.add_table(rows=0, cols=2)
    if lang == "ar":
        _set_table_rtl(table)
    for row_photos in rows:
        row = table.add_row()
        for i, cell in enumerate(row.cells):
            if i >= len(row_photos):
                continue
            photo = row_photos[i]
            p = cell.paragraphs[0]
            _set_paragraph_alignment(p, "center")
            run = p.add_run()
            run.add_picture(
                io.BytesIO(photo["data"]),
                width=Emu(photo["width"] * EMU_PER_PIXEL),
                height=Emu(photo["height"] * EMU_PER_PIXEL),
            )
    return table


def _add_date_line(document, label, lang="en"):
    p = document.add_paragraph()
    p.paragraph_format.space_before = _dxa(100)
    p.paragraph_format.space_after = _dxa(200)
    run = p.add_run(_t(lang, "date_prefix", label=label))
    run.italic = True
    run.font.name = _font_for(lang)
    run.font.size = _hp(18)
    run.font.color.rgb = _color(COLOR_GRAY)
    if lang == "ar":
        _apply_rtl(p, FONT_ARABIC)
    return p


def _add_footer(document, logo_path=None, lang="en"):
    section = document.sections[0]
    footer = section.footer
    p = footer.paragraphs[0]
    _set_paragraph_top_border(p, COLOR_BORDER, size=4, space=4)

    if lang == "ar":
        _set_paragraph_alignment(p, "right")

        r1 = p.add_run(_t(lang, "footer_confidential"))
        r1.font.name = FONT_ARABIC
        r1.font.size = _hp(14)
        r1.font.color.rgb = _color(COLOR_GRAY)

        r_tab = p.add_run("\t")

        r2 = p.add_run(_t(lang, "footer_page"))
        r2.font.name = FONT_ARABIC
        r2.font.size = _hp(14)
        r2.font.color.rgb = _color(COLOR_GRAY)

        r_p = _add_field(p, "PAGE")

        r3 = p.add_run(_t(lang, "footer_of"))
        r3.font.name = FONT_ARABIC
        r3.font.size = _hp(14)
        r3.font.color.rgb = _color(COLOR_GRAY)

        r_np = _add_field(p, "NUMPAGES")

        p.paragraph_format.tab_stops.add_tab_stop(Pt(468), WD_TAB_ALIGNMENT.LEFT)
        _apply_rtl(p, FONT_ARABIC, keep_alignment=True)
    else:
        p.paragraph_format.tab_stops.add_tab_stop(Pt(468), WD_TAB_ALIGNMENT.RIGHT)

        def run_of(text=""):
            r = p.add_run(text)
            r.font.name = FONT_SANS
            r.font.size = _hp(14)
            r.font.color.rgb = _color(COLOR_GRAY)
            return r

        run_of(_t(lang, "footer_confidential"))
        run_of("\t" + _t(lang, "footer_page"))
        _add_field(p, "PAGE")
        run_of(_t(lang, "footer_of"))
        _add_field(p, "NUMPAGES")


def _add_cover_page(document, project, period_label, logo_path, lang="en"):
    font = _font_for(lang, serif=True)

    p = document.add_paragraph()
    run = p.add_run(period_label)
    run.font.name = font
    run.font.size = _hp(24)
    run.font.color.rgb = _color(COLOR_TEXT)
    if lang == "ar":
        _apply_rtl(p, FONT_ARABIC)

    spacer = document.add_paragraph()
    spacer.paragraph_format.space_before = _dxa(1600)

    logo_p = document.add_paragraph()
    _set_paragraph_alignment(logo_p, "center")
    if logo_path:
        logo_p.add_run().add_picture(logo_path, width=Emu(150 * EMU_PER_PIXEL), height=Emu(71 * EMU_PER_PIXEL))

    title_p = document.add_paragraph()
    _set_paragraph_alignment(title_p, "center")
    title_p.paragraph_format.space_before = _dxa(500)
    run = title_p.add_run(_t(lang, "monthly_report"))
    run.font.name = font
    run.font.size = _hp(72)
    if lang == "ar":
        _apply_rtl(title_p, FONT_ARABIC, keep_alignment=True)

    sub_p = document.add_paragraph()
    _set_paragraph_alignment(sub_p, "center")
    sub_p.paragraph_format.space_before = _dxa(150)
    run = sub_p.add_run(_t(lang, "company"))
    run.font.name = font
    run.font.size = _hp(24)
    if lang == "ar":
        _apply_rtl(sub_p, FONT_ARABIC, keep_alignment=True)

    gap = document.add_paragraph()
    gap.paragraph_format.space_before = _dxa(3200)

    for label, value in [
        (_t(lang, "prepared_for"), _t(lang, "prepared_for_value", name=project.get("client_name") or "")),
        (_t(lang, "project_location"), project.get("location") or ""),
        (_t(lang, "plot_number"), project.get("plot_number") or ""),
        (_t(lang, "document_ref"), project.get("project_no") or ""),
    ]:
        line = document.add_paragraph()
        text_val = f"\u200F{label}: {value}" if lang == "ar" else f"{label}: {value}"
        run = line.add_run(text_val)
        run.font.name = font
        run.font.size = _hp(20)
        run.font.color.rgb = _color(COLOR_TEXT)
        if lang == "ar":
            _set_paragraph_alignment(line, "right")
            _apply_rtl(line, FONT_ARABIC, keep_alignment=True)

    document.add_page_break()


def build_report_docx(project, period_label, visit_dates_label, visits, synthesis, logo_path=None, language="en"):
    lang = language if language in LABELS else "en"
    document = Document()
    if lang == "ar":
        _set_section_rtl(document.sections[0])
    _add_footer(document, logo_path, lang=lang)
    _add_cover_page(document, project, period_label, logo_path, lang=lang)

    _add_info_table(
        document,
        [
            (_t(lang, "project_name"), project.get("project_name")),
            (_t(lang, "location"), project.get("location") or ""),
            (_t(lang, "contractor"), project.get("contractor") or ""),
            (_t(lang, "consultant"), project.get("consultant") or ""),
        ],
        lang=lang,
    )
    _add_body_paragraph(document, _t(lang, "disclaimer"), gray=True, italic=True, lang=lang)

    _add_heading(document, _t(lang, "heading_1"), lang=lang)
    _add_body_paragraph(
        document,
        _t(
            lang, "summary_line",
            count=len(visits), project=project.get("project_name"),
            period=period_label, dates=visit_dates_label,
        ),
        lang=lang,
    )

    _add_heading(document, _t(lang, "heading_2"), with_rule=True, lang=lang)
    for para in synthesis["site_update_summary"].split("\n\n"):
        if para.strip():
            _add_body_paragraph(document, para.strip(), lang=lang)

    _add_heading(document, _t(lang, "heading_3"), lang=lang)
    for visit in visits:
        if visit["photos"]:
            _add_photo_grid(document, visit["photos"], lang=lang)
        _add_date_line(document, visit["date_label"], lang=lang)

    _add_heading(document, _t(lang, "heading_4"), with_rule=True, lang=lang)
    for item in synthesis["planned_activities"]:
        _add_bullet(document, item, lang=lang)

    _add_heading(document, _t(lang, "heading_5"), lang=lang)
    _add_body_paragraph(document, synthesis["recommendations"], lang=lang)

    sign_table = document.add_table(rows=1, cols=2)
    if lang == "ar":
        _set_table_rtl(sign_table)
    font = _font_for(lang)

    prepared_p = sign_table.rows[0].cells[0].paragraphs[0]
    prepared_p.add_run(_t(lang, "prepared_by")).bold = True
    if lang == "ar":
        _apply_rtl(prepared_p, FONT_ARABIC)

    p = sign_table.rows[0].cells[0].add_paragraph()
    manager_name = project.get("manager_name")
    run = p.add_run(_t(lang, "manager_title", name=manager_name) if manager_name else _t(lang, "name_title_sig"))
    run.italic = True
    run.font.name = font
    run.font.color.rgb = _color(COLOR_GRAY)
    if lang == "ar":
        _apply_rtl(p, FONT_ARABIC)

    reviewed_p = sign_table.rows[0].cells[1].paragraphs[0]
    reviewed_p.add_run(_t(lang, "reviewed_by")).bold = True
    if lang == "ar":
        _apply_rtl(reviewed_p, FONT_ARABIC)

    p = sign_table.rows[0].cells[1].add_paragraph()
    run = p.add_run(_t(lang, "name_title_sig"))
    run.italic = True
    run.font.name = font
    run.font.color.rgb = _color(COLOR_GRAY)
    if lang == "ar":
        _apply_rtl(p, FONT_ARABIC)

    buf = io.BytesIO()
    document.save(buf)
    return buf.getvalue()