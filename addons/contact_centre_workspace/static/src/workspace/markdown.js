/** @odoo-module **/

// Markdown → HTML for the AI copilot's replies: headings, bold and italic,
// inline and fenced code, lists and tables. The same small renderer as the
// AI Ops screen in contact_centre_ai_ops, copied because that addon is
// optional here. It escapes first, so the model's own text can never inject
// markup.
function escapeHtml(text) {
    return String(text)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
}

function renderInlineMarkdown(text) {
    let s = text;
    s = s.replace(/`([^`\n]+)`/g, "<code>$1</code>");
    s = s.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");
    s = s.replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, "$1<em>$2</em>");
    s = s.replace(/(^|[^_])_([^_\n]+)_(?!_)/g, "$1<em>$2</em>");
    return s;
}

function splitTableRow(line) {
    let trimmed = line.trim();
    if (trimmed.startsWith("|")) {
        trimmed = trimmed.slice(1);
    }
    if (trimmed.endsWith("|")) {
        trimmed = trimmed.slice(0, -1);
    }
    return trimmed.split("|").map((cell) => cell.trim());
}

function isTableSeparatorRow(line) {
    const cells = splitTableRow(line);
    return cells.length > 0 && cells.every((c) => /^:?-+:?$/.test(c));
}

function tableCellAlign(separatorCell) {
    const left = separatorCell.startsWith(":");
    const right = separatorCell.endsWith(":");
    if (left && right) {
        return "center";
    }
    return right ? "right" : left ? "left" : null;
}

function renderMarkdownTable(lines) {
    const header = splitTableRow(lines[0]);
    const aligns = splitTableRow(lines[1]).map(tableCellAlign);
    const cellTag = (tag, cell, i) => {
        const align = aligns[i];
        const style = align ? ` style="text-align:${align}"` : "";
        return `<${tag}${style}>${renderInlineMarkdown(cell)}</${tag}>`;
    };
    const headHtml = header.map((cell, i) => cellTag("th", cell, i)).join("");
    const bodyHtml = lines.slice(2).map((line) => {
        const cells = splitTableRow(line);
        return `<tr>${cells.map((cell, i) => cellTag("td", cell, i)).join("")}</tr>`;
    }).join("");
    return `<div class="o_ccw_md_tablewrap"><table class="o_ccw_md_table">`
        + `<thead><tr>${headHtml}</tr></thead><tbody>${bodyHtml}</tbody></table></div>`;
}

function renderMarkdownBlock(block) {
    const lines = block.split("\n");
    if (lines.length >= 2 && lines[0].includes("|") && isTableSeparatorRow(lines[1])) {
        return renderMarkdownTable(lines);
    }
    const headerMatch = lines.length === 1 && block.match(/^(#{1,6})\s+(.*)$/);
    if (headerMatch) {
        const level = Math.min(headerMatch[1].length + 2, 6); // keep headings small inside a chat bubble
        return `<h${level}>${renderInlineMarkdown(headerMatch[2])}</h${level}>`;
    }
    if (lines.every((l) => /^\s*\d+\.\s+/.test(l))) {
        const items = lines.map((l) => `<li>${renderInlineMarkdown(l.replace(/^\s*\d+\.\s+/, ""))}</li>`).join("");
        return `<ol>${items}</ol>`;
    }
    if (lines.every((l) => /^\s*[-*]\s+/.test(l))) {
        const items = lines.map((l) => `<li>${renderInlineMarkdown(l.replace(/^\s*[-*]\s+/, ""))}</li>`).join("");
        return `<ul>${items}</ul>`;
    }
    return `<p>${lines.map(renderInlineMarkdown).join("<br>")}</p>`;
}

export function markdownToHtml(text) {
    if (!text) {
        return "";
    }
    const escaped = escapeHtml(text);
    // Pull fenced code blocks out first so their contents skip inline
    // formatting and blank-line splitting, then splice back in at the end.
    const codeBlocks = [];
    const withPlaceholders = escaped.replace(/```(?:\w+)?\n?([\s\S]*?)```/g, (_match, code) => {
        const index = codeBlocks.length;
        codeBlocks.push(`<pre class="o_ccw_md_code"><code>${code.replace(/\n$/, "")}</code></pre>`);
        return ` CODEBLOCK${index} `;
    });
    const html = withPlaceholders
        .split(/\n{2,}/)
        .map(renderMarkdownBlock)
        .join("")
        .replace(/ CODEBLOCK(\d+) /g, (_match, i) => codeBlocks[Number(i)]);
    return html;
}
