# -*- coding: utf-8 -*-
"""Flow diagrams inside a company doc.

A diagram is a list of steps, each saying which step comes next. Nobody draws
lines: the screen lays the steps out by itself. A doc keeps its diagrams in
`flows`, {key: {'name', 'steps'}}, and the place of each one in its text as an
empty block, <div class="o_sdb_flow o_sdb_flow_<key>">, so a diagram sits in
the doc like a picture or a table.

Every diagram is also plain numbered steps ("1. Start: … Then step 2."). That
text is what Sidekick and the chatbot read, what prints, and what a screen
reader hears. It is made here, in one place.

A step: {'id': int, 'kind': start | step | decision | handover | end,
         'text': str, 'detail': str, 'next': [{'label': str, 'to': id | False}]}
Only a decision has more than one way on, each with its answer as the label.
"""
import re

from lxml import html
from markupsafe import Markup

from odoo import _
from odoo.tools import html2plaintext

KINDS = ('start', 'step', 'decision', 'handover', 'end')
MAX_STEPS = 60
TEXT_CHARS = 160
DETAIL_CHARS = 600
LABEL_CHARS = 24
NAME_CHARS = 100
KEY = re.compile(r'^[a-z0-9]{1,12}$')
BLOCK_CLASS = re.compile(r'(?:^|\s)o_sdb_flow_([a-z0-9]{1,12})(?:\s|$)')


def kind_labels():
    return {'start': _("Start"), 'step': _("Step"), 'decision': _("Decision"),
            'handover': _("Hand-over"), 'end': _("End")}


def _one_line(text, limit):
    return ' '.join(str(text or '').split())[:limit]


def clean_steps(steps):
    """Steps as they are stored: known kinds, whole-number ids, and ways on
    that point at steps of this diagram. Anything else is dropped."""
    cleaned, seen = [], set()
    for raw in (steps or [])[:MAX_STEPS]:
        if not isinstance(raw, dict):
            continue
        try:
            step_id = int(raw.get('id'))
        except (TypeError, ValueError):
            continue
        if step_id in seen:
            continue
        seen.add(step_id)
        cleaned.append({
            'id': step_id,
            'kind': raw.get('kind') if raw.get('kind') in KINDS else 'step',
            'text': _one_line(raw.get('text'), TEXT_CHARS),
            'detail': str(raw.get('detail') or '').strip()[:DETAIL_CHARS],
            'next': raw.get('next') if isinstance(raw.get('next'), list) else [],
        })
    for step in cleaned:
        ways = []
        for way in step['next']:
            if not isinstance(way, dict):
                continue
            try:
                to = int(way.get('to'))
            except (TypeError, ValueError):
                to = False
            if to not in seen or to == step['id']:
                to = False
            ways.append({'label': _one_line(way.get('label'), LABEL_CHARS), 'to': to})
        if step['kind'] == 'end':
            ways = []
        elif step['kind'] != 'decision':
            ways = [{'label': '', 'to': way['to']} for way in ways[:1] if way['to']]
        step['next'] = ways
    return cleaned


def clean_flow(flow):
    flow = flow if isinstance(flow, dict) else {}
    return {'name': _one_line(flow.get('name'), NAME_CHARS) or _("Flow diagram"),
            'steps': clean_steps(flow.get('steps'))}


def _sentence(text):
    text = (text or '').strip()
    return text if not text or text[-1] in '.?!:' else text + '.'


def flow_lines(flow):
    """One {'label', 'text'} per step, in order: the kind, then what happens
    and where it goes next. Steps are numbered by their place in the list."""
    steps = (flow or {}).get('steps') or []
    number = {step['id']: index + 1 for index, step in enumerate(steps)}
    labels = kind_labels()
    lines = []
    for step in steps:
        said = [_sentence(step.get('text')) or _("(nothing written yet)")]
        if step.get('detail'):
            said.append(_sentence(' '.join(step['detail'].split())))
        for way in step.get('next') or []:
            target = number.get(way.get('to'))
            if step['kind'] == 'decision':
                answer = way.get('label') or _("otherwise")
                said.append(_("If %(answer)s, step %(number)s.", answer=answer, number=target) if target
                            else _("If %(answer)s: not decided yet.", answer=answer))
            elif target:
                said.append(_("Then step %s.", target))
        lines.append({'label': labels[step['kind']], 'text': ' '.join(said)})
    return lines


