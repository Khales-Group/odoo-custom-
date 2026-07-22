/** @odoo-module **/

/**
 * Minimal Markdown -> HTML renderer for Claude's chat replies (bold,
 * headings, horizontal rules, lists, tables, inline code). The source text
 * is HTML-escaped BEFORE any markdown tag is added, so nothing in the
 * original message (even if it contains "<script>" or similar) can ever
 * turn into a real HTML tag - only the tags this function itself inserts
 * are real markup.
 */

function escapeHtml(text) {
    return String(text)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}

function inlineFormat(text) {
    let out = text;
    out = out.replace(/`([^`]+)`/g, "<code>$1</code>");
    out = out.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    out = out.replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, "$1<em>$2</em>");
    return out;
}

function splitTableRow(line) {
    return line
        .trim()
        .replace(/^\|/, "")
        .replace(/\|$/, "")
        .split("|");
}

export function markdownToHtml(rawText) {
    const lines = escapeHtml(rawText).split("\n");
    const htmlParts = [];
    let listBuffer = null; // { type: "ul" | "ol", items: [] }
    let tableBuffer = null; // { header: [...], rows: [...] }

    function flushList() {
        if (!listBuffer) {
            return;
        }
        const tag = listBuffer.type;
        const items = listBuffer.items
            .map((item) => `<li>${inlineFormat(item)}</li>`)
            .join("");
        htmlParts.push(`<${tag} class="o_mcp_md_list">${items}</${tag}>`);
        listBuffer = null;
    }

    function flushTable() {
        if (!tableBuffer) {
            return;
        }
        let html = '<table class="o_mcp_md_table"><thead><tr>';
        html += tableBuffer.header
            .map((cell) => `<th>${inlineFormat(cell.trim())}</th>`)
            .join("");
        html += "</tr></thead><tbody>";
        for (const row of tableBuffer.rows) {
            html += "<tr>" + row.map((cell) => `<td>${inlineFormat(cell.trim())}</td>`).join("") + "</tr>";
        }
        html += "</tbody></table>";
        htmlParts.push(html);
        tableBuffer = null;
    }

    let i = 0;
    while (i < lines.length) {
        const line = lines[i];
        const trimmed = line.trim();

        if (tableBuffer) {
            if (trimmed.includes("|")) {
                tableBuffer.rows.push(splitTableRow(trimmed));
                i++;
                continue;
            }
            flushTable();
            // fall through: re-evaluate this same line against the rules below
        }

        if (/^(-{3,}|\*{3,})$/.test(trimmed)) {
            flushList();
            htmlParts.push("<hr/>");
            i++;
            continue;
        }

        const headerMatch = trimmed.match(/^(#{1,6})\s+(.*)$/);
        if (headerMatch) {
            flushList();
            const level = Math.min(headerMatch[1].length + 2, 6);
            htmlParts.push(
                `<h${level} class="o_mcp_md_heading">${inlineFormat(headerMatch[2])}</h${level}>`
            );
            i++;
            continue;
        }

        if (trimmed.includes("|")) {
            const next = (lines[i + 1] || "").trim();
            if (/^\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)+\|?$/.test(next)) {
                flushList();
                tableBuffer = { header: splitTableRow(trimmed), rows: [] };
                i += 2;
                continue;
            }
        }

        const ulMatch = trimmed.match(/^[-*]\s+(.*)$/);
        if (ulMatch) {
            if (!listBuffer || listBuffer.type !== "ul") {
                flushList();
                listBuffer = { type: "ul", items: [] };
            }
            listBuffer.items.push(ulMatch[1]);
            i++;
            continue;
        }

        const olMatch = trimmed.match(/^\d+\.\s+(.*)$/);
        if (olMatch) {
            if (!listBuffer || listBuffer.type !== "ol") {
                flushList();
                listBuffer = { type: "ol", items: [] };
            }
            listBuffer.items.push(olMatch[1]);
            i++;
            continue;
        }

        flushList();

        if (!trimmed) {
            i++;
            continue;
        }

        htmlParts.push(`<p class="o_mcp_md_p">${inlineFormat(line)}</p>`);
        i++;
    }
    flushList();
    flushTable();

    return htmlParts.join("");
}
