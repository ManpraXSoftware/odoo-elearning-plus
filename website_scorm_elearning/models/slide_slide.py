# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
import os
import json
import base64
import zipfile
import urllib.parse
from io import BytesIO
import logging
_logger = logging.getLogger(__name__)
import xml.etree.ElementTree as ET
from odoo.http import request
from markupsafe import Markup
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from urllib.parse import quote


class IrAttachment(models.Model):
    _inherit = 'ir.attachment'

    scorm_relpath = fields.Char(index=True, help="Relative path of this file inside its SCORM package.")


class SlidePartnerRelation(models.Model):
    _inherit = 'slide.slide.partner'

    lms_session_info_ids = fields.One2many('lms.session.info', 'slide_partner_id', 'LMS Session Info')
    lms_scorm_karma = fields.Integer("Scorm Karma")


class LmsSessionInfo(models.Model):
    _name = 'lms.session.info'
    _description = 'Lms Session Info'

    name = fields.Char("Name")
    value = fields.Char("Value")
    slide_partner_id = fields.Many2one('slide.slide.partner')


class Channel(models.Model):
    """ A channel is a container of slides. """
    _inherit = 'slide.channel'

    nbr_scorm = fields.Integer("Number of Scorms", compute="_compute_slides_statistics", store=True)

    @api.depends('slide_ids.slide_category', 'slide_ids.is_published', 'slide_ids.completion_time',
                 'slide_ids.likes', 'slide_ids.dislikes', 'slide_ids.total_views', 'slide_ids.is_category', 'slide_ids.active')
    def _compute_slides_statistics(self):
        super(Channel, self)._compute_slides_statistics()


