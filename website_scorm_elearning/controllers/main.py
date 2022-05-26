# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from cmath import e
import json
from isodate import duration_isoformat
import werkzeug
from tkinter import E
from urllib import response
from odoo import exceptions, http
from odoo.http import request
from odoo.addons.http_routing.models.ir_http import slug
from odoo import http, _, exceptions
from odoo.exceptions import UserError
from odoo.addons.website_slides.controllers.main import WebsiteSlides


class WebsiteSlidesScorm(WebsiteSlides):

    @http.route('/slides/slide/get_scorm_version', type="json", auth="public", website=True)
    def get_scorm_version(self, slide_id):
        slide_dict = self._fetch_slide(slide_id)
        scorm_datas = request.env['statement.scorm'].sudo().search([('activityId', '=', int(slide_id)),('user_id','=',request.uid)])
        if scorm_datas:
            return {
                'scorm_version': slide_dict['slide'].scorm_version,
                'type' : slide_dict['slide'].slide_type,
                'is_tincan' : slide_dict['slide'].is_tincan,
                'completed': slide_dict['slide'].user_membership_id.sudo().completed
            }
        else:
            return {
                'scorm_version': slide_dict['slide'].scorm_version,
                'type' : slide_dict['slide'].slide_type,
                'is_tincan' : slide_dict['slide'].is_tincan,
                'completed' : False
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

    @http.route('/slides/slide/set_completed_scorm', website=True, type="json", auth="public")
    def slide_set_completed_scorm(self, slide_id, completion_type):
        if request.website.is_public_user():
            return {'error': 'public_user'}
        fetch_res = self._fetch_slide(slide_id)
        slide = fetch_res['slide']
        if fetch_res.get('error'):
            return fetch_res
        if slide.website_published and slide.channel_id.is_member:
            slide.action_set_completed()
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

    @http.route('/slides/slide/<model("slide.slide"):slide>/set_completed', website=True, type="http", auth="user")
    def slide_set_completed_and_redirect(self, slide, next_slide_id=None):
        if slide.slide_type == 'scorm' and slide.is_tincan:
            scorm_datas = request.env['statement.scorm'].sudo().search([('activityId', '=', int(slide.id)),('user_id','=',request.uid)])
            state_datas = request.env['state.scorm'].sudo().search([('activityId','=',int(slide.id)),('user_id','=',request.uid)])
            if scorm_datas:
                if any('passed' in rec.verb_type for rec in scorm_datas):
                    self._set_completed_slide(slide)
                    next_slide = None
                    if next_slide_id:
                        next_slide = self._fetch_slide(next_slide_id).get('slide', None)
                    for rec in state_datas:
                        rec.error_scorm=''
                    return werkzeug.utils.redirect("/slides/slide/%s" % (slug(next_slide) if next_slide else slug(slide)))
                if any('failed' in rec.verb_type for rec in scorm_datas):
                    self._set_completed_slide(slide)
                    next_slide = None
                    if next_slide_id:
                        next_slide = self._fetch_slide(next_slide_id).get('slide', None)
                    for rec in state_datas:
                        rec.error_scorm=''
                    return werkzeug.utils.redirect("/slides/slide/%s" % (slug(next_slide) if next_slide else slug(slide)))
                else:
                    state_datas[-1].error_scorm = _("%s must be completed to the end to set it as done !" %slide.name)
                    return werkzeug.utils.redirect("/slides/slide/%s" % slug(slide))
        else:
            res = super(WebsiteSlidesScorm, self).slide_set_completed_and_redirect(slide,next_slide_id)
            return res

    @http.route('/slides/slide/quiz/submit', type="json", auth="public", website=True)
    def slide_quiz_submit(self, slide_id, answer_ids):
        slide = request.env['slide.slide'].sudo().search([('id','=',int(slide_id))])
        if slide.slide_type == 'scorm' and slide.is_tincan:
            scorm_datas = request.env['statement.scorm'].sudo().search([('activityId', '=', int(slide_id)),('user_id','=',request.uid)])
            state_datas = request.env['state.scorm'].sudo().search([('activityId','=',int(slide_id)),('user_id','=',request.uid)])
            if scorm_datas:
                if any('passed' in rec.verb_type for rec in scorm_datas):
                    for rec in state_datas:
                        rec.error_scorm=''
                if any('failed' in rec.verb_type for rec in scorm_datas):
                    self._set_completed_slide(slide)
                    for rec in state_datas:
                        rec.error_scorm=''
                else:
                    state_datas[-1].error_scorm = _("%s must be completed to the end to set it as done !" %slide.name)
        res = super(WebsiteSlidesScorm, self).slide_quiz_submit(slide_id, answer_ids)
        return res

    @http.route('/slides/slide/scorm_set_completed', website=True, type="json", auth="user")
    def state_scorm(self, slide_id):
        try:
            scorm_datas = request.env['statement.scorm'].sudo().search([('activityId', '=', int(slide_id)),('user_id','=',request.uid)])
            if scorm_datas:
                if request.website.is_public_user():
                    return {'error': 'public_user'}
                fetch_res = self._fetch_slide(slide_id)
                slide = fetch_res['slide']
                if fetch_res.get('error'):
                    return fetch_res
                if slide.website_published and slide.channel_id.is_member:
                    if any('passed' in rec.verb_type for rec in scorm_datas):
                        return {
                            'channel_completion': fetch_res['slide'].channel_id.completion,
                            'result_passed': True if any('passed' in rec.verb_type for rec in scorm_datas) else False,
                            'result_failed': True if any('failed' in rec.verb_type for rec in scorm_datas) else False,
                            'slide_id':slide_id
                        }
                    if any('failed' in rec.verb_type for rec in scorm_datas):
                         return {
                            'channel_completion': fetch_res['slide'].channel_id.completion,
                            'result_passed': True if any('passed' in rec.verb_type for rec in scorm_datas) else False,
                            'result_failed': True if any('failed' in rec.verb_type for rec in scorm_datas) else False,
                            'slide_id':slide_id
                        }
                    else:
                        return {
                            'channel_completion':fetch_res['slide'].channel_id.completion,
                            'result_passed': False ,
                            'result_failed': False ,
                            'slide_id':slide_id
                        }
            else:
                return {
                    'channel_completion': 0.0,
                    'result_passed': False,
                    'result_failed': False,
                    'slide_id':slide_id
                }
        except(SyntaxError) as e:
            return json.dumps(res = {
                                    "error": str(e)
            })
    
    @http.route(['/slides/channel/leave'], type='json', auth='user', website=True)
    def slide_channel_leave(self, channel_id):
        scorm_slide_ids = request.env['slide.slide'].sudo().search([('channel_id','=',int(channel_id))])
        for data in scorm_slide_ids:
            if data.slide_type == 'scorm':
                request.env['statement.scorm'].sudo().search([('activityId','=',int(data.id)),('user_id','=',request.uid)]).unlink()
                request.env['state.scorm'].sudo().search([('activityId','=',int(data.id)),('user_id','=',request.uid)]).unlink()
        res = super(WebsiteSlidesScorm, self).slide_channel_leave(channel_id)
        return res

    @http.route(['/slides/slide/activities/state'], type='http',website=True, auth='public',
                methods=['PUT'], csrf=False, cors='*')
    def set_state_scorm(self, **params):
        try:
            request_payload = request.httprequest.data.decode('utf-8')
            activityId = params.get('activityId')
            stateId = params.get('stateId')
            agent = params.get('agent')
            agent = json.loads(agent)
            user_name = request.env.user.name
            user_email = request.env.user.login
            objectType=agent.get('objectType')
            is_tincan=params.get('tincan')
            channel_rec = request.env['slide.slide'].sudo().search([('id', '=', int(activityId))], limit=1)
            if channel_rec:
                vals = ({
                    'activityId':activityId,
                    'state':stateId,
                    'state_id':activityId,
                    'user_id':request.uid,
                    'agent_name':user_name,
                    'agent_email':user_email,
                    'object_type':objectType,
                    'request_payload':request_payload
                })
                request.env['state.scorm'].sudo().create(vals)
        except(SyntaxError) as e:
            return json.dumps(res = {
                                    "error": str(e)
                                })
    
    @http.route(['/slides/slide/activities/state'], type='http', auth='public',
                methods=['GET'], csrf=False, cors='*')
    def get_state_scorm(self, **params):
        try:
            if params:
                activityId = params.get('activityId')
                channel_rec = request.env['state.scorm'].sudo().search([('activityId', '=', int(activityId)),('user_id','=',request.uid)])
                if channel_rec:
                    return channel_rec[-1].request_payload
            else:
                return {
                        'error': {
                            'status_code': '400',
                            'message': 'Data Not found'
                        }
                    }
        except(SyntaxError) as e:
            return json.dumps(res = {
                                    "error": str(e)
                                })

    @http.route(['/slides/slide/statements'], type='json', auth='public', methods=['PUT'], csrf=False, cors='*')
    def set_statement_scorm(self, **params):
        try:
            data = request.jsonrequest
            verb_type = data['verb']['display'].get('en-US')
            user_name = request.env.user.name
            user_email = request.env.user.login
            options = []
            correct_option_pattern = ''
            correct_option_patterns = []
            chosen_choices = []
            response = ''
            match_source_options = []
            scaled_score = ''
            min_score = ''
            max_score = ''
            score = ''
            check_success = ''
            if verb_type == 'answered':
                activityId = data['object'].get('id').partition('/')[0]
                object_name = data['object']['definition']['name'].get('und') if data['object']['definition']['name'].get('und') else ''
                interaction_type = data['object']['definition'].get('interactionType') if data['object']['definition'].get('interactionType') else ''
                # if interaction_type == 'numeric':
                # if interaction_type == 'likert':
                if interaction_type == 'choice':
                    if  'choices' in data['object']['definition']:
                        option = data['object']['definition']['choices']
                        option_dict = {sub['id'] : sub['description']['und'] for sub in option}
                        for k, vals in option_dict.items():
                            options.append(vals)
                    if 'correctResponsesPattern' in data['object']['definition']:
                        if '[,]' in data['object']['definition']['correctResponsesPattern'][0]:
                            correct_option_pattern_rec = list(data['object']['definition']['correctResponsesPattern'][0].split('[,]'))
                            for k in correct_option_pattern_rec:
                                if k in option_dict:
                                    correct_option_patterns.append(option_dict[k])
                        if '[,]' not in data['object']['definition']['correctResponsesPattern'][0]:
                            correct_option_pattern_id = data['object']['definition']['correctResponsesPattern'][0]
                            if correct_option_pattern_id in option_dict:
                                correct_option_pattern = option_dict[correct_option_pattern_id]
                    if '[,]' in data['result']['response']:
                        chosen_choices_id = list(data['result']['response'].split('[,]'))
                        for k in chosen_choices_id:
                            if k in option_dict:
                                chosen_choices.append(option_dict[k])
                    if '[,]' not in data['result']['response']:
                        response_id = data['result']['response']
                        if response_id in option_dict:
                                response = option_dict[response_id]
                if interaction_type == 'fill-in':
                    response = data['result']['response']  if 'result' in data else ''
                if interaction_type == 'matching':
                    if 'source' in data['object']['definition']:
                        sources = data['object']['definition']['source']
                        sources_dict = {sub['id'] : sub['description']['und'] for sub in sources}
                        for k, vals in sources_dict.items():
                            match_source_options.append(vals)
                    if 'target' in data['object']['definition']:
                        option = data['object']['definition']['target']
                        option_dict = {sub['id'] : sub['description']['und'] for sub in option}
                        for k, vals in option_dict.items():
                            options.append(vals)
                    if 'correctResponsesPattern' in data['object']['definition']:
                        if '[,]' in data['object']['definition']['correctResponsesPattern'][0]:
                            correct_option_pattern_rec = list(data['object']['definition']['correctResponsesPattern'][0].split('[,]'))
                            for i, j in enumerate(correct_option_pattern_rec):
                                correct_option_pattern_rec[i] = j.rsplit('[.]', 1)[1]
                            for k in correct_option_pattern_rec:
                                if k in option_dict:
                                    correct_option_patterns.append(option_dict[k])
                        if '[,]' not in data['object']['definition']['correctResponsesPattern'][0]:
                            correct_option_pattern_id = data['object']['definition']['correctResponsesPattern'][0]
                            if correct_option_pattern_id in option_dict:
                                correct_option_pattern = option_dict[correct_option_pattern_id]
                    if '[,]' in data['result']['response']:
                        chosen_choices_id = list(data['result']['response'].split('[,]'))
                        for i, j in enumerate(chosen_choices_id):
                            chosen_choices_id[i] = j.rsplit('[.]', 1)[1]
                        for k in chosen_choices_id:
                            if k in option_dict:
                                chosen_choices.append(option_dict[k])
                    if '[,]' not in data['result']['response']:
                        response_id = data['result']['response']
                        if response_id in option_dict:
                                response = option_dict[response_id]
                if interaction_type == 'sequencing':
                    if 'choices' in data['object']['definition']:
                        option = data['object']['definition']['choices']
                        option_dict = {sub['id'] : sub['description']['und'] for sub in option}
                        for k, vals in option_dict.items():
                            options.append(vals)
                    if 'correctResponsesPattern' in data['object']['definition']:
                        if '[,]' in data['object']['definition']['correctResponsesPattern'][0]:
                            correct_option_pattern_rec = list(data['object']['definition']['correctResponsesPattern'][0].split('[,]'))
                            for k in correct_option_pattern_rec:
                                if k in option_dict:
                                    correct_option_patterns.append(option_dict[k])
                        if '[,]' not in data['object']['definition']['correctResponsesPattern'][0]:
                            correct_option_pattern_id = data['object']['definition']['correctResponsesPattern'][0]
                            if correct_option_pattern_id in option_dict:
                                correct_option_pattern = option_dict[correct_option_pattern_id]
                    if '[,]' in data['result']['response']:
                        chosen_choices_id = list(data['result']['response'].split('[,]'))
                        for k in chosen_choices_id:
                            if k in option_dict:
                                chosen_choices.append(option_dict[k])
                    if '[,]' not in data['result']['response']:
                        response_id = data['result']['response']
                        if response_id in option_dict:
                                response = option_dict[response_id]
                if 'success' in data['result']:
                    check_success = data['result'].get('success')
                if 'score' in data['result']:
                    if 'raw' in data['result']['score']:
                        score = int(data['result']['score'].get('raw'))
                channel_rec = request.env['slide.slide'].sudo().search([('id', '=', int(activityId))], limit=1)
                if channel_rec:
                    vals = ({
                        'name' : channel_rec.name,
                        'activityId' : activityId,
                        'verb_type' : verb_type,
                        'user_name' : user_name,
                        'user_email' : user_email,
                        'object_name' : object_name,
                        'interaction_type' : interaction_type,
                        'correct_option_pattern_ids' : [(0, 0, {
                                                        'name': correct_option_patterns[index]
                                                        }) for index in range(len(correct_option_patterns))] if correct_option_patterns else [(0, 0, {'correct_option_pattern' : correct_option_pattern})] if correct_option_pattern else '',
                        'options_ids' : [(0, 0, {
                                        'name': options[index]
                                        })for index in range(len(options))],
                        'check_success' : check_success,
                        'score' : score,
                        'chosen_choice_ids' : [(0, 0, {
                                                'multiple_response': chosen_choices[index],
                                            }) for index in range(len(chosen_choices))] if chosen_choices else [(0, 0, {'response' : response})] if response else '',
                        'user_id' : request.env.user.id
                    })
                    request.env['statement.scorm'].sudo().create(vals)

            if (verb_type == 'attempted'):
                activityId = data['object'].get('id')
                object_name = data['object']['definition']['name'].get('und')
                interaction_type = data['object'].get('objectType')
                channel_rec = request.env['slide.slide'].sudo().search([('id', '=', int(activityId))], limit=1)
                if channel_rec:
                    vals = ({
                            'name':channel_rec.name,
                            'activityId':activityId,
                            'verb_type': verb_type,
                            'user_name': user_name,
                            'user_email': user_email,
                            'object_name':object_name,
                            'interaction_type':interaction_type,
                            'user_id' : request.env.user.id
                        })
                    request.env['statement.scorm'].sudo().create(vals)

            if (verb_type == 'experienced'):
                activityId = data['object'].get('id').partition('/')[0]
                object_name = data['object']['definition']['name'].get('und')
                interaction_type = data['object'].get('objectType')
                channel_rec = request.env['slide.slide'].sudo().search([('id', '=', int(activityId))], limit=1)
                if channel_rec:
                    vals = ({
                        'name':channel_rec.name,
                        'activityId':activityId,
                        'verb_type': verb_type,
                        'user_name': user_name,
                        'user_email': user_email,
                        'object_name':object_name,
                        'interaction_type':interaction_type,
                        'user_id' : request.env.user.id
                    })
                    request.env['statement.scorm'].sudo().create(vals)

            if (verb_type == 'completed'):
                activityId = data['object'].get('id').partition('/')[0]
            if (verb_type == 'passed'):
                if '/' in data['object']['id']:
                    activityId = data['object'].get('id').partition('/')[0]
                else:
                    activityId = data['object'].get('id')
                object_name = data['object']['definition']['name'].get('und')
                interaction_type = data['object'].get('objectType')
                completion = data['result']['completion'] if 'completion' in data['result'] else ''
                duration = data['result']['duration'] if 'duration' in data['result'] else ''
                check_success = data['result']['success'] if 'success' in ['result'] else ''
                if 'score' in data['result']:
                    scaled_score = float(data['result']['score'].get('scaled')) if 'scaled' in data['result']['score'] else None
                    min_score = int(data['result']['score'].get('min')) if 'min' in data['result']['score'] else None
                    max_score = int(data['result']['score'].get('max')) if 'max' in data['result']['score'] else None
                    score = int(data['result']['score'].get('raw')) if 'raw' in data['result']['score'] else None
                channel_rec = request.env['slide.slide'].sudo().search([('id', '=', int(activityId))], limit=1)
                if channel_rec:
                    vals = ({
                        'name':channel_rec.name,
                        'activityId':activityId,
                        'verb_type': verb_type,
                        'user_name': user_name,
                        'user_email': user_email,
                        'object_name':object_name,
                        'interaction_type':interaction_type,
                        'total_duration':duration,
                        'completion':completion,
                        'scaled_score': scaled_score,
                        'min_score':min_score,
                        'max_score':max_score,
                        'score':score,
                        'user_id' : request.env.user.id,
                    })
                    request.env['statement.scorm'].sudo().create(vals)

            if (verb_type == 'failed'):
                if '/' in data['object']['id']:
                    activityId = data['object'].get('id').partition('/')[0]
                else:
                    activityId = data['object'].get('id')
                object_name = data['object']['definition']['name'].get('und')
                interaction_type = data['object'].get('objectType')
                completion = data['result']['completion'] if 'completion' in data['result'] else ''
                duration = data['result']['duration'] if 'duration' in data['result'] else ''
                check_success = data['result']['success'] if 'success' in ['result'] else ''
                if 'score' in data['result']:
                    scaled_score = float(data['result']['score'].get('scaled')) if 'scaled' in data['result']['score'] else None
                    min_score = int(data['result']['score'].get('min')) if 'min' in data['result']['score'] else None
                    max_score = int(data['result']['score'].get('max')) if 'max' in data['result']['score'] else None
                    score = int(data['result']['score'].get('raw')) if 'raw' in data['result']['score'] else None
                channel_rec = request.env['slide.slide'].sudo().search([('id', '=', int(activityId))], limit=1)
                if channel_rec:
                    vals = ({
                        'name':channel_rec.name,
                        'activityId':activityId,
                        'verb_type': verb_type,
                        'user_name': user_name,
                        'user_email': user_email,
                        'object_name':object_name,
                        'interaction_type':interaction_type,
                        'total_duration':duration,
                        'completion':completion,
                        'scaled_score': scaled_score,
                        'min_score':min_score,
                        'max_score':max_score,
                        'score':score,
                        'user_id' : request.env.user.id
                    })
                    request.env['statement.scorm'].sudo().create(vals)
        except(SyntaxError) as e:
            return json.dumps(res = {
                                    "error": str(e)
                                })