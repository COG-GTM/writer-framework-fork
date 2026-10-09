const HTML_ESCAPES: Record<string, string> = {
	"&": "&amp;",
	"<": "&lt;",
	">": "&gt;",
	'"': "&quot;",
	"'": "&#39;",
};

/**
 * Escape a value so it can be safely interpolated into HTML text or a quoted attribute.
 *
 * ```js
 * escapeHtml('<img src=x onerror="alert(1)">')
 * // => '&lt;img src=x onerror=&quot;alert(1)&quot;&gt;'
 * ```
 */
export function escapeHtml(value: unknown) {
	return String(value ?? "").replace(/[&<>"']/g, (c) => HTML_ESCAPES[c]);
}
