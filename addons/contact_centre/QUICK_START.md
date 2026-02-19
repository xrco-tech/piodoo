# Contact Centre Module - Quick Start Guide

## 🚀 Getting Started

### Step 1: Create Module Structure

```bash
cd /Users/handsomerocks/piodoo/addons
mkdir -p contact_centre/{models,views,controllers,security,data,static/description}
```

### Step 2: Basic Files

#### `__manifest__.py`
```python
# -*- coding: utf-8 -*-
{
    'name': 'Contact Centre',
    'version': '18.0.1.0.0',
    'category': 'Customer Relationship Management',
    'summary': 'Unified SMS and WhatsApp Contact Centre',
    'description': """
Contact Centre Module
=====================
Unified contact centre for managing SMS and WhatsApp communications.
    """,
    'author': 'Your Company',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'contacts',
        'mail',
        'utm',
        'web',
    ],
    'data': [
        'security/ir.model.access.csv',
        'security/contact_centre_security.xml',
        'data/contact_centre_data.xml',
        'views/contact_centre_menus.xml',
        'views/contact_centre_contact_views.xml',
        'views/contact_centre_message_views.xml',
        'views/contact_centre_campaign_views.xml',
        'views/contact_centre_script_views.xml',
        'views/contact_centre_automation_views.xml',
        'views/whatsapp_config_views.xml',
        'views/sms_config_views.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
```

#### `__init__.py`
```python
# -*- coding: utf-8 -*-

from . import models
from . import controllers
```

#### `models/__init__.py`
```python
# -*- coding: utf-8 -*-

from . import contact_centre_contact
from . import contact_centre_message
from . import contact_centre_campaign
from . import contact_centre_script
from . import contact_centre_automation
from . import whatsapp_config
from . import sms_config
```

#### `controllers/__init__.py`
```python
# -*- coding: utf-8 -*-

from . import webhook_controller
```

### Step 3: Development Order

Follow this order for implementation:

1. **Phase 1**: Core Foundation
   - Create `contact_centre_contact.py` model
   - Create basic menu structure
   - Test contact extension

2. **Phase 2**: Messaging
   - Create `contact_centre_message.py` model
   - Create message views
   - Integrate with WhatsApp/SMS APIs

3. **Phase 3**: Campaigns
   - Create `contact_centre_campaign.py` model
   - Create campaign views
   - Implement campaign execution

4. **Phase 4**: Agent Tools
   - Create `contact_centre_script.py` model
   - Create script widget

5. **Phase 5**: Configuration
   - Create configuration models
   - Create settings views
   - Implement API integrations

## 🔌 Integration with Existing Modules

### WhatsApp Integration

If using `whatsapp_light`:
```python
# In contact_centre_message.py
def send_whatsapp_message(self):
    whatsapp_account = self.env['whatsapp.account'].search([], limit=1)
    whatsapp_account.send_message(
        recipient=self.contact_id.whatsapp_number,
        message=self.body_text,
    )
```

If using `comm_whatsapp`:
```python
# In contact_centre_message.py
def send_whatsapp_message(self):
    self.env['whatsapp.message'].send_whatsapp_message(
        recipient_phone=self.contact_id.whatsapp_number,
        message_text=self.body_text,
    )
```

### SMS Integration

If using `comm_sms`:
```python
# In contact_centre_message.py
def send_sms_message(self):
    self.env['sms.sms'].create({
        'number': self.contact_id.sms_number,
        'body': self.body_text,
    }).send()
```

### Chatbot Integration

Link to existing chatbot:
```python
# In contact_centre_automation.py
chatbot_id = fields.Many2one('whatsapp.chatbot', 'Chatbot Flow')
```

## 📋 Checklist

### Phase 1: Core Foundation
- [ ] Module structure created
- [ ] `__manifest__.py` configured
- [ ] `contact.centre.contact` model created
- [ ] Contact views created
- [ ] Menu structure created
- [ ] Security groups defined
- [ ] Module installs without errors

### Phase 2: Messaging
- [ ] `contact.centre.message` model created
- [ ] Message list views (inbound/outbound)
- [ ] Message form view
- [ ] Message kanban view (agent inbox)
- [ ] Send message functionality
- [ ] Reply functionality
- [ ] WhatsApp API integration
- [ ] SMS API integration
- [ ] Webhook handlers

### Phase 3: Campaigns
- [ ] `contact.centre.campaign` model created
- [ ] Campaign overview dashboard
- [ ] Campaign list/form views
- [ ] Campaign execution engine
- [ ] Campaign statistics
- [ ] Bulk send functionality

### Phase 4: Agent Tools
- [ ] `contact.centre.script` model created
- [ ] Script views
- [ ] Script widget (JavaScript)
- [ ] Context-aware script suggestions

### Phase 5: Configuration
- [ ] WhatsApp config model
- [ ] SMS config model
- [ ] Template models
- [ ] Settings views
- [ ] API sync functionality

## 🧪 Testing

### Manual Testing Checklist

1. **Contact Management**
   - [ ] Create contact with WhatsApp number
   - [ ] Create contact with SMS number
   - [ ] View contact message history
   - [ ] Assign agent to contact

2. **Messaging**
   - [ ] Send WhatsApp message
   - [ ] Send SMS message
   - [ ] Receive inbound message (webhook)
   - [ ] Reply to message
   - [ ] View conversation thread

3. **Campaigns**
   - [ ] Create outbound campaign
   - [ ] Schedule campaign
   - [ ] Execute campaign
   - [ ] View campaign statistics

4. **Agent Tools**
   - [ ] Create script
   - [ ] View script in message form
   - [ ] Use script suggestion

5. **Configuration**
   - [ ] Configure WhatsApp credentials
   - [ ] Sync WhatsApp templates
   - [ ] Configure SMS provider
   - [ ] Test SMS sending

## 📚 Resources

- [Implementation Plan](./IMPLEMENTATION_PLAN.md)
- [Data Model](./DATA_MODEL.md)
- [Odoo 18 Documentation](https://www.odoo.com/documentation/18.0/)
- [Meta Cloud API](https://developers.facebook.com/docs/whatsapp/cloud-api)
- [InfoBip SMS API](https://www.infobip.com/docs/api)
