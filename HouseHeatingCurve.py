#!/usr/bin/env python
##############################################################################################################
# HouseHeatingCurve.py 
# Last Update: December 24th 2019
# V0.1 : Initial Creation
# V0.2 : Update comments, added scaling on placement of text labels in the plot, added Gas Sensor.
# V0.3 : Added option to read data from .csv file i.s.o. Domoticz query.
#        Added option to estimate yearly energy required and internal and external heating sources.
#        Distributed the data over subplots so it remains readable.
# V0.4 : Added python reference for shell in first line of the script, made csv as data source default
# V0.41: Added Python3 style urllib with fallback for python 2 style changed some constructs to be python3.5 compatible.
##############################################################################################################
# Script queries Heating (kWh) and Temperature (oC) data from Domoticz stored in sensors with ids 
# OutDoorTemperatureSensorID and HeatingEnergySensorID and analyses the data from DateStartAnalyses till 
# DateEndAnalyses.
# Optionally when EstimateAdditionalInternalAndExternalEnergy is set to True it can do an analyses on the 
# additional internal and external heating power sources, for which it will need indoor temperature data 
# (InDoorTemperatureSensorID), used electricity data (TotalElectricSensorID) and an estimate for the average 
# heat produced per day by the people inside the house as set with the HeatFromWarmBodies parameter.
#
# The Script can also be used without Domoticz, the required average outside temperature and heating information
# can be read from a csv file. Indicate this by setting UseCSVFileAsDataSource to True and specify the correct
# filename of the file to use in CSVFile. The CSV file should contain 2 columns of data: outside temperature, energy
# and no header. The GiGo principle applies here, please make sure the file is formatted correctly.
# When the option EstimateAdditionalInternalAndExternalEnergy is set to True, the file should also contain 
# columns for the indoor temperature and the used electricity in kWh, so than the order of the columns would
# be: outdoor temperature, energy, indoor temperature, electricity.
#
# The OutdoorTemperatureSensor is a standard Domoticz temperature sensor, the HeatingEnergySensor is a sensor
# type General, subtype Custom Sensor, I use a Kamstrup302 to accurately measure the energy going into my 
# heating system. 
# When you don't have such a device, but do have a smart Gas meter, that one can also be used by setting
# the UseGasDataForHeatingEnergyEstimation to True. In that case GasSensorID will be used to get the data
# and the Energy is estimated by deducting the amount of Gas you use for Warm Water and Cooking indicated by 
# CubicMetersGasADayForWarmWaterAndCooking and multiply this with EnergyPerCubicMeterGas. 
# Default setting of 31.65/3.6 equals the energy content of Natural Gas used in Holland, assuming the heater
# is not finely tuned to make use of additional energy from condensation of the water vapor.
# The csv file energy column is also interpreted to have gas in cubic meters when the 
# UseGasDataForHeatingEnergyEstimation parameter equals True.
#
# The script will calculate the required heating power at OutsideTemperatureOfInterest when taking into account a 
# maximum number of hours it can run a day defined by HoursForHeatingADay.
#
# It will also calculate the required maximum power of additional heating which will be required not to have 
# the house cooling down based on historic data since 1951 from ALL KNMI weather stations in the Netherlands.
# Based on this it will give an estimate on the amount of energy spend this way in kWh per year and the cost of
# it based on the CostPerkWh.
#
# Make sure you update the IP adress and port number of DomoticzHostAndPort so it reflects the correct
# Domoticz host for you.
#
# Other defines do not need changing.
# 
# This script uses the scipy library package, make sure it is installed.
#
##############################################################################################################
# Imports
##############################################################################################################
import datetime
try:
   #Python 3 
   from urllib.request import urlopen
   from urllib.error import HTTPError as HTTPError
   from urllib.error import URLError as URLError
except ImportError:
   #Python 2
   from urllib2 import urlopen
   from urllib2 import HTTPError as HTTPError
   from urllib2 import URLError as URLError
import ssl
import json
import collections
import csv
import pylab
from scipy.optimize import curve_fit
from scipy import argmax

##############################################################################################################
# Definitions                                                                                                #
##############################################################################################################

##############################################################################################################
# Config Start                                                                                               #
##############################################################################################################
DateStartAnalyses=datetime.date(2019,9,12)
DateEndAnalyses=datetime.date(2019,12,23)
#DateEndAnalyses=datetime.datetime.now().date()

# Indicate to use energy data from Domoticz in kWh, or use Gas data and convert that to kWh
UseGasDataForHeatingEnergyEstimation = False
EnergyPerCubicMeterGas = float(31.65/3.6)
CubicMetersGasADayForWarmWaterAndCooking = float(8/30)

#Indicate to use indoor temperature data, indoor electricity and estimated heat from ppl to estimate
#the average of the additional internal and external heat contributions.
EstimateAdditionalInternalAndExternalEnergy=True

#The S0 pulse kWh meters are not measuring exactly the same as the Enexis Meter, since that one determines
#the bill, I declare that measurement holy and have calibrated the others I have towards it. Make this factor
# 1.0 if you don't have such a calibration done, or change it to what is applicable for your own meter.
TotalUsageCorrectionFactor=float(0.987755312791)

#Define the Average Heat by ppl during the Day in kWh, for now the average of 14 hours present a day seems to 
#match and also 120 W per adult.
HeatFromWarmBodies = float(14.0*2.0*0.12)

# The outside temperature of interest is what is used to calculate the required Heating Capacity.
OutsideTemperatureOfInterest=float(-7.0)

# Hours Per Day for Heating is defined such that some time can be reserved to heatup a boiler of warm water
# or to indicate for example not to heat during the night.
HoursForHeatingADay = float(22.0)

# Price per kWh for the alternative energy to calculate the variabel cost of additional heating.
CostPerkWh = float(0.227)

#Indicate to use a csv file
UseCSVFileAsDataSource=False
CSVFile="MyDataFile.csv"

#Sensor IDx from Domoticz
OutDoorTemperatureSensorID="20"
InDoorTemperatureSensorID="69"
HeatingEnergySensorID="102"
GasSensorID="53"
TotalElectricSensorID="3"

# Domoticz Host IP
DomoticzHostAndPort="https://192.168.225.86:443/"
##############################################################################################################
# Config End                                                                                                 #
##############################################################################################################


#Domoticz URL constructs to get data
QueryPreFix=DomoticzHostAndPort+"json.htm?type=graph&sensor="
QueryPostFix="&range=year&method=1"
Percentage="Percentage&idx="
Temperature="temp&idx="
Counter="counter&idx="

#Domoticz URLs
OutdoorTemperatureDataURL=QueryPreFix+Temperature+OutDoorTemperatureSensorID+QueryPostFix
IndoorTemperatureDataURL=QueryPreFix+Temperature+InDoorTemperatureSensorID+QueryPostFix
HeatingEnergyDataURL=QueryPreFix+Percentage+HeatingEnergySensorID+QueryPostFix
GasUsageDataURL=QueryPreFix+Counter+GasSensorID+QueryPostFix
TotalElectricUsageDataURL=QueryPreFix+Counter+TotalElectricSensorID+QueryPostFix


#Creating a context to indicate to urllib(2) that we don't want SSL verification
#in case the domoticz setup does not have a valid CERT certificate.
UnverifiedContext = ssl._create_unverified_context()

#Plot properties
PlotMinTemperature=-15.0
PlotMaxTemperature=30.0 
#PlotMinPower will either be 0.0 or calculated from internal and external energy
#PlotMaxPower will be determined from calculated Maxpower @ PlotMinTemperature.

