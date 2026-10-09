import { describe, expect, it } from "vitest";
import { escapeHtml } from "./html";

describe(escapeHtml.name, () => {
	it("should escape HTML special characters", () => {
		expect(escapeHtml(`<a href="x" title='y'>&</a>`)).toBe(
			"&lt;a href=&quot;x&quot; title=&#39;y&#39;&gt;&amp;&lt;/a&gt;",
		);
	});

	it("should keep markdown syntax untouched", () => {
		expect(escapeHtml("**bold** _it_ [link](https://x.y)")).toBe(
			"**bold** _it_ [link](https://x.y)",
		);
	});

	it("should stringify non-string values", () => {
		expect(escapeHtml(42)).toBe("42");
		expect(escapeHtml(undefined)).toBe("");
		expect(escapeHtml(null)).toBe("");
	});
});
