from odoo import models, fields, api, _
import boto3
from botocore.exceptions import NoCredentialsError, PartialCredentialsError, ClientError
from odoo.exceptions import UserError

class ResConfigSettings(models.TransientModel):
    """
    Configure the access credentials
    """
    _inherit = 'res.config.settings'

    amazon_access_key = fields.Char(string='Amazon S3 Access Key', copy=False,
                                    config_parameter='amazon_s3_connector.amazon_access_key',
                                    help='Enter your Amazon S3 Access Key here.')
    amazon_secret_key = fields.Char(string='Amazon S3 Secret key',
                                    config_parameter='amazon_s3_connector.amazon_secret_key',
                                    help='Enter your Amazon S3 Secret Key here.')
    amazon_bucket_name = fields.Char(string='Folder ID',
                                     config_parameter='amazon_s3_connector.amazon_bucket_name',
                                     help='Enter the name of your Amazon S3 Bucket here.')
    is_amazon_connector = fields.Boolean(
        config_parameter='amazon_s3_connector.amazon_connector', default=False,
        help='Enable or disable the Amazon S3 connector.')
    
    def action_test_amazon_s3_connection(self):
        """
        Test the S3 connection using the provided credentials.
        """
        self.ensure_one()
        amazon_access_key = self.amazon_access_key
        amazon_secret_key = self.amazon_secret_key
        bucket_name = self.amazon_bucket_name

        if not amazon_access_key or not amazon_secret_key or not bucket_name:
            raise UserError(_("Amazon S3 credentials or bucket name are missing."))

        try:
            s3_client = boto3.client(
                's3',
                aws_access_key_id=amazon_access_key,
                aws_secret_access_key=amazon_secret_key
            )

            s3_client.head_bucket(Bucket=bucket_name)
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _("Success"),
                    'type': 'success',
                    'message': _("Connection Successful"),
                    'sticky': False,
                },
            }
        except Exception as e:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _("Error Occured"),
                    'type': 'danger',
                    # 'message': _("Unexpected error: %s") % str(e),
                    'message': _("Check Credentials Again"),
                    'sticky': False,
                },
            }
