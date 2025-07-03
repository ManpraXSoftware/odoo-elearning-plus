# -*- coding: utf-8 -*-
{
    'name': 'eLearning with Scorm',
    'version': '17.0.1.5',
    'sequence': 10,
    'summary': 'Manage and publish an eLearning platform',
    'icon': '/website_scorm_elearning/static/description/icon.svg',
    'website': 'https://www.manprax.com',
    'author': 'ManpraX Software LLP',
    'category': 'Website/eLearning',
    'description': """
Create Online Courses Using Scorm
""",
    'depends': [
        'website_slides',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/res_config_settings_views.xml',
        'views/slide_slide_views.xml',
        'views/templates.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'website_scorm_elearning/static/src/js/slides_course.js',
            'website_scorm_elearning/static/src/js/slides_course_fullscreen_player.js',
            'website_scorm_elearning/static/src/xml/website_slides_fullscreen.xml',
        ],
        'web.assets_backend': [
            'website_scorm_elearning/static/src/scss/slide_slide.scss',
        ]
    },
    'external_dependencies': {'python': ['boto3']},
    'images': ["static/description/images/scorm_banner.png"],
    'installable': True,
    'application': True,
    'license': 'AGPL-3',
}
