/** @odoo-module **/

import { Interaction } from "@web/public/interaction";
import { registry } from "@web/core/registry";


export class WebsiteSlidesScormFullscreen extends Interaction {

    static selector = ".o_wslides_fs_main";


    setup() {
        console.log(
            "========== SCORM FULLSCREEN INTERACTION =========="
        );

        this.slidesService = this.services.website_slides;

        this.scormContainer = null;
        this.scormIframe = null;

        this.currentSlideId = null;

        this.renderTimer = null;
        this.destroyed = false;

        this._mutationObserver = null;
        this._resizeObserver = null;
        this._resizeHandler = null;
    }


    start() {
        console.log(
            "========== SCORM FULLSCREEN START =========="
        );

        console.log(
            "Odoo fullscreen element:",
            this.el
        );

        console.log(
            "Slides service:",
            this.slidesService
        );


        /*
         * IMPORTANT:
         *
         * We observe Odoo's existing fullscreen content area.
         *
         * Odoo changes the content when the user selects
         * another slide.
         *
         * We don't create our own fullscreen.
         */
        this.startContentObserver();


        /*
         * Initial render.
         */
        this.renderTimer = setTimeout(() => {

            this.renderScorm();

        }, 150);


        return this;
    }


    /**
     * ============================================================
     * FIND ODOO CONTENT
     * ============================================================
     */
    getContentContainer() {

        return (
            this.el.querySelector(
                ".o_wslides_fs_content"
            )
            ||
            document.querySelector(
                ".o_wslides_fs_main .o_wslides_fs_content"
            )
        );
    }


    /**
     * ============================================================
     * WATCH ODOO SLIDE CONTENT
     * ============================================================
     *
     * This is the important part.
     *
     * Odoo itself changes the DOM when the selected slide changes.
     *
     * We watch that existing container instead of guessing
     * which EventBus event Odoo is using.
     */
    startContentObserver() {

        const content =
            this.getContentContainer();


        if (!content) {

            console.warn(
                "SCORM: fullscreen content not available yet"
            );


            setTimeout(() => {

                if (!this.destroyed) {

                    this.startContentObserver();

                }

            }, 100);

            return;
        }


        console.log(
            "SCORM: starting Odoo content MutationObserver"
        );


        this._mutationObserver =
            new MutationObserver(
                (mutations) => {

                    if (this.destroyed) {
                        return;
                    }


                    /*
                     * Ignore our own iframe mutations.
                     */
                    let externalChange = false;


                    for (
                        const mutation of mutations
                    ) {

                        if (
                            mutation.type !==
                            "childList"
                        ) {
                            continue;
                        }


                        const target =
                            mutation.target;


                        /*
                         * If the mutation belongs to our
                         * SCORM container, ignore it.
                         */
                        if (
                            this.scormContainer &&
                            (
                                target ===
                                this.scormContainer
                                ||
                                this.scormContainer.contains(
                                    target
                                )
                            )
                        ) {

                            continue;
                        }


                        externalChange = true;

                        break;
                    }


                    if (externalChange) {

                        console.log(
                            "SCORM: Odoo fullscreen content changed"
                        );


                        this.scheduleRender();
                    }
                }
            );


        this._mutationObserver.observe(
            content,
            {
                childList: true,
                subtree: true,
            }
        );
    }


    /**
     * ============================================================
     * SCHEDULE RENDER
     * ============================================================
     */
    scheduleRender() {

        clearTimeout(
            this.renderTimer
        );


        this.renderTimer =
            setTimeout(() => {

                if (!this.destroyed) {

                    this.renderScorm();

                }

            }, 80);
    }