EnergyTemperatureList=[-30.0, -29.5, -29.0, -28.5, -28.0, -27.5, -27.0, -26.5, -26.0, -25.5, -25.0, -24.5, -24.0, -23.5, -23.0, -22.5, -22.0, -21.5, -21.0, -20.5, -20.0, -19.5, -19.0, -18.5, -18.0, -17.5, -17.0, -16.5, -16.0, -15.5, -15.0, -14.5, -14.0, -13.5, -13.0, -12.5, -12.0, -11.5, -11.0, -10.5, -10.0, -9.5, -9.0, -8.5, -8.0, -7.5, -7.0, -6.5, -6.0, -5.5, -5.0, -4.5, -4.0, -3.5, -3.0, -2.5, -2.0, -1.5, -1.0, -0.5, 0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0, 6.5, 7.0, 7.5, 8.0, 8.5, 9.0, 9.5, 10.0, 10.5, 11.0, 11.5, 12.0, 12.5, 13.0, 13.5, 14.0, 14.5, 15.0, 15.5, 16.0, 16.5, 17.0, 17.5, 18.0, 18.5, 19.0, 19.5, 20.0, 20.5, 21.0, 21.5, 22.0, 22.5, 23.0, 23.5, 24.0, 24.5, 25.0, 25.5, 26.0, 26.5, 27.0, 27.5, 28.0, 28.5, 29.0, 29.5, 30.0]
#Using the AVG Allyears distribution scaled to the temperature days integration value of the last 5 years average.
DaysPerYearAverageTemperature=[0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0177, 0.0, 0.05311, 0.05311, 0.05311, 0.0177, 0.0177, 0.07082, 0.10624, 0.05311, 0.12394, 0.14165, 0.03541, 0.38953, 0.23018, 0.40724, 0.37183, 0.37183, 0.51347, 0.54888, 0.79677, 0.97382, 1.29252, 1.31023, 1.36335, 2.08929, 2.05387, 2.46111, 2.7444, 3.50575, 3.98381, 4.28481, 4.62122, 5.02845, 5.66587, 6.26786, 6.33868, 6.46262, 7.27709, 8.10927, 8.19779, 8.78208, 9.01226, 8.87062, 8.33944, 8.30403, 8.09156, 7.64891, 8.42797, 7.13545, 7.68433, 7.40104, 7.9145, 7.56039, 8.37485, 8.26862, 8.58732, 8.88832, 8.39256, 9.49032, 8.41027, 8.48109, 8.09156, 6.74592, 6.58657, 5.93145, 4.83369, 4.49727, 4.2494, 3.3464, 2.97458, 2.69129, 1.75287, 1.55811, 1.62893, 1.31023, 1.13317, 0.70823, 0.79677, 0.47805, 0.53118, 0.24788, 0.301, 0.15935, 0.08853, 0.05311, 0.0177, 0.0177, 0.0177, 0.0]