class Slide(models.Model):
    _inherit = 'slide.slide'

    slide_category = fields.Selection(
        selection_add=[('scorm', 'Scorm')], ondelete={'scorm': 'set default'})
    slide_type = fields.Selection(
        selection_add=[('scorm', 'Scorm')], ondelete={'scorm': 'set null'}, compute="_compute_slide_type", store=True)
    scorm_data = fields.Many2many('ir.attachment')
    nbr_scorm = fields.Integer("Number of Scorms", compute="_compute_slides_statistics", store=True)
    filename = fields.Char()
    embed_code = fields.Html('Embed Code', readonly=True, compute='_compute_embed_code')
    embed_code_external = fields.Html('External Embed Code', readonly=True, compute='_compute_embed_code')
    scorm_version = fields.Selection([
        ('scorm11', 'Scorm 1.1/1.2'),
        ('scorm2004', 'Scorm 2004 Edition')
    ], default="scorm11")
    scorm_passed_xp = fields.Integer("Scorm Passed Xp")
    scorm_completed_xp = fields.Integer("Scorm Completed Xp")
    scorm_completion_on_finish = fields.Boolean("Scorm Completion on Finish")
    manifest_file = fields.Char()

    @api.onchange('scorm_version')
    def onchange_scorm_version(self):
        if self.manifest_file:
            res = {}
            scorm_version = self.extract_scorm_version(self.manifest_file)
            if scorm_version != self.scorm_version:
                res['warning'] = {
                    'title': _('Warning'),
                    'message': _('The scorm version is different from actual scorm verison. Results may vary if you select wrong scorm version.')
                }
                return res

    @api.depends('slide_ids.sequence', 'slide_ids.slide_category', 'slide_ids.is_published', 'slide_ids.is_category')
    def _compute_slides_statistics(self):
        super(Slide, self)._compute_slides_statistics()

    @api.depends('slide_category', 'question_ids', 'channel_id.is_member')
    @api.depends_context('uid')
    def _compute_mark_complete_actions(self):
        super(Slide, self)._compute_mark_complete_actions()

    @api.depends('slide_category', 'source_type', 'video_source_type')
    def _compute_slide_type(self):
        res = super(Slide, self)._compute_slide_type()
        for slide in self:
            if slide.slide_category == 'scorm':
                slide.slide_type = 'scorm'
        return res
                
    @api.depends('slide_type')
    def _compute_slide_icon_class(self):
        slide = self.filtered(lambda slide: slide.slide_type == 'scorm')
        slide.slide_icon_class = 'fa-file-archive-o'
        super(Slide, self - slide)._compute_slide_icon_class()

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

    @api.model_create_multi
    def create(self, vals_list):
        slides = super().create(vals_list)
        for slide in slides:
            if slide.slide_category == 'scorm' and slide.scorm_data:
                slide._process_scorm_upload()
        return slides

    def write(self, vals):
        res = super().write(vals)
        if 'scorm_data' in vals:
            for slide in self:
                if slide.slide_category != 'scorm':
                    continue
                if slide.scorm_data:
                    slide._process_scorm_upload()
                else:
                    slide._clear_scorm_files()
        return res

    def unlink(self):
        scorm_attachments = self.env['ir.attachment'].sudo().search([
            ('res_model', '=', 'slide.slide'),
            ('res_id', 'in', self.ids),
            ('scorm_relpath', '!=', False),
        ])
        res = super().unlink()
        scorm_attachments.unlink()
        return res

    def copy(self, default=None):
        """ The extracted SCORM files are linked to this slide's own id, so a
        plain field copy would leave the duplicate's filename pointing at the
        original slide's files. Duplicate the attachments too and repoint. """
        new_slides = self.browse()
        for slide in self:
            new_slide = super(Slide, slide).copy(default=default)
            if slide.slide_category == 'scorm' and slide.filename:
                attachments = self.env['ir.attachment'].sudo().search([
                    ('res_model', '=', 'slide.slide'),
                    ('res_id', '=', slide.id),
                    ('scorm_relpath', '!=', False),
                ])
                for attachment in attachments:
                    attachment.copy({'res_id': new_slide.id})
                new_slide.filename = slide.filename.replace(
                    f'/slide/{slide.id}/scorm/', f'/slide/{new_slide.id}/scorm/', 1)
            new_slides |= new_slide
        return new_slides

    def _process_scorm_upload(self):
        self.ensure_one()
        if len(self.scorm_data) > 1:
            raise ValidationError(_("Only one scorm package allowed per slide."))
        name = self.scorm_data.name or ''
        ext = name.rsplit('.', 1)[-1] if '.' in name else ''
        if ext.lower() != 'zip':
            raise ValidationError(_("The file must be a zip file.!!"))
        self.read_files_from_zip()

    def _clear_scorm_files(self):
        self.ensure_one()
        self.env['ir.attachment'].sudo().search([
            ('res_model', '=', 'slide.slide'),
            ('res_id', '=', self.id),
            ('scorm_relpath', '!=', False),
        ]).unlink()
        self.filename = False
        self.manifest_file = False

    @api.constrains('slide_category', 'filename')
    def _check_scorm_filename(self):
        for slide in self:
            if slide.slide_category == 'scorm' and not slide.filename:
                raise ValidationError(_("Please upload a SCORM package for this slide."))

    @api.depends('slide_category', 'google_drive_id', 'video_source_type', 'youtube_id')
    def _compute_embed_code(self):
            for rec in self:
                super(Slide, rec)._compute_embed_code()
                try:
                    if rec.slide_category == 'scorm' and rec.scorm_data and not rec.is_tincan:
                        rec.embed_code = Markup('<iframe src="%s" frameborder="0"  aria-label="%s"></iframe>') % (rec.filename, _('Scorm'))
                        rec.embed_code_external = Markup('<iframe src="%s" frameborder="0"  aria-label="%s"></iframe>') % (rec.filename, _('Scorm'))
                    elif rec.slide_category == 'scorm' and rec.scorm_data and rec.is_tincan:
                        user_name = self.env.user.id
                        user_mail = self.env.user.login
                        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
                        end_point = f"{base_url}/slides/slide"
                        encoded_endpoint = urllib.parse.quote(end_point, safe=":/?&=")
                        actor_data = {
                            "name": [user_name],
                            "mbox": [f"mailto:{user_mail}"]
                        }
                        actor_json = json.dumps(actor_data)  # Convert to JSON string
                        encoded_actor = urllib.parse.quote(actor_json)  # URL encode the JSON string
                        iframe_template = (
                            '<iframe src="{}?endpoint={}&actor={}&activity_id={}" '
                            'allowFullScreen="true" frameborder="0"></iframe>'
                        )
                        rec.embed_code = Markup(iframe_template.format(
                            rec.filename, encoded_endpoint, encoded_actor, rec.id
                        ))
                        rec.embed_code_external = Markup(iframe_template.format(
                            rec.filename, encoded_endpoint, encoded_actor, rec.id
                        ))
                except Exception as e:
                    if rec.slide_category  == 'scorm' and rec.scorm_data:
                        rec.embed_code = Markup('<iframe src="%s" frameborder="0" autoplay="1"></iframe>') % (rec.filename)
                        rec.embed_code_external = Markup('<iframe src="%s" aria-label="%s"></iframe>') % (rec.filename, _('Scorm'))

    def _scorm_resolve_launch_href(self, manifest_root, strip_namespace):
        """ Resolve the href of the SCO a compliant SCORM player must launch:
        the manifest's default <organization>'s first visible <item> that
        points (directly, or through nested items) at a <resource href>. """
        resources_by_id = {}
        for res in manifest_root.iter():
            if strip_namespace(res.tag) == 'resource':
                res_id, href = res.attrib.get('identifier'), res.attrib.get('href')
                if res_id and href:
                    resources_by_id[res_id] = href

        organizations = next(
            (el for el in manifest_root.iter() if strip_namespace(el.tag) == 'organizations'), None)
        if organizations is None:
            return None

        orgs = [el for el in organizations if strip_namespace(el.tag) == 'organization']
        default_org_id = organizations.attrib.get('default')
        organization = next((o for o in orgs if o.attrib.get('identifier') == default_org_id), None) \
            or (orgs[0] if orgs else None)
        if organization is None:
            return None

        def first_identifierref(el):
            for child in el:
                if strip_namespace(child.tag) != 'item':
                    continue
                if child.attrib.get('isvisible', 'true').lower() == 'false':
                    continue
                ref = child.attrib.get('identifierref')
                if ref and ref in resources_by_id:
                    return ref
                nested = first_identifierref(child)
                if nested:
                    return nested
            return None

        resource_id = first_identifierref(organization)
        return resources_by_id.get(resource_id) if resource_id else None

    def read_files_from_zip(self):
        self.ensure_one()

        # drop any files left over from a previous package on this slide
        self.env['ir.attachment'].sudo().search([
            ('res_model', '=', 'slide.slide'),
            ('res_id', '=', self.id),
            ('scorm_relpath', '!=', False),
        ]).unlink()

        zip_content = base64.decodebytes(self.scorm_data.datas)
        html_file_name = None
        manifest_relpath = None
        is_tincan = getattr(self, 'is_tincan', None)

        def find_case_insensitive(name, file_list):
            return next((f for f in file_list if f.lower() == name.lower()), None)

        def find_with_alt_extensions(base_name, ext, file_list):
            alt_ext = '.html' if ext == '.htm' else '.htm'
            alt_name = base_name + alt_ext
            return find_case_insensitive(alt_name, file_list)

        def strip_namespace(tag):
            return tag.split('}')[-1] if '}' in tag else tag

        with zipfile.ZipFile(BytesIO(zip_content)) as zip_obj:
            members = [info for info in zip_obj.infolist() if not info.is_dir()]
            list_of_file_names = [member.filename for member in members]

            manifest_matches = [x for x in list_of_file_names if x.lower().endswith("imsmanifest.xml")]
            if manifest_matches:
                manifest_relpath = manifest_matches[0]

            # 1) Follow the actual SCORM resolution order: the manifest's
            # default <organization>'s first visible <item identifierref>,
            # matched to its <resource href>. This is the file the SCORM
            # spec says a player must launch, and the only way to pick the
            # right SCO out of a multi-resource/multi-SCO package.
            if manifest_relpath:
                try:
                    manifest_root = ET.fromstring(zip_obj.read(manifest_relpath))
                except ET.ParseError:
                    manifest_root = None
                if manifest_root is not None:
                    href = self._scorm_resolve_launch_href(manifest_root, strip_namespace)
                    if href:
                        base, ext = os.path.splitext(href)
                        html_file_name = (
                            href if href in list_of_file_names else
                            find_case_insensitive(href, list_of_file_names) or
                            find_with_alt_extensions(base, ext.lower(), list_of_file_names)
                        )

            # 2) Non-standard/malformed manifest: scan the manifest only
            # (not every .xml in the zip, which can false-match on unrelated
            # files) for any sco/asset resource, or a <launch> hint.
            if not html_file_name and manifest_relpath and manifest_root is not None:
                for res in manifest_root.iter():
                    if strip_namespace(res.tag) == 'resource':
                        scorm_type = next(
                            (v for k, v in res.attrib.items() if k.lower().endswith('scormtype')),
                            None
                        )
                        href = res.attrib.get('href')
                        if scorm_type and href:
                            base, ext = os.path.splitext(href)
                            html_file_name = (
                                href if href in list_of_file_names else
                                find_case_insensitive(href, list_of_file_names) or
                                find_with_alt_extensions(base, ext.lower(), list_of_file_names)
                            )
                            if html_file_name:
                                break
                if not html_file_name:
                    launch = manifest_root.find('.//launch')
                    if launch is not None:
                        if launch.text:
                            html_file_name = launch.text.strip()
                        elif launch.find('location') is not None:
                            html_file_name = launch.find('location').text.strip()

            # 3) No usable manifest at all: guess from well-known filenames,
            # preferring an exact basename match over a loose substring one.
            if not html_file_name:
                candidates = ['story.html', 'index.html'] if is_tincan is False or is_tincan is None \
                    else ['index_lms.html', 'story.html', 'index.html']
                for candidate in candidates:
                    match = next((f for f in list_of_file_names if os.path.basename(f).lower() == candidate), None) \
                        or next((f for f in list_of_file_names if candidate in f.lower()), None)
                    if match:
                        html_file_name = match
                        break

            if not html_file_name:
                raise UserError(_("Could not find a launch file (e.g. index.html, story.html) in this SCORM package. Try another package."))

            # No explicit mimetype: ir.attachment.create() already guesses it
            # from the filename, and - crucially - falls back to sniffing the
            # actual file content whenever that guess is empty/generic, which
            # is more reliable than a filename-only guess of our own.
            attachment_vals = [{
                'name': os.path.basename(member.filename) or member.filename,
                'res_model': 'slide.slide',
                'res_id': self.id,
                'scorm_relpath': member.filename,
                'raw': zip_obj.read(member.filename),
            } for member in members]
            self.env['ir.attachment'].sudo().create(attachment_vals)

        self.filename = f'/slide/{self.id}/scorm/{quote(html_file_name, safe="/()")}'
        if manifest_relpath:
            self.manifest_file = manifest_relpath
            self.scorm_version = self.extract_scorm_version(manifest_relpath)

    def extract_scorm_version(self, manifest_relpath):
        attachment = self.env['ir.attachment'].sudo().search([
            ('res_model', '=', 'slide.slide'),
            ('res_id', '=', self._origin.id),
            ('scorm_relpath', '=', manifest_relpath),
        ], limit=1)
        if not attachment:
            return 'scorm2004'
        root = ET.fromstring(attachment.raw)
        # Namespace-agnostic: SCORM 1.2 and 2004 manifests declare different
        # imscp namespaces (or none at all, depending on the authoring tool),
        # so matching a hardcoded namespace URI silently misses most packages.
        schema_version_element = next(
            (el for el in root.iter() if el.tag.rsplit('}', 1)[-1] == 'schemaversion'), None)
        version_text = (schema_version_element.text or '').strip() if schema_version_element is not None else ''
        return 'scorm11' if version_text.startswith('1.2') else 'scorm2004'
