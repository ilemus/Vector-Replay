from time import sleep
from time import time
from time import perf_counter
import datetime
import threading

'''
    This file is used for acceleration distribution per driving info spec.
    This file can be used for other CAN log analysis, the framework can be reused.
    Input files MUST BE in .asc format. If there is .blf format then it needs to be converted.
    To convert:
        1. Open CANoe (doesn't need specific simulator type, i.e. can be default configuration)
        2. Go to measurement setup.
        3. Make a trace for all CAN lines (filter a CAN trace to allow all CAN lines i.e. 1 through 3)
        4. Change simulation from 'Simulated' to 'Offline'
        5. Configure offline data and add the .blf file
        6. Open the CAN trace window
        7. Start replaying the offline data (lightning bolt symbol)
        8. After completed replaying, right click and export from the trace window
        9. In export option choose file location, also change save format to .asc
'''

EV = False
PHEV = False
HEV = False
STANDARD = True

KM = 0
MI = 1

KPH_TO_MPH = 1.609

TIME_MULT = 0.641

ENG_MSG_STD = 0x000
ENG_MSG_EV = 0x000
SPD_MSG_1 = 0x000

'''
    This function translates .asc formatted data as below:
    Input:
        12.940318 1  ###             Tx   d 6 00 00 00 00 00 00  Length = 205987 BitCount = 106 ID = ###X
        13.140300 1  ###             Tx   d 6 01 00 00 00 00 00  Length = 205987 BitCount = 106 ID = ###X
    Output: [
        [(20, 0.0), (20, 1.0)]
    ]
    Output data is formatted as an array of arrays. Each array is a trip. A trip is defined as bounds between engine on and engine off.
    Each touple inside of the array is a time delta and a speed value. Time delta unit is milliseconds, speed value is either in MPH or KPH. (This could be further explored to get the speed unit from the CAN frame)
    For better understanding:
    [
        [(time1 ms, speed1 kph/mph), (time2 ms, speed2 kph/mph), ...], # trip 1
        [(time1 ms, speed1 kph/mph), (time2 ms, speed2 kph/mph), ...]  # trip 2
    ]
    The parser assumes initial state is engine off, but it works recognizing that engine is on, it just might miss the first speed values before first engine on signal.
'''
def parse_file(filename):
    file = open(filename)
    # Count is used because .asc format file has a header, first line is the measurement start time
    count = 0
    
    # this stores our variables for lookup. In a class based system context is 'self', so this could be changed to a class (class ParseDrivingData:)
    context = {
        # Used to determine event delta time
        'old_time': 0.0,
        # assume there was at least one trip
        'trips': 0,
        # Assume initial state is engine off
        'engine': False,
        # This is the output array
        'time_speed': [[]]
    }
    # Initialize engine status (in case if vehicle is not defined then engine status will alwaysb be on)
    context['engine'] = engine_status(context)
    for line in file:
        # This is the case that we are past the header, but can be delayed by engine on condition or speed condition.
        if count < 3:
            count += 1
            continue
        
        #   12.940318 1  XXX             Tx   d 6 00 00 00 00 00 00  Length = 205987 BitCount = 106 ID = XXXX
        split = line.split()
        # [ 12.94, 1, XXX, Tx, d, 6, 00, 00, 00, 00, 00, 00, ...]
        context['time'] = get_offset_ms(split)
        id = int(split[2], 16)
        frame = get_frame(split)
        process_frame(id, frame, speed_events_logic, context)
        
    return context['time_speed']

# Get time offset in ms from CAN log
# Input: 12.034905
# Output: 120349
def get_offset_ms(offset):
    return int(float(offset[0]) * 1000)

'''
    CAN data parser.
    Updates context based on new data.
    Input function is called at each ID so that you can apply your own business logic.
    Business logic ex.: format data and save to file, or make event array, or collect diagnostic data.
    
    Input:
    0x###, [00, 00, 00, 00], speed_events_logic(), {'old_time': 0.0, ...}
    Output:
    None # No need for output, the updated values will exist in context
'''
def process_frame(id, frame, func, context):
    if id == SPD_MSG_1:
        context['speed'] = get_speed_signal_a(frame)
        context['speed_unit'] = get_speed_signal_b(frame)
        
        # this is business logic
        func(id, context)
    elif id == ENG_MSG_STD:
        context['rpm'] = get_engine_signal_a(frame)
        context['ign'] = get_engine_signal_b(frame)
        
        # this is business logic
        func(id, context)
    elif id == ENG_MSG_EV:
        context['on'] = get_engine_signal_EV_a(frame)
        
        # this is business logic
        func(id, context)
    else:
        pass

