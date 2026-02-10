# -*- coding: utf-8 -*-

def migrate(cr, version):
    """
    Drop the unique constraint on message_id to allow duplicate webhook deliveries.
    """
    # Drop the unique constraint if it exists
    cr.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_constraint 
                WHERE conname = 'whatsapp_message_message_id_unique'
            ) THEN
                ALTER TABLE whatsapp_message DROP CONSTRAINT whatsapp_message_message_id_unique;
            END IF;
        END $$;
    """)
