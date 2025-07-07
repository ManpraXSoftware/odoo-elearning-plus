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
from odoo.exceptions import UserError, UserError, ValidationError
from odoo.addons.http_routing.models.ir_http import url_for
from urllib.parse import quote
import logging

_logger = logging.getLogger(__name__)


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
            raise UserError("Amazon S3 credentials or bucket name are not configured in settings.")
        
        def find_case_insensitive(name, file_list):
            return next((f for f in file_list if f.lower() == name.lower()), None)

        def find_with_alt_extensions(base_name, ext, file_list):
            alt_ext = '.html' if ext == '.htm' else '.htm'
            alt_name = base_name + alt_ext
            return find_case_insensitive(alt_name, file_list)

        def strip_namespace(tag):
            return tag.split('}')[-1] if '}' in tag else tag

        try:
            s3 = boto3.client(
                's3',
                aws_access_key_id=amazon_access_key,
                aws_secret_access_key=amazon_secret_key
            )

            try:
                bucket_region = s3.get_bucket_location(Bucket=bucket_name).get('LocationConstraint') or 'us-east-1'
            except Exception as e:
                raise UserError(_("Failed to retrieve bucket region: %s" % str(e)))

            try:
                zip_content = base64.b64decode(scorm_data.datas)
            except Exception as e:
                raise UserError(_("Failed to decode the SCORM data: %s" % str(e)))

            base_name = os.path.splitext(scorm_data.name)[0]
            channel_id = int(str(self.channel_id.id).split("_")[1])
            file_prefix = f"{base_name}_Scorm_{channel_id}"
            story_url = None
            selected_file = None

            with tempfile.TemporaryDirectory() as temp_dir:
                zip_file_path = os.path.join(temp_dir, scorm_data.name)

                try:
                    with open(zip_file_path, 'wb') as zip_file:
                        zip_file.write(zip_content)
                except Exception as e:
                    raise UserError(_("Failed to save SCORM zip content to temporary file: %s" % str(e)))

                extract_dir = os.path.join(temp_dir, f"extracted_files/{file_prefix}")
                os.makedirs(extract_dir, exist_ok=True)

                try:
                    with zipfile.ZipFile(zip_file_path, 'r') as zip_ref:
                        zip_ref.extractall(extract_dir)
                except Exception as e:
                    raise UserError(_("Failed to extract SCORM zip file: %s" % str(e)))

                # Look for launch file in XMLs
                launch_file_from_xml = None
                for root_dir, _, files in os.walk(extract_dir):
                    for file_name in files:
                        if file_name.lower().endswith('.xml'):
                            file_path = os.path.join(root_dir, file_name)
                            try:
                                tree = ET.parse(file_path)
                                root = tree.getroot()

                                # Look for <resource> with sco
                                for res in root.iter():
                                    if strip_namespace(res.tag) == 'resource':
                                        scorm_type = res.attrib.get('{http://www.adlnet.org/xsd/adlcp_rootv1p2}scormtype') or res.attrib.get('scormType')
                                        href = res.attrib.get('href')
                                        if scorm_type and href:
                                            base, ext = os.path.splitext(href)
                                            launch_file_from_xml = (
                                                href if href in files else
                                                find_case_insensitive(href, files) or
                                                find_with_alt_extensions(base, ext.lower(), files)
                                            )
                                            if launch_file_from_xml:
                                                break
                                        

                                # Look for <launch><location> or <launch>text
                                if not launch_file_from_xml:
                                    launch = root.find('.//launch')
                                    if launch is not None:
                                        if launch.text:
                                            launch_file_from_xml = launch.text.strip()
                                        elif launch.find('location') is not None:
                                            launch_file_from_xml = launch.find('location').text.strip()
                                
                            except Exception:
                                continue  # skip unreadable or malformed XML

                # === Fallback selection: check for preferred launch files if XML not successful ===
                all_files = []
                for root_dir, _, files in os.walk(extract_dir):
                    for file_name in files:
                        relative_path = os.path.relpath(os.path.join(root_dir, file_name), extract_dir)
                        all_files.append(relative_path.replace(os.sep, '/'))

                # Launch file priority
                preferred_launch_files = ['index_lms.html', 'index.html', 'story.html']
                for fallback_name in preferred_launch_files:
                    fallback_path = next((f for f in all_files if f.endswith(fallback_name)), None)
                    if fallback_path:
                        fallback_encoded = quote(f"{file_prefix}/{fallback_path}", safe='/()')
                        if not selected_file:
                            selected_file = fallback_encoded
                        break

                # Override fallback if launch file from XML is more specific
                if launch_file_from_xml:
                    matched_file = next((f for f in all_files if f.endswith(launch_file_from_xml)), None)
                    if matched_file:
                        selected_file = quote(f"{file_prefix}/{matched_file}", safe='/()')

                # Upload all files to S3
                try:
                    s3_file_url_base = f"https://{bucket_name}.s3.{bucket_region}.amazonaws.com/"
                    for root_dir, _, files in os.walk(extract_dir):
                        for file_name in files:
                            file_path = os.path.join(root_dir, file_name)
                            relative_path = os.path.relpath(file_path, extract_dir)
                            s3_key = f"{file_prefix}/{relative_path.replace(os.sep, '/')}"
                            mime_type, _ = guess_type(file_name)
                            if mime_type is None:
                                mime_type = 'application/octet-stream'
                            with open(file_path, 'rb') as file_stream:
                                s3.upload_fileobj(
                                    file_stream,
                                    bucket_name,
                                    s3_key,
                                    ExtraArgs={'ContentType': mime_type, 'ContentDisposition': 'inline'}
                                )

                    if selected_file:
                        story_url = s3_file_url_base + selected_file

                    if not self.is_tincan and not selected_file:
                        raise UserError(_("SCORM launch file (index_lms.html, index.html, or story.html) not found."))

                except Exception as e:
                    raise ValidationError("Failed to upload files to Amazon S3: %s" % str(e))

            return story_url

        except Exception as e:
            raise ValidationError("An unexpected error occurred while processing the SCORM data: %s" % str(e))
    @api.depends('slide_category', 'google_drive_id', 'video_source_type', 'youtube_id')
    def _compute_embed_code(self):
            for rec in self:
                super(Slide, rec)._compute_embed_code()
                try:
                    if rec.slide_category == 'scorm' and rec.scorm_data and not rec.is_tincan:
                        rec.embed_code = Markup('<iframe src="%s" allowFullScreen="true" frameborder="0"></iframe>') % (rec.filename)
                        rec.embed_code_external = Markup('<iframe src="%s" allowFullScreen="true" frameborder="0"></iframe>') % (rec.filename)
                    elif rec.slide_category == 'scorm' and rec.scorm_data and rec.is_tincan:
                        user_name = self.env.user.id
                        user_mail = self.env.user.login
                        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
                        end_point = f"{base_url}/slides/slide"
                        encoded_endpoint = urllib.parse.quote(end_point, safe=":/?&=")
                        actor_data = {
                            "name": [user_name],
                            "mbox": [f"mailto:{user_mail},{rec.id}"]
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
                except:
                    if rec.slide_category  == 'scorm' and rec.scorm_data:
                        rec.embed_code = Markup('<iframe src="%s" allowFullScreen="true" frameborder="0"></iframe>') % (rec.filename)
                        rec.embed_code_external = Markup('<iframe src="%s" allowFullScreen="true" frameborder="0"></iframe>') % (rec.filename)

    def read_files_from_zip(self):
        file = base64.decodebytes(self.scorm_data.datas)
        fobj = tempfile.NamedTemporaryFile(delete=False)
        fobj.write(file)
        fobj.flush()
        fobj.seek(0)

        path = os.path.dirname(os.path.abspath(__file__))
        html_file_name = None
        manifest_file = None

        source_dir = os.path.join(os.path.split(path)[-2], "static", "media", "scorm", str(self.id))

        def find_case_insensitive(name, file_list):
            return next((f for f in file_list if f.lower() == name.lower()), None)

        def find_with_alt_extensions(base_name, ext, file_list):
            alt_ext = '.html' if ext == '.htm' else '.htm'
            alt_name = base_name + alt_ext
            return find_case_insensitive(alt_name, file_list)

        def strip_namespace(tag):
            return tag.split('}')[-1] if '}' in tag else tag

        try:
            with zipfile.ZipFile(fobj, 'r') as zipObj:
                listOfFileNames = zipObj.namelist()
                zipObj.extractall(source_dir)

                manifest_file_name = [x for x in listOfFileNames if x.lower().endswith("imsmanifest.xml")]
                if manifest_file_name:
                    manifest_file = os.path.join(source_dir, manifest_file_name[0])

                for name in listOfFileNames:
                    if name.lower().endswith(".xml"):
                        try:
                            xml_path = os.path.join(source_dir, name)
                            tree = ET.parse(xml_path)
                            root = tree.getroot()

                            # Look for <resource> with sco
                            for res in root.iter():
                                if strip_namespace(res.tag) == 'resource':
                                    scorm_type = res.attrib.get('{http://www.adlnet.org/xsd/adlcp_rootv1p2}scormtype') or res.attrib.get('scormType')
                                    print (res.attrib)
                                    href = res.attrib.get('href')
                                    if scorm_type and href:
                                        base, ext = os.path.splitext(href)
                                        html_file_name = (
                                            href if href in listOfFileNames else
                                            find_case_insensitive(href, listOfFileNames) or
                                            find_with_alt_extensions(base, ext.lower(), listOfFileNames)
                                        )
                                        if html_file_name:
                                            break
                                    

                            # Look for <launch><location> or <launch>text
                            if not html_file_name:
                                launch = root.find('.//launch')
                                if launch is not None:
                                    if launch.text:
                                        html_file_name = launch.text.strip()
                                    elif launch.find('location') is not None:
                                        html_file_name = launch.find('location').text.strip()
                            if html_file_name:
                                break
                        except ET.ParseError:
                            continue

                # Fallback to known filenames
                if not html_file_name:
                    if not self.is_tincan:
                        for candidate in ['story.html', 'index.html']:
                            match = next((f for f in listOfFileNames if candidate.lower() in f.lower()), None)
                            if match:
                                html_file_name = match
                                break
                    else:
                        for candidate in ['index_lms.html', 'story.html', 'index.html']:
                            match = next((f for f in listOfFileNames if candidate.lower() in f.lower()), None)
                            if match:
                                html_file_name = match
                                break

                if html_file_name:
                    self.filename = f'/website_scorm_elearning/static/media/scorm/{self.id}/{html_file_name}'
                if manifest_file:
                    self.manifest_file = manifest_file
                    self.scorm_version = self.extract_scorm_version(manifest_file)

        except OSError as e:
            _logger.warning("Filesystem is read-only, cannot create directory: %s", source_dir)
            raise UserError("Something went wrong")
        
    def extract_scorm_version(self, manifest_file):
        tree = ET.parse(manifest_file)
        root = tree.getroot()
        # Find the schemaversion element
        schema_version_element = root.find('.//{http://www.imsproject.org/xsd/imscp_rootv1p1p2}metadata/{http://www.imsproject.org/xsd/imscp_rootv1p1p2}schemaversion')
        # Check if the version is 1.2
        if schema_version_element is not None and schema_version_element.text == '1.2':
            return 'scorm11'
        else:
            return 'scorm2004'
