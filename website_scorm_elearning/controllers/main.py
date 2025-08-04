# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

import boto3
import mimetypes
from odoo import http
from odoo.http import request, Response
from odoo.addons.website_slides.controllers.main import WebsiteSlides


class WebsiteSlidesScorm(WebsiteSlides):

    @http.route('/slides/slide/get_scorm_version', type="json", auth="public", website=True, core='*')
    def get_scorm_version(self, slide_id):
        slide_dict = self._fetch_slide(slide_id)
        return {
            'scorm_version': slide_dict['slide'].scorm_version
        }

    @http.route('/slide/slide/set_session_info', type='json', auth="user", website=True, cors='*')
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

    @http.route('/slide/slide/get_session_info', type='json', auth="user", website=True, cors='*')
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

    @http.route('/slides/slide/set_completed_scorm', website=True, type="json", auth="public")
    def slide_set_completed_scorm(self, slide_id, completion_type):
        if request.website.is_public_user():
            return {'error': 'public_user'}
        fetch_res = self._fetch_slide(slide_id)
        slide = fetch_res['slide']
        if fetch_res.get('error'):
            return fetch_res
        if slide.website_published and slide.channel_id.is_member:
            slide.action_mark_completed()
        self._set_karma_points(fetch_res['slide'], completion_type)
        return {
            'channel_completion': fetch_res['slide'].channel_id.completion
        }

    def _set_karma_points(self, slide_id, completion_type):
        slide_partner_sudo = request.env['slide.slide.partner'].sudo()
        slide_partner_id = slide_partner_sudo.search([
            ('slide_id', '=', slide_id.id),
            ('partner_id', '=', request.env.user.partner_id.id)], limit=1)
        if slide_partner_id:
            user_sudo = request.env['res.users'].sudo()
            user_id = user_sudo.search([('partner_id', '=', slide_partner_id.partner_id.id)], limit=1)
            if completion_type == 'passed':
                slide_partner_id.lms_scorm_karma = slide_id.scorm_passed_xp
                user_id.karma = slide_id.scorm_passed_xp
            if completion_type == 'completed':
                slide_partner_id.lms_scorm_karma = slide_id.scorm_completed_xp
                user_id.karma = slide_id.scorm_passed_xp


    @http.route(['/scorm/<path:file_path>'], type='http', auth='public', website=True)
    def scorm_proxy(self, file_path, **kwargs):
        amazon_access_key = request.env['ir.config_parameter'].sudo().get_param('amazon_s3_connector.amazon_access_key')
        amazon_secret_key = request.env['ir.config_parameter'].sudo().get_param('amazon_s3_connector.amazon_secret_key')
        bucket_name = request.env['ir.config_parameter'].sudo().get_param('amazon_s3_connector.amazon_bucket_name')

        if not amazon_access_key or not amazon_secret_key or not bucket_name:
            return Response("Amazon S3 credentials are not properly configured.", status=500)

        # Determine MIME type
        content_type, _ = mimetypes.guess_type(file_path)
        if not content_type:
            content_type = 'application/octet-stream'

        try:
            s3 = boto3.client(
                's3',
                aws_access_key_id=amazon_access_key,
                aws_secret_access_key=amazon_secret_key
            )

            s3_response = s3.get_object(Bucket=bucket_name, Key=file_path)
            content = s3_response['Body'].read()

            return Response(
                content,
                content_type=content_type,
                headers=[("Content-Disposition", f"inline; filename=\"{file_path.split('/')[-1]}\"")]
            )

        except Exception as e:
            return Response(f"Error loading SCORM file: {str(e)}", status=404)