##############################################################################################################
# Below are some lists containing the average over all KNMI weather stations of the daily average temperature 
# distribution over a year.
# These averages have been calculated over various time periods and binned per 0.5 C. They can be used to 
# calculate the predicted energy usage over a year for heating based on the fitted data.
# As can be seen from the lists, using the more recent years will lead to lower heating energy estimates since
# the average daily outdoor temperatures are indeed increasing ...
##############################################################################################################
# 
# AllScaledToLast5  DaysPerYearAverageTemperature=[0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0177, 0.0, 0.05311, 0.05311, 0.05311, 0.0177, 0.0177, 0.07082, 0.10624, 0.05311, 0.12394, 0.14165, 0.03541, 0.38953, 0.23018, 0.40724, 0.37183, 0.37183, 0.51347, 0.54888, 0.79677, 0.97382, 1.29252, 1.31023, 1.36335, 2.08929, 2.05387, 2.46111, 2.7444, 3.50575, 3.98381, 4.28481, 4.62122, 5.02845, 5.66587, 6.26786, 6.33868, 6.46262, 7.27709, 8.10927, 8.19779, 8.78208, 9.01226, 8.87062, 8.33944, 8.30403, 8.09156, 7.64891, 8.42797, 7.13545, 7.68433, 7.40104, 7.9145, 7.56039, 8.37485, 8.26862, 8.58732, 8.88832, 8.39256, 9.49032, 8.41027, 8.48109, 8.09156, 6.74592, 6.58657, 5.93145, 4.83369, 4.49727, 4.2494, 3.3464, 2.97458, 2.69129, 1.75287, 1.55811, 1.62893, 1.31023, 1.13317, 0.70823, 0.79677, 0.47805, 0.53118, 0.24788, 0.301, 0.15935, 0.08853, 0.05311, 0.0177, 0.0177, 0.0177, 0.0]
# 2018-2019         DaysPerYearAverageTemperature=[0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.5112, 0.0, 0.0, 0.0, 0.5112, 0.5112, 0.5112, 2.04482, 0.5112, 1.53361, 1.02241, 2.04482, 1.02241, 2.04482, 1.53361, 3.57843, 5.11204, 6.13445, 3.06723, 4.08964, 7.15686, 5.11204, 9.71289, 7.66807, 6.64566, 11.7577, 13.29132, 9.20168, 8.69048, 8.17927, 10.73529, 6.64566, 8.17927, 9.71289, 9.20168, 7.15686, 7.66807, 8.17927, 7.66807, 6.64566, 7.66807, 6.13445, 7.15686, 6.64566, 8.17927, 11.2465, 6.64566, 7.66807, 10.73529, 9.20168, 8.17927, 8.69048, 7.66807, 11.7577, 5.11204, 5.11204, 7.66807, 4.60084, 2.55602, 2.04482, 3.06723, 1.53361, 1.53361, 1.53361, 1.02241, 1.53361, 1.02241, 0.0, 1.02241, 0.0, 0.5112, 0.0, 0.5112, 0.5112, 0.0]
# 2012-2017         DaysPerYearAverageTemperature=[0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.16651, 0.0, 0.0, 0.0, 0.0, 0.16651, 0.0, 0.0, 0.0, 0.0, 0.16651, 0.49954, 0.33303, 0.0, 0.0, 0.33303, 0.16651, 1.1656, 0.66606, 1.33212, 0.83257, 0.66606, 1.49863, 2.49772, 2.99726, 2.83075, 2.66423, 3.33029, 3.99635, 4.82892, 4.49589, 5.32847, 6.49407, 5.32847, 6.49407, 7.9927, 10.82345, 9.49133, 9.99088, 9.49133, 11.32299, 9.1583, 11.82254, 11.82254, 8.32573, 9.65785, 9.49133, 6.8271, 8.65876, 9.82436, 7.65967, 9.65785, 9.1583, 9.65785, 8.65876, 9.49133, 9.82436, 9.32482, 11.65602, 9.82436, 8.15922, 6.66058, 7.49316, 7.65967, 5.99453, 4.16286, 4.66241, 3.33029, 4.16286, 3.33029, 1.99818, 2.3312, 1.66515, 0.66606, 0.49954, 0.83257, 0.49954, 0.83257, 0.0, 0.66606, 0.0, 0.49954, 0.0, 0.0, 0.0, 0.0, 0.0]
# 2006-2011         DaysPerYearAverageTemperature=[0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.16659, 0.0, 0.0, 0.0, 0.16659, 0.0, 0.16659, 0.16659, 0.33318, 0.49977, 0.16659, 0.16659, 0.49977, 0.99954, 1.99909, 1.66591, 2.33227, 1.8325, 2.83204, 2.33227, 2.66545, 2.99863, 4.83113, 4.99772, 6.49703, 5.49749, 3.4984, 6.33044, 7.1634, 5.66408, 5.99726, 6.33044, 6.49703, 7.66317, 6.33044, 10.6618, 9.66225, 11.16157, 10.49521, 6.99681, 7.1634, 9.32907, 7.66317, 7.49658, 9.66225, 6.99681, 8.66271, 8.66271, 10.49521, 9.82885, 9.16248, 9.66225, 10.49521, 10.32862, 10.16203, 12.16111, 10.16203, 9.99544, 6.83021, 5.83067, 5.66408, 5.66408, 4.66454, 4.99772, 2.33227, 1.33272, 1.49932, 2.49886, 1.16613, 1.66591, 0.49977, 1.33272, 0.49977, 0.66636, 0.33318, 0.49977, 0.33318, 0.0, 0.33318, 0.0, 0.0, 0.0, 0.0]
# 2000-2005         DaysPerYearAverageTemperature=[0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.16651, 0.0, 0.0, 0.0, 0.0, 0.0, 0.33303, 0.33303, 0.49954, 0.33303, 0.49954, 0.33303, 0.83257, 1.1656, 1.49863, 2.83075, 1.99818, 2.99726, 2.49772, 4.32938, 4.99544, 5.32847, 5.49498, 5.6615, 5.6615, 6.49407, 6.16104, 7.16013, 6.99361, 7.82619, 6.66058, 9.32482, 9.82436, 10.82345, 8.15922, 8.15922, 10.98996, 9.32482, 8.32573, 7.16013, 9.32482, 7.49316, 9.65785, 10.65693, 9.99088, 9.99088, 7.32664, 11.15648, 11.48951, 10.32391, 9.82436, 10.65693, 8.32573, 9.1583, 7.32664, 7.49316, 8.15922, 5.82801, 5.49498, 3.49681, 3.16378, 3.66332, 3.16378, 1.66515, 1.66515, 1.33212, 1.49863, 0.33303, 0.66606, 0.83257, 1.33212, 0.49954, 0.33303, 0.33303, 0.0, 0.0, 0.16651, 0.0, 0.0, 0.0]
# 1994-1999         DaysPerYearAverageTemperature=[0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.16659, 0.16659, 0.0, 0.0, 0.16659, 0.0, 0.0, 0.0, 0.16659, 0.33318, 0.16659, 0.49977, 0.16659, 0.16659, 0.83295, 0.83295, 0.83295, 0.99954, 1.16613, 0.99954, 2.33227, 1.49932, 1.8325, 2.33227, 2.83204, 2.33227, 3.99817, 3.16522, 3.83158, 3.16522, 5.16431, 4.83113, 6.16385, 7.32999, 7.66317, 4.16476, 8.99589, 8.66271, 11.66134, 8.66271, 9.49566, 8.66271, 7.99635, 11.32816, 11.16157, 10.49521, 9.16248, 7.32999, 10.99498, 7.82976, 8.49612, 6.83021, 11.16157, 8.8293, 10.82839, 8.99589, 9.99544, 9.16248, 7.82976, 9.66225, 8.99589, 7.1634, 7.32999, 7.99635, 4.66454, 4.66454, 3.66499, 3.16522, 3.33181, 2.49886, 2.66545, 1.33272, 1.99909, 2.49886, 2.49886, 1.66591, 1.8325, 0.99954, 0.66636, 0.49977, 0.16659, 0.0, 0.16659, 0.0, 0.0, 0.0, 0.0, 0.0]
# 1988-1993         DaysPerYearAverageTemperature=[0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.16651, 0.0, 0.0, 0.0, 0.33303, 0.0, 0.49954, 0.0, 0.0, 0.49954, 0.83257, 0.99909, 0.16651, 0.49954, 1.1656, 0.66606, 0.83257, 1.83166, 2.16469, 2.99726, 4.82892, 3.16378, 3.66332, 4.66241, 4.32938, 5.49498, 6.8271, 6.99361, 7.32664, 8.82527, 10.98996, 12.32208, 14.65328, 11.48951, 10.65693, 9.49133, 9.65785, 9.49133, 7.65967, 9.82436, 8.49224, 7.65967, 8.49224, 10.82345, 8.49224, 9.82436, 10.15739, 9.49133, 8.99179, 9.1583, 12.48859, 8.99179, 9.65785, 8.15922, 8.15922, 8.65876, 5.16195, 5.6615, 4.99544, 5.82801, 4.16286, 3.66332, 2.66423, 1.49863, 1.99818, 1.49863, 0.83257, 0.66606, 1.33212, 0.33303, 0.33303, 0.16651, 0.33303, 0.16651, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
# 1982-1987         DaysPerYearAverageTemperature=[0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.16659, 0.0, 0.33318, 0.0, 0.33318, 0.0, 0.0, 0.33318, 0.49977, 0.16659, 0.66636, 0.33318, 0.16659, 0.83295, 0.83295, 0.83295, 0.83295, 0.66636, 1.33272, 0.49977, 1.33272, 1.49932, 1.8325, 2.33227, 2.49886, 3.83158, 3.4984, 2.66545, 2.49886, 4.66454, 6.33044, 5.3309, 5.16431, 6.33044, 7.82976, 7.1634, 8.49612, 7.66317, 8.32953, 8.32953, 7.66317, 7.99635, 9.32907, 6.99681, 8.32953, 5.83067, 8.8293, 9.16248, 10.32862, 8.66271, 10.16203, 10.82839, 9.49566, 9.32907, 11.16157, 8.16294, 9.66225, 11.16157, 9.32907, 10.16203, 8.99589, 9.16248, 8.49612, 6.16385, 4.99772, 5.66408, 4.49795, 3.99817, 3.99817, 2.49886, 2.16568, 2.49886, 1.8325, 2.33227, 2.16568, 1.49932, 1.8325, 1.33272, 0.99954, 0.33318, 0.33318, 0.0, 0.0, 0.16659, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
# 1976-1981         DaysPerYearAverageTemperature=[0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.16651, 0.16651, 0.16651, 0.0, 0.16651, 0.16651, 0.16651, 0.0, 0.16651, 0.0, 0.83257, 0.33303, 0.83257, 0.66606, 0.99909, 0.83257, 0.99909, 0.66606, 1.99818, 2.49772, 1.99818, 1.83166, 3.16378, 2.66423, 4.66241, 4.16286, 5.49498, 5.6615, 6.49407, 5.32847, 6.99361, 6.49407, 7.16013, 8.32573, 7.49316, 8.15922, 8.32573, 7.82619, 10.15739, 9.49133, 10.32391, 10.49042, 6.8271, 5.82801, 7.9927, 10.82345, 7.82619, 8.32573, 7.9927, 8.65876, 10.15739, 9.82436, 8.65876, 11.15648, 12.82162, 8.82527, 15.15283, 10.82345, 8.15922, 8.15922, 4.66241, 6.16104, 6.16104, 3.33029, 3.82984, 3.66332, 2.16469, 2.83075, 2.49772, 0.49954, 1.49863, 1.1656, 0.99909, 0.83257, 0.33303, 0.33303, 0.33303, 0.16651, 0.16651, 0.33303, 0.33303, 0.16651, 0.0, 0.0, 0.0, 0.0, 0.0]
# 1970-1975         DaysPerYearAverageTemperature=[0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.16659, 0.0, 0.16659, 0.16659, 0.0, 0.66636, 0.16659, 0.66636, 0.33318, 0.49977, 0.0, 0.66636, 0.49977, 1.16613, 0.49977, 0.66636, 1.49932, 1.8325, 0.99954, 2.16568, 3.16522, 2.49886, 3.99817, 3.99817, 5.3309, 9.99544, 8.49612, 7.82976, 9.32907, 11.32816, 10.32862, 12.66089, 9.99544, 11.16157, 11.99452, 12.16111, 10.99498, 10.49521, 8.8293, 9.16248, 8.66271, 7.49658, 9.16248, 6.16385, 7.82976, 6.83021, 6.33044, 9.82885, 10.82839, 10.32862, 8.8293, 8.99589, 9.32907, 8.49612, 9.49566, 6.33044, 7.82976, 6.33044, 2.83204, 4.83113, 3.66499, 4.99772, 2.83204, 2.49886, 0.66636, 1.49932, 1.33272, 1.33272, 0.49977, 0.16659, 0.66636, 0.33318, 0.33318, 0.16659, 0.66636, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
# 1964-1969         DaysPerYearAverageTemperature=[0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.16651, 0.33303, 0.0, 0.0, 0.16651, 0.16651, 0.33303, 0.49954, 0.99909, 0.16651, 0.99909, 0.99909, 0.99909, 0.83257, 1.49863, 1.33212, 2.16469, 2.66423, 2.49772, 4.49589, 4.66241, 5.99453, 4.66241, 5.6615, 7.49316, 4.82892, 6.99361, 7.49316, 8.82527, 10.65693, 6.99361, 7.49316, 8.32573, 8.65876, 8.82527, 7.9927, 7.32664, 8.32573, 6.32755, 9.82436, 7.32664, 6.66058, 6.49407, 6.49407, 9.82436, 11.82254, 9.65785, 7.16013, 7.82619, 9.49133, 12.48859, 12.32208, 11.82254, 12.32208, 9.1583, 6.49407, 8.15922, 6.32755, 5.49498, 5.6615, 5.32847, 4.99544, 3.49681, 2.3312, 0.83257, 0.66606, 0.99909, 0.83257, 0.16651, 1.83166, 0.83257, 0.66606, 0.33303, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
# 1958-1963         DaysPerYearAverageTemperature=[0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.16851, 0.33703, 0.50554, 0.50554, 0.67405, 0.16851, 0.50554, 0.67405, 0.84257, 0.84257, 1.34811, 1.17959, 1.17959, 1.85365, 1.51662, 2.02216, 2.5277, 3.03324, 3.87581, 2.69621, 3.70729, 3.70729, 5.56094, 5.0554, 5.39243, 6.235, 5.89797, 5.39243, 6.06648, 7.5831, 5.89797, 7.41459, 9.09972, 9.09972, 6.06648, 9.77378, 8.42567, 8.08864, 9.77378, 7.07756, 9.26824, 8.93121, 7.07756, 8.59418, 7.75162, 10.27932, 10.1108, 9.43675, 11.2904, 8.42567, 11.62742, 13.64958, 11.96445, 12.6385, 10.44783, 7.41459, 6.90905, 7.92013, 4.54986, 3.87581, 4.21283, 1.85365, 3.03324, 3.37027, 1.68513, 2.02216, 1.51662, 1.01108, 0.84257, 0.33703, 0.16851, 0.0, 0.67405, 0.0, 0.0, 0.16851, 0.16851, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
# 1952-1957         DaysPerYearAverageTemperature=[0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.40873, 0.0, 0.0, 0.40873, 0.0, 0.40873, 0.40873, 0.0, 0.81747, 0.0, 1.63494, 0.0, 0.81747, 0.40873, 0.40873, 2.04367, 0.0, 1.63494, 0.0, 0.0, 0.0, 1.2262, 1.63494, 1.63494, 0.81747, 2.86114, 4.08735, 3.67861, 2.04367, 3.26988, 4.90482, 4.08735, 7.35722, 6.53975, 6.13102, 6.13102, 4.90482, 7.76596, 8.17469, 11.03583, 4.90482, 10.6271, 9.80963, 8.99216, 9.4009, 11.8533, 8.17469, 8.99216, 8.99216, 10.6271, 8.17469, 10.21837, 9.4009, 9.80963, 12.26204, 15.12318, 13.07951, 8.58343, 9.80963, 8.17469, 8.99216, 8.99216, 6.13102, 5.31355, 6.13102, 7.76596, 4.49608, 4.90482, 6.13102, 0.0, 2.04367, 2.04367, 2.45241, 0.0, 0.81747, 0.81747, 0.81747, 0.81747, 0.40873, 0.40873, 0.81747, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
# AVG AllYears      DaysPerYearAverageTemperature=[0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.01553, 0.01553, 0.0, 0.06214, 0.0466, 0.06214, 0.03107, 0.01553, 0.12427, 0.15534, 0.15534, 0.15534, 0.21747, 0.07767, 0.41942, 0.38835, 0.52815, 0.48155, 0.54369, 0.62136, 0.68349, 0.99417, 1.18058, 1.50679, 1.59999, 1.833, 2.56309, 2.60969, 2.99804, 3.43299, 4.20969, 4.64464, 5.21939, 5.32813, 5.82521, 6.38443, 7.05239, 7.54947, 7.17666, 8.18636, 8.91646, 9.24267, 9.46014, 9.89509, 9.59995, 9.28927, 9.08733, 9.00966, 8.59025, 9.24267, 7.82908, 8.52811, 8.48151, 9.36694, 8.93199, 9.46014, 9.52228, 9.52228, 10.40771, 10.0815, 10.87373, 10.0349, 9.49121, 8.59025, 7.54947, 7.39414, 6.30676, 5.31259, 5.06405, 4.36503, 3.6194, 3.21552, 2.68736, 1.7864, 1.63106, 1.63106, 1.27378, 1.22718, 0.73009, 0.77669, 0.54369, 0.46602, 0.21747, 0.27961, 0.15534, 0.07767, 0.0466, 0.01553, 0.01553, 0.01553, 0.0]
# AVG Last 50 years DaysPerYearAverageTemperature=[0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.01999, 0.0, 0.05997, 0.05997, 0.05997, 0.01999, 0.01999, 0.07996, 0.11995, 0.05997, 0.13994, 0.15993, 0.03998, 0.43981, 0.25989, 0.4598, 0.41982, 0.41982, 0.57975, 0.61973, 0.89961, 1.09952, 1.45936, 1.47935, 1.53933, 2.35897, 2.31898, 2.77878, 3.09864, 3.95826, 4.49803, 4.83788, 5.21771, 5.67751, 6.3972, 7.0769, 7.15686, 7.2968, 8.2164, 9.15599, 9.25594, 9.91565, 10.17554, 10.01561, 9.41587, 9.37589, 9.136, 8.63621, 9.51583, 8.05647, 8.6762, 8.35634, 8.93608, 8.53626, 9.45585, 9.33591, 9.69575, 10.0356, 9.47585, 10.7153, 9.49584, 9.5758, 9.136, 7.61666, 7.43674, 6.69706, 5.45761, 5.07777, 4.7979, 3.77834, 3.35853, 3.03867, 1.97913, 1.75923, 1.83919, 1.47935, 1.27944, 0.79965, 0.89961, 0.53976, 0.59974, 0.27988, 0.33985, 0.17992, 0.09996, 0.05997, 0.01999, 0.01999, 0.01999, 0.0]
# AVG Last 30 years DaysPerYearAverageTemperature=[0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.03332, 0.06665, 0.0, 0.0, 0.03332, 0.03332, 0.03332, 0.03332, 0.06665, 0.09997, 0.03332, 0.23327, 0.16662, 0.29992, 0.33324, 0.26659, 0.46654, 0.59984, 0.99973, 0.86643, 1.46626, 1.39962, 1.36629, 2.13275, 2.36602, 2.66594, 3.09915, 3.83228, 4.06555, 4.83201, 5.19858, 4.36547, 5.69844, 6.69816, 6.16498, 6.26495, 7.66457, 8.69762, 9.56405, 9.83064, 9.93061, 10.09723, 8.93089, 10.3305, 10.03059, 8.69762, 9.29745, 8.03113, 8.46435, 8.56432, 8.89756, 8.531, 9.63069, 9.43075, 9.26413, 9.13083, 9.56405, 10.06391, 9.3641, 10.06391, 9.43075, 8.73094, 8.09778, 7.19803, 6.63152, 5.66511, 5.33187, 3.93226, 3.69899, 3.39907, 2.63261, 1.79951, 1.99945, 1.69953, 1.49959, 0.89975, 1.0997, 0.66648, 0.83311, 0.39989, 0.36657, 0.19995, 0.1333, 0.09997, 0.03332, 0.03332, 0.03332, 0.0]
# AVG Last 20 years DaysPerYearAverageTemperature=[0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.04999, 0.0, 0.0, 0.0, 0.04999, 0.04999, 0.0, 0.04999, 0.04999, 0.0, 0.09999, 0.19997, 0.24997, 0.24997, 0.14998, 0.29996, 0.34995, 0.84988, 0.94987, 1.34982, 1.34982, 1.34982, 2.24969, 2.29968, 2.69963, 2.74962, 3.74949, 4.3994, 5.24928, 5.39926, 4.3994, 5.64923, 6.74908, 5.74921, 6.84906, 7.14902, 8.29886, 8.29886, 8.99877, 9.89864, 10.49856, 9.34872, 10.1986, 9.59869, 8.24887, 9.14875, 8.19888, 7.79893, 8.49884, 8.7488, 8.84879, 9.14875, 9.64868, 8.64882, 9.39871, 9.84865, 9.99863, 9.94864, 10.39858, 9.84865, 9.29873, 8.09889, 7.34899, 7.34899, 5.99918, 5.74921, 4.3494, 3.94946, 3.79948, 2.79962, 1.79975, 2.14971, 1.54979, 1.29982, 0.54992, 0.99986, 0.64991, 0.99986, 0.34995, 0.44994, 0.29996, 0.14998, 0.14998, 0.04999, 0.04999, 0.04999, 0.0]
# AVG Last 15 years DaysPerYearAverageTemperature=[0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.06668, 0.0, 0.0, 0.0, 0.06668, 0.06668, 0.0, 0.0, 0.06668, 0.0, 0.13336, 0.26672, 0.33339, 0.20004, 0.06668, 0.26672, 0.33339, 1.00018, 1.13354, 1.53361, 1.40026, 1.33358, 2.26708, 2.46712, 2.60047, 3.00055, 3.53398, 4.13409, 5.53434, 5.40099, 3.86737, 5.60102, 6.86792, 5.46767, 6.73456, 7.20132, 8.06814, 8.66825, 9.00164, 9.73511, 10.26854, 9.60175, 10.66862, 9.20168, 8.13482, 9.135, 8.40153, 7.13464, 9.26836, 8.60157, 8.46821, 8.80161, 9.60175, 8.86829, 8.80161, 9.86847, 10.06851, 10.00183, 10.33522, 10.33522, 9.135, 8.33486, 7.06796, 6.86792, 6.20113, 5.86774, 4.46748, 4.20077, 4.00073, 2.93387, 1.86701, 2.2004, 1.73365, 1.20022, 0.60011, 1.13354, 0.53343, 0.80015, 0.33339, 0.53343, 0.26672, 0.20004, 0.20004, 0.0, 0.06668, 0.06668, 0.0]
# AVG Last 10 years DaysPerYearAverageTemperature=[0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.10005, 0.0, 0.0, 0.0, 0.0, 0.10005, 0.0, 0.0, 0.0, 0.0, 0.10005, 0.40022, 0.40022, 0.30016, 0.0, 0.30016, 0.40022, 1.30071, 1.1006, 1.60088, 1.40077, 1.60088, 2.10115, 2.40132, 2.80154, 3.00164, 3.00164, 3.80208, 5.00274, 5.20285, 3.90214, 5.70313, 6.70367, 5.00274, 7.40406, 7.20395, 9.00493, 9.3051, 9.70532, 9.90543, 10.60581, 9.10499, 11.00603, 9.80537, 8.10444, 9.90543, 8.80482, 6.80373, 8.2045, 8.80482, 7.304, 9.00493, 8.90488, 9.3051, 8.40461, 9.3051, 9.40515, 9.60526, 10.10554, 10.10554, 9.10499, 8.10444, 7.70422, 7.50411, 6.2034, 5.50302, 4.60252, 3.70203, 4.50247, 3.20175, 1.90104, 2.30126, 1.70093, 0.80044, 0.70038, 1.00055, 0.70038, 0.80044, 0.20011, 0.60033, 0.30016, 0.30016, 0.20011, 0.0, 0.10005, 0.10005, 0.0]
# AVG Last  5 years DaysPerYearAverageTemperature=[0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.20033, 0.0, 0.0, 0.0, 0.20033, 0.20033, 0.40066, 1.80296, 0.80132, 0.60099, 1.80296, 2.00329, 2.00329, 2.40395, 2.20362, 4.40724, 5.00823, 6.61087, 4.40724, 5.00823, 6.61087, 6.00988, 7.81284, 8.2135, 8.61416, 10.81778, 11.21844, 9.81614, 9.61581, 7.41218, 12.01976, 9.41548, 8.41383, 9.61581, 9.01482, 6.8112, 9.41548, 9.81614, 7.21186, 7.81284, 8.2135, 9.21515, 6.8112, 7.81284, 7.61251, 9.21515, 9.41548, 8.81449, 10.41712, 8.2135, 7.81284, 9.61581, 6.41054, 6.41054, 4.40724, 4.8079, 6.00988, 4.00659, 2.00329, 1.80296, 2.20362, 1.00165, 1.00165, 1.40231, 0.80132, 1.20198, 0.40066, 0.60099, 0.40066, 0.0, 0.20033, 0.0, 0.20033, 0.20033, 0.0]
# AVG Last  3 years DaysPerYearAverageTemperature=[0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.33456, 0.0, 0.0, 0.0, 0.33456, 0.33456, 0.66911, 2.34189, 0.66911, 1.00367, 2.34189, 3.011, 1.67278, 2.00733, 2.00733, 4.01467, 4.34922, 6.69111, 3.34555, 5.01833, 5.68744, 5.68744, 7.02566, 9.033, 8.02933, 11.04033, 13.04766, 8.69844, 9.033, 7.69478, 11.04033, 10.03666, 8.69844, 8.02933, 8.69844, 7.02566, 9.033, 8.36389, 5.68744, 7.02566, 7.02566, 7.69478, 7.02566, 6.69111, 9.033, 10.03666, 9.36755, 8.69844, 11.37489, 9.033, 8.69844, 9.033, 7.36022, 9.70211, 4.34922, 4.34922, 7.02566, 4.01467, 2.00733, 1.67278, 2.34189, 1.67278, 1.33822, 1.33822, 1.00367, 1.00367, 0.66911, 0.0, 0.66911, 0.0, 0.33456, 0.0, 0.33456, 0.33456, 0.0]
# AVG Last  2 years DaysPerYearAverageTemperature=[0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.50275, 0.0, 0.0, 0.0, 0.50275, 0.50275, 0.50275, 2.01102, 0.50275, 1.50826, 1.00551, 2.01102, 1.00551, 2.01102, 1.50826, 3.51928, 5.02755, 6.03306, 3.51928, 4.52479, 7.03857, 5.02755, 9.55234, 7.54132, 7.03857, 12.06612, 13.07163, 9.04959, 9.55234, 8.04408, 11.56336, 8.04408, 8.04408, 9.55234, 9.04959, 7.03857, 8.04408, 8.04408, 7.54132, 6.53581, 7.54132, 6.03306, 7.03857, 6.53581, 8.04408, 11.06061, 6.53581, 7.54132, 10.55785, 9.04959, 8.04408, 8.54683, 7.54132, 11.56336, 5.02755, 5.02755, 7.54132, 4.52479, 2.51377, 2.01102, 3.01653, 1.50826, 1.50826, 1.50826, 1.00551, 1.50826, 1.00551, 0.0, 1.00551, 0.0, 0.50275, 0.0, 0.50275, 0.50275, 0.0]
# Last year         DaysPerYearAverageTemperature=[0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 2.02216, 1.01108, 1.01108, 0.0, 2.02216, 2.02216, 1.01108, 1.01108, 2.02216, 7.07756, 3.03324, 1.01108, 2.02216, 6.06648, 4.04432, 11.12188, 9.09972, 8.08864, 10.1108, 14.15512, 12.13296, 14.15512, 10.1108, 14.15512, 8.08864, 10.1108, 12.13296, 7.07756, 7.07756, 10.1108, 5.0554, 7.07756, 6.06648, 7.07756, 10.1108, 7.07756, 5.0554, 12.13296, 13.14404, 9.09972, 11.12188, 12.13296, 10.1108, 6.06648, 9.09972, 4.04432, 9.09972, 2.02216, 3.03324, 4.04432, 1.01108, 2.02216, 1.01108, 3.03324, 1.01108, 1.01108, 2.02216, 2.02216, 1.01108, 1.01108, 0.0, 0.0, 0.0, 1.01108, 0.0, 1.01108, 0.0, 0.0]
#
##############################################################################################################


