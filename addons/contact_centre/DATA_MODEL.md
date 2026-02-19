# Contact Centre - Data Model Relationships

## Entity Relationship Diagram

```
┌─────────────────────┐
│  res.partner        │
│  (Base Contact)     │
└──────────┬──────────┘
           │
           │ extends
           │
┌──────────▼──────────────────────────────────────────┐
│  contact.centre.contact                             │
│  - whatsapp_number                                  │
│  - sms_number                                       │
│  - preferred_channel                                │
│  - assigned_agent_id                                │
│  - opt_in_whatsapp, opt_in_sms                     │
└──────────┬──────────────────────────────────────────┘
           │
           │ 1:N
           │
┌──────────▼──────────────────────────────────────────┐
│  contact.centre.message                             │
│  - contact_id (M2O)                                 │
│  - channel (whatsapp/sms)                           │
│  - direction (inbound/outbound)                     │
│  - message_type, body_text, body_html               │
│  - status, external_message_id                      │
│  - campaign_id (M2O)                                │
│  - template_id (M2O)                                │
│  - assigned_agent_id (M2O)                          │
│  - parent_message_id (M2O)                          │
│  - thread_id                                        │
└──────────┬──────────────────────────────────────────┘
           │
           │ N:1
           │
┌──────────▼──────────────────────────────────────────┐
│  contact.centre.campaign                            │
│  - campaign_type (inbound/outbound)                 │
│  - channel (whatsapp/sms/both)                      │
│  - contact_ids (M2M)                                │
│  - template_id (M2O)                                │
│  - state, scheduled_date                            │
│  - statistics (sent, delivered, read, etc.)        │
└──────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────┐
│  contact.centre.script                               │
│  - script_type                                       │
│  - content_html, content_text                        │
│  - trigger_keywords                                  │
│  - category_id (M2O)                                 │
└──────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────┐
│  contact.centre.automation                           │
│  - channel                                           │
│  - automation_type (chatbot/auto_reply/keyword)     │
│  - chatbot_id (M2O → whatsapp.chatbot)              │
│  - trigger_type, trigger_keywords                    │
│  - response_message                                  │
└──────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────┐
│  contact.centre.whatsapp.config                      │
│  - account_id, phone_number_id                       │
│  - access_token                                      │
│  - template_ids (O2M)                               │
│  - flow_ids (O2M)                                   │
└──────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────┐
│  contact.centre.sms.config                           │
│  - provider (infobip/twilio/custom)                  │
│  - provider-specific credentials                     │
└──────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────┐
│  contact.centre.template                             │
│  - name, channel                                     │
│  - body_text, body_html                              │
│  - variable_ids (O2M)                                │
└──────────────────────────────────────────────────────┘
```

## Key Relationships

### Contact → Messages
- One contact can have many messages (WhatsApp and SMS)
- Messages are linked via `contact_id`
- Filtered by `channel` and `direction`

### Campaign → Messages
- One campaign can send many messages
- Messages track which campaign they belong to
- Used for campaign statistics

### Contact → Campaigns
- Many-to-many relationship
- Contacts can be in multiple campaigns
- Campaigns can target multiple contacts

### Automation → Chatbot
- Links to existing `whatsapp.chatbot` model
- Allows reuse of existing chatbot flows

### Templates
- Base template model (`contact.centre.template`)
- Channel-specific templates (`whatsapp.template`, `sms.template`)
- Templates can be used in campaigns and automated replies

## Indexes for Performance

```python
# contact.centre.message
_indexes = [
    ('contact_id', 'channel', 'direction'),
    ('status', 'message_timestamp'),
    ('thread_id',),
    ('external_message_id',),
    ('campaign_id',),
]

# contact.centre.contact
_indexes = [
    ('whatsapp_number',),
    ('sms_number',),
    ('assigned_agent_id',),
]
```
