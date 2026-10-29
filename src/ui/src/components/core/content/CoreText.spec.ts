import { describe, expect, it, beforeAll } from "vitest";
import BaseMarkdown from "../base/BaseMarkdown.vue";
import CoreText from "./CoreText.vue";
import injectionKeys from "@/injectionKeys";
import { buildMockComponent, buildMockCore, mockProvides } from "@/tests/mocks";
import { flushPromises, mount } from "@vue/test-utils";
import { ref } from "vue";
import { Core } from "@/writerTypes";
import VueDOMPurifyHTML from "vue-dompurify-html";
import { VUE_DOMPURIFY_HTML_OPTIONS } from "@/utils/sanitizeHtml";

describe("CoreText", async () => {
	const text = `# Hello\n\nI'm the **content**.`;
	let core: Core;

	beforeAll(() => {
		core = buildMockCore().core;

		core.addComponent(
			buildMockComponent({
				handlers: { "wf-click": "python_handler" },
			}),
		);
	});

	it("should render in non-markdown mode", () => {
		const wrapper = mount(CoreText, {
			global: {
				provide: {
					...mockProvides,
					[injectionKeys.core as symbol]: core,
					[injectionKeys.isBeingEdited as symbol]: ref(false),
					[injectionKeys.evaluatedFields as symbol]: {
						text: ref(text),
						alignment: ref("center"),
						useMarkdown: ref(false),
						quickCopy: ref(false),
					},
				},
			},
		});

		expect(wrapper.element).toMatchSnapshot();
	});

	it("should render in markdown mode", () => {
		const wrapper = mount(CoreText, {
			global: {
				provide: {
					...mockProvides,
					[injectionKeys.core as symbol]: core,
					[injectionKeys.isBeingEdited as symbol]: ref(false),
					[injectionKeys.evaluatedFields as symbol]: {
						text: ref(text),
						alignment: ref("center"),
						useMarkdown: ref(true),
						quickCopy: ref(false),
					},
				},
			},
		});

		expect(wrapper.findComponent(BaseMarkdown).exists()).toBe(true);

		expect(wrapper.element).toMatchSnapshot();
	});

	it("should not render script from nested mXSS payloads in markdown mode", async () => {
		const depth = 600;
		const payloads = [
			"<div>".repeat(depth) +
				'<img src="x" onerror="alert(1)">' +
				"</div>".repeat(depth),
			'<svg></p><style><a id="</style><img src=1 onerror=alert(1)>">',
			"<form><math><mtext></form><form><mglyph><style></math><img src onerror=alert(1)>",
			'<noscript><p title="</noscript><img src=x onerror=alert(1)>">',
			"<script>alert(1)</script>",
		];

		for (const payload of payloads) {
			const wrapper = mount(CoreText, {
				global: {
					plugins: [[VueDOMPurifyHTML, VUE_DOMPURIFY_HTML_OPTIONS]],
					provide: {
						...mockProvides,
						[injectionKeys.core as symbol]: core,
						[injectionKeys.isBeingEdited as symbol]: ref(false),
						[injectionKeys.evaluatedFields as symbol]: {
							text: ref(`Answer:\n\n${payload}`),
							alignment: ref("left"),
							useMarkdown: ref(true),
							quickCopy: ref(false),
						},
					},
				},
			});
			await flushPromises();

			const markdown = wrapper.find(".BaseMarkdown");
			expect(markdown.exists()).toBe(true);
			expect(markdown.text()).toContain("Answer:");
			expect(markdown.element.querySelector("script")).toBeNull();
			expect(markdown.element.querySelector("[onerror]")).toBeNull();
			expect(markdown.html()).not.toMatch(/onerror|<script/i);
			wrapper.unmount();
		}
	});
});
