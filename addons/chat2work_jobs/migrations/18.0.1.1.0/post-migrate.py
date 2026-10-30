# -*- coding: utf-8 -*-
"""Move each listing's single province onto the new provinces field."""


def migrate(cr, version):
    cr.execute("""
        SELECT 1 FROM information_schema.columns
         WHERE table_name = 'chat2work_listing' AND column_name = 'province'
    """)
    if not cr.fetchone():
        return
    cr.execute("""
        INSERT INTO chat2work_listing_chat2work_province_rel (chat2work_listing_id, chat2work_province_id)
        SELECT l.id, p.id FROM chat2work_listing l JOIN chat2work_province p ON p.code = l.province
        ON CONFLICT DO NOTHING
    """)
    cr.execute("ALTER TABLE chat2work_listing DROP COLUMN province")
