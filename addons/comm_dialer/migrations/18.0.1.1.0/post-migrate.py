# -*- coding: utf-8 -*-
"""Backfill comm.voip.call.agent_user_id from the dialer agent session so
existing dialer calls stay visible to their agent under the own-calls rule."""


def migrate(cr, version):
    cr.execute("""
        UPDATE comm_voip_call c
           SET agent_user_id = s.user_id
          FROM comm_dialer_agent_session s
         WHERE c.dialer_agent_session_id = s.id
           AND c.agent_user_id IS NULL
    """)
