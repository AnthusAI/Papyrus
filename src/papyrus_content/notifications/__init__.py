"""The ``notifications`` plugin's side of Caducus (PPY-44721a, PPY-38be08).

Caducus (the ``caducus[notify]`` package) decides who is told and sends it; it runs inside each site's own stack with the
site's own table. This package is the thin adapter: it turns a published story into a Caducus event, passes the site's themed
renderer to the package's email channel, and exposes the Lambda entry points. No stores, queues or senders are written here.
"""
