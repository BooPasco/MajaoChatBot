import os
import json
import time
import sqlite3
import logging
from datetime import datetime, timedelta
import requests
from typing import List, Optional, Dict, Any
from dotenv import load_dotenv
from langchain_core.language_models import SimpleChatModel
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import pytz
import re
from flask import Flask, request
from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse
from Majao_Bot_Modules.Booking.CalendarScript import check_availability, schedule_event

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv("/Users/chrispasco/Documents/MachineLearning/Majao_Chatbot/.env")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_TOKEN")
if not all([DEEPSEEK_API_KEY, TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN]):
    raise ValueError("Missing required environment variables")

# SQLite setup
db_path = "/Users/chrispasco/Documents/MachineLearning/Majao_Chatbot/conversations.db"
conn = sqlite3.connect(db_path, check_same_thread=False)
cursor = conn.cursor()

# Create tables if they don't exist
cursor.executescript("""
    CREATE TABLE IF NOT EXISTS chats (
        user_name TEXT, 
        phone_number TEXT, 
        message TEXT, 
        is_bot INTEGER DEFAULT 0, 
        timestamp TEXT,
        temp_booking_details TEXT,
        PRIMARY KEY (phone_number, timestamp)
    );
    
    CREATE TABLE IF NOT EXISTS pending_notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        teacher_number TEXT,
        message TEXT,
        timestamp TEXT,
        delivered INTEGER DEFAULT 0
    );
    
    CREATE INDEX IF NOT EXISTS idx_booking_requests 
    ON chats (phone_number, is_bot, timestamp) 
    WHERE temp_booking_details IS NOT NULL;
""")
conn.commit()

# Twilio setup
twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
TWILIO_WHATSAPP_NUMBER = "whatsapp:+16012862526"
TWILIO_SMS_NUMBER = "+16012862526"  # Your Twilio phone number
TEACHER_NUMBER = "whatsapp:+573052622525"  # Chris's number


# Updated fact sheet
fact_sheet = {
    "about": "Majao Studio’s in the heart of Laureles, Medellín, near Carrera 70. We’re a space for creativity, freedom, and connection through dance—a place where every step tells a story and adapts to the moment. It’s not about perfection; it’s about expression.",
    "group_classes": {
        "days": "Tuesdays, Wednesdays, Thursdays",
        "styles": {
            "bacha_zouk": "Tuesdays: A fusion of Bachata’s rhythm and Zouk’s flow—fluid, creative, and open-ended. No rigid figures, just movement that breathes.",
            "bachata": "Thursdays: Focused on connection, adaptability, and smooth flow. Learn to dance with your partner, not just at them.",
            "zouk": "Wednesdays: Deep connection, fluid motion, and total freedom. It’s about feeling the music and letting go."
        }
    },
    "private_classes": {
        "availability": "Available all week with Medellín’s best instructors.",
        "styles": "Bachata, Zouk, Salsa, Porro, Kazumba—customized to your goals, whether it’s technique, confidence, or just fun.",
        "pricing": "90,000 COP per hour. Packages available: 4 sessions for 340,000 COP, 8 sessions for 650,000 COP, 10 sessions for 750,000 COP. Custom packages can be arranged (e.g., 6 sessions at 85,000 COP/hour, total 510,000 COP). Payment by cash or Bancolombia transfers only."
    },
    "intensives": "Boot camps every few weeks (2-3 hours, Saturdays)—options like contemporary Bachata/Zouk fusion, traditional Bachata roots, or men’s styling. Also, a four-week workshop Thursdays 7:00-8:30 PM on playful, spontaneous dance.",
    "majao_social": "Wednesdays: 7:30 PM Bachata class, followed by an 8:30 PM social—Bachata, Salsa, Zouk. Occasional shows or friendly competitions. Two rooms: upstairs (Bachata + Salsa), downstairs (Zouk).",
    "location": "Majao Studio, Laureles, Medellín: https://maps.app.goo.gl/Gf3iMTcZNYMeXPhF7",
    "q_and_a": {
        "What is MAJAO’s teaching philosophy?": "At MAJAO, we believe dance should feel natural, like a conversation rather than a script. Instead of focusing on memorization, we emphasize small, adaptable movements—building from the fundamentals to create freedom and play within the dance. Our approach encourages creativity and expression, allowing each dancer to develop their own unique style.",
        "How does MAJAO approach social dancing?": "Social dancing is about connection and enjoyment, not performance. It’s a shared experience where both partners contribute to the dance. We encourage dancers to be present, listen to their partner, and move with intention—always adaptable and engaged in a dynamic exchange. Every dance is a conversation, and our goal is to help dancers develop the skills to express themselves naturally.",
        "What makes MAJAO Studio special?": "MAJAO is about freedom in dance. We move away from choreographed sequences and focus on helping dancers find their own unique voice. Our goal is to create a space where dance is a form of artistic expression—fluid, personal, and limitless.",
        "What is your favorite dance style?": "Bachata is where I feel most at home, especially right now. Kizomba and Zouk are a close second for their fluidity and depth, offering a different kind of connection and expression."
    }
}


