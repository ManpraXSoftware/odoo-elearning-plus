# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
import os
import base64
import zipfile
import tempfile
import shutil
from werkzeug import urls
from odoo.http import request
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from odoo.addons.http_routing.models.ir_http import url_for


class Channel(models.Model):
    """ A channel is a container of slides. """
    _inherit = 'slide.channel'

    nbr_scorm = fields.Integer("Number of Scorms", compute="_compute_slides_statistics", store=True)


class Slide(models.Model):
    _inherit = 'slide.slide'

    slide_type = fields.Selection(
        selection_add=[('scorm', 'Scorm')], ondelete={'scorm': 'set default'})
    scorm_data = fields.Many2many('ir.attachment')
    nbr_scorm = fields.Integer("Number of Scorms", compute="_compute_slides_statistics", store=True)
    filename = fields.Char()
    embed_code = fields.Text('Embed Code', readonly=True, compute='_compute_embed_code')

    @api.onchange('scorm_data')
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
                folder_dir = self.filename.split('media')[-1].split('/')[1]
                path = os.path.join(os.path.dirname(os.path.abspath(__file__)))
                target_dir = '/'.join(p for p in path.split('/')[:len(path.split('/')) - 1]) + '/static/media/' + folder_dir
                if os.path.isdir(target_dir):
                    shutil.rmtree(target_dir)

    @api.depends('document_id', 'slide_type', 'mime_type')
    def _compute_embed_code(self):
        for rec in self:
            if rec.slide_type == 'scorm' and rec.scorm_data:
                rec.embed_code = "<iframe src='%s' allowFullScreen='true' frameborder='0'></iframe>" % (rec.filename)
            else:
                res = super(Slide, rec)._compute_embed_code()
                return res

    def read_files_from_zip(self):
        file_full_path = self.env['ir.attachment']._full_path(self.scorm_data.store_fname)
        file = base64.decodebytes(self.scorm_data.datas)
        fobj = tempfile.NamedTemporaryFile(delete=False)
        fname = fobj.name
        fobj.write(file)
        fobj.close()
        zipzip = self.scorm_data.datas
        f = open(fname, 'r+b')
        f.write(base64.b64decode(zipzip))
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)))
        with zipfile.ZipFile(file_full_path, 'r') as zipObj:
            listOfFileNames = zipObj.namelist()
            html_file_name = ''
            package_name = ''
            flag = False
            for fileName in listOfFileNames:
                filename = fileName.split('/')
                if 'meta.xml' in listOfFileNames: #Normal Structure
                    if not package_name:
                        flag = True
                        package_name = self.scorm_data.name.split('.')[0]
                if 'index.html' in filename:
                    html_file_name = '/'.join(filename)
                    break
                if 'story.html' in filename:
                    html_file_name = '/'.join(filename)
                    break
                if not package_name: #Nested Structure
                    package_name = filename[0]
            source_dir = '/'.join(p for p in path.split('/')[:len(path.split('/')) - 1]) + '/static/media/'
            if flag:
                source_dir += str(package_name)
            zipObj.extractall(source_dir)
            self.filename = '/website_scorm_elearning/static/media/%s' % (str(package_name) + '/' if flag else '') + html_file_name
        f.close()
