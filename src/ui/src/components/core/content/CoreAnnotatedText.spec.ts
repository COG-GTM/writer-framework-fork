import { describe, expect, it, vi } from "vitest";
import BaseMarkdownRaw from "../base/BaseMarkdownRaw.vue";
import CoreAnnotatedText from "./CoreAnnotatedText.vue";
import VueDOMPurifyHTML from "vue-dompurify-html";
import injectionKeys from "@/injectionKeys";
import { buildMockCore, mockProvides } from "@/tests/mocks";
import { flushPromises, mount } from "@vue/test-utils";
import { ref } from "vue";
import { WdsColor } from "@/wds/tokens";

describe("CoreAnnotatedText", async () => {
	const text = [
		"# This\n\n",
		["**is**", "Verb", "red"],
		" some ",
		["_annotated_", "Adjective"],
		["text", "Noun"],
		". ",
		"## title 2\n\n",
		"And [here](https://google.com)'s paragraph 2",
	];

	it("should render in non-markdown mode", async () => {
		const { core } = buildMockCore();

		const wrapper = mount(CoreAnnotatedText, {
			global: {
				plugins: [VueDOMPurifyHTML],
				provide: {
					...mockProvides,
					[injectionKeys.core as symbol]: core,
					[injectionKeys.isBeingEdited as symbol]: ref(false),
					[injectionKeys.evaluatedFields as symbol]: {
						text: ref(text),
						seed: ref(1),
						useMarkdown: ref(false),
						rotateHue: ref(true),
						referenceColor: ref(WdsColor.Blue5),
						copyButtons: ref(true),
					},
				},
			},
		});

		await flushPromises();

		const annotations = wrapper.findAll(".CoreAnnotatedText__annotation");
		expect(annotations).toHaveLength(text.filter(Array.isArray).length);

		// should use the value provided
		expect(annotations.at(0).attributes().style).toBe(
			"background-color: red;",
		);

		// should generate the color
		expect(annotations.at(1).attributes().style).toMatchInlineSnapshot(
			`"background-color: rgb(180, 237, 238);"`,
		);

		expect(wrapper.element).toMatchSnapshot();
	});

	it("should render in markdown mode", async () => {
		const { core } = buildMockCore();

		const wrapper = mount(CoreAnnotatedText, {
			global: {
				plugins: [VueDOMPurifyHTML],
				provide: {
					...mockProvides,
					[injectionKeys.core as symbol]: core,
					[injectionKeys.isBeingEdited as symbol]: ref(false),
					[injectionKeys.evaluatedFields as symbol]: {
						text: ref(text),
						seed: ref(1),
						useMarkdown: ref(true),
						rotateHue: ref(true),
						referenceColor: ref(WdsColor.Blue5),
						copyButtons: ref(true),
					},
				},
			},
		});

		await flushPromises();

		expect(
			wrapper.getComponent(BaseMarkdownRaw).props().rawMarkdown,
		).toMatchSnapshot();
	});

	it("should escape annotation content, subject and color in markdown mode", async () => {
		const { core } = buildMockCore();

		const wrapper = mount(CoreAnnotatedText, {
			global: {
				plugins: [VueDOMPurifyHTML],
				provide: {
					...mockProvides,
					[injectionKeys.core as symbol]: core,
					[injectionKeys.isBeingEdited as symbol]: ref(false),
					[injectionKeys.evaluatedFields as symbol]: {
						text: ref([
							"Hello ",
							[
								'<a href="/phish">**click**</a>',
								'<form action="/phish"></form>',
								'red;position:fixed;inset:0;z-index:9999" title="x',
							],
							["ok", "Noun", "#faf"],
							["themed", "Noun", "var(--accentColor)"],
						]),
						seed: ref(1),
						useMarkdown: ref(true),
						rotateHue: ref(false),
						referenceColor: ref(WdsColor.Blue5),
						copyButtons: ref(false),
					},
				},
			},
		});

		const getRawMarkdown = () =>
			wrapper.getComponent(BaseMarkdownRaw).props().rawMarkdown;
		await vi.waitFor(() => expect(getRawMarkdown()).not.toBe(""));
		const rawMarkdown = getRawMarkdown();

		expect(rawMarkdown).not.toContain("<a ");
		expect(rawMarkdown).not.toContain("<form");
		expect(rawMarkdown).not.toContain("position:fixed");
		expect(rawMarkdown).toContain(
			"&lt;a href=&quot;/phish&quot;&gt;<strong>click</strong>&lt;/a&gt;",
		);

		await flushPromises();
		const annotations = wrapper.findAll(".CoreAnnotatedText__annotation");
		expect(annotations).toHaveLength(3);
		// invalid color falls back to the reference color
		expect(annotations.at(0).attributes().style).not.toContain("fixed");
		expect(annotations.at(0).attributes().title).toBeUndefined();
		expect(annotations.at(0).find("a").exists()).toBe(false);
		expect(annotations.at(0).find("form").exists()).toBe(false);
		expect(annotations.at(1).attributes().style).toContain(
			"rgb(255,170,255)",
		);
		expect(annotations.at(2).attributes().style).toContain(
			"var(--accentColor)",
		);
	});
});