##############################################################################################################
# Functions
##############################################################################################################

def DataInAnalysesWindow(DateString): 
   Year=int(DateString.split("-")[0])
   Month=int(DateString.split("-")[1])
   Day=int(DateString.split("-")[2])
   CompareDate=datetime.date(Year,Month,Day)
   return (DateStartAnalyses <= CompareDate and CompareDate <= DateEndAnalyses)

def CalculateDaysPerYearBelowTemperature(Temperature):
   LowValue=0.0
   HighValue = 0.0
   HighValueTemperature = 0.0
   HighValueFound = False
   for temp,day in zip(EnergyTemperatureList,DaysPerYearAverageTemperature):
      if temp < Temperature:
         LowValue=LowValue+day
      elif temp == Temperature:
         LowValue=LowValue+day
         HighValue=LowValue
         HighValueTemperature = temp
         HighValueFound = True
      else:
         if not HighValueFound:
            HighValue = LowValue+day
            HighValueTemperature = temp
            HighValueFound = True
   Fraction=1.0-((HighValueTemperature-Temperature)/0.5)
   DaysPerYear=LowValue+(Fraction*(HighValue-LowValue))
   return(DaysPerYear)

def GetOutdoorTemp():
   #print('>GetOutdoorTemp')
   ReturnList=[]
   try:
      Page=urlopen(OutdoorTemperatureDataURL, context=UnverifiedContext)
      DataString=Page.read()
      JsonData=json.loads(DataString.decode('utf-8'))
      TemperatureList=JsonData['result']
      #Filter out only the items with proper values
      for item in TemperatureList:
         if 'd' in item:
            if DataInAnalysesWindow(item['d']):
               if 'ta' in item:
                  ReturnList.append(item)
   except (HTTPError, URLError) as fout:
      print("Error: "+str(fout)+" URL: "+OutdoorTemperatureDataURL)
   #print('<GetOutdoorTemp:'+ReturnList.__str__())
   return(ReturnList)

