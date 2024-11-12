/** @odoo-module **/

import publicWidget from '@web/legacy/js/public/public_widget';
import { rpc } from "@web/core/network/rpc";

var findSlide = function (slideList, matcher) {
    return slideList.find((slide) => {
        return Object.keys(matcher).every((key) => matcher[key] === slide[key]);
    });
};

var API = publicWidget.Widget.extend({
    init: function () {
        var result = this._super.apply(this, arguments);
        this.rpc = rpc;
        var slideId = parseInt($('.o_wslides_lesson_aside_list_link.active').data('id'));
        var $slides = $('.o_wslides_lesson_aside_list_link').not('[id^="category-collapse-"]');
        var slideList = [];
        $slides.each(function () {
            var slideData = $(this).data();
            slideList.push(slideData);
        });
        var slide = findSlide(slideList, {
            id: slideId,
        });
        this.slide = slide;
        this.values = {};
        this.rpc('/slide/slide/get_session_info', {
            slide_id: this.slide.id,
        }).then(data => {
            this.values = data;
        })

        this.LMSInitialize = function(){
            return "true";
        }
        this.LMSSetValue = function(element, value){
            this.values[element] = value;
            this.rpc('/slide/slide/set_session_info', {
                slide_id: this.slide.id,
                element: element,
                value: value,
            })
            if ((['cmi.completion_status', 'cmi.core.lesson_status'].includes(element)) && (['completed', 'passed'].includes(value))) {
                this.rpc('/slides/slide/set_completed_scorm', {
                    slide_id: this.slide.id,
                    completion_type: value,
                }).then(data => {
                    this.slide.completed = true;
                    var $elem = $('.fa-circle-thin[data-slide-id="'+this.slide.id+'"]');
                    $elem.removeClass('fa-circle-thin').addClass('fa-check text-success o_wslides_slide_completed');
                    var channelCompletion = data.channel_completion;
                    var completion = Math.min(100, channelCompletion);
                    $('.progress-bar').css('width', completion + "%" );
                    $('.o_wslides_progress_percentage').text(completion);
                });
            };
            return "true";
        }
        this.LMSGetValue = function(element) {
            return this.values[element];
        }
        this.LMSGetLastError = function() {
            return 0;
        }
        this.LMSGetErrorString = function(errorCode) {
            return "error string";
        }
        this.LMSGetDiagnostic = function(errorCode) {
            return "diagnostic string";
        }
        this.LMSCommit = function() {
            this.LMSGetValue('');
            return "true";
        }
        this.LMSFinish = function() {
            return "true";
        }
        return result;
    },
});

var API_1484_11 = publicWidget.Widget.extend({
    init: function () {
        var result = this._super.apply(this, arguments);
        this.rpc = rpc;
        var slideId = parseInt($('.o_wslides_lesson_aside_list_link.active').data('id'));
        var $slides = $('.o_wslides_lesson_aside_list_link').not('[id^="category-collapse-"]');
        var slideList = [];
        $slides.each(function () {
            var slideData = $(this).data();
            slideList.push(slideData);
        });
        this.slide = findSlide(slideList, {id: slideId});
        this.values = {};
        this.rpc('/slide/slide/get_session_info', {
            slide_id: this.slide.id,
        }).then(data => {
            this.values = data;
        })

        this.Initialize = function(){
            var returnValue = true;
            return returnValue;
        }
        this.SetValue = function(element, value){
            if (isNaN(value)) {
                value = 0;
            }
            this.values[element] = value;
            this.rpc('/slide/slide/set_session_info', {
                slide_id: this.slide.id,
                element: element,
                value: value,
            })
            if ((['cmi.completion_status', 'cmi.core.lesson_status'].includes(element)) && (['completed', 'passed'].includes(value))) {
                this.rpc('/slides/slide/set_completed_scorm', {
                    slide_id: this.slide.id,
                    completion_type: value,
                }).then(data => {
                    this.slide.completed = true;
                    var $elem = $('.fa-circle-thin[data-slide-id="'+this.slide.id+'"]');
                    $elem.removeClass('fa-circle-thin').addClass('fa-check text-success o_wslides_slide_completed');
                    var channelCompletion = data.channel_completion;
                    var completion = Math.min(100, channelCompletion);
                    $('.progress-bar').css('width', completion + "%" );
                    $('.o_wslides_progress_percentage').text(completion);
                });
            }

            return "true";
        }
        this.GetValue = function(element) {
            var value = this.values[element];
            if (value == undefined) {
                value = '';
            }
            return value;
        }
        this.GetLastError = function() {
            return 0;
        }
        this.GetErrorString = function(errorCode) {
            return "error string";
        }
        this.GetDiagnostic = function(errorCode) {
            return "diagnostic string";
        }
        this.Commit = function() {
            return true;
        }
        this.Terminate = function() {
            return "true";
        }
        return result;
    },
});


publicWidget.registry.Scorm = publicWidget.Widget.extend({
    selector: '.o_wslides_lesson_content_type',

    init: function() {
        this._super.apply(this, arguments);
        this.rpc = rpc;
    },

    /**
     * @override
     */
    start: function () {
        var currentSlide = parseInt($('#scorm_content').attr('slide_id'));
        $('#scorm_content').append($('#iframe_src').attr('value'));
        $('#iframe_src').remove();
        if (!(isNaN(currentSlide))) {
            this.rpc("/slides/slide/get_scorm_version",{
                'slide_id': currentSlide
            }).then(function (data){
                if (data.scorm_version === 'scorm11') {
                    window.API = new API(currentSlide, 'scorm');
                }
                if (data.scorm_version === 'scorm2004') {
                    window.API_1484_11 = new API_1484_11(currentSlide, 'scorm');
                }
            });
        }
    },
});