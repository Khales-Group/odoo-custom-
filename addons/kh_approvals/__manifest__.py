# addons/kh_approvals/__manifest__.py
{
    "name": "Khales Approvals",
    "summary": "Configurable multi-step approvals with routing rules.",
    "version": "18.0.1.0.0",
    "author": "Khales Team",
    "website": "https://khales.ae",
    "category": "Operations/Approvals",
    "depends": ["base", "mail"],
    "data": [
        # --- security first ---
        "security/kh_approvals_security.xml", # This file was missing, I've added it.
        "security/ir.model.access.csv",
        "security/kh_approvals_manager_access.xml",
        "security/kh_approvals_rules.xml",
        # --- data ---
        "data/sequence.xml",
        # --- views ---
        "views/approval_request_views.xml",
        "views/approval_rule_views.xml",
        "views/qweb_templates.xml",
        "views/department_views.xml",

        # --- ACTIONS + MENUS LAST (they may reference the views above) ---
        "views/menu.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "kh_approvals/static/src/css/approvals_backend.css",
        ],
    },
    "application": True,
    "installable": True,
    "license": "LGPL-3",
}


                                                                 
    cd C:\Users\Khales\odoo-custom-

 # Get on your working branch
 git checkout approvals-test2
 git pull

 # Add any unsaved changes you have
 git add .

 # Commit your changes with an automatic message
 git commit -m "Auto-sync: Save latest local edits"

 # Push your new code to your "source of truth" branch
 git push origin approvals-test2


 # --- PART 2: AUTO-UPDATE AND REBUILD THE ODOO.SH PROJECT ---

 # Go to the main Odoo.sh project folder
 cd C:\Users\Khales\Khales-System

 # Get on the Odoo.sh branch you want to update
 # (Change 'final-activity-updates2' if you are working on a different branch)
 git checkout final-activity-updates4
 git pull

 # Go into the submodule to sync it
 cd Khales-Group/odoo-custom-

 # Fetch the latest information from the server
 git fetch origin

 # THIS IS THE NEW, CRITICAL COMMAND:
 # Force the submodule to become an EXACT copy of your 'approvals-test2' branch.
 git reset --hard origin/approvals-test4

 # Go back to the main project
 cd ../../

 # Commit the pointer update
 git add Khales-Group/odoo-custom-
 git commit -m "Auto-sync: Update submodule from approvals-test2"

 # Create an empty commit to guarantee a rebuild
 git commit --allow-empty -m "FORCE REBUILD"

 # Push everything to Odoo.sh
 git push

                                                          