# DeepSeek LLM (unchanged from your original)
# DeepSeek LLM
class DeepSeekLLM(SimpleChatModel):
    model_name: str = "deepseek-chat"
    temperature: float = 0.5
    api_key: Optional[str] = None
    api_url: str = "https://api.deepseek.com/v1/chat/completions"

    def __init__(self, model_name="deepseek-chat", temperature=0.5, api_key=None):
        super().__init__(model_name=model_name, temperature=temperature, api_key=api_key)
        self.api_key = api_key or DEEPSEEK_API_KEY

    def _call(self, messages: List, stop: Optional[List[str]] = None, **kwargs) -> str:
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"}
        deepseek_messages = [{"role": "user" if isinstance(m, HumanMessage) else "assistant" if isinstance(m, AIMessage) else "system", "content": m.content} for m in messages]
        data = {"model": self.model_name, "messages": deepseek_messages, "temperature": self.temperature, **kwargs}
        try:
            start_time = time.time()
            response = requests.post(self.api_url, headers=headers, data=json.dumps(data))
            response.raise_for_status()
            elapsed = time.time() - start_time
            print(f"DeepSeek response time: {elapsed:.2f} seconds")
            return response.json()["choices"][0]["message"]["content"]
        except Exception as e:
            print(f"DeepSeek error: {e}")
            return "Something’s not working—let’s try that again."

    @property
    def _llm_type(self) -> str:
        return "deepseek"

    @property
    def _identifying_params(self) -> Dict[str, Any]:
        return {"model_name": self.model_name, "temperature": self.temperature}

llm = DeepSeekLLM()

# Helper functions
def parse_time(time_str):
    """Standardize time parsing"""
    time_str = time_str.replace(" ", "").lower()
    if "pm" in time_str and not time_str.startswith("12"):
        hour = int(time_str.replace("pm", "").split(":")[0]) + 12
        time_str = f"{hour:02d}:00"
    elif "am" in time_str:
        time_str = time_str.replace("am", "")
    if ":" not in time_str:
        time_str += ":00"
    return time_str

