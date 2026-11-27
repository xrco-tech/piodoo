# -*- coding: utf-8 -*-
"""The menu now shows icon.svg, which moves, where it showed icon.png.

A Library doc remembers its page icon by the menu's icon, so a doc that
carries this app's icon is pointed at the new file. The Library may not be
installed here.
"""
OLD = 'comm_billing_core,static/description/icon.png'
NEW = 'comm_billing_core,static/description/icon.svg'


def migrate(cr, version):
    cr.execute("SELECT 1 FROM information_schema.columns WHERE table_name = 'sediba_doc' AND column_name = 'icon_app'")
    if cr.fetchone():
        cr.execute("UPDATE sediba_doc SET icon_app = %s WHERE icon_app = %s", (NEW, OLD))
