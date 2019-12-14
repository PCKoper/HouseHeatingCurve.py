##############################################################################################################
# HouseHeatingCurve.py 
# Last Update: December 14th 2019
# V0.1 : Initial Creation
# V0.2 : Update comments, added scaling on placement of text labels in the plot.
##############################################################################################################
# Script queries Heating (kWh) and Temperature (oC) data from Domoticz stored in sensors with ids 
# OutDoorTemperatureSensorID and HeatingEnergySensorID and analyses the data from DateStartAnalyses till 
# DateEndAnalyses.
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
#
# It will calculate the required heating power at OutsideTemperatureOfInterest when taking into account a 
# maximum number of hours it can run a day defined by HoursForHeatingADay.
#
# It will also calculate the required maximum power of additional heating which will be required not to have 
# the house cooling down based on historic data since 1951 from Volkel Airbase KNMI weather station.
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
import urllib2
import ssl
import json
import collections
import pylab
from scipy.optimize import curve_fit

##############################################################################################################
# Definitions                                                                                                #
##############################################################################################################

##############################################################################################################
# Config Start 												     #
##############################################################################################################
DateStartAnalyses=datetime.date(2019,9,12)
DateEndAnalyses=datetime.datetime.now().date()

# Indicate to use energy data from Domoticz in kWh, or use Gas data and convert that to kWh
UseGasDataForHeatingEnergyEstimation = False
EnergyPerCubicMeterGas = float(31.65/3.6)
CubicMetersGasADayForWarmWaterAndCooking = float(8/30)

# The outside temperature of interest is what is used to calculate the required Heating Capacity.
OutsideTemperatureOfInterest=float(-7.0)

# Hours Per Day for Heating is defined such that some time can be reserved to heatup a boiler of warm water
# or to indicate for example not to heat during the night.
HoursForHeatingADay = float(22.0)

# Price per kWh for the alternative energy to calculate the variabel cost of additional heating.
CostPerkWh = float(0.227)

#Sensor IDx from Domoticz
OutDoorTemperatureSensorID="20"
HeatingEnergySensorID="102"
GasSensorID="53"

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
HeatingEnergyDataURL=QueryPreFix+Percentage+HeatingEnergySensorID+QueryPostFix
GasUsageDataURL=QueryPreFix+Counter+GasSensorID+QueryPostFix


#Creating a context to indicate to urllib2 that we don't want SSL verification
#in case the domoticz setup does not have a valid CERT certificate.
UnverifiedContext = ssl._create_unverified_context()

#Plot properties
PlotMinTemperature=-15.0
PlotMaxTemperature=20.0 
PlotMinPower=0.0
#PlotMaxPower will be defined from calculated Maxpower @ PlotMinTemperature.

#Volkel Historic Data, below averages are calculated from all the KNMI data from 1953-2019
DaysPerYearBelowTemperatureCummulative = {
    20 : 347.7 ,  
    19 : 339.07 , 
    18 : 327.17 , 
    17 : 312.86 , 
    16 : 295.19 , 
    15 : 274.63 , 
    14 : 252.87 , 
    13 : 233.21 , 
    12 : 214.74 , 
    11 : 197.01 , 
    10 : 179.39 , 
    9  : 162.11 , 
    8  : 143.66 , 
    7  : 125.12 , 
    6  : 105.77 , 
    5  : 87.12 ,  
    4  : 71.08 ,  
    3  : 56.89 ,  
    2  : 44.71 ,  
    1  : 33.9 ,   
    0  : 25.01 ,
   -1  : 18.08 ,
   -2  : 12.77 ,
   -3  : 8.73 ,
   -4  : 6.14 ,
   -5  : 4.38 ,
   -6  : 3.11 ,
   -7  : 2.15 ,
   -8  : 1.54 ,
   -9  : 0.88 ,
   -10 : 0.45 ,
   -11 : 0.31 ,
   -12 : 0.18 ,
   -13 : 0.07 ,
   -14 : 0.06 ,
   -15 : 0.01 ,
   -16 : 0.01 ,
   -17 : 0.0 ,
   -18 : 0.0 ,
   -19 : 0.0 ,
   -20 : 0.0 ,
}

##############################################################################################################
# Functions
##############################################################################################################

def DataInAnalysesWindow(DateString): 
   Year=int(DateString.split("-")[0])
   Month=int(DateString.split("-")[1])
   Day=int(DateString.split("-")[2])
   CompareDate=datetime.date(Year,Month,Day)
   return (DateStartAnalyses <= CompareDate and CompareDate <= DateEndAnalyses)

