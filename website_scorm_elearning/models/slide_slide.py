# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
import os
import json
import base64
import zipfile
import tempfile
import shutil
import urllib.parse
import posixpath
import boto3
import logging

from io import BytesIO
from mimetypes import guess_type
import xml.etree.ElementTree as ET
from urllib.parse import quote
from werkzeug import urls
from odoo.http import request
from markupsafe import Markup
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


_logger = logging.getLogger(__name__)


class SlidePartnerRelation(models.Model):
    _inherit = 'slide.slide.partner'

    lms_session_info_ids = fields.One2many(
        'lms.session.info',
        'slide_partner_id',
        'LMS Session Info'
    )

    lms_scorm_karma = fields.Integer("Scorm Karma")


class LmsSessionInfo(models.Model):
    _name = 'lms.session.info'
    _description = 'Lms Session Info'

    name = fields.Char("Name")
    value = fields.Char("Value")
    slide_partner_id = fields.Many2one(
        'slide.slide.partner'
    )


class Channel(models.Model):
    """ A channel is a container of slides. """
    _inherit = 'slide.channel'

    nbr_scorm = fields.Integer(
        "Number of Scorms",
        compute="_compute_slides_statistics",
        store=True
    )

    @api.depends(
        'slide_ids.slide_category',
        'slide_ids.is_published',
        'slide_ids.completion_time',
        'slide_ids.likes',
        'slide_ids.dislikes',
        'slide_ids.total_views',
        'slide_ids.is_category',
        'slide_ids.active'
    )
    def _compute_slides_statistics(self):
        super(Channel, self)._compute_slides_statistics()


