/** @odoo-module **/

import { Interaction } from "@web/public/interaction";
import { registry } from "@web/core/registry";
import { rpc } from "@web/core/network/rpc";

/**
 * SCORM API Handler for standard lesson pages
 */
class SCORM_API {
    constructor(slideId) {
        this.slideId = slideId;
        this.values = {};
        this.initSession();
    }

    async initSession() {
        if (!this.slideId) return;
        try {
            const data = await rpc('/slide/slide/get_session_info', {
                slide_id: this.slideId,
            });
            this.values = data || {};
        } catch (e) {
            console.error("Failed to load SCORM session info", e);
        }
    }

    LMSInitialize() { return "true"; }
    Initialize() { return "true"; }

    LMSSetValue(element, value) { return this.SetValue(element, value); }
    SetValue(element, value) {
        if (value === undefined || value === null) value = "";
        this.values[element] = value;

        if (this.slideId) {
            rpc('/slide/slide/set_session_info', {
                slide_id: this.slideId,
                element: element,
                value: value,
            });

            if (['cmi.completion_status', 'cmi.core.lesson_status'].includes(element) && ['completed', 'passed'].includes(value)) {
                rpc('/slides/slide/set_completed_scorm', {
                    slide_id: this.slideId,
                    completion_type: value,
                }).then(data => {
                    const $elem = document.querySelector(`.fa-circle-thin[data-slide-id="${this.slideId}"]`);
                    if ($elem) {
                        $elem.classList.remove('fa-circle-thin');
                        $elem.classList.add('fa-check', 'text-success', 'o_wslides_slide_completed');
                    }
                    if (data && data.channel_completion !== undefined) {
                        const completion = Math.min(100, data.channel_completion);
                        const progressBars = document.querySelectorAll('.progress-bar');
                        progressBars.forEach(bar => bar.style.width = `${completion}%`);
                        const percentageLabels = document.querySelectorAll('.o_wslides_progress_percentage');
                        percentageLabels.forEach(lbl => lbl.textContent = completion);
                    }
                });
            }
        }
        return "true";
    }

    LMSGetValue(element) { return this.GetValue(element); }
    GetValue(element) {
        const val = this.values[element];
        return (val === undefined || val === null) ? "" : val;
    }

    LMSGetLastError() { return 0; }
    GetLastError() { return 0; }
    LMSGetErrorString() { return "error string"; }
    GetErrorString() { return "error string"; }
    LMSGetDiagnostic() { return "diagnostic string"; }
    GetDiagnostic() { return "diagnostic string"; }
    LMSCommit() { return "true"; }
    Commit() { return "true"; }
    LMSFinish() { return "true"; }
    Terminate() { return "true"; }
}

/**
 * Modern Interaction Handler for SCORM content on lesson pages
 */
export class WebsiteSlidesScormLesson extends Interaction {
    static selector = ".o_wslides_lesson_content_type, #scorm_content";

    async start() {
        const scormContent = this.el.id === "scorm_content" ? this.el : this.el.querySelector('#scorm_content');
        if (!scormContent) return;

        const iframeSrcEl = document.querySelector('#iframe_src');
        if (iframeSrcEl) {
            const iframeValue = iframeSrcEl.getAttribute('value');
            if (iframeValue) {
                scormContent.insertAdjacentHTML('beforeend', iframeValue);
            }
            iframeSrcEl.remove();
        }

        const slideId = parseInt(scormContent.getAttribute('slide_id')) || 0;
        if (slideId) {
            const scormApi = new SCORM_API(slideId);

            window.API = scormApi;
            window.API_1484_11 = scormApi;

            if (window.parent) {
                window.parent.API = scormApi;
                window.parent.API_1484_11 = scormApi;
            }
            if (window.top) {
                window.top.API = scormApi;
                window.top.API_1484_11 = scormApi;
            }

            try {
                const data = await rpc("/slides/slide/get_scorm_version", { slide_id: slideId });
                if (data) {
                    console.log("SCORM version:", data.scorm_version);
                }
            } catch (e) {
                console.warn("Could not fetch SCORM version", e);
            }
        }
    }
}

registry.category("public.interactions").add("website_slides.scorm_lesson", WebsiteSlidesScormLesson);