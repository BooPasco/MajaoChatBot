import os
import logging
from datetime import datetime, timedelta
import pytz
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import uuid
import time

# Logging setup - INFO level for high-level flow only
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Google Calendar config
SCOPES = ['https://www.googleapis.com/auth/calendar']
CREDENTIALS_FILE = '/Users/chrispasco/Documents/MachineLearning/Majao_Chatbot/client_secret.json'
TOKEN_FILE = '/Users/chrispasco/Documents/MachineLearning/Majao_Chatbot/token.json'
TZ = pytz.timezone('America/Bogota')
LOCATION = "Majao Studio Medellin, Carrera 43A #1-50, Medellín, Colombia"
OPEN_TIME = 8  # 8:00 AM
CLOSE_TIME = 17.5  # 5:30 PM

def get_calendar_service():
    """Initialize Google Calendar service."""
    logger.info("Initializing calendar service")
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
        creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, 'w') as token:
            token.write(creds.to_json())
    service = build('calendar', 'v3', credentials=creds)
    return service

def availability(start_time: str, length: int, style: str, date_str: str = None) -> dict:
    """Check availability for a class, suggest closest before, after, and one more. 8:00 AM - 5:30 PM only."""
    today = datetime.now(TZ)
    if not date_str:
        date_str = today.strftime('%Y-%m-%d')
    logger.info(f"Checking availability for {style} on {date_str} at {start_time} for {length} mins")

    # Parse start and end times
    start_dt = TZ.localize(datetime.strptime(f"{date_str} {start_time}", '%Y-%m-%d %H:%M'))
    end_dt = start_dt + timedelta(minutes=length)
    start_hour = start_dt.hour + start_dt.minute / 60
    if start_hour < OPEN_TIME or start_hour > CLOSE_TIME:
        logger.info(f"Time {start_time} is outside 8:00 AM - 5:30 PM")
        return {"is_free": False, "start": None, "end": None, "suggestions": []}
    start_utc = start_dt.astimezone(pytz.UTC).isoformat()
    end_utc = end_dt.astimezone(pytz.UTC).isoformat()

    # Get events in the time range
    service = get_calendar_service()
    events_result = service.events().list(
        calendarId='primary', timeMin=start_utc, timeMax=end_utc,
        singleEvents=True, orderBy='startTime'
    ).execute()
    events = events_result.get('items', [])

    # Check if slot is free (max 2 classes, same style allowed)
    is_free = True
    overlapping_count = 0
    for event in events:
        event_style = event.get('summary', 'Unknown').split(':')[-1].strip().lower()
        if event_style == style.lower():
            overlapping_count += 1
            if overlapping_count >= 2:
                is_free = False
                logger.info(f"Too many overlapping {style} classes: {overlapping_count + 1} with new booking")
                break
        else:
            is_free = False
            logger.info(f"Slot conflicts with {event.get('summary', 'Untitled event')}")
            break

    if is_free:
        logger.info("Slot is free")
        return {"is_free": True, "start": start_dt, "end": end_dt, "suggestions": []}

    # Find closest before, after, and one more suggestion
    logger.info("Slot not free, finding closest before, after, and one more suggestion")
    day_start = TZ.localize(datetime.strptime(date_str, '%Y-%m-%d').replace(hour=OPEN_TIME, minute=0))
    day_end = TZ.localize(datetime.strptime(date_str, '%Y-%m-%d').replace(hour=int(CLOSE_TIME), minute=int((CLOSE_TIME % 1) * 60)))
    day_start_utc = day_start.astimezone(pytz.UTC).isoformat()
    day_end_utc = (day_end + timedelta(minutes=length)).astimezone(pytz.UTC).isoformat()

    day_events = service.events().list(
        calendarId='primary', timeMin=day_start_utc, timeMax=day_end_utc,
        singleEvents=True, orderBy='startTime'
    ).execute().get('items', [])

    # Scan for free slots
    before = None
    after = None
    all_slots = []
    current_time = day_start
    while current_time + timedelta(minutes=length) <= day_end + timedelta(minutes=length):
        slot_end = current_time + timedelta(minutes=length)
        slot_start_utc = current_time.astimezone(pytz.UTC).isoformat()
        slot_end_utc = slot_end.astimezone(pytz.UTC).isoformat()
        
        overlapping = [e for e in day_events if 
                       e['start']['dateTime'] < slot_end_utc and e['end']['dateTime'] > slot_start_utc]
        total_overlap = len(overlapping)  # Count all events
        salsa_count = sum(1 for e in overlapping if e.get('summary', 'Unknown').split(':')[-1].strip().lower() == style.lower())
        
        # Slot is free if: < 2 total overlaps OR all overlaps are same style and < 2
        if (total_overlap < 2) or (salsa_count == total_overlap and salsa_count < 2):
            slot = {"start": current_time, "end": slot_end}
            if current_time != start_dt:  # Skip the requested slot
                all_slots.append(slot)
            if current_time < start_dt and (before is None or current_time > before["start"]):
                before = slot
            if current_time > start_dt and (after is None or current_time < after["start"]):
                after = slot
        current_time += timedelta(minutes=30)

    # Pick 3: closest before, closest after, and one more
    suggestions = []
    if before:
        suggestions.append(before)
    if after:
        suggestions.append(after)
    if len(suggestions) < 3 and all_slots:
        remaining = [s for s in all_slots if s not in suggestions]
        if remaining:
            remaining.sort(key=lambda x: abs((x["start"] - start_dt).total_seconds()))
            suggestions.append(remaining[0])

    logger.info(f"Suggestions: {suggestions}")
    return {"is_free": False, "start": None, "end": None, "suggestions": suggestions[:3]}