def extract_booking_details(message: str) -> Optional[Dict[str, str]]:
    """Extract booking details from user message"""
    booking_request = re.search(
        r'(tomorrow|next \w+day|\d{4}-\d{2}-\d{2}|friday|monday|tuesday|wednesday|thursday|saturday|sunday)\s+(\w+)\s+(?:at|around)?\s*(\d{1,2}(?::\d{2})?(?:\s*(?:am|pm))?)',
        message.lower()
    )
    
    if not booking_request:
        return None
        
    date_str, style, time_str = booking_request.groups()
    tz = pytz.timezone('America/Bogota')
    weekdays = {
        "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
        "friday": 4, "saturday": 5, "sunday": 6
    }
    
    # Date parsing logic
    if date_str == "tomorrow":
        date = datetime.now(tz) + timedelta(days=1)
        date_str = date.strftime('%Y-%m-%d')
    elif date_str.startswith("next "):
        day = date_str.split("next ")[1]
        days_ahead = (weekdays[day] - datetime.now(tz).weekday() + 7) % 7 or 7
        date = datetime.now(tz) + timedelta(days=days_ahead)
        date_str = date.strftime('%Y-%m-%d')
    elif date_str in weekdays:
        today = datetime.now(tz)
        days_ahead = (weekdays[date_str] - today.weekday() + 7) % 7 or 7
        date = today + timedelta(days=days_ahead)
        date_str = date.strftime('%Y-%m-%d')
    
    # Time parsing logic
    time_str = parse_time(time_str)
    
    return {
        'date': date_str,
        'time': time_str,
        'style': style,
        'status': 'pending_teacher_approval'
    }

def notify_teacher(booking_details: dict) -> bool:
    """Send booking notification to teacher with fallback to SMS"""
    teacher_msg = (
        f"📅 New Booking Request:\n"
        f"Student: {booking_details['user_name']}\n"
        f"Style: {booking_details['style']}\n"
        f"Date: {booking_details['date']}\n"
        f"Time: {booking_details['time']}\n\n"
        f"Reply with:\n"
        f"YES {booking_details['date']} {booking_details['time']} to confirm\n"
        f"NO to decline"
    )
    
    attempts = [
        {'channel': 'whatsapp', 'to': TEACHER_NUMBER, 'from': TWILIO_WHATSAPP_NUMBER},
        {'channel': 'sms', 'to': TEACHER_NUMBER.replace("whatsapp:", ""), 'from': TWILIO_SMS_NUMBER}
    ]
    
    for attempt in attempts:
        try:
            message = twilio_client.messages.create(
                body=teacher_msg,
                from_=attempt['from'],
                to=attempt['to']
            )
            logger.info(f"Sent via {attempt['channel']}, SID: {message.sid}")
            return True
        except Exception as e:
            logger.error(f"Failed {attempt['channel']} attempt: {str(e)}")
    
    logger.error("All delivery attempts failed")
    return False


# Flask app
app = Flask(__name__)

@app.route("/webhook", methods=["POST"])
def webhook():
    sender_number = request.values.get("From", "").replace("whatsapp:", "")
    incoming_msg = request.values.get("Body", "").strip()
    user_name = request.values.get("ProfileName", "User").capitalize()
    logger.info(f"Received from {sender_number} ({user_name}): {incoming_msg}")

    # Log incoming message
    conn.execute(
        "INSERT INTO chats (user_name, phone_number, message, is_bot, timestamp) VALUES (?, ?, ?, ?, ?)",
        (user_name, sender_number, incoming_msg, 0, datetime.now().isoformat())
    )
    conn.commit()

    # Handle teacher responses
    if sender_number == TEACHER_NUMBER.replace("whatsapp:", ""):
        return handle_teacher_response(incoming_msg, sender_number)

    # Handle student booking requests
    booking_details = extract_booking_details(incoming_msg)
    if booking_details:
        return handle_booking_request(user_name, sender_number, incoming_msg, booking_details)

    # Handle non-booking messages with LLM
    return handle_regular_message(user_name, sender_number, incoming_msg)