class Slide(models.Model):
    _inherit = 'slide.slide'

    slide_category = fields.Selection(
        selection_add=[
            ('scorm', 'Scorm')
        ],
        ondelete={
            'scorm': 'set default'
        }
    )

    slide_type = fields.Selection(
        selection_add=[
            ('scorm', 'Scorm')
        ],
        ondelete={
            'scorm': 'set null'
        },
        compute="_compute_slide_type",
        store=True
    )

    is_amazon_s3 = fields.Boolean(
        string="Scorm upload on Amazon S3",
        help="Indicates whether the slide file is hosted on Amazon S3"
    )

    scorm_data = fields.Many2many(
        'ir.attachment'
    )

    nbr_scorm = fields.Integer(
        "Number of Scorms",
        compute="_compute_slides_statistics",
        store=True
    )

    filename = fields.Char()

    embed_code = fields.Html(
        'Embed Code',
        readonly=True,
        compute='_compute_embed_code'
    )

    embed_code_external = fields.Html(
        'External Embed Code',
        readonly=True,
        compute='_compute_embed_code'
    )

    scorm_version = fields.Selection(
        [
            ('scorm11', 'Scorm 1.1/1.2'),
            ('scorm2004', 'Scorm 2004 Edition')
        ],
        default="scorm11"
    )

    scorm_passed_xp = fields.Integer(
        "Scorm Passed Xp"
    )

    scorm_completed_xp = fields.Integer(
        "Scorm Completed Xp"
    )

    scorm_completion_on_finish = fields.Boolean(
        "Scorm Completion on Finish"
    )

    manifest_file = fields.Char()

    @staticmethod
    def _strip_ns(tag):
        if not tag:
            return ''

        return tag.split('}', 1)[-1]

    @staticmethod
    def _normalize_zip_path(path):

        if not path:
            return None

        path = str(path)
        path = path.replace('\\', '/')
        path = path.split('#', 1)[0]
        path = path.split('?', 1)[0]
        path = path.lstrip('/')
        normalized = posixpath.normpath(path)
        if normalized == '.':
            return ''
        return normalized

    @staticmethod
    def _find_case_insensitive(name, file_list):

        if not name:
            return None

        normalized_name = Slide._normalize_zip_path(name)

        if not normalized_name:
            return None

        for file_name in file_list:
            normalized_file = Slide._normalize_zip_path(file_name)

            if not normalized_file:
                continue

            if normalized_file.lower() == normalized_name.lower():
                return normalized_file

        return None

    @staticmethod
    def _safe_zip_member_path(target_dir, member_name):
        target_dir = os.path.abspath(target_dir)

        member_name = member_name.replace('\\', '/')

        member_path = os.path.abspath(
            os.path.join(
                target_dir,
                member_name
            )
        )

        if not (
            member_path == target_dir
            or member_path.startswith(target_dir + os.sep)
        ):
            raise UserError(
                _(
                    "Invalid SCORM ZIP file: "
                    "unsafe file path detected: %s"
                ) % member_name
            )

        return member_path

    def _safe_extract_zip(self, zip_obj, target_dir):

        target_dir = os.path.abspath(target_dir)

        for member in zip_obj.infolist():

            self._safe_zip_member_path(
                target_dir,
                member.filename
            )

        zip_obj.extractall(target_dir)

    def _resolve_scorm_launch_file(
        self,
        manifest_path,
        available_files,
        manifest_zip_path=None
    ):


        if not manifest_path:
            return None

        try:
            tree = ET.parse(manifest_path)

        except (
            ET.ParseError,
            OSError
        ) as e:

            _logger.exception(
                "Unable to parse SCORM manifest %s: %s",
                manifest_path,
                e
            )

            return None

        root = tree.getroot()



        def local_name(tag):
            return self._strip_ns(tag).lower()

        def get_attr(element, attribute_name):

            if element is None:
                return None

            attribute_name = attribute_name.lower()

            for key, value in element.attrib.items():

                if self._strip_ns(key).lower() == attribute_name:
                    return value

            return None


        normalized_files = []

        for file_name in available_files:

            normalized = self._normalize_zip_path(
                file_name
            )

            if normalized and normalized not in normalized_files:
                normalized_files.append(normalized)

        if not normalized_files:
            _logger.warning(
                "SCORM package contains no files."
            )
            return None


        if manifest_zip_path:

            manifest_zip_path = self._normalize_zip_path(
                manifest_zip_path
            )

        else:

            manifest_zip_path = None

            manifest_base_name = 'imsmanifest.xml'


            for file_name in normalized_files:

                if file_name.lower() == manifest_base_name:
                    manifest_zip_path = file_name
                    break


            if not manifest_zip_path:

                for file_name in normalized_files:

                    if posixpath.basename(
                        file_name
                    ).lower() == manifest_base_name:

                        manifest_zip_path = file_name
                        break

        manifest_dir = ''

        if manifest_zip_path:

            manifest_dir = posixpath.dirname(
                manifest_zip_path
            )

        _logger.info(
            "SCORM manifest ZIP path: %s",
            manifest_zip_path
        )

        _logger.info(
            "SCORM manifest directory: %s",
            manifest_dir
        )


        def resolve_path(href, base_dir=''):

            if not href:
                return None

            href = str(href).strip()

            if not href:
                return None

            href = href.replace('\\', '/')


            href = href.split('#', 1)[0]
            href = href.split('?', 1)[0]


            href = href.lstrip('/')

            if base_dir:

                candidate = posixpath.join(
                    base_dir,
                    href
                )

            else:

                candidate = href

            candidate = self._normalize_zip_path(
                candidate
            )

            if not candidate:
                return None


            if candidate in normalized_files:
                return candidate


            return self._find_case_insensitive(
                candidate,
                normalized_files
            )

        resources = {}

        for element in root.iter():

            if local_name(element.tag) != 'resource':
                continue

            identifier = get_attr(
                element,
                'identifier'
            )

            href = get_attr(
                element,
                'href'
            )

            if not identifier:
                continue

            resources[identifier] = {
                'element': element,
                'href': href,
            }

        _logger.info(
            "SCORM resources found: %s",
            {
                identifier: resource.get('href')
                for identifier, resource in resources.items()
            }
        )

        organizations = None

        for element in root.iter():

            if local_name(element.tag) == 'organizations':

                organizations = element
                break

        organization = None

        if organizations is not None:

            default_id = get_attr(
                organizations,
                'default'
            )

            organization_elements = [
                element
                for element in list(organizations)
                if local_name(element.tag) == 'organization'
            ]


            if default_id:

                for org in organization_elements:

                    if get_attr(
                        org,
                        'identifier'
                    ) == default_id:

                        organization = org
                        break


            if organization is None and organization_elements:

                organization = organization_elements[0]


        def find_launch_from_items(parent):

            if parent is None:
                return None

            for element in parent.iter():

                if local_name(element.tag) != 'item':
                    continue

                identifierref = get_attr(
                    element,
                    'identifierref'
                )

                if not identifierref:
                    continue

                resource = resources.get(
                    identifierref
                )

                if not resource:

                    _logger.warning(
                        "SCORM item references missing "
                        "resource: %s",
                        identifierref
                    )

                    continue

                resource_element = resource.get(
                    'element'
                )

                href = resource.get(
                    'href'
                )

                if not href:
                    continue



                resource_base = manifest_dir

                if resource_element is not None:

                    xml_base = resource_element.attrib.get(
                        '{http://www.w3.org/XML/1998/namespace}base'
                    )

                    if xml_base:

                        resource_base = (
                            self._normalize_zip_path(
                                posixpath.join(
                                    resource_base,
                                    xml_base
                                )
                            )
                        )


                resolved = resolve_path(
                    href,
                    resource_base
                )

                if resolved:

                    _logger.info(
                        "SCORM launch file resolved from "
                        "organization/item/resource: %s",
                        resolved
                    )

                    return resolved



                resolved = resolve_path(
                    href,
                    ''
                )

                if resolved:

                    _logger.info(
                        "SCORM launch file resolved using "
                        "package-root fallback: %s",
                        resolved
                    )

                    return resolved

            return None



        launch_file = None

        if organization is not None:

            launch_file = find_launch_from_items(
                organization
            )


        if not launch_file:

            _logger.info(
                "Trying SCORM resource scormtype fallback."
            )

            for resource in resources.values():

                resource_element = resource.get(
                    'element'
                )

                href = resource.get(
                    'href'
                )

                if resource_element is None:
                    continue

                if not href:
                    continue

                scorm_type = get_attr(
                    resource_element,
                    'scormtype'
                )

                if not scorm_type:
                    continue

                scorm_type = scorm_type.lower().strip()

                if scorm_type not in (
                    'sco',
                    'asset',
                    'webcontent'
                ):
                    continue

                resource_base = manifest_dir

                xml_base = resource_element.attrib.get(
                    '{http://www.w3.org/XML/1998/namespace}base'
                )

                if xml_base:

                    resource_base = (
                        self._normalize_zip_path(
                            posixpath.join(
                                resource_base,
                                xml_base
                            )
                        )
                    )

                launch_file = resolve_path(
                    href,
                    resource_base
                )

                if not launch_file:

                    launch_file = resolve_path(
                        href,
                        ''
                    )

                if launch_file:

                    _logger.info(
                        "SCORM launch file resolved from "
                        "scormtype resource: %s",
                        launch_file
                    )

                    break


        if launch_file:

            _logger.info(
                "FINAL SCORM LAUNCH FILE: %s",
                launch_file
            )

            return launch_file

        _logger.warning(
            "Could not resolve SCORM launch file "
            "from manifest: %s",
            manifest_path
        )

        return None

    @api.onchange('is_amazon_s3')
    def _onchange_is_amazon_s3(self):

        amazon_access_key = (
            self.env['ir.config_parameter']
            .sudo()
            .get_param(
                'amazon_s3_connector.amazon_access_key'
            )
        )

        amazon_secret_key = (
            self.env['ir.config_parameter']
            .sudo()
            .get_param(
                'amazon_s3_connector.amazon_secret_key'
            )
        )

        bucket_name = (
            self.env['ir.config_parameter']
            .sudo()
            .get_param(
                'amazon_s3_connector.amazon_bucket_name'
            )
        )

        if self.is_amazon_s3:

            if (
                not amazon_access_key
                or not amazon_secret_key
                or not bucket_name
            ):

                self.scorm_data = False

                raise UserError(
                    _(
                        "Amazon S3 credentials or "
                        "bucket name are not configured."
                    )
                )



    @api.onchange('scorm_version')
    def onchange_scorm_version(self):

        if self.manifest_file:

            res = {}

            try:

                actual_version = self.extract_scorm_version(
                    self.manifest_file
                )

                if actual_version != self.scorm_version:

                    res['warning'] = {
                        'title': _('Warning'),
                        'message': _(
                            'The SCORM version is different from '
                            'the actual SCORM version. Results may '
                            'vary if you select the wrong SCORM version.'
                        )
                    }

            except Exception:

                _logger.exception(
                    "Unable to detect SCORM version."
                )

            return res



    @api.depends(
        'slide_ids.sequence',
        'slide_ids.slide_category',
        'slide_ids.is_published',
        'slide_ids.is_category'
    )
    def _compute_slides_statistics(self):

        super(Slide, self)._compute_slides_statistics()

    @api.depends(
        'slide_category',
        'question_ids',
        'channel_id.is_member'
    )
    @api.depends_context('uid')
    def _compute_mark_complete_actions(self):

        super(Slide, self)._compute_mark_complete_actions()

    @api.depends(
        'slide_category',
        'source_type',
        'video_source_type'
    )
    def _compute_slide_type(self):

        res = super(Slide, self)._compute_slide_type()

        for slide in self:

            if slide.slide_category == 'scorm':
                slide.slide_type = 'scorm'

        return res

    @api.depends('slide_type')
    def _compute_slide_icon_class(self):

        slide = self.filtered(
            lambda slide: slide.slide_type == 'scorm'
        )

        slide.slide_icon_class = 'fa-file-archive-o'

        super(
            Slide,
            self - slide
        )._compute_slide_icon_class()


    def _compute_quiz_info(
        self,
        target_partner,
        quiz_done=False
    ):

        res = super(
            Slide,
            self
        )._compute_quiz_info(
            target_partner
        )

        for slide in self:

            slide_partner_id = (
                self.env['slide.slide.partner']
                .sudo()
                .search(
                    [
                        ('slide_id', '=', slide.id),
                        ('partner_id', '=', target_partner.id)
                    ],
                    limit=1
                )
            )

            if res[slide.id].get(
                'quiz_karma_won'
            ):

                res[slide.id][
                    'quiz_karma_won'
                ] += slide_partner_id.lms_scorm_karma

            else:

                res[slide.id][
                    'quiz_karma_won'
                ] = slide_partner_id.lms_scorm_karma

        return res

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            if rec.sudo().scorm_data and not rec.is_amazon_s3:
                rec.read_files_from_zip()
            elif rec.sudo().scorm_data and rec.is_amazon_s3:
                rec.filename = rec._upload_to_s3(rec.sudo().scorm_data)
        return records


    @api.onchange('scorm_data')
    def _on_change_scorm_data(self):

        if self.scorm_data:

            if len(self.scorm_data) > 1:

                raise ValidationError(
                    _(
                        "Only one SCORM package allowed per slide."
                    )
                )

            file_name = self.scorm_data.name or ''

            extension = os.path.splitext(
                file_name
            )[1].lower()

            if extension != '.zip':

                raise ValidationError(
                    _("The file must be a ZIP file.")
                )

            if self.is_amazon_s3:

                self.filename = self._upload_to_s3(
                    self.scorm_data
                )

            else:

                self.read_files_from_zip()

        else:

            if self.filename:

                try:

                    folder_dir = (
                        self.filename
                        .split('scorm')[-1]
                        .split('/')[-2]
                    )

                except Exception:

                    folder_dir = None

                path = os.path.dirname(
                    os.path.abspath(__file__)
                )

                if folder_dir:

                    target_dir = os.path.join(
                        os.path.split(path)[-2],
                        "static",
                        "media",
                        "scorm",
                        str(self.id),
                        folder_dir
                    )

                else:

                    target_dir = os.path.join(
                        os.path.split(path)[-2],
                        "static",
                        "media",
                        "scorm",
                        str(self.id)
                    )

                if os.path.isdir(target_dir):

                    shutil.rmtree(
                        target_dir
                    )



    def _upload_to_s3(self, scorm_data):

        amazon_access_key = (
            self.env['ir.config_parameter']
            .sudo()
            .get_param(
                'amazon_s3_connector.amazon_access_key'
            )
        )

        amazon_secret_key = (
            self.env['ir.config_parameter']
            .sudo()
            .get_param(
                'amazon_s3_connector.amazon_secret_key'
            )
        )

        bucket_name = (
            self.env['ir.config_parameter']
            .sudo()
            .get_param(
                'amazon_s3_connector.amazon_bucket_name'
            )
        )

        if (
            not amazon_access_key
            or not amazon_secret_key
            or not bucket_name
        ):

            raise UserError(
                _(
                    "Amazon S3 credentials or bucket name "
                    "are not configured in settings."
                )
            )

        try:

            s3 = boto3.client(
                's3',
                aws_access_key_id=amazon_access_key,
                aws_secret_access_key=amazon_secret_key
            )

            try:

                bucket_region = (
                    s3.get_bucket_location(
                        Bucket=bucket_name
                    ).get('LocationConstraint')
                    or 'us-east-1'
                )

            except Exception as e:

                raise UserError(
                    _(
                        "Failed to retrieve bucket region: %s"
                    ) % str(e)
                )


            try:

                zip_content = base64.b64decode(
                    scorm_data.datas
                )

            except Exception as e:

                raise UserError(
                    _(
                        "Failed to decode the SCORM data: %s"
                    ) % str(e)
                )

            base_name = os.path.splitext(
                scorm_data.name
            )[0]



            channel_id = self.channel_id.id

            try:

                channel_id = int(
                    str(channel_id).split("_")[-1]
                )

            except Exception:

                channel_id = int(
                    channel_id
                )

            file_prefix = (
                f"{base_name}_Scorm_{channel_id}"
            )

            story_url = None
            selected_file = None
            scorm_version = None
            manifest_relative_path = None

            is_tincan = getattr(
                self,
                'is_tincan',
                None
            )



            with tempfile.TemporaryDirectory() as temp_dir:

                zip_file_path = os.path.join(
                    temp_dir,
                    scorm_data.name
                )

                try:

                    with open(
                        zip_file_path,
                        'wb'
                    ) as zip_file:

                        zip_file.write(
                            zip_content
                        )

                except Exception as e:

                    raise UserError(
                        _(
                            "Failed to save SCORM ZIP content "
                            "to temporary file: %s"
                        ) % str(e)
                    )

                extract_dir = os.path.join(
                    temp_dir,
                    "extracted_files",
                    file_prefix
                )

                os.makedirs(
                    extract_dir,
                    exist_ok=True
                )


                try:

                    with zipfile.ZipFile(
                        zip_file_path,
                        'r'
                    ) as zip_ref:

                        list_of_files = zip_ref.namelist()

                        self._safe_extract_zip(
                            zip_ref,
                            extract_dir
                        )

                except UserError:
                    raise

                except Exception as e:

                    raise UserError(
                        _(
                            "Failed to extract SCORM ZIP file: %s"
                        ) % str(e)
                    )



                all_files = []

                for root_dir, _, files in os.walk(
                    extract_dir
                ):

                    for file_name in files:

                        relative_path = os.path.relpath(
                            os.path.join(
                                root_dir,
                                file_name
                            ),
                            extract_dir
                        )

                        relative_path = (
                            relative_path
                            .replace(
                                os.sep,
                                '/'
                            )
                        )

                        all_files.append(
                            relative_path
                        )

                _logger.info(
                    "SCORM files extracted: %s",
                    all_files
                )


                has_tincan = any(
                    os.path.basename(
                        f
                    ).lower() == 'tincan.xml'
                    for f in all_files
                )



                manifest_candidates = [
                    f for f in all_files
                    if os.path.basename(
                        f
                    ).lower() == 'imsmanifest.xml'
                ]

                manifest_relative_path = (
                    manifest_candidates[0]
                    if manifest_candidates
                    else None
                )

                launch_file_from_xml = None



                if manifest_relative_path:

                    manifest_path = os.path.join(
                        extract_dir,
                        *manifest_relative_path.split('/')
                    )


                    try:

                        tree = ET.parse(
                            manifest_path
                        )

                        version_element = next(
                            (
                                el
                                for el in tree.getroot().iter()
                                if self._strip_ns(
                                    el.tag
                                ).lower() == 'schemaversion'
                            ),
                            None
                        )

                        if (
                            version_element is not None
                            and version_element.text
                        ):

                            schema_version = (
                                version_element.text
                                .strip()
                                .lower()
                            )

                            if schema_version in (
                                '1.1',
                                '1.2'
                            ):

                                scorm_version = 'scorm11'

                            elif (
                                schema_version.startswith(
                                    '2004'
                                )
                                or '2004' in schema_version
                            ):

                                scorm_version = 'scorm2004'

                    except (
                        ET.ParseError,
                        OSError
                    ):

                        _logger.exception(
                            "Failed to read SCORM version "
                            "from manifest."
                        )


                    launch_file_from_xml = (
                        self._resolve_scorm_launch_file(
                            manifest_path,
                            all_files,
                            manifest_zip_path=manifest_relative_path
                        )
                    )


                if launch_file_from_xml:

                    candidate = self._find_case_insensitive(
                        launch_file_from_xml,
                        all_files
                    )

                    if candidate:

                        selected_file = quote(
                            f"{file_prefix}/{candidate}",
                            safe='/()'
                        )

                        _logger.info(
                            "S3 SCORM launch file selected "
                            "from manifest: %s",
                            candidate
                        )



                if not selected_file:

                    _logger.warning(
                        "Manifest could not resolve SCORM "
                        "launch file. Trying fallback names."
                    )

                    preferred_launch_files = [
                        'index_lms.html',
                        'index.html',
                        'story.html',
                        'index.htm',
                        'story.htm'
                    ]

                    for fallback_name in preferred_launch_files:

                        fallback_path = next(
                            (
                                f
                                for f in all_files
                                if os.path.basename(
                                    f
                                ).lower()
                                == fallback_name.lower()
                            ),
                            None
                        )

                        if not fallback_path:
                            continue

                        fallback_encoded = quote(
                            f"{file_prefix}/{fallback_path}",
                            safe='/()'
                        )

                        if (
                            is_tincan is False
                            or is_tincan is None
                        ):

                            if has_tincan:

                                if fallback_name in (
                                    'story.html',
                                    'story.htm'
                                ):

                                    selected_file = (
                                        fallback_encoded
                                    )

                                    break

                                elif (
                                    fallback_name in (
                                        'index.html',
                                        'index.htm'
                                    )
                                    and not any(
                                        os.path.basename(
                                            f
                                        ).lower()
                                        in (
                                            'story.html',
                                            'story.htm'
                                        )
                                        for f in all_files
                                    )
                                ):

                                    selected_file = (
                                        fallback_encoded
                                    )

                                    break

                            else:

                                selected_file = (
                                    fallback_encoded
                                )

                                break

                        elif is_tincan is True:

                            if has_tincan:

                                selected_file = (
                                    fallback_encoded
                                )

                                break

                            else:

                                raise UserError(
                                    _(
                                        "SCORM file is marked as "
                                        "TinCan, but tincan.xml "
                                        "is missing."
                                    )
                                )



                if not selected_file:

                    raise UserError(
                        _(
                            "Unable to determine the SCORM launch "
                            "file. The package does not contain a "
                            "valid launch resource in "
                            "imsmanifest.xml."
                        )
                    )



                s3_file_url_base = (
                    f"https://{bucket_name}.s3."
                    f"{bucket_region}.amazonaws.com/"
                )


                try:

                    for root_dir, _, files in os.walk(
                        extract_dir
                    ):

                        for file_name in files:

                            file_path = os.path.join(
                                root_dir,
                                file_name
                            )

                            relative_path = os.path.relpath(
                                file_path,
                                extract_dir
                            )

                            relative_path = (
                                relative_path
                                .replace(
                                    os.sep,
                                    '/'
                                )
                            )

                            s3_key = (
                                f"{file_prefix}/"
                                f"{relative_path}"
                            )

                            mime_type, _ = guess_type(
                                file_name
                            )

                            if mime_type is None:

                                mime_type = (
                                    'application/octet-stream'
                                )

                            with open(
                                file_path,
                                'rb'
                            ) as file_stream:

                                s3.upload_fileobj(
                                    file_stream,
                                    bucket_name,
                                    s3_key,
                                    ExtraArgs={
                                        'ContentType': mime_type,
                                        'ContentDisposition': 'inline'
                                    }
                                )



                    if selected_file:

                        story_url = (
                            f"/scorm/{selected_file}"
                        )



                    if scorm_version:

                        self.scorm_version = (
                            scorm_version
                        )


                    if manifest_relative_path:

                        self.manifest_file = (
                            f"{s3_file_url_base}"
                            f"{file_prefix}/"
                            f"{manifest_relative_path}"
                        )

                except Exception as e:

                    _logger.exception(
                        "Failed to upload SCORM files to S3."
                    )

                    raise ValidationError(
                        _(
                            "Failed to upload files to "
                            "Amazon S3: %s"
                        ) % str(e)
                    )

            return story_url

        except (
            UserError,
            ValidationError
        ):
            raise

        except Exception as e:

            _logger.exception(
                "Unexpected error while processing SCORM."
            )

            raise ValidationError(
                _(
                    "An unexpected error occurred while "
                    "processing the SCORM data: %s"
                ) % str(e)
            )



    @api.depends(
        'slide_category',
        'google_drive_id',
        'video_source_type',
        'youtube_id'
    )
    def _compute_embed_code(self):

        for rec in self:

            super(
                Slide,
                rec
            )._compute_embed_code()

            try:

                if (
                    rec.slide_category == 'scorm'
                    and rec.scorm_data
                    and not rec.is_tincan
                ):

                    rec.embed_code = Markup(
                        '<iframe src="%s" '
                        'frameborder="0" '
                        'aria-label="%s"></iframe>'
                    ) % (
                        rec.filename,
                        _('Scorm')
                    )

                    rec.embed_code_external = Markup(
                        '<iframe src="%s" '
                        'frameborder="0" '
                        'aria-label="%s"></iframe>'
                    ) % (
                        rec.filename,
                        _('Scorm')
                    )

                elif (
                    rec.slide_category == 'scorm'
                    and rec.scorm_data
                    and rec.is_tincan
                ):

                    user_name = self.env.user.id
                    user_mail = self.env.user.login

                    base_url = (
                        self.env['ir.config_parameter']
                        .sudo()
                        .get_param(
                            'web.base.url'
                        )
                    )

                    end_point = (
                        f"{base_url}/slides/slide"
                    )

                    encoded_endpoint = (
                        urllib.parse.quote(
                            end_point,
                            safe=":/?&="
                        )
                    )

                    actor_data = {
                        "name": [user_name],
                        "mbox": [
                            f"mailto:{user_mail}"
                        ]
                    }

                    actor_json = json.dumps(
                        actor_data
                    )

                    encoded_actor = (
                        urllib.parse.quote(
                            actor_json
                        )
                    )

                    iframe_template = (
                        '<iframe src="{}?endpoint={}'
                        '&actor={}&activity_id={}" '
                        'allowFullScreen="true" '
                        'frameborder="0"></iframe>'
                    )

                    rec.embed_code = Markup(
                        iframe_template.format(
                            rec.filename,
                            encoded_endpoint,
                            encoded_actor,
                            rec.id
                        )
                    )

                    rec.embed_code_external = Markup(
                        iframe_template.format(
                            rec.filename,
                            encoded_endpoint,
                            encoded_actor,
                            rec.id
                        )
                    )

            except Exception:

                _logger.exception(
                    "Failed to compute SCORM embed code."
                )

                if (
                    rec.slide_category == 'scorm'
                    and rec.scorm_data
                ):

                    rec.embed_code = Markup(
                        '<iframe src="%s" '
                        'frameborder="0" '
                        'autoplay="1"></iframe>'
                    ) % rec.filename

                    rec.embed_code_external = Markup(
                        '<iframe src="%s" '
                        'aria-label="%s"></iframe>'
                    ) % (
                        rec.filename,
                        _('Scorm')
                    )



    def read_files_from_zip(self):

        if not self.scorm_data:
            return

        try:

            file_data = base64.b64decode(
                self.scorm_data.datas
            )

        except Exception as e:

            raise UserError(
                _(
                    "Unable to decode the SCORM ZIP file: %s"
                ) % str(e)
            )

        path = os.path.dirname(
            os.path.abspath(__file__)
        )

        source_dir = os.path.join(
            os.path.split(path)[-2],
            "static",
            "media",
            "scorm",
            str(self.id)
        )

        os.makedirs(
            source_dir,
            exist_ok=True
        )

        html_file_name = None
        manifest_file = None

        is_tincan = getattr(
            self,
            'is_tincan',
            None
        )

        temp_zip_path = None

        try:



            with tempfile.NamedTemporaryFile(
                delete=False,
                suffix='.zip'
            ) as fobj:

                fobj.write(
                    file_data
                )

                temp_zip_path = fobj.name



            with zipfile.ZipFile(
                temp_zip_path,
                'r'
            ) as zip_obj:

                list_of_file_names = (
                    zip_obj.namelist()
                )

                _logger.info(
                    "SCORM ZIP contains %s files.",
                    len(list_of_file_names)
                )



                self._safe_extract_zip(
                    zip_obj,
                    source_dir
                )



                manifest_candidates = [
                    x
                    for x in list_of_file_names
                    if os.path.basename(
                        x
                    ).lower() == 'imsmanifest.xml'
                ]

                if manifest_candidates:

                    # Keep the actual ZIP-relative path.
                    manifest_file = (
                        manifest_candidates[0]
                    )

                    manifest_file_path = os.path.join(
                        source_dir,
                        *manifest_file.replace(
                            '\\',
                            '/'
                        ).split('/')
                    )

                    _logger.info(
                        "SCORM manifest found: %s",
                        manifest_file
                    )



                    resolved = (
                        self._resolve_scorm_launch_file(
                            manifest_file_path,
                            list_of_file_names,
                            manifest_zip_path=manifest_file
                        )
                    )

                    if resolved:

                        html_file_name = resolved

                        _logger.info(
                            "SCORM local launch file resolved "
                            "from manifest: %s",
                            html_file_name
                        )



                    try:

                        self.scorm_version = (
                            self.extract_scorm_version(
                                manifest_file_path
                            )
                        )

                    except Exception:

                        _logger.exception(
                            "Unable to extract SCORM version."
                        )



                has_tincan = any(
                    os.path.basename(
                        f
                    ).lower() == 'tincan.xml'
                    for f in list_of_file_names
                )



                if not html_file_name:

                    _logger.warning(
                        "SCORM launch file was not found "
                        "from manifest. Using fallback."
                    )

                    if (
                        is_tincan is False
                        or is_tincan is None
                    ):

                        candidates = [
                            'story.html',
                            'index.html',
                            'story.htm',
                            'index.htm',
                            'index_lms.html'
                        ]

                    else:

                        candidates = [
                            'index_lms.html',
                            'story.html',
                            'index.html',
                            'story.htm',
                            'index.htm'
                        ]

                    for candidate in candidates:

                        match = next(
                            (
                                f
                                for f in list_of_file_names
                                if os.path.basename(
                                    f
                                ).lower()
                                == candidate.lower()
                            ),
                            None
                        )

                        if match:

                            html_file_name = (
                                self._normalize_zip_path(
                                    match
                                )
                            )

                            break



                if not html_file_name:

                    raise UserError(
                        _(
                            "Unable to determine the SCORM "
                            "launch file. Please check that "
                            "imsmanifest.xml contains a valid "
                            "resource href."
                        )
                    )


                self.filename = (
                    '/website_scorm_elearning/'
                    'static/media/scorm/'
                    f'{self.id}/'
                    f'{html_file_name}'
                )

                _logger.info(
                    "FINAL LOCAL SCORM URL: %s",
                    self.filename
                )



                if manifest_file:

                    self.manifest_file = os.path.join(
                        source_dir,
                        *manifest_file.replace(
                            '\\',
                            '/'
                        ).split('/')
                    )

        except UserError:
            raise

        except OSError as e:

            _logger.exception(
                "Filesystem error while extracting SCORM."
            )

            raise UserError(
                _(
                    "Something went wrong while extracting "
                    "the SCORM package: %s"
                ) % str(e)
            )

        except zipfile.BadZipFile:

            raise UserError(
                _(
                    "The uploaded SCORM file is not a valid "
                    "ZIP file."
                )
            )

        finally:

            if temp_zip_path:

                try:

                    if os.path.exists(
                        temp_zip_path
                    ):

                        os.unlink(
                            temp_zip_path
                        )

                except Exception:

                    _logger.warning(
                        "Unable to remove temporary SCORM ZIP: %s",
                        temp_zip_path
                    )



    def extract_scorm_version(
        self,
        manifest_file
    ):

        tree = ET.parse(
            manifest_file
        )

        root = tree.getroot()

        schema_version_element = next(
            (
                el
                for el in root.iter()
                if self._strip_ns(
                    el.tag
                ).lower() == 'schemaversion'
            ),
            None
        )

        if (
            schema_version_element is None
            or not schema_version_element.text
        ):

            _logger.warning(
                "SCORM manifest does not contain "
                "schemaversion."
            )

            return 'scorm11'

        schema_version = (
            schema_version_element.text
            .strip()
            .lower()
        )

        if schema_version in (
            '1.1',
            '1.2'
        ):

            return 'scorm11'

        if (
            schema_version.startswith('2004')
            or '2004' in schema_version
        ):

            return 'scorm2004'

        # Compatibility fallback.
        return 'scorm11'