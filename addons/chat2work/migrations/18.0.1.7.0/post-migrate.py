# -*- coding: utf-8 -*-
"""Place existing candidates on the new pipeline (everyone starts at New)."""


def migrate(cr, version):
    cr.execute("""
        UPDATE chat2work_candidate SET stage = 'cv_ready'
         WHERE stage = 'new' AND cv_state IN ('uploaded', 'built')
    """)
    cr.execute("""
        UPDATE chat2work_candidate c SET stage = 'help'
         WHERE stage = 'new'
           AND (cv_state = 'help_requested'
                OR EXISTS (SELECT 1 FROM chat2work_callback_request r
                            WHERE r.candidate_id = c.id AND r.state IN ('new', 'in_progress')))
    """)
