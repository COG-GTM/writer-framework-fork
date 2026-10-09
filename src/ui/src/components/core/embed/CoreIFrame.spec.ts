import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";
import { ref } from "vue";
import CoreIFrame from "./CoreIFrame.vue";
import injectionKeys from "@/injectionKeys";
import { mockProvides } from "@/tests/mocks";

const DEFAULT_SANDBOX =
	"allow-scripts allow-same-origin allow-forms allow-popups";

function mountIFrame(src: unknown, sandbox = DEFAULT_SANDBOX) {
	return mount(CoreIFrame, {
		global: {
			provide: {
				...mockProvides,
				[injectionKeys.evaluatedFields as symbol]: {
					src: ref(src),
					sandbox: ref(sandbox),
					referrerPolicy: ref("strict-origin-when-cross-origin"),
				},
			},
		},
	});
}

describe("CoreIFrame", () => {
	it("should render an https URL in a sandboxed iframe", () => {
		const wrapper = mountIFrame("https://example.com/embed");
		const iframe = wrapper.get("iframe");

		expect(iframe.attributes("src")).toBe("https://example.com/embed");
		expect(iframe.attributes("sandbox")).toBe(DEFAULT_SANDBOX);
	});

	it("should apply a custom sandbox", () => {
		expect(
			mountIFrame("https://example.com", "allow-scripts")
				.get("iframe")
				.attributes("sandbox"),
		).toBe("allow-scripts");
	});

	it.each([
		"javascript:alert(document.domain)",
		"  JaVaScRiPt:alert(1)",
		"java\tscript:alert(1)",
		"data:text/html,<script>alert(1)</script>",
		"vbscript:msgbox(1)",
	])("should not render an iframe for %j", (src) => {
		const wrapper = mountIFrame(src);

		expect(wrapper.find("iframe").exists()).toBe(false);
		expect(wrapper.text()).toContain("No URL provided.");
	});

	it("should render the empty state when no URL is set", () => {
		expect(mountIFrame("").find("iframe").exists()).toBe(false);
	});
});
