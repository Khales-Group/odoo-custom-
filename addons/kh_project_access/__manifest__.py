{
    "name": "Project Access Restriction",
    "version": "19.0.1.0.0",
    "summary": "Restrict projects/tasks to their manager and assignees only",
    "description": """
Project Access Restriction
===========================

By default any internal user with Project access can see every project and
task company-wide. This module restricts that: a user can only see a
project if they are its Project Manager, or they are assigned to at least
one task in it - and the same restriction applies directly on the Tasks
screen.

A new "Full Project Access" checkbox on the user's Access Rights tab
bypasses the restriction entirely (sees every project/task), including for
users who have Project: Administrator access - that access level alone no
longer grants company-wide visibility on its own.
    """,
    "author": "Khales Group",
    "category": "Project",
    "depends": ["base", "project"],
    "data": [
        "security/project_access_rules.xml",
        "views/res_users_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
    "license": "LGPL-3",
}
