import { Marked } from "marked";

const HTML_ESCAPES: Record<string, string> = {
	"&": "&amp;",
	"<": "&lt;",
	">": "&gt;",
	'"': "&quot;",
	"'": "&#39;",
};

export function escapeHtml(text: string): string {
	return text.replace(/[&<>"']/g, (char) => HTML_ESCAPES[char]);
}

const markedWithoutRawHtml = new Marked({
	renderer: {
		html: (html: string) => escapeHtml(html),
	},
});

/**
 * Renders Markdown while showing any raw HTML in the source as literal text.
 * Use it for Markdown built from untrusted text, such as exception messages.
 */
export function parseMarkdownWithoutRawHtml(markdown: string): string {
	return markedWithoutRawHtml.parse(markdown, { async: false }) as string;
}
