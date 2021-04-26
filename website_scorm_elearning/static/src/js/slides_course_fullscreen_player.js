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
            var res = this._super.apply(this, arguments);
            slidesDataList.forEach(function (slideData, index) {
                if (slideData.type === 'scorm') {
                    slideData.embedUrl = $(slideData.embedCode).attr('src');
                } else {
                    return res;
                }
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
