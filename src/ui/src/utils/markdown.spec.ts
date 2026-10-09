import { describe, expect, it } from "vitest";
import { escapeHtml, parseMarkdownWithoutRawHtml } from "./markdown";

describe(escapeHtml.name, () => {
	it("should escape HTML special characters", () => {
		expect(escapeHtml(`<a href="x">'&'</a>`)).toBe(
			"&lt;a href=&quot;x&quot;&gt;&#39;&amp;&#39;&lt;/a&gt;",
		);
	});
});

describe(parseMarkdownWithoutRawHtml.name, () => {
	it("should still render Markdown", () => {
		expect(parseMarkdownWithoutRawHtml("**bold** `code`")).toBe(
			"<p><strong>bold</strong> <code>code</code></p>\n",
		);
	});

	it("should escape block-level raw HTML", () => {
		const html = parseMarkdownWithoutRawHtml(
			"<div><img src=x onerror=alert(1)></div>",
		);
		expect(html).not.toContain("<img");
		expect(html).not.toContain("<div");
		expect(html).toContain("&lt;img src=x onerror=alert(1)&gt;");
	});

	it("should escape inline raw HTML in exception text", () => {
		const html = parseMarkdownWithoutRawHtml(
			`ValueError("invalid literal for int() with base 10: '<svg onload=alert(1)>'")`,
		);
		expect(html).not.toContain("<svg");
		expect(html).toContain("&lt;svg onload=alert(1)&gt;");
	});

	it("should escape HTML inside fenced code blocks", () => {
		const html = parseMarkdownWithoutRawHtml(
			"```\nTraceback\nKeyError: '<script>alert(1)</script>'\n```",
		);
		expect(html).not.toContain("<script>");
		expect(html).toContain("&lt;script&gt;alert(1)&lt;/script&gt;");
	});
});
