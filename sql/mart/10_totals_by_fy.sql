-- yoy: keys=none values=total_payments
-- Dashboard file totals_by_fy: all payments per fiscal year, rows, paying agencies, vendors.
SELECT fiscal_year, sum(amount) AS total_payments, count(*) AS payment_records, count(DISTINCT agency_code) AS agencies, count(DISTINCT vendor) AS vendors
FROM mart.payment_area GROUP BY 1