def flow_text(flow):
    """A diagram as plain text, for the assistants and for search."""
    lines = ["%s. %s: %s" % (index + 1, line['label'], line['text'])
             for index, line in enumerate(flow_lines(flow))]
    return "\n".join([_("Flow diagram: %s", (flow or {}).get('name') or '')] + lines)


def _block_key(element):
    match = BLOCK_CLASS.search(element.get('class') or '')
    return match.group(1) if match else False


def _parse(body):
    return html.fragment_fromstring(body or '', create_parent='div')


def _inner(root):
    return (root.text or '') + ''.join(html.tostring(child, encoding='unicode') for child in root)


def clean_doc(body, flows):
    """A doc's text and diagrams as they are stored. Each diagram keeps one
    block in the text, on a line of its own; a block with no diagram behind it
    goes, and so does a diagram with no block left in the text."""
    flows = {key: clean_flow(flow) for key, flow in (flows or {}).items()
             if isinstance(key, str) and KEY.match(key)}
    if not flows and 'o_sdb_flow' not in (body or ''):
        return body, {}
    root = _parse(body)
    kept = {}
    for block in root.xpath(".//*[contains(concat(' ', normalize-space(@class), ' '), ' o_sdb_flow ')]"):
        key = _block_key(block)
        if key not in flows or key in kept:
            block.drop_tree()
            continue
        kept[key] = flows[key]
        # A diagram stands on its own line: lift it out of a list or a table.
        top = block
        while top.getparent() is not root:
            top = top.getparent()
        if top is not block:
            tail, block.tail = block.tail, None
            parent = block.getparent()
            previous = block.getprevious()
            parent.remove(block)
            if tail:
                if previous is not None:
                    previous.tail = (previous.tail or '') + tail
                else:
                    parent.text = (parent.text or '') + tail
            top.addnext(block)
        for child in list(block):
            block.remove(child)
        block.tag = 'div'
        for name in list(block.attrib):
            del block.attrib[name]
        # Only a class: it is all the text's cleaner is sure to keep. The
        # editor makes the block read-only itself when it opens.
        block.set('class', 'o_sdb_flow o_sdb_flow_%s' % key)
        block.text = _("Flow diagram: %(name)s (%(count)s steps)", name=kept[key]['name'], count=len(kept[key]['steps']))
    return _inner(root), kept


def doc_parts(body, flows):
    """A doc's text cut at its diagrams, for the page to draw:
    [{'html': Markup} | {'flow': {'key', 'name', 'steps', 'lines'}}]."""
    flows = flows or {}
    if not flows or 'o_sdb_flow' not in (body or ''):
        return [{'html': Markup(body)}] if html2plaintext(body or '').strip() else []
    root = _parse(body)
    parts, run = [], [root.text or '']

    def close():
        text = ''.join(run)
        if html2plaintext(text).strip():
            parts.append({'html': Markup(text)})
        run.clear()

    for child in root:
        key = _block_key(child) if 'o_sdb_flow' in (child.get('class') or '') else False
        if key and key in flows:
            close()
            parts.append({'flow': dict(flows[key], key=key, lines=flow_lines(flows[key]))})
            run.append(child.tail or '')
        else:
            run.append(html.tostring(child, encoding='unicode'))
    close()
    return parts


def doc_text(body, flows):
    """A doc's text with each diagram written out as numbered steps where it
    stands. What the assistants read and what search looks through."""
    chunks = []
    for part in doc_parts(body, flows):
        chunks.append(flow_text(part['flow']) if 'flow' in part else html2plaintext(part['html']).strip())
    return "\n\n".join(chunk for chunk in chunks if chunk)
