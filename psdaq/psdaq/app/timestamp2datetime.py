"""Print the local date/time ('%d-%m-%Y %H:%M:%S') for a timestamp given as seconds and nanoseconds since 1990-01-01 UTC (two command-line arguments)."""
import datetime as dt
import sys
# two arguments are lcls2 seconds/nanoseconds from the timestamp
sec = int(sys.argv[1])
usec = int(sys.argv[2])/1000
epoch = dt.datetime(1990, 1, 1)
delta_t = dt.timedelta(seconds=sec, microseconds=usec)
mydatetime = epoch + delta_t
localt = mydatetime.replace(tzinfo=dt.timezone.utc).astimezone(tz=None)    
print(localt.strftime('%d-%m-%Y %H:%M:%S'))