def handle_teacher_response(incoming_msg: str, sender_number: str):
    """Process messages from the teacher"""
    # Teacher confirming a booking
    if "yes" in incoming_msg.lower():
        confirmation_match = re.search(r'yes (\d{4}-\d{2}-\d{2}) (\d{2}:\d{2})', incoming_msg.lower())
        if confirmation_match:
            date_str, time_str = confirmation_match.groups()
            
            # Find matching pending request
            cursor.execute("""
                SELECT temp_booking_details FROM chats 
                WHERE temp_booking_details LIKE ? 
                AND is_bot = 2
                ORDER BY timestamp DESC LIMIT 1
            """, (f'%"date":"{date_str}","time":"{time_str}%',))
            
            result = cursor.fetchone()
            if result:
                booking_details = json.loads(result[0])
                if booking_details.get('status') == 'pending_teacher_approval':
                    # Update status to awaiting email
                    booking_details['status'] = 'awaiting_email'
                    conn.execute("""
                        UPDATE chats SET temp_booking_details = ?
                        WHERE timestamp = (
                            SELECT timestamp FROM chats 
                            WHERE temp_booking_details LIKE ?
                            AND is_bot = 2
                            ORDER BY timestamp DESC LIMIT 1
                        )
                    """, (json.dumps(booking_details), f'%"date":"{date_str}","time":"{time_str}%'))
                    conn.commit()
                    
                    reply = "What's the student's email to send a calendar invite?"
                    send_message(TEACHER_NUMBER, reply)
                    return str(MessagingResponse())
    
    # Teacher providing student email
    elif re.search(r'[\w\.-]+@[\w\.-]+', incoming_msg):
        # Find the most recent booking awaiting email
        cursor.execute("""
            SELECT temp_booking_details FROM chats 
            WHERE temp_booking_details LIKE '%"status":"awaiting_email"%'
            AND is_bot = 2
            ORDER BY timestamp DESC LIMIT 1
        """)
        result = cursor.fetchone()
        
        if result:
            booking_details = json.loads(result[0])
            student_email = re.search(r'[\w\.-]+@[\w\.-]+', incoming_msg).group(0)
            
            # Complete the booking
            date_str = booking_details['date']
            time_str = booking_details['time']
            style = booking_details['style']
            user_name = booking_details['user_name']
            user_number = booking_details['user_number']
            
            end_hour = int(time_str.split(':')[0]) + 1
            end_time = f"{end_hour:02d}:{time_str.split(':')[1]}"
            
            check = check_availability(time_str, end_time, date_str)
            if check['is_free']:
                booking_result = book_class(
                    check['start'], 
                    check['end'], 
                    style, 
                    user_name, 
                    "Chris", 
                    student_email
                )
                
                # Update status to booked
                booking_details['status'] = 'booked'
                booking_details['student_email'] = student_email
                conn.execute("""
                    UPDATE chats SET temp_booking_details = ?
                    WHERE timestamp = (
                        SELECT timestamp FROM chats 
                        WHERE temp_booking_details LIKE '%"status":"awaiting_email"%'
                        AND is_bot = 2
                        ORDER BY timestamp DESC LIMIT 1
                    )
                """, (json.dumps(booking_details),))
                conn.commit()
                
                # Notify student
                student_reply = f"Hi {user_name}, your booking is confirmed! Invite sent to {student_email}."
                send_message(f"whatsapp:{user_number}", student_reply)
            else:
                student_reply = f"Hi {user_name}, sorry, that slot's no longer available. Let's pick another time."
                send_message(f"whatsapp:{user_number}", student_reply)
            
            return str(MessagingResponse())
    
    # Default response for unrecognized teacher messages
    send_message(TEACHER_NUMBER, "I didn't understand that. Please reply with 'yes DATE TIME' or provide a student email.")
    return str(MessagingResponse())