def GetIndoorTemp():
   #print('>GetIndoorTemp')
   ReturnList=[]
   try:
      Page=urlopen(IndoorTemperatureDataURL, context=UnverifiedContext)
      DataString=Page.read()
      JsonData=json.loads(DataString.decode('utf-8'))
      TemperatureList=JsonData['result']
      #Filter out only the items with proper values
      for item in TemperatureList:
         if 'd' in item:
            if DataInAnalysesWindow(item['d']):
               if 'ta' in item:
                  ReturnList.append(item)
   except (HTTPError, URLError) as fout:
      print("Error: "+str(fout)+" URL: "+IndoorTemperatureDataURL)
   #print('<GetIndoorTemp:'+ReturnList.__str__())
   return(ReturnList)

def GetHeatingEnergy():
   #print('>GetHeatingEnergy')
   ReturnList=[]
   try:
      Page=urlopen(HeatingEnergyDataURL, context=UnverifiedContext)
      DataString=Page.read()
      JsonData=json.loads(DataString.decode('utf-8'))
      HeatingEnergyList=JsonData['result']
      #Filter out only the items with proper values
      for item in HeatingEnergyList:
         if 'd' in item:
            if DataInAnalysesWindow(item['d']):
               if 'v_max' and 'v_min' in item:
                  ReturnList.append(item)
   except (HTTPError, URLError) as fout:
      print("Error: "+str(fout)+" URL: "+HeatingEnergyDataURL)
   #print('<GetHeatingEnergy:'+ReturnList.__str__())
   return(ReturnList)

