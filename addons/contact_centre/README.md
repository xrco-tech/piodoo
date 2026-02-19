# Contact Centre Module

Unified SMS and WhatsApp Contact Centre for Odoo 18

## 📚 Documentation

- **[Implementation Plan](./IMPLEMENTATION_PLAN.md)** - Comprehensive implementation guide with phases, models, and specifications
- **[Data Model](./DATA_MODEL.md)** - Entity relationships and data structure
- **[Quick Start Guide](./QUICK_START.md)** - Getting started checklist and development order

## 🎯 Overview

This module provides a unified contact centre solution for managing SMS and WhatsApp communications in Odoo 18. It consolidates messaging, campaigns, agent tools, and automation into a single interface.

## ✨ Features

- **Unified Messaging**: Single interface for SMS and WhatsApp
- **Contact Management**: Enhanced contacts with communication history
- **Campaign Management**: Inbound and outbound campaigns
- **Agent Tools**: Dynamic scripts for conversation guidance
- **Automation**: Chatbot flows and automated replies
- **Template Management**: WhatsApp and SMS templates
- **Configuration**: API settings for WhatsApp (Meta) and SMS (InfoBip)

## 🏗️ Module Structure

```
contact_centre/
├── __manifest__.py              # Module manifest
├── __init__.py                  # Module initialization
├── models/                      # Python models
│   ├── contact_centre_contact.py
│   ├── contact_centre_message.py
│   ├── contact_centre_campaign.py
│   ├── contact_centre_script.py
│   ├── contact_centre_automation.py
│   ├── whatsapp_config.py
│   └── sms_config.py
├── views/                       # XML views
│   ├── contact_centre_menus.xml
│   ├── contact_centre_contact_views.xml
│   ├── contact_centre_message_views.xml
│   ├── contact_centre_campaign_views.xml
│   ├── contact_centre_script_views.xml
│   ├── contact_centre_automation_views.xml
│   ├── whatsapp_config_views.xml
│   └── sms_config_views.xml
├── controllers/                 # HTTP controllers
│   └── webhook_controller.py
├── security/                    # Access control
│   ├── ir.model.access.csv
│   └── contact_centre_security.xml
└── data/                        # Initial data
    └── contact_centre_data.xml
```

## 🚀 Installation

1. Copy the module to your Odoo addons directory:
   ```bash
   cp -r contact_centre /path/to/odoo/addons/
   ```

2. Update the app list in Odoo:
   - Go to Apps menu
   - Click "Update Apps List"
   - Search for "Contact Centre"
   - Click Install

## 📋 Current Status

### ✅ Completed
- Module structure and scaffolding
- Basic contact model extension
- Menu structure
- Security groups
- Placeholder models and views

### 🚧 In Progress / TODO
- Message model implementation
- Campaign execution engine
- WhatsApp API integration
- SMS API integration
- Webhook handlers
- Agent script widget
- Dashboard views
- Template management
- Automation engine

## 🔌 Integration

This module is designed to work with existing WhatsApp and SMS modules:

- **WhatsApp**: Can integrate with `whatsapp_light`, `comm_whatsapp`, or `whatsapp_custom`
- **SMS**: Can integrate with `comm_sms` or custom SMS providers
- **Chatbots**: Links to existing `whatsapp.chatbot` models

## 📖 Development

See [QUICK_START.md](./QUICK_START.md) for development guidelines and checklists.

## 📝 License

LGPL-3

## 👥 Author

Your Company
