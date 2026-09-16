# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
import subprocess
import sys
import logging

_logger = logging.getLogger(__name__)


def _ensure_boto3():
    try:
        import boto3  # noqa
    except ImportError:
        _logger.warning("boto3 not found. Installing automatically...")
        try:
            subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'boto3'])
            _logger.info("boto3 installed successfully.")
        except Exception as e:
            _logger.error(
                "Automatic installation of boto3 failed: %s. "
                "Please install it manually: pip install boto3", e
            )
            raise


_ensure_boto3()
from . import models
from . import controllers