def GetTotalUsedElectricEnergy():
   #print('>GetTotalUsedElectricEnergy')
   ReturnList=[]
   try:
      Page=urlopen(TotalElectricUsageDataURL, context=UnverifiedContext)
      DataString=Page.read()
      JsonData=json.loads(DataString.decode('utf-8'))
      EnergyList=JsonData['result']
      #Filter out only the items with proper values
      for item in EnergyList:
         if 'd' in item:
            if DataInAnalysesWindow(item['d']):
               if 'v' in item:
                  ReturnList.append(item)
   except (HTTPError, URLError) as fout:
      print("Error: "+str(fout)+" URL: "+TotalElectricUsageDataURL)
   #print('<GetTotalUsedElectricEnergy:'+ReturnList.__str__())
   return(ReturnList)

def ProcessElectricEnergy(RawList):
   #print('>ProcessElectricEnergy')
   ReturnList=[]
   for entry in RawList:
      ValueDict = dict()
      if 'd' in entry:
         ValueDict['d'] = entry['d']
      if 'v' in entry:
         ValueDict['v'] = round(TotalUsageCorrectionFactor*float(entry['v']),3)
      ReturnList.append(ValueDict)
   #print('<ProcessElectricEnergy:'+ReturnList.__str__())
   return(ReturnList)

def GetHeatingEnergyFromGasUsage():
   #print('>GetHeatingEnergyFromGasUsage')
   ReturnList=[]
   try:
      Page=urlopen(GasUsageDataURL, context=UnverifiedContext)
      DataString=Page.read()
      JsonData=json.loads(DataString.decode('utf-8'))
      HeatingEnergyList=JsonData['result']
      #Filter out only the items with proper values
      for item in HeatingEnergyList:
         if 'd' in item:
            if DataInAnalysesWindow(item['d']):
               if 'v' in item:
                  ReturnList.append(item)
   except (HTTPError, URLError) as fout:
      print("Error: "+str(fout)+" URL: "+GasUsageDataURL)
   #print('<GetHeatingEnergyFromGasUsage:'+ReturnList.__str__())
   return(ReturnList)

def ConvertGasTokWh(Gas):
   return(((Gas-CubicMetersGasADayForWarmWaterAndCooking)*EnergyPerCubicMeterGas))

def CreateDictionaryOfData (IndoorData, OutdoorData, HeatingEnergyData, ElectricEnergyData):
   OutputDict=collections.OrderedDict()
   if (EstimateAdditionalInternalAndExternalEnergy):
      for item in IndoorData:
         ValueDict = dict()
         ValueDict['IndoorTemperature']=item['ta']
         if item['d'] in OutputDict:
            OutputDict[item['d']].append(ValueDict)
         else:
            ValueList = []
            ValueList.append(ValueDict)
            OutputDict[item['d']]=ValueList
      for item in ElectricEnergyData:
         ValueDict = dict()
         ValueDict['ElectricEnergy']=item['v']
         if item['d'] in OutputDict:
            OutputDict[item['d']].append(ValueDict)
         else:
            ValueList = []
            ValueList.append(ValueDict)
            OutputDict[item['d']]=ValueList
   for item in OutdoorData:
      ValueDict = dict()
      ValueDict['OutdoorTemperature']=item['ta']
      if item['d'] in OutputDict:
         OutputDict[item['d']].append(ValueDict)
      else:
         ValueList = []
         ValueList.append(ValueDict)
         OutputDict[item['d']]=ValueList
   if (UseGasDataForHeatingEnergyEstimation):
      for item in HeatingEnergyData:
         ValueDict = dict()
         ValueDict['Energy']=ConvertGasTokWh(float(item['v'])).__str__()
         if item['d'] in OutputDict:
            OutputDict[item['d']].append(ValueDict)
         else:
            ValueList = []
            ValueList.append(ValueDict)
            OutputDict[item['d']]=ValueList
   else:
      for item in HeatingEnergyData:
         ValueDict = dict()
         ValueDict['Energy']=(float(item['v_max'])-float(item['v_min'])).__str__()
         if item['d'] in OutputDict:
            OutputDict[item['d']].append(ValueDict)
         else:
            ValueList = []
            ValueList.append(ValueDict)
            OutputDict[item['d']]=ValueList
   return(OutputDict)

def GetDataListsFromDictionary (Measurements):
   #Initialize Previous Values, to be used when entry is missing.
   HeatingPowerSamples=[]
   IndoorTempSamples=[]
   OutdoorTempSamples=[]
   ElectricEnergySamples=[]
   PreviousIndoorTemperature = 0.0
   PreviousOutdoorTemperature = 0.0
   PreviousHeatingPower = 0.0
   PreviousElectricEnergy = 0.0
   for Date, ValueList in Measurements.items():
      for Value in ValueList:
         if 'Energy' in Value:
            PreviousHeatingPower = float(Value['Energy'])/HoursForHeatingADay
         if 'OutdoorTemperature' in Value:
            PreviousOutdoorTemperature = float(Value['OutdoorTemperature'])
         if 'ElectricEnergy' in Value:
            PreviousElectricEnergy = float(Value['ElectricEnergy'])
         if 'IndoorTemperature' in Value:
            PreviousIndoorTemperature = float(Value['IndoorTemperature'])
      ElectricEnergySamples.append(PreviousElectricEnergy)
      HeatingPowerSamples.append(PreviousHeatingPower)
      IndoorTempSamples.append(PreviousIndoorTemperature)
      OutdoorTempSamples.append(PreviousOutdoorTemperature)
   return(IndoorTempSamples, OutdoorTempSamples, HeatingPowerSamples, ElectricEnergySamples)

def GetDataListsFromCSVFile():
   HeatingPowerSamples=[]
   OutdoorTempSamples=[]
   IndoorTempSamples=[]
   ElectricitySamples=[]
   with open(CSVFile) as csvfile:
      readCSV=csv.reader(csvfile, delimiter=',')
      for row in readCSV:
         if row[0].strip() and row[1].strip():
            OutdoorTempSamples.append(float(row[0]))
            if UseGasDataForHeatingEnergyEstimation:
               HeatingPower=ConvertGasTokWh(float(row[1]))/HoursForHeatingADay
            else:
               HeatingPower= float(row[1])/HoursForHeatingADay  
            HeatingPowerSamples.append(HeatingPower)
         if EstimateAdditionalInternalAndExternalEnergy:
            if row[2].strip() and row[3].strip():
               IndoorTempSamples.append(float(row[2]))
               ElectricitySamples.append(round(TotalUsageCorrectionFactor*float(row[3]),3))
   return(OutdoorTempSamples, HeatingPowerSamples, IndoorTempSamples, ElectricitySamples)
   
