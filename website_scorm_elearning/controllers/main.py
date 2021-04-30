# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import http
from odoo.http import request
from odoo.addons.website_profile.controllers.main import WebsiteProfile


class WebsiteSlides(WebsiteProfile):

    @http.route('/slides/slide/get_scorm_version', type="json", auth="public", website=True)
    def get_scorm_version(self, slide_id):
        slide_dict = self._fetch_slide(slide_id)
        return {
            'scorm_version': slide_dict['slide'].scorm_version
        }

    @http.route('/slide/slide/set_session_info', type='json', auth="user", website=True)
    def _set_session_info(self, slide_id, element, value):
        slide_partner_sudo = request.env['slide.slide.partner'].sudo()
        slide_id = request.env['slide.slide'].browse(slide_id)
        slide_partner_id = slide_partner_sudo.search([
            ('slide_id', '=', slide_id.id),
            ('partner_id', '=', request.env.user.partner_id.id)], limit=1)
        if not slide_partner_id:
            slide_partner_id = slide_partner_sudo.create({
                'slide_id': slide_id.id,
                'channel_id': slide_id.channel_id.id,
                'partner_id': request.env.user.partner_id.id
            })
        session_element_id = slide_partner_id.lms_session_info_ids.filtered(lambda l: l.name == element)
        if session_element_id:
            session_element_id.value = value
        else:
            request.env['lms.session.info'].create({
                'name': element,
                'value': value,
                'slide_partner_id': slide_partner_id.id
            })

    @http.route('/slide/slide/get_session_info', type='json', auth="user", website=True)
    def _get_session_info(self, slide_id):
        slide_partner_sudo = request.env['slide.slide.partner'].sudo()
        slide_id = request.env['slide.slide'].browse(slide_id)
        slide_partner_id = slide_partner_sudo.search([
            ('slide_id', '=', slide_id.id),
            ('partner_id', '=', request.env.user.partner_id.id)], limit=1)
        session_info_ids = request.env['lms.session.info'].search([
            ('slide_partner_id', '=', slide_partner_id.id)
        ])
        values = {}
        for session_info in session_info_ids:
            values[session_info.name] = session_info.value
        return values
                
