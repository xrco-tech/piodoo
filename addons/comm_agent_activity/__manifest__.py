# -*- coding: utf-8 -*-
{
    'name': 'Agent Activity',
    'version': '18.0.1.2.0',
    'category': 'Communications',
    'summary': 'What each agent did, how fast and how well: one record per action, and the Team report',
    'description': """
Agent Activity
==============
One line for each thing an agent does that counts: who, when, what, on which
record and how it went. The workspaces write the lines (Chat2Work: jobs
checked, matches decided, employers checked or joined, messages answered;
Contact Centre: messages answered, conversations closed, queued calls wrapped
up). Calls and their talk time are read from the call records.

The Team report is built on those lines:

- Supervisors see every agent for a period: active time, counts per action,
  how long people waited for a reply, calls, decisions someone else reversed
  later, and a score.
- One agent in detail: their figures beside the team average, active time per
  day and their latest activity.
- Agents see their own figures beside the team average, never each other's.
- The score is points per action, less points for each reversed decision.
  Supervisors set the points.
- Activity per day: bars split by kind of work (per hour for one day), with
  the period before as a dashed line. It can count actions, score or active
  time, and the whole page can be narrowed to some agents.
- Planning: work waiting against the team's pace, and the hours of the day
  when people wait longest.
- Targets: a supervisor sets what each agent should reach (for everyone, or
  different for one agent). Agents see their progress in My activity and in
  a slim line at the top of the workspaces; the supervisor sees who is on
  target today. Daily targets count Monday to Friday. No target is on until
  a supervisor switches it on.

Active time is worked out from the gaps between an agent's actions (a gap of
more than 15 minutes ends a stretch), not from logins. Figures start the day
this is installed; only past job checks are filled in from what the jobs
still record.
    """,
    'author': 'XR Co.',
    'website': 'https://github.com/xrco-tech/piodoo',
    'license': 'LGPL-3',
    'depends': ['base', 'web'],
    'data': [
        'security/comm_agent_activity_security.xml',
        'security/ir.model.access.csv',
        'data/comm_agent_activity_points_data.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'comm_agent_activity/static/src/team/team.scss',
            'comm_agent_activity/static/src/team/team.js',
            'comm_agent_activity/static/src/team/team.xml',
            'comm_agent_activity/static/src/team/strip.js',
            'comm_agent_activity/static/src/team/strip.xml',
        ],
        'web.assets_web_dark': [
            'comm_agent_activity/static/src/team/team.dark.scss',
        ],
    },
    'installable': True,
}