def InterPolateDaysPerYearBelowTemperature(Temperature):
   LowValue=float(DaysPerYearBelowTemperatureCummulative[(int(Temperature))])
   HighValue=float(DaysPerYearBelowTemperatureCummulative[(int(Temperature)+1)])
   Fraction=Temperature-(int(Temperature))
   DaysPerYear=LowValue+(Fraction*(HighValue-LowValue))
   return(DaysPerYear)

def GetOutdoorTemp():
   #print('>GetOutdoorTemp')
   ReturnList=[]
   try:
      Page=urllib2.urlopen(OutdoorTemperatureDataURL, context=UnverifiedContext)
      DataString=Page.read()
      JsonData=json.loads(DataString)
      TemperatureList=JsonData['result']
      #Filter out only the items with proper values
      for item in TemperatureList:
         if 'd' in item:
	    if DataInAnalysesWindow(item['d']):
	       if 'ta' in item:
		  ReturnList.append(item)
   except (urllib2.HTTPError, urllib2.URLError) as fout:
      print("Error: "+str(fout)+" URL: "+OutdoorTemperatureDataURL)
   #print('<GetOutdoorTemp:'+ReturnList.__str__())
   return(ReturnList)

def GetHeatingEnergy():
   #print('>GetHeatingEnergy')
   ReturnList=[]
   try:
      Page=urllib2.urlopen(HeatingEnergyDataURL, context=UnverifiedContext)
      DataString=Page.read()
      JsonData=json.loads(DataString)
      HeatingEnergyList=JsonData['result']
      #Filter out only the items with proper values
      for item in HeatingEnergyList:
         if 'd' in item:
	    if DataInAnalysesWindow(item['d']):
	       if 'v_max' and 'v_min' in item:
		  ReturnList.append(item)
   except (urllib2.HTTPError, urllib2.URLError) as fout:
      print("Error: "+str(fout)+" URL: "+HeatingEnergyDataURL)
   #print('<GetHeatingEnergy:'+ReturnList.__str__())
   return(ReturnList)

def GetHeatingEnergyFromGasUsage():
   #print('>GetHeatingEnergyFromGasUsage')
   ReturnList=[]
   try:
      Page=urllib2.urlopen(GasUsageDataURL, context=UnverifiedContext)
      DataString=Page.read()
      JsonData=json.loads(DataString)
      HeatingEnergyList=JsonData['result']
      #Filter out only the items with proper values
      for item in HeatingEnergyList:
         if 'd' in item:
	    if DataInAnalysesWindow(item['d']):
	       if 'v' in item:
		  ReturnList.append(item)
   except (urllib2.HTTPError, urllib2.URLError) as fout:
      print("Error: "+str(fout)+" URL: "+GasUsageDataURL)
   #print('<GetHeatingEnergyFromGasUsage:'+ReturnList.__str__())
   return(ReturnList)


def CreateDictionaryOfData (OutdoorData, HeatingEnergyData):
   OutputDict=collections.OrderedDict()
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
	 ValueDict['Energy']=((float(item['v'])-CubicMetersGasADayForWarmWaterAndCooking)*EnergyPerCubicMeterGas).__str__()
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
   OutdoorTempSamples=[]
   PreviousOutdoorTemperature = 0.0
   PreviousHeatingPower = 0.0
   for Date, ValueList in Measurements.iteritems():
      for Value in ValueList:
	 if 'Energy' in Value:
	    PreviousHeatingPower = float(Value['Energy'])/HoursForHeatingADay
	 if 'OutdoorTemperature' in Value:
	    PreviousOutdoorTemperature = float(Value['OutdoorTemperature'])
      HeatingPowerSamples.append(PreviousHeatingPower)
      OutdoorTempSamples.append(PreviousOutdoorTemperature)
   return(OutdoorTempSamples, HeatingPowerSamples)
   
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

##############################################################################################################
# Main
##############################################################################################################

# Get the data from Domoticz

OutdoorData = GetOutdoorTemp()

if UseGasDataForHeatingEnergyEstimation:
   HeatingEnergyData = GetHeatingEnergyFromGasUsage()
else:
   HeatingEnergyData = GetHeatingEnergy()

#Create One dictionary of measurements, date+time based.

Measurements=CreateDictionaryOfData(OutdoorData, HeatingEnergyData)

