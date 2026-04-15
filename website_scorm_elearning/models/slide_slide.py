# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
import os
import json
import base64
import zipfile
import tempfile
import shutil
import urllib.parse
import boto3
from io import BytesIO
import logging
_logger = logging.getLogger(__name__)
from werkzeug import urls
from mimetypes import guess_type
import xml.etree.ElementTree as ET
from odoo.http import request
from markupsafe import Markup
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from urllib.parse import quote


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
    is_amazon_s3 = fields.Boolean(
        string="Scorm upload on Amazon S3",
        help="Indicates whether the slide file is hosted on Amazon S3"
    )
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

    @api.onchange('is_amazon_s3')
    def _onchange_is_amazon_s3(self):
        amazon_access_key = self.env['ir.config_parameter'].sudo().get_param('amazon_s3_connector.amazon_access_key')
        amazon_secret_key = self.env['ir.config_parameter'].sudo().get_param('amazon_s3_connector.amazon_secret_key')
        bucket_name = self.env['ir.config_parameter'].sudo().get_param('amazon_s3_connector.amazon_bucket_name')
        if self.is_amazon_s3:
            if not amazon_access_key or not amazon_secret_key or not bucket_name:
                self.scorm_data = False
                raise UserError("Amazon S3 credentials or bucket name are not configured.")
            else:
                pass
        else:
            pass

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)

        for rec in records:
            if rec.scorm_data:
                rec.read_files_from_zip()

        return records

    @api.onchange('scorm_version')
    def onchange_scorm_version(self):
        if self.manifest_file:
            scorm_version = self.extract_scorm_version(self.manifest_file)

            if scorm_version != self.scorm_version:
                previous_version = self._origin.scorm_version  # previous saved value
                self.scorm_version = previous_version  # revert value

                return {
                    'warning': {
                        'title': _('Warning'),
                        'message': _(
                            'The scorm version is different from actual scorm version. Results may vary if you select wrong scorm version.')
                    }
                }

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

    @api.onchange('scorm_data')
    def _on_change_scorm_data(self):
        if self.scorm_data:
            if len(self.scorm_data) > 1:
                raise ValidationError(_("Only one scorm package allowed per slide."))
            tmp = self.scorm_data.name.split('.')
            ext = tmp[len(tmp) - 1]
            if ext != 'zip':
                raise ValidationError(_("The file must be a zip file.!!"))
            if self.is_amazon_s3:
                # preferred_file = "index_lms.html" if self.is_tincan else "story.html"
                self.filename = self._upload_to_s3(self.scorm_data)
            else:
                self.read_files_from_zip()
        else:
            if self.filename:
                folder_dir = self.filename.split('scorm')[-1].split('/')[-2]
                path = os.path.join(os.path.dirname(os.path.abspath(__file__)))
                target_dir = os.path.join(os.path.split(path)[-2],"static","media","scorm",str(self.id),folder_dir)
                if os.path.isdir(target_dir):
                    shutil.rmtree(target_dir)


    def _upload_to_s3(self, scorm_data):

        amazon_access_key = self.env['ir.config_parameter'].sudo().get_param('amazon_s3_connector.amazon_access_key')
        amazon_secret_key = self.env['ir.config_parameter'].sudo().get_param('amazon_s3_connector.amazon_secret_key')
        bucket_name = self.env['ir.config_parameter'].sudo().get_param('amazon_s3_connector.amazon_bucket_name')

        if not amazon_access_key or not amazon_secret_key or not bucket_name:
            raise UserError("Amazon S3 credentials or bucket name are not configured.")

        def find_case_insensitive(name, file_list):
            return next((f for f in file_list if f.lower() == name.lower()), None)

        def find_with_alt_extensions(base, ext, file_list):
            alt_ext = '.html' if ext == '.htm' else '.htm'
            alt_name = base + alt_ext
            return find_case_insensitive(alt_name, file_list)

        def strip_namespace(tag):
            return tag.split('}')[-1] if '}' in tag else tag

        try:

            s3 = boto3.client(
                's3',
                aws_access_key_id=amazon_access_key,
                aws_secret_access_key=amazon_secret_key
            )

            zip_content = base64.b64decode(scorm_data.datas)

            base_name = os.path.splitext(scorm_data.name)[0]
            channel_id = self.channel_id.id
            file_prefix = f"{base_name}_Scorm_{channel_id}"

            selected_file = None
            scorm_version = None

            with tempfile.TemporaryDirectory() as temp_dir:

                zip_file_path = os.path.join(temp_dir, scorm_data.name)

                with open(zip_file_path, "wb") as f:
                    f.write(zip_content)

                extract_dir = os.path.join(temp_dir, "scorm")
                os.makedirs(extract_dir, exist_ok=True)

                with zipfile.ZipFile(zip_file_path, 'r') as zip_ref:
                    zip_ref.extractall(extract_dir)

                all_files = []

                for root, _, files in os.walk(extract_dir):
                    for f in files:
                        rel = os.path.relpath(os.path.join(root, f), extract_dir)
                        rel = rel.replace(os.sep, '/')
                        all_files.append(rel)

                launch_file = None

                for root, _, files in os.walk(extract_dir):

                    for file in files:

                        if file.lower().endswith(".xml"):

                            xml_path = os.path.join(root, file)

                            try:

                                tree = ET.parse(xml_path)
                                root_xml = tree.getroot()

                                if file.lower() == "imsmanifest.xml":

                                    version_el = next(
                                        (el for el in root_xml.iter() if el.tag.lower().endswith("schemaversion")),
                                        None
                                    )

                                    if version_el is not None and version_el.text:
                                        if version_el.text.strip() == "1.2":
                                            scorm_version = "scorm11"
                                        else:
                                            scorm_version = "scorm2004"

                                for res in root_xml.iter():

                                    if strip_namespace(res.tag) == "resource":

                                        scorm_type = next(
                                            (v for k, v in res.attrib.items() if k.lower().endswith("scormtype")),
                                            None
                                        )

                                        href = res.attrib.get("href")

                                        # if scorm_type and href:
                                        if scorm_type and scorm_type.lower() == "sco" and href:

                                            base, ext = os.path.splitext(href)

                                            launch_file = (
                                                href if href in all_files else
                                                find_case_insensitive(href, all_files) or
                                                find_with_alt_extensions(base, ext.lower(), all_files)
                                            )

                                            if launch_file:
                                                break

                                if launch_file:
                                    break

                            except Exception:
                                continue

                if not launch_file:

                    preferred = [
                        "index_lms.html",
                        "indexAPI.html",
                        "index.html",
                        "story.html"
                    ]

                    for p in preferred:
                        match = next((f for f in all_files if f.lower().endswith(p.lower())), None)
                        if match:
                            launch_file = match
                            break

                if not launch_file:
                    raise UserError("SCORM launch file not found.")

                selected_file = quote(f"{file_prefix}/{launch_file}", safe="/()")

                for root, _, files in os.walk(extract_dir):

                    for file in files:

                        full = os.path.join(root, file)

                        rel = os.path.relpath(full, extract_dir)
                        rel = rel.replace(os.sep, "/")

                        s3_key = f"{file_prefix}/{rel}"

                        mime, _ = guess_type(file)
                        if mime is None:
                            mime = "application/octet-stream"

                        with open(full, "rb") as f:

                            s3.upload_fileobj(
                                f,
                                bucket_name,
                                s3_key,
                                ExtraArgs={
                                    "ContentType": mime,
                                    "ContentDisposition": "inline"
                                }
                            )

                story_url = f"/scorm/{selected_file}"

                if scorm_version:
                    self.scorm_version = scorm_version

                return story_url

        except Exception as e:
            raise ValidationError(f"SCORM upload failed: {str(e)}")

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


    def read_files_from_zip(self):

        file = base64.decodebytes(self.scorm_data.datas)

        fobj = tempfile.NamedTemporaryFile(delete=False)
        fobj.write(file)
        fobj.flush()
        fobj.seek(0)

        path = os.path.dirname(os.path.abspath(__file__))

        html_file_name = None
        manifest_file = None

        module_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        source_dir = os.path.join(
            module_path,
            "static",
            "media",
            "scorm",
            str(self.id)
        )

        os.makedirs(source_dir, exist_ok=True)

        def find_case_insensitive(name, file_list):
            return next((f for f in file_list if f.lower() == name.lower()), None)

        def find_with_alt_extensions(base, ext, file_list):
            alt_ext = '.html' if ext == '.htm' else '.htm'
            alt_name = base + alt_ext
            return find_case_insensitive(alt_name, file_list)

        def strip_namespace(tag):
            return tag.split('}')[-1] if '}' in tag else tag

        try:

            with zipfile.ZipFile(fobj, 'r') as zipObj:

                zipObj.extractall(source_dir)

                listOfFileNames = [
                    f.replace("\\", "/") for f in zipObj.namelist()
                ]

                manifest = next(
                    (x for x in listOfFileNames if x.lower().endswith("imsmanifest.xml")),
                    None
                )

                if manifest:
                    manifest_file = os.path.join(source_dir, manifest)

                for name in listOfFileNames:

                    if name.lower().endswith(".xml"):

                        try:

                            xml_path = os.path.join(source_dir, name)

                            tree = ET.parse(xml_path)
                            root = tree.getroot()

                            for res in root.iter():

                                if strip_namespace(res.tag) == "resource":

                                    scorm_type = next(
                                        (v for k, v in res.attrib.items() if k.lower().endswith("scormtype")),
                                        None
                                    )

                                    href = res.attrib.get("href")

                                    # if scorm_type and href:
                                    if scorm_type and scorm_type.lower() == "sco" and href:

                                        base, ext = os.path.splitext(href)

                                        html_file_name = (
                                            href if href in listOfFileNames else
                                            find_case_insensitive(href, listOfFileNames) or
                                            find_with_alt_extensions(base, ext.lower(), listOfFileNames)
                                        )

                                        if html_file_name:
                                            break

                            if html_file_name:
                                break

                        except ET.ParseError:
                            continue

                if not html_file_name:

                    preferred = [
                        "index_lms.html",
                        "indexAPI.html",
                        "index.html",
                        "story.html"
                    ]

                    for p in preferred:
                        match = next(
                            (f for f in listOfFileNames if f.lower().endswith(p.lower())),
                            None
                        )
                        if match:
                            html_file_name = match
                            break

                if html_file_name:
                    from urllib.parse import quote

                    clean_path = quote(html_file_name)

                    self.filename = f'/website_scorm_elearning/static/media/scorm/{self.id}/{clean_path}'
                if manifest_file:
                    self.manifest_file = manifest_file
                    self.scorm_version = self.extract_scorm_version(manifest_file)

        except OSError:
            raise UserError("Error extracting SCORM package")
    
    def extract_scorm_version(self, manifest_file):
        tree = ET.parse(manifest_file)
        root = tree.getroot()
        schema_version_element = root.find('.//{http://www.imsproject.org/xsd/imscp_rootv1p1p2}metadata/{http://www.imsproject.org/xsd/imscp_rootv1p1p2}schemaversion')
        if schema_version_element is not None and schema_version_element.text == '1.2':
            return 'scorm11'
        else:
            return 'scorm2004'