    /**
     * ============================================================
     * RENDER SCORM
     * ============================================================
     */
    renderScorm() {

        if (this.destroyed) {
            return;
        }


        console.log(
            "========== SCORM RENDER =========="
        );


        const slide =
            this.slidesService?.data?.slide;


        console.log(
            "Current slide:",
            slide
        );


        if (!slide) {

            console.warn(
                "SCORM: no current slide"
            );

            this.removeScorm();

            return;
        }


        /*
         * Only handle SCORM slides.
         */
        if (
            slide.category !== "scorm"
        ) {

            console.log(
                "SCORM: current slide is not SCORM"
            );


            this.removeScorm();

            return;
        }


        /*
         * Find SCORM URL.
         */
        const scormUrl =
            this.getScormUrl(slide);


        console.log(
            "SCORM URL:",
            scormUrl
        );


        if (!scormUrl) {

            console.error(
                "SCORM: URL not found"
            );

            this.removeScorm();

            return;
        }


        /*
         * If this exact slide is already loaded,
         * don't reload the Storyline application.
         */
        if (
            this.currentSlideId === slide.id &&
            this.scormIframe &&
            this.scormIframe.isConnected
        ) {

            console.log(
                "SCORM: current slide already loaded"
            );


            this.updateScormSize();

            return;
        }


        /*
         * Remove previous SCORM.
         */
        this.removeScorm();


        /*
         * Find Odoo's content area.
         */
        const content =
            this.getContentContainer();


        if (!content) {

            console.warn(
                "SCORM: Odoo content container not found"
            );


            this.scheduleRender();

            return;
        }


        console.log(
            "SCORM content container:",
            content
        );


        /*
         * ========================================================
         * SCORM CONTAINER
         * ========================================================
         */
        const container =
            document.createElement(
                "div"
            );


        container.className =
            "o_wslides_fs_scorm_custom";


        container.dataset.slideId =
            String(slide.id);


        /*
         * Fill Odoo's content area.
         */
        Object.assign(
            container.style,
            {
                width: "100%",
                height: "100%",
                minWidth: "0",
                minHeight: "0",
                display: "flex",
                flex: "1 1 auto",
                position: "relative",
                overflow: "hidden",
            }
        );


        /*
         * ========================================================
         * IFRAME
         * ========================================================
         */
        const iframe =
            document.createElement(
                "iframe"
            );


        iframe.className =
            "o_wslides_iframe_viewer";


        iframe.src =
            this.makeAbsoluteUrl(
                scormUrl
            );


        iframe.setAttribute(
            "frameborder",
            "0"
        );


        iframe.setAttribute(
            "title",
            "SCORM Content"
        );


        iframe.setAttribute(
            "allow",
            "autoplay; fullscreen; clipboard-read; clipboard-write"
        );


        iframe.setAttribute(
            "allowfullscreen",
            ""
        );


        Object.assign(
            iframe.style,
            {
                width: "100%",
                height: "100%",
                minWidth: "0",
                minHeight: "0",
                border: "0",
                display: "block",
            }
        );


        /*
         * Add iframe.
         */
        container.appendChild(
            iframe
        );


        /*
         * Add to Odoo fullscreen content.
         */
        content.appendChild(
            container
        );


        /*
         * Save references.
         */
        this.scormContainer =
            container;


        this.scormIframe =
            iframe;


        this.currentSlideId =
            slide.id;


        console.log(
            "========== SCORM INSERTED INTO ODOO CONTENT =========="
        );


        console.log(
            "Slide ID:",
            slide.id
        );


        console.log(
            "SCORM container:",
            container
        );


        console.log(
            "SCORM iframe:",
            iframe
        );


        console.log(
            "Iframe connected:",
            iframe.isConnected
        );


        console.log(
            "Odoo content rect:",
            content.getBoundingClientRect()
        );


        console.log(
            "SCORM iframe rect:",
            iframe.getBoundingClientRect()
        );


        /*
         * ========================================================
         * IFRAME LOAD
         * ========================================================
         */
        iframe.addEventListener(
            "load",
            () => {

                if (this.destroyed) {
                    return;
                }


                console.log(
                    "========== SCORM IFRAME LOADED =========="
                );


                console.log(
                    "SCORM URL:",
                    iframe.src
                );


                console.log(
                    "Iframe connected:",
                    iframe.isConnected
                );


                this.updateScormSize();
            }
        );


        /*
         * ========================================================
         * RESIZE OBSERVER
         * ========================================================
         */
        if (
            typeof ResizeObserver !==
            "undefined"
        ) {

            this._resizeObserver =
                new ResizeObserver(
                    () => {

                        if (
                            !this.destroyed
                        ) {

                            this.updateScormSize();
                        }
                    }
                );


            this._resizeObserver.observe(
                content
            );
        }


        /*
         * Browser resize.
         */
        this._resizeHandler =
            () => {

                this.updateScormSize();
            };


        window.addEventListener(
            "resize",
            this._resizeHandler
        );


        /*
         * Final check.
         */
        setTimeout(() => {

            if (
                this.destroyed
            ) {
                return;
            }


            console.log(
                "========== SCORM 1 SECOND CHECK =========="
            );


            console.log(
                "Current slide ID:",
                this.currentSlideId
            );


            console.log(
                "Container connected:",
                container.isConnected
            );


            console.log(
                "Iframe connected:",
                iframe.isConnected
            );


            console.log(
                "Content connected:",
                content.isConnected
            );


            console.log(
                "Content rect:",
                content.getBoundingClientRect()
            );


            console.log(
                "SCORM rect:",
                iframe.getBoundingClientRect()
            );


        }, 1000);
    }


