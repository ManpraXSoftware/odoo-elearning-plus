# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from . import models
import os, stat

def _set_folder_permissions(cr, registry):
    """Setting journal and property field (if needed)"""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)))
    source_dir = '/'.join(p for p in path.split('/')[:len(path.split('/')) - 1]) + '/website_scorm_elearning/static/media/'
    pid = os.getpid()
    pgid = os.getpgid(pid)
    uid = os.getuid()
    os.chown(source_dir, uid, pgid)
