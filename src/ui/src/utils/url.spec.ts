import { describe, expect, it, vi, beforeAll, afterAll } from "vitest";
import {
	convertAbsolutePathtoFullURL,
	resolveAssetURL,
	sanitizeUrl,
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

describe(sanitizeUrl.name, () => {
	const base = "http://localhost:3000/app/";

	it.each([
		"https://writer.com",
		"http://example.com/path?q=1",
		"mailto:hello@writer.com",
		"tel:+15555555555",
		"#page-key",
		"/absolute/path",
		"relative/path",
		"./relative",
		"//cdn.example.com/x",
	])("should keep the safe URL %s", (url) => {
		expect(sanitizeUrl(url, base)).toBe(url);
	});

	it.each([
		"javascript:alert(1)",
		"JavaScript:alert(1)",
		" javascript:alert(1)",
		"\tjava\nscript:alert(1)",
		"data:text/html,<script>alert(1)</script>",
		"vbscript:msgbox(1)",
		"file:///etc/passwd",
		"blob:http://localhost:3000/uuid",
		"http://[invalid",
	])("should block the unsafe URL %j", (url) => {
		expect(sanitizeUrl(url, base)).toBe("about:blank");
	});

	it("should return an empty string for empty values", () => {
		expect(sanitizeUrl("", base)).toBe("");
		expect(sanitizeUrl("   ", base)).toBe("");
		expect(sanitizeUrl(undefined, base)).toBe("");
		expect(sanitizeUrl(null, base)).toBe("");
	});
});