def speed_events_logic(id, context):
    if id == SPD_MSG_1:
        if not context['engine']:
            return
        context['time_speed'][context['trips']].append((context['time'] - context['old_time'], context['speed']))
        context['old_time'] = context['time']
    elif id == ENG_MSG_STD:
        engine = engine_status(context)
        if not engine and context['engine']:
            # Engine on -> off
            context['trips'] += 1
            context['time_speed'].append([])
            context['engine'] = False
            print("Engine off at " + str(context['time'] / 1000.0))
        elif engine and not context['engine']:
            context['engine'] = True
            print("Engine on at " + str(context['time'] / 1000.0))
    elif id == ENG_MSG_EV:
        engine = engine_status(context)
        if not engine and context['engine']:
            # Engine on -> off
            context['trips'] += 1
            context['time_speed'].append([])
            context['engine'] = False
            print("Engine off at " + str(context['time'] / 1000.0))
        elif engine and not context['engine']:
            context['engine'] = True
            print("Engine on at " + str(context['time'] / 1000.0))
    else:
        pass

def save_to_file_logic(id, context):
    if id == SPD_MSG_1:
        if not context['engine']:
            return
        curr = context['first_time'] + datetime.timedelta(seconds=context['time_s'], milliseconds=context['time_ms'])
        context['time_speed'][context['trips']].append((curr.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3], float(context['speed'])))
    elif id == ENG_MSG_STD:
        engine = engine_status(context)
        if not engine and context['engine']:
            # Engine on -> off
            context['trips'] += 1
            context['time_speed'].append([])
            context['engine'] = False
        elif engine and not context['engine']:
            context['engine'] = True
    elif id == ENG_MSG_EV:
        engine = engine_status(context)
        if not engine and context['engine']:
            # Engine on -> off
            context['trips'] += 1
            context['time_speed'].append([])
            context['engine'] = False
        elif engine and not context['engine']:
            context['engine'] = True
    else:
        pass

def engine_status(context):
    if EV:
        return True
    elif PHEV:
        return True
    elif HEV:
        return True
    elif STANDARD:
        return True
    else:
        return True

def speed(context, unit):
    if 'speed' not in context['speed'] or 'speed_unit' not in context['speed_unit']:
        return 0.0
    if unit == KM:
        if context['speed_unit'] == KM:
            return context['speed']
        else:
            return context['speed'] / KPH_TO_MPH
    elif unit == MI:
        if context['speed_unit'] == MI:
            return context['speed']
        else:
            return context['speed'] * KPH_TO_MPH
    else:
        return 0.0

def get_engine_ev_a(frame):
    return 0

# get CAN frame
# Input: [ 12.94, 1, XXX, Tx, d, 6, 00, 00, 00, 00, 00, 00, ...]
# Output: [00, 00, 00, 00, 00, 00]
def get_frame(line):
    return line[6:int(line[5]) + 6]

def get_speed_signal_a(frame):
    return 0

def get_speed_signal_b(frame):
    return 0

def get_engine_signal_a(frame):
    return 0

def get_engine_signal_b(frame):
    return 0

'''
    Used to export speed events. (Verisk wants to analyze)
    Input:
        12.940318 1  XXX             Tx   d 6 00 00 00 00 00 00  Length = 205987 BitCount = 106 ID = XXXX
        13.140300 1  XXX             Tx   d 6 01 00 00 00 00 00  Length = 205987 BitCount = 106 ID = XXXX
    Output (save_to_mph_0.csv):
        2020-01-15 10:30:01.187, 0.0
        2020-01-15 10:30:01.387, 0.1
'''
def save_to_csv(filename):
    file = open(filename)
    # Count is used because .asc format file has a header, first line is the measurement start time
    count = 0
    
    context = {
        # Used to determine event delta time
        'first_time': None,
        # assume there was at least one trip
        'trips': 0,
        # Assume initial state is engine off
        'engine': False,
        # This is the output array
        'time_speed': [[]],
        # This is current offset time in seconds
        'time_s': 0,
        # This is current offset time millisecond
        'time_ms': 0
    }
    
    for line in file:
        # This is the case that we are past the header, but can be delayed by engine on condition or speed condition.
        if count < 3:
            if count == 0:
                # date Thu Dec 19 01:32:07.156 pm 2019
                context['first_time'] = datetime.datetime.strptime(line[:-1], "date %a %b %d %I:%M:%S.%f %p %Y")
            count += 1
            continue
        
        #   12.940318 1  XXX             Tx   d 6 00 00 00 00 00 00  Length = 205987 BitCount = 106 ID = XXXX
        split = line.split()
        # [ 12.94, 1, XXX, Tx, d, 6, 00, 00, 00, 00, 00, 00, ...]
        
        split_time = split[0].split('.')
        context['time_s'] = int(split_time[0])
        context['time_ms'] = int((float(split[0]) - context['time_s']) * 1000)
        id = int(split[2], 16)
        frame = get_frame(split)
        process_frame(id, frame, save_to_file_logic, context)
    file.close()
    
    for i in range(0, len(context['time_speed'])):
        file = open("save_to_mph_" + str(i) + ".csv", "w")
        for row in context['time_speed'][i]:
            file.write(row[0] + "," + str(row[1]) + "\n")
    