def FitEnergyVsTOutsideFunction(OutdoorTempSamples, Gain, Offset):
   return(OutdoorTempSamples*Gain + Offset)

def FitHeatingAndTemperatureData(OutdoorTempSamples, HeatingPowerSamples):
   FitParams = curve_fit(FitEnergyVsTOutsideFunction, OutdoorTempSamples, HeatingPowerSamples)
   HeatingPowerGain=FitParams[0][0]
   HeatingPowerOffset=FitParams[0][1]
   #corrrelation
   CorrPower=[]
   for temperature in OutdoorTempSamples:
      Power=HeatingPowerGain*temperature+HeatingPowerOffset
      CorrPower.append(Power)
   Correlation=round((pylab.corrcoef(CorrPower, HeatingPowerSamples)[0][1]),3)
   return(HeatingPowerGain, HeatingPowerOffset,Correlation)

def PlotData():
   Figure, PlotList = pylab.subplots(3,1, figsize=(8,16))
   PlotList[0].xaxis.set_visible(False)
   PlotList[0].yaxis.set_visible(False)
   PlotBaseData(PlotList[1])
   if EstimateAdditionalInternalAndExternalEnergy:
      PlotExternalEnergyData(PlotList[1])
   EnergyUsageString=PlotEnergyDistribution(PlotList[2])
   PlotText(PlotList[0],EnergyUsageString)
   Figure.set_tight_layout(True)
   pylab.show()
   #pylab.savefig('Testje.pdf')

def PlotText(PlotReference,EnergyUsageString):
   #Define A Grid to plot the text labels in
   PlotReference.axis([0,20.0,0,10.0])
   PlotLineBase=[0,20]
   PlotLineResultsValues=[7.8,7.8]
   PlotReference.plot(PlotLineBase,PlotLineResultsValues, 'k-')
   # Create the label texts for the plot 
   if UseGasDataForHeatingEnergyEstimation:
      EnergyTypeString = "(Gas Based)"
   else:
      EnergyTypeString = "(Power Meter Based)"
   if UseCSVFileAsDataSource:
      AnalysesWindowString="Analysed File: "+CSVFile+" "
   else:
      StartString=DateStartAnalyses.strftime("%A %B %d %Y")
      StopString=DateEndAnalyses.strftime("%A %B %d %Y")
      AnalysesWindowString="Analysed: "+StartString+" - "+StopString+" "
   HeatingLimitString="Heating Required until Toutdoor :"
   HeatingLimitValueString=round(HeatingLimit,2).__str__()+" C"
   OutsideTemperatureOfInterestString=OutsideTemperatureOfInterest.__str__()+" C"
   PowerRequiredTemperatureOffInterestString="Heating Power Required @ "+OutsideTemperatureOfInterest.__str__()+" C: "
   PowerRequiredTemperatureOffInterestValueString=round(HeatingPowerTemperatureOffInterest,2).__str__()+" kW"
   AlternativeHeatingPowerString="When Heatpump can still deliver "+round(HeatingPowerTemperatureOffInterest,2).__str__()+" kW @ -15 C,\n"+DaysAlternativePower.__str__()+" Days/Year Alternative Power Required Below "+OutsideTemperatureOfInterestString+" of "+AlternativePower.__str__()+" kW \nfor a total of "+AlternativeEnergy.__str__()+" kWh ("+AlternativeEnergyCost.__str__()+" Euro)"
   AlternativeHeatingPowerValueString=AlternativePower.__str__()+" kW"
   if EstimateAdditionalInternalAndExternalEnergy:
      HeatFromWarmBodiesString="Heat From People per day: "+HeatFromWarmBodies.__str__()+"kWh\n"
   else:
      HeatFromWarmBodiesString="\n"
   SettingValuesString="Used Settings:\nHours / Day Reserved for Heating: "+HoursForHeatingADay.__str__()+"\n"+HeatFromWarmBodiesString+"Outside Temperature Of Interest: "+OutsideTemperatureOfInterest.__str__()+" C"
   PowerFitFunctionString="Results:\nFiting function:   Power = "+round(HeatingPowerPerxxhGain,5).__str__()+" * temperature + "+round(HeatingPowerPerxxhOffset,3).__str__()+"  (r="+Correlation.__str__()+")"
   
   PlotReference.set_title("Heating Power VS OutDoor Temperature. "+EnergyTypeString+"\n"+AnalysesWindowString)
   
   PlotReference.text(1,8.0,SettingValuesString)
   PlotReference.text(1,6.0,PowerFitFunctionString)
   LabelOffsetY=0.5
   PlotReference.text(1,(6-(LabelOffsetY+0.3)),HeatingLimitString)
   PlotReference.text(12,(6-(LabelOffsetY+0.3)),HeatingLimitValueString)
   PlotReference.text(1,(6-(2*LabelOffsetY+0.3)),PowerRequiredTemperatureOffInterestString)
   PlotReference.text(12,(6-(2*LabelOffsetY+0.3)),PowerRequiredTemperatureOffInterestValueString)
   PlotReference.text(1,(6-(5*LabelOffsetY+0.3)),AlternativeHeatingPowerString)
   PlotReference.text(1,(6-(6.5*LabelOffsetY+0.3)),EnergyUsageString)
   if EstimateAdditionalInternalAndExternalEnergy:
      AdditionalPowerValueString="Estimated Average Additional Heating Power = "+round(abs(PowerPointAtIndoorTemperature),3).__str__()+" kW, of which:\n   Internal Heat From Electricity and People = "+round(abs(AverageInternalPower),3).__str__()+" kW \n   External Heat From Sun = "+round(abs(AverageExternalPower),3).__str__()+" kW"
      PlotReference.text(1,(6-(9.5*LabelOffsetY+0.3)),AdditionalPowerValueString)
  

def PlotBaseData(PlotReference):

   # Create points to draw the lines for the temperature of interest and the calculated required power.
   CrossSectionTempLine=[0,HeatingPowerTemperatureOffInterest]
   CrossSectionPowerLine=[PlotMinTemperature,OutsideTemperatureOfInterest]
   TempBaseLine=[OutsideTemperatureOfInterest,OutsideTemperatureOfInterest]
   PowerBaseLine=[HeatingPowerTemperatureOffInterest,HeatingPowerTemperatureOffInterest]

   #Calculate the Offsets for the text labels in the plot
   LabelOffsetY=(PlotMaxPower/24.0)
   
   # Make the plot.
   PlotReference.plot(OutdoorTempSamples, HeatingPowerSamples, 'r.', label="Measured HeatingPower")
   PlotReference.plot(HeatingPowerFitlineTemp, HeatingPowerFitline, 'b-', label="Fitted HeatingPower")
   PlotReference.plot(CrossSectionPowerLine, PowerBaseLine, 'k--')
   PlotReference.plot(TempBaseLine, CrossSectionTempLine, 'k--')
   PlotReference.plot((PlotMinTemperature,PlotMaxTemperature), (0.0,0.0), 'k-')
   PlotReference.axis([PlotMinTemperature,PlotMaxTemperature,PlotMinPower,PlotMaxPower])
   ylabeltext="Required Heating Power / "+HoursForHeatingADay.__str__()+"h [kW]"
   PlotReference.set_xlabel("OutDoor Temperature [C]")
   PlotReference.set_ylabel(ylabeltext)
   PowerRequiredTemperatureOffInterestValueString=round(HeatingPowerTemperatureOffInterest,2).__str__()+" kW"
   OutsideTemperatureOfInterestString=OutsideTemperatureOfInterest.__str__()+" C"
   PlotReference.text((PlotMinTemperature+0.1),(HeatingPowerTemperatureOffInterest+0.1),PowerRequiredTemperatureOffInterestValueString)
   PlotReference.text((OutsideTemperatureOfInterest+0.1),0.3,OutsideTemperatureOfInterestString)
   PlotReference.legend(loc="upper right")
   #PlotReference.spines['bottom'].set_position('zero')
   #PlotReference.spines['left'].set_position('zero')
   PlotReference.grid(True)
   
