import os
import logging
from datetime import datetime, timedelta
import pytz
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import uuid
from typing import Dict
import time

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
SCOPES = ['https://www.googleapis.com/auth/calendar']
CREDENTIALS_FILE = 'client_secret.json'
TOKEN_FILE = 'token.json'
TZ = pytz.timezone('America/Bogota')
LOCATION = "Majao Studio Medellin, Carrera 43A #1-50, Medellín, Colombia"
OPEN_TIME = 8  # 8:00 AM
CLOSE_TIME = 17.5  # 5:30 PM

def get_calendar_service():
    """Initialize Google Calendar service with Bogotá timezone."""
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
        creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, 'w') as token:
            token.write(creds.to_json())
    return build('calendar', 'v3', credentials=creds)

def check_availability(start_time: str, length: int, style: str, date_str: str = None) -> Dict:
    """Check availability with all times in Bogotá timezone."""
    today = datetime.now(TZ)
    date_str = date_str or today.strftime('%Y-%m-%d')
    
    try:
        start_dt = TZ.localize(datetime.strptime(f"{date_str} {start_time}", '%Y-%m-%d %H:%M'))
        end_dt = start_dt + timedelta(minutes=length)
        
        # Check business hours
        start_hour = start_dt.hour + start_dt.minute / 60
        if start_hour < OPEN_TIME or start_hour > CLOSE_TIME:
            return {
                "is_free": False,
                "message": f"❌ Time {start_time} is outside operating hours (8:00 AM - 5:30 PM)",
                "suggestions": []
            }

        # Check calendar conflicts (all times in Bogotá timezone)
        service = get_calendar_service()
        events_result = service.events().list(
            calendarId='primary',
            timeMin=start_dt.isoformat(),
            timeMax=end_dt.isoformat(),
            timeZone='America/Bogota',
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        events = events_result.get('items', [])

        if len(events) >= 2:
            conflict_details = []
            for event in events[:2]:
                summary = event.get('summary', 'Unknown class')
                start = datetime.fromisoformat(event['start']['dateTime']).astimezone(TZ).strftime('%H:%M')
                end = datetime.fromisoformat(event['end']['dateTime']).astimezone(TZ).strftime('%H:%M')
                conflict_details.append(f"• {summary} ({start}-{end})")
            
            suggestions = get_alternative_slots(start_dt, length, date_str)
            
            return {
                "is_free": False,
                "message": (
                    f"❌ {start_dt.strftime('%a %b %d')} at {start_time} is fully booked:\n"
                    + "\n".join(conflict_details)
                    + "\n\n💡 Available time slots:"
                ),
                "suggestions": suggestions,
                "suggestion_text": format_suggestions(suggestions)
            }
        
        return {"is_free": True, "start": start_dt, "end": end_dt}
    
    except Exception as e:
        logger.error(f"Availability check failed: {e}")
        return {"is_free": False, "message": "⚠️ Error checking availability", "suggestions": []}

def get_alternative_slots(original_start, length, date_str):
    """Find alternative time slots in Bogotá time."""
    day_start = original_start.replace(hour=OPEN_TIME, minute=0)
    day_end = original_start.replace(hour=int(CLOSE_TIME), minute=int((CLOSE_TIME % 1) * 60))
    
    service = get_calendar_service()
    events_result = service.events().list(
        calendarId='primary',
        timeMin=day_start.isoformat(),
        timeMax=day_end.isoformat(),
        timeZone='America/Bogota',
        singleEvents=True,
        orderBy='startTime',
        fields='items(start/dateTime,end/dateTime)'
    ).execute()
    day_events = events_result.get('items', [])
    
    # Find all available slots
    available_slots = []
    current_time = day_start
    slot_duration = timedelta(minutes=length)
    
    while current_time + slot_duration <= day_end:
        slot_end = current_time + slot_duration
        overlapping = [
            e for e in day_events 
            if datetime.fromisoformat(e['start']['dateTime']).astimezone(TZ) < slot_end
            and datetime.fromisoformat(e['end']['dateTime']).astimezone(TZ) > current_time
        ]
        
        if len(overlapping) < 2 and current_time != original_start:
            available_slots.append({
                "start": current_time,
                "end": slot_end
            })
        
        current_time += timedelta(minutes=30)
    
    # Select best alternatives
    before = [s for s in available_slots if s["start"] < original_start]
    after = [s for s in available_slots if s["start"] > original_start]
    
    suggestions = []
    if before:
        suggestions.append(max(before, key=lambda x: x["start"]))
    if after:
        suggestions.append(min(after, key=lambda x: x["start"]))
    
    # Add one more suggestion if available
    remaining = [s for s in available_slots if s not in suggestions]
    if remaining:
        remaining.sort(key=lambda x: abs((x["start"] - original_start).total_seconds()))
        suggestions.append(remaining[0])
    
    return suggestions[:3]

def format_suggestions(suggestions):
    """Format time suggestions clearly."""
    if not suggestions:
        return "No alternative times available today"
    
    formatted = []
    for i, slot in enumerate(suggestions, 1):
        start = slot["start"].strftime('%H:%M')
        end = slot["end"].strftime('%H:%M')
        formatted.append(f"{i}. {start}-{end}")
    
    return "\n".join(formatted)

def schedule_event(start_time: str, length: int, style: str, student: str, teacher: str, 
                  student_email: str, teacher_email: str, unique_code: str = None, date_str: str = None) -> Dict:
    """Book a class in Bogotá timezone."""
    try:
        start_dt = TZ.localize(datetime.strptime(f"{date_str or datetime.now(TZ).strftime('%Y-%m-%d')} {start_time}", '%Y-%m-%d %H:%M'))
        end_dt = start_dt + timedelta(minutes=length)
        
        event = {
            'summary': f"{student} & {teacher}: {style}",
            'location': LOCATION,
            'start': {'dateTime': start_dt.isoformat(), 'timeZone': 'America/Bogota'},
            'end': {'dateTime': end_dt.isoformat(), 'timeZone': 'America/Bogota'},
            'attendees': [{'email': student_email}, {'email': teacher_email}],
            'description': f"Booking ID: {unique_code or str(uuid.uuid4())[:8]}"
        }
        
        service = get_calendar_service()
        created_event = service.events().insert(calendarId='primary', body=event).execute()
        
        return {
            "success": True,
            "event_id": created_event['id'],
            "details": f"✅ Booked {style} for {student} with {teacher}\n"
                      f"📅 {start_dt.strftime('%a %b %d')}\n"
                      f"⏰ {start_dt.strftime('%H:%M')}-{end_dt.strftime('%H:%M')}"
        }
    
    except Exception as e:
        logger.error(f"Booking failed: {e}")
        return {"success": False, "error": f"⚠️ Booking failed: {str(e)}"}

if __name__ == "__main__":
    print("Majao Studio Booking System")
    print(f"Today in Bogotá: {datetime.now(TZ).strftime('%Y-%m-%d %H:%M')}\n")
    
    while True:
        try:
            user_input = input("Enter [date] [time] [minutes] [style] (or 'quit'): ").strip()
            if user_input.lower() == 'quit':
                break
            
            parts = user_input.split()
            if len(parts) == 3:
                date_str, start_time, length, style = None, parts[0], int(parts[1]), parts[2]
            elif len(parts) == 4:
                date_str, start_time, length, style = parts[0], parts[1], int(parts[2]), parts[3]
            else:
                print("Invalid format. Example: '2025-03-31 14:00 60 Salsa' or '14:00 60 Salsa'")
                continue
            
            result = check_availability(start_time, length, style, date_str)
            
            if result["is_free"]:
                booking = schedule_event(
                    start_time, length, style, 
                    "Test Student", "Test Teacher",
                    "student@example.com", "teacher@example.com",
                    date_str=date_str
                )
                print("\n" + booking["details"] + "\n")
            else:
                print("\n" + result["message"] + "\n")
                print(result["suggestion_text"] + "\n")
                
        except ValueError:
            print("Please enter length as a number (e.g., 60)")
        except Exception as e:
            print(f"Error: {e}")