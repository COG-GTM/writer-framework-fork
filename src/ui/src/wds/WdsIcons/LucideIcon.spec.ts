import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import LucideIcon from "./LucideIcon.vue";

describe("LucideIcon", () => {
	it("renders the matching Lucide SVG", () => {
		const wrapper = mount(LucideIcon, { props: { name: "badge-check" } });

		const svg = wrapper.element.querySelector("svg");
		expect(svg).not.toBeNull();
		expect(svg?.getAttribute("data-lucide")).toBe("badge-check");
		expect(svg?.getAttribute("width")).toBe("1em");
		expect(svg?.classList.contains("lucide-badge-check")).toBe(true);
	});

	it("updates the SVG when the name changes", async () => {
		const wrapper = mount(LucideIcon, { props: { name: "badge-check" } });

		await wrapper.setProps({ name: "trash" });

		const svgs = wrapper.element.querySelectorAll("svg");
		expect(svgs).toHaveLength(1);
		expect(svgs[0].getAttribute("data-lucide")).toBe("trash");
	});

	it("renders nothing for unknown icon names", () => {
		const wrapper = mount(LucideIcon, {
			props: { name: "not-a-real-icon" },
		});

		expect(wrapper.element.childNodes).toHaveLength(0);
	});

	it("does not inject markup from the icon name", async () => {
		const payload = 'x"><img src=x onerror="window.__lucideXss=1">';
		const wrapper = mount(LucideIcon, { props: { name: payload } });

		expect(wrapper.element.querySelector("img")).toBeNull();
		expect(wrapper.element.childNodes).toHaveLength(0);

		await wrapper.setProps({ name: 'badge-check"><img src=x>' });
		expect(wrapper.element.querySelector("img")).toBeNull();
		expect(wrapper.element.childNodes).toHaveLength(0);
	});

	it("ignores prototype keys", () => {
		const wrapper = mount(LucideIcon, { props: { name: "constructor" } });

		expect(wrapper.element.childNodes).toHaveLength(0);
	});
});