def PlotEnergyDistribution(PlotReference):
   ScaledEnergyVsAverageTemperature=[]
   for temp, days in zip(EnergyTemperatureList, DaysPerYearAverageTemperature):
      if temp < HeatingLimit:
         ScaledEnergyVsAverageTemperature.append(((HeatingPowerPerxxhGain*temp)+HeatingPowerPerxxhOffset)*days*HoursForHeatingADay)
      else:
         ScaledEnergyVsAverageTemperature.append(0.0)
   #Now Scale the calculated energyback to fit the plot, max energy = max days
   EnergyScaleFactor=max(DaysPerYearAverageTemperature)/max(ScaledEnergyVsAverageTemperature)
   #EnergyScaleFactor=1.0
   
   for index, Energy in enumerate(ScaledEnergyVsAverageTemperature):
      ScaledEnergyVsAverageTemperature[index]=Energy*EnergyScaleFactor
      
   MaxEnergyIndex=argmax(ScaledEnergyVsAverageTemperature)
   MaxEnergy=int((ScaledEnergyVsAverageTemperature[MaxEnergyIndex])/EnergyScaleFactor)
   MaxScaledEnergy=int(ScaledEnergyVsAverageTemperature[MaxEnergyIndex])
   MaxEnergyXOffset=EnergyTemperatureList[MaxEnergyIndex]
   MaxEnergyYOffset=(ScaledEnergyVsAverageTemperature[MaxEnergyIndex]+0.3)

   TotalEnergy=int(sum(ScaledEnergyVsAverageTemperature)/EnergyScaleFactor)
   PlotReference.plot(EnergyTemperatureList,ScaledEnergyVsAverageTemperature,'-', label="Scaled Estimated Heating Energy Distribution")
   PlotReference.plot(EnergyTemperatureList, DaysPerYearAverageTemperature,'-.', label="Average Daily Temperature Distribution")
   MaxEnergyString="Max="+MaxEnergy.__str__()+" kWh @"+MaxEnergyXOffset.__str__()+"C,\nEstimated Year Total="+TotalEnergy.__str__()+" kWh"
   PlotReference.text(MaxEnergyXOffset-5,MaxEnergyYOffset,MaxEnergyString)
   PlotReference.axis([PlotMinTemperature,30,0,(1.65*MaxScaledEnergy)])
   PlotReference.legend(loc="upper left")
   PlotReference.grid(True)
   PlotReference.set_xlabel("OutDoor Temperature [C]")
   EnergyUsageString="Estimated Year Total Energy Required for Heating ="+(TotalEnergy/1000.0).__str__()+" MWh"
   return(EnergyUsageString)

def PlotExternalEnergyData(PlotReference):
   # Create points to draw the lines for the internal and external Power.
   CrossSectionIndoorTempLine=[2.0, PowerPointAtIndoorTemperature]
   IndoorTempBaseLine=[AverageIndoorTemp, AverageIndoorTemp]
   PlotReference.plot(IndoorTempBaseLine, CrossSectionIndoorTempLine, 'k--')
   IndoorTemperatureValueString="Average\nTindoor="+round(AverageIndoorTemp,1).__str__()+" C"
   PlotReference.text((AverageIndoorTemp-5.0),(2.2),IndoorTemperatureValueString)

   HeatingPowerPlusInternalFitline=[(HeatingPowerMax-AverageInternalPower),(HeatingPowerMin-AverageInternalPower)]
   HeatingPowerPlusInternalPlusExternalFitline=[(HeatingPowerMax-AverageInternalPower-AverageExternalPower),(HeatingPowerMin-AverageInternalPower-AverageExternalPower)]
   PlotReference.plot(HeatingPowerFitlineTemp, HeatingPowerPlusInternalFitline, 'b-.', label="+ Internal Power")
   PlotReference.plot(HeatingPowerFitlineTemp, HeatingPowerPlusInternalPlusExternalFitline, 'b:', label="+ Internal & External Power")
   PlotReference.legend(loc="upper right")




##############################################################################################################
# Main
##############################################################################################################
HeatingLimit = 0.0
if not EstimateAdditionalInternalAndExternalEnergy:
   ElectricEnergyData = []
   IndoorData = []

# Get the data from Domoticz or csv file
if UseCSVFileAsDataSource:
   OutdoorTempSamples, HeatingPowerSamples, IndoorTempSamples, ElectricitySamples = GetDataListsFromCSVFile()
else:
   OutdoorData = GetOutdoorTemp()
   if UseGasDataForHeatingEnergyEstimation:
      HeatingEnergyData = GetHeatingEnergyFromGasUsage()
   else:
      HeatingEnergyData = GetHeatingEnergy()
   if EstimateAdditionalInternalAndExternalEnergy:
      RawElectricEnergyData = GetTotalUsedElectricEnergy()
      ElectricEnergyData = ProcessElectricEnergy(RawElectricEnergyData)
      IndoorData = GetIndoorTemp()
   #Create One dictionary of measurements, date+time based.
   Measurements=CreateDictionaryOfData(IndoorData, OutdoorData, HeatingEnergyData, ElectricEnergyData)
   # Now Create the lists of data for the fitting algorithm to use.
   IndoorTempSamples, OutdoorTempSamples, HeatingPowerSamples, ElectricitySamples = GetDataListsFromDictionary(Measurements)

# Fit a straight line over the energy points and calculate some points for the plot.
HeatingPowerPerxxhGain, HeatingPowerPerxxhOffset, Correlation = FitHeatingAndTemperatureData(OutdoorTempSamples, HeatingPowerSamples)

HeatingPowerMax=HeatingPowerPerxxhGain*PlotMinTemperature+HeatingPowerPerxxhOffset
HeatingPowerMin=HeatingPowerPerxxhGain*PlotMaxTemperature+HeatingPowerPerxxhOffset
PlotMaxPower = round(HeatingPowerMax,2)+1.5
HeatingPowerFitline=[HeatingPowerMax,HeatingPowerMin]
HeatingPowerFitlineTemp=[PlotMinTemperature,PlotMaxTemperature]
HeatingLimit=(-1.0*HeatingPowerPerxxhOffset)/HeatingPowerPerxxhGain

#When Outside Temperature of interest is higher than the temperature that does no require heating anymore,
# make it the same, to prevent negative heating capacity values 
if HeatingLimit < OutsideTemperatureOfInterest:
   OutsideTemperatureOfInterest = round(HeatingLimit,2)

DaysAlternativePower=round(CalculateDaysPerYearBelowTemperature(OutsideTemperatureOfInterest),1)
HeatingPowerMinus15=HeatingPowerPerxxhGain*-15.0+HeatingPowerPerxxhOffset
HeatingPowerTemperatureOffInterest=HeatingPowerPerxxhGain*OutsideTemperatureOfInterest+HeatingPowerPerxxhOffset
AlternativePower=round(HeatingPowerMinus15-HeatingPowerTemperatureOffInterest,2)
AlternativeEnergy=round(((HeatingPowerMinus15-HeatingPowerTemperatureOffInterest)*DaysAlternativePower*HoursForHeatingADay*0.5),2)
AlternativeEnergyCost=round(CostPerkWh*AlternativeEnergy,2)

PlotMinPower = 0.0
if EstimateAdditionalInternalAndExternalEnergy:
   AverageIndoorTemp = sum(IndoorTempSamples)/len(IndoorTempSamples)
   PowerPointAtIndoorTemperature = HeatingPowerPerxxhGain*AverageIndoorTemp+HeatingPowerPerxxhOffset
   PlotMinPower = PowerPointAtIndoorTemperature-1.0
   ElectricPower = -1.0*((sum(ElectricitySamples)/len(ElectricitySamples))/HoursForHeatingADay)
   PowerFromPeople = -1.0*(HeatFromWarmBodies/HoursForHeatingADay)
   AverageInternalPower = ElectricPower + PowerFromPeople
   AverageExternalPower = PowerPointAtIndoorTemperature - AverageInternalPower

PlotData()
