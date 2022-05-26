# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
import os
import base64
import zipfile
import tempfile
import shutil
import urllib.parse
import json
from datetime import datetime
import werkzeug
from werkzeug import urls
from odoo.http import request
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError
from odoo.addons.http_routing.models.ir_http import url_for
from odoo.addons import website_slides
from odoo.addons.http_routing.models.ir_http import slug
from odoo.tools.translate import encode


class SlidePartnerRelation(models.Model):
    _inherit = 'slide.slide.partner'

    lms_session_info_ids = fields.One2many('lms.session.info', 'slide_partner_id', 'LMS Session Info')
    lms_scorm_karma = fields.Integer("Scorm Karma")

class LmsSessionInfo(models.Model):
    _name = 'lms.session.info'

    name = fields.Char("Name")
    value = fields.Char("Value")
    slide_partner_id = fields.Many2one('slide.slide.partner')


class Channel(models.Model):
    """ A channel is a container of slides. """
    _inherit = 'slide.channel'

    nbr_scorm = fields.Integer("Number of Scorms", compute="_compute_slides_statistics", store=True)

    @api.depends('slide_ids.slide_type', 'slide_ids.is_published', 'slide_ids.completion_time',
                 'slide_ids.likes', 'slide_ids.dislikes', 'slide_ids.total_views', 'slide_ids.is_category', 'slide_ids.active')
    def _compute_slides_statistics(self):
        super(Channel, self)._compute_slides_statistics()


class StateScorm(models.Model):
    _name = 'state.scorm'

    state = fields.Char("State")
    user_id = fields.Integer("User ID")
    state_id = fields.Many2one('slide.slide', ondelete = "cascade")
    activityId = fields.Char("Activity ID")
    agent_name = fields.Char("User Name")
    agent_email = fields.Char("User Email")
    request_payload = fields.Char("Request Payload")
    object_type = fields.Char("Object Type")
    error_scorm = fields.Char("Error")
    start_duration = fields.Datetime("Start Time")
    end_duration = fields.Datetime("End Time")
    completion_duration = fields.Char("Completion Time")


class StatementScorm(models.Model):
    _name = 'statement.scorm'

    name = fields.Char("Name")
    statement_id = fields.Many2one('slide.slide', ondelete = "cascade")
    activityId = fields.Char("Scorm ID")
    user_name = fields.Char("User Name")
    user_email = fields.Char("User Email")
    verb_type = fields.Char("Verb")
    object_name = fields.Char("Object Name")
    interaction_type = fields.Char("Interaction Type")
    check_success = fields.Boolean("Success")
    score = fields.Integer("Score")
    chosen_choice_ids = fields.One2many('response.choice','chosen_option_id')
    correct_option_pattern_ids = fields.One2many('option.pattern','correct_option_id')
    options_ids = fields.One2many('assesment.option','assesment_option_id',"Options")
    completion = fields.Char("Completion")
    min_score = fields.Integer("Min Score")
    max_score = fields.Integer("Max Score")
    scaled_score = fields.Float("Scaled Score")
    total_duration = fields.Char("Completion Time")
    check_verb = fields.Boolean('Check Verb')
    user_id = fields.Integer("User ID")

class chosenOptions(models.Model):
    _name = 'response.choice'

    multiple_response = fields.Char("Chosen Response")
    response = fields.Char("Chosen Choice")
    chosen_option_id = fields.Many2one('statement.scorm', ondelete = "cascade")

class correctOptionPatterns(models.Model):
    _name = 'option.pattern'

    name = fields.Char("Correct Response")
    correct_option_pattern = fields.Char("Correct Option Pattern")
    correct_option_id = fields.Many2one('statement.scorm', ondelete = "cascade")


class ScormAssesOptions(models.Model):
    _name = 'assesment.option'

    name = fields.Char("Option Name")
    assesment_option_id = fields.Many2one('statement.scorm', ondelete = "cascade")


