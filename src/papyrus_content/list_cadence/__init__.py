"""A list carries its cadence, time, time zone and rule as data (slice N1, PPY-4d74d9).

``settings.py`` is the document and every rule about what may be saved; ``store.py`` reads and changes it as a versioned site document;
``schedule.py`` turns a periodic list into the schedule entry the schedule reconciler keeps; ``announce.py`` makes the Announcement and the email Delivery,
the same shape for every cadence. Nothing about a cadence is in code: a list that is added to the document needs no deploy of anything but the next
``papyrus agents schedules`` run, which the deploy step makes.
"""
