-- mart.v_purchase (helper for the Vendors tab)
-- Grain: one row per payment line paid to a private vendor.
-- What: the Spend Lens basis: payments to payees that are not government or institutional (ref.map_payee_vendor
-- is_government: public bodies, hospitals, health plans, banks) and not pass-through (reference/payee_area_exclusions.csv).
-- Payees outside the six focus areas are labeled "Other goods & services", as the Spend Lens does.
CREATE OR REPLACE TABLE mart.v_purchase AS
SELECT fiscal_year, agency_code, vendor, vendor_name, coalesce(area, 'Other goods & services') AS area, amount
FROM mart.payment_area WHERE NOT is_government AND NOT passthrough AND fiscal_year <= 2026;
