# -*- coding: utf-8 -*-
"""Fill the Team report with the job checks the jobs still record.

A job keeps only its latest check (who and when), so this is the one piece of
past activity that can be recovered. Everything else starts from today."""
from odoo import SUPERUSER_ID, api

MAX_TAKEN = 30 * 60


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    if 'comm.agent.activity' not in env:
        return
    Log = env['comm.agent.activity']
    if Log.search_count([('action', '=', 'job_check')]):
        return
    listings = env['chat2work.listing'].with_context(active_test=False).search(
        [('verified_by_id', '!=', False), ('verified_at', '!=', False), ('verification_state', '!=', 'unverified')],
        order='verified_by_id, verified_at, id')
    labels = dict(listings._fields['verification_state']._description_selection(env))
    vals, previous = [], {}
    for listing in listings:
        user = listing.verified_by_id
        if user.id == SUPERUSER_ID or user.share:
            continue
        last = previous.get(user.id)
        taken = (listing.verified_at - last).total_seconds() if last else None
        previous[user.id] = listing.verified_at
        vals.append({
            'user_id': user.id,
            'at': listing.verified_at,
            'source': 'chat2work',
            'action': 'job_check',
            'res_model': listing._name,
            'res_id': listing.id,
            'name': (listing.title or '')[:200],
            'result': listing.verification_state,
            'result_label': labels.get(listing.verification_state),
            'has_note': bool(listing.verification_note),
            'seconds': max(1, round(taken)) if taken is not None and taken <= MAX_TAKEN else False,
        })
    Log.create(vals)