class Speed:
    def __init__(self):
        self.s = 0.0
        self.e = True
    
    def set_speed(self, speed):
        self.s = speed
    
    def end(self):
        self.e = False
    
    def get_speed(self):
        return self.s
    
    def get_end(self):
        return self.e

class ReplayThread(threading.Thread):
    def __init__(self, time_speed, shared):
        threading.Thread.__init__(self)
        self.time_speed = time_speed
        self.shared = shared
    
    def run(self):
        self.replay_speed(self.time_speed)
    
    def replay_speed(self, time_speed):
        for speed in time_speed:
            delay(speed[0])
            self.shared.set_speed(speed[1])
        self.shared.end()


class ParseThread(threading.Thread):
    def __init__(self, name, shared):
        threading.Thread.__init__(self)
        self.name = name
        self.shared = shared
        
    def run(self):
        print("[" + self.name + "] Started driving_info")
        start = time()
        accel = self.read_speed()
        end = time()
        print("[" + self.name + "] duration: " + str(end - start) + " mph: " + str(accel[0]) + ", kph: " + str(accel[1]))
    
    def read_speed(self):
        accel_mph = []
        accel_kph = []
        old_speed = 0.0
        while self.shared.get_end():
            delay(1000)
            speed = self.shared.get_speed()
            # Assumes speed unit is MPH
            ParseThread.process_accel_mph(accel_mph, speed - old_speed)
            ParseThread.process_accel_kph(accel_kph, speed / 1.609 - old_speed / 1.609)
            old_speed = speed
        return (accel_mph, accel_kph)
            
    def process_accel_mph(accel, speed_diff):
        pass
            
    def process_accel_kph(accel, speed_diff):
        pass
    
def start_dist(time_speed, name):
    shared = Speed()
    replay = ReplayThread(time_speed, shared)
    parse = ParseThread(name, shared)
    replay.start()
    parse.start()

'''
    This will use the other file asciiCanTool.py to reduce the amount of data to consider.
    Parses for CAN ID XXX XXX XXX for speed, engine, engine respectively
'''
def read_from_raw_asc(filename):
    from asciiCanTool import trim
    trim(filename, [])

'''
    Raw logs collected (.asc) are converted to a .csv file with event time, speed value.
    To process speed events we need to process the raw ascii before we can use it.
'''
def raw_ascii_to_speed_event(filename):
    from asciiCanTool import trim
    trim(filename, [])
    save_to_csv("OUTPUT.asc")

# Because Python time.sleep is innaccurate then define as such
def delay(millis):
    _ = perf_counter() + millis / 1000
    while perf_counter() < _:
        pass

'''
    SO WE CAN REPLAY THE LOGS
    Requirements: Python_CANoe.py; pip install win32com
    NEED TO HAVE SIMULATOR ALREADY OPEN.
    This is designed to replay speed, but it can be for anything.
    Also start simulator and turn engine on so all signals are populated.
'''
def replay_trip(data):
    from Python_CANoe import CANoe
    app = CANoe()
    # speed_signal has property Value which can be get/set
    unit_signal = app.set_GetSigVal(1, "XXX_XXX", "XX_XXX_XXXXXXX")
    unit_signal.Value = MI
    speed_signal = app.set_GetSigVal(1, "XXX_XXX", "XX_XXX_XXXXXXX")
    length = len(data)
    per = int(length / 100)
    for i in range(0, len(data)):
        delay(data[i][0])
        speed_signal.Value = int(data[i][1] * 2.0)
        if i % per == 0:
            print(str(int(i / length * 100)) + "%\r", end='')
    app.stop_Measurement()
