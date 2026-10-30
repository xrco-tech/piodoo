# -*- coding: utf-8 -*-
"""Use the town from CVs built on the CV page as the candidate's location."""


def migrate(cr, version):
    cr.execute("""
        UPDATE chat2work_candidate
           SET location = cv_data->>'town'
         WHERE COALESCE(location, '') = '' AND COALESCE(cv_data->>'town', '') <> ''
    """)
