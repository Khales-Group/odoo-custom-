def migrate(cr, version):
    # The "Payment" type became "Client" (next to Contractor / VAT Return /
    # VAT Refund). Renamed before the module loads, so no case is left
    # holding a value the selection no longer has.
    cr.execute("UPDATE kh_collection_case SET collection_type = 'client' WHERE collection_type = 'payment'")
