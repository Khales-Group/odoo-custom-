# Fix Non-Admin Filter Bypass in Approvals

## Steps:

- [x] 1. Edit addons/kh_approvals/views/menu.xml: Add domain to action_kh_approval_requests_my_v2
- [x] 1b. Add domain to action_kh_approval_requests_to_approve_v2 (To Approve tab)
- [ ] 2. Upgrade kh_approvals module
- [ ] 3. Test as non-admin user
- [ ] 4. Verify manager access unchanged
- [ ] 5. Mark complete