class Slide(models.Model):
    _inherit = 'slide.slide'

    slide_type = fields.Selection(
        selection_add=[('scorm', 'Scorm')], ondelete={'scorm': 'set default'})
    scorm_data = fields.Many2many('ir.attachment')
    nbr_scorm = fields.Integer("Number of Scorms", compute="_compute_slides_statistics", store=True)
    filename = fields.Char()
    embed_code = fields.Text('Embed Code', readonly=True, compute='_compute_embed_code')
    scorm_version = fields.Selection([
        ('scorm11', 'Scorm 1.1/1.2'),
        ('scorm2004', 'Scorm 2004 Edition')
    ], default="scorm11")
    tincan_version = fields.Selection([
        ('scorm11', 'Scorm 1.1/1.2'),
        ('scorm2004', 'Scorm 2004 Edition')
    ], default="scorm11")
    is_tincan = fields.Boolean(string="Is Tincan")
    scorm_passed_xp = fields.Integer("Scorm Passed Xp")
    scorm_completed_xp = fields.Integer("Scorm Completed Xp")
    state_scorm_ids = fields.One2many('state.scorm','state_id',"Scorm State Data")
    statement_scorm_ids = fields.One2many('statement.scorm','statement_id',"Scorm Statement Data")

    @api.depends('slide_ids.sequence', 'slide_ids.slide_type', 'slide_ids.is_published', 'slide_ids.is_category')
    def _compute_slides_statistics(self):
        super(Slide, self)._compute_slides_statistics()

    def action_set_completed(self):
        for slide in self:
            if slide.slide_type == 'scorm' and slide.is_tincan and slide.channel_id.is_member:
                scorm_datas = self.env['statement.scorm'].sudo().search([('activityId', '=', int(slide.id)),('user_id','=',request.env.user.id)])
                state_rec =  self.env['state.scorm'].sudo().search([('activityId', '=', int(slide.id)),('user_id','=',request.env.user.id)])
                if any('passed' in rec.verb_type for rec in scorm_datas):
                    result_rec = self.env['statement.scorm'].sudo().search([('activityId', '=', int(slide.id)),('user_id','=',request.env.user.id),('verb_type','=','passed')])
                    state_rec[-1].end_duration=result_rec[-1].create_date
                if any('failed' in rec.verb_type for rec in scorm_datas):
                    result_rec = self.env['statement.scorm'].sudo().search([('activityId', '=', int(slide.id)),('user_id','=',request.env.user.id),('verb_type','=','failed')])
                    state_rec[-1].end_duration=result_rec[-1].create_date
                for rec in scorm_datas:
                    if rec.verb_type in ['passed', 'failed'] and rec.completion:
                        attempt_rec = self.env['statement.scorm'].sudo().search([('activityId', '=', int(slide.id)),('user_id','=',request.env.user.id),('verb_type','=','attempted')])
                        state_rec[-1].start_duration=attempt_rec[0].create_date
                        elapsed_time = datetime.strptime(state_rec[-1].end_duration.strftime("%Y-%m-%d %H:%M:%S"), "%Y-%m-%d  %H:%M:%S") - datetime.strptime(state_rec[-1].start_duration.strftime("%Y-%m-%d %H:%M:%S"), "%Y-%m-%d  %H:%M:%S")
                        duration_in_s = elapsed_time.total_seconds()
                        days    = divmod(duration_in_s, 86400)
                        hours   = divmod(days[1], 3600)
                        minutes = divmod(hours[1], 60)
                        seconds = divmod(minutes[1], 1)
                        state_rec[-1].completion_duration =  "%d days, %d hours, %d minutes and %d seconds" % (days[0], hours[0], minutes[0], seconds[0])
                if scorm_datas:
                    if any('passed' in rec.verb_type for rec in scorm_datas):
                        slide._action_set_completed(self.env.user.partner_id)
                    if any('failed' in rec.verb_type for rec in scorm_datas):
                         slide._action_set_completed(self.env.user.partner_id)
                    else:
                        return {'error':'slide_scorm_incomplete'}
                else:
                    return request.redirect('/slides/slide/%s' % slug(slide))
            else:
                res = super(Slide, self).action_set_completed()
                return res
    def _compute_quiz_info(self, target_partner, quiz_done=False):
        res = super(Slide, self)._compute_quiz_info(target_partner)
        for slide in self:
            slide_partner_id = self.env['slide.slide.partner'].sudo().search([
                ('slide_id', '=', slide.id),
                ('partner_id', '=', target_partner.id)
            ], limit=1)
            if res[slide.id].get('quiz_karma_won'):
                res[slide.id]['quiz_karma_won'] += slide_partner_id.lms_scorm_karma
            else:
                res[slide.id]['quiz_karma_won'] = slide_partner_id.lms_scorm_karma
        return res

    @api.onchange('scorm_data','name')
    def _on_change_scorm_data(self):
        if self.scorm_data:
            if len(self.scorm_data) > 1:
                raise ValidationError(_("Only one scorm package allowed per slide."))
            tmp = self.scorm_data.name.split('.')
            ext = tmp[len(tmp) - 1]
            if ext != 'zip':
                raise ValidationError(_("The file must be a zip file.!!"))
            self.read_files_from_zip()
        else:
            if self.filename:
                folder_dir = self.filename.split('scorm')[-1].split('/')[1]
                path = os.path.join(os.path.dirname(os.path.abspath(__file__)))
                path = path.replace('\\', '/')
                target_dir = '/'.join(p for p in path.split('/')[:len(path.split('/')) - 1]) + '/static/media/scorm/' + self.name + '/' + folder_dir
                if os.path.isdir(target_dir):
                    shutil.rmtree(target_dir)

    @api.depends('document_id', 'slide_type', 'mime_type')
    def _compute_embed_code(self):
        for rec in self:
            if rec.slide_type == 'scorm' and rec.scorm_data:
                user_name = self.env.user.name
                user_mail = self.env.user.login
                end_point = self.env['ir.config_parameter'].get_param('web.base.url') + '/slides/slide'
                end_point = urllib.parse.quote(end_point, safe=" ")
                actor = "{'name': [%s], mbox: ['mailto':%s]}" % (user_name,user_mail)
                actor = json.dumps(actor)
                actor = urllib.parse.quote(actor)
                rec.embed_code = "<iframe src='%s?endpoint=%s&actor=%s&activity_id=%s' allowFullScreen='true' frameborder='0'></iframe>" % (rec.filename,end_point,actor,rec.id)
            else:
                res = super(Slide, rec)._compute_embed_code()
                return res

    def read_files_from_zip(self):
        file = base64.decodebytes(self.scorm_data.datas)
        fobj = tempfile.NamedTemporaryFile(delete=False)
        fname = fobj.name
        fobj.write(file)
        zipzip = self.scorm_data.datas
        f = open(fname, 'r+b')
        f.write(base64.b64decode(zipzip))
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)))
        path = path.replace('\\', '/')
        with zipfile.ZipFile(fobj, 'r') as zipObj:
            listOfFileNames = zipObj.namelist()
            html_file_name = ''
            package_name = self.name
            # tincan_file = list(filter(lambda x: 'tincan.xml' in x, listOfFileNames))
            # if tincan_file:
            #     self.is_tincan = True
            html_file_name = list(filter(lambda x: 'index.html' in x, listOfFileNames))
            if not html_file_name:
                html_file_name = list(filter(lambda x: 'index_lms.html' in x, listOfFileNames))
                if not html_file_name:
                    html_file_name = list(filter(lambda x: 'story.html' in x, listOfFileNames))
            # for fileName in sorted(listOfFileNames):
            #     filename = fileName.split('/')
            #     package_name = self.scorm_data.name.split('.')[0]
            #     if 'index.html' in filename:
            #         html_file_name = '/'.join(filename)
            #         break
            #     elif 'index_lms.html' in filename:
            #         html_file_name = '/'.join(filename)
            #         break
            #     elif 'story.html' in filename:
            #         html_file_name = '/'.join(filename)
            #         break
            source_dir = '/'.join(p for p in path.split('/')[:len(path.split('/')) - 1]) + '/static/media/scorm/' + str(package_name)
            zipObj.extractall(source_dir)
            self.filename = '/website_scorm_elearning/static/media/scorm/%s/%s' % (str(package_name), html_file_name[0] if len(html_file_name) > 0 else None)
        f.close()
