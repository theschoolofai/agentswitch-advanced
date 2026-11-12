#Minutes of meeting

##Nov 8, 2026

1- what should be the order of the orders in the daily report - in order of duration or in order of Order value (Rohan)

2- Does Accounts have visibility to orders (Rohan)

3- how do we provide deep links to orders (S/D)

4- Add header to the list of orders - show currency symbol also (S/D)

4 a - Is the content and format of the mail ok or needs modification? (Provide sample to Rohan)

5- whether it should be an attachment or show in the mail itself.(Rohan)

6- if attachment then where should it stored (Rohan)

7- content of the mail , we can provide different options

8- why is the delay in creating invoices happening , group them into buckets - useful for analytics.(Rohan)

9- should we do some financial impact analysis of delay (in terms of interest loss) in invoicing (propose to Rohan)

10) Internal monitoring - Orders not invoiced , send a mail to accounts .Are you going to add external monitoring later (Rohan)

11) Add payment received logic to update Invoice entity - reduce outstanding and increase amount received. for this join invoice to payment to track receivables.(Deepak)

12- where/whom do we send the daily report ?-(Sunil / Rohan to provide the destination of the report)

13- Is there a way to check whether the invoice is sent to the customer?(Sunil)

14- Who handles customer receivables - whom to alert about delay? (Rohan)

15- How to handle ambigious receivables e.g invoiced for 100 but received only 90 , should we keep tracking 10 receivable and for how long ? (Rohan)


##weekly update (Nov 8, 2026)

work split -

Invoices Overdue - Sunil

Payment not applied - Deepak

0- Please elaborate on the term Payment not applied , how to derive this (Rohan)

1- what should be the order of the orders in the daily report - in order of duration or in order of Order value (Rohan)

2- Does Accounts have visibility to orders (Rohan)

3 - Is the content and format of the mail ok or needs modification? (Provide sample to Rohan)

4- whether it should be an attachment or show in the mail itself.(Rohan)

5- if attachment then where should it stored (Rohan)

6- why is the delay in creating invoices happening ,can we group them into buckets (based on lookup code)- useful for analytics.(Rohan)

7- should we do some financial impact analysis of delay (in terms of interest loss) in invoicing (propose to Rohan)

8- Internal monitoring - Orders not invoiced , send a mail to accounts .Are you going to add external monitoring later (Rohan)

9- where/whom do we send the daily report ?-(Sunil / Rohan to provide the destination of the report)

10- Who handles customer receivables - whom to alert about delay? (Rohan)

11- How to handle ambigious receivables e.g invoiced for 100 but received only 90 , should we keep tracking 10 receivable and for how long ? (Rohan)

12- Please resolve 2 bugs raised from seat 31 , it is blocking us from progressing.