def handle_booking_request(user_name: str, sender_number: str, incoming_msg: str, booking_details: dict):
    """Process booking requests from students"""
    # Check availability
    end_hour = int(booking_details['time'].split(':')[0]) + 1
    end_time = f"{end_hour:02d}:{booking_details['time'].split(':')[1]}"
    check = check_availability(booking_details['time'], end_time, booking_details['date'])
    
    if check['is_free']:
        # Store booking request
        full_booking_details = {
            **booking_details,
            'user_name': user_name,
            'user_number': sender_number
        }
        
        conn.execute("""
            INSERT INTO chats 
            (user_name, phone_number, message, is_bot, timestamp, temp_booking_details) 
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            user_name, 
            sender_number, 
            f"Booking request: {booking_details['style']} on {booking_details['date']} at {booking_details['time']}", 
            2,  # Flag for booking request
            datetime.now().isoformat(),
            json.dumps(full_booking_details)
        ))
        conn.commit()
        
        # Notify teacher
        if not notify_teacher(full_booking_details):
            # Store failed notification
            conn.execute("""
                INSERT INTO pending_notifications 
                (teacher_number, message, timestamp)
                VALUES (?, ?, ?)
            """, (TEACHER_NUMBER, json.dumps(full_booking_details), datetime.now().isoformat()))
            conn.commit()
        
        # Reply to student
        reply = (
            f"Hi {user_name}, I've sent your {booking_details['style']} class request "
            f"for {booking_details['date']} at {booking_details['time']} to the teacher. "
            f"I'll get back to you soon with confirmation!"
        )
    else:
        reply = f"Hi {user_name}, sorry, that time slot is already taken. Please suggest another time."
    
    send_message(f"whatsapp:{sender_number}", reply)
    log_bot_message(user_name, sender_number, reply)
    return str(MessagingResponse())

def handle_regular_message(user_name: str, sender_number: str, incoming_msg: str):
    """Handle non-booking related messages"""
    # Updated system prompt
    system_prompt = SystemMessage(
    content=(
        f"Hi, thanks for reaching out to us at Majao. We’re here to assist with class options, scheduling, or any dance-related questions "
        f"you have. Our responses are clear, professional, and welcoming—think of us as your guide to everything Majao.\n\n"

        f"Here’s the full rundown:\n{json.dumps(fact_sheet, indent=2)}\n\n"

        f"We aim to make this easy and helpful. When responding:\n"
        f"- We’ll use your name if you share it.\n"
        f"- We’ll keep info structured and simple—bullets or short sentences.\n"
        f"- We’ll stay professional but warm—no slang or over-the-top casual stuff.\n"
        f"- For private lessons, we’ll ask about your goals and availability to find the best fit.\n"
        f"- For scheduling, we’ll suggest times and confirm what works for you. If they request multiple classes, ask about other preferred dates/times to book together.\n"
        f"- We’ll keep it concise—no fluff, just what you need. Only mention payment (cash or Bancolombia transfers) if they ask or refer to it.\n\n"

        f"What can we help you with today?"
    )
)
    
    # Load chat history
    cursor.execute("""
        SELECT message, is_bot FROM chats 
        WHERE phone_number = ? 
        ORDER BY timestamp DESC 
        LIMIT 10
    """, (sender_number,))
    
    history = []
    for row in reversed(cursor.fetchall()):  # Reverse to maintain chronological order
        history.append(HumanMessage(content=row[0]) if row[1] == 0 else AIMessage(content=row[0]))
    
    messages = [system_prompt] + history + [HumanMessage(content=incoming_msg)]
    reply = llm._call(messages)
    
    # Truncate long replies
    if len(reply) > 1500:
        reply = reply[:1500] + "… (shortened)"
    
    send_message(f"whatsapp:{sender_number}", reply)
    log_bot_message(user_name, sender_number, reply)
    return str(MessagingResponse())

def send_message(to: str, body: str) -> bool:
    """Send message with error handling"""
    try:
        message = twilio_client.messages.create(
            body=body,
            from_=TWILIO_WHATSAPP_NUMBER,
            to=to
        )
        logger.info(f"Message sent to {to}, SID: {message.sid}")
        return True
    except Exception as e:
        logger.error(f"Failed to send to {to}: {str(e)}")
        return False

def log_bot_message(user_name: str, phone_number: str, message: str):
    """Log bot responses to database"""
    conn.execute(
        "INSERT INTO chats (user_name, phone_number, message, is_bot, timestamp) VALUES (?, ?, ?, ?, ?)",
        (user_name, phone_number, message, 1, datetime.now().isoformat())
    )
    conn.commit()

if __name__ == "__main__":
    logger.info("Starting MajaoBot with Twilio WhatsApp API...")
    app.run(host="0.0.0.0", port=5000)