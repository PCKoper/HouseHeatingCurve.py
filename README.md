# HouseHeatingCurve.py
Python script to query heating energy and outside temperature data from Domoticz to fit and plot the 
heating power points and curve and calculate:

- The required heating power (for example a heat pump) at a configured outside temperature 
- The required alternative additional power to be able to keep the house warm based on historic data.
- The required days/year this alternative power is needed and the total energy involved as well as the cost.
- At what temperature no heating is needed anymore.

This script makes use of the scipy package.