    /**
     * ============================================================
     * UPDATE SIZE
     * ============================================================
     */
    updateScormSize() {

        if (
            this.destroyed ||
            !this.scormContainer ||
            !this.scormIframe
        ) {
            return;
        }


        if (
            !this.scormContainer.isConnected ||
            !this.scormIframe.isConnected
        ) {
            return;
        }


        const content =
            this.getContentContainer();


        if (!content) {
            return;
        }


        /*
         * Odoo owns the fullscreen dimensions.
         *
         * We only fill the content area.
         */
        content.style.minWidth =
            "0";

        content.style.minHeight =
            "0";


        this.scormContainer.style.width =
            "100%";

        this.scormContainer.style.height =
            "100%";


        this.scormIframe.style.width =
            "100%";

        this.scormIframe.style.height =
            "100%";


        /*
         * Do NOT use:
         *
         * position: fixed
         * top: 0
         * left: 0
         * width: 100vw
         * height: 100vh
         *
         * because that bypasses Odoo fullscreen.
         */
    }


    /**
     * ============================================================
     * REMOVE SCORM
     * ============================================================
     */
    removeScorm() {

        if (
            this._resizeObserver
        ) {

            this._resizeObserver.disconnect();

            this._resizeObserver =
                null;
        }


        if (
            this._resizeHandler
        ) {

            window.removeEventListener(
                "resize",
                this._resizeHandler
            );

            this._resizeHandler =
                null;
        }


        if (
            this.scormContainer &&
            this.scormContainer.isConnected
        ) {

            this.scormContainer.remove();
        }


        this.scormContainer =
            null;


        this.scormIframe =
            null;


        this.currentSlideId =
            null;
    }


    /**
     * ============================================================
     * FIND SCORM URL
     * ============================================================
     */
    getScormUrl(slide) {

        console.log(
            "========== FIND SCORM URL =========="
        );


        console.log(
            "Slide:",
            slide
        );


        /*
         * Direct URL.
         */
        if (slide.embedUrl) {
            return slide.embedUrl;
        }


        if (slide.embed_url) {
            return slide.embed_url;
        }


        if (slide.url) {
            return slide.url;
        }


        /*
         * Embed code.
         */
        const embedCode =
            slide.embedCode ||
            slide.embed_code ||
            slide.embedHtml ||
            slide.embed_html;


        if (!embedCode) {

            return null;
        }


        console.log(
            "SCORM embed code:",
            embedCode
        );


        try {

            const parser =
                new DOMParser();


            const doc =
                parser.parseFromString(
                    String(embedCode),
                    "text/html"
                );


            const iframe =
                doc.querySelector(
                    "iframe"
                );


            if (!iframe) {

                return null;
            }


            const src =
                iframe.getAttribute(
                    "src"
                );


            console.log(
                "SCORM URL found:",
                src
            );


            return src;

        } catch (error) {

            console.error(
                "SCORM embed parse error:",
                error
            );


            return null;
        }
    }


    /**
     * ============================================================
     * ABSOLUTE URL
     * ============================================================
     */
    makeAbsoluteUrl(url) {

        if (!url) {
            return url;
        }


        if (
            url.startsWith(
                "http://"
            ) ||
            url.startsWith(
                "https://"
            ) ||
            url.startsWith(
                "//"
            )
        ) {

            return url;
        }


        if (
            url.startsWith("/")
        ) {

            return (
                window.location.origin +
                url
            );
        }


        return new URL(
            url,
            window.location.href
        ).href;
    }


    /**
     * ============================================================
     * DESTROY
     * ============================================================
     */
    destroy() {

        console.log(
            "========== SCORM FULLSCREEN DESTROY =========="
        );


        this.destroyed =
            true;


        clearTimeout(
            this.renderTimer
        );


        if (
            this._mutationObserver
        ) {

            this._mutationObserver.disconnect();

            this._mutationObserver =
                null;
        }


        this.removeScorm();


        /*
         * IMPORTANT:
         *
         * Never do:
         *
         * this.isDestroyed = true;
         *
         * Interaction.isDestroyed is read-only.
         */
        if (
            typeof super.destroy ===
            "function"
        ) {

            super.destroy();
        }
    }
}


registry
    .category(
        "public.interactions"
    )
    .add(
        "website_scorm_elearning.scorm_fullscreen",
        WebsiteSlidesScormFullscreen
    );