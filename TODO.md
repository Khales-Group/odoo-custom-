# TODO: Implement Phase 1: Odoo Changes for Email Categories

## Step 1: Update project_extension.py

- Add ProjectEmailCategory model with name and color fields.
- Add category_ids field to ProjectEmail model (but wait, ProjectEmail is in project_email.py, so update there instead).

## Step 2: Update project_email.py

- Add category_ids Many2many field to ProjectEmail model.

## Step 3: Update project_email_views.xml

- Add search view with searchpanel for category_ids.

## Step 4: Update project_views.xml

- Ensure the smart button uses the new search view.

## Step 5: Update ir.model.access.csv

- Add access rights for project.email.category model.

## Step 6: Update **manifest**.py

- Add "data/email_categories.xml" to the data list.

## Step 7: Verify and Test

- Check that categories are created.
- Test filtering in the email list view.
