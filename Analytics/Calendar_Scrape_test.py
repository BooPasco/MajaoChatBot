import os
from datetime import datetime, timedelta
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import pytz
from dotenv import load_dotenv

# Load environment variables
load_dotenv("/Users/chrispasco/Documents/MachineLearning/Majao_Chatbot/.env")

# Constants
SCOPES = ['https://www.googleapis.com/auth/calendar']
CREDENTIALS_FILE = '/Users/chrispasco/Documents/MachineLearning/Majao_Chatbot/CalendarMonitor/client_secret.json'
TOKEN_FILE = '/Users/chrispasco/Documents/MachineLearning/Majao_Chatbot/CalendarMonitor/token.json'
TEACHER_RATE_COP = int(os.getenv('TEACHER_RATE_COP')) # Payment rate per hour for external teachers
OWNER_TEACHERS = {'chris', 'sindi'}  # Teachers who don't get paid per hour (case-insensitive)

def get_calendar_service():
    creds = None
    if os.path.exists(TOKEN_FILE):
        print(f"Loading existing token from {TOKEN_FILE}")
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        if not os.path.exists(CREDENTIALS_FILE):
            raise FileNotFoundError(f"Credentials file not found at {CREDENTIALS_FILE}")
        print(f"No valid creds found, initiating OAuth flow with {CREDENTIALS_FILE}")
        try:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            flow.redirect_uri = 'http://localhost:8080/'
            creds = flow.run_local_server(port=8080)
            print(f"OAuth flow completed, saving new token to {TOKEN_FILE}")
            with open(TOKEN_FILE, 'w') as token:
                token.write(creds.to_json())
        except Exception as e:
            print(f"OAuth flow failed: {str(e)}")
            raise
    print(f"Calendar service initialized with creds: {creds is not None}")
    return build('calendar', 'v3', credentials=creds)

def get_all_calendars(service):
    print("Fetching all accessible calendars...")
    calendar_list = service.calendarList().list().execute()
    calendars = calendar_list.get('items', [])
    print(f"Found {len(calendars)} calendars:")
    for cal in calendars:
        print(f" - {cal['summary']} (ID: {cal['id']}, Color: {cal.get('backgroundColor', 'Not set')})")
    return calendars

def get_week_range(week_choice):
    tz = pytz.timezone('America/Bogota')
    now = datetime.now(tz)
    
    if week_choice == "last":
        now = now - timedelta(days=7)
    
    days_to_saturday = (now.weekday() - 5 + 7) % 7
    start_of_week = now - timedelta(days=days_to_saturday)
    start_of_week = start_of_week.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_week = start_of_week + timedelta(days=6, hours=23, minutes=59, seconds=59)
    
    return start_of_week, end_of_week

