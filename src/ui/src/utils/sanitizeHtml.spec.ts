import { beforeAll, describe, expect, it } from "vitest";
import DOMPurify from "dompurify";
import { marked } from "marked";
import {
	isSafeInlineStyle,
	SANITIZE_HTML_CONFIG,
	SANITIZE_HTML_HOOKS,
} from "./sanitizeHtml";

function sanitize(html: string) {
	return DOMPurify.sanitize(html, SANITIZE_HTML_CONFIG) as string;
}

function renderMarkdown(markdown: string) {
	return sanitize(String(marked.parse(markdown)));
}

describe("sanitizeHtml", () => {
	beforeAll(() => {
		DOMPurify.addHook(
			"uponSanitizeAttribute",
			SANITIZE_HTML_HOOKS.uponSanitizeAttribute,
		);
	});

	it("uses a DOMPurify release without the known default-config mXSS bypasses", () => {
		const [major, minor, patch] = DOMPurify.version.split(".").map(Number);
		expect(major).toBe(3);
		expect(minor * 1000 + patch).toBeGreaterThanOrEqual(3 * 1000 + 2);
	});

	it("keeps regular markdown output", () => {
		const html = renderMarkdown(
			"# Title\n\n**bold** [link](https://writer.com) `code`\n\n| a |\n|---|\n| b |",
		);
		expect(html).toContain("<h1>Title</h1>");
		expect(html).toContain("<strong>bold</strong>");
		expect(html).toContain('<a href="https://writer.com">link</a>');
		expect(html).toContain("<code>code</code>");
		expect(html).toContain("<td>b</td>");
	});

	it("strips scripts and event handlers passed through marked", () => {
		const html = renderMarkdown(
			'hi <script>alert(1)</script><img src="x" onerror="alert(1)"><a href="#" onclick="alert(1)">x</a>',
		);
		expect(html).not.toMatch(/<script|onerror|onclick/i);
	});

	it.each([
		"javascript:alert(1)",
		"JaVaScRiPt:alert(1)",
		"vbscript:msgbox(1)",
		"data:text/html,<script>alert(1)</script>",
		"//evil.test/x",
		"/\\evil.test/x",
		"\\\\evil.test/x",
	])("drops dangerous link protocol %s", (href) => {
		const html = sanitize(`<a href="${href}">x</a>`);
		expect(html).toBe("<a>x</a>");
	});

	it.each([
		"https://writer.com",
		"mailto:a@b.com",
		"/static/a.png",
		"#top",
		"docs/a.md",
	])("keeps safe link %s", (href) => {
		expect(sanitize(`<a href="${href}">x</a>`)).toBe(
			`<a href="${href}">x</a>`,
		);
	});

	it("removes forbidden tags used by mXSS and UI-redress payloads", () => {
		const html = sanitize(
			'<svg><p><style><a id="</style><img src=1 onerror=alert(1)>"></a></style></p></svg>' +
				"<math><mtext><table><mglyph><style><img src=x onerror=alert(1)></style></mglyph></table></mtext></math>" +
				'<form action="https://evil.test"><input name="password"><button>go</button></form>' +
				"<style>body{display:none}</style>",
		);
		expect(html).not.toMatch(
			/<(svg|math|style|form|input|button)\b|onerror/i,
		);
	});

	it("neutralises deeply nested payloads", () => {
		const depth = 600;
		const payload =
			"<div>".repeat(depth) +
			'<img src="x" onerror="alert(1)">' +
			"</div>".repeat(depth);
		const html = sanitize(payload);
		expect(html).not.toMatch(/onerror/i);

		const container = document.createElement("div");
		container.innerHTML = html;
		expect(container.querySelector("[onerror]")).toBeNull();
	});

	it("is stable when its output is parsed again", () => {
		const payloads = [
			'<svg></p><style><a id="</style><img src=1 onerror=alert(1)>">',
			"<form><math><mtext></form><form><mglyph><style></math><img src onerror=alert(1)>",
			'<noscript><p title="</noscript><img src=x onerror=alert(1)>">',
			'<template><img src=x onerror="alert(1)"></template>',
		];
		for (const payload of payloads) {
			const once = sanitize(payload);
			const container = document.createElement("div");
			container.innerHTML = once;
			expect(container.querySelector("[onerror]")).toBeNull();
			expect(sanitize(container.innerHTML)).toBe(container.innerHTML);
		}
	});

	it("keeps annotation background colours and drops other inline styles", () => {
		expect(
			sanitize(
				'<span class="CoreAnnotatedText__annotation" style="background: rgb(180, 237, 238)">a</span>',
			),
		).toContain('style="background: rgb(180, 237, 238)"');
		expect(
			sanitize(
				'<div style="position:fixed;inset:0;background:url(https://evil.test)">x</div>',
			),
		).toBe("<div>x</div>");
	});

	it.each([
		["background: red", true],
		["background-color: #ffcc00;", true],
		["background: hsl(10, 50%, 50%)", true],
		["background: rgb(255 0 0 / 50%)", true],
		["background: red /* x */", false],
		["background: url(https://evil.test/x)", false],
		["background: red; position: fixed", false],
		["background: image-set('x.png' 1x)", false],
		["background: var(--x)", false],
		["color: red", false],
	])("isSafeInlineStyle(%s) is %s", (value, expected) => {
		expect(isSafeInlineStyle(value)).toBe(expected);
	});
});