def booking(start_time: str, length: int, style: str, student: str, teacher: str, 
            student_email: str, teacher_email: str, unique_code: str = None, date_str: str = None) -> dict:
    """Book a class and verify it’s on the calendar. 8:00 AM - 5:30 PM only."""
    today = datetime.now(TZ)
    if not date_str:
        date_str = today.strftime('%Y-%m-%d')
    logger.info(f"Preparing to book {style} for {student} & {teacher} on {date_str} at {start_time}")

    # Parse start time and check if it’s in the past or outside hours
    start_dt = TZ.localize(datetime.strptime(f"{date_str} {start_time}", '%Y-%m-%d %H:%M'))
    start_hour = start_dt.hour + start_dt.minute / 60
    if start_dt < today:
        logger.info(f"Cannot book: {start_dt} is in the past")
        return {"success": False, "event_id": None, "unique_code": unique_code, "error": "Cannot book past dates"}
    if start_hour < OPEN_TIME or start_hour > CLOSE_TIME:
        logger.info(f"Cannot book: {start_time} is outside 8:00 AM - 5:30 PM")
        return {"success": False, "event_id": None, "unique_code": unique_code, "error": "Outside operating hours"}

    end_dt = start_dt + timedelta(minutes=length)
    unique_code = unique_code or str(uuid.uuid4())[:8]
    logger.info(f"Booking slot: {start_dt} to {end_dt}, code={unique_code}")

    # Create event
    service = get_calendar_service()
    event = {
        'summary': f"{student} & {teacher}: {style}",
        'location': LOCATION,
        'start': {'dateTime': start_dt.isoformat(), 'timeZone': 'America/Bogota'},
        'end': {'dateTime': end_dt.isoformat(), 'timeZone': 'America/Bogota'},
        'attendees': [{'email': student_email}, {'email': teacher_email}],
        'description': f"Unique Code: {unique_code}"
    }
    
    try:
        created_event = service.events().insert(calendarId='primary', body=event).execute()
        event_id = created_event['id']
        logger.info(f"Event created with ID: {event_id}")
    except Exception as e:
        logger.info(f"Booking failed: {str(e)}")
        return {"success": False, "event_id": None, "unique_code": unique_code, "error": str(e)}

    # Verify event exists
    time.sleep(2)
    logger.info(f"Verifying event ID: {event_id}")
    try:
        verified_event = service.events().get(calendarId='primary', eventId=event_id).execute()
        if verified_event['summary'] == f"{student} & {teacher}: {style}":
            logger.info("Event verified")
            return {"success": True, "event_id": event_id, "unique_code": unique_code, "error": None}
        else:
            logger.info("Verification failed: details mismatch")
            return {"success": False, "event_id": event_id, "unique_code": unique_code, "error": "Event details mismatch"}
    except Exception as e:
        logger.info(f"Verification failed: {str(e)}")
        return {"success": False, "event_id": event_id, "unique_code": unique_code, "error": str(e)}

# Interactive test loop
if __name__ == "__main__":
    print(f"Today is: {datetime.now(TZ).strftime('%Y-%m-%d %H:%M:%S')}")
    print("Enter 'quit' to exit. Format: date (YYYY-MM-DD) or blank for today, start time (HH:MM), length (mins), style")
    
    while True:
        user_input = input("\nEnter: [date] [start_time] [length] [style] (e.g., 2025-03-28 15:00 60 salsa): ").strip()
        if user_input.lower() == 'quit':
            break
        
        parts = user_input.split()
        if len(parts) < 3:
            print("Invalid input. Use: [date] [start_time] [length] [style] or just [start_time] [length] [style] for today.")
            continue
        
        if len(parts) == 3:  # Today’s date assumed
            date_str = None
            start_time, length, style = parts[0], int(parts[1]), parts[2]
        else:  # Date provided
            date_str, start_time, length, style = parts[0], parts[1], int(parts[2]), parts[3]

        avail = availability(start_time, length, style, date_str)
        print("Result:", avail)

        if avail["is_free"]:
            book = booking(
                start_time, length, style, "Prince", "Chris",
                "prince@example.com", "chris@example.com", date_str=date_str
            )
            print("Booking Result:", book)
        else:
            print("Slot not free. Suggestions:", avail["suggestions"])