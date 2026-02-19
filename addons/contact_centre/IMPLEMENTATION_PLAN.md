# Contact Centre Module - Implementation Plan
## Odoo 18 - SMS & WhatsApp Contact Centre

---

## 📋 Table of Contents

1. [Overview](#overview)
2. [Architecture & Dependencies](#architecture--dependencies)
3. [Phase 1: Core Foundation](#phase-1-core-foundation)
4. [Phase 2: Messaging](#phase-2-messaging)
5. [Phase 3: Campaigns](#phase-3-campaigns)
6. [Phase 4: Agent Tools](#phase-4-agent-tools)
7. [Phase 5: Configuration](#phase-5-configuration)
8. [Phase 6: Advanced Features](#phase-6-advanced-features)
9. [Technical Specifications](#technical-specifications)
10. [Testing Strategy](#testing-strategy)

---

## 🎯 Overview

### Module Purpose
A unified contact centre module that enables businesses to manage SMS and WhatsApp communications with contacts through a single interface, supporting both inbound customer service and outbound marketing campaigns.

### Key Features
- **Unified Messaging**: Single interface for SMS and WhatsApp
- **Contact Management**: Enhanced contact profiles with communication history
- **Campaign Management**: Create and manage inbound/outbound campaigns
- **Agent Tools**: Dynamic scripts and conversation guidance
- **Automation**: Chatbot flows and automated replies
- **Integration**: Meta Cloud API (WhatsApp) and InfoBip (SMS)

---

## 🏗️ Architecture & Dependencies

### Module Structure
```
contact_centre/
├── __init__.py
├── __manifest__.py
├── models/
│   ├── __init__.py
│   ├── contact_centre_contact.py      # Enhanced contact model
│   ├── contact_centre_message.py       # Unified message model
│   ├── contact_centre_campaign.py     # Campaign management
│   ├── contact_centre_script.py        # Agent scripts
│   ├── contact_centre_automation.py    # Automated replies/chatbots
│   ├── whatsapp_config.py              # WhatsApp settings
│   └── sms_config.py                   # SMS settings
├── views/
│   ├── contact_centre_menus.xml
│   ├── contact_centre_contact_views.xml
│   ├── contact_centre_message_views.xml
│   ├── contact_centre_campaign_views.xml
│   ├── contact_centre_script_views.xml
│   ├── contact_centre_automation_views.xml
│   ├── whatsapp_config_views.xml
│   └── sms_config_views.xml
├── controllers/
│   ├── __init__.py
│   ├── webhook_controller.py           # Unified webhook handler
│   └── api_controller.py               # External API endpoints
├── security/
│   ├── ir.model.access.csv
│   └── contact_centre_security.xml
├── data/
│   ├── contact_centre_data.xml
│   └── ir_sequence_data.xml
└── static/
    └── description/
        └── icon.png
```

### Dependencies
```python
'depends': [
    'base',
    'contacts',           # res.partner extension
    'mail',               # Messaging framework
    'utm',                # Campaign tracking
    'web',                # Web framework
    'portal',             # Portal access (optional)
]
```

### Integration Points
- **WhatsApp**: Leverage existing `whatsapp_light` or `comm_whatsapp` modules
- **SMS**: Leverage existing `comm_sms` module
- **Chatbots**: Extend `whatsapp_light_chatbot` functionality

---

## 📦 Phase 1: Core Foundation

### 1.1 Module Setup
**Files**: `__manifest__.py`, `__init__.py`

**Tasks**:
- Create module manifest with dependencies
- Set up basic module structure
- Configure security groups

**Deliverables**:
- ✅ Module installable
- ✅ Security groups: `contact_centre.user`, `contact_centre.manager`, `contact_centre.admin`

### 1.2 Enhanced Contact Model
**File**: `models/contact_centre_contact.py`

**Model**: `contact.centre.contact` (extends `res.partner`)

**Key Fields**:
```python
# Communication Channels
whatsapp_number = fields.Char('WhatsApp Number', index=True)
sms_number = fields.Char('SMS Number', index=True)
preferred_channel = fields.Selection([
    ('whatsapp', 'WhatsApp'),
    ('sms', 'SMS'),
    ('email', 'Email'),
], 'Preferred Channel')

# Communication History
whatsapp_message_count = fields.Integer('WhatsApp Messages', compute='_compute_message_counts')
sms_message_count = fields.Integer('SMS Messages', compute='_compute_message_counts')
last_whatsapp_message = fields.Datetime('Last WhatsApp')
last_sms_message = fields.Datetime('Last SMS')

# Contact Centre Specific
contact_centre_tags = fields.Many2many('contact.centre.tag', 'Contact Tags')
assigned_agent_id = fields.Many2one('res.users', 'Assigned Agent')
contact_score = fields.Integer('Contact Score', help='Engagement score')
opt_in_whatsapp = fields.Boolean('WhatsApp Opt-In')
opt_in_sms = fields.Boolean('SMS Opt-In')
opt_out_date = fields.Datetime('Opt-Out Date')

# Related Records
whatsapp_message_ids = fields.One2many('contact.centre.message', 'contact_id', domain=[('channel', '=', 'whatsapp')])
sms_message_ids = fields.One2many('contact.centre.message', 'contact_id', domain=[('channel', '=', 'sms')])
campaign_ids = fields.Many2many('contact.centre.campaign', 'Campaigns')
```

**Methods**:
- `_compute_message_counts()`: Count messages per channel
- `send_whatsapp_message()`: Send WhatsApp message
- `send_sms_message()`: Send SMS message
- `get_conversation_history()`: Get unified conversation view

### 1.3 Menu Structure
**File**: `views/contact_centre_menus.xml`

**Menu Hierarchy**:
```xml
<menuitem id="contact_centre_main" name="Contact Centre" sequence="10"/>
  <menuitem id="contact_centre_overview" name="Overview" parent="contact_centre_main" action="action_contact_centre_overview"/>
  <menuitem id="contact_centre_contacts" name="Contacts" parent="contact_centre_main" action="action_contact_centre_contact"/>
  <menuitem id="contact_centre_messages" name="Messages" parent="contact_centre_main"/>
    <menuitem id="contact_centre_messages_inbound" name="Inbound" parent="contact_centre_messages"/>
      <menuitem id="contact_centre_messages_inbound_all" name="All" parent="contact_centre_messages_inbound" action="action_contact_centre_message_inbound"/>
      <menuitem id="contact_centre_messages_inbound_whatsapp" name="WhatsApp" parent="contact_centre_messages_inbound" action="action_contact_centre_message_inbound_whatsapp"/>
      <menuitem id="contact_centre_messages_inbound_sms" name="SMS" parent="contact_centre_messages_inbound" action="action_contact_centre_message_inbound_sms"/>
    <menuitem id="contact_centre_messages_outbound" name="Outbound" parent="contact_centre_messages"/>
      <menuitem id="contact_centre_messages_outbound_all" name="All" parent="contact_centre_messages_outbound" action="action_contact_centre_message_outbound"/>
      <menuitem id="contact_centre_messages_outbound_whatsapp" name="WhatsApp" parent="contact_centre_messages_outbound" action="action_contact_centre_message_outbound_whatsapp"/>
      <menuitem id="contact_centre_messages_outbound_sms" name="SMS" parent="contact_centre_messages_outbound" action="action_contact_centre_message_outbound_sms"/>
  <menuitem id="contact_centre_campaigns" name="Campaigns" parent="contact_centre_main"/>
    <menuitem id="contact_centre_campaigns_overview" name="Overview" parent="contact_centre_campaigns" action="action_contact_centre_campaign_overview"/>
    <menuitem id="contact_centre_campaigns_inbound" name="Inbound" parent="contact_centre_campaigns"/>
      <!-- Similar submenu structure -->
    <menuitem id="contact_centre_campaigns_outbound" name="Outbound" parent="contact_centre_campaigns"/>
      <!-- Similar submenu structure -->
  <menuitem id="contact_centre_config" name="Configuration" parent="contact_centre_main"/>
    <!-- Configuration menus -->
```

**Deliverables**:
- ✅ Complete menu structure
- ✅ All menu items linked to actions

---

## 💬 Phase 2: Messaging

### 2.1 Unified Message Model
**File**: `models/contact_centre_message.py`

**Model**: `contact.centre.message`

**Key Fields**:
```python
# Basic Info
name = fields.Char('Message ID', required=True, index=True)
contact_id = fields.Many2one('contact.centre.contact', 'Contact', required=True, index=True)
channel = fields.Selection([
    ('whatsapp', 'WhatsApp'),
    ('sms', 'SMS'),
], 'Channel', required=True, index=True)
direction = fields.Selection([
    ('inbound', 'Inbound'),
    ('outbound', 'Outbound'),
], 'Direction', required=True, index=True)

# Content
message_type = fields.Selection([
    ('text', 'Text'),
    ('image', 'Image'),
    ('video', 'Video'),
    ('audio', 'Audio'),
    ('document', 'Document'),
    ('location', 'Location'),
    ('template', 'Template'),
    ('interactive', 'Interactive'),
], 'Message Type', default='text')
body_text = fields.Text('Message Body')
body_html = fields.Html('Formatted Body', compute='_compute_body_html')
preview_html = fields.Html('Preview', compute='_compute_preview_html')

# Status & Tracking
status = fields.Selection([
    ('pending', 'Pending'),
    ('sent', 'Sent'),
    ('delivered', 'Delivered'),
    ('read', 'Read'),
    ('failed', 'Failed'),
], 'Status', default='pending')
status_timestamp = fields.Datetime('Status Time')
error_message = fields.Text('Error')

# Metadata
external_message_id = fields.Char('External Message ID', index=True)  # WhatsApp/SMS provider ID
phone_number_id = fields.Char('Phone Number ID')  # WhatsApp phone number ID
campaign_id = fields.Many2one('contact.centre.campaign', 'Campaign')
template_id = fields.Many2one('contact.centre.template', 'Template')
assigned_agent_id = fields.Many2one('res.users', 'Assigned Agent')

# Media
attachment_ids = fields.Many2many('ir.attachment', 'Message Attachments')
media_url = fields.Char('Media URL')
media_type = fields.Char('Media Type')

# Threading
parent_message_id = fields.Many2one('contact.centre.message', 'Parent Message')
reply_to_message_id = fields.Many2one('contact.centre.message', 'Reply To')
thread_id = fields.Char('Thread ID', index=True)  # For conversation threading

# Timestamps
message_timestamp = fields.Datetime('Message Time', required=True, index=True)
create_date = fields.Datetime('Created', readonly=True)
```

**Methods**:
- `send()`: Send message via appropriate channel
- `_compute_body_html()`: Format message with markdown
- `_compute_preview_html()`: Generate WhatsApp-style preview
- `mark_as_read()`: Mark message as read
- `reply()`: Create reply message
- `forward()`: Forward message to another contact

### 2.2 Message Views
**File**: `views/contact_centre_message_views.xml`

**Views Needed**:
1. **List View** (Inbound/Outbound):
   - Channel badge (WhatsApp/SMS)
   - Direction badge (Inbound/Outbound)
   - Contact name
   - Message preview
   - Status
   - Timestamp
   - Filters: Channel, Direction, Status, Date range
   - Group by: Channel, Direction, Status, Date

2. **Form View**:
   - Header: Status, Channel, Direction badges
   - Contact info card
   - Message content (preview + raw)
   - Thread view (conversation history)
   - Media attachments
   - Reply/Forward actions
   - Campaign/Template info

3. **Kanban View** (Agent Inbox):
   - Group by: Unassigned, Assigned to Me, Assigned to Others
   - Show: Contact, Last message preview, Channel, Time since last message
   - Quick actions: Assign, Reply, Mark as Read

### 2.3 Message Actions
**Methods**:
- `action_send_message()`: Send message wizard
- `action_reply()`: Quick reply
- `action_assign_agent()`: Assign to agent
- `action_mark_read()`: Mark as read
- `action_create_ticket()`: Create helpdesk ticket (if module exists)

**Deliverables**:
- ✅ Unified message model
- ✅ List/Form/Kanban views
- ✅ Send/Reply functionality
- ✅ Integration with WhatsApp/SMS APIs

---

## 📢 Phase 3: Campaigns

### 3.1 Campaign Model
**File**: `models/contact_centre_campaign.py`

**Model**: `contact.centre.campaign`

**Key Fields**:
```python
name = fields.Char('Campaign Name', required=True)
campaign_type = fields.Selection([
    ('inbound', 'Inbound'),
    ('outbound', 'Outbound'),
], 'Type', required=True)
channel = fields.Selection([
    ('whatsapp', 'WhatsApp'),
    ('sms', 'SMS'),
    ('both', 'Both'),
], 'Channel', required=True)

# Targeting
contact_domain = fields.Char('Contact Domain', help='Domain to filter contacts')
contact_ids = fields.Many2many('contact.centre.contact', 'Campaign Contacts')
contact_count = fields.Integer('Contact Count', compute='_compute_contact_count')

# Content
template_id = fields.Many2one('contact.centre.template', 'Template')
message_body = fields.Text('Message Body')
use_template = fields.Boolean('Use Template')

# Scheduling
state = fields.Selection([
    ('draft', 'Draft'),
    ('scheduled', 'Scheduled'),
    ('running', 'Running'),
    ('paused', 'Paused'),
    ('completed', 'Completed'),
    ('cancelled', 'Cancelled'),
], 'State', default='draft')
scheduled_date = fields.Datetime('Scheduled Date')
start_date = fields.Datetime('Start Date')
end_date = fields.Datetime('End Date')

# Statistics
sent_count = fields.Integer('Sent', compute='_compute_statistics')
delivered_count = fields.Integer('Delivered', compute='_compute_statistics')
read_count = fields.Integer('Read', compute='_compute_statistics')
failed_count = fields.Integer('Failed', compute='_compute_statistics')
response_count = fields.Integer('Responses', compute='_compute_statistics')
response_rate = fields.Float('Response Rate %', compute='_compute_statistics')

# Related
message_ids = fields.One2many('contact.centre.message', 'campaign_id', 'Messages')
```

**Methods**:
- `action_start()`: Start campaign
- `action_pause()`: Pause campaign
- `action_resume()`: Resume campaign
- `action_cancel()`: Cancel campaign
- `_compute_statistics()`: Calculate campaign metrics
- `send_to_contacts()`: Send campaign messages
- `schedule_send()`: Schedule campaign send

### 3.2 Campaign Views
**File**: `views/contact_centre_campaign_views.xml`

**Views**:
1. **Overview Dashboard** (Kanban):
   - Groups: Draft, Scheduled, Running, Completed
   - Show: Name, Channel, Contact count, Statistics
   - Quick actions: Start, Pause, View Details

2. **List View**:
   - Campaign name
   - Type (Inbound/Outbound)
   - Channel
   - State
   - Statistics
   - Dates

3. **Form View**:
   - Campaign details
   - Targeting (domain builder)
   - Content editor
   - Scheduling
   - Statistics dashboard
   - Message list

**Deliverables**:
- ✅ Campaign model
- ✅ Campaign management views
- ✅ Campaign execution engine
- ✅ Statistics and reporting

---

## 👤 Phase 4: Agent Tools

### 4.1 Dynamic Scripts Model
**File**: `models/contact_centre_script.py`

**Model**: `contact.centre.script`

**Key Fields**:
```python
name = fields.Char('Script Name', required=True)
description = fields.Text('Description')
script_type = fields.Selection([
    ('greeting', 'Greeting'),
    ('product_info', 'Product Information'),
    ('pricing', 'Pricing'),
    ('support', 'Support'),
    ('closing', 'Closing'),
    ('custom', 'Custom'),
], 'Script Type')

# Content
content_html = fields.Html('Script Content')
content_text = fields.Text('Plain Text Version')

# Conditions
trigger_keywords = fields.Char('Trigger Keywords', help='Comma-separated keywords')
contact_tags = fields.Many2many('contact.centre.tag', 'Script Tags')
campaign_ids = fields.Many2many('contact.centre.campaign', 'Script Campaigns')

# Usage
usage_count = fields.Integer('Usage Count', compute='_compute_usage_stats')
last_used = fields.Datetime('Last Used')

# Organization
sequence = fields.Integer('Sequence')
category_id = fields.Many2one('contact.centre.script.category', 'Category')
```

**Model**: `contact.centre.script.category`
- Categories for organizing scripts

**Methods**:
- `get_relevant_scripts()`: Get scripts based on context
- `increment_usage()`: Track script usage

### 4.2 Script Views
**File**: `views/contact_centre_script_views.xml`

**Views**:
1. **List View**: Scripts with categories
2. **Form View**: Script editor with preview
3. **Widget**: Floating script panel in message form (JavaScript)

**Deliverables**:
- ✅ Script model and management
- ✅ Script widget for agents
- ✅ Context-aware script suggestions

---

## ⚙️ Phase 5: Configuration

### 5.1 Automated Replies (Chatbots)
**File**: `models/contact_centre_automation.py`

**Model**: `contact.centre.automation` (extends chatbot functionality)

**Key Fields**:
```python
name = fields.Char('Automation Name', required=True)
channel = fields.Selection([
    ('whatsapp', 'WhatsApp'),
    ('sms', 'SMS'),
    ('both', 'Both'),
], 'Channel', required=True)
automation_type = fields.Selection([
    ('chatbot', 'Chatbot Flow'),
    ('auto_reply', 'Auto Reply'),
    ('keyword_response', 'Keyword Response'),
], 'Type', required=True)

# Chatbot Integration
chatbot_id = fields.Many2one('whatsapp.chatbot', 'Chatbot Flow')  # Link to existing chatbot

# Auto Reply Rules
trigger_type = fields.Selection([
    ('always', 'Always'),
    ('business_hours', 'Business Hours Only'),
    ('after_hours', 'After Hours Only'),
    ('keyword', 'Keyword Match'),
], 'Trigger Type')
trigger_keywords = fields.Char('Trigger Keywords')
response_message = fields.Text('Response Message')
response_template_id = fields.Many2one('contact.centre.template', 'Response Template')

# Settings
active = fields.Boolean('Active', default=True)
priority = fields.Integer('Priority', help='Lower number = higher priority')
```

**Methods**:
- `evaluate_trigger()`: Check if automation should trigger
- `execute()`: Execute automation
- `get_response()`: Get response message

### 5.2 WhatsApp Configuration
**File**: `models/whatsapp_config.py`

**Model**: `contact.centre.whatsapp.config`

**Key Fields**:
```python
name = fields.Char('Configuration Name', required=True)
account_id = fields.Char('Meta Business Account ID', required=True)
phone_number_id = fields.Char('Phone Number ID', required=True)
access_token = fields.Char('Access Token', required=True)
webhook_verify_token = fields.Char('Webhook Verify Token')
webhook_url = fields.Char('Webhook URL', compute='_compute_webhook_url')

# Template Management
template_ids = fields.One2many('contact.centre.whatsapp.template', 'config_id', 'Templates')
last_template_sync = fields.Datetime('Last Template Sync')

# Flow Management
flow_ids = fields.One2many('contact.centre.whatsapp.flow', 'config_id', 'Flows')
last_flow_sync = fields.Datetime('Last Flow Sync')

# Settings
api_version = fields.Char('API Version', default='v18.0')
```

**Methods**:
- `sync_templates()`: Sync templates from Meta
- `sync_flows()`: Sync flows from Meta
- `test_connection()`: Test API connection
- `send_message()`: Send WhatsApp message

### 5.3 SMS Configuration
**File**: `models/sms_config.py`

**Model**: `contact.centre.sms.config`

**Key Fields**:
```python
name = fields.Char('Configuration Name', required=True)
provider = fields.Selection([
    ('infobip', 'InfoBip'),
    ('twilio', 'Twilio'),
    ('custom', 'Custom API'),
], 'Provider', required=True)

# InfoBip Settings
infobip_api_key = fields.Char('API Key')
infobip_base_url = fields.Char('Base URL', default='https://api.infobip.com')
infobip_sender_id = fields.Char('Sender ID')

# Twilio Settings
twilio_account_sid = fields.Char('Account SID')
twilio_auth_token = fields.Char('Auth Token')
twilio_phone_number = fields.Char('Phone Number')

# Custom API Settings
custom_api_url = fields.Char('API Endpoint')
custom_api_key = fields.Char('API Key')
custom_api_method = fields.Selection([
    ('POST', 'POST'),
    ('GET', 'GET'),
], 'HTTP Method', default='POST')
```

**Methods**:
- `send_sms()`: Send SMS via configured provider
- `test_connection()`: Test SMS API connection

### 5.4 Template Models
**Models**:
- `contact.centre.template`: Base template model
- `contact.centre.whatsapp.template`: WhatsApp-specific templates
- `contact.centre.sms.template`: SMS templates

**Deliverables**:
- ✅ Configuration models
- ✅ Settings views
- ✅ Template management
- ✅ API integration

---

## 🚀 Phase 6: Advanced Features

### 6.1 Overview Dashboard
**File**: `views/contact_centre_overview_views.xml`

**Dashboard Components**:
- **Statistics Cards**: Total messages, Unread, Response rate
- **Channel Breakdown**: WhatsApp vs SMS
- **Recent Activity**: Latest messages
- **Agent Performance**: Messages per agent
- **Campaign Performance**: Active campaigns
- **Response Time Metrics**: Average response time

### 6.2 Conversation Threading
- Group messages by thread_id
- Show conversation view in message form
- Thread-based kanban view

### 6.3 WhatsApp Calls Integration (Future)
- Link to existing `whatsapp.call.log` model
- Show calls in contact history
- Call controls in contact form

### 6.4 Reporting & Analytics
- Message volume reports
- Response time reports
- Campaign performance reports
- Agent performance reports

---

## 🔧 Technical Specifications

### API Integration

#### WhatsApp (Meta Cloud API)
```python
# Endpoints to implement:
- POST /v18.0/{phone-number-id}/messages  # Send message
- GET /v18.0/{phone-number-id}/message_templates  # List templates
- GET /v18.0/{business-account-id}/flows  # List flows
- Webhook: /contact_centre/webhook/whatsapp  # Receive messages
```

#### SMS (InfoBip)
```python
# Endpoints to implement:
- POST /sms/2/text/advanced  # Send SMS
- GET /sms/2/reports  # Get delivery reports
- Webhook: /contact_centre/webhook/sms  # Receive SMS
```

### Security
- **Groups**:
  - `contact_centre.user`: Can view/send messages
  - `contact_centre.agent`: Can assign, use scripts
  - `contact_centre.manager`: Can manage campaigns
  - `contact_centre.admin`: Full access + configuration

### Performance Considerations
- Index on: `contact_id`, `channel`, `direction`, `status`, `message_timestamp`
- Use `read_group` for statistics
- Cache template sync results
- Background jobs for bulk sends

---

## ✅ Testing Strategy

### Unit Tests
- Message model methods
- Campaign execution
- Answer matching logic
- Template rendering

### Integration Tests
- WhatsApp API integration
- SMS API integration
- Webhook handling
- Campaign sending

### User Acceptance Tests
- Agent workflow
- Campaign creation and execution
- Script usage
- Configuration setup

---

## 📅 Implementation Timeline

### Phase 1: Core Foundation (Week 1-2)
- Module setup
- Contact model
- Menu structure

### Phase 2: Messaging (Week 3-4)
- Message model
- Views and actions
- API integration

### Phase 3: Campaigns (Week 5-6)
- Campaign model
- Campaign execution
- Statistics

### Phase 4: Agent Tools (Week 7)
- Scripts model
- Script widget

### Phase 5: Configuration (Week 8)
- Settings models
- Template management
- API configuration

### Phase 6: Polish & Testing (Week 9-10)
- Dashboard
- Reporting
- Testing
- Documentation

---

## 📝 Next Steps

1. **Review this plan** with stakeholders
2. **Set up development environment**
3. **Create module scaffold** (`contact_centre/`)
4. **Start Phase 1** implementation
5. **Iterate** based on feedback

---

## 🔗 Related Documentation

- [Odoo 18 Developer Documentation](https://www.odoo.com/documentation/18.0/)
- [Meta Cloud API Documentation](https://developers.facebook.com/docs/whatsapp/cloud-api)
- [InfoBip SMS API Documentation](https://www.infobip.com/docs/api)
