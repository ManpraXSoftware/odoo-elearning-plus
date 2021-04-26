odoo.define('website_scorm_elearning.fullscreen_scorm', function (require) {
    'use strict';
    var core = require('web.core');
    var QWeb = core.qweb;
    var Fullscreen = require('website_slides.fullscreen');
    Fullscreen.include({
        xmlDependencies: (Fullscreen.prototype.xmlDependencies || []).concat(
            ["/website_scorm_elearning/static/src/xml/website_slides_fullscreen.xml"]
        ),
        _preprocessSlideData: function (slidesDataList) {
            slidesDataList.forEach(function (slideData, index) {
                // compute hasNext slide
                slideData.hasNext = index < slidesDataList.length-1;
                // compute embed url
                if (slideData.type === 'video') {
                    slideData.embedCode = $(slideData.embedCode).attr('src') || ""; // embedCode contains an iframe tag, where src attribute is the url (youtube or embed document from odoo)
                    var separator = slideData.embedCode.indexOf("?") !== -1 ? "&" : "?";
                    var scheme = slideData.embedCode.indexOf('//') === 0 ? 'https:' : '';
                    var params = { rel: 0, enablejsapi: 1, origin: window.location.origin };
                    if (slideData.embedCode.indexOf("//drive.google.com") === -1) {
                        params.autoplay = 1;
                    }
                    slideData.embedUrl = slideData.embedCode ? scheme + slideData.embedCode + separator + $.param(params) : "";
                } else if (slideData.type === 'infographic') {
                    slideData.embedUrl = _.str.sprintf('/web/image/slide.slide/%s/image_1024', slideData.id);
                } else if (_.contains(['document', 'presentation'], slideData.type)) {
                    slideData.embedUrl = $(slideData.embedCode).attr('src');
                } else if (slideData.type === 'scorm') {
                    slideData.embedUrl = $(slideData.embedCode).attr('src');
                }
                // fill empty property to allow searching on it with _.filter(list, matcher)
                slideData.isQuiz = !!slideData.isQuiz;
                slideData.hasQuestion = !!slideData.hasQuestion;
                // technical settings for the Fullscreen to work
                slideData._autoSetDone = _.contains(['infographic', 'presentation', 'document', 'webpage'], slideData.type) && !slideData.hasQuestion;
            });
            return slidesDataList;
        },

        /**
         * Extend the _renderSlide method so that slides of type "scorm"
         * are also taken into account and rendered correctly
         *
         * @private
         * @override
         */

        _renderSlide: function (){
            var def = this._super.apply(this, arguments);
            var $content = this.$('.o_wslides_fs_content');
            var slideId = this.get('slide');
            var self = this;
            if (slideId.type === "scorm"){
                $content.html(QWeb.render('website.slides.fullscreen.content',{widget: this}));
                this._rpc({
                    route: '/slides/slide/set_completed',
                    params: {
                        slide_id: slideId.id,
                    }
                }).then(function (data){
                    self._markAsCompleted(slideId.id, data.channel_completion);
                    return Promise.resolve();
                });
            }
            return Promise.all([def]);
        },
    });
});