# Now Create the lists of data for the fitting algorithm to use.
OutdoorTempSamples, HeatingPowerSamples = GetDataListsFromDictionary(Measurements)

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

DaysAlternativePower=round(InterPolateDaysPerYearBelowTemperature(OutsideTemperatureOfInterest),1)
HeatingPowerMinus15=HeatingPowerPerxxhGain*-15.0+HeatingPowerPerxxhOffset
HeatingPowerTemperatureOffInterest=HeatingPowerPerxxhGain*OutsideTemperatureOfInterest+HeatingPowerPerxxhOffset
AlternativePower=round(HeatingPowerMinus15-HeatingPowerTemperatureOffInterest,2)
AlternativeEnergy=round(((HeatingPowerMinus15-HeatingPowerTemperatureOffInterest)*DaysAlternativePower*HoursForHeatingADay*0.5),2)
AlternativeEnergyCost=round(CostPerkWh*AlternativeEnergy,2)

# Create the label texts for the plot 

HeatingLimitString="Heating Until: "
HeatingLimitValueString=round(HeatingLimit,2).__str__()+" C"
OutsideTemperatureOfInterestString=OutsideTemperatureOfInterest.__str__()+" C"
PowerRequiredTemperatureOffInterestString="Power Required @ "+OutsideTemperatureOfInterestString+": "
PowerRequiredTemperatureOffInterestValueString=round(HeatingPowerTemperatureOffInterest,2).__str__()+" kW"
AlternativeHeatingPowerString=DaysAlternativePower.__str__()+" Days/Year Alternative Power Required @ "+OutsideTemperatureOfInterestString+": \n"+AlternativePower.__str__()+" kW for a total of "+AlternativeEnergy.__str__()+" kWh ("+AlternativeEnergyCost.__str__()+" Euro)"
AlternativeHeatingPowerValueString=AlternativePower.__str__()+" kW"
PowerFitFunctionString="Fit: Power = "+round(HeatingPowerPerxxhGain,5).__str__()+" * temperature + "+round(HeatingPowerPerxxhOffset,3).__str__()+" (r="+Correlation.__str__()+")"

# Create points to draw the lines for the temperature of interest and the calculated required power.

CrossSectionTempLine=[PlotMinPower,HeatingPowerTemperatureOffInterest]
CrossSectionPowerLine=[PlotMinTemperature,OutsideTemperatureOfInterest]
TempBaseLine=[OutsideTemperatureOfInterest,OutsideTemperatureOfInterest]
PowerBaseLine=[HeatingPowerTemperatureOffInterest,HeatingPowerTemperatureOffInterest]

#Calculate the Offsets for the text labels in the plot
LabelOffsetY=(PlotMaxPower/24.0)

# Make the plot.

pylab.plot(OutdoorTempSamples, HeatingPowerSamples, 'r.')
pylab.plot(HeatingPowerFitlineTemp, HeatingPowerFitline, 'r-', label="HeatingPower")
pylab.plot(CrossSectionPowerLine, PowerBaseLine, 'k-')
pylab.plot(TempBaseLine, CrossSectionTempLine, 'k-')

pylab.axis([PlotMinTemperature,PlotMaxTemperature,PlotMinPower,PlotMaxPower])
pylab.legend(loc="upper left")
pylab.title("Heating Power VS OutDoor Temperature.\n"+PowerFitFunctionString)
pylab.xlabel("OutDoor Temperature [C]")
ylabeltext="Required Heating Power / "+HoursForHeatingADay.__str__()+"h [kW]"
pylab.ylabel(ylabeltext)
pylab.grid(True)

pylab.text(-0,(PlotMaxPower-(LabelOffsetY+0.3)),HeatingLimitString)
pylab.text(13,(PlotMaxPower-(LabelOffsetY+0.3)),HeatingLimitValueString)
pylab.text(-0,(PlotMaxPower-(2*LabelOffsetY+0.3)),PowerRequiredTemperatureOffInterestString)
pylab.text(13,(PlotMaxPower-(2*LabelOffsetY+0.3)),PowerRequiredTemperatureOffInterestValueString)
pylab.text(-10,(PlotMaxPower-(5*LabelOffsetY+0.3)),AlternativeHeatingPowerString)
pylab.text((PlotMinTemperature+0.1),(HeatingPowerTemperatureOffInterest+0.1),PowerRequiredTemperatureOffInterestValueString)
pylab.text((OutsideTemperatureOfInterest+0.1),(PlotMinPower+0.1),OutsideTemperatureOfInterestString)
pylab.show()
