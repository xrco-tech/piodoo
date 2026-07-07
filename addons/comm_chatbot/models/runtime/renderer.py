# -*- coding: utf-8 -*-
"""The renderer — canonical step → channel-appropriate payload.

Public entry point: `RendererService.render(env, step, conversation)`
Returns a `RenderedPayload` (dict) that the channel adapter consumes.

Stages:
  1. LANGUAGE       pick body translation
  2. OVERRIDE       apply channel_override
  3. SUBSTITUTION   safe Mustache from whitelisted context
  4. CAPABILITY     check channel supports what step wants
  5. DEGRADATION    reduce if not, or jump to on_unsupported_step_id
  6. TRUNCATION     enforce max_body_length per truncation_strategy
"""
import logging
import re
from odoo import models, api

_logger = logging.getLogger(__name__)

MUSTACHE_RE = re.compile(r'\{\{\s*([a-zA-Z0-9_.|:\-]+)\s*\}\}')


class RenderError(Exception):
    pass


class TemplateParseError(RenderError):
    pass


class VariableMissingError(RenderError):
    pass


class CapabilityMismatchError(RenderError):
    pass


class LengthExceededError(RenderError):
    pass


class RendererService(models.AbstractModel):
    _name = 'comm.chatbot.renderer'
    _description = 'Bot step renderer'

    # ---------- Public entry ----------
    @api.model
    def render(self, step, conversation, leg=None):
        """Return dict: {
            'body': str,
            'options': [{'value': str, 'label': str}, ...],
            'media': [{'kind': str, 'url': str, 'alt': str}, ...],
            'input_hint': str?,
            'metadata': dict,
        } — the adapter converts this to the provider-specific payload.
        """
        channel = (leg.channel_id if leg else conversation.primary_channel_id)
        bot = conversation.bot_id
        try:
            body = self._resolve_body(step, channel, conversation)
            options = self._resolve_options(step, conversation)
            media = self._resolve_media(step, channel)
            self._check_capabilities(step, channel)
            body, options, media = self._degrade(step, channel, body, options, media)
            body = self._truncate(body, channel, step, bot)
            return {
                'body': body,
                'options': options,
                'media': media,
                'input_hint': self._input_hint(step, channel),
                'metadata': dict(step.metadata or {}),
            }
        except RenderError as e:
            _logger.warning('RenderError on step %s: %s', step.id, e)
            raise

    # ---------- Stage 1: language ----------
    @api.model
    def _resolve_body(self, step, channel, conversation):
        lang = self._conversation_language(conversation)
        body = step.body or ''
        if lang:
            tr = step.body_translation_ids.filtered(lambda t: t.language == lang)
            if tr:
                body = tr[0].body

        # Stage 2: channel override
        override = step.channel_override_ids.filtered(
            lambda o: o.channel_id.id == channel.id)
        if override:
            if override[0].hide:
                raise CapabilityMismatchError('step.hidden_on_channel')
            if override[0].body_override:
                body = override[0].body_override

        # Stage 3: Mustache substitution
        return self._substitute(body, conversation, step.bot_id)

    def _conversation_language(self, conversation):
        # partner language > bot default
        if conversation.partner_id and conversation.partner_id.lang:
            return conversation.partner_id.lang
        return conversation.bot_id.default_language

    # ---------- Stage 3: substitution ----------
    @api.model
    def _substitute(self, template, conversation, bot):
        if not template:
            return ''
        ctx = self._context(conversation, bot)
        mode = bot.missing_variable_mode

        def replace(match):
            expr = match.group(1)
            parts = expr.split('|')
            path = parts[0].strip()
            filters = [f.strip() for f in parts[1:]]
            try:
                value = self._resolve_path(path, ctx)
            except KeyError:
                if mode == 'strict':
                    raise VariableMissingError(path)
                if mode == 'debug':
                    return f'<<{path} MISSING>>'
                return ''
            for f in filters:
                value = self._apply_filter(f, value)
            return str(value)

        try:
            return MUSTACHE_RE.sub(replace, template)
        except VariableMissingError:
            raise
        except Exception as e:
            raise TemplateParseError(str(e))

    def _context(self, conversation, bot):
        partner = conversation.partner_id
        return {
            'contact': {
                'name':       partner.name or '',
                'first_name': (partner.name or '').split(' ')[0],
                'phone':      partner.phone or '',
                'mobile':     partner.mobile or '',
                'email':      partner.email or '',
                'language':   partner.lang or '',
            },
            'state': conversation.state or {},
            'env':   bot.env_variables or {},
            'campaign': {'id': conversation.campaign_id or ''},
        }

    def _resolve_path(self, path, ctx):
        parts = path.split('.')
        if len(parts) > 3:
            raise KeyError(path)  # depth guard
        node = ctx
        for p in parts:
            if isinstance(node, dict) and p in node:
                node = node[p]
            else:
                raise KeyError(path)
        return node

    def _apply_filter(self, spec, value):
        if ':' in spec:
            name, arg = spec.split(':', 1)
        else:
            name, arg = spec, ''
        if name == 'default':
            return value if value not in (None, '', 0) else arg
        if name == 'currency':
            try:
                return f'{arg} {float(value):,.2f}'.strip()
            except (ValueError, TypeError):
                return str(value)
        if name == 'date':
            try:
                if arg == 'short':
                    return value.strftime('%a %d %b')
                return value.strftime('%Y-%m-%d')
            except AttributeError:
                return str(value)
        if name == 'mask':
            n = int(arg) if arg else 2
            s = str(value)
            return s[:n] + '*' * max(len(s) - n, 0)
        if name == 'upper':
            return str(value).upper()
        if name == 'lower':
            return str(value).lower()
        return value

    # ---------- Options + media ----------
    @api.model
    def _resolve_options(self, step, conversation):
        if step.kind != 'menu' and step.input_type != 'choice':
            return []
        rendered = []
        for opt in step.option_ids.sorted('sequence'):
            if opt.condition_expression and not self._eval_condition(
                    opt.condition_expression, conversation):
                continue
            rendered.append({
                'value':      opt.value or opt.label,
                'label':      self._substitute(opt.label, conversation, step.bot_id),
                'is_default': opt.is_default,
                'next_step_id': opt.next_step_id.id,
            })
        return rendered

    @api.model
    def _resolve_media(self, step, channel):
        override = step.channel_override_ids.filtered(
            lambda o: o.channel_id.id == channel.id)
        source = step.media_ids
        if override and override[0].media_override_ids:
            source = override[0].media_override_ids
        return [{
            'kind': m.kind,
            'url':  m.url or (m.attachment_id.public_url if m.attachment_id else ''),
            'alt':  m.alt_text or '',
        } for m in source]

    # ---------- Stage 4: capability check ----------
    @api.model
    def _check_capabilities(self, step, channel):
        if step.kind == 'menu':
            n = len(step.option_ids)
            # If a channel can't do interactive lists and n > 0, we still don't
            # fail — degradation will number them. So no strict fail here.
            if n == 0:
                raise CapabilityMismatchError('menu_no_options')
        if step.input_type == 'media' and not any([
                channel.supports_media_image, channel.supports_media_video,
                channel.supports_media_audio, channel.supports_media_document]):
            # Adapter must handle unsupported by jumping to on_unsupported_step_id
            raise CapabilityMismatchError('input_media_unsupported')

    # ---------- Stage 5: degradation ----------
    @api.model
    def _degrade(self, step, channel, body, options, media):
        # Options degradation: if channel doesn't support buttons/lists, embed
        # them as numbered text in body.
        if options:
            embed_as_text = False
            n = len(options)
            if not channel.supports_lists and not channel.supports_buttons:
                embed_as_text = True
            elif channel.supports_buttons and not channel.supports_lists \
                    and n > (channel.max_buttons or 3):
                embed_as_text = True
            elif channel.supports_lists and n > (channel.max_list_rows or 10):
                # Chunk to first N and add "reply MORE" — simplistic
                options = options[: (channel.max_list_rows or 10)]

            if embed_as_text:
                menu_lines = [f'{i+1}. {o["label"]}' for i, o in enumerate(options)]
                body = (body + '\n\n' + '\n'.join(menu_lines)).strip()
                # Options still returned; adapter may render as text-only
                for i, o in enumerate(options):
                    o['numeric_key'] = str(i + 1)

        # Media degradation: filter out unsupported types
        supported = []
        for m in media:
            k = m['kind']
            if k == 'image' and channel.supports_media_image:
                supported.append(m)
            elif k == 'video' and channel.supports_media_video:
                supported.append(m)
            elif k == 'audio' and channel.supports_media_audio:
                supported.append(m)
            elif k == 'document' and channel.supports_media_document:
                supported.append(m)
            else:
                if m.get('alt') and not body:
                    body = m['alt']
                elif m.get('alt'):
                    body = (body + '\n' + m['alt']).strip()
        return body, options, supported

    # ---------- Stage 6: truncation ----------
    @api.model
    def _truncate(self, body, channel, step, bot):
        limit = channel.max_body_length or 0
        if not limit or not body or len(body) <= limit:
            return body
        strategy = step.truncation_strategy
        if strategy == 'inherit':
            strategy = bot.truncation_strategy
        if strategy == 'error':
            raise LengthExceededError(f'{len(body)} > {limit}')
        if strategy == 'hard':
            return body[: limit - 3] + '...'
        # Smart: try last sentence boundary
        head = body[:limit]
        for punct in ('. ', '! ', '? ', '\n\n', '\n'):
            idx = head.rfind(punct)
            if idx > int(limit * 0.5):
                return body[: idx + 1] + ' ...more'
        # Fall back to word boundary
        idx = head.rfind(' ')
        if idx > int(limit * 0.5):
            return body[:idx] + ' ...more'
        return body[: limit - 3] + '...'

    # ---------- Helpers ----------
    def _input_hint(self, step, channel):
        if step.kind != 'input':
            return ''
        t = step.input_type or 'text'
        return {
            'text':   '',
            'number': 'Reply with a number',
            'date':   'Reply with a date (YYYY-MM-DD)',
            'choice': '',
            'media':  'Send a photo or file',
            'email':  'Reply with your email',
            'phone':  'Reply with your phone number',
        }.get(t, '')

    def _eval_condition(self, expression, conversation):
        # Same safe substitution engine — 'expression' is evaluated after
        # substitution, then truthiness-checked. We do NOT eval Python.
        substituted = self._substitute(expression, conversation, conversation.bot_id)
        s = substituted.strip().lower()
        return s and s not in ('false', '0', 'no', 'none', 'null', '')
