import { describe, expect, it, vi, beforeAll, afterAll } from "vitest";
import {
	convertAbsolutePathtoFullURL,
	EMBED_URL_PROTOCOLS,
	LINK_URL_PROTOCOLS,
	MEDIA_URL_PROTOCOLS,
	resolveAssetURL,
	sanitizeURL,
} from "./url";

describe(convertAbsolutePathtoFullURL.name, () => {
	it("should convert the URL", () => {
		expect(
			convertAbsolutePathtoFullURL(
				"/assets/image.png",
				"http://localhost:3000/",
			),
		).toBe("http://localhost:3000/assets/image.png");
	});

	it("should convert the URL with a current path", () => {
		expect(
			convertAbsolutePathtoFullURL(
				"/assets/image.png",
				"http://localhost:3000/hello/?foo=bar",
			),
		).toBe("http://localhost:3000/hello/assets/image.png");
	});
});

describe(resolveAssetURL.name, () => {
	beforeAll(() => {
		vi.stubGlobal("location", new URL("http://localhost:3000/"));
	});

	afterAll(() => {
		vi.unstubAllGlobals();
	});

	it("Should build the absolute URL from the absolute path", () => {
		expect(resolveAssetURL("/assets/image.png")).toBe(
			"http://localhost:3000/assets/image.png",
		);
	});

	it("Should not change the relative path", () => {
		expect(resolveAssetURL("./assets/image.png")).toBe(
			"./assets/image.png",
		);
	});

	it("Should not change the relative path without leading .", () => {
		expect(resolveAssetURL("assets/image.png")).toBe("assets/image.png");
	});

	it("Should not change the absolute path", () => {
		expect(resolveAssetURL("http://someserver/assets/image.png")).toBe(
			"http://someserver/assets/image.png",
		);
	});
});

describe(sanitizeURL.name, () => {
	const base = "https://app.example.com/";

	it.each([
		"https://example.com/page",
		"http://example.com/page",
		"blob:https://app.example.com/0b8f-1c2d",
		"static/report.html",
		"/static/report.html",
		"//cdn.example.com/embed",
	])("should allow %s for embeds", (url) => {
		expect(sanitizeURL(url, EMBED_URL_PROTOCOLS, base)).toBe(url);
	});

	it.each([
		"javascript:alert(document.domain)",
		"JavaScript:alert(1)",
		" javascript:alert(1)",
		"java\tscript:alert(1)",
		"java\nscript:alert(1)",
		"\u0001javascript:alert(1)",
		"vbscript:msgbox(1)",
		"data:text/html,<script>alert(1)</script>",
		"file:///etc/passwd",
	])("should reject %j for embeds", (url) => {
		expect(sanitizeURL(url, EMBED_URL_PROTOCOLS, base)).toBe("");
	});

	it("should allow data URLs for media only", () => {
		const img = "data:image/png;base64,iVBORw0KGgo=";
		expect(sanitizeURL(img, MEDIA_URL_PROTOCOLS, base)).toBe(img);
		expect(sanitizeURL(img, EMBED_URL_PROTOCOLS, base)).toBe("");
		expect(
			sanitizeURL("javascript:alert(1)", MEDIA_URL_PROTOCOLS, base),
		).toBe("");
	});

	it("should allow page anchors, mailto and tel for links", () => {
		for (const url of ["#main", "mailto:a@b.co", "tel:+15555550100"]) {
			expect(sanitizeURL(url, LINK_URL_PROTOCOLS, base)).toBe(url);
		}
		expect(
			sanitizeURL("javascript:void(0)", LINK_URL_PROTOCOLS, base),
		).toBe("");
	});

	it.each([undefined, null, "", "   ", 42, {}])(
		"should return an empty string for %j",
		(value) => {
			expect(sanitizeURL(value, EMBED_URL_PROTOCOLS, base)).toBe("");
		},
	);
});
