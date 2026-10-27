"""The shared property master and the simulated enterprise GIS.

* ``seed`` writes the synthetic town onto the registry parcel and address tables.
* ``scoring`` normalises and scores addresses for the simulated locator.
* ``simulator`` serves ArcGIS REST shaped endpoints from those tables.
* ``adapter`` is the ``GisLocator`` the application's own code calls over HTTP.
* ``matching`` holds the parcel link of an application.
"""
