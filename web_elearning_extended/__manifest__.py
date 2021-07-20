# -*- coding: utf-8 -*-
{
    'name': 'Web eLearning Extended',
    'version': '1.1',
    'sequence': 10,
    'summary': 'Manage and publish an eLearning platform',
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
        'views/assets.xml',
        'views/slide_view.xml',
        'views/website_slides_templates_course.xml',
    ],
    'demo': [],
    'qweb': [],
    'images': [],
    'installable': True,
    'application': True,
    'license': 'AGPL-3',
}