def get_week_events(service, calendar_id, calendar_name, start_of_week, end_of_week):
    start_utc = start_of_week.astimezone(pytz.UTC).isoformat()
    end_utc = end_of_week.astimezone(pytz.UTC).isoformat()
    
    print(f"Fetching events from '{calendar_name}' (ID: {calendar_id}) from {start_of_week.strftime('%Y-%m-%d %H:%M')} to {end_of_week.strftime('%Y-%m-%d %H:%M')} Bogota time")
    
    try:
        events_result = service.events().list(
            calendarId=calendar_id,
            timeMin=start_utc,
            timeMax=end_utc,
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        events = events_result.get('items', [])
        print(f"Successfully fetched {len(events)} events from '{calendar_name}'")
        return [(event, calendar_name) for event in events]
    except Exception as e:
        print(f"Error fetching events from '{calendar_name}': {str(e)}")
        return []

def calculate_event_duration(event):
    start_str = event['start'].get('dateTime', event['start'].get('date'))
    end_str = event['end'].get('dateTime', event['end'].get('date'))
    
    if 'date' in event['start']:
        print(f"Skipping all-day event: {event.get('summary', 'Untitled')}")
        return 0
    
    start = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
    end = datetime.fromisoformat(end_str.replace('Z', '+00:00'))
    
    duration = end - start
    hours = duration.total_seconds() / 3600
    print(f"Event '{event.get('summary', 'Untitled')}' duration: {hours:.2f} hours")
    return hours

def analyze_events(events_with_cal, is_majao):
    total_hours = 0
    total_classes = 0
    teacher_hours = {}
    teacher_payments = {}  # Track payments for external teachers
    
    for event, cal_name in events_with_cal:
        title = event.get('summary', 'Untitled')
        print(f"Processing event from {cal_name} ({'MAJAO' if is_majao else 'Casa Ritmo Laureles'}): {title}")
        
        duration = calculate_event_duration(event)
        if duration == 0:
            continue
        
        total_hours += duration
        total_classes += 1
        
        teachers = []
        title_lower = title.lower()
        
        # Existing teacher extraction logic...
        if ' y ' in title:
            parts = title.split(' y ', 1)
            teacher_part = parts[1].strip()
            teacher_part = teacher_part.replace('(', '').replace(')', '')
            if ' y ' in teacher_part:
                teachers = [t.strip().rstrip(':') for t in teacher_part.split(' y ')]
            elif '&' in teacher_part:
                teachers = [t.strip().rstrip(':') for t in teacher_part.split('&')]
            elif '+' in teacher_part:
                teachers = [t.strip().rstrip(':') for t in teacher_part.split('+')]
            elif ' and ' in teacher_part:
                teachers = [t.strip().rstrip(':') for t in teacher_part.split(' and ')]
            else:
                teachers = [teacher_part.split(' ', 1)[0].strip().rstrip(':')]
        elif ' con ' in title_lower:
            teacher_part = title.split(' con ', 1)[1].strip()
            if ' y ' in teacher_part:
                teachers = [t.strip().rstrip(':') for t in teacher_part.split(' y ')]
            elif '&' in teacher_part:
                teachers = [t.strip().rstrip(':') for t in teacher_part.split('&')]
            elif '+' in teacher_part:
                teachers = [t.strip().rstrip(':') for t in teacher_part.split('+')]
            elif ' and ' in teacher_part:
                teachers = [t.strip().rstrip(':') for t in teacher_part.split(' and ')]
            else:
                teachers = [teacher_part.split(' ', 1)[0].strip()]
        elif '&' in title or '+' in title:
            separator = '&' if '&' in title else '+'
            parts = title.split(separator, 1)
            teacher_part = parts[1].strip()
            if ' y ' in teacher_part:
                teachers = [t.strip().rstrip(':') for t in teacher_part.split(' y ')]
            elif '&' in teacher_part:
                teachers = [t.strip().rstrip(':') for t in teacher_part.split('&')]
            elif '+' in teacher_part:
                teachers = [t.strip().rstrip(':') for t in teacher_part.split('+')]
            elif ' and ' in teacher_part:
                teachers = [t.strip().rstrip(':') for t in teacher_part.split(' and ')]
            else:
                teachers = [teacher_part.split(' ', 1)[0].strip()]
        elif 'bootcamp' in title_lower and '-' in title:
            teacher_part = title.split('-', 1)[1].strip()
            if ' y ' in teacher_part:
                teachers = [t.strip().rstrip(':') for t in teacher_part.split(' y ')]
            elif '&' in teacher_part:
                teachers = [t.strip().rstrip(':') for t in teacher_part.split('&')]
            elif '+' in teacher_part:
                teachers = [t.strip().rstrip(':') for t in teacher_part.split('+')]
            elif ' and ' in teacher_part:
                teachers = [t.strip().rstrip(':') for t in teacher_part.split(' and ')]
            else:
                teachers = [teacher_part.split(' ', 1)[0].strip()]
        else:
            print(f"Skipping unparseable title in {cal_name} ({'MAJAO' if is_majao else 'Casa Ritmo Laureles'}): {title}")
            continue
        
        if is_majao:
            for teacher in teachers:
                teacher_lower = teacher.lower()
                teacher_hours[teacher] = teacher_hours.get(teacher, 0) + duration
                
                # Calculate payment for non-owner teachers
                if teacher_lower not in OWNER_TEACHERS:
                    payment = duration * TEACHER_RATE_COP
                    teacher_payments[teacher] = teacher_payments.get(teacher, 0) + payment
    
    return total_hours, total_classes, teacher_hours, teacher_payments

def print_analysis(start_date, casa_ritmo_hours, casa_ritmo_classes, majao_hours, majao_classes, majao_teacher_hours, majao_teacher_payments):
    end_date = start_date + timedelta(days=6)
    week_range = f"{start_date.strftime('%b %d')} to {end_date.strftime('%b %d, %Y')}"
    
    print(f"\n╔════════════════════════════════════════╗")
    print(f"║          WEEKLY CLASS ANALYSIS         ║")
    print(f"║           {week_range:^18}          ║")
    print(f"╚════════════════════════════════════════╝")
    
    print(f"\n┌────────────────────────────────────────┐")
    print(f"│        Casa Ritmo Laureles            │")
    print(f"├────────────────────────────────────────┤")
    print(f"│  Total Classes: {casa_ritmo_classes:>14}  │")
    print(f"│  Total Hours: {casa_ritmo_hours:>16.2f}  │")
    print(f"└────────────────────────────────────────┘")
    
    print(f"\n┌────────────────────────────────────────┐")
    print(f"│               MAJAO                   │")
    print(f"├────────────────────────────────────────┤")
    print(f"│  Total Classes: {majao_classes:>14}  │")
    print(f"│  Total Hours: {majao_hours:>16.2f}  │")
    print(f"└────────────────────────────────────────┘")
    
    if majao_teacher_hours:
        print(f"\n┌────────────────────────────────────────┐")
        print(f"│          Teacher Hours Breakdown       │")
        print(f"├────────────────────────────────────────┤")
        for teacher, hours in sorted(majao_teacher_hours.items()):
            print(f"│  {teacher:<20} {hours:>8.2f} hours  │")
        print(f"└────────────────────────────────────────┘")
    
    if majao_teacher_payments:
        print(f"\n┌────────────────────────────────────────┐")
        print(f"│          TEACHER PAYMENTS              │")
        print(f"├────────────────────────────────────────┤")
        total_payments = 0
        for teacher, payment in sorted(majao_teacher_payments.items()):
            hours = majao_teacher_hours.get(teacher, 0)
            if teacher.lower() not in OWNER_TEACHERS:
                print(f"│  Private {week_range:<18}         │")
                print(f"│  ∙ {teacher:<18} {hours:>4.1f}h × {TEACHER_RATE_COP:,}  │")
                print(f"│  {'TOTAL:':<23} COP {payment:>9,.0f}  │")
                print(f"├────────────────────────────────────────┤")
                total_payments += payment
        
        if total_payments > 0:
            print(f"│  {'GRAND TOTAL:':<23} COP {total_payments:>9,.0f}  │")
            print(f"└────────────────────────────────────────┘")
        else:
            print(f"│  No external teacher payments due      │")
            print(f"└────────────────────────────────────────┘")

def get_week_choice():
    tz = pytz.timezone('America/Bogota')
    now = datetime.now(tz)
    
    # Calculate date ranges for display
    current_start, current_end = get_week_range("current")
    last_start, last_end = get_week_range("last")
    
    print("\nWhich week do you want to see class details about?")
    print(f"1. Current week: {current_start.strftime('%b %d')} - {current_end.strftime('%b %d, %Y')}")
    print(f"2. Last week: {last_start.strftime('%b %d')} - {last_end.strftime('%b %d, %Y')}")
    
    while True:
        choice = input("Enter your choice (1 or 2): ").strip()
        if choice == "1":
            return "current"
        elif choice == "2":
            return "last"
        else:
            print("Invalid choice. Please enter 1 or 2.")

if __name__ == "__main__":
    print("Starting Calendar Analysis...")
    try:
        # Get user's week choice
        week_choice = get_week_choice()
        
        # Get calendar service
        service = get_calendar_service()
        
        # Get all calendars
        calendars = get_all_calendars(service)
        
        # Get the date range for selected week
        start_of_week, end_of_week = get_week_range(week_choice)
        
        # Split into MAJAO and Casa Ritmo Laureles
        majao_events = []
        casa_ritmo_events = []
        
        for cal in calendars:
            events = get_week_events(service, cal['id'], cal['summary'], start_of_week, end_of_week)
            if cal['summary'].lower() == 'majao':
                majao_events.extend(events)
            else:
                casa_ritmo_events.extend(events)
                
        # Analyze events
        majao_hours, majao_classes, majao_teacher_hours, majao_teacher_payments = analyze_events(majao_events, True) if majao_events else (0, 0, {}, {})
        casa_ritmo_hours, casa_ritmo_classes, _, _ = analyze_events(casa_ritmo_events, False) if casa_ritmo_events else (0, 0, {}, {})
        
        # Print results
        print_analysis(start_of_week, casa_ritmo_hours, casa_ritmo_classes, majao_hours, majao_classes, majao_teacher_hours, majao_teacher_payments)
        
        if not majao_events and any(cal['summary'].lower() == 'majao' for cal in calendars):
            print("Warning: MAJAO calendar found but no events fetched!")
        elif not any(cal['summary'].lower() == 'majao' for cal in calendars):
            print("Warning: MAJAO calendar not found!")
            
    except Exception as e:
        print(f"Script failed: {str(e)}")