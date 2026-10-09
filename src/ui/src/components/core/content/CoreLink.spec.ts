import { describe, expect, it, beforeAll, afterAll, vi } from "vitest";
import { mount } from "@vue/test-utils";
import { ref } from "vue";
import CoreLink from "./CoreLink.vue";
import injectionKeys from "@/injectionKeys";
import { mockProvides } from "@/tests/mocks";

function mountLink(fields: {
	url: string;
	target?: string;
	rel?: string;
	text?: string;
}) {
	return mount(CoreLink, {
		global: {
			provide: {
				...mockProvides,
				[injectionKeys.evaluatedFields as symbol]: {
					url: ref(fields.url),
					target: ref(fields.target ?? "_blank"),
					rel: ref(fields.rel ?? ""),
					text: ref(fields.text ?? ""),
				},
			},
		},
	});
}

describe("CoreLink", () => {
	beforeAll(() => {
		vi.stubGlobal("location", new URL("http://localhost:3000/"));
	});

	afterAll(() => {
		vi.unstubAllGlobals();
	});

	it("should bind safe URLs to href", () => {
		const a = mountLink({ url: "https://writer.com" }).get("a");
		expect(a.attributes("href")).toBe("https://writer.com");
		expect(a.text()).toBe("https://writer.com");
	});

	it("should keep page key links", () => {
		const a = mountLink({ url: "#home", target: "_self" }).get("a");
		expect(a.attributes("href")).toBe("#home");
	});

	it.each(["javascript:alert(document.domain)", " JaVaScRiPt:alert(1)"])(
		"should not bind the unsafe URL %j to href",
		(url) => {
			const a = mountLink({ url, target: "_self", text: "Docs" }).get(
				"a",
			);
			expect(a.attributes("href")).toBe("about:blank");
			expect(a.text()).toBe("Docs");
		},
	);

	it("should default rel to noopener noreferrer for _blank", () => {
		const a = mountLink({ url: "https://writer.com" }).get("a");
		expect(a.attributes("rel")).toBe("noopener noreferrer");
	});

	it("should keep an explicit rel", () => {
		const a = mountLink({ url: "https://writer.com", rel: "nofollow" }).get(
			"a",
		);
		expect(a.attributes("rel")).toBe("nofollow");
	});

	it("should not set rel for _self without an explicit rel", () => {
		const a = mountLink({ url: "#home", target: "_self" }).get("a");
		expect(a.attributes("rel")).toBeUndefined();
	});
});
