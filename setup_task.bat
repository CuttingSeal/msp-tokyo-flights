@echo off
REM Creates a Windows Task Scheduler task to run the flight tracker daily at 8 AM
REM Run this file as Administrator

schtasks /create /tn "FlightTracker" /tr "C:\Python314\python.exe C:\Users\ethan\flight-tracker\flight_tracker.py" /sc daily /st 08:00 /f

echo.
echo Task "FlightTracker" created. It will run daily at 8:00 AM.
echo Make sure your .env file is configured before the first run.
pause
