import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";
import { ref } from "vue";
import CoreLink from "./CoreLink.vue";
import injectionKeys from "@/injectionKeys";
import { mockProvides } from "@/tests/mocks";

function mountLink(url: string) {
	return mount(CoreLink, {
		global: {
			provide: {
				...mockProvides,
				[injectionKeys.evaluatedFields as symbol]: {
					url: ref(url),
					target: ref("_blank"),
					rel: ref(""),
					text: ref(""),
				},
			},
		},
	});
}

describe("CoreLink", () => {
	it.each(["https://writer.com", "#main", "mailto:team@writer.com"])(
		"should keep the href for %s",
		(url) => {
			expect(mountLink(url).get("a").attributes("href")).toBe(url);
		},
	);

	it("should drop a javascript: href but keep the text", () => {
		const a = mountLink("javascript:alert(1)").get("a");

		expect(a.attributes("href")).toBeUndefined();
		expect(a.text()).toBe("javascript:alert(1)");
	});
});
