# -*- coding: utf-8 -*-
"""LLM step runtime.

Implements the tool loop, output modes, guardrails, and billing telemetry.
Uses the Anthropic Python SDK when available; falls back to a stub if not
installed. The stub returns a "not configured" fallback so bots don't crash
during initial deployment without an API key.
"""
import json
import logging
import time

from odoo import models, fields, api

from . import adapter_registry
from .renderer import RenderError

_logger = logging.getLogger(__name__)


try:
    import anthropic  # type: ignore
    _ANTHROPIC_AVAILABLE = True
except Exception:
    _ANTHROPIC_AVAILABLE = False


class LlmClient(models.AbstractModel):
    _name = 'comm.chatbot.llm'
    _description = 'LLM step runtime'

    # ---------- Public entry ----------
    @api.model
    def _run_llm_step(self, step, conversation, leg):
        """Execute an LLM step; return the next comm.bot.step or None.

        Honours comm_chatbot_skip_llm context flag — set by the walker
        when the user hasn't opted into spending real tokens. Distinct
        from comm_chatbot_force_shadow which only blocks adapter sends.
        """
        if self.env.context.get('comm_chatbot_skip_llm'):
            # Preview walker without real-tokens toggle — don't call API;
            # log a placeholder so the walker transcript still shows the step.
            self.env['comm.interaction'].create({
                'conversation_id': conversation.id,
                'leg_id': leg.id if leg else False,
                'channel_id': (leg.channel_id if leg else
                               conversation.primary_channel_id).id,
                'direction': 'outbound',
                'step_id': step.id,
                'raw_body': f'(LLM step — skipped in preview)',
                'rendered_body': f'(LLM step "{step.name}" would call '
                                  f'{step.llm_model or step.bot_id.default_llm_model} '
                                  f'here — skipped. Toggle "Spend real tokens" '
                                  f'in the walker to actually run it.)',
                'status': 'sent',
            })
            return step.next_step_id or step.llm_fallback_step_id
        model = step.llm_model or step.bot_id.default_llm_model or 'claude-sonnet-4-6'
        api_key = self._get_api_key()
        if not (api_key and _ANTHROPIC_AVAILABLE):
            _logger.warning('Anthropic SDK/API key unavailable — LLM step %s '
                            'falling back.', step.id)
            return step.llm_fallback_step_id or step.next_step_id

        renderer = self.env['comm.chatbot.renderer']
        system_prompt = renderer._substitute(step.llm_system_prompt or '',
                                             conversation, step.bot_id)
        messages = self._build_messages(step, conversation)
        tools = self._build_tools(step)

        interaction = self.env['comm.interaction'].create({
            'conversation_id': conversation.id,
            'leg_id': leg.id if leg else False,
            'channel_id': (leg.channel_id if leg else conversation.primary_channel_id).id,
            'direction': 'outbound',
            'step_id': step.id,
            'raw_body': step.body or '',
            'status': 'pending',
            'llm_model_used': model,
        })

        try:
            result = self._call_model_loop(
                step, model, api_key, system_prompt, messages, tools,
                conversation, interaction)
        except Exception as e:
            _logger.warning('LLM step %s errored: %s', step.id, e)
            interaction.write({'status': 'failed', 'error': str(e)})
            return step.llm_fallback_step_id or step.next_step_id

        # Handle output based on mode
        return self._handle_output(step, conversation, leg, result, interaction)

    # ---------- Message building ----------
    def _build_messages(self, step, conversation):
        msgs = []
        if step.llm_include_history:
            history = self.env['comm.interaction'].search([
                ('conversation_id', '=', conversation.id),
                ('at', '<', fields.Datetime.now()),
            ], limit=step.llm_history_turns * 2, order='at desc')
            for i in reversed(history):
                role = 'user' if i.direction == 'inbound' else 'assistant'
                body = i.rendered_body or i.raw_body
                if body:
                    msgs.append({'role': role, 'content': body})
        # Prompt this turn — use step.body as the initial user turn or trigger
        if step.body:
            renderer = self.env['comm.chatbot.renderer']
            msgs.append({'role': 'user',
                         'content': renderer._substitute(step.body, conversation,
                                                          step.bot_id)})
        elif not msgs:
            msgs.append({'role': 'user', 'content': '(begin)'})
        return msgs

    def _build_tools(self, step):
        tools = []
        for t in step.llm_tool_ids:
            tools.append({
                'name': t.name,
                'description': t.description,
                'input_schema': t.input_schema or {'type': 'object', 'properties': {}},
            })
        # Synthesize a choose_next_step tool for decision mode
        if step.llm_output_mode == 'decision' and step.llm_decision_option_ids:
            tools.append({
                'name': 'choose_next_step',
                'description': 'Pick the next step from the allowed set.',
                'input_schema': {
                    'type': 'object',
                    'properties': {
                        'next_step_name': {
                            'type': 'string',
                            'enum': [s.name for s in step.llm_decision_option_ids],
                        },
                        'reasoning': {'type': 'string'},
                    },
                    'required': ['next_step_name'],
                },
            })
        return tools

    # ---------- Model loop ----------
    def _call_model_loop(self, step, model, api_key, system_prompt, messages,
                        tools, conversation, interaction):
        client = anthropic.Anthropic(api_key=api_key)
        iterations = 0
        max_iters = step.llm_max_tool_iterations or 5
        total_input = total_output = 0
        first_token_at = None
        tool_calls_count = 0

        while iterations < max_iters:
            iterations += 1
            t0 = time.time()

            # Prompt caching: mark system as cacheable
            system_arg = [{'type': 'text', 'text': system_prompt,
                           'cache_control': {'type': 'ephemeral'}}] \
                if step.llm_cache_breakpoint else system_prompt

            resp = client.messages.create(
                model=model,
                max_tokens=step.llm_max_tokens or 1024,
                temperature=step.llm_temperature or 0.5,
                system=system_arg,
                messages=messages,
                tools=tools if tools else [],
            )
            if first_token_at is None:
                first_token_at = int((time.time() - t0) * 1000)

            usage = getattr(resp, 'usage', None)
            if usage:
                total_input += getattr(usage, 'input_tokens', 0) or 0
                total_output += getattr(usage, 'output_tokens', 0) or 0

            if resp.stop_reason == 'tool_use':
                # Execute all tool calls in this turn
                tool_results = []
                for block in resp.content:
                    if getattr(block, 'type', '') == 'tool_use':
                        tool_calls_count += 1
                        result = self._execute_tool(
                            step, block.name, block.input, conversation)
                        tool_results.append({
                            'type': 'tool_result',
                            'tool_use_id': block.id,
                            'content': json.dumps(result) if not isinstance(result, str)
                                        else result,
                        })
                messages.append({'role': 'assistant', 'content': resp.content})
                messages.append({'role': 'user', 'content': tool_results})
                continue

            # end_turn — collect final text
            text_parts = [b.text for b in resp.content
                          if getattr(b, 'type', '') == 'text']
            interaction.write({
                'llm_input_tokens': total_input,
                'llm_output_tokens': total_output,
                'llm_tool_calls': tool_calls_count,
                'llm_first_token_latency_ms': first_token_at or 0,
                'rendered_body': '\n'.join(text_parts),
                'status': 'sent',
            })
            self._log_billing(step, model, total_input, total_output, interaction)
            return {'text': '\n'.join(text_parts), 'stop': 'end_turn',
                    'tool_choice': self._extract_decision(resp)}

        # Iteration cap hit
        interaction.write({'status': 'failed',
                           'error': 'max_tool_iterations exceeded'})
        return {'text': '', 'stop': 'max_iterations', 'tool_choice': None}

    def _execute_tool(self, step, tool_name, args, conversation):
        tool = step.llm_tool_ids.filtered(lambda t: t.name == tool_name)
        if not tool:
            # decision tool
            if tool_name == 'choose_next_step':
                return {'ack': True, '_decision': args.get('next_step_name')}
            return {'error': f'unknown tool: {tool_name}'}
        tool = tool[0]
        try:
            if tool.executor_type == 'python':
                fn = adapter_registry.get_python_tool(tool.executor_python_key)
                result = fn(self.env, conversation, args) if fn else {'error': 'no callable'}
            elif tool.executor_type == 'action':
                # Run the action step's logic and return its result
                exec_ = self.env['comm.chatbot.executor']
                result = exec_._run_action(tool.executor_action_step_id, conversation)
            elif tool.executor_type == 'jump':
                result = {'jump_to_step_id': tool.executor_jump_step_id.id}
            else:
                result = {}
            if tool.result_variable:
                state = dict(conversation.state or {})
                state[tool.result_variable] = result
                conversation.state = state
            return result
        except Exception as e:
            _logger.warning('Tool %s failed: %s', tool_name, e)
            return {'error': str(e)}

    def _extract_decision(self, resp):
        for block in resp.content:
            if getattr(block, 'type', '') == 'tool_use' \
                    and block.name == 'choose_next_step':
                return block.input.get('next_step_name')
        return None

    # ---------- Output handling ----------
    def _handle_output(self, step, conversation, leg, result, interaction):
        mode = step.llm_output_mode or 'freeform'
        if result['stop'] == 'max_iterations':
            return step.llm_fallback_step_id or step.next_step_id

        if mode == 'freeform':
            # Send the text as an outbound message
            self._send_llm_body(conversation, leg, result['text'], step, interaction)
            return step.next_step_id

        if mode == 'structured':
            try:
                parsed = json.loads(result['text']) if result['text'] else {}
                if step.llm_output_save_to:
                    state = dict(conversation.state or {})
                    state[step.llm_output_save_to] = parsed
                    conversation.state = state
            except Exception:
                return step.llm_fallback_step_id or step.next_step_id
            return step.next_step_id

        if mode == 'decision':
            picked = result.get('tool_choice')
            if picked:
                target = step.llm_decision_option_ids.filtered(
                    lambda s: s.name == picked)
                if target:
                    return target[0]
            return step.llm_fallback_step_id or step.next_step_id

        return step.next_step_id

    def _send_llm_body(self, conversation, leg, body, step, interaction):
        adapter = self.env['comm.chatbot.registry'].get_adapter_for_channel(
            leg.channel_id if leg else conversation.primary_channel_id)
        if not adapter:
            return
        try:
            adapter().send(self.env, interaction,
                           {'body': body, 'options': [], 'media': []})
        except Exception as e:
            _logger.warning('LLM adapter send failed: %s', e)

    # ---------- Billing ----------
    def _log_billing(self, step, model, input_tokens, output_tokens, interaction):
        Event = self.env['comm.billing.event']
        Event.create({
            'event_date': fields.Datetime.now(),
            'channel': 'other',
            'provider': 'anthropic',
            'category': 'mba_token',
            'unit': 'kilotoken',
            'unit_qty': (input_tokens + output_tokens) / 1000.0,
            'source_model': 'comm.interaction',
            'source_id': interaction.id,
            'interaction_id': interaction.id,
            'conversation_id': interaction.conversation_id.id,
        })

    # ---------- Config ----------
    def _get_api_key(self):
        return self.env['ir.config_parameter'].sudo().get_param(
            'comm_chatbot.anthropic_api_key') or